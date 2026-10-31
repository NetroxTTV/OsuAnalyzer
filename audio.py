"""
Beatmap music playback for the replay viewer.

The song is decoded once to float32 PCM and streamed through a sounddevice
callback. The playback position (in map time) lives here and the viewer reads it,
so the music is the clock and the picture can never drift away from it.

Speed: NC (and anything without a stretched buffer yet) is resampled, which shifts
the pitch like nightcore. Other rates are time-stretched with WSOLA in a background
thread so the pitch stays the same, as DT/HT do in osu!.
"""

import threading
import time

import numpy as np

SAMPLE_RATE = 44100


class AudioPlayer:
    def __init__(self, path, volume=0.5):
        import miniaudio
        import sounddevice as sd

        d = miniaudio.decode_file(str(path), output_format=miniaudio.SampleFormat.FLOAT32,
                                  nchannels=2, sample_rate=SAMPLE_RATE)
        self.src = np.frombuffer(d.samples, dtype=np.float32).reshape(-1, 2)
        self.sr = SAMPLE_RATE
        self.volume = volume
        self.rate = 1.0
        self.keep_pitch = True
        self.playing = False
        self._pos_ms = 0.0       # map time of the next sample the callback will write
        self._wall = time.perf_counter()
        self._stretched = {}     # rate -> stretched (N, 2) buffer
        self._pending = set()
        self._lock = threading.Lock()
        self.stream = sd.OutputStream(samplerate=self.sr, channels=2, dtype="float32",
                                      latency="low", callback=self._callback)
        self.stream.start()

    # ----------------------------------------------------------- control --

    @property
    def latency_ms(self):
        try:
            return float(self.stream.latency) * 1000
        except Exception:  # noqa: BLE001
            return 0.0

    def position(self):
        """Map time (ms) currently coming out of the speakers."""
        with self._lock:
            pos, wall, rate, playing = self._pos_ms, self._wall, self.rate, self.playing
        if not playing:
            return pos
        # Callbacks arrive in blocks: extrapolate between them, minus what is still buffered
        return pos + (time.perf_counter() - wall) * 1000 * rate - self.latency_ms * rate

    def seek(self, ms):
        with self._lock:
            self._pos_ms = ms + (self.latency_ms * self.rate if self.playing else 0)
            self._wall = time.perf_counter()

    def play(self, ms):
        with self._lock:
            self.playing = True
            self._pos_ms = ms + self.latency_ms * self.rate
            self._wall = time.perf_counter()

    def pause(self):
        with self._lock:
            self.playing = False

    def set_rate(self, rate, keep_pitch=True):
        with self._lock:
            self.rate = rate
            self.keep_pitch = keep_pitch
        key = round(rate, 4)
        if keep_pitch and abs(rate - 1) > 1e-6 and key not in self._stretched and key not in self._pending:
            self._pending.add(key)
            threading.Thread(target=self._stretch, args=(key,), daemon=True).start()

    def stretch_ready(self):
        key = round(self.rate, 4)
        return not self.keep_pitch or abs(self.rate - 1) < 1e-6 or key in self._stretched

    def close(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------- internals --

    def _stretch(self, key):
        from audiotsm import wsola
        from audiotsm.io.array import ArrayReader, ArrayWriter
        w = ArrayWriter(2)
        wsola(2, speed=key).run(ArrayReader(np.ascontiguousarray(self.src.T)), w)
        self._stretched[key] = np.ascontiguousarray(w.data.T.astype(np.float32))
        self._pending.discard(key)

    @staticmethod
    def _slice(buf, start, frames):
        """frames samples from buf starting at integer index start, zero-padded outside."""
        out = np.zeros((frames, 2), dtype=np.float32)
        a, b = max(start, 0), min(start + frames, len(buf))
        if b > a:
            out[a - start:b - start] = buf[a:b]
        return out

    def _callback(self, out, frames, _time, _status):
        with self._lock:
            if not self.playing:
                out.fill(0)
                self._wall = time.perf_counter()
                return
            rate, pos = self.rate, self._pos_ms
            self._pos_ms += frames / self.sr * 1000 * rate
            self._wall = time.perf_counter()
        key = round(rate, 4)
        if abs(rate - 1) < 1e-6:
            chunk = self._slice(self.src, int(round(pos / 1000 * self.sr)), frames)
        elif self.keep_pitch and key in self._stretched:
            chunk = self._slice(self._stretched[key], int(round(pos / 1000 * self.sr / rate)), frames)
        else:
            # Resample on the fly (pitch follows the speed)
            idx = pos / 1000 * self.sr + np.arange(frames) * rate
            i0 = np.floor(idx).astype(np.int64)
            f = (idx - i0).astype(np.float32)[:, None]
            a = self._slice(self.src, int(i0[0]), int(i0[-1] - i0[0]) + 2)
            rel = i0 - i0[0]
            chunk = a[rel] * (1 - f) + a[rel + 1] * f
        out[:] = chunk * self.volume
