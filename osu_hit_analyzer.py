#!/usr/bin/env python3
"""
osu! hit-position analyzer.

Reads an osu!standard replay (.osr) together with its beatmap (.osu), finds
the key press that hit each circle (and slider head), and records where the
cursor was relative to the object's centre at that instant.  Every hit is then
drawn inside one big normalised circle (edge = the real hit-circle radius) so
you can see your average hit position, spread, and early/late timing.

Usage:
    python osu_hit_analyzer.py                       # file pickers
    python osu_hit_analyzer.py replay.osr            # beatmap found automatically
    python osu_hit_analyzer.py a.osr b.osr --save out.png
    python osu_hit_analyzer.py replay.osr --beatmap map.osu --frame movement
"""

import argparse
import bisect
import hashlib
import json
import lzma
import math
import os
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "1.0.0"

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

MOD_NAMES = [
    (1, "NF"), (2, "EZ"), (4, "TD"), (8, "HD"), (16, "HR"), (32, "SD"),
    (64, "DT"), (128, "RX"), (256, "HT"), (512, "NC"), (1024, "FL"),
    (2048, "AT"), (4096, "SO"), (8192, "AP"), (16384, "PF"),
]
MOD_EZ, MOD_HR, MOD_DT, MOD_HT, MOD_NC = 2, 16, 64, 256, 512

KEY_LEFT = 1 | 4    # M1 | K1
KEY_RIGHT = 2 | 8   # M2 | K2

PLAYFIELD_H = 384
STACK_DISTANCE = 3
EARLY_MISS_WINDOW = 400  # ms: pressing earlier than the 50 window but inside this = miss

DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "osu-hit-analyzer"
INDEX_PATH = DATA_DIR / "beatmap_index.json"
SETTINGS_PATH = DATA_DIR / "settings.json"


def load_settings():
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(**values):
    """Merge values into the settings file (other keys are kept)."""
    data = load_settings()
    data.update(values)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Replay (.osr) parsing
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Beatmap (.osu) parsing and slider paths
# --------------------------------------------------------------------------- #

@dataclass
class HitObject:
    kind: str           # "circle" | "slider" | "spinner"
    time: float
    pos: tuple
    end_time: float = 0.0
    end_pos: tuple = None        # slider end, repeats taken into account
    path_end_pos: tuple = None   # slider path at progress 1 (no repeats)
    stack: int = 0
    stacked_pos: tuple = None
    path: list = None            # slider body polyline (unstacked), cut to the slider length
    slides: int = 1
    combo_number: int = 1
    combo_index: int = 0


@dataclass
class Beatmap:
    path: Path
    version: int
    title: str
    artist: str
    diff_name: str
    cs: float
    od: float
    ar: float
    stack_leniency: float
    objects: list = field(default_factory=list)
    colours: list = field(default_factory=list)   # combo colours as (r, g, b)
    audio: Path = None                              # the song file, if present
    background: Path = None                         # background image, if present


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _bezier(points):
    """Sample a single bezier segment."""
    if len(points) == 1:
        return [points[0]]
    poly_len = sum(_dist(points[i], points[i + 1]) for i in range(len(points) - 1))
    steps = int(min(1000, max(16, poly_len / 2)))
    out = []
    for s in range(steps + 1):
        t = s / steps
        pts = list(points)
        while len(pts) > 1:
            pts = [(pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t,
                    pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t) for i in range(len(pts) - 1)]
        out.append(pts[0])
    return out


def _bezier_path(points):
    """Bezier with red anchors (repeated points split segments)."""
    out, seg = [], [points[0]]
    for p in points[1:]:
        if p == seg[-1]:
            out += _bezier(seg)
            seg = [p]
        else:
            seg.append(p)
    out += _bezier(seg)
    return out


def _catmull_path(points):
    out = []
    n = len(points)
    for i in range(n - 1):
        v1 = points[i - 1] if i > 0 else points[i]
        v2 = points[i]
        v3 = points[i + 1] if i + 1 < n else (2 * v2[0] - v1[0], 2 * v2[1] - v1[1])
        v4 = points[i + 2] if i + 2 < n else (2 * v3[0] - v2[0], 2 * v3[1] - v2[1])
        for c in range(50):
            t = c / 50
            t2, t3 = t * t, t * t * t
            out.append(tuple(
                0.5 * (2 * v2[k] + (-v1[k] + v3[k]) * t
                       + (2 * v1[k] - 5 * v2[k] + 4 * v3[k] - v4[k]) * t2
                       + (-v1[k] + 3 * v2[k] - 3 * v3[k] + v4[k]) * t3)
                for k in (0, 1)))
    out.append(points[-1])
    return out


def _circle_path(a, b, c):
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-3:
        return None
    asq, bsq, csq = a[0] ** 2 + a[1] ** 2, b[0] ** 2 + b[1] ** 2, c[0] ** 2 + c[1] ** 2
    cx = (asq * (b[1] - c[1]) + bsq * (c[1] - a[1]) + csq * (a[1] - b[1])) / d
    cy = (asq * (c[0] - b[0]) + bsq * (a[0] - c[0]) + csq * (b[0] - a[0])) / d
    r = math.hypot(a[0] - cx, a[1] - cy)
    t0 = math.atan2(a[1] - cy, a[0] - cx)
    t1 = math.atan2(c[1] - cy, c[0] - cx)
    while t1 < t0:
        t1 += 2 * math.pi
    direction, rng = 1, t1 - t0
    ortho = (c[1] - a[1], -(c[0] - a[0]))
    if ortho[0] * (b[0] - a[0]) + ortho[1] * (b[1] - a[1]) < 0:
        direction, rng = -1, 2 * math.pi - rng
    if r > 0.1:
        n = int(min(1000, max(2, math.ceil(rng / (2 * math.acos(max(-1.0, 1 - 0.1 / r)))))))
    else:
        n = 2
    return [(cx + r * math.cos(t0 + direction * rng * i / (n - 1)),
             cy + r * math.sin(t0 + direction * rng * i / (n - 1))) for i in range(n)]


def _point_at_length(poly, length):
    """Point at `length` along the polyline (extends the last segment if needed)."""
    if len(poly) == 1:
        return poly[0]
    walked = 0.0
    for i in range(len(poly) - 1):
        seg = _dist(poly[i], poly[i + 1])
        if walked + seg >= length and seg > 0:
            f = (length - walked) / seg
            return (poly[i][0] + (poly[i + 1][0] - poly[i][0]) * f,
                    poly[i][1] + (poly[i + 1][1] - poly[i][1]) * f)
        walked += seg
    a, b = poly[-2], poly[-1]
    seg = _dist(a, b)
    if seg == 0:
        return b
    f = (length - walked) / seg
    return (b[0] + (b[0] - a[0]) * f, b[1] + (b[1] - a[1]) * f)


