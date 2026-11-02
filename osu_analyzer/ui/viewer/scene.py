"""Everything the replay viewer needs about one analysis, precomputed once so that drawing
a frame is only lookups (bisect) at the current time."""

import bisect
import math

from ...core import KEY_LEFT, KEY_RIGHT, CursorTrack, key_presses, key_segments, preempt

DEFAULT_COMBO = [(255, 102, 170), (90, 200, 250), (126, 217, 87), (255, 179, 71)]
MISS_LEAD = 1200   # jumping to a miss lands this long (ms) before it


class ReplayScene:
    def __init__(self, analysis):
        a = self.analysis = analysis
        bm, rp = a.beatmap, a.replay
        self.beatmap, self.replay = bm, rp
        self.cursor = CursorTrack(rp.frames)
        self.frames, self.ftimes = rp.frames, self.cursor.times
        self.radius = a.radius
        self.preempt = preempt(bm.ar)
        self.fade_in = 400 * min(1.0, self.preempt / 450)
        self.w300, self.w100, self.w50 = a.windows
        self.objs = bm.objects
        self.starts = [o.time - self.preempt for o in self.objs]
        self.obj_times = [o.time for o in self.objs]
        self.max_len = max((o.end_time - o.time for o in self.objs), default=0)
        self.colours = bm.colours or DEFAULT_COMBO
        self._cum = {}

        playable = [o for o in self.objs if o.kind != "spinner"]
        self.head_done = {}   # id(object) -> time its head was judged
        self.result = {}      # id(object) -> 300 / 100 / 50 / 0 (miss)
        events = []           # (time, kind, pos, judgement)
        for h in a.hits:
            t = h.time + h.error
            self.head_done[id(playable[h.index])] = t
            self.result[id(playable[h.index])] = h.judgement
            events.append((t, "hit", h.pos, h.judgement))
        for m in a.misses:
            t = m.time + (m.error if m.reason == "early" else self.w50)
            self.head_done[id(playable[m.index])] = t
            self.result[id(playable[m.index])] = 0
            events.append((t, "miss", m.pos, None))
        events.sort(key=lambda e: e[0])
        self.events = events
        self.event_times = [e[0] for e in events]
        self.miss_times = [e[0] for e in events if e[1] == "miss"]
        self.count_times = {j: [e[0] for e in events if e[1] == "hit" and e[3] == j] for j in (300, 100, 50)}

        # Hit error bar: hits in the order they happened + running sums for the unstable rate
        self.hit_seq = sorted((h.time + h.error, h.error, h.judgement) for h in a.hits)
        self.hit_times = [hs[0] for hs in self.hit_seq]
        self.err_sum, self.err_sq = [0.0], [0.0]
        for _, e, _ in self.hit_seq:
            self.err_sum.append(self.err_sum[-1] + e)
            self.err_sq.append(self.err_sq[-1] + e * e)

        self.presses = key_presses(self.frames)
        self.press_times = [p[0] for p in self.presses]
        self.key_segs = {}    # mask -> (segments, their start times, longest)
        for mask in (KEY_LEFT, KEY_RIGHT):
            segs = key_segments(self.frames, mask)
            self.key_segs[mask] = (segs, [s[0] for s in segs], max((b - a for a, b in segs), default=0))

        first = self.objs[0].time if self.objs else 0
        self.t0 = max(0.0, first - 2000)
        self.t1 = max(self.cursor.end, self.objs[-1].end_time if self.objs else 0) + 500

    # ------------------------------------------------------------ queries --

    def visible(self, t):
        """[(object, head judged at)] on screen at t, latest first (so earlier ones end on top)."""
        hi = bisect.bisect_right(self.starts, t)
        out = []
        for i in range(hi - 1, -1, -1):
            o = self.objs[i]
            if o.time < t - self.max_len - 1000:
                break
            head_end = self.head_done.get(id(o), o.time + self.w50)
            if o.kind == "spinner":
                end = o.end_time
            elif o.kind == "circle":
                end = head_end + 150
            else:
                end = max(head_end, o.end_time) + 150
            if t <= end:
                out.append((o, head_end))
        return out

    def ball(self, o, t):
        """Slider ball position (unstacked) at time t."""
        pts = o.path
        cum = self._cum.get(id(o))
        if cum is None:
            cum = [0.0]
            for i in range(len(pts) - 1):
                cum.append(cum[-1] + math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]))
            self._cum[id(o)] = cum
        dur = max(1.0, o.end_time - o.time)
        p = min(max((t - o.time) / dur, 0.0), 1.0) * o.slides
        span = min(int(p), o.slides - 1)
        f = p - span
        if span % 2 == 1:
            f = 1 - f
        d = f * cum[-1]
        i = min(max(bisect.bisect_right(cum, d) - 1, 0), len(pts) - 2)
        seg = cum[i + 1] - cum[i]
        g = (d - cum[i]) / seg if seg > 0 else 0
        return pts[i][0] + (pts[i + 1][0] - pts[i][0]) * g, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * g

    def counts_at(self, t):
        """{300, 100, 50, 0: count} judged up to t (0 = misses)."""
        c = {j: bisect.bisect_right(self.count_times[j], t) for j in (300, 100, 50)}
        c[0] = bisect.bisect_right(self.miss_times, t)
        return c

    def unstable_rate_at(self, t):
        """(unstable rate, mean error) of the hits up to t, or None before two hits."""
        n = bisect.bisect_right(self.hit_times, t)
        if n < 2:
            return None
        mean = self.err_sum[n] / n
        ur = 10 * math.sqrt(max(0.0, self.err_sq[n] / n - mean * mean)) / self.replay.rate
        return ur, mean

    def next_miss(self, t):
        i = bisect.bisect_right(self.miss_times, t + MISS_LEAD + 5)
        return self.miss_times[i] - MISS_LEAD if i < len(self.miss_times) else None

    def prev_miss(self, t):
        i = bisect.bisect_left(self.miss_times, t + MISS_LEAD - 5) - 1
        return self.miss_times[i] - MISS_LEAD if i >= 0 else None

    @property
    def judged_marks(self):
        """(time, judgement) of the hits that weren't 300s, for the seek bar."""
        return [(et, j) for et, _e, j in self.hit_seq if j != 300]
