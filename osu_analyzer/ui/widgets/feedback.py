"""Progress bar and the loading card shown over the pages while replays are analysed."""

from PySide6.QtCore import QEasingCurve, QEvent, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QLinearGradient
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..theme import qcolor, theme
from .base import label, painter
from .card import Card


class ProgressBar(QWidget):
    """Slim rounded bar: determinate (value / maximum, or animate_to(fraction))
    or indeterminate (sliding glow). An accent colour can be forced with .colour."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self.value, self.maximum = 0, 0     # maximum 0 = indeterminate
        self.colour = None
        self._phase = 0.0
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self._step)
        self._anim = QVariantAnimation(self, duration=450)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda v: self.set_range(float(v), 1.0))

    def set_range(self, value, maximum):
        self.value, self.maximum = value, maximum
        self.update()

    def animate_to(self, fraction):
        """Glide to `fraction` (0..1) of the bar."""
        start = self.value / self.maximum if self.maximum else 0.0
        self._anim.stop()
        self._anim.setStartValue(float(start))
        self._anim.setEndValue(float(max(start, min(1.0, fraction))))
        self._anim.start()

    def set_indeterminate(self):
        self.set_range(0, 0)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _step(self):
        self._phase = (self._phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, _e):
        p = painter(self)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("#ffffff", 0.08))
        p.drawRoundedRect(r, rad, rad)
        accent = self.colour or theme.accent
        if self.maximum:
            w = r.width() * min(1.0, self.value / self.maximum)
            if w <= 0:
                return
            fill = QRectF(0, 0, max(w, r.height()), r.height())
            p.setBrush(accent)
            p.drawRoundedRect(fill, rad, rad)
            if self._timer.isActive():   # a light sheen running over the filled part
                seg = max(40.0, fill.width() * 0.3)
                x = -seg + (fill.width() + seg) * self._phase
                g = QLinearGradient(x, 0, x + seg, 0)
                g.setColorAt(0, qcolor("#ffffff", 0))
                g.setColorAt(0.5, qcolor("#ffffff", 0.45))
                g.setColorAt(1, qcolor("#ffffff", 0))
                p.setClipRect(fill)
                p.setBrush(g)
                p.drawRoundedRect(fill, rad, rad)
            return
        seg = r.width() * 0.35
        x = -seg + (r.width() + seg) * self._phase
        g = QLinearGradient(x, 0, x + seg, 0)
        g.setColorAt(0, qcolor(accent, 0))
        g.setColorAt(0.5, accent)
        g.setColorAt(1, qcolor(accent, 0))
        p.setClipRect(r)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(x, 0, seg, r.height()), rad, rad)


class LoadingOverlay(QWidget):
    """Dims its parent and shows a card with a title, a status line and a progress bar.
    Follows the parent's size and swallows clicks while visible."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.card = Card(padding=(28, 24, 28, 24), radius=16, color="surface", spacing=6)
        self.card.setFixedWidth(420)
        self.title = label("Analysing...", "h3")
        self.status = label("", "muted")
        self.bar = ProgressBar()
        self.card.body.addWidget(self.title)
        self.card.body.addWidget(self.status)
        self.card.body.addSpacing(10)
        self.card.body.addWidget(self.bar)
        lay.addWidget(self.card)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def start(self, title):
        self.title.setText(title)
        self.status.setText("Starting...")
        self.bar.set_indeterminate()
        self.bar.start()
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()

    def set_status(self, text):
        self.status.setText(text)
        self.bar.set_indeterminate()

    def set_progress(self, text, done, total):
        self.status.setText(text)
        self.bar.set_range(done, max(total, 1))

    def stop(self):
        self.bar.stop()
        self.hide()

    def mousePressEvent(self, e):
        e.accept()

    def paintEvent(self, _e):
        p = painter(self)
        p.fillRect(self.rect(), qcolor(theme.bg, 0.6))