def slider_path(curve_type, points, length):
    """Slider body as a polyline, cut (or extended) to the slider's pixel length."""
    if curve_type == "P" and len(points) == 3:
        poly = _circle_path(*points) or _bezier_path(points)
    elif curve_type == "L":
        poly = list(points)
    elif curve_type == "C":
        poly = _catmull_path(points)
    else:
        poly = _bezier_path(points)
    if length is None or length <= 0 or len(poly) < 2:
        return poly
    out, walked = [poly[0]], 0.0
    for i in range(len(poly) - 1):
        seg = _dist(poly[i], poly[i + 1])
        if walked + seg >= length and seg > 0:
            f = (length - walked) / seg
            out.append((poly[i][0] + (poly[i + 1][0] - poly[i][0]) * f,
                        poly[i][1] + (poly[i + 1][1] - poly[i][1]) * f))
            return out
        walked += seg
        out.append(poly[i + 1])
    out[-1] = _point_at_length(poly, length)  # path shorter than the length: extend
    return out


def slider_path_end(curve_type, points, length):
    return slider_path(curve_type, points, length)[-1]


def _beat_info(timing, t):
    reds = [tp for tp in timing if tp[2]]
    beat_len = reds[0][1] if reds else 500.0
    sv = 1.0
    for time, bl, uninherited in timing:
        if time > t:
            break
        if uninherited:
            beat_len, sv = bl, 1.0
        elif bl < 0:
            sv = min(10.0, max(0.1, -100.0 / bl))
    return beat_len, sv


def read_beatmap(path, hard_rock=False, easy=False) -> Beatmap:
    path = Path(path)
    version = 14
    section = None
    kv = {}
    timing = []
    raw_objects = []
    colours = []
    background = None
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            m = re.match(r"osu file format v(\d+)", line)
            if m:
                version = int(m.group(1))
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if section in ("General", "Metadata", "Difficulty"):
                k, _, v = line.partition(":")
                kv[k.strip()] = v.strip()
            elif section == "Events" and background is None:
                ev = line.split(",")
                if len(ev) >= 3 and ev[0].strip() in ("0", "Background"):
                    background = ev[2].strip().strip('"')
            elif section == "Colours":
                k, _, v = line.partition(":")
                if k.strip().startswith("Combo"):
                    try:
                        colours.append(tuple(int(c) for c in v.split(",")[:3]))
                    except ValueError:
                        pass
            elif section == "TimingPoints":
                p = line.split(",")
                try:
                    bl = float(p[1])
                    uninherited = p[6].strip() == "1" if len(p) >= 7 else bl > 0
                    timing.append((float(p[0]), bl, uninherited))
                except (ValueError, IndexError):
                    pass
            elif section == "HitObjects":
                raw_objects.append(line.split(","))

    if kv.get("Mode", "0") != "0":
        raise ValueError(f"{path.name} is not an osu!standard beatmap")

    def num(key, default):
        try:
            return float(kv[key])
        except (KeyError, ValueError):
            return default

    cs = num("CircleSize", 5)
    od = num("OverallDifficulty", 5)
    ar = num("ApproachRate", od)
    if hard_rock:
        cs, od, ar = min(10, cs * 1.3), min(10, od * 1.4), min(10, ar * 1.4)
    elif easy:
        cs, od, ar = cs * 0.5, od * 0.5, ar * 0.5

    slider_mult = num("SliderMultiplier", 1.4)
    timing.sort(key=lambda tp: tp[0])

    def flip(p):
        return (p[0], PLAYFIELD_H - p[1]) if hard_rock else p

    objects = []
    combo_number, combo_index, force_new = 0, 0, True
    for p in raw_objects:
        try:
            pos = flip((float(p[0]), float(p[1])))
            t = float(p[2])
            typ = int(p[3])
        except (ValueError, IndexError):
            continue
        if not typ & 8:  # combo numbering (spinners start a new combo after them)
            if (typ & 4 or force_new) and objects:
                combo_index += 1 + ((typ >> 4) & 7)
                combo_number = 0
            combo_number += 1
            force_new = False
        else:
            force_new = True
        if typ & 1:
            objects.append(HitObject("circle", t, pos, t, pos, pos,
                                     combo_number=combo_number, combo_index=combo_index))
        elif typ & 2:
            curve = p[5].split("|")
            ctype = curve[0][:1] if curve[0][:1].isalpha() else "B"
            pts = [pos]
            for tok in curve[1:]:
                xy = tok.split(":")
                if len(xy) == 2:
                    try:
                        pts.append(flip((float(xy[0]), float(xy[1]))))
                    except ValueError:
                        pass
            slides = int(p[6]) if len(p) > 6 else 1
            length = float(p[7]) if len(p) > 7 and p[7] else None
            body = slider_path(ctype, pts, length) if len(pts) > 1 else [pos]
            path_end = body[-1]
            end_pos = path_end if slides % 2 == 1 else pos
            beat_len, sv = _beat_info(timing, t)
            px_len = length if length else _dist(pos, path_end)
            dur = px_len * slides / (slider_mult * 100 * sv) * beat_len if beat_len > 0 else 0
            objects.append(HitObject("slider", t, pos, t + dur, end_pos, path_end, path=body,
                                     slides=max(1, slides), combo_number=combo_number,
                                     combo_index=combo_index))
        elif typ & 8:
            end = float(p[5]) if len(p) > 5 else t
            objects.append(HitObject("spinner", t, pos, end, pos, pos))

    objects.sort(key=lambda o: o.time)
    bm = Beatmap(path, version, kv.get("Title", "?"), kv.get("Artist", "?"),
                 kv.get("Version", "?"), cs, od, ar, num("StackLeniency", 0.7), objects, colours)
    if kv.get("AudioFilename"):
        bm.audio = path.parent / kv["AudioFilename"]
    if background:
        bm.background = path.parent / background
    apply_stacking(bm)
    return bm


# --------------------------------------------------------------------------- #
# Stacking (port of osu!lazer's OsuBeatmapProcessor, which mirrors stable)
# --------------------------------------------------------------------------- #

def preempt(ar):
    return 1200 + 600 * (5 - ar) / 5 if ar < 5 else 1200 - 750 * (ar - 5) / 5


def circle_scale(cs):
    return (1 - 0.7 * (cs - 5) / 5) / 2 * 1.00041


