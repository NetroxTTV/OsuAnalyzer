"""Hit detection: which press hit which note, where and when."""

import math
from dataclasses import dataclass

from .beatmap import Beatmap, circle_scale
from .replay import CursorTrack, Replay, key_presses

EARLY_MISS_WINDOW = 400  # ms: pressing earlier than the 50 window but inside this = miss


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

    presses = key_presses(replay.frames)

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
    cursor = CursorTrack(replay.frames)
    last_t = cursor.end
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
            x, y, _ = cursor.at(o.time)
        cx, cy = o.stacked_pos
        misses.append(Miss(k, o.kind, o.time, err, x - cx, y - cy, radius, reason, move_dir(k),
                           jump(k), o.stacked_pos))
    return Analysis(replay, bm, hits, misses, radius, (w300, w100, w50))
