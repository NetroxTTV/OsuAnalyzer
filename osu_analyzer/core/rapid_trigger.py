"""Rapid trigger: analog keyboard settings suggested from how you tap.

With rapid trigger a key registers a press once it has gone down by the press distance since
its highest point, and a release once it has come up by the release distance, at any depth.
The actuation point is only the depth of the first press from rest.

Replays record when osu! saw each key go down and up, not how far it travelled, so what is
measured is what the settings cause:

- how fast you press the same key again: the faster, the less your finger travels between two
  taps, so the smaller the distances must be for every tap to register
- double presses: released and pressed again within a few ms on no note (finger jitter is
  crossing a too small distance)
- broken slider holds: released during a slider and pressed again at once (same, on release)
- stuck keys: a note with no click while the key was still held from an earlier note (the
  release didn't register: too big a release distance)
- timing: hitting later on quick re-presses than on presses from rest means the key needs more
  travel to trigger again than your finger gives it
"""

import bisect
import math
from dataclasses import dataclass, field

from .replay import KEY_LEFT, KEY_RIGHT

KEYBOARD_BITS = 4 | 8       # K1 | K2 (M1 / M2 alone = mouse buttons)
DOUBLE_GAP = 30             # ms: pressed again faster than this after a release, on no note
REPRESS = 150               # ms since that key's release: the press relies on rapid trigger
FRESH = 400                 # ms: the key was at rest
IDLE = 1000                 # map ms from any note: a break or the intro, presses there are fidgeting
MIN_INTERVALS = 30
STEP = 0.05                 # mm
RT_RANGE = (0.1, 2.0)
AP_RANGE = (0.1, 4.0)
DEFAULTS = {"rt_actuation": 1.0, "rt_press": 0.3, "rt_release": 0.3}


