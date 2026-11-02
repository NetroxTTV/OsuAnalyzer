"""Drawings of the Tablet Zone page: the tablet with its areas, and the playfield heat map."""

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import mix, qcolor, theme
from ..widgets import painter

INNER = "#121218"


class TabletAreaView(QWidget):
    """The tablet, the current area (dashed) and the suggested one (accent)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tablet, self.area, self.suggested = (15200, 9500), None, None

    def sizeHint(self):
        return QSize(400, 230)

    def set_data(self, tablet, area, suggested):
        self.tablet, self.area, self.suggested = tablet, area, suggested
        self.update()

    def paintEvent(self, _e):
        p = painter(self)
        legend_h = 24
        tw, th = self.tablet
        k = min((self.width() - 4) / tw, (self.height() - legend_h - 4) / th)
        ox = (self.width() - tw * k) / 2
        oy = 2

        def rect(a):
            t, b, l, r = a
            return QRectF(ox + l * k, oy + t * k, (r - l) * k, (b - t) * k)

        p.setPen(QPen(theme.border, 1.5))
        p.setBrush(qcolor(INNER))
        p.drawRoundedRect(QRectF(ox, oy, tw * k, th * k), 14, 14)
        if self.suggested:
            p.setPen(QPen(theme.accent, 2))
            p.setBrush(theme.accent_soft(0.18))
            p.drawRoundedRect(rect(self.suggested), 4, 4)
        if self.area:
            pen = QPen(theme.text, 1.2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect(self.area), 4, 4)

        y = oy + th * k + 8
        p.setFont(theme.font(9))
        pen = QPen(theme.text, 1.2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(ox, y + 8), QPointF(ox + 22, y + 8))
        p.drawText(QRectF(ox + 30, y, 140, 16), Qt.AlignmentFlag.AlignVCenter, "current area")
        if self.suggested:
            p.setPen(QPen(theme.accent, 2.5))
            p.drawLine(QPointF(ox + 150, y + 8), QPointF(ox + 172, y + 8))
            p.setPen(theme.accent)
            p.drawText(QRectF(ox + 180, y, 160, 16), Qt.AlignmentFlag.AlignVCenter, "suggested area")


class FieldHeatmap(QWidget):
    """The playfield in 3 x 3 regions: misses (heat), average cursor error (arrow, 4x), counts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(260)
        self.suggestion = None

    def set_suggestion(self, s):
        self.suggestion = s
        self.update()

    def paintEvent(self, _e):
        p = painter(self)
        k = min((self.width() - 4) / 512, (self.height() - 4) / 384)
        ox, oy = (self.width() - 512 * k) / 2, 2
        field = QRectF(ox, oy, 512 * k, 384 * k)
        cw, ch = field.width() / 3, field.height() / 3
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(INNER))
        p.drawRoundedRect(field, 12, 12)
        s = self.suggestion
        if not s:
            p.setPen(theme.muted)
            p.setFont(theme.font(10))
            p.drawText(field, Qt.AlignmentFlag.AlignCenter, "Pick a replay to see where you miss")
            return
        most = max((r.misses.total for r in s.regions), default=0) or 1
        small, body = theme.font(8.5), theme.semibold(9.5)
        for r in s.regions:
            cell = QRectF(ox + r.col * cw, oy + r.row * ch, cw, ch).adjusted(2, 2, -2, -2)
            heat = r.misses.total / most
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(mix(INNER, theme.miss, 0.45 * heat) if r.misses.total else qcolor("#ffffff", 0.03))
            p.drawRoundedRect(cell, 10, 10)
            c = cell.center()
            if r.n >= 15:
                ex, ey = r.mean_err
                scale = min(cw, ch) * 0.9      # 1 radius of error = 0.9 cell (4x bigger visually)
                a = QPointF(c.x() + ex * scale, c.y() + ey * scale)
                lim = min(cw, ch) * 0.38
                d = math.hypot(a.x() - c.x(), a.y() - c.y())
                if d > lim:
                    a = QPointF(c.x() + (a.x() - c.x()) * lim / d, c.y() + (a.y() - c.y()) * lim / d)
                    d = lim
                p.setBrush(theme.muted)
                p.drawEllipse(c, 3, 3)
                if d > 2:
                    self._arrow(p, c, a)
                p.setFont(small)
                p.setPen(theme.muted)
                p.drawText(cell.adjusted(10, 8, -10, -8), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                           f"{math.hypot(ex, ey) * 100:.0f}% r")
            p.setFont(small)
            p.setPen(theme.muted)
            p.drawText(cell.adjusted(10, 8, -10, -8), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                       f"{r.n} clicks")
            p.setFont(body)
            p.setPen(theme.text)
            p.drawText(cell.adjusted(8, 8, -8, -10), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       f"{r.misses.over} over  ·  {r.misses.under} under")

    @staticmethod
    def _arrow(p, a, b):
        pen = QPen(theme.gold, 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(a, b)
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        for side in (-1, 1):
            q = QPointF(b.x() - 10 * math.cos(ang + side * 0.45), b.y() - 10 * math.sin(ang + side * 0.45))
            p.drawLine(b, q)