def apply_stacking(bm: Beatmap):
    objs = bm.objects
    threshold = preempt(bm.ar) * bm.stack_leniency
    if bm.version >= 6:
        _stack_new(objs, threshold)
    else:
        _stack_old(objs, threshold)
    off = circle_scale(bm.cs) * -6.4
    for o in objs:
        o.stacked_pos = (o.pos[0] + o.stack * off, o.pos[1] + o.stack * off)


def _stack_new(objs, thr):
    for i in range(len(objs) - 1, 0, -1):
        oi = objs[i]
        if oi.stack != 0 or oi.kind == "spinner":
            continue
        n = i
        if oi.kind == "circle":
            while n > 0:
                n -= 1
                on = objs[n]
                if on.kind == "spinner":
                    continue
                if oi.time - on.end_time > thr:
                    break
                if on.kind == "slider" and _dist(on.end_pos, oi.pos) < STACK_DISTANCE:
                    offset = oi.stack - on.stack + 1
                    for j in range(n + 1, i + 1):
                        if _dist(on.end_pos, objs[j].pos) < STACK_DISTANCE:
                            objs[j].stack -= offset
                    break
                if _dist(on.pos, oi.pos) < STACK_DISTANCE:
                    on.stack = oi.stack + 1
                    oi = on
        elif oi.kind == "slider":
            while n > 0:
                n -= 1
                on = objs[n]
                if on.kind == "spinner":
                    continue
                if oi.time - on.time > thr:
                    break
                if _dist(on.end_pos, oi.pos) < STACK_DISTANCE:
                    on.stack = oi.stack + 1
                    oi = on


def _stack_old(objs, thr):
    for i, cur in enumerate(objs):
        if cur.stack != 0 and cur.kind != "slider":
            continue
        start_time = cur.end_time
        slider_stack = 0
        pos2 = cur.path_end_pos if cur.kind == "slider" else cur.pos
        for j in range(i + 1, len(objs)):
            if objs[j].time - thr > start_time:
                break
            if _dist(objs[j].pos, cur.pos) < STACK_DISTANCE:
                cur.stack += 1
                start_time = objs[j].time
            elif _dist(objs[j].pos, pos2) < STACK_DISTANCE:
                slider_stack += 1
                objs[j].stack -= slider_stack
                start_time = objs[j].time


# --------------------------------------------------------------------------- #
# Locating the beatmap from the replay's MD5
# --------------------------------------------------------------------------- #

def find_osu_dir(explicit=None):
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("OSU_DIR"):
        candidates.append(Path(os.environ["OSU_DIR"]))
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"osu\shell\open\command") as k:
                cmd = winreg.QueryValue(k, None)
            m = re.match(r'"([^"]+)"', cmd)
            if m:
                candidates.append(Path(m.group(1)).parent)
        except OSError:
            pass
    candidates += [
        Path(os.environ.get("LOCALAPPDATA", "")) / "osu!",
        Path.home() / "Documents" / "osu!",
        Path("C:/osu!"),
        Path("D:/osu!"),
    ]
    for c in candidates:
        if (c / "osu!.exe").exists() or (c / "Songs").is_dir():
            return c
    return None


def find_songs_dir(osu_dir: Path):
    # Respect a custom BeatmapDirectory from osu!.<user>.cfg
    for cfg in osu_dir.glob("osu!.*.cfg"):
        try:
            for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("BeatmapDirectory"):
                    d = Path(line.split("=", 1)[1].strip())
                    d = d if d.is_absolute() else osu_dir / d
                    if d.is_dir():
                        return d
        except OSError:
            pass
    return osu_dir / "Songs"


def _md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def find_beatmap(md5, songs_dir: Path, progress=None):
    """Find the .osu with this MD5. `progress(done, total)` is called while indexing."""
    index = {}
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        if data.get("songs_dir") == str(songs_dir):
            index = data.get("files", {})
    except (OSError, ValueError):
        pass

    for rel, (_mtime, _size, h) in index.items():
        if h == md5 and (songs_dir / rel).exists():
            return songs_dir / rel

    if progress is None:
        print(f"Indexing beatmaps in {songs_dir} (first run can take a moment)...")
    new_index, found = {}, None
    files = list(songs_dir.rglob("*.osu"))
    if progress:
        progress(0, len(files))
    for k, p in enumerate(files, 1):
        rel = str(p.relative_to(songs_dir))
        try:
            st = p.stat()
        except OSError:
            continue
        e = index.get(rel)
        h = e[2] if e and e[0] == st.st_mtime and e[1] == st.st_size else _md5(p)
        new_index[rel] = [st.st_mtime, st.st_size, h]
        if h == md5:
            found = p
        if k % 250 == 0:
            if progress:
                progress(k, len(files))
            elif k % 2000 == 0:
                print(f"  {k}/{len(files)}")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps({"songs_dir": str(songs_dir), "files": new_index}),
                              encoding="utf-8")
    except OSError:
        pass
    return found


# --------------------------------------------------------------------------- #
# Hit detection
# --------------------------------------------------------------------------- #

@dataclass
class Hit:
    index: int
    kind: str
    time: float
    error: float        # ms, press time - object time (negative = early)
    dx: float           # cursor - centre, osu!pixels (screen axes, y down)
    dy: float
    radius: float
    judgement: int      # 300 / 100 / 50
    move_dir: tuple     # unit vector from the previous object, or None
    jump: tuple = None  # vector from the previous object's end to this object (osu!pixels)
    pos: tuple = None   # note centre on the playfield (stacked, HR-flipped = as on screen)


@dataclass
class Miss:
    index: int
    kind: str
    time: float
    error: float        # ms of the failed press, or None when there was no click
    dx: float           # cursor - centre at the failed press (or at object time)
    dy: float
    radius: float
    reason: str         # "outside" | "early" | "no click"
    move_dir: tuple
    jump: tuple = None
    pos: tuple = None


@dataclass
class Analysis:
    replay: Replay
    beatmap: Beatmap
    hits: list
    misses: list
    radius: float
    windows: tuple


def hit_windows(od):
    return (math.floor(80 - 6 * od) - 0.5,
            math.floor(140 - 8 * od) - 0.5,
            math.floor(200 - 10 * od) - 0.5)


