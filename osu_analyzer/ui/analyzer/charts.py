"""Small charts for the stats column: timing histogram and an over / underaim split bar."""

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import qcolor, theme
from ..widgets import painter

BINS = 41


class TimingHistogram(QWidget):
    """Distribution of the timing errors over ±(100 window); gold line = mean."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.counts, self.span, self.mean = None, 1.0, 0.0

    def sizeHint(self):
        return QSize(300, 120)

    def set_data(self, errors, span, mean):
        self.span, self.mean = span, mean
        self.counts, _ = np.histogram(np.clip(errors, -span, span), bins=np.linspace(-span, span, BINS + 1))
        self.update()

    def paintEvent(self, _e):
        if self.counts is None:
            return
        p = painter(self)
        plot = QRectF(0, 4, self.width(), self.height() - 24)
        peak = max(1, int(self.counts.max()))
        bw = plot.width() / BINS
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.accent)
        for i, n in enumerate(self.counts):
            if n:
                h = max(2.0, plot.height() * n / peak)
                p.drawRoundedRect(QRectF(plot.x() + i * bw + 1, plot.bottom() - h, bw - 2, h), 1.5, 1.5)

        def X(ms):
            return plot.x() + (ms + self.span) / (2 * self.span) * plot.width()

        p.setPen(QPen(qcolor(theme.text, 0.35), 1))
        p.drawLine(QPointF(X(0), plot.top()), QPointF(X(0), plot.bottom()))
        p.setPen(QPen(theme.gold, 2))
        m = max(-self.span, min(self.span, self.mean))
        p.drawLine(QPointF(X(m), plot.top()), QPointF(X(m), plot.bottom()))
        p.setPen(QPen(qcolor("#ffffff", 0.1), 1))
        p.drawLine(QPointF(plot.left(), plot.bottom() + 0.5), QPointF(plot.right(), plot.bottom() + 0.5))
        p.setFont(theme.font(8))
        p.setPen(theme.muted)
        y = plot.bottom() + 4
        p.drawText(QRectF(plot.left(), y, 80, 16), Qt.AlignmentFlag.AlignLeft, f"-{self.span:.0f} ms")
        p.drawText(QRectF(X(0) - 30, y, 60, 16), Qt.AlignmentFlag.AlignCenter, "0")
        p.drawText(QRectF(plot.right() - 80, y, 80, 16), Qt.AlignmentFlag.AlignRight, f"+{self.span:.0f} ms")


class SplitBar(QWidget):
    """Two-part bar: overaim share (accent) vs underaim (neutral)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self.share = None

    def set_share(self, share):
        self.share = share
        self.update()

    def paintEvent(self, _e):
        p = painter(self)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("#ffffff", 0.12))
        p.drawRoundedRect(r, 4, 4)
        if self.share:
            p.setBrush(theme.accent)
            p.drawRoundedRect(QRectF(0, 0, max(r.height(), r.width() * self.share), r.height()), 4, 4)
