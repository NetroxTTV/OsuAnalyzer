"""Over / underaim and tablet area calibration."""

import math
from dataclasses import dataclass

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
