"""Overlays around the playfield: the K1 / K2 key timeline (top) and the hit error bar (bottom)."""

import bisect
import math

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QFontMetricsF, QPen, QPolygonF

from ...core import KEY_LEFT, KEY_RIGHT
from ...palette import JUDGE_COLORS, K1_COLOR, K2_COLOR
from ..theme import qcolor, theme

TIMELINE_MS = 800    # the key timeline shows +/- this much real time around "now"
UR_TICK_MS = 6000    # how long a hit stays on the hit error bar
PANEL_ALPHA = 0.5


def _panel(p, rect, radius=12):
    p.setPen(qcolor("#ffffff", 0.06))
    p.setBrush(qcolor("#08080c", PANEL_ALPHA))
    p.drawRoundedRect(rect, radius, radius)


class KeyTimelineRenderer:
    """Scrolling strip: K1 presses / notes with their 300-100-50 windows / K2 presses,
    plus the two keys on the right (lit while held, with their press count)."""

    HEIGHT = 86
    KEYS_W = 84

    def paint(self, p, rect, scene, t):
        w300, w100, w50 = scene.w300, scene.w100, scene.w50
        win = TIMELINE_MS * scene.replay.rate          # half width in map time
        strip = QRectF(rect.x(), rect.y(), rect.width() - self.KEYS_W - 10, rect.height())
        _panel(p, strip)
        x0, x1 = strip.x() + 10, strip.right() - 10
        cx = (x0 + x1) / 2
        pxms = (x1 - x0) / 2 / win
        y = strip.y() + 8
        lanes = {"ruler": (y, y + 8), KEY_LEFT: (y + 11, y + 29), "notes": (y + 32, y + 50),
                 KEY_RIGHT: (y + 53, y + 71)}

        def X(ms):
            return min(x1, max(x0, cx + (ms - t) * pxms))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("#ffffff", 0.035))
        for name, (a, b) in lanes.items():
            if name != "ruler":
                p.drawRoundedRect(QRectF(x0, a, x1 - x0, b - a), 5, 5)

        # Ruler: a tick every 100 ms of map time
        ra, rb = lanes["ruler"]
        tick = QPen(qcolor("#ffffff", 0.3), 1)
        p.setPen(tick)
        first = math.ceil((t - win) / 100) * 100
        p.drawLines([QLineF(X(ms), rb - (6 if ms % 500 == 0 else 3), X(ms), rb)
                     for ms in range(int(first), int(t + win) + 1, 100)])

        # Notes: 50 / 100 / 300 windows, outline = result, dark line = exact note time
        na, nb = lanes["notes"]
        lo = bisect.bisect_left(scene.obj_times, t - win - w50 - scene.max_len)
        hi = bisect.bisect_right(scene.obj_times, t + win + w50)
        result_colours = {**JUDGE_COLORS, 0: theme.miss}
        for o in scene.objs[lo:hi]:
            if o.kind != "circle" and o.end_time >= t - win:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qcolor("#ffffff", 0.3))
                p.drawRoundedRect(QRectF(X(o.time), (na + nb) / 2 - 2, X(o.end_time) - X(o.time), 4), 2, 2)
            if o.kind == "spinner" or o.time + w50 < t - win:
                continue
            p.setPen(Qt.PenStyle.NoPen)
            for wnd, shade in ((w50, 0.10), (w100, 0.22), (w300, 0.7)):
                p.setBrush(qcolor("#ffffff", shade))
                p.drawRoundedRect(QRectF(X(o.time - wnd), na, X(o.time + wnd) - X(o.time - wnd), nb - na), 4, 4)
            res = scene.result.get(id(o))
            if res is not None:
                p.setPen(QPen(qcolor(result_colours[res]), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(X(o.time - w300), na, X(o.time + w300) - X(o.time - w300), nb - na), 4, 4)
            p.setPen(QPen(qcolor("#000000", 0.6), 1))
            p.drawLine(QPointF(X(o.time), na + 2), QPointF(X(o.time), nb - 2))

        # Key presses: bar while held + a tick at the press reaching into the note lane
        keys_now = scene.cursor.at(t)[2]
        key_font = theme.semibold(10)
        count_font = theme.font(8.5)
        for i, (mask, colour, name) in enumerate(((KEY_LEFT, K1_COLOR, "K1"), (KEY_RIGHT, K2_COLOR, "K2"))):
            segs, starts, longest = scene.key_segs[mask]
            la, lb = lanes[mask]
            lo = bisect.bisect_left(starts, t - win - longest)
            hi = bisect.bisect_right(starts, t + win)
            for a, b in segs[lo:hi]:
                if b < t - win:
                    continue
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qcolor(colour))
                p.drawRoundedRect(QRectF(X(a), la, max(2.0, X(b) - X(a)), lb - la), 5, 5)
                if a >= t - win:
                    ta, tb = (la, nb) if mask == KEY_LEFT else (na, lb)
                    p.setPen(QPen(qcolor("#ffffff", 0.9), 2))
                    p.drawLine(QPointF(X(a), ta), QPointF(X(a), tb))

            # Key box on the right: K1 on top, K2 below
            held = keys_now & mask
            box = QRectF(rect.right() - self.KEYS_W, rect.y() + i * (rect.height() / 2 + 2),
                         self.KEYS_W, rect.height() / 2 - 2)
            if held:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qcolor(colour))
                p.drawRoundedRect(box, 10, 10)
            else:
                _panel(p, box, 10)
            p.setFont(key_font)
            p.setPen(qcolor("#14141a") if held else theme.text)
            p.drawText(box.adjusted(14, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, name)
            p.setFont(count_font)
            p.setPen(qcolor("#14141a") if held else theme.muted)
            p.drawText(box.adjusted(0, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       str(bisect.bisect_right(starts, t)))

        # Now
        p.setPen(QPen(theme.gold, 2))
        p.drawLine(QPointF(cx, strip.y() + 4), QPointF(cx, strip.bottom() - 4))


class HitErrorRenderer:
    """osu!-style hit error meter; judgement counts on its left, unstable rate on its right."""

    HEIGHT = 56

    def paint(self, p, rect, scene, t):
        _panel(p, rect, 14)
        w300, w100, w50 = scene.w300, scene.w100, scene.w50
        half = min(220.0, rect.width() * 0.2)
        bx, by = rect.center().x(), rect.center().y()
        sc = half / w50
        p.setPen(Qt.PenStyle.NoPen)
        for wnd, j in ((w50, 50), (w100, 100), (w300, 300)):
            p.setBrush(qcolor(JUDGE_COLORS[j], 0.55))
            p.drawRoundedRect(QRectF(bx - wnd * sc, by - 3, 2 * wnd * sc, 6), 3, 3)
        lo = bisect.bisect_left(scene.hit_times, t - UR_TICK_MS)
        n = bisect.bisect_right(scene.hit_times, t)
        for et, err, j in scene.hit_seq[lo:n]:
            f = 1 - (t - et) / UR_TICK_MS
            x = bx + max(-w50, min(w50, err)) * sc
            pen = QPen(qcolor(JUDGE_COLORS[j], f), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(x, by - 11), QPointF(x, by + 11))
        centre = QPen(theme.text, 2)
        centre.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(centre)
        p.drawLine(QPointF(bx, by - 14), QPointF(bx, by + 14))
        recent = scene.hit_seq[max(0, n - 20):n]
        if recent:
            m = sum(e for _, e, _ in recent) / len(recent)
            x = bx + max(-w50, min(w50, m)) * sc
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.gold)
            p.drawPolygon(QPolygonF([QPointF(x, by - 15), QPointF(x - 6, by - 24), QPointF(x + 6, by - 24)]))

        small = theme.font(8.5)
        p.setFont(small)
        p.setPen(theme.muted)
        p.drawText(QRectF(bx - half - 60, rect.y(), 50, rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "early")
        p.drawText(QRectF(bx + half + 10, rect.y(), 50, rect.height()), Qt.AlignmentFlag.AlignVCenter, "late")

        # Judgement counts, right-aligned on the left of the bar
        counts = scene.counts_at(t)
        big = theme.semibold(11)
        fm = QFontMetricsF(big)
        x = bx - half - 76
        p.setFont(big)
        for j, text in ((0, "✕"), (50, "50"), (100, "100"), (300, "300")):
            s = f"{text} {counts[j]}"
            w = fm.horizontalAdvance(s)
            if x - w < rect.x() + 10:
                break
            p.setPen(theme.miss if j == 0 else qcolor(JUDGE_COLORS[j]))
            p.drawText(QRectF(x - w, rect.y(), w + 2, rect.height()), Qt.AlignmentFlag.AlignVCenter, s)
            x -= w + 18

        # Unstable rate on the right of the bar
        ur = scene.unstable_rate_at(t)
        ur_text = f"UR {ur[0]:.1f}" if ur else "UR -"
        x = bx + half + 68
        p.setFont(big)
        p.setPen(theme.text)
        p.drawText(QRectF(x, rect.y(), 200, rect.height()), Qt.AlignmentFlag.AlignVCenter, ur_text)
        if ur:
            p.setFont(theme.font(9))
            p.setPen(theme.muted)
            p.drawText(QRectF(x + fm.horizontalAdvance(ur_text) + 12, rect.y(), 200, rect.height()),
                       Qt.AlignmentFlag.AlignVCenter, f"avg {ur[1]:+.1f} ms")
