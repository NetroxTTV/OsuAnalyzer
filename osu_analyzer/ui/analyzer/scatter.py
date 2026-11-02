"""Every hit drawn inside one normalised hit circle (edge = the real circle radius).
Hover a dot / cross for details, click it to watch that note in the viewer."""

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QLinearGradient, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core import MISS_CAP, MISS_LABELS
from ...palette import EARLY_BLUE, JUDGE_COLORS, LATE_RED, MISS_COLORS
from ..theme import mix, qcolor, theme
from ..widgets import painter

NEUTRAL = "#e6e6ee"
COLORBAR_H = 46
PICK_RADIUS = 8


def timing_colour(err, w300):
    """Early (blue) -> on time (light) -> late (red)."""
    f = max(-1.0, min(1.0, err / w300)) if w300 else 0.0
    return mix(NEUTRAL, LATE_RED if f > 0 else EARLY_BLUE, abs(f))


def _stamp(o):
    m, s = divmod(o.time / 1000, 60)
    return f"#{o.index + 1} {o.kind} at {int(m)}:{s:06.3f}"


class HitScatter(QWidget):
    picked = Signal(object, object)    # (Analysis, Hit or Miss)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 360)
        self.setMouseTracking(True)
        self.stats = None
        self.color_by = "timing"
        self._layer = None
        self._hover = None          # ("hit" | "miss", index)
        self._points = None         # screen positions for picking
        theme.changed.connect(self._invalidate)

    def set_stats(self, stats, color_by):
        self.stats, self.color_by = stats, color_by
        self._hover = None
        self._invalidate()

    def _invalidate(self):
        self._layer = None
        self.update()

    def resizeEvent(self, _e):
        self._layer = None

    # ----------------------------------------------------------- geometry --

    def _plot_rect(self):
        bottom = COLORBAR_H if self.color_by == "timing" else 8
        h = self.height() - bottom - 8
        side = min(self.width() - 16, h)
        return QRectF((self.width() - side) / 2, 8 + (h - side) / 2, side, side)

    def _limit(self):
        s = self.stats
        lim = 1.15
        if len(s.hits):
            lim = max(lim, float(np.max(np.abs(np.concatenate([s.xs, s.ys])))) + 0.05)
        if len(s.misses):
            lim = max(lim, float(min(s.miss_dists.max(initial=0), MISS_CAP)) + 0.12)
        return lim

    def _mapper(self):
        r = self._plot_rect()
        scale = r.width() / 2 / self._limit()
        c = r.center()
        return c, scale

    # ------------------------------------------------------------ drawing --

    def _build_layer(self):
        dpr = self.devicePixelRatioF()
        pm = QPixmap(round(self.width() * dpr), round(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = painter(pm)
        s = self.stats
        c, k = self._mapper()

        def P(x, y):
            return QPointF(c.x() + x * k, c.y() - y * k)

        # The hit circle, guide rings and axes
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.accent_soft(0.07))
        p.drawEllipse(c, k, k)
        p.setPen(QPen(theme.accent, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, k, k)
        dash = QPen(qcolor("#ffffff", 0.13), 1, Qt.PenStyle.CustomDashLine)
        dash.setDashPattern([3, 4])
        small = theme.font(8)
        p.setFont(small)
        for rr in (0.25, 0.5, 0.75):
            p.setPen(dash)
            p.drawEllipse(c, rr * k, rr * k)
            p.setPen(qcolor(theme.muted, 0.75))
            p.drawText(P(rr * 0.707 + 0.015, rr * 0.707 + 0.015), f"{int(rr * 100)}%")
        p.setPen(QPen(qcolor("#ffffff", 0.08), 1))
        p.drawLines([QLineF(P(-1, 0), P(1, 0)), QLineF(P(0, -1), P(0, 1))])

        if s.frame == "movement":
            p.setPen(QPen(theme.muted, 1.5))
            a, b = P(0.55, -1.1), P(0.95, -1.1)
            p.drawLine(a, b)
            p.drawLines([QLineF(b, b + QPointF(-7, -4)), QLineF(b, b + QPointF(-7, 4))])
            p.setFont(theme.font(9))
            p.drawText(QRectF(a.x() - 200, a.y() - 10, 192, 20),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "movement direction")
            for x, text, angle in ((1.06, "overshoot", 90), (-1.06, "undershoot", -90)):
                p.save()
                p.translate(P(x, 0))
                p.rotate(angle)
                p.drawText(QRectF(-60, -10, 120, 20), Qt.AlignmentFlag.AlignCenter, text)
                p.restore()

        mxs, mys, pinned = s.pinned_misses()
        if pinned.any():
            ring = QPen(qcolor(theme.muted, 0.35), 1, Qt.PenStyle.CustomDashLine)
            ring.setDashPattern([2, 4])
            p.setPen(ring)
            p.drawEllipse(c, MISS_CAP * k, MISS_CAP * k)
            p.setPen(qcolor(theme.muted, 0.8))
            p.setFont(small)
            p.drawText(P(MISS_CAP * 0.707 + 0.02, -MISS_CAP * 0.707 - 0.08), f"{int(MISS_CAP * 100)}%+")

        # Hits
        dot = 3.4 if len(s.hits) < 600 else 2.4
        w300 = s.windows[0]
        p.setPen(Qt.PenStyle.NoPen)
        pts = []
        for x, y, h in zip(s.xs, s.ys, s.hits):
            col = (timing_colour(h.error, w300) if self.color_by == "timing"
                   else qcolor(JUDGE_COLORS[h.judgement]))
            col.setAlphaF(0.85)
            p.setBrush(col)
            pt = P(x, y)
            pts.append((pt.x(), pt.y()))
            p.drawEllipse(pt, dot, dot)

        # Spread ellipses (1σ and 2σ)
        ell = s.ellipse()
        if ell:
            (ex, ey), (w, h), angle = ell
            for n, style in ((1, Qt.PenStyle.SolidLine), (2, Qt.PenStyle.DashLine)):
                p.save()
                p.translate(P(ex, ey))
                p.rotate(-angle)
                p.setPen(QPen(qcolor(theme.text, 0.55), 1.3, style))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(0, 0), n * w / 2 * k, n * h / 2 * k)
                p.restore()

        # Average hit
        mx, my = s.mean
        p.setPen(QPen(qcolor(theme.gold, 0.9), 2))
        p.drawLine(c, P(mx, my))
        p.setPen(QPen(qcolor(theme.text, 0.6), 1.5))
        p.drawLines([QLineF(c.x() - 7, c.y(), c.x() + 7, c.y()), QLineF(c.x(), c.y() - 7, c.x(), c.y() + 7)])
        self._cross(p, P(mx, my), 8, theme.gold, 4.5, outline=True)

        # Misses
        mpts = []
        for x, y, m, pin in zip(mxs, mys, s.misses, pinned):
            pt = P(x, y)
            mpts.append((pt.x(), pt.y()))
            self._cross(p, pt, 5, qcolor(MISS_COLORS[m.reason], 0.55 if pin else 0.95), 2.2)

        if self.color_by == "timing":
            self._colorbar(p, w300)
        p.end()
        self._layer = pm
        self._points = (np.array(pts).reshape(-1, 2), np.array(mpts).reshape(-1, 2))

    @staticmethod
    def _cross(p, pt, size, colour, width, outline=False):
        lines = [QLineF(pt.x() - size, pt.y() - size, pt.x() + size, pt.y() + size),
                 QLineF(pt.x() - size, pt.y() + size, pt.x() + size, pt.y() - size)]
        if outline:
            pen = QPen(QColor("#000000"), width + 2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLines(lines)
        pen = QPen(colour, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLines(lines)

    def _colorbar(self, p, w300):
        w = min(420.0, self.width() * 0.6)
        bar = QRectF((self.width() - w) / 2, self.height() - COLORBAR_H + 10, w, 8)
        g = QLinearGradient(bar.left(), 0, bar.right(), 0)
        g.setColorAt(0, qcolor(EARLY_BLUE))
        g.setColorAt(0.5, qcolor(NEUTRAL))
        g.setColorAt(1, qcolor(LATE_RED))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(bar, 4, 4)
        p.setFont(theme.font(8.5))
        p.setPen(theme.muted)
        y = bar.bottom() + 4
        p.drawText(QRectF(bar.left() - 60, y, 120, 16), Qt.AlignmentFlag.AlignCenter, f"-{w300:.0f} ms  early")
        p.drawText(QRectF(bar.center().x() - 60, y, 120, 16), Qt.AlignmentFlag.AlignCenter, "0")
        p.drawText(QRectF(bar.right() - 60, y, 120, 16), Qt.AlignmentFlag.AlignCenter, f"late  +{w300:.0f} ms")

    def paintEvent(self, _e):
        if not self.stats or self.stats.empty:
            return
        if self._layer is None:
            self._build_layer()
        p = painter(self)
        p.drawPixmap(0, 0, self._layer)
        if self._hover:
            self._paint_tooltip(p)

    def _paint_tooltip(self, p):
        kind, i = self._hover
        s = self.stats
        hits, misses = self._points
        x, y = (hits if kind == "hit" else misses)[i]
        if kind == "hit":
            h = s.hits[i]
            lines = [_stamp(h), f"{h.error:+.0f} ms  ·  {h.judgement}",
                     f"{s.dists[i] * 100:.0f}% of radius from the centre"]
            colour = qcolor(JUDGE_COLORS[h.judgement])
        else:
            m = s.misses[i]
            when = "" if m.error is None else f", {m.error:+.0f} ms"
            lines = [_stamp(m), f"Miss: {MISS_LABELS[m.reason]}{when}",
                     f"{s.miss_dists[i] * 100:.0f}% of radius from the centre"]
            colour = qcolor(MISS_COLORS[m.reason])
        lines.append("Click to watch it in the viewer")
        p.setPen(QPen(colour, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(x, y), 7, 7)

        fonts = [theme.semibold(9), theme.font(9), theme.font(9), theme.font(8.5)]
        widths = [QFontMetricsF(f).horizontalAdvance(t) for f, t in zip(fonts, lines)]
        w, h = max(widths) + 24, 18 * len(lines) + 16
        bx = x + 14 if x + 14 + w < self.width() else x - 14 - w
        by = min(max(4, y - h / 2), self.height() - h - 4)
        box = QRectF(bx, by, w, h)
        p.setPen(qcolor("#ffffff", 0.08))
        p.setBrush(qcolor(theme.elevated, 0.97))
        p.drawRoundedRect(box, 9, 9)
        for n, (font, text) in enumerate(zip(fonts, lines)):
            p.setFont(font)
            p.setPen(theme.text if n < 3 else theme.accent)
            p.drawText(QRectF(bx + 12, by + 8 + n * 18, w - 24, 18), Qt.AlignmentFlag.AlignVCenter, text)

    # ------------------------------------------------------------ picking --

    def _nearest(self, pos):
        if self._points is None:
            return None
        best, best_d = None, PICK_RADIUS
        for kind, pts in (("miss", self._points[1]), ("hit", self._points[0])):
            if len(pts):
                d = np.hypot(pts[:, 0] - pos.x(), pts[:, 1] - pos.y())
                i = int(np.argmin(d))
                if d[i] < best_d:
                    best, best_d = (kind, i), float(d[i])
        return best

    def mouseMoveEvent(self, e):
        h = self._nearest(e.position())
        if h != self._hover:
            self._hover = h
            self.setCursor(Qt.CursorShape.PointingHandCursor if h else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _e):
        if self._hover:
            self._hover = None
            self.update()

    def mousePressEvent(self, e):
        h = self._nearest(e.position())
        if h and e.button() == Qt.MouseButton.LeftButton:
            kind, i = h
            s = self.stats
            if kind == "hit":
                self.picked.emit(s.owners[i], s.hits[i])
            else:
                self.picked.emit(s.miss_owners[i], s.misses[i])

