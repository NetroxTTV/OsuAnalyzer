"""Small helpers shared by the custom widgets."""

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QVariantAnimation
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QLayout


def painter(widget):
    """Antialiased QPainter on a widget."""
    p = QPainter(widget)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                     | QPainter.RenderHint.SmoothPixmapTransform)
    return p


class Hover(QObject):
    """Animated 0..1 hover amount for a widget (repaints it while it changes)."""

    def __init__(self, widget, duration=130):
        super().__init__(widget)
        self.widget = widget
        self.value = 0.0
        self._anim = QVariantAnimation(self, duration=duration)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._step)
        widget.installEventFilter(self)

    def _step(self, v):
        self.value = float(v)
        self.widget.update()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Enter:
            self._go(1.0)
        elif event.type() == QEvent.Type.Leave:
            self._go(0.0)
        return False

    def _go(self, target):
        self._anim.stop()
        self._anim.setStartValue(self.value)
        self._anim.setEndValue(target)
        self._anim.start()


def label(text="", role="body", wrap=False, parent=None):
    """QLabel styled by the stylesheet through its role (h1, h2, h3, body, muted, caption...)."""
    lbl = QLabel(text, parent)
    lbl.setProperty("role", role)
    lbl.setWordWrap(wrap)
    return lbl


def set_role(lbl, role):
    lbl.setProperty("role", role)
    lbl.style().unpolish(lbl)
    lbl.style().polish(lbl)


def clear_layout(layout: QLayout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.setParent(None)
            w.deleteLater()
        elif item.layout():
            clear_layout(item.layout())
