"""Buttons: text / icon buttons in three variants, and the round play button."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QFontMetricsF, QPainterPath
from PySide6.QtWidgets import QAbstractButton, QSizePolicy

from .. import icons
from ..theme import mix, qcolor, theme
from .base import Hover, painter


class Button(QAbstractButton):
    """Rounded button. variant: 'primary' (accent), 'secondary' (raised) or 'ghost' (flat)."""

    def __init__(self, text="", icon=None, variant="secondary", parent=None, compact=False):
        super().__init__(parent)
        self.setText(text)
        self.glyph = icon
        self.variant = variant
        self.compact = compact
        self.hover = Hover(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _font(self):
        return theme.semibold(9.5 if self.compact else 10)

    def sizeHint(self):
        h = 30 if self.compact else 36
        pad = 12 if self.compact else 16
        w = 0.0
        if self.text():
            w += QFontMetricsF(self._font()).horizontalAdvance(self.text())
        if self.glyph:
            w += 16 + (8 if self.text() else 0)
        if not self.text():
            return QSize(h, h)
        return QSize(round(w + 2 * pad), h)

    def _colours(self):
        """(background, foreground)."""
        hv = self.hover.value
        if self.variant == "primary":
            bg = theme.accent_pressed if self.isDown() else mix(theme.accent, theme.accent_hover, hv)
            return bg, theme.on_accent
        if self.variant == "secondary":
            bg = mix(theme.elevated, "#30303e", hv)
            if self.isDown():
                bg = theme.elevated
            return bg, theme.text
        bg = qcolor("#ffffff", 0.07 * hv + (0.04 if self.isDown() else 0))
        return bg, mix(theme.muted, theme.text, hv)

    def paintEvent(self, _event):
        p = painter(self)
        if not self.isEnabled():
            p.setOpacity(0.45)
        bg, fg = self._colours()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 8, 8)
        if self.variant == "secondary":
            p.setPen(qcolor("#ffffff", 0.06))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 8, 8)
        font = self._font()
        fm = QFontMetricsF(font)
        tw = fm.horizontalAdvance(self.text()) if self.text() else 0
        iw = 16 if self.glyph else 0
        gap = 8 if self.text() and self.glyph else 0
        x = (self.width() - (tw + iw + gap)) / 2
        if self.glyph:
            icons.draw_icon(p, QRectF(x, 0, iw, self.height()), self.glyph, fg, 14 if self.compact else 15)
        if self.text():
            p.setFont(font)
            p.setPen(fg)
            p.drawText(QRectF(x + iw + gap, 0, tw + 2, self.height()), Qt.AlignmentFlag.AlignVCenter,
                       self.text())


class IconButton(Button):
    """Square icon-only button (ghost by default) with a tooltip."""

    def __init__(self, glyph, tooltip="", parent=None, size=34, variant="ghost", active=False):
        super().__init__("", glyph, variant, parent)
        self.setToolTip(tooltip)
        self._size = size
        self.active = active

    def sizeHint(self):
        return QSize(self._size, self._size)

    def set_active(self, on):
        self.active = on
        self.update()

    def paintEvent(self, _event):
        p = painter(self)
        bg, fg = self._colours()
        if self.active:
            bg, fg = theme.accent_soft(0.18), theme.accent
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        icons.draw_icon(p, self.rect(), self.glyph, fg, self._size * 0.45)


class PlayButton(QAbstractButton):
    """Round accent play / pause button (checked = playing)."""

    def __init__(self, parent=None, size=48):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hover = Hover(self)

    def paintEvent(self, _event):
        p = painter(self)
        s = self.width()
        c = s / 2
        glow = qcolor(theme.accent, 0.22 * self.hover.value)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(c, c), c, c)
        p.setBrush(theme.accent_pressed if self.isDown() else mix(theme.accent, theme.accent_hover,
                                                                   self.hover.value))
        p.drawEllipse(QPointF(c, c), c - 3, c - 3)
        p.setBrush(theme.on_accent)
        if self.isChecked():
            w, h = s * 0.085, s * 0.32
            for dx in (-s * 0.09, s * 0.09):
                p.drawRoundedRect(QRectF(c + dx - w / 2, c - h / 2, w, h), 1.5, 1.5)
        else:
            h = s * 0.17
            path = QPainterPath(QPointF(c - h * 0.6, c - h))
            path.lineTo(c - h * 0.6, c + h)
            path.lineTo(c + h * 1.1, c)
            path.closeSubpath()
            p.drawPath(path)

