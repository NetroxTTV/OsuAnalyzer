"""Rapid Trigger page: analog keyboard settings suggested from how you tap."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QGridLayout, QScrollArea, QVBoxLayout, QWidget

from ...core import RTSettings, settings, suggest_rapid_trigger
from ...core.rapid_trigger import AP_RANGE, DEFAULTS, DOUBLE_GAP, RT_RANGE, percentile
from .. import icons
from ..theme import theme
from ..widgets import Button, Card, NumberField, clear_layout, hbox, label
from .views import ROWS, IntervalChart, SettingsBars

FIELDS = (("rt_actuation", "Actuation point"), ("rt_press", "RT press"), ("rt_release", "RT release"))
LIMITS = {"rt_actuation": AP_RANGE[1], "rt_press": RT_RANGE[1], "rt_release": RT_RANGE[1]}


class RapidTriggerPage(QWidget):
    """message(text) reports to the status bar."""

    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.analyses = []
        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self.refresh)

        outer = hbox(spacing=16, margins=(24, 18, 24, 18))
        self.setLayout(outer)

        # Left column: your settings and the suggestion
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left = QWidget()
        col = QVBoxLayout(left)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(12)
        scroll.setWidget(left)
        outer.addWidget(scroll, 5)

        keys = Card(title="Your keyboard")
        keys.body.addWidget(label("Analog (Hall effect) keyboard with rapid trigger on, in mm: "
                                  "your current settings, as in the keyboard's software.", "caption", wrap=True))
        self.inputs = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        top = Qt.AlignmentFlag.AlignTop
        for r, (key, name) in enumerate(FIELDS):
            f = self._input(key, settings.get(key, DEFAULTS[key]))
            f.edit.ensurePolished()
            h = f.edit.sizeHint().height()
            for c, w in ((0, label(name, "muted")), (1, f), (2, label("mm", "muted"))):
                if w is not f:
                    w.setFixedHeight(h)
                grid.addWidget(w, r, c, top)
        grid.setColumnStretch(3, 1)
        keys.body.addLayout(grid)
        keys.body.addWidget(label("Actuation = depth of the first press from rest  ·  RT press / release = "
                                  "travel down / up that triggers the next press / release.", "caption", wrap=True))
        keys.body.addSpacing(6)
        self.bars = SettingsBars()
        keys.body.addWidget(self.bars)
        col.addWidget(keys)

        self.result = QVBoxLayout()
        self.result.setSpacing(12)
        col.addLayout(self.result)
        col.addStretch(1)

        # Right column: how you tap
        taps = Card(title="How you tap")
        taps.body.addWidget(label("Measured on the presses that hit notes, in real time (DT / HT taken "
                                  "into account).", "caption", wrap=True))
        self.tap_text = label("", "body", wrap=True)
        taps.body.addWidget(self.tap_text)
        self.chart = IntervalChart()
        taps.body.addWidget(self.chart, 1)
        taps.body.addWidget(label("Time between two presses of the same key. The fastest ones decide how "
                                  "little your finger travels, so how small the distances must be.",
                                  "caption", wrap=True))
        outer.addWidget(taps, 6)
        theme.changed.connect(self.refresh)
        self.refresh()

    def _input(self, key, value):
        f = NumberField(value, decimals=2, maximum=LIMITS[key], width=80)
        f.textChanged.connect(lambda _t: self._timer.start())
        self.inputs[key] = f
        return f

    # ---------------------------------------------------------- page API --

    def set_analyses(self, analyses):
        self.analyses = list(analyses)
        self.refresh()

    def refresh(self):
        clear_layout(self.result)
        vals = {k: f.value() for k, f in self.inputs.items()}
        errors = {}
        for k, v in vals.items():
            if v is None:
                errors[k] = "enter a number"
            elif v <= 0:
                errors[k] = "must be > 0"
            elif v > LIMITS[k]:
                errors[k] = f"max {LIMITS[k]:g} mm"
        for k, f in self.inputs.items():
            f.set_error(errors.get(k, ""))
        if errors:
            self.bars.set_data(None, None)
            return
        settings.update(**vals)
        current = RTSettings(vals["rt_actuation"], vals["rt_press"], vals["rt_release"])

        if not self.analyses:
            self.bars.set_data(current, None)
            self.chart.set_data([], None)
            self.tap_text.setText("")
            self._note("Pick one or more replays on the left (Ctrl+click to combine several: "
                       "the more notes, the more reliable the result). Fast maps tell the most.")
            return

        s, stats = suggest_rapid_trigger(self.analyses, current)
        self._fill_tap_text(stats)
        self.chart.set_data(stats.intervals, s.fast_interval if s else None)
        if s is None:
            self.bars.set_data(current, None)
            self._note("Not enough notes pressed with the same key twice in a row: pick more replays, "
                       "ideally with streams.")
            return
        self.bars.set_data(current, s.suggested)
        self._fill_result(s, len(self.analyses))

    # ------------------------------------------------------------ content --

    def _note(self, text, role="caption"):
        lbl = label(text, role, wrap=True)
        self.result.addWidget(lbl)
        return lbl

    def _fill_tap_text(self, st):
        hold = percentile(st.holds, 0.5)
        lines = [f"{st.presses} presses  ·  {st.alternate_share * 100:.0f}% alternating"
                 + (f"  ·  median hold {hold:.0f} ms" if hold is not None else ""),
                 f"Double presses: {len(st.doubles)}  ·  broken slider holds: {len(st.broken)}  ·  "
                 f"stuck keys: {len(st.stuck)}"]
        late = st.late_on_repress
        if late is not None:
            lines.append(f"Quick re-presses vs presses from rest:  {late:+.1f} ms")
        self.tap_text.setText("\n".join(lines))

    def _fill_result(self, s, n):
        card = Card(title="Suggested settings", border="accent")
        card.title.setStyleSheet(f"color: {theme.accent.name()};")
        card.body.addWidget(label(f"Based on {n} replay{'s' if n > 1 else ''}  ·  "
                                  f"{len(s.stats.intervals)} same-key re-presses", "caption"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for r, (key, name) in enumerate(ROWS):
            old, new = getattr(s.current, key), getattr(s.suggested, key)
            changed = abs(new - old) > 1e-6
            value = label(f"{new:.2f} mm" + (f"   {new - old:+.2f}" if changed else ""), "metric-sm")
            if changed:
                value.setStyleSheet(f"color: {theme.gold.name()};")
            grid.addWidget(label(name, "muted"), r, 0)
            grid.addWidget(value, r, 1)
        grid.setColumnStretch(1, 1)
        copy = Button("Copy", icons.COPY, "primary")
        copy.clicked.connect(lambda: self._copy(s.suggested))
        row = hbox(spacing=12)
        row.addLayout(grid, 1)
        row.addWidget(copy, 0, Qt.AlignmentFlag.AlignTop)
        card.body.addLayout(row)
        self.result.addWidget(card)

        why = Card(title="Why")
        for key, name in ROWS:
            why.body.addWidget(label(f"{name}:  " + ";  ".join(s.reasons[key]), "body", wrap=True))
        notes = list(s.conflicts)
        st = s.stats
        if st.keyboard_share < 0.5:
            notes.append(f"Only {st.keyboard_share * 100:.0f}% of your presses come from the keyboard keys "
                         "(K1 / K2): rapid trigger only applies to an analog keyboard.")
        if not (st.doubles or st.broken or st.stuck) and s.suggested.as_tuple() == s.current.as_tuple():
            notes.append("Your settings already fit how you tap.")
        notes.append(f"Double press = released and pressed again within {DOUBLE_GAP} ms on no note. Change one "
                     "setting at a time, play a few maps, then analyse again. Keyboards that go below 0.1 mm "
                     "can go lower if nothing misfires.")
        for text in notes:
            why.body.addWidget(label(text, "caption", wrap=True))
        self.result.addWidget(why)

    def _copy(self, rt):
        QGuiApplication.clipboard().setText(f"Actuation {rt.actuation:.2f} mm  RT press {rt.press:.2f} mm  "
                                            f"RT release {rt.release:.2f} mm")
        self.message.emit("Suggested settings copied to the clipboard")
