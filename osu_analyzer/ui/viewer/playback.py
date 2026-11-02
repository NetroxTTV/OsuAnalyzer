"""The viewer's clock: current time, play / pause, speed and the music.
While the music plays it is the clock, so the picture can never drift away from it."""

import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from ...core import MOD_NC, settings

VOLUME_GAIN = 0.5   # slider at 100 % = half of full scale (full scale is too loud)


class Playback(QObject):
    timeChanged = Signal(float)
    playingChanged = Signal(bool)
    audioStatusChanged = Signal(str)
    _audioReady = Signal(int, object, object)   # token, AudioPlayer, error (from a worker thread)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = None
        self.t = 0.0
        self.playing = False
        self.speed = 1.0
        self.volume = settings.get("volume", 0.5)     # effective (0 when muted)
        self.player = None
        self._token = 0
        self._last = 0.0
        self._audio_name = ""
        self._audio_status = ""
        self._timer = QTimer(self, interval=8, timerType=Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._audioReady.connect(self._audio_ready)
        self._remembered = self.volume
        self._save = QTimer(self, singleShot=True, interval=600)
        self._save.timeout.connect(lambda: settings.update(volume=self._remembered))

    # ------------------------------------------------------------ loading --

    def load(self, scene, at=None):
        self.pause()
        self.scene = scene
        self._load_audio(scene.beatmap.audio)
        self.seek(at if at is not None else scene.t0)

    def clear(self):
        self.pause()
        self.scene = None
        self._close_audio()
        self._set_status("")

    def shutdown(self):
        self._timer.stop()
        self._close_audio()

    # --------------------------------------------------------------- music --

    def _set_status(self, text):
        if text != self._audio_status:
            self._audio_status = text
            self.audioStatusChanged.emit(text)

    def _close_audio(self):
        if self.player:
            self.player.close()
            self.player = None
        self._token += 1

    def _load_audio(self, path):
        self._close_audio()
        if not path or not path.exists():
            self._set_status("Audio file not found")
            return
        self._audio_name = path.name
        self._set_status("Loading music...")
        token = self._token

        def work():
            try:
                from ...audio import AudioPlayer
                self._audioReady.emit(token, AudioPlayer(path, self.volume * VOLUME_GAIN), None)
            except Exception as e:  # noqa: BLE001 - no output device, unknown format...
                self._audioReady.emit(token, None, e)

        threading.Thread(target=work, daemon=True).start()

    def _audio_ready(self, token, player, error):
        if token != self._token:
            if player:
                player.close()
            return
        if error or not player:
            self._set_status(f"No sound ({error})")
            return
        self.player = player
        player.volume = self.volume * VOLUME_GAIN
        self._apply_rate()
        self._update_status()
        if self.playing:
            player.play(self.t)

    def _update_status(self):
        if self.player:
            ready = self.player.stretch_ready()
            self._set_status(self._audio_name + ("  ·  preparing pitch..." if not ready else ""))

    def set_volume(self, effective, remembered):
        """effective = what is heard (0 when muted); remembered = the slider position to save."""
        self.volume = effective
        if self.player:
            self.player.volume = effective * VOLUME_GAIN
        self._remembered = remembered
        self._save.start()

    # ------------------------------------------------------------ control --

    @property
    def rate(self):
        return (self.scene.replay.rate if self.scene else 1.0) * self.speed

    def set_speed(self, speed):
        self.speed = speed
        self._apply_rate()
        self._update_status()

    def _apply_rate(self):
        if self.player and self.scene:
            nc = bool(self.scene.replay.mods & MOD_NC)
            self.player.set_rate(self.rate, keep_pitch=not nc)
            if self.playing:
                self.player.seek(self.t)

    def toggle(self):
        if self.scene is None:
            return
        self.playing = not self.playing
        if self.playing and self.t >= self.scene.t1 - 1:
            self.t = self.scene.t0
        self._last = time.perf_counter()
        if self.player:
            if self.playing:
                self.player.play(self.t)
            else:
                self.player.pause()
        if self.playing:
            self._timer.start()
        else:
            self._timer.stop()
        self.playingChanged.emit(self.playing)

    def pause(self):
        if self.playing:
            self.toggle()

    def play_from(self, t):
        self.seek(t)
        if not self.playing:
            self.toggle()

    def seek(self, t):
        if self.scene is None:
            return
        self.t = min(max(self.scene.t0, t), self.scene.t1)
        if self.player:
            self.player.seek(self.t)
        self.timeChanged.emit(self.t)

    def step(self, frames):
        """Move by frames of 60 fps (real time)."""
        if self.scene:
            self.pause()
            self.seek(self.t + frames * 1000 / 60 * self.scene.replay.rate)

    def next_miss(self):
        t = self.scene.next_miss(self.t) if self.scene else None
        if t is not None:
            self.seek(t)

    def prev_miss(self):
        t = self.scene.prev_miss(self.t) if self.scene else None
        if t is not None:
            self.seek(t)

    def _tick(self):
        if not (self.playing and self.scene):
            return
        now = time.perf_counter()
        if self.player and self.player.playing:
            self.t = self.player.position()
            self._update_status()
        else:
            self.t += (now - self._last) * 1000 * self.rate
        self._last = now
        if self.t >= self.scene.t1:
            self.t = self.scene.t1
            self.toggle()
        self.timeChanged.emit(self.t)
