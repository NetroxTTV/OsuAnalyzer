"""Replay (.osr) parsing, mods and key presses."""

import bisect
import lzma
import struct
from dataclasses import dataclass
from pathlib import Path

MOD_NAMES = [
    (1, "NF"), (2, "EZ"), (4, "TD"), (8, "HD"), (16, "HR"), (32, "SD"),
    (64, "DT"), (128, "RX"), (256, "HT"), (512, "NC"), (1024, "FL"),
    (2048, "AT"), (4096, "SO"), (8192, "AP"), (16384, "PF"),
]
MOD_EZ, MOD_HR, MOD_DT, MOD_HT, MOD_NC = 2, 16, 64, 256, 512

KEY_LEFT = 1 | 4    # M1 | K1
KEY_RIGHT = 2 | 8   # M2 | K2


class _Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

    def _unpack(self, fmt):
        v = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += struct.calcsize(fmt)
        return v

    def byte(self):
        return self._unpack("<B")

    def short(self):
        return self._unpack("<H")

    def int(self):
        return self._unpack("<i")

    def long(self):
        return self._unpack("<q")

    def uleb(self):
        result = shift = 0
        while True:
            b = self.byte()
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result
            shift += 7

    def string(self):
        flag = self.byte()
        if flag == 0x00:
            return ""
        if flag != 0x0B:
            raise ValueError(f"bad string marker 0x{flag:02x} at offset {self.p - 1}")
        n = self.uleb()
        s = self.d[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        return s

    def raw(self, n):
        b = self.d[self.p:self.p + n]
        self.p += n
        return b


@dataclass
class Replay:
    path: Path
    mode: int
    version: int
    beatmap_md5: str
    player: str
    n300: int
    n100: int
    n50: int
    nmiss: int
    max_combo: int
    mods: int
    frames: list  # (time, x, y, keys)

    @property
    def mod_string(self):
        names = [n for bit, n in MOD_NAMES if self.mods & bit]
        if "NC" in names:
            names.remove("DT")
        if "PF" in names:
            names.remove("SD")
        return "".join(names) or "NM"

    @property
    def rate(self):
        if self.mods & (MOD_DT | MOD_NC):
            return 1.5
        if self.mods & MOD_HT:
            return 0.75
        return 1.0


def read_replay(path) -> Replay:
    path = Path(path)
    r = _Reader(path.read_bytes())
    mode = r.byte()
    version = r.int()
    beatmap_md5 = r.string()
    player = r.string()
    r.string()  # replay md5
    n300, n100, n50, _geki, _katu, nmiss = (r.short() for _ in range(6))
    r.int()  # score
    max_combo = r.short()
    r.byte()  # perfect
    mods = r.int()
    r.string()  # life bar graph
    r.long()  # timestamp
    length = r.int()
    compressed = r.raw(length)

    text = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(compressed)
    text = text.decode("ascii", "replace")

    frames = []
    t = 0
    for chunk in text.split(","):
        parts = chunk.split("|")
        if len(parts) < 4:
            continue
        try:
            w = int(parts[0])
            if w == -12345:  # RNG seed frame
                continue
            t += w
            frames.append((t, float(parts[1]), float(parts[2]), int(float(parts[3]))))
        except ValueError:
            continue

    return Replay(path, mode, version, beatmap_md5, player,
                  n300, n100, n50, nmiss, max_combo, mods, frames)


def key_presses(frames):
    """Rising edges of either key: [(time, x, y)]."""
    presses, prev = [], 0
    for t, x, y, keys in frames:
        for mask in (KEY_LEFT, KEY_RIGHT):
            if keys & mask and not prev & mask:
                presses.append((t, x, y))
        prev = keys
    return presses


def key_segments(frames, mask):
    """[(press, release)] while `mask` is held."""
    segs, down = [], None
    for t, _x, _y, keys in frames:
        if keys & mask and down is None:
            down = t
        elif not keys & mask and down is not None:
            segs.append((down, t))
            down = None
    if down is not None and frames:
        segs.append((down, frames[-1][0]))
    return segs


class CursorTrack:
    """Cursor position at any time, linearly interpolated between replay frames."""

    def __init__(self, frames):
        self.frames = frames
        self.times = [f[0] for f in frames]

    def at(self, t):
        """(x, y, keys) at time t."""
        frames = self.frames
        if not frames:
            return 256.0, 192.0, 0
        k = bisect.bisect_right(self.times, t)
        if k <= 0:
            return frames[0][1], frames[0][2], frames[0][3]
        if k >= len(frames):
            return frames[-1][1], frames[-1][2], frames[-1][3]
        t0, x0, y0, keys = frames[k - 1]
        t1, x1, y1, _ = frames[k]
        f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
        return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, keys

    @property
    def end(self):
        return self.times[-1] if self.times else 0
