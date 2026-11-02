"""Song timeline: click to jump, drag to scrub, wheel to step, hover for the time.
Shows note density (played part in the accent), misses (red, click = jump just before)
and 100s / 50s."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...palette import JUDGE_COLORS
from ..theme import qcolor, theme
from ..widgets import painter
from .scene import MISS_LEAD

PAD = 6
TRACK_TOP, TRACK_BOTTOM = 10, 40


def fmt_time(ms):
    m, s = divmod(max(0, ms) / 1000, 60)
    return f"{int(m)}:{s:06.3f}"


class SeekBar(QWidget):
    seekRequested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.t0, self.t1, self.t = 0.0, 1.0, 0.0
        self.obj_times, self.misses, self.marks = [], [], []
        self._hover_x = None
        self._layers = None     # (unplayed, played) density pixmaps for the current size
        theme.changed.connect(self._invalidate)

    def sizeHint(self):
        return QSize(400, 48)

    def set_data(self, t0, t1, obj_times, misses, marks):
        self.t0, self.t1 = t0, max(t1, t0 + 1)
        self.obj_times, self.misses, self.marks = obj_times, misses, marks
        self._invalidate()

    def clear(self):
        self.set_data(0, 1, [], [], [])

    def set_time(self, t):
        self.t = t
        self.update()

    def _invalidate(self):
        self._layers = None
        self.update()

    # ------------------------------------------------------- coordinates --

    def _x(self, t):
        return PAD + (t - self.t0) / (self.t1 - self.t0) * (self.width() - 2 * PAD)

    def _t(self, x):
        f = min(max((x - PAD) / max(1, self.width() - 2 * PAD), 0.0), 1.0)
        return self.t0 + f * (self.t1 - self.t0)

    def _miss_near(self, x):
        return next((m for m in self.misses if abs(self._x(m) - x) <= 5), None)

    # ------------------------------------------------------------ events --

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.obj_times:
            m = self._miss_near(e.position().x())
            self.seekRequested.emit(m - MISS_LEAD if m is not None else self._t(e.position().x()))

    def mouseMoveEvent(self, e):
        self._hover_x = e.position().x()
        if e.buttons() & Qt.MouseButton.LeftButton and self.obj_times:
            self.seekRequested.emit(self._t(self._hover_x))
        self.update()

    def leaveEvent(self, _e):
        self._hover_x = None
        self.update()

    def wheelEvent(self, e):
        if self.obj_times:
            self.seekRequested.emit(self.t + (-1000 if e.angleDelta().y() > 0 else 1000))

    def resizeEvent(self, _e):
        self._layers = None

    # ------------------------------------------------------------ drawing --

    def _build_layers(self):
        dpr = self.devicePixelRatioF()
        layers = []
        w = self.width()
        n_bins = max(10, int((w - 2 * PAD) / 4))
        span = (self.t1 - self.t0) / n_bins
        counts = [0] * n_bins
        for t in self.obj_times:
            i = int((t - self.t0) / span)
            if 0 <= i < n_bins:
                counts[i] += 1
        peak = max(counts) or 1
        for colour in (qcolor("#ffffff", 0.22), theme.accent):
            pm = QPixmap(round(w * dpr), round(self.height() * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            p = painter(pm)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(colour)
            for i, n in enumerate(counts):
                if n:
                    x = self._x(self.t0 + i * span)
                    h = 3 + (TRACK_BOTTOM - TRACK_TOP - 8) * n / peak
                    p.drawRoundedRect(QRectF(x + 0.5, TRACK_BOTTOM - 3 - h, 3, h), 1.2, 1.2)
            p.end()
            layers.append(pm)
        self._layers = tuple(layers)

    def paintEvent(self, _e):
        p = painter(self)
        track = QRectF(PAD - 4, TRACK_TOP, self.width() - 2 * PAD + 8, TRACK_BOTTOM - TRACK_TOP)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("#ffffff", 0.035))
        p.drawRoundedRect(track, 9, 9)
        if not self.obj_times:
            return
        if self._layers is None:
            self._build_layers()
        x = self._x(self.t)
        unplayed, played = self._layers
        full = QRectF(0, 0, self.width(), self.height())
        p.save()
        p.setClipRect(QRectF(x, 0, self.width() - x, self.height()))
        p.drawPixmap(full, unplayed, QRectF(unplayed.rect()))
        p.setClipRect(QRectF(0, 0, x, self.height()))
        p.drawPixmap(full, played, QRectF(played.rect()))
        p.restore()

        for t, j in self.marks:
            mx = self._x(t)
            p.setPen(QPen(qcolor(JUDGE_COLORS[j]), 2))
            p.drawLine(QPointF(mx, TRACK_TOP + 2), QPointF(mx, TRACK_TOP + 7))
        p.setPen(QPen(theme.miss, 2))
        for m in self.misses:
            mx = self._x(m)
            p.drawLine(QPointF(mx, TRACK_TOP - 2), QPointF(mx, TRACK_BOTTOM + 2))

        # Playhead
        p.setPen(QPen(qcolor("#ffffff"), 2))
        p.drawLine(QPointF(x, TRACK_TOP - 4), QPointF(x, TRACK_BOTTOM + 4))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("#ffffff"))
        p.drawEllipse(QPointF(x, TRACK_TOP - 4), 5, 5)

        if self._hover_x is not None:
            self._paint_hover(p)

    def _paint_hover(self, p):
        m = self._miss_near(self._hover_x)
        t = m if m is not None else self._t(self._hover_x)
        x = self._x(t)
        text = f"Miss  {fmt_time(t)}  ·  click = 1.2 s before" if m is not None else fmt_time(t)
        p.setPen(QPen(theme.miss if m is not None else qcolor("#ffffff", 0.6), 1))
        p.drawLine(QPointF(x, TRACK_TOP), QPointF(x, TRACK_BOTTOM))
        font = theme.semibold(8.5)
        fm = QFontMetricsF(font)
        w, h = fm.horizontalAdvance(text) + 16, 22
        bx = x + 10 if x + 10 + w < self.width() else x - 10 - w
        box = QRectF(bx, (TRACK_TOP + TRACK_BOTTOM) / 2 - h / 2, w, h)
        p.setPen(qcolor("#ffffff", 0.08))
        p.setBrush(qcolor("#0b0b10", 0.95))
        p.drawRoundedRect(box, 7, 7)
        p.setFont(font)
        p.setPen(theme.text)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
