"""Beatmap (.osu) parsing and stacking."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .curves import dist, slider_path

PLAYFIELD_W, PLAYFIELD_H = 512, 384
STACK_DISTANCE = 3


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
            px_len = length if length else dist(pos, path_end)
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


# Stacking (port of osu!lazer's OsuBeatmapProcessor, which mirrors stable)

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
                if on.kind == "slider" and dist(on.end_pos, oi.pos) < STACK_DISTANCE:
                    offset = oi.stack - on.stack + 1
                    for j in range(n + 1, i + 1):
                        if dist(on.end_pos, objs[j].pos) < STACK_DISTANCE:
                            objs[j].stack -= offset
                    break
                if dist(on.pos, oi.pos) < STACK_DISTANCE:
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
                if dist(on.end_pos, oi.pos) < STACK_DISTANCE:
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
            if dist(objs[j].pos, cur.pos) < STACK_DISTANCE:
                cur.stack += 1
                start_time = objs[j].time
            elif dist(objs[j].pos, pos2) < STACK_DISTANCE:
                slider_stack += 1
                objs[j].stack -= slider_stack
                start_time = objs[j].time
