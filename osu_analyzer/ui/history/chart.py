"""Progress chart: one metric per replay over time, its rolling average, and the moments
the tablet area changed. Hover a point for details, click it to open the replay."""

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import mix, qcolor, theme
from ..widgets import painter

ROLLING = 5


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    value: Callable          # HistoryEntry -> float
    fmt: str                 # format of one value
    better: str              # "lower", "higher" or "zero" (closer to 0 is better)
    unit: str = ""

    def text(self, v):
        return self.fmt.format(v)

    def improvement(self, old, new):
        """> 0 when going from old to new is an improvement."""
        if self.better == "lower":
            return old - new
        if self.better == "higher":
            return new - old
        return abs(old) - abs(new)


METRICS = [
    Metric("ur", "Unstable rate", lambda e: e.ur, "{:.1f}", "lower"),
    Metric("accuracy", "Accuracy", lambda e: e.accuracy * 100, "{:.2f}%", "higher", "%"),
    Metric("offset", "Aim offset", lambda e: e.offset * 100, "{:.1f}%", "lower", "% of radius"),
    Metric("timing", "Mean timing error", lambda e: e.mean_error, "{:+.1f} ms", "zero", "ms"),
    Metric("misses", "Misses per 100 notes", lambda e: e.miss_rate, "{:.1f}", "lower"),
]
METRIC_BY_KEY = {m.key: m for m in METRICS}


def rolling(values, n=ROLLING):
    """Trailing mean over the last n values."""
    out, acc = [], 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= n:
            acc -= values[i - n]
        out.append(acc / min(i + 1, n))
    return out