def percentile(values, q):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo = math.floor(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _mean(v):
    return sum(v) / len(v) if v else None


def snap(x, lo, hi):
    return round(min(hi, max(lo, round(x / STEP) * STEP)), 2)


@dataclass
class Tap:
    key: int                # 0 = left (K1 / M1), 1 = right
    down: float             # map time
    up: float
    keyboard: bool
    note: int = None        # playable object index it was aimed at, or None
    prev_up: float = None   # release of the previous press of the same key


@dataclass
class Event:
    """Something that points at a setting, kept so the viewer can show it."""
    analysis: object
    time: float             # map time


@dataclass
class TapStats:
    presses: int = 0
    keyboard: int = 0
    note_pairs: int = 0
    alternate: int = 0
    intervals: list = field(default_factory=list)   # same key, note to note, real ms
    pairs: list = field(default_factory=list)       # (interval, hold of the first press), real ms
    holds: list = field(default_factory=list)       # presses on circles, real ms
    doubles: list = field(default_factory=list)
    broken: list = field(default_factory=list)
    stuck: list = field(default_factory=list)
    repress_err: list = field(default_factory=list)  # timing error of quick re-presses, real ms
    fresh_err: list = field(default_factory=list)    # ... of presses from rest

    @property
    def keyboard_share(self):
        return self.keyboard / self.presses if self.presses else 0.0

    @property
    def alternate_share(self):
        return self.alternate / self.note_pairs if self.note_pairs else 0.0

    @property
    def late_on_repress(self):
        """Mean error of quick re-presses minus presses from rest (ms, + = later), or None."""
        if len(self.repress_err) < MIN_INTERVALS or len(self.fresh_err) < MIN_INTERVALS:
            return None
        return _mean(self.repress_err) - _mean(self.fresh_err)


def _taps(frames):
    taps, held, prev = [], {}, 0
    for t, _x, _y, keys in frames:
        for k, mask in enumerate((KEY_LEFT, KEY_RIGHT)):
            if keys & mask and not prev & mask:
                held[k] = (t, bool(keys & mask & KEYBOARD_BITS))
            elif prev & mask and not keys & mask and k in held:
                d, kb = held.pop(k)
                taps.append(Tap(k, d, t, kb))
        prev = keys
    end = frames[-1][0] if frames else 0
    taps += [Tap(k, d, end, kb) for k, (d, kb) in held.items()]
    taps.sort(key=lambda tp: tp.down)
    return taps


def tap_stats(analyses):
    s = TapStats()
    for a in analyses:
        rate = a.replay.rate
        w50 = a.windows[2]
        objs = [o for o in a.beatmap.objects if o.kind != "spinner"]   # same indices as Hit / Miss
        times = [o.time for o in objs]
        spinners = [(o.time, o.end_time) for o in a.beatmap.objects if o.kind == "spinner"]
        taps = _taps(a.replay.frames)

        for tp in taps:
            i = bisect.bisect_left(times, tp.down)
            near = [j for j in (i - 1, i) if 0 <= j < len(objs) and abs(times[j] - tp.down) <= w50]
            if near:
                tp.note = min(near, key=lambda j: abs(times[j] - tp.down))
        s.presses += len(taps)
        s.keyboard += sum(tp.keyboard for tp in taps)

        on_notes = [tp for tp in taps if tp.note is not None]
        for p, c in zip(on_notes, on_notes[1:]):
            if c.note != p.note:
                s.note_pairs += 1
                s.alternate += c.key != p.key

        for k in (0, 1):
            seq = [tp for tp in taps if tp.key == k]
            for p, c in zip(seq, seq[1:]):
                c.prev_up = p.up
                if p.note is not None and c.note is not None and c.note != p.note:
                    interval = (c.down - p.down) / rate
                    s.intervals.append(interval)
                    s.pairs.append((interval, (p.up - p.down) / rate))
                if (c.down - p.up) / rate >= DOUBLE_GAP or (c.note is not None and c.note != p.note):
                    continue
                if any(t0 - 100 <= c.down <= t1 + 300 for t0, t1 in spinners):
                    continue
                i = bisect.bisect_left(times, c.down)
                if all(abs(times[j] - c.down) > IDLE for j in (i - 1, i) if 0 <= j < len(objs)):
                    continue
                held = objs[p.note] if p.note is not None else None
                if held is not None and held.kind == "slider" and p.up < held.end_time - 20:
                    other = any(tp.key != k and tp.down <= p.up and tp.up >= c.down for tp in taps)
                    if not other:      # the other key kept the slider held: just a tap on it
                        s.broken.append(Event(a, p.up))
                else:
                    s.doubles.append(Event(a, c.down))
            s.holds += [(tp.up - tp.down) / rate for tp in seq
                        if tp.note is not None and objs[tp.note].kind == "circle"]

        by_down = {round(tp.down): tp for tp in taps}
        for h in a.hits:
            tp = by_down.get(round(h.time + h.error))
            if tp is None:
                continue
            rest = (tp.down - tp.prev_up) / rate if tp.prev_up is not None else math.inf
            if rest < REPRESS:
                s.repress_err.append(h.error / rate)
            elif rest > FRESH:
                s.fresh_err.append(h.error / rate)

        for m in a.misses:
            if m.reason != "no click":
                continue
            for tp in taps:
                if tp.down >= m.time - w50 or tp.up <= m.time + w50:
                    continue
                o = objs[tp.note] if tp.note is not None else None
                if o is not None and o.kind == "slider" and o.end_time >= m.time - w50:
                    continue            # still holding a slider: not stuck
                s.stuck.append(Event(a, m.time))
                break
    return s


@dataclass
class RTSettings:
    actuation: float
    press: float
    release: float

    def as_tuple(self):
        return self.actuation, self.press, self.release


@dataclass
class RTSuggestion:
    current: RTSettings
    suggested: RTSettings
    stats: TapStats
    fast_interval: float        # ms between two presses of the same key, fastest 10 %
    stream_bpm: float           # the 1/4 stream speed that interval corresponds to
    hold_ratio: float           # hold / interval on the fastest taps
    reasons: dict               # "actuation" / "press" / "release" -> [text]
    conflicts: list


def suggest_rapid_trigger(analyses, current):
    """current = RTSettings in mm. None when there are too few same-key presses on notes."""
    s = tap_stats(analyses)
    if len(s.intervals) < MIN_INTERVALS:
        return None, s
    T = percentile(s.intervals, 0.1)
    alt = s.alternate_share > 0.5
    bpm = (30000 if alt else 15000) / T
    reasons = {"actuation": [], "press": [], "release": []}
    conflicts = []

    # Speed: between two taps of the same key the finger travels about in proportion to the time
    # it has, so the distances shrink with it (0.1 mm at ~60 ms, 0.3 mm at ~190 ms, max 0.5)
    base_rt = 0.0016 * T
    rt = {"press": base_rt, "release": base_rt}
    ap = 0.3 + 0.0025 * T
    speed = (f"your fastest taps press the same key again every {T:.0f} ms "
             f"(≈ {bpm:.0f} BPM streams, {'alternating' if alt else 'single-tapping'})")
    reasons["press"].append(f"{speed}: the key must re-trigger after a short travel")
    reasons["release"].append("same distance as the press, so taps stay even")
    reasons["actuation"].append("shallow enough that the first press of a burst is not late, deep "
                                "enough that a resting finger doesn't trigger it")

    fast = [h / i for i, h in s.pairs if i <= 1.5 * T]
    ratio = percentile(fast, 0.5) if fast else 0.0
    if ratio > 0.6:
        rt["release"] -= STEP
        reasons["release"].append(f"on fast taps the key stays down {ratio * 100:.0f}% of the time: "
                                  "a smaller release lets it come back up sooner")

    lo = {"press": RT_RANGE[0], "release": RT_RANGE[0]}
    hi = {"press": RT_RANGE[1], "release": RT_RANGE[1]}
    cur = {"press": current.press, "release": current.release}

    n_double = len(s.doubles)
    if n_double >= 3 and n_double / s.presses >= 0.002:
        lo["press"] = max(lo["press"], cur["press"] + STEP)
        reasons["press"].append(f"{n_double} double presses (released and pressed again within "
                                f"{DOUBLE_GAP} ms on no note): more press distance than now "
                                f"({current.press:.2f} mm) filters the jitter")
    if len(s.broken) >= 2:
        lo["release"] = max(lo["release"], cur["release"] + STEP)
        reasons["release"].append(f"{len(s.broken)} slider holds broken by a release and an "
                                  f"immediate re-press: more release distance than now "
                                  f"({current.release:.2f} mm)")
    if len(s.stuck) >= 2:
        hi["release"] = min(hi["release"], cur["release"] - STEP)
        reasons["release"].append(f"{len(s.stuck)} notes with no click while the key was still held "
                                  f"from an earlier note: less release distance than now "
                                  f"({current.release:.2f} mm)")
    late = s.late_on_repress
    if late is not None and late >= 6:
        hi["press"] = min(hi["press"], cur["press"] - STEP)
        reasons["press"].append(f"quick re-presses land {late:.0f} ms later than presses from rest: "
                                f"less press distance than now ({current.press:.2f} mm)")

    out = {}
    for k in ("press", "release"):
        if lo[k] > hi[k] + 1e-9:
            conflicts.append(f"{k.capitalize()}: the signs point both ways, kept at {cur[k]:.2f} mm.")
            out[k] = snap(cur[k], *RT_RANGE)
        else:
            out[k] = snap(min(hi[k], max(lo[k], rt[k])), *RT_RANGE)
    suggested = RTSettings(snap(min(1.2, max(0.4, ap)), *AP_RANGE), out["press"], out["release"])
    return RTSuggestion(current, suggested, s, T, bpm, ratio, reasons, conflicts), s
