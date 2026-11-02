"""The app logo: a hit circle with the average-hit dot, on an accent tile."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QLinearGradient, QPen
from PySide6.QtWidgets import QWidget

from ..theme import mix, theme
from .base import painter


def paint_brand(p, rect, accent=None):
    """Draw the logo in rect (QRectF), in `accent` (the theme accent by default)."""
    accent = accent or theme.accent
    s = rect.width()
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0, mix(accent, "#ffffff", 0.16))
    g.setColorAt(1, mix(accent, "#000000", 0.12))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(rect, s * 0.28, s * 0.28)
    ink = theme.ink_on(accent)
    c = rect.center()
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(ink, s * 0.062))
    p.drawEllipse(c, s * 0.28, s * 0.28)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ink)
    p.drawEllipse(QPointF(c.x() + s * 0.083, c.y() - s * 0.055), s * 0.083, s * 0.083)


class BrandMark(QWidget):
    def __init__(self, size=36, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        paint_brand(painter(self), QRectF(self.rect()))