def nice_ticks(lo, hi, count=4):
    """Round tick values covering lo..hi."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first, last = math.floor(lo / step), math.ceil(hi / step)
    return [round(i * step, 10) for i in range(first, last + 1)]


class HistoryChart(QWidget):
    openRequested = Signal(object)      # HistoryEntry

    MARGIN = (58, 30, 18, 30)           # left, top, right, bottom

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.entries, self.shown_metric = [], METRICS[0]
        self.values, self.trend = [], []
        self._hover = None
        self._points = []

    def set_data(self, entries, metric):
        self.entries, self.shown_metric = list(entries), metric
        self.values = [metric.value(e) for e in self.entries]
        self.trend = rolling(self.values)
        self._hover = None
        self.update()

    # ----------------------------------------------------------- geometry --

    def _plot(self):
        l, t, r, b = self.MARGIN
        return QRectF(l, t, self.width() - l - r, self.height() - t - b)

    def _ranges(self):
        t0, t1 = self.entries[0].date, self.entries[-1].date
        if t1 - t0 < timedelta(hours=12):
            t0, t1 = t0 - timedelta(hours=6), t1 + timedelta(hours=6)
        pad = (t1 - t0) * 0.03
        lo, hi = min(self.values), max(self.values)
        if self.shown_metric.better == "zero":
            lo, hi = min(lo, 0), max(hi, 0)
        span = (hi - lo) or max(abs(hi), 1) * 0.2
        ticks = nice_ticks(lo - span * 0.08, hi + span * 0.08)
        return t0 - pad, t1 + pad, ticks

    # ------------------------------------------------------------ drawing --

    def paintEvent(self, _e):
        p = painter(self)
        plot = self._plot()
        if not self.entries:
            p.setPen(theme.muted)
            p.setFont(theme.font(10))
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "No replays in this period")
            return
        t0, t1, ticks = self._ranges()
        lo, hi = ticks[0], ticks[-1]
        span_s = (t1 - t0).total_seconds()

        def X(d):
            return plot.left() + (d - t0).total_seconds() / span_s * plot.width()

        def Y(v):
            return plot.bottom() - (v - lo) / (hi - lo) * plot.height()

        # Grid + y labels
        small = theme.font(8.5)
        p.setFont(small)
        for v in ticks:
            y = Y(v)
            p.setPen(QPen(qcolor("#ffffff", 0.07), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(theme.muted)
            p.drawText(QRectF(0, y - 9, plot.left() - 10, 18),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._tick_text(v, ticks))

        # x labels (dates)
        fmt = "%H:%M" if (t1 - t0) < timedelta(days=2) else "%b %d"
        n = max(2, min(7, int(plot.width() / 110)))
        p.setPen(theme.muted)
        for i in range(n):
            d = t0 + (t1 - t0) * (i / (n - 1))
            x = X(d)
            p.drawText(QRectF(x - 50, plot.bottom() + 8, 100, 16), Qt.AlignmentFlag.AlignCenter,
                       d.astimezone().strftime(fmt))

        # Tablet area changes
        prev = None
        for e in self.entries:
            if e.area:
                if prev and e.area != prev:
                    x = X(e.date)
                    p.setPen(QPen(qcolor(theme.gold, 0.55), 1))
                    p.drawLine(QPointF(x, plot.top() - 6), QPointF(x, plot.bottom()))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(theme.gold)
                    p.drawEllipse(QPointF(x, plot.top() - 14), 3, 3)
                    p.setPen(theme.muted)
                    p.drawText(QRectF(x + 7, plot.top() - 24, 160, 18), Qt.AlignmentFlag.AlignVCenter,
                               "Tablet area changed")
                prev = e.area

        # Per-replay values (de-emphasised dots) and the rolling average (accent line)
        self._points = [QPointF(X(e.date), Y(v)) for e, v in zip(self.entries, self.values)]
        ring = QPen(theme.card, 2)
        p.setPen(ring)
        p.setBrush(mix(theme.card, theme.accent, 0.55))
        for pt in self._points:
            p.drawEllipse(pt, 4, 4)
        if len(self.entries) > 1:
            path = QPainterPath(QPointF(X(self.entries[0].date), Y(self.trend[0])))
            for e, v in zip(self.entries[1:], self.trend[1:]):
                path.lineTo(X(e.date), Y(v))
            pen = QPen(theme.accent, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            end = QPointF(X(self.entries[-1].date), Y(self.trend[-1]))
            p.setPen(ring)
            p.setBrush(theme.accent)
            p.drawEllipse(end, 4.5, 4.5)

        if self._hover is not None:
            self._paint_hover(p, plot)

    def _tick_text(self, v, ticks):
        step = ticks[1] - ticks[0] if len(ticks) > 1 else 1
        decimals = 0 if step >= 1 else 1 if step >= 0.1 else 2
        return f"{v:.{decimals}f}"

    def _paint_hover(self, p, plot):
        i = self._hover
        e, pt = self.entries[i], self._points[i]
        p.setPen(QPen(qcolor("#ffffff", 0.18), 1))
        p.drawLine(QLineF(pt.x(), plot.top(), pt.x(), plot.bottom()))
        p.setPen(QPen(theme.card, 2))
        p.setBrush(theme.accent)
        p.drawEllipse(pt, 5.5, 5.5)

        when = e.date.astimezone().strftime("%b %d, %Y  %H:%M")
        mods = f"+{e.mods}  ·  " if e.mods != "NM" else ""
        lines = [(when, theme.font(8.5), theme.muted),
                 (e.map_name, theme.semibold(9), theme.text),
                 (f"{mods}{e.accuracy * 100:.2f}%  ·  {e.grade}  ·  {e.misses} misses", theme.font(9), theme.muted),
                 (f"{self.shown_metric.name}: {self.shown_metric.text(self.values[i])}", theme.semibold(9), theme.text),
                 (f"Average of the last {min(i + 1, ROLLING)}: {self.shown_metric.text(self.trend[i])}",
                  theme.font(9), theme.muted),
                 ("Click to open this replay", theme.font(8.5), theme.accent)]
        width = min(420.0, max(QFontMetricsF(f).horizontalAdvance(t) for t, f, _c in lines) + 24)
        h = 18 * len(lines) + 16
        bx = pt.x() + 14 if pt.x() + 14 + width < self.width() else pt.x() - 14 - width
        by = min(max(4, pt.y() - h / 2), self.height() - h - 4)
        box = QRectF(bx, by, width, h)
        p.setPen(qcolor("#ffffff", 0.08))
        p.setBrush(qcolor(theme.elevated, 0.97))
        p.drawRoundedRect(box, 9, 9)
        for n, (text, font, colour) in enumerate(lines):
            p.setFont(font)
            p.setPen(colour)
            fm = QFontMetricsF(font)
            p.drawText(QRectF(bx + 12, by + 8 + n * 18, width - 24, 18), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(text, Qt.TextElideMode.ElideRight, width - 24))

    # ------------------------------------------------------------- events --

    def _nearest(self, pos):
        if not self._points:
            return None
        i = min(range(len(self._points)), key=lambda k: abs(self._points[k].x() - pos.x())
                + 0.25 * abs(self._points[k].y() - pos.y()))
        return i if abs(self._points[i].x() - pos.x()) < 30 else None

    def mouseMoveEvent(self, e):
        h = self._nearest(e.position())
        if h != self._hover:
            self._hover = h
            self.setCursor(Qt.CursorShape.PointingHandCursor if h is not None else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _e):
        if self._hover is not None:
            self._hover = None
            self.update()

    def mousePressEvent(self, e):
        h = self._nearest(e.position())
        if h is not None and e.button() == Qt.MouseButton.LeftButton:
            self.openRequested.emit(self.entries[h])
