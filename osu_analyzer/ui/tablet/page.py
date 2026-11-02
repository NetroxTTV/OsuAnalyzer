"""Tablet Zone page: suggests a tablet area from where you over / underaim on the playfield."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QGridLayout, QScrollArea, QVBoxLayout, QWidget

from ...core import DRIVERS, current_driver, settings, suggest_tablet_area
from ...core.drivers import fmt
from ...core.tablet import TIMING_MIN
from .. import icons
from ..theme import theme
from ..widgets import Button, Card, NumberField, SegmentedControl, clear_layout, hbox, label
from .views import FieldHeatmap, TabletAreaView

EDGES = (("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right"))
SIDES = {"top": "top notes", "bottom": "bottom notes", "left": "left notes", "right": "right notes"}


def describe_edge(key, e, driver):
    side = SIDES[key]
    if e.stderr is None:
        return "not enough notes to measure"
    d = e.suggested - e.current
    if d == 0:
        return f"no clear bias on {side}, unchanged"
    outward = d > 0 if key in ("bottom", "right") else d < 0
    if outward:
        return f"you overaim {side}  →  edge moved out by {driver.length(abs(d))}"
    return f"you underaim {side}  →  edge moved in by {driver.length(abs(d))}"


def signed(x):
    return ("+" if x > 0 else "-") + fmt(abs(x))


def timing_effect(curve):
    """'early taps (-40…-25 ms) look 0.19 radius more underaimed, ...' from the outermost measured bins."""
    parts = []
    for side, word in ((-1, "early"), (1, "late")):
        bins = [b for b in curve if b.n >= TIMING_MIN and b.offset and b.lo is not None and b.hi is not None
                and (b.hi <= 0 if side < 0 else b.lo >= 0)]
        if bins:
            b = bins[0] if side < 0 else bins[-1]
            how = "overaimed" if b.offset > 0 else "underaimed"
            parts.append(f"{word} taps ({b.lo:+d}…{b.hi:+d} ms) look {abs(b.offset):.2f} radius more {how}")
    return ",  ".join(parts)


class TabletPage(QWidget):
    """screen_size() gives the resolution osu! runs at. message(text) reports to the status bar."""

    message = Signal(str)

    def __init__(self, screen_size, parent=None):
        super().__init__(parent)
        self.screen_size = screen_size
        self.analyses = []
        self.driver = current_driver()
        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self.refresh)

        outer = hbox(spacing=16, margins=(24, 18, 24, 18))
        self.setLayout(outer)

        # Left column: the area, its drawing and the suggestion
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left = QWidget()
        col = QVBoxLayout(left)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(12)
        scroll.setWidget(left)
        outer.addWidget(scroll, 5)

        area = Card(title="Your tablet area")
        self.driver_opt = SegmentedControl([(d.key, d.name) for d in DRIVERS.values()], self.driver.key)
        self.driver_opt.changed.connect(self._set_driver)
        area.body.addLayout(hbox(label("Driver", "muted"), self.driver_opt, None, spacing=10))
        area.body.addSpacing(4)
        self.form = QVBoxLayout()
        self.form.setSpacing(8)
        area.body.addLayout(self.form)
        self._build_form()
        area.body.addSpacing(6)
        self.tablet_view = TabletAreaView()
        area.body.addWidget(self.tablet_view)
        col.addWidget(area)

        self.result = QVBoxLayout()
        self.result.setSpacing(12)
        col.addLayout(self.result)
        col.addStretch(1)

        # Right column: where you over / underaim
        field = Card(title="Where you miss on the playfield")
        field.body.addWidget(label("Overaim = the cursor goes past the note in the jump's direction  ·  "
                                   "underaim = it stops before.", "caption", wrap=True))
        self.timing_opt = SegmentedControl([(True, "Corrected"), (False, "As tapped")],
                                           settings.get("tablet_timing", True))
        self.timing_opt.changed.connect(self._set_timing)
        field.body.addLayout(hbox(label("Tap timing", "muted"), self.timing_opt, None, spacing=10))
        field.body.addWidget(label("Corrected = your aim as if every note had been tapped on time: tapping early "
                                   "catches the cursor before it arrives, late after it went further. An area "
                                   "can't fix timing, so that part is left out.", "caption", wrap=True))
        self.aim_text = label("", "body", wrap=True)
        field.body.addWidget(self.aim_text)
        self.heatmap = FieldHeatmap()
        field.body.addWidget(self.heatmap, 1)
        field.body.addWidget(label("Arrow = where your cursor lands on average for notes in that area "
                                   "(drawn 4× bigger). Red = more misses.", "caption", wrap=True))
        outer.addWidget(field, 6)
        theme.changed.connect(self.refresh)
        self.refresh()

    def _build_form(self):
        """The driver's own fields, filled with what was last entered for it."""
        clear_layout(self.form)
        d = self.driver
        stored = d.stored()
        self.inputs = {}
        self.form.addWidget(label(d.hint, "caption", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        top = Qt.AlignmentFlag.AlignTop
        for i, (key, name) in enumerate(d.fields):
            r, c = divmod(i, 2)
            f = self._input(key, stored[key])
            grid.addWidget(self._name(name, f), r, c * 2, top)
            grid.addWidget(f, r, c * 2 + 1, top)
        tw, th = self._input("tablet_w", stored["tablet_w"]), self._input("tablet_h", stored["tablet_h"])
        grid.addWidget(self._name("Tablet", tw), 2, 0, top)
        size = hbox(tw, self._name("×", tw), th, spacing=8)
        size.setAlignment(top)
        grid.addLayout(size, 2, 1, 1, 3, top)
        grid.setColumnStretch(4, 1)
        self.form.addLayout(grid)
        self.form.addWidget(label(d.tablet_hint, "caption", wrap=True))

    def _input(self, key, value):
        f = NumberField(value, self.driver.decimals)
        f.textChanged.connect(lambda _t: self._timer.start())
        self.inputs[key] = f
        return f

    @staticmethod
    def _name(text, field):
        """Field name, level with its input even when an error shows under it."""
        lbl = label(text, "muted")
        field.edit.ensurePolished()
        lbl.setFixedHeight(field.edit.sizeHint().height())
        return lbl

    def _set_timing(self, on):
        settings.update(tablet_timing=bool(on))
        self.refresh()

    def _set_driver(self, key):
        self.driver = DRIVERS[key]
        settings.update(tablet_driver=key)
        self._timer.stop()
        self._build_form()
        self.refresh()

    # ---------------------------------------------------------- page API --

    def set_analyses(self, analyses):
        self.analyses = list(analyses)
        self.refresh()

    def refresh(self):
        clear_layout(self.result)
        d = self.driver
        vals = {k: f.value() for k, f in self.inputs.items()}
        errors = {k: "enter a number" for k, v in vals.items() if v is None} or d.check(vals)
        for k, f in self.inputs.items():
            f.set_error(errors.get(k, ""))
        if errors:
            tablet = (vals["tablet_w"], vals["tablet_h"])
            if "tablet_w" in errors or "tablet_h" in errors:
                tablet = (d.defaults["tablet_w"], d.defaults["tablet_h"])
            self.tablet_view.set_data(tablet, None, None)
            self.heatmap.set_suggestion(None)
            self.aim_text.setText("")
            return
        area = d.edges(vals)
        tablet = (vals["tablet_w"], vals["tablet_h"])
        d.store(vals)

        if not self.analyses:
            self.tablet_view.set_data(tablet, area, None)
            self.heatmap.set_suggestion(None)
            self.aim_text.setText("")
            self._note("Pick one or more replays on the left (Ctrl+click to combine several: "
                       "the more notes, the more reliable the result).")
            return

        screen = self.screen_size()
        s = suggest_tablet_area(self.analyses, area, tablet, screen, on_time=bool(self.timing_opt.value))
        self.tablet_view.set_data(tablet, area, s.suggested)
        self.heatmap.set_suggestion(s)
        self._fill_aim_text(s)
        self._fill_result(s, area, len(self.analyses), screen)

    # ------------------------------------------------------------ content --

    def _note(self, text, role="caption"):
        lbl = label(text, role, wrap=True)
        self.result.addWidget(lbl)
        return lbl

    def _fill_aim_text(self, s):
        ms, hs = s.miss_split, s.hit_split
        lines = [f"Misses next to the note:  {ms.over} overaim  ·  {ms.under} underaim  "
                 f"({ms.over_pct:.0f}% overaim)" if ms.total else "No misses where you clicked next to the note."]
        if hs.total:
            lines.append(f"Hits:  {hs.over_pct:.0f}% overaim  ·  {100 - hs.over_pct:.0f}% underaim")
        t = s.timing
        if s.n_samples:
            when = "on time" if abs(t.mean) < 0.5 else f"{abs(t.mean):.0f} ms {'early' if t.mean < 0 else 'late'}"
            lines.append(f"Tap timing:  {when} on average  ·  {t.early_share * 100:.0f}% of clicks early")
            effect = timing_effect(t.curve)
            if effect:
                lines.append(effect[0].upper() + effect[1:] + ".")
        self.aim_text.setText("\n".join(lines))

    def _fill_result(self, s, area, n, screen):
        card = Card(title="Suggested area", border="accent")
        card.title.setStyleSheet(f"color: {theme.accent.name()};")
        card.body.addWidget(label(f"Based on {n} replay{'s' if n > 1 else ''}  ·  {s.n_samples} clicks", "caption"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        d = self.driver
        olds, news = d.values(area), d.values(s.suggested)
        for i, (key, name) in enumerate(d.fields):
            r, c = divmod(i, 2)
            old, new = olds[key], news[key]
            changed = abs(new - old) > 1e-6
            value = label(fmt(new) + (f"   {signed(new - old)}" if changed else ""), "metric-sm")
            if changed:
                value.setStyleSheet(f"color: {theme.gold.name()};")
            grid.addWidget(label(name, "muted"), r, c * 2)
            grid.addWidget(value, r, c * 2 + 1)
        grid.setColumnStretch(3, 1)
        copy = Button("Copy", icons.COPY, "primary")
        copy.clicked.connect(lambda: self._copy(s.suggested))
        row = hbox(spacing=12)
        row.addLayout(grid, 1)
        row.addWidget(copy, 0, Qt.AlignmentFlag.AlignTop)
        card.body.addLayout(row)
        ow, oh = area[3] - area[2], area[1] - area[0]
        nw, nh = s.suggested[3] - s.suggested[2], s.suggested[1] - s.suggested[0]
        if d.mm:
            size = (f"{nw * d.mm:.1f} × {nh * d.mm:.1f} mm   "
                    f"(was {ow * d.mm:.1f} × {oh * d.mm:.1f} mm)")
        else:
            size = f"{fmt(nw)} × {fmt(nh)}   (was {fmt(ow)} × {fmt(oh)})"
        card.body.addWidget(label(size, "caption"))
        self.result.addWidget(card)

        why = Card(title="Why")
        for key, name in EDGES:
            why.body.addWidget(label(f"{name}:  {describe_edge(key, s.edges[key], d)}", "body", wrap=True))
        why.body.addWidget(label(f"Estimated misses on {'this replay' if n == 1 else 'these replays'}:  "
                                 f"{s.misses_now}  →  {s.misses_after}", "h3"))
        notes = []
        if s.suggested == area:
            notes.append("Your area is already well calibrated: no edge shows a measurable overaim or underaim.")
        if s.misses_now and s.misses_now - s.misses_after <= max(1, s.misses_now // 10):
            notes.append("Most of your misses come from aim scatter, not from an area bias: "
                         "the area only fixes the systematic offset.")
        if s.clamped:
            notes.append("Large bias: change limited to ±15% per edge. Analyse again after a few maps "
                         "with the new area.")
        sw, sh = screen
        zr, sr = (area[3] - area[2]) / (area[1] - area[0]), sw / sh
        if abs(zr / sr - 1) > 0.05:
            notes.append(f"Computed for an area stretched over the whole {sw}×{sh} screen ({d.stretch_note}). "
                         f"Your area ratio ({zr:.2f}) differs from the screen's ({sr:.2f}).")
        if not s.on_time:
            notes.append("Not corrected for tap timing: early taps count as underaim and late ones as overaim.")
        elif not s.timing.curve:
            notes.append("Too few on-time taps to measure how your tap timing shifts your aim: not corrected.")
        elif s.as_tapped != s.suggested:
            notes.append(f"Corrected for tap timing. As tapped it would be  {d.copy_text(s.as_tapped)}:  "
                         "that difference comes from tapping early or late, which an area can't fix.")
        else:
            notes.append("Checked for tap timing: tapping early or late doesn't change this suggestion.")
        notes.append("Apply it, play a few maps, then analyse again: adjust in small steps.")
        for text in notes:
            why.body.addWidget(label(text, "caption", wrap=True))
        self.result.addWidget(why)

    def _copy(self, area):
        QGuiApplication.clipboard().setText(self.driver.copy_text(area))
        self.message.emit("Suggested area copied to the clipboard")

