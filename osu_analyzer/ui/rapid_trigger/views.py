"""Drawings of the Rapid Trigger page: the settings as bars, and how fast you re-press a key."""

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import qcolor, theme
from ..widgets import painter

INNER = "#121218"
ROWS = (("actuation", "Actuation point"), ("press", "RT press"), ("release", "RT release"))


class SettingsBars(QWidget):
    """Each setting as a bar in mm: the current value (dashed tick) and the suggested one (accent)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(3 * 34 + 44)
        self.current, self.suggested = None, None

    def sizeHint(self):
        return QSize(400, 3 * 34 + 44)

    def set_data(self, current, suggested):
        self.current, self.suggested = current, suggested
        self.update()

    def paintEvent(self, _e):
        p = painter(self)
        values = [getattr(s, k) for s in (self.current, self.suggested) if s for k, _ in ROWS]
        top = max([2.0] + [v * 1.1 for v in values])
        top = math.ceil(top * 2) / 2                     # scale in 0.5 mm steps
        name_w, value_w = 112, 70
        x0, x1 = name_w, self.width() - value_w
        X = lambda mm: x0 + (x1 - x0) * mm / top        # noqa: E731
        small = theme.font(9)

        for i, (key, name) in enumerate(ROWS):
            y = 4 + i * 34
            track = QRectF(x0, y + 6, x1 - x0, 14)
            p.setFont(small)
            p.setPen(theme.muted)
            p.drawText(QRectF(0, y, name_w - 10, 26), Qt.AlignmentFlag.AlignVCenter, name)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(INNER))
            p.drawRoundedRect(track, 7, 7)
            if self.suggested:
                v = getattr(self.suggested, key)
                p.setBrush(theme.accent_soft(0.55))
                p.drawRoundedRect(QRectF(x0, y + 6, max(14.0, X(v) - x0), 14), 7, 7)
                p.setFont(theme.semibold(9.5))
                p.setPen(theme.accent)
                p.drawText(QRectF(x1 + 10, y, value_w - 10, 26), Qt.AlignmentFlag.AlignVCenter, f"{v:.2f} mm")
            if self.current:
                v = getattr(self.current, key)
                p.setPen(QPen(theme.text, 1.5, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(X(v), y + 2), QPointF(X(v), y + 24))
                if not self.suggested:
                    p.setFont(small)
                    p.setPen(theme.text)
                    p.drawText(QRectF(x1 + 10, y, value_w - 10, 26), Qt.AlignmentFlag.AlignVCenter,
                               f"{v:.2f} mm")

        y = 4 + 3 * 34
        p.setFont(small)
        p.setPen(theme.muted)
        p.drawText(QRectF(x0, y - 4, 40, 14), Qt.AlignmentFlag.AlignLeft, "0")
        p.drawText(QRectF(x1 - 60, y - 4, 60, 14), Qt.AlignmentFlag.AlignRight, f"{top:g} mm")
        y += 12
        p.setPen(QPen(theme.text, 1.2, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x0, y + 8), QPointF(x0 + 22, y + 8))
        p.drawText(QRectF(x0 + 30, y, 140, 16), Qt.AlignmentFlag.AlignVCenter, "current")
        if self.suggested:
            p.setPen(QPen(theme.accent, 2.5))
            p.drawLine(QPointF(x0 + 110, y + 8), QPointF(x0 + 132, y + 8))
            p.setPen(theme.accent)
            p.drawText(QRectF(x0 + 140, y, 160, 16), Qt.AlignmentFlag.AlignVCenter, "suggested")


class IntervalChart(QWidget):
    """Time between two presses of the same key on notes (real ms), with the fastest 10 % marked."""

    BIN, MAX = 10, 400

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(220)
        self.intervals, self.fast = [], None

    def set_data(self, intervals, fast):
        self.intervals, self.fast = list(intervals), fast
        self.update()

    def paintEvent(self, _e):
        p = painter(self)
        plot = QRectF(8, 26, self.width() - 16, self.height() - 52)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(INNER))
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        if not self.intervals:
            p.setPen(theme.muted)
            p.setFont(theme.font(10))
            p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, "Pick a replay to see how you tap")
            return
        plot.adjust(10, 0, -10, 0)
        n = self.MAX // self.BIN
        counts = [0] * n
        for v in self.intervals:
            counts[min(n - 1, int(v // self.BIN))] += 1
        most = max(counts) or 1
        bw = plot.width() / n
        X = lambda ms: plot.left() + plot.width() * min(ms, self.MAX) / self.MAX   # noqa: E731
        for i, c in enumerate(counts):
            if not c:
                continue
            h = plot.height() * c / most
            fast = self.fast is not None and (i + 1) * self.BIN <= self.fast + self.BIN
            p.setBrush(theme.accent if fast else theme.accent_soft(0.45))
            p.drawRoundedRect(QRectF(plot.left() + i * bw + 1, plot.bottom() - h, bw - 2, h), 2, 2)

        p.setFont(theme.font(8.5))
        p.setPen(theme.muted)
        for ms in range(0, self.MAX + 1, 50):
            x = X(ms)
            text = f"{ms}+" if ms == self.MAX else f"{ms}"
            p.drawText(QRectF(x - 25, plot.bottom() + 6, 50, 14), Qt.AlignmentFlag.AlignCenter, text)
        if self.fast is not None:
            x = X(self.fast)
            p.setPen(QPen(theme.gold, 1.5, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, plot.top() - 6), QPointF(x, plot.bottom()))
            p.setPen(theme.gold)
            p.setFont(theme.semibold(9))
            p.drawText(QRectF(x + 6, plot.top() - 22, 220, 16), Qt.AlignmentFlag.AlignVCenter,
                       f"fastest 10%: {self.fast:.0f} ms")
