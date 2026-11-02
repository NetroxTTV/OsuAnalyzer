"""Tablet Zone page: suggests a tablet area from where you over / underaim on the playfield."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QIntValidator
from PySide6.QtWidgets import QGridLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from ...core import settings, suggest_tablet_area
from .. import icons
from ..theme import theme
from ..widgets import Button, Card, clear_layout, hbox, label
from .views import FieldHeatmap, TabletAreaView

AREA_DEFAULTS = {"top": 2000, "bottom": 5000, "left": 1600, "right": 5000,
                 "tablet_w": 15200, "tablet_h": 9500}
DEFAULT_TABLET = (AREA_DEFAULTS["tablet_w"], AREA_DEFAULTS["tablet_h"])
FIELDS = (("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right"))
SIDES = {"top": "top notes", "bottom": "bottom notes", "left": "left notes", "right": "right notes"}


def describe_edge(key, e):
    side = SIDES[key]
    if e.stderr is None:
        return "not enough notes to measure"
    d = e.suggested - e.current
    if d == 0:
        return f"no clear bias on {side}, unchanged"
    outward = d > 0 if key in ("bottom", "right") else d < 0
    if outward:
        return f"you overaim {side}  →  edge moved out by {abs(d)}"
    return f"you underaim {side}  →  edge moved in by {abs(d)}"


class TabletPage(QWidget):
    """screen_size() gives the resolution osu! runs at. message(text) reports to the status bar."""

    message = Signal(str)

    def __init__(self, screen_size, parent=None):
        super().__init__(parent)
        self.screen_size = screen_size
        self.analyses = []
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
        area.body.addWidget(label("As in Wacom Center, in tablet points (100 points = 1 mm).", "caption"))
        stored = {**AREA_DEFAULTS, **{k: settings[k] for k in AREA_DEFAULTS if k in settings}}
        self.inputs = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for i, (key, name) in enumerate(FIELDS):
            r, c = divmod(i, 2)
            grid.addWidget(label(name, "muted"), r, c * 2)
            grid.addWidget(self._input(key, stored[key]), r, c * 2 + 1)
        grid.addWidget(label("Tablet", "muted"), 2, 0)
        size = hbox(self._input("tablet_w", stored["tablet_w"]), label("×", "muted"),
                    self._input("tablet_h", stored["tablet_h"]), spacing=8)
        grid.addLayout(size, 2, 1, 1, 3)
        grid.setColumnStretch(4, 1)
        area.body.addLayout(grid)
        area.body.addWidget(label("Intuos S = 15200 × 9500", "caption"))
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
        self.aim_text = label("", "body", wrap=True)
        field.body.addWidget(self.aim_text)
        self.heatmap = FieldHeatmap()
        field.body.addWidget(self.heatmap, 1)
        field.body.addWidget(label("Arrow = where your cursor lands on average for notes in that area "
                                   "(drawn 4× bigger). Red = more misses.", "caption", wrap=True))
        outer.addWidget(field, 6)
        theme.changed.connect(self.refresh)
        self.refresh()

    def _input(self, key, value):
        e = QLineEdit(str(value))
        e.setValidator(QIntValidator(0, 100000, e))
        e.setFixedWidth(96)
        e.textChanged.connect(lambda _t: self._timer.start())
        self.inputs[key] = e
        return e

    # ---------------------------------------------------------- page API --

    def set_analyses(self, analyses):
        self.analyses = list(analyses)
        self.refresh()

    def refresh(self):
        clear_layout(self.result)
        try:
            vals = {k: int(e.text()) for k, e in self.inputs.items()}
        except ValueError:
            self._note("Enter whole numbers in every field.")
            return
        area = (vals["top"], vals["bottom"], vals["left"], vals["right"])
        tablet = (vals["tablet_w"], vals["tablet_h"])
        if area[1] <= area[0] or area[3] <= area[2] or min(tablet) <= 0:
            self._note("Bottom must be greater than Top, and Right greater than Left.")
            self.tablet_view.set_data(tablet if min(tablet) > 0 else DEFAULT_TABLET, None, None)
            return
        settings.update(**vals)

        if not self.analyses:
            self.tablet_view.set_data(tablet, area, None)
            self.heatmap.set_suggestion(None)
            self.aim_text.setText("")
            self._note("Pick one or more replays on the left (Ctrl+click to combine several: "
                       "the more notes, the more reliable the result).")
            return

        screen = self.screen_size()
        s = suggest_tablet_area(self.analyses, area, tablet, screen)
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
        self.aim_text.setText("\n".join(lines))

    def _fill_result(self, s, area, n, screen):
        card = Card(title="Suggested area", border="accent")
        card.title.setStyleSheet(f"color: {theme.accent.name()};")
        card.body.addWidget(label(f"Based on {n} replay{'s' if n > 1 else ''}  ·  {s.n_samples} clicks", "caption"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for i, (key, name) in enumerate(FIELDS):
            r, c = divmod(i, 2)
            old, new = area[i], s.suggested[i]
            value = label(f"{new}" + (f"   {new - old:+d}" if new != old else ""), "metric-sm")
            if new != old:
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
        ow, oh = (area[3] - area[2]) / 100, (area[1] - area[0]) / 100
        nw, nh = (s.suggested[3] - s.suggested[2]) / 100, (s.suggested[1] - s.suggested[0]) / 100
        card.body.addWidget(label(f"{nw:.1f} × {nh:.1f} mm   (was {ow:.1f} × {oh:.1f} mm)", "caption"))
        self.result.addWidget(card)

        why = Card(title="Why")
        for key, name in FIELDS:
            why.body.addWidget(label(f"{name}:  {describe_edge(key, s.edges[key])}", "body", wrap=True))
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
            notes.append(f"Computed for an area stretched over the whole {sw}×{sh} screen (\"Force "
                         f"proportions\" off). Your area ratio ({zr:.2f}) differs from the screen's ({sr:.2f}).")
        notes.append("Apply it, play a few maps, then analyse again: adjust in small steps.")
        for text in notes:
            why.body.addWidget(label(text, "caption", wrap=True))
        self.result.addWidget(why)

    def _copy(self, area):
        t, b, l, r = area
        QGuiApplication.clipboard().setText(f"Top {t}  Bottom {b}  Left {l}  Right {r}")
        self.message.emit("Suggested area copied to the clipboard")

