"""Hit Analyzer page: options, the hit scatter and a column of statistics."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPen
from PySide6.QtWidgets import QGridLayout, QScrollArea, QStackedLayout, QVBoxLayout, QWidget

from ...core import MISS_LABELS, MISS_REASONS, HitStats
from ...palette import JUDGE_COLORS, MISS_COLORS
from .. import icons
from ..theme import qcolor, theme
from ..widgets import Button, Card, EmptyState, SegmentedControl, clear_layout, hbox, label, painter
from .charts import SplitBar, TimingHistogram
from .scatter import HitScatter


class StatRow(QWidget):
    """'label ........ value' line."""

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.value = label("", "body")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay = hbox(label(name, "muted"), None, self.value)
        self.setLayout(lay)

    def set(self, text):
        self.value.setText(text)


class JudgementTile(QWidget):
    """Coloured count tile (300 / 100 / 50 / miss)."""

    def __init__(self, title, colour, parent=None):
        super().__init__(parent)
        self.colour = colour
        self.setFixedHeight(64)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 8, 12, 8)
        lay.setSpacing(0)
        self.count = label("0", "metric-sm")
        name = label(title, "caption")
        lay.addWidget(self.count)
        lay.addWidget(name)

    def set(self, n):
        self.count.setText(f"{n:,}")

    def paintEvent(self, _e):
        p = painter(self)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(self.colour, 0.12))
        p.drawRoundedRect(self.rect(), 10, 10)
        p.setBrush(qcolor(self.colour))
        p.drawRoundedRect(7, 16, 3, self.height() - 32, 1.5, 1.5)


class LegendItem(QWidget):
    def __init__(self, colour, text, cross=False, parent=None):
        super().__init__(parent)
        self.colour, self.cross = colour, cross
        lay = hbox(14, label(text, "caption"), spacing=6)
        self.setLayout(lay)

    def paintEvent(self, _e):
        p = painter(self)
        c = self.rect().center()
        y = c.y() + 1
        if self.cross:
            pen = QPen(qcolor(self.colour), 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(2, y - 4, 10, y + 4)
            p.drawLine(2, y + 4, 10, y - 4)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(self.colour))
            p.drawEllipse(2, y - 4, 8, 8)


class AnalyzerPage(QWidget):
    picked = Signal(object, object)          # (Analysis, Hit / Miss): watch it in the viewer
    sliderHeadsChanged = Signal(bool)
    saveRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.analyses = []
        self.frame_mode = "screen"
        self.color_by = "timing"
        self.stats = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(14)

        self.view_opt = SegmentedControl([("screen", "Screen"), ("movement", "Movement")], "screen")
        self.view_opt.changed.connect(lambda v: self._set("frame_mode", v))
        self.colour_opt = SegmentedControl([("timing", "Timing"), ("judgement", "300 / 100 / 50")], "timing")
        self.colour_opt.changed.connect(lambda v: self._set("color_by", v))
        self.heads_opt = SegmentedControl([(True, "On"), (False, "Off")], True)
        self.heads_opt.changed.connect(lambda v: self.sliderHeadsChanged.emit(bool(v)))
        save = Button("Save image", icons.SAVE, "secondary")
        save.setToolTip("Save this page as a PNG (Ctrl+S)")
        save.clicked.connect(self.saveRequested)
        outer.addLayout(hbox(label("View", "caption"), self.view_opt, 18,
                             label("Colour", "caption"), self.colour_opt, 18,
                             label("Slider heads", "caption"), self.heads_opt, None, save, spacing=8))

        self.stack = QStackedLayout()
        outer.addLayout(self.stack, 1)
        self.empty = EmptyState(icons.TARGET, "Hit Analyzer",
                                "Pick a replay on the left to see where you hit each note.\n"
                                "Ctrl/Shift+click several replays to combine them.")
        self.stack.addWidget(self.empty)
        self.content = QWidget()
        self.stack.addWidget(self.content)
        body = hbox(spacing=16)
        self.content.setLayout(body)

        # Left: the scatter
        plot = Card(padding=(22, 18, 22, 14), spacing=4)
        self.title = label("", "h2")
        self.subtitle = label("", "muted")
        self.view_note = label("", "caption")
        plot.body.addLayout(hbox(self.title, None, self.view_note))
        plot.body.addWidget(self.subtitle)
        self.legend = hbox(spacing=16)
        plot.body.addSpacing(4)
        plot.body.addLayout(self.legend)
        self.scatter = HitScatter()
        self.scatter.picked.connect(self.picked)
        plot.body.addWidget(self.scatter, 1)
        body.addWidget(plot, 1)

        # Right: statistics
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(380)
        column = QWidget()
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(12)
        scroll.setWidget(column)
        body.addWidget(scroll)

        avg = Card(title="Average hit")
        self.offset = label("", "metric")
        self.offset_px = label("", "muted")
        avg.body.addLayout(hbox(self.offset, self.offset_px, None, spacing=10))
        self.direction = StatRow("Direction")
        self.xy = StatRow("X / Y")
        avg.body.addWidget(self.direction)
        avg.body.addWidget(self.xy)
        col.addWidget(avg)

        timing = Card(title="Timing")
        self.ur = label("", "metric")
        self.mean_err = label("", "metric-sm")
        ur_box, err_box = QVBoxLayout(), QVBoxLayout()
        ur_box.setSpacing(0)
        err_box.setSpacing(0)
        ur_box.addWidget(self.ur)
        ur_box.addWidget(label("unstable rate", "caption"))
        err_box.addWidget(self.mean_err)
        self.mean_err_note = label("", "caption")
        err_box.addWidget(self.mean_err_note)
        row = hbox(spacing=24)
        row.addLayout(ur_box)
        row.addLayout(err_box)
        row.addStretch(1)
        timing.body.addLayout(row)
        self.histogram = TimingHistogram()
        timing.body.addWidget(self.histogram)
        col.addWidget(timing)

        judge = Card(title="Judgements")
        grid = QGridLayout()
        grid.setSpacing(8)
        self.tiles = {j: JudgementTile(str(j), JUDGE_COLORS[j]) for j in (300, 100, 50)}
        self.tiles[0] = JudgementTile("miss", theme.miss.name())
        for i, j in enumerate((300, 100, 50, 0)):
            grid.addWidget(self.tiles[j], i // 2, i % 2)
        judge.body.addLayout(grid)
        self.miss_note = label("", "caption", wrap=True)
        judge.body.addWidget(self.miss_note)
        col.addWidget(judge)

        spread = Card(title="Spread")
        self.mean_dist = StatRow("Mean distance")
        self.std = StatRow("Std x / y")
        self.inside = StatRow("Inside 50% radius")
        for w in (self.mean_dist, self.std, self.inside):
            spread.body.addWidget(w)
        col.addWidget(spread)

        aim = Card(title="Over / under aim")
        self.aim_misses = StatRow("Misses")
        self.aim_misses_bar = SplitBar()
        self.aim_hits = StatRow("Hits")
        self.aim_hits_bar = SplitBar()
        for w in (self.aim_misses, self.aim_misses_bar, self.aim_hits, self.aim_hits_bar):
            aim.body.addWidget(w)
        aim.body.addWidget(label("Along the jump direction: overaim = past the note, "
                                 "underaim = short of it.", "caption", wrap=True))
        col.addWidget(aim)
        col.addStretch(1)

    # ---------------------------------------------------------- page API --

    def set_analyses(self, analyses):
        self.analyses = list(analyses)
        self.refresh()

    def set_slider_heads(self, on):
        self.heads_opt.set_value(on, animate=False)

    def refresh(self):
        if not self.analyses:
            self.stack.setCurrentWidget(self.empty)
            return
        s = self.stats = HitStats.compute(self.analyses, self.frame_mode)
        self.stack.setCurrentWidget(self.content)
        self.title.setText(s.title)
        self.subtitle.setText(s.subtitle)
        self.view_note.setText("Screen axes, up = up" if self.frame_mode == "screen"
                               else "Rotated so the jump points right")
        self.scatter.set_stats(s, self.color_by)
        self._fill_legend(s)
        if s.empty:
            self.offset.setText("-")
            return

        mx, my = s.mean
        self.offset.setText(f"{s.offset * 100:.1f}%")
        self.offset_px.setText(f"of the radius  ·  {s.offset_px:.1f} px")
        self.direction.set(s.direction)
        self.xy.set(f"{mx * 100:+.1f}%  /  {my * 100:+.1f}%")

        self.ur.setText(f"{s.unstable_rate:.1f}")
        self.mean_err.setText(f"{s.mean_error:+.1f} ms")
        self.mean_err_note.setText("mean error  ·  " + ("late" if s.mean_error > 0 else "early"))
        self.histogram.set_data(s.errors, s.windows[1], s.mean_error)

        counts = s.counts
        for j in (300, 100, 50):
            self.tiles[j].set(counts[j])
        self.tiles[0].set(s.total_misses)
        reasons = s.misses_by_reason
        note = "  ·  ".join(f"{reasons[r]} {MISS_LABELS[r]}" for r in MISS_REASONS)
        if s.skipped:
            note += f"\n{s.skipped} hits without a jump direction are not plotted"
        if len(s.analyses) == 1:
            r = s.analyses[0].replay
            note += f"\nReplay header: {r.n300} / {r.n100} / {r.n50} / {r.nmiss}x"
        self.miss_note.setText(note)

        self.mean_dist.set(f"{s.mean_distance * 100:.1f}% of radius")
        self.std.set(f"{s.std[0] * 100:.1f}%  /  {s.std[1] * 100:.1f}%")
        self.inside.set(f"{s.inside_half * 100:.1f}%")

        miss_split, hit_split = s.aim_splits()
        self.aim_misses.set(f"{miss_split.over} over  ·  {miss_split.under} under" if miss_split.total else "-")
        self.aim_misses_bar.set_share(miss_split.over / miss_split.total if miss_split.total else None)
        self.aim_hits.set(f"{hit_split.over_pct:.0f}% over  ·  {100 - hit_split.over_pct:.0f}% under"
                          if hit_split.total else "-")
        self.aim_hits_bar.set_share(hit_split.over_pct / 100 if hit_split.total else None)

    def _fill_legend(self, s):
        clear_layout(self.legend)
        self.legend.addWidget(LegendItem(theme.gold.name(), "average hit", cross=True))
        for reason in MISS_REASONS:
            n = sum(1 for m in s.misses if m.reason == reason)
            if n:
                self.legend.addWidget(LegendItem(MISS_COLORS[reason], f"miss: {MISS_LABELS[reason]} ({n})",
                                                 cross=True))
        self.legend.addStretch(1)

    def _set(self, name, value):
        setattr(self, name, value)
        self.refresh()

    def grab_image(self):
        return self.content.grab()
