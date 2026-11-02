"""Over / underaim and tablet area calibration."""

import bisect
import math
from dataclasses import dataclass, replace

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
    timing: float = 0.0  # press - note time (real ms, + = late)

    @property
    def along(self):
        """Error along the approach direction in radii: + overaim, - underaim."""
        if not self.move_dir:
            return None
        return (self.err[0] * self.move_dir[0] + self.err[1] * self.move_dir[1]) / self.radius


# Tap timing bins (real ms): the error measured on taps in each bin is compared with on-time ones
TIMING_EDGES = (-40, -25, -15, -5, 5, 15, 25, 40)
TIMING_MIN = 30     # samples a bin needs for its offset to count


def aim_samples(analyses):
    """Hits plus misses where you clicked next to the note (not notelock clicks far away)."""
    out = []
    for a in analyses:
        clicks = [(h, False) for h in a.hits if h.pos]
        clicks += [(m, True) for m in a.misses
                   if m.pos and m.reason == "outside" and math.hypot(m.dx, m.dy) < 3 * m.radius]
        for c, miss in clicks:
            out.append(AimSample(c.pos, (c.dx, c.dy), c.radius, c.move_dir, miss, c.error / a.replay.rate))
    return out


def _bin(t):
    return bisect.bisect_right(TIMING_EDGES, t)


@dataclass
class TimingBin:
    lo: float           # real ms, None = open-ended
    hi: float
    n: int
    offset: float       # mean over / underaim compared with on-time taps, radii (+ = more overaim)


def timing_curve(samples):
    """How the over / underaim changes with tap timing, per timing bin. An early tap catches the
    cursor before it arrives (looks like underaim), a late one after it went further (looks like
    overaim): that part is timing, not the area. Measured on your own taps, as the link is not
    linear. [] when there are too few on-time taps to compare with."""
    groups = [[] for _ in range(len(TIMING_EDGES) + 1)]
    for s in samples:
        if s.along is not None:
            groups[_bin(s.timing)].append(max(-2.0, min(2.0, s.along)))
    centre = groups[_bin(0)]
    if len(centre) < TIMING_MIN:
        return []
    ref = sum(centre) / len(centre)
    edges = (None,) + TIMING_EDGES + (None,)
    return [TimingBin(edges[i], edges[i + 1], len(g),
                      sum(g) / len(g) - ref if len(g) >= TIMING_MIN else 0.0)
            for i, g in enumerate(groups)]


def tapped_on_time(samples, curve):
    """The samples as if every note had been tapped on time: the timing part of the error removed."""
    if not curve:
        return list(samples)
    out = []
    for s in samples:
        k = curve[_bin(s.timing)].offset * s.radius
        if s.move_dir and k:
            s = replace(s, err=(s.err[0] - k * s.move_dir[0], s.err[1] - k * s.move_dir[1]))
        out.append(s)
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
    timing: "TapTiming"
    on_time: bool        # the fit removed the part of the error that comes from tap timing
    as_tapped: tuple     # what the fit gives without that


@dataclass
class TapTiming:
    mean: float          # press - note time, real ms (+ = late)
    early_share: float   # 0..1
    curve: list          # TimingBin per timing range (see timing_curve), [] if not measured
    along_tapped: float  # mean over / underaim as tapped, radii (+ = overaim)
    along_on_time: float  # ... as if tapped on time


def _mean_along(samples):
    v = [s.along for s in samples if s.along is not None]
    return sum(v) / len(v) if v else 0.0


def tap_timing(tapped, corrected, curve):
    n = len(tapped)
    return TapTiming(sum(s.timing for s in tapped) / n if n else 0.0,
                     sum(s.timing < 0 for s in tapped) / n if n else 0.0,
                     curve, _mean_along(tapped), _mean_along(corrected))


def round_step(size):
    """Step the edges are rounded to: about 1/3000 of the tablet, a 1 / 2 / 5 multiple of a power
    of ten (5 points on a 15200 point Wacom, 0.05 mm on a 152 mm one)."""
    raw = size / 3000
    mag = 10 ** math.floor(math.log10(raw))
    return max(m * mag for m in (1, 2, 5) if m * mag <= raw * (1 + 1e-9))


def _fit_axis(samples, axis, lo, hi, screen, min_change):
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
    sig_a = abs(a - lo) > 2 * se_a and abs(a - lo) >= min_change
    sig_b = abs(b - hi) > 2 * se_b and abs(b - hi) >= min_change
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


def _fit_area(samples, area, tablet, screen, max_change):
    """(edges, suggested, clamped) for these samples."""
    top, bottom, left, right = area
    step = round_step(tablet[0])
    fl, fr = _fit_axis(samples, 0, left, right, screen, 2 * step)
    ft, fb = _fit_axis(samples, 1, top, bottom, screen, 2 * step)

    clamped = False
    for f, size, limit in ((fl, right - left, tablet[0]), (fr, right - left, tablet[0]),
                           (ft, bottom - top, tablet[1]), (fb, bottom - top, tablet[1])):
        d = f.suggested - f.current
        if not d:
            continue                    # unchanged edges keep their exact value
        if abs(d) > max_change * size:
            clamped = True
            d = math.copysign(max_change * size, d)
        v = min(limit, max(0, round((f.current + d) / step) * step))
        f.suggested = int(v) if step >= 1 else round(v, 4)
    for lo, hi in ((fl, fr), (ft, fb)):
        if hi.suggested <= lo.suggested:    # area outside the tablet: nothing sensible to suggest
            lo.suggested, hi.suggested = lo.current, hi.current
    edges = dict(zip(EDGE_NAMES, (ft, fb, fl, fr)))
    return edges, (ft.suggested, fb.suggested, fl.suggested, fr.suggested), clamped


def suggest_tablet_area(analyses, area, tablet=(15200, 9500), screen=(1920, 1080), max_change=0.15,
                        on_time=True):
    """area = (top, bottom, left, right) edges from the tablet's top-left corner, in any unit as long
    as tablet (width, height) uses the same one (see drivers.py).
    Assumes the area is mapped to the whole screen (the drivers' default).
    on_time: remove the part of each error that comes from tapping early or late, so it isn't
    mistaken for under / overaim (an area can't fix timing)."""
    top, bottom, left, right = area
    tapped = aim_samples(analyses)
    curve = timing_curve(tapped)
    samples = tapped_on_time(tapped, curve) if on_time else tapped
    edges, suggested, clamped = _fit_area(samples, area, tablet, screen, max_change)
    as_tapped = _fit_area(tapped, area, tablet, screen, max_change)[1] if on_time else suggested
    ft, fb, fl, fr = (edges[k] for k in EDGE_NAMES)

    # Replay every real click with the new area: same pen position, new screen position
    fixed = broken = 0
    for s in tapped:
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
    return TabletSuggestion(edges, tuple(area), suggested, clamped, len(tapped), misses_now,
                            misses_now - fixed + broken, fixed, broken,
                            over_under(samples, True), over_under(samples, False),
                            region_stats(samples), tap_timing(tapped, samples, curve), on_time, as_tapped)
