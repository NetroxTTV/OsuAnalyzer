"""Segmented control: a row of options, one selected, with a sliding thumb."""

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import icons
from ..theme import qcolor, theme
from .base import painter


class SegmentedControl(QWidget):
    """options: [(value, label)] or [(value, label, glyph)].
    style 'accent' = solid accent thumb, 'soft' = subtle raised thumb (navigation)."""

    changed = Signal(object)

    def __init__(self, options, value=None, parent=None, style="accent", height=32, font_size=9.5):
        super().__init__(parent)
        self.options = [tuple(o) + (None,) * (3 - len(o)) for o in options]
        self.value = value
        self.style = style
        self._h = height
        self._font = theme.semibold(font_size)
        self._hover = None
        self._thumb = None          # QRectF, animated
        self._anim = QVariantAnimation(self, duration=200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._move_thumb)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._layout_cells()

    # ----------------------------------------------------------- geometry --

    def _layout_cells(self):
        fm = QFontMetricsF(self._font)
        pad, inset, x = 14, 3, 3.0
        self.cells = []
        for value, text, glyph in self.options:
            w = fm.horizontalAdvance(text) + 2 * pad + (22 if glyph else 0)
            self.cells.append((value, text, glyph, QRectF(x, inset, w, self._h - 2 * inset)))
            x += w + 2
        self._width = x + inset - 2
        self.updateGeometry()

    def sizeHint(self):
        return QSize(round(self._width), self._h)

    def _cell(self, value):
        return next((c for c in self.cells if c[0] == value), None)

    def _at(self, pos):
        return next((c[0] for c in self.cells if c[3].contains(pos.x(), self._h / 2)), None)

    # -------------------------------------------------------------- value --

    def set_value(self, value, notify=False, animate=True):
        changed = value != self.value
        self.value = value
        cell = self._cell(value)
        if cell and self._thumb is not None and animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._thumb)
            self._anim.setEndValue(cell[3])
            self._anim.start()
        else:
            self._thumb = QRectF(cell[3]) if cell else None
        self.update()
        if notify and changed:
            self.changed.emit(value)

    def _move_thumb(self, rect):
        self._thumb = rect
        self.update()

    # ------------------------------------------------------------- events --

    def mouseMoveEvent(self, e):
        v = self._at(e.position())
        if v != self._hover:
            self._hover = v
            self.update()

    def leaveEvent(self, _e):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            value = self._at(e.position())
            if self._cell(value):
                self.set_value(value, notify=True)

    # ------------------------------------------------------------ drawing --

    def paintEvent(self, _e):
        if self._thumb is None and self._cell(self.value):
            self._thumb = QRectF(self._cell(self.value)[3])
        p = painter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._h / 2 if self.style == "accent" else 10
        p.setPen(qcolor("#ffffff", 0.05))
        p.setBrush(qcolor("#ffffff", 0.035))
        p.drawRoundedRect(r, radius, radius)

        if self._thumb is not None and self._cell(self.value):
            p.setPen(Qt.PenStyle.NoPen)
            if self.style == "accent":
                p.setBrush(theme.accent)
                tr = self._thumb.height() / 2
            else:
                p.setBrush(qcolor("#ffffff", 0.09))
                tr = 8
            p.drawRoundedRect(self._thumb, tr, tr)

        p.setFont(self._font)
        for value, text, glyph, rect in self.cells:
            selected = value == self.value
            if selected:
                fg = theme.on_accent if self.style == "accent" else theme.text
            else:
                if value == self._hover:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(qcolor("#ffffff", 0.04))
                    p.drawRoundedRect(rect, rect.height() / 2 if self.style == "accent" else 8,
                                      rect.height() / 2 if self.style == "accent" else 8)
                fg = theme.text if value == self._hover else theme.muted
            x = rect.x()
            if glyph:
                icol = theme.accent if selected and self.style == "soft" else fg
                icons.draw_icon(p, QRectF(x + 12, rect.y(), 16, rect.height()), glyph, icol, 14)
                x += 22
            p.setPen(fg)
            p.drawText(QRectF(x, rect.y(), rect.right() - x, rect.height()), Qt.AlignmentFlag.AlignCenter,
                       text)

