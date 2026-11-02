"""Draws the playfield at time t: notes, approach circles, sliders, judgements, clicks and cursor.
Everything is drawn in osu! pixels (512 x 384) through the painter's transform."""

import bisect

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QPen, QPolygonF

from ...core import KEY_LEFT, KEY_RIGHT
from ...palette import JUDGE_COLORS
from ..theme import qcolor, theme

TRAIL_MS = 160
CLICK_MARK_MS = 450
JUDGE_MS = 500
MISS_MS = 800
SPINNER_RADIUS = 170


def _pen(colour, width, cap=Qt.PenCapStyle.RoundCap):
    pen = QPen(colour, width)
    pen.setCapStyle(cap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


class PlayfieldRenderer:
    def __init__(self):
        self._bodies = {}      # id(slider) -> outline path of the slider body (osu!px)
        self._scene = None

    def _body(self, o, r):
        path = self._bodies.get(id(o))
        if path is None:
            sx, sy = o.stacked_pos[0] - o.pos[0], o.stacked_pos[1] - o.pos[1]
            line = QPainterPath()
            line.addPolygon(QPolygonF([QPointF(x + sx, y + sy) for x, y in o.path]))
            stroker = QPainterPathStroker()
            stroker.setWidth(2 * r)
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            path = stroker.createStroke(line).simplified()
            self._bodies[id(o)] = path
        return path

    @staticmethod
    def layout(rect, radius):
        """(scale, origin) fitting the playfield plus a circle radius around it in rect."""
        k = min(rect.width() / (512 + 2 * radius), rect.height() / (384 + 2 * radius))
        return k, QPointF(rect.center().x() - 256 * k, rect.center().y() - 192 * k)

    def paint(self, p, rect, scene, t):
        if scene is not self._scene:
            self._scene, self._bodies = scene, {}
        r = scene.radius
        k, origin = self.layout(rect, r)
        if k <= 0:
            return
        p.save()
        p.translate(origin)
        p.scale(k, k)

        border = QPen(qcolor("#ffffff", 0.10), 1)
        border.setCosmetic(True)
        p.setPen(border)
        p.setBrush(qcolor("#000000", 0.18))
        p.drawRoundedRect(QRectF(0, 0, 512, 384), 6, 6)

        number_font = theme.semibold()
        number_font.setPixelSize(max(6, int(r * 0.8)))
        white = QColor("#ffffff")

        for o, head_end in scene.visible(t):
            alpha = min(1.0, (t - (o.time - scene.preempt)) / scene.fade_in)
            col = QColor(*scene.colours[o.combo_index % len(scene.colours)])
            if o.kind == "spinner":
                self._spinner(p, o, t, alpha, col, number_font, scene)
                continue

            ball = None
            if o.kind == "slider" and o.path and len(o.path) > 1:
                fade = alpha if t <= o.end_time else max(0.0, 1 - (t - o.end_time) / 150) * alpha
                body = self._body(o, r)
                p.setPen(_pen(qcolor(white, 0.85 * fade), max(2.0, r * 0.1)))
                p.setBrush(qcolor(col.darker(320), 0.82 * fade))
                p.drawPath(body)
                sx, sy = o.stacked_pos[0] - o.pos[0], o.stacked_pos[1] - o.pos[1]
                if o.slides > 1 and t <= o.end_time:
                    end = QPointF(o.path[-1][0] + sx, o.path[-1][1] + sy)
                    p.setPen(qcolor(white, fade))
                    p.setFont(number_font)
                    p.drawText(QRectF(end.x() - r, end.y() - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, "↺")
                if o.time <= t <= o.end_time:
                    bx, by = scene.ball(o, t)
                    ball = QPointF(bx + sx, by + sy)

            if t <= head_end + 150:   # hit circle / slider head
                a2 = alpha if t <= head_end else alpha * max(0.0, 1 - (t - head_end) / 150)
                c = QPointF(*o.stacked_pos)
                p.setPen(_pen(qcolor(white, a2), max(2.0, r * 0.11)))
                p.setBrush(qcolor(col, a2 * 0.92))
                p.drawEllipse(c, r * 0.94, r * 0.94)
                p.setPen(qcolor(white, a2))
                p.setFont(number_font)
                p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter,
                           str(o.combo_number))
                if t < o.time:
                    ar = r * (1 + 3 * (o.time - t) / scene.preempt)
                    p.setPen(_pen(qcolor(col, alpha), max(1.5, r * 0.07)))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(c, ar, ar)
            if ball is not None:   # slider ball + follow circle, above the fading head
                p.setPen(_pen(qcolor(white, 0.9), max(1.5, r * 0.06)))
                p.setBrush(col)
                p.drawEllipse(ball, r * 0.9, r * 0.9)
                p.setPen(_pen(qcolor(col, 0.7), max(1.5, r * 0.06)))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(ball, r * 2.2, r * 2.2)

        self._judgements(p, scene, t, r)
        self._clicks(p, scene, t, r)
        self._cursor(p, scene, t, r)
        p.restore()

    def _spinner(self, p, o, t, alpha, col, font, scene):
        if t < o.time - scene.preempt:
            return
        c = QPointF(256, 192)
        prog = min(max((t - o.time) / max(1, o.end_time - o.time), 0), 1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_pen(qcolor("#ffffff", alpha * 0.6), 3))
        p.drawEllipse(c, SPINNER_RADIUS, SPINNER_RADIUS)
        rr = SPINNER_RADIUS * (1 - prog)
        p.setPen(_pen(qcolor(col, alpha), 2))
        p.drawEllipse(c, rr, rr)
        p.setFont(font)
        p.setPen(qcolor("#ffffff", alpha * 0.7))
        p.drawText(QRectF(156, 172, 200, 40), Qt.AlignmentFlag.AlignCenter, "spinner")

    def _judgements(self, p, scene, t, r):
        lo = bisect.bisect_left(scene.event_times, t - MISS_MS)
        hi = bisect.bisect_right(scene.event_times, t)
        font = theme.bold()
        font.setPixelSize(max(6, int(r * 0.55)))
        p.setFont(font)
        for et, kind, pos, judgement in scene.events[lo:hi]:
            age = t - et
            x, y = pos
            if kind == "miss":
                f = 1 - age / MISS_MS
                s = r * 0.6
                p.setPen(_pen(qcolor(theme.miss, f), max(3.0, r * 0.18)))
                p.drawLines([QLineF(x - s, y - s, x + s, y + s), QLineF(x - s, y + s, x + s, y - s)])
            elif age <= JUDGE_MS:
                f = 1 - age / JUDGE_MS
                p.setPen(qcolor(JUDGE_COLORS[judgement], f))
                p.drawText(QRectF(x - r * 1.5, y - r * 2.1, 3 * r, r * 1.2), Qt.AlignmentFlag.AlignCenter,
                           str(judgement))

    def _clicks(self, p, scene, t, r):
        lo = bisect.bisect_left(scene.press_times, t - CLICK_MARK_MS)
        hi = bisect.bisect_right(scene.press_times, t)
        p.setPen(Qt.PenStyle.NoPen)
        d = max(2.5, r * 0.13)
        for pt, x, y in scene.presses[lo:hi]:
            p.setBrush(qcolor(theme.gold, 1 - (t - pt) / CLICK_MARK_MS))
            p.drawEllipse(QPointF(x, y), d, d)

    def _cursor(self, p, scene, t, r):
        lo = bisect.bisect_left(scene.ftimes, t - TRAIL_MS)
        hi = bisect.bisect_right(scene.ftimes, t)
        cx, cy, keys = scene.cursor.at(t)
        trail = [QPointF(f[1], f[2]) for f in scene.frames[lo:hi]] + [QPointF(cx, cy)]
        n = len(trail)
        for i in range(1, n):
            f = i / n
            p.setPen(_pen(qcolor(theme.accent, f * 0.9), max(1.0, r * 0.12 * f)))
            p.drawLine(trail[i - 1], trail[i])
        c = QPointF(cx, cy)
        cr = max(4.0, r * 0.26)
        pressed = keys & (KEY_LEFT | KEY_RIGHT)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(theme.accent, 0.25))
        p.drawEllipse(c, cr * 1.8, cr * 1.8)
        p.setPen(_pen(QColor("#000000"), max(1.0, cr * 0.25)))
        p.setBrush(theme.gold if pressed else QColor("#ffffff"))
        p.drawEllipse(c, cr, cr)