def analyse(replay: Replay, bm: Beatmap, include_slider_heads=True) -> Analysis:
    radius = 64 * circle_scale(bm.cs)
    w300, w100, w50 = hit_windows(bm.od)

    playable = [o for o in bm.objects if o.kind != "spinner"]

    # Rising edges of either key = presses
    presses = []
    prev = 0
    for t, x, y, keys in replay.frames:
        for mask in (KEY_LEFT, KEY_RIGHT):
            if keys & mask and not prev & mask:
                presses.append((t, x, y))
        prev = keys

    def jump(i):
        if i == 0:
            return None
        p, o = playable[i - 1].end_pos, playable[i]
        return (o.pos[0] - p[0], o.pos[1] - p[1])

    def move_dir(i):
        j = jump(i)
        if j is None:
            return None
        d = math.hypot(*j)
        return (j[0] / d, j[1] / d) if d > radius * 0.5 else None

    judged = [None] * len(playable)
    attempts = {}  # object index -> failed press (abs err, err, x, y, reason)
    hits = []
    i = 0
    for t, x, y in presses:
        while i < len(playable) and (judged[i] is not None or t > playable[i].time + w50):
            if judged[i] is None:
                judged[i] = 0
            i += 1
        if i >= len(playable):
            break
        o = playable[i]
        err = t - o.time
        if err < -EARLY_MISS_WINDOW:
            continue
        cx, cy = o.stacked_pos
        if math.hypot(x - cx, y - cy) > radius:
            # Click outside the circle does nothing (notelock), remember the closest one
            if err >= -w50 and (i not in attempts or abs(err) < attempts[i][0]):
                attempts[i] = (abs(err), err, x, y, "outside")
            continue
        if err < -w50:
            judged[i] = 0
            attempts[i] = (abs(err), err, x, y, "early")
            continue
        a = abs(err)
        j = 300 if a <= w300 else 100 if a <= w100 else 50
        judged[i] = j
        if include_slider_heads or o.kind == "circle":
            hits.append(Hit(i, o.kind, o.time, err, x - cx, y - cy, radius, j, move_dir(i), jump(i),
                            o.stacked_pos))

    # Objects after the replay ends (fail / quit) are not counted as misses
    frames = replay.frames
    frame_times = [f[0] for f in frames]
    last_t = frame_times[-1] if frames else 0
    misses = []
    for k, o in enumerate(playable):
        if judged[k] not in (None, 0) or o.time + w50 > last_t:
            continue
        if not include_slider_heads and o.kind != "circle":
            continue
        if k in attempts:
            _, err, x, y, reason = attempts[k]
        else:
            err, reason = None, "no click"
            x, y = _cursor_at(frames, frame_times, o.time)
        cx, cy = o.stacked_pos
        misses.append(Miss(k, o.kind, o.time, err, x - cx, y - cy, radius, reason, move_dir(k),
                           jump(k), o.stacked_pos))
    return Analysis(replay, bm, hits, misses, radius, (w300, w100, w50))


# --------------------------------------------------------------------------- #
# Over / underaim and tablet area calibration
# --------------------------------------------------------------------------- #
#
# A tablet maps every pen position to a fixed screen position. For each click we
# know where the note spawned and where the cursor really landed, i.e. which pen
# position you *used* for that note. Fitting, per axis, the area edges that would
# have mapped those pen positions onto the notes gives a correction per edge:
# overaiming notes on the right side moves the right edge out (bigger area on
# that side, so the same hand motion travels less on screen), underaiming them
# moves it in. Only the systematic part can be fixed - random scatter is aim skill.

STABLE_PLAYFIELD_SHIFT = 8  # osu!stable draws the playfield 8 osu!px below centre
EDGE_NAMES = ("top", "bottom", "left", "right")


def playfield_to_screen(x, y, screen):
    sw, sh = screen
    s = sh * 0.8 / 384
    return (sw - 512 * s) / 2 + x * s, (sh - 384 * s) / 2 + (y + STABLE_PLAYFIELD_SHIFT) * s


def screen_to_playfield(sx, sy, screen):
    sw, sh = screen
    s = sh * 0.8 / 384
    return (sx - (sw - 512 * s) / 2) / s, (sy - (sh - 384 * s) / 2) / s - STABLE_PLAYFIELD_SHIFT


@dataclass
class AimSample:
    target: tuple       # note centre (osu!px)
    err: tuple          # cursor - centre (osu!px, y down)
    radius: float
    move_dir: tuple     # unit approach direction, or None
    is_miss: bool

    @property
    def along(self):
        """Error along the approach direction in radii: + overaim, - underaim."""
        if not self.move_dir:
            return None
        return (self.err[0] * self.move_dir[0] + self.err[1] * self.move_dir[1]) / self.radius


def aim_samples(analyses):
    """Hits plus misses where you clicked next to the note (not notelock clicks far away)."""
    out = []
    for a in analyses:
        for h in a.hits:
            if h.pos:
                out.append(AimSample(h.pos, (h.dx, h.dy), h.radius, h.move_dir, False))
        for m in a.misses:
            if m.pos and m.reason == "outside" and math.hypot(m.dx, m.dy) < 3 * m.radius:
                out.append(AimSample(m.pos, (m.dx, m.dy), m.radius, m.move_dir, True))
    return out


@dataclass
class AimSplit:
    over: int = 0
    under: int = 0

    @property
    def total(self):
        return self.over + self.under

    @property
    def over_pct(self):
        return 100 * self.over / self.total if self.total else 0.0


def over_under(samples, misses):
    split = AimSplit()
    for s in samples:
        if s.is_miss != misses or s.along is None:
            continue
        if s.along > 0:
            split.over += 1
        else:
            split.under += 1
    return split


@dataclass
class RegionStat:
    col: int            # 0 left, 1 centre, 2 right
    row: int            # 0 top, 1 middle, 2 bottom
    n: int
    misses: AimSplit
    hits: AimSplit
    mean_err: tuple     # average cursor error in radii (screen axes, y down)


