"""Surfaces: rounded cards, small pills and empty-state placeholders."""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from .. import icons
from ..theme import qcolor, theme
from .base import label, painter


class Card(QFrame):
    """Rounded panel; add children to .body (a QVBoxLayout).
    color / border are theme attribute names ('card', 'accent'...) or colours."""

    def __init__(self, parent=None, title=None, padding=(20, 18, 20, 18), radius=14, color="card",
                 border=None, spacing=10):
        super().__init__(parent)
        self.radius, self.color, self.border = radius, color, border
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*padding)
        self.body.setSpacing(spacing)
        if title:
            self.title = label(title.upper(), "overline")
            self.body.addWidget(self.title)

    def _resolve(self, c):
        return getattr(theme, c) if isinstance(c, str) and hasattr(theme, c) else qcolor(c)

    def set_border(self, border):
        self.border = border
        self.update()

    def paintEvent(self, _e):
        p = painter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(self._resolve(self.color))
        if self.border:
            p.setPen(self._resolve(self.border))
        else:
            p.setPen(qcolor("#ffffff", 0.045))
        p.drawRoundedRect(r, self.radius, self.radius)


class Surface(QWidget):
    """Plain widget filled with a theme colour (sidebar, top bar...)."""

    def __init__(self, color="surface", parent=None):
        super().__init__(parent)
        self.color = color

    def paintEvent(self, _e):
        p = painter(self)
        p.fillRect(self.rect(), getattr(theme, self.color))


class Chip(QWidget):
    """Small rounded tag. tone: a colour, or None for neutral."""

    def __init__(self, text="", tone=None, parent=None, glyph=None):
        super().__init__(parent)
        self.tone, self.glyph = tone, glyph
        self._font = theme.semibold(8.5)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_text(text)

    def set_text(self, text):
        self.text = text
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        w = QFontMetricsF(self._font).horizontalAdvance(self.text) + 20 + (18 if self.glyph else 0)
        return QSize(round(w), 24)

    def paintEvent(self, _e):
        p = painter(self)
        tone = qcolor(self.tone) if self.tone else None
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(tone, 0.16) if tone else qcolor("#ffffff", 0.07))
        r = QRectF(self.rect())
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        fg = tone if tone else theme.text
        x = 10
        if self.glyph:
            icons.draw_icon(p, QRectF(x - 1, 0, 14, r.height()), self.glyph, fg, 11)
            x += 18
        p.setFont(self._font)
        p.setPen(fg)
        p.drawText(QRectF(x, 0, r.width() - x - 8, r.height()), Qt.AlignmentFlag.AlignVCenter, self.text)


class EmptyState(QWidget):
    """Centered icon, title and hint, shown when a page has nothing to show yet."""

    def __init__(self, glyph, title, hint, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        self.icon = _Badge(glyph)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(14)
        t = label(title, "h2")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        h = label(hint, "muted", wrap=True)
        h.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(h)
        lay.addStretch(1)


class _Badge(QWidget):
    def __init__(self, glyph):
        super().__init__()
        self.glyph = glyph
        self.setFixedSize(64, 64)

    def paintEvent(self, _e):
        p = painter(self)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.accent_soft(0.14))
        p.drawRoundedRect(QRectF(self.rect()), 18, 18)
        icons.draw_icon(p, self.rect(), self.glyph, theme.accent, 28)


def hbox(*widgets, spacing=8, margins=(0, 0, 0, 0)):
    """Horizontal layout with the given widgets; None = stretch, int = spacing."""
    lay = QHBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        else:
            lay.addWidget(w)
    return lay
