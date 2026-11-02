"""Inputs: search field, volume slider and colour swatches."""

from PySide6.QtCore import QEvent, QLocale, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from .. import icons
from ..theme import mix, qcolor, theme
from .base import label, painter


def _number_text(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


class NumberField(QWidget):
    """Number input (decimals = 0 for whole numbers) that shows what is wrong in red under it,
    instead of an error dialog."""

    textChanged = Signal(str)

    def __init__(self, value, decimals=0, maximum=100000, width=96, parent=None):
        super().__init__(parent)
        self.decimals = decimals
        self.edit = QLineEdit(_number_text(value))
        if decimals:
            v = QDoubleValidator(0, maximum, decimals, self.edit)
            v.setNotation(QDoubleValidator.Notation.StandardNotation)
            v.setLocale(QLocale.c())
        else:
            v = QIntValidator(0, int(maximum), self.edit)
        self.edit.setValidator(v)
        self.edit.setFixedWidth(width)
        self.edit.textChanged.connect(self.textChanged)
        self.error = label("", "error", wrap=True)
        self.error.setFixedWidth(width + 40)
        self.error.hide()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        lay.addWidget(self.edit)
        lay.addWidget(self.error)

    def text(self):
        return self.edit.text()

    def setText(self, text):
        self.edit.setText(text)

    def value(self):
        """The number, or None when the field is empty or unfinished."""
        try:
            return float(self.edit.text()) if self.decimals else int(self.edit.text())
        except ValueError:
            return None

    def set_error(self, text=""):
        self.error.setText(text)
        self.error.setVisible(bool(text))
        if self.edit.property("invalid") != bool(text):
            self.edit.setProperty("invalid", bool(text))
            self.edit.style().unpolish(self.edit)
            self.edit.style().polish(self.edit)


class SearchField(QWidget):
    """Rounded search box with an icon, a placeholder and a clear button. Esc clears it."""

    textChanged = Signal(str)

    def __init__(self, placeholder="Search", parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        self.edit = QLineEdit(self)
        self.edit.setObjectName("Bare")
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFont(theme.font(10))
        self.edit.textChanged.connect(self._changed)
        self.edit.installEventFilter(self)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(36, 0, 32, 0)
        lay.addWidget(self.edit)
        self.setCursor(Qt.CursorShape.IBeamCursor)

    def text(self):
        return self.edit.text()

    def clear(self):
        self.edit.clear()

    def focus(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def _changed(self, text):
        self.update()
        self.textChanged.emit(text)

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.update()
        elif e.type() == QEvent.Type.KeyPress and e.key() == Qt.Key.Key_Escape:
            self.edit.clear()
            return True
        return False

    def _clear_rect(self):
        return QRectF(self.width() - 30, 0, 26, self.height())

    def mousePressEvent(self, e):
        if self.edit.text() and self._clear_rect().contains(e.position()):
            self.edit.clear()
        self.edit.setFocus()

    def paintEvent(self, _e):
        p = painter(self)
        focused = self.edit.hasFocus()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(theme.elevated if focused else qcolor("#ffffff", 0.045))
        p.setPen(theme.accent if focused else qcolor("#ffffff", 0.06))
        p.drawRoundedRect(r, 10, 10)
        icons.draw_icon(p, QRectF(10, 0, 20, self.height()), icons.SEARCH,
                        theme.text if focused else theme.muted, 13)
        if self.edit.text():
            icons.draw_icon(p, self._clear_rect(), icons.CLOSE, theme.muted, 10)


class VolumeSlider(QWidget):
    """Speaker (click = mute) + draggable track + percentage. The wheel steps by 5 %."""

    changed = Signal(float)     # effective volume (0 when muted)

    def __init__(self, value=0.5, parent=None, width=180):
        super().__init__(parent)
        self.value, self.muted = value, False
        self.setFixedSize(width, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.x0, self.x1 = 36.0, width - 46.0

    @property
    def effective(self):
        return 0.0 if self.muted else self.value

    def set_value(self, value, notify=True):
        self.value = min(1.0, max(0.0, value))
        if self.value > 0:
            self.muted = False
        self.update()
        if notify:
            self.changed.emit(self.effective)

    def toggle_mute(self):
        self.muted = not self.muted
        self.update()
        self.changed.emit(self.effective)

    def mousePressEvent(self, e):
        if e.position().x() < self.x0 - 8:
            self.toggle_mute()
        else:
            self._drag(e.position().x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._drag(e.position().x())

    def wheelEvent(self, e):
        self.set_value(self.value + (0.05 if e.angleDelta().y() > 0 else -0.05))

    def _drag(self, x):
        if x >= self.x0 - 8:
            self.muted = False
            self.set_value((x - self.x0) / (self.x1 - self.x0))

    def paintEvent(self, _e):
        p = painter(self)
        y = self.height() / 2
        silent = self.muted or self.value == 0
        icons.draw_icon(p, QRectF(0, 0, 28, self.height()), icons.MUTE if silent else icons.VOLUME,
                        theme.muted if silent else theme.text, 15)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("#ffffff", 0.1))
        p.drawRoundedRect(QRectF(self.x0, y - 2, self.x1 - self.x0, 4), 2, 2)
        xv = self.x0 + (self.x1 - self.x0) * self.effective
        if self.effective > 0:
            p.setBrush(theme.accent)
            p.drawRoundedRect(QRectF(self.x0, y - 2, xv - self.x0, 4), 2, 2)
        p.setBrush(qcolor("#000000", 0.35))
        p.drawEllipse(QPointF(xv, y + 1), 7.5, 7.5)
        p.setBrush(Qt.GlobalColor.white)
        p.drawEllipse(QPointF(xv, y), 6.5, 6.5)
        p.setFont(theme.font(9))
        p.setPen(theme.muted)
        p.drawText(QRectF(self.x1 + 10, 0, 40, self.height()), Qt.AlignmentFlag.AlignVCenter,
                   "muted" if self.muted else f"{round(self.value * 100)}%")


class Swatches(QWidget):
    """Row of round colour swatches; the selected one gets a ring."""

    changed = Signal(str)

    def __init__(self, colours, value, parent=None, size=26, gap=12):
        super().__init__(parent)
        self.colours, self.value, self.size, self.gap = colours, value, size, gap
        self._hover = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(len(self.colours) * (self.size + self.gap) - self.gap + 8, self.size + 8)

    def _index(self, x):
        i = int((x - 4) // (self.size + self.gap))
        return i if 0 <= i < len(self.colours) else None

    def mouseMoveEvent(self, e):
        i = self._index(e.position().x())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, _e):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        i = self._index(e.position().x())
        if i is not None:
            self.value = self.colours[i]
            self.update()
            self.changed.emit(self.value)

    def paintEvent(self, _e):
        p = painter(self)
        for i, colour in enumerate(self.colours):
            c = QPointF(4 + i * (self.size + self.gap) + self.size / 2, self.height() / 2)
            r = self.size / 2
            if colour.lower() == self.value.lower():
                p.setPen(qcolor(theme.text))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, r + 3.5, r + 3.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(mix(colour, "#ffffff", 0.15) if i == self._hover else qcolor(colour))
            p.drawEllipse(c, r, r)



class ComboBox(QComboBox):
    """Stylesheet-styled combo box with a chevron drawn from the icon font."""

    def paintEvent(self, e):
        super().paintEvent(e)
        p = painter(self)
        icons.draw_icon(p, QRectF(self.width() - 30, 0, 24, self.height()), icons.CHEVRON_DOWN, theme.muted, 10)