def region_stats(samples):
    cells = {}
    for s in samples:
        c = min(2, max(0, int(s.target[0] // (512 / 3))))
        r = min(2, max(0, int(s.target[1] // 128)))
        cells.setdefault((c, r), []).append(s)
    out = []
    for row in range(3):
        for col in range(3):
            ss = cells.get((col, row), [])
            n = len(ss)
            mx = sum(s.err[0] / s.radius for s in ss) / n if n else 0.0
            my = sum(s.err[1] / s.radius for s in ss) / n if n else 0.0
            out.append(RegionStat(col, row, n, over_under(ss, True), over_under(ss, False), (mx, my)))
    return out


@dataclass
class EdgeFit:
    current: int
    suggested: int
    stderr: float       # None when there was not enough data
    significant: bool


@dataclass
class TabletSuggestion:
    edges: dict          # "top"/"bottom"/"left"/"right" -> EdgeFit
    current: tuple       # (top, bottom, left, right) in tablet points
    suggested: tuple
    clamped: bool
    n_samples: int
    misses_now: int
    misses_after: int
    fixed: int
    broken: int
    miss_split: AimSplit
    hit_split: AimSplit
    regions: list


def _fit_axis(samples, axis, lo, hi, screen):
    """Least-squares edges (lo', hi') so that the pen positions used land on the notes."""
    us, ps = [], []
    for s in samples:
        r = s.radius
        e = max(-2 * r, min(2 * r, s.err[axis]))
        land = (s.target[0] + e, s.target[1]) if axis == 0 else (s.target[0], s.target[1] + e)
        ut = playfield_to_screen(*s.target, screen)[axis] / screen[axis]
        ul = playfield_to_screen(*land, screen)[axis] / screen[axis]
        us.append(ut)
        ps.append(lo + ul * (hi - lo))
    n = len(us)
    if n < 20:
        return EdgeFit(lo, lo, None, False), EdgeFit(hi, hi, None, False)
    s11 = sum((1 - u) ** 2 for u in us)
    s12 = sum((1 - u) * u for u in us)
    s22 = sum(u * u for u in us)
    t1 = sum((1 - u) * p for u, p in zip(us, ps))
    t2 = sum(u * p for u, p in zip(us, ps))
    det = s11 * s22 - s12 * s12
    a = (t1 * s22 - t2 * s12) / det
    b = (s11 * t2 - s12 * t1) / det
    var = sum((p - a * (1 - u) - b * u) ** 2 for u, p in zip(us, ps)) / (n - 2)
    se_a, se_b = math.sqrt(var * s22 / det), math.sqrt(var * s11 / det)
    sig_a = abs(a - lo) > 2 * se_a and abs(a - lo) >= 10
    sig_b = abs(b - hi) > 2 * se_b and abs(b - hi) >= 10
    # Refit with the edge that shows no clear bias held where it is
    if sig_a and not sig_b:
        b = hi
        a = sum((1 - u) * (p - hi * u) for u, p in zip(us, ps)) / s11
    elif sig_b and not sig_a:
        a = lo
        b = sum(u * (p - lo * (1 - u)) for u, p in zip(us, ps)) / s22
    elif not sig_a and not sig_b:
        a, b = lo, hi
    return EdgeFit(lo, a, se_a, sig_a), EdgeFit(hi, b, se_b, sig_b)


def suggest_tablet_area(analyses, area, tablet=(15200, 9500), screen=(1920, 1080), max_change=0.15):
    """area = (top, bottom, left, right) in tablet points, as in Wacom Center.
    Assumes the area is mapped to the whole screen (Wacom default)."""
    top, bottom, left, right = area
    samples = aim_samples(analyses)
    fl, fr = _fit_axis(samples, 0, left, right, screen)
    ft, fb = _fit_axis(samples, 1, top, bottom, screen)

    clamped = False
    for f, size, limit in ((fl, right - left, tablet[0]), (fr, right - left, tablet[0]),
                           (ft, bottom - top, tablet[1]), (fb, bottom - top, tablet[1])):
        d = f.suggested - f.current
        if abs(d) > max_change * size:
            clamped = True
            d = math.copysign(max_change * size, d)
        f.suggested = int(min(limit, max(0, round((f.current + d) / 5) * 5)))
    edges = dict(zip(EDGE_NAMES, (ft, fb, fl, fr)))
    suggested = (ft.suggested, fb.suggested, fl.suggested, fr.suggested)

    # Replay every click with the new area: same pen position, new screen position
    fixed = broken = 0
    for s in samples:
        tx, ty = s.target
        sx, sy = playfield_to_screen(tx + s.err[0], ty + s.err[1], screen)
        px = left + sx / screen[0] * (right - left)
        py = top + sy / screen[1] * (bottom - top)
        nsx = (px - fl.suggested) / (fr.suggested - fl.suggested) * screen[0]
        nsy = (py - ft.suggested) / (fb.suggested - ft.suggested) * screen[1]
        nx, ny = screen_to_playfield(nsx, nsy, screen)
        inside = math.hypot(nx - tx, ny - ty) <= s.radius
        if s.is_miss and inside:
            fixed += 1
        elif not s.is_miss and not inside:
            broken += 1

    misses_now = sum(len(a.misses) for a in analyses)
    return TabletSuggestion(edges, tuple(area), suggested, clamped, len(samples), misses_now,
                            misses_now - fixed + broken, fixed, broken,
                            over_under(samples, True), over_under(samples, False),
                            region_stats(samples))


def _cursor_at(frames, times, t):
    """Cursor position at time t, linearly interpolated between frames."""
    k = bisect.bisect_left(times, t)
    if k <= 0:
        return frames[0][1], frames[0][2]
    if k >= len(frames):
        return frames[-1][1], frames[-1][2]
    t0, x0, y0, _ = frames[k - 1]
    t1, x1, y1, _ = frames[k]
    f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f


# --------------------------------------------------------------------------- #
# Plot
# --------------------------------------------------------------------------- #

BG = "#15151c"
PANEL = "#1e1e28"
FG = "#e8e8f0"
MUTED = "#8a8aa0"
DEFAULT_ACCENT = "#ff66aa"
PINK = load_settings().get("accent", DEFAULT_ACCENT)   # accent colour (Settings)
AVG = "#ffd84d"
JUDGE_COLORS = {300: "#5ac8fa", 100: "#7ed957", 50: "#ffb347"}
MISS_COLORS = {"outside": "#ff4d5e", "early": "#ffa94d", "no click": "#a8a8c0"}
MISS_LABELS = {"outside": "miss: clicked outside", "early": "miss: too early",
               "no click": "miss: no click"}
MISS_CAP = 1.5  # misses farther than this (in radii) are pinned to this ring


def _coords(hits, frame):
    xs, ys, used = [], [], []
    for h in hits:
        if frame == "movement":
            if h.move_dir is None:
                continue
            ux, uy = h.move_dir
            along = h.dx * ux + h.dy * uy
            perp = -h.dx * uy + h.dy * ux
            xs.append(along / h.radius)
            ys.append(-perp / h.radius)
        else:
            xs.append(h.dx / h.radius)
            ys.append(-h.dy / h.radius)  # screen y points down; plot up = screen up
        used.append(h)
    return xs, ys, used


def plot(analyses, frame="screen", color_by="timing", save=None):
    import matplotlib
    if save:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(14, 9.5))
    if fig.canvas.manager:
        fig.canvas.manager.set_window_title("osu! hit analyzer")
    if not draw(fig, analyses, frame, color_by):
        print("No hits to plot.")
    if save:
        fig.savefig(save, dpi=130, facecolor=BG)
        print(f"Saved plot to {save}")
    else:
        plt.show()


def draw(fig, analyses, frame="screen", color_by="timing", on_pick=None):
    """Draw the analysis onto a matplotlib Figure (cleared first). Returns False if no hits.
    on_pick(analysis, hit_or_miss) is called when a dot / X is clicked."""
    import numpy as np
    import matplotlib.colors as mcolors
    from matplotlib.patches import Circle, Ellipse
    from matplotlib.colors import TwoSlopeNorm
    from matplotlib.lines import Line2D

    if getattr(fig, "_hover_cid", None) is not None:
        fig.canvas.mpl_disconnect(fig._hover_cid)
        fig._hover_cid = None
    if getattr(fig, "_pick_cid", None) is not None:
        fig.canvas.mpl_disconnect(fig._pick_cid)
        fig._pick_cid = None
    fig.clear()
    fig.set_facecolor(BG)

    all_hits = [h for a in analyses for h in a.hits]
    xs, ys, used = _coords(all_hits, frame)
    if not used:
        fig.text(0.5, 0.5, "No hits found in this replay", color=MUTED, ha="center", fontsize=14)
        return False
    xs, ys = np.array(xs), np.array(ys)
    errs = np.array([h.error for h in used])
    rates = np.array([next(a.replay.rate for a in analyses if h in a.hits) for h in used])
    mean_x, mean_y = xs.mean(), ys.mean()
    dists = np.hypot(xs, ys)

    all_misses = [m for a in analyses for m in a.misses]
    mxs, mys, mused = _coords(all_misses, frame)
    mxs, mys = np.array(mxs, dtype=float), np.array(mys, dtype=float)
    mdists = np.hypot(mxs, mys)
    pinned = mdists > MISS_CAP
    shrink = np.where(pinned, MISS_CAP / np.maximum(mdists, 1e-9), 1.0)
    mxs_plot, mys_plot = mxs * shrink, mys * shrink

    ax = fig.add_axes([0.03, 0.07, 0.60, 0.80])
    ax.set_facecolor(BG)
    ax.set_aspect("equal")
    lim = max(1.15, float(np.max(np.abs(np.concatenate([xs, ys])))) + 0.05)
    if len(mused):
        lim = max(lim, float(mdists.max(initial=0).clip(max=MISS_CAP)) + 0.12)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.axis("off")

    # The hit circle
    ax.add_patch(Circle((0, 0), 1, facecolor=PINK, alpha=0.07, zorder=0))
    ax.add_patch(Circle((0, 0), 1, fill=False, edgecolor=PINK, lw=3, zorder=1))
    for r in (0.25, 0.5, 0.75):
        ax.add_patch(Circle((0, 0), r, fill=False, edgecolor="#ffffff", alpha=0.12,
                            lw=1, ls=(0, (3, 4)), zorder=1))
        ax.text(r * 0.707 + 0.01, r * 0.707 + 0.01, f"{int(r * 100)}%", color=MUTED,
                fontsize=8, alpha=0.7, zorder=1)
    ax.plot([-1, 1], [0, 0], color="#ffffff", alpha=0.08, lw=1, zorder=1)
    ax.plot([0, 0], [-1, 1], color="#ffffff", alpha=0.08, lw=1, zorder=1)

    if frame == "movement":
        ax.annotate("", xy=(0.95, -1.08), xytext=(0.55, -1.08),
                    arrowprops=dict(arrowstyle="->", color=MUTED, lw=1.5))
        ax.text(0.5, -1.08, "movement direction", color=MUTED, ha="right", va="center", fontsize=9)
        ax.text(1.04, 0, "overshoot", color=MUTED, rotation=-90, va="center", fontsize=9)
        ax.text(-1.04, 0, "undershoot", color=MUTED, rotation=90, va="center", ha="right", fontsize=9)

    # Hits
    size = 26 if len(used) < 600 else 14
    if color_by == "judgement":
        colors = [JUDGE_COLORS[h.judgement] for h in used]
        sc = ax.scatter(xs, ys, c=colors, s=size, alpha=0.8, linewidths=0, zorder=3)
    else:
        w300 = max(a.windows[0] for a in analyses)
        sc = ax.scatter(xs, ys, c=np.clip(errs, -w300, w300), cmap="coolwarm",
                        norm=TwoSlopeNorm(0, -w300, w300),
                        s=size, alpha=0.85, linewidths=0, zorder=3)
        cax = fig.add_axes([0.08, 0.05, 0.50, 0.015])
        cb = fig.colorbar(sc, cax=cax, orientation="horizontal")
        cb.set_label("timing error (ms, scale = 300 window)   ← early  |  late →", color=FG, fontsize=9)
        cb.ax.tick_params(colors=MUTED, labelsize=8)
        cb.outline.set_edgecolor(MUTED)

    # Spread ellipses (1σ and 2σ)
    if len(used) >= 3:
        cov = np.cov(xs, ys)
        vals, vecs = np.linalg.eigh(cov)
        vals = np.maximum(vals, 0)
        angle = math.degrees(math.atan2(vecs[1, 1], vecs[0, 1]))
        for k, ls in ((1, "-"), (2, "--")):
            ax.add_patch(Ellipse((mean_x, mean_y), 2 * k * math.sqrt(vals[1]),
                                 2 * k * math.sqrt(vals[0]), angle=angle, fill=False,
                                 edgecolor=FG, alpha=0.55, lw=1.3, ls=ls, zorder=4))

    # Average hit
    ax.plot([0, mean_x], [0, mean_y], color=AVG, lw=2, alpha=0.9, zorder=5)
    ax.scatter([0], [0], marker="+", s=120, color=FG, alpha=0.6, zorder=5)
    ax.scatter([mean_x], [mean_y], marker="X", s=320, color=AVG,
               edgecolors="#000000", linewidths=1.5, zorder=6, label="average hit")

    # Misses
    msc = None
    if len(mused):
        if pinned.any():
            ax.add_patch(Circle((0, 0), MISS_CAP, fill=False, edgecolor=MUTED, alpha=0.35,
                                lw=1, ls=(0, (2, 4)), zorder=1))
            ax.text(MISS_CAP * 0.707 + 0.02, -MISS_CAP * 0.707 - 0.02,
                    f"{int(MISS_CAP * 100)}%+", color=MUTED, fontsize=8, alpha=0.8, va="top")
        miss_colors = [MISS_COLORS[m.reason] for m in mused]
        malpha = np.where(pinned, 0.55, 0.95)
        rgba = [mcolors.to_rgba(c, a) for c, a in zip(miss_colors, malpha)]
        msc = ax.scatter(mxs_plot, mys_plot, marker="x", s=80, c=rgba, linewidths=2.4, zorder=7)

    handles = [Line2D([], [], marker="X", ls="", color=AVG, markeredgecolor="#000000",
                      markersize=11, label="average hit")]
    for reason in MISS_COLORS:
        n = sum(1 for m in mused if m.reason == reason)
        if n:
            handles.append(Line2D([], [], marker="x", ls="", color=MISS_COLORS[reason],
                                  markeredgewidth=2.4, markersize=9,
                                  label=f"{MISS_LABELS[reason]} ({n})"))
    # One row under the title, aligned with it (kept out of the plot so it never covers hits)
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.025, 0.915), ncol=len(handles),
               frameon=False, fontsize=9, labelcolor=FG, columnspacing=1.6, handletextpad=0.4)

    # Hover tooltip
    tip = ax.annotate("", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
                      color=FG, fontsize=9, zorder=10,
                      bbox=dict(boxstyle="round", fc=PANEL, ec=MUTED, alpha=0.95))
    tip.set_visible(False)

    def _stamp(o):
        m, s = divmod(o.time / 1000, 60)
        return f"#{o.index + 1} {o.kind} @ {int(m)}:{s:06.3f}"

    hint = "\nclick: open in replay viewer" if on_pick else ""

    def on_move(event):
        if event.inaxes != ax:
            return
        tip.set_visible(False)
        ok, info = msc.contains(event) if msc is not None else (False, {})
        if ok and info["ind"].size:
            k = info["ind"][0]
            m = mused[k]
            when = "" if m.error is None else f", {m.error:+.0f} ms"
            tip.xy = (mxs_plot[k], mys_plot[k])
            tip.set_text(f"{_stamp(m)}\nMISS ({MISS_LABELS[m.reason][6:]}{when})\n"
                         f"{mdists[k] * 100:.0f}% of radius from centre" + hint)
            tip.set_visible(True)
        else:
            ok, info = sc.contains(event)
            if ok and info["ind"].size:
                k = info["ind"][0]
                h = used[k]
                tip.xy = (xs[k], ys[k])
                tip.set_text(f"{_stamp(h)}\n{h.error:+.0f} ms  ({h.judgement})\n"
                             f"{dists[k] * 100:.0f}% of radius" + hint)
                tip.set_visible(True)
        fig.canvas.draw_idle()

    fig._hover_cid = fig.canvas.mpl_connect("motion_notify_event", on_move)

    owner = {id(o): a for a in analyses for o in a.hits + a.misses}

    def on_click(event):
        if on_pick is None or event.inaxes != ax or event.button != 1:
            return
        for scatter, items in ((msc, mused), (sc, used)):
            if scatter is None:
                continue
            ok, info = scatter.contains(event)
            if ok and info["ind"].size:
                o = items[info["ind"][0]]
                on_pick(owner[id(o)], o)
                return

    fig._pick_cid = fig.canvas.mpl_connect("button_press_event", on_click)

    # Title
    if len(analyses) == 1:
        a = analyses[0]
        title = f"{a.beatmap.artist} - {a.beatmap.title} [{a.beatmap.diff_name}]"
        sub = f"{a.replay.player}   +{a.replay.mod_string}   CS {a.beatmap.cs:.1f}  OD {a.beatmap.od:.1f}"
    else:
        title = f"{len(analyses)} replays combined"
        sub = ", ".join(sorted({a.replay.player for a in analyses}))
    fig.text(0.03, 0.965, title, color=FG, fontsize=14, weight="bold")
    fig.text(0.03, 0.935, sub, color=MUTED, fontsize=10)

    # Stats panel
    sx = 0.66
    pane = fig.add_axes([sx, 0.05, 0.31, 0.86])
    pane.set_facecolor("none")
    from matplotlib.patches import FancyBboxPatch
    pw, ph = fig.get_figwidth() * 0.31, fig.get_figheight() * 0.86   # inches, to keep corners round
    pane.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.045",
                                  mutation_aspect=pw / ph, transform=pane.transAxes,
                                  facecolor=PANEL, edgecolor="none", clip_on=False, zorder=-1))
    pane.set_xticks([])
    pane.set_yticks([])
    for s in pane.spines.values():
        s.set_visible(False)

    real_err = errs / rates
    ur = float(np.std(real_err) * 10) if len(used) > 1 else 0.0
    avg_px = math.hypot(mean_x, mean_y) * np.mean([h.radius for h in used])
    cnt = {j: sum(1 for h in used if h.judgement == j) for j in (300, 100, 50)}
    total_miss = len(all_misses)
    by_reason = {r: sum(1 for m in all_misses if m.reason == r) for r in MISS_COLORS}
    aim = aim_samples(analyses)
    miss_split, hit_split = over_under(aim, True), over_under(aim, False)
    direction = ""
    if math.hypot(mean_x, mean_y) > 0.02:
        ang = math.degrees(math.atan2(mean_y, mean_x))
        if frame == "movement":
            parts = []
            if abs(mean_x) > 0.02:
                parts.append("overshoot" if mean_x > 0 else "undershoot")
            if abs(mean_y) > 0.02:
                parts.append("left of path" if mean_y > 0 else "right of path")
            direction = " + ".join(parts)
        else:
            names = ["right", "up-right", "up", "up-left", "left", "down-left", "down", "down-right"]
            direction = names[int(((ang + 22.5) % 360) // 45)]

    rows = [
        ("AVERAGE HIT", None),
        ("offset", f"{math.hypot(mean_x, mean_y) * 100:.1f}% of radius  ({avg_px:.1f} px)"),
        ("direction", direction or "centred"),
        ("x / y", f"{mean_x * 100:+.1f}%  /  {mean_y * 100:+.1f}%"),
        ("", None),
        ("SPREAD", None),
        ("mean distance", f"{dists.mean() * 100:.1f}% of radius"),
        ("std x / y", f"{xs.std() * 100:.1f}%  /  {ys.std() * 100:.1f}%"),
        ("inside 50% radius", f"{(dists <= 0.5).mean() * 100:.1f}%"),
        ("", None),
        ("OVER / UNDER AIM", None),
        ("misses", f"{miss_split.over} over / {miss_split.under} under"
                                     + (f"  ({miss_split.over_pct:.0f}% over)" if miss_split.total else "")),
        ("hits", f"{hit_split.over_pct:.0f}% over / {100 - hit_split.over_pct:.0f}% under"
                 if hit_split.total else "-"),
        ("", None),
        ("TIMING", None),
        ("mean error", f"{errs.mean():+.1f} ms ({'late' if errs.mean() > 0 else 'early'})"),
        ("unstable rate", f"{ur:.1f}"),
        ("", None),
        ("HITS", None),
        ("analysed", f"{len(used)}" + (f"  ({len(all_hits) - len(used)} skipped)" if len(used) != len(all_hits) else "")),
        ("300 / 100 / 50", f"{cnt[300]} / {cnt[100]} / {cnt[50]}"),
        ("misses (detected)", f"{total_miss}"),
        ("outside / early / no click",
         f"{by_reason['outside']} / {by_reason['early']} / {by_reason['no click']}"),
    ]
    if len(analyses) == 1:
        r = analyses[0].replay
        rows.append(("replay header", f"{r.n300}/{r.n100}/{r.n50}/{r.nmiss}x"))

    y = 0.965
    for label, value in rows:
        if value is None:
            if label:
                pane.text(0.06, y, label, color=PINK, fontsize=10, weight="bold",
                          transform=pane.transAxes)
            y -= 0.033 if label else 0.012
            continue
        pane.text(0.06, y, label, color=MUTED, fontsize=9.5, transform=pane.transAxes)
        pane.text(0.94, y, value, color=FG, fontsize=9.5, ha="right", transform=pane.transAxes)
        y -= 0.031

    # Timing histogram
    hax = fig.add_axes([sx + 0.025, 0.08, 0.26, 0.12])
    hax.set_facecolor(PANEL)
    w100 = max(a.windows[1] for a in analyses)
    bins = np.linspace(-w100, w100, 41)
    hax.hist(np.clip(errs, -w100, w100), bins=bins, color=PINK, alpha=0.8)
    hax.axvline(0, color=FG, alpha=0.4, lw=1)
    hax.axvline(errs.mean(), color=AVG, lw=1.5)
    hax.set_title("timing distribution (ms)", color=MUTED, fontsize=9)
    hax.tick_params(colors=MUTED, labelsize=8)
    for s in hax.spines.values():
        s.set_color("#33334a")

    fig.text(0.63, 0.935, f"view: {frame}" + ("  (screen axes, up = up)" if frame == "screen" else
             "  (rotated so movement → right)"), color=MUTED, fontsize=8, ha="right")
    return True


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _pick_files(osu_dir):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    initial = str(osu_dir / "Replays") if osu_dir and (osu_dir / "Replays").is_dir() else None
    files = filedialog.askopenfilenames(title="Choose osu! replay(s)", initialdir=initial,
                                        filetypes=[("osu! replay", "*.osr"), ("All files", "*.*")])
    root.destroy()
    return list(files)


def _pick_beatmap(replay_name, songs_dir):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    f = filedialog.askopenfilename(
        title=f"Beatmap not found for {replay_name} - choose the .osu file",
        initialdir=str(songs_dir) if songs_dir and songs_dir.is_dir() else None,
        filetypes=[("osu! beatmap", "*.osu"), ("All files", "*.*")])
    root.destroy()
    return f or None


def main():
    ap = argparse.ArgumentParser(description="Plot where your cursor was when you hit each circle.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("replays", nargs="*", help=".osr file(s); opens a file picker if omitted")
    ap.add_argument("--beatmap", help=".osu file (otherwise found by MD5 in your Songs folder)")
    ap.add_argument("--osu-dir", help="osu! install folder (auto-detected)")
    ap.add_argument("--frame", choices=["screen", "movement"], default="screen",
                    help="screen = raw axes; movement = rotated so approach direction points right")
    ap.add_argument("--color", choices=["timing", "judgement"], default="timing",
                    help="colour hits by timing error or by 300/100/50")
    ap.add_argument("--circles-only", action="store_true", help="ignore slider heads")
    ap.add_argument("--save", help="save the plot to this image file instead of showing it")
    args = ap.parse_args()

    osu_dir = find_osu_dir(args.osu_dir)
    songs_dir = find_songs_dir(osu_dir) if osu_dir else None
    gui = not args.replays
    replay_paths = args.replays or _pick_files(osu_dir)
    if not replay_paths:
        print("No replay selected.")
        return 1

    analyses = []
    for rp in replay_paths:
        replay = read_replay(rp)
        if replay.mode != 0:
            print(f"Skipping {Path(rp).name}: not an osu!standard replay")
            continue
        bpath = args.beatmap
        if not bpath and songs_dir and songs_dir.is_dir():
            bpath = find_beatmap(replay.beatmap_md5, songs_dir)
        if not bpath and gui:
            bpath = _pick_beatmap(Path(rp).name, songs_dir)
        if not bpath:
            print(f"Skipping {Path(rp).name}: beatmap {replay.beatmap_md5} not found (use --beatmap)")
            continue
        bm = read_beatmap(bpath, hard_rock=bool(replay.mods & MOD_HR), easy=bool(replay.mods & MOD_EZ))
        a = analyse(replay, bm, include_slider_heads=not args.circles_only)
        analyses.append(a)

        hits = a.hits
        print(f"\n{replay.player} | {bm.artist} - {bm.title} [{bm.diff_name}] +{replay.mod_string}")
        print(f"  beatmap: {Path(bpath).name}")
        print(f"  radius {a.radius:.1f}px, windows 300/100/50 = ±{a.windows[0]:.1f}/{a.windows[1]:.1f}/{a.windows[2]:.1f} ms")
        if hits:
            mx = sum(h.dx for h in hits) / len(hits)
            my = sum(h.dy for h in hits) / len(hits)
            me = sum(h.error for h in hits) / len(hits)
            md = sum(math.hypot(h.dx, h.dy) / h.radius for h in hits) / len(hits)
            reasons = ", ".join(f"{sum(1 for m in a.misses if m.reason == r)} {r}"
                                for r in MISS_COLORS)
            print(f"  {len(hits)} hits, {len(a.misses)} misses detected [{reasons}] (replay header: "
                  f"{replay.n300}/{replay.n100}/{replay.n50}/{replay.nmiss}x)")
            print(f"  average hit offset: dx {mx:+.2f}px  dy {my:+.2f}px  "
                  f"({math.hypot(mx, my) / a.radius * 100:.1f}% of radius)")
            print(f"  mean distance from centre: {md * 100:.1f}% of radius, mean timing {me:+.1f} ms")

    if not analyses:
        return 1
    plot(analyses, frame=args.frame, color_by=args.color, save=args.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
