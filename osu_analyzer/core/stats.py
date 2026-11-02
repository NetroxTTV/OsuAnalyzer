"""Summary of one or more analyses: where the hits land, spread, timing, aim.

Coordinates are in hit-circle radii (1 = the edge of the circle), with y pointing up.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from .tablet import aim_samples, over_under

MISS_REASONS = ("outside", "early", "no click")
MISS_LABELS = {"outside": "clicked outside", "early": "too early", "no click": "no click"}
MISS_CAP = 1.5  # misses farther than this (in radii) are pinned to this ring

_DIRECTIONS = ["right", "up-right", "up", "up-left", "left", "down-left", "down", "down-right"]


def to_plot(objs, frame):
    """(xs, ys, used) in radii for hits or misses. frame: 'screen' | 'movement'
    (rotated so the approach direction points right; objects without one are skipped)."""
    xs, ys, used = [], [], []
    for h in objs:
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
    return np.array(xs, dtype=float), np.array(ys, dtype=float), used


@dataclass
class HitStats:
    analyses: list
    frame: str
    # hits
    hits: list = field(default_factory=list)         # the hits that are plotted
    owners: list = field(default_factory=list)       # their Analysis
    xs: np.ndarray = None
    ys: np.ndarray = None
    errors: np.ndarray = None                        # ms, map time
    real_errors: np.ndarray = None                   # ms, real time (DT / HT)
    total_hits: int = 0
    # misses
    misses: list = field(default_factory=list)
    miss_owners: list = field(default_factory=list)
    mxs: np.ndarray = None
    mys: np.ndarray = None
    total_misses: int = 0

    @classmethod
    def compute(cls, analyses, frame="screen"):
        s = cls(list(analyses), frame)
        xs, ys, errs, real, mxs, mys = [], [], [], [], [], []
        for a in s.analyses:
            hx, hy, used = to_plot(a.hits, frame)
            xs.append(hx)
            ys.append(hy)
            s.hits += used
            s.owners += [a] * len(used)
            errs += [h.error for h in used]
            real += [h.error / a.replay.rate for h in used]
            mx, my, mused = to_plot(a.misses, frame)
            mxs.append(mx)
            mys.append(my)
            s.misses += mused
            s.miss_owners += [a] * len(mused)
            s.total_hits += len(a.hits)
            s.total_misses += len(a.misses)
        cat = lambda parts: np.concatenate(parts) if parts else np.zeros(0)  # noqa: E731
        s.xs, s.ys, s.mxs, s.mys = cat(xs), cat(ys), cat(mxs), cat(mys)
        s.errors, s.real_errors = np.array(errs, dtype=float), np.array(real, dtype=float)
        return s

    # ------------------------------------------------------------- basics --

    @property
    def empty(self):
        return not self.hits

    @property
    def windows(self):
        """Widest (300, 100, 50) windows over the analyses."""
        return tuple(max(a.windows[i] for a in self.analyses) for i in range(3))

    @property
    def mean(self):
        return (float(self.xs.mean()), float(self.ys.mean())) if self.hits else (0.0, 0.0)

    @property
    def offset(self):
        """Distance of the average hit from the centre, in radii."""
        return math.hypot(*self.mean)

    @property
    def offset_px(self):
        return self.offset * float(np.mean([h.radius for h in self.hits])) if self.hits else 0.0

    @property
    def dists(self):
        return np.hypot(self.xs, self.ys)

    @property
    def miss_dists(self):
        return np.hypot(self.mxs, self.mys)

    def pinned_misses(self):
        """Miss coordinates with the far ones pulled in to MISS_CAP, and which were pulled."""
        d = self.miss_dists
        pinned = d > MISS_CAP
        shrink = np.where(pinned, MISS_CAP / np.maximum(d, 1e-9), 1.0)
        return self.mxs * shrink, self.mys * shrink, pinned

    @property
    def direction(self):
        mx, my = self.mean
        if math.hypot(mx, my) <= 0.02:
            return "centred"
        if self.frame == "movement":
            parts = []
            if abs(mx) > 0.02:
                parts.append("overshoot" if mx > 0 else "undershoot")
            if abs(my) > 0.02:
                parts.append("left of path" if my > 0 else "right of path")
            return " + ".join(parts)
        ang = math.degrees(math.atan2(my, mx))
        return _DIRECTIONS[int(((ang + 22.5) % 360) // 45)]

    # -------------------------------------------------------------- spread --

    def ellipse(self):
        """1σ spread ellipse: (centre, (width, height), angle in degrees) or None."""
        if len(self.hits) < 3:
            return None
        vals, vecs = np.linalg.eigh(np.cov(self.xs, self.ys))
        vals = np.maximum(vals, 0)
        angle = math.degrees(math.atan2(vecs[1, 1], vecs[0, 1]))
        return self.mean, (2 * math.sqrt(vals[1]), 2 * math.sqrt(vals[0])), angle

    @property
    def mean_distance(self):
        return float(self.dists.mean()) if self.hits else 0.0

    @property
    def std(self):
        return (float(self.xs.std()), float(self.ys.std())) if self.hits else (0.0, 0.0)

    @property
    def inside_half(self):
        """Share of hits within 50% of the radius."""
        return float((self.dists <= 0.5).mean()) if self.hits else 0.0

    # -------------------------------------------------------------- timing --

    @property
    def mean_error(self):
        return float(self.errors.mean()) if self.hits else 0.0

    @property
    def unstable_rate(self):
        return float(np.std(self.real_errors) * 10) if len(self.hits) > 1 else 0.0

    # --------------------------------------------------------- judgements --

    @property
    def counts(self):
        return {j: sum(1 for h in self.hits if h.judgement == j) for j in (300, 100, 50)}

    @property
    def misses_by_reason(self):
        all_misses = [m for a in self.analyses for m in a.misses]
        return {r: sum(1 for m in all_misses if m.reason == r) for r in MISS_REASONS}

    @property
    def skipped(self):
        return self.total_hits - len(self.hits)

    # ---------------------------------------------------------------- aim --

    def aim_splits(self):
        """(misses, hits) AimSplit: over / underaim along the approach direction."""
        samples = aim_samples(self.analyses)
        return over_under(samples, True), over_under(samples, False)

    # -------------------------------------------------------------- title --

    @property
    def title(self):
        if len(self.analyses) == 1:
            bm = self.analyses[0].beatmap
            return f"{bm.artist} - {bm.title} [{bm.diff_name}]"
        return f"{len(self.analyses)} replays combined"

    @property
    def subtitle(self):
        if len(self.analyses) == 1:
            a = self.analyses[0]
            return (f"{a.replay.player}   +{a.replay.mod_string}   "
                    f"CS {a.beatmap.cs:.1f}  OD {a.beatmap.od:.1f}")
        return ", ".join(sorted({a.replay.player for a in self.analyses}))
