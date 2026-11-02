"""Settings page."""

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from .. import __version__
from ..core import DATA_DIR
from ..palette import ACCENTS
from . import icons
from .theme import theme
from .widgets import Button, Card, SegmentedControl, Swatches, label

BG_LEVELS = [(0.0, "Off"), (0.1, "Darker"), (0.16, "Dark"), (0.26, "Dim")]


class SettingsPage(QWidget):
    refreshRequested = Signal()
    chooseFolderRequested = Signal()
    autoLoadChanged = Signal(bool)
    bgDimChanged = Signal(float)

    def __init__(self, auto_load, bg_dim, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        page = QWidget()
        scroll.setWidget(page)
        centre = QHBoxLayout(page)
        centre.setContentsMargins(24, 28, 24, 28)
        centre.addStretch(1)
        column = QWidget()
        column.setMaximumWidth(780)
        column.setMinimumWidth(520)
        centre.addWidget(column, 4)
        centre.addStretch(1)
        self.col = QVBoxLayout(column)
        self.col.setSpacing(12)
        self.col.addWidget(label("Settings", "h1"))
        self.col.addSpacing(8)

        self._section("Library")
        self.folder_text = label("", "caption", wrap=True)
        change = Button("Change...", icons.FOLDER)
        change.clicked.connect(self.chooseFolderRequested)
        self._row("osu! folder", self.folder_text, change)
        refresh = Button("Refresh everything", icons.REFRESH)
        refresh.clicked.connect(self.refreshRequested)
        self._row("Refresh", "Rescan your replays, reload the beatmaps and analyse the current selection again.",
                  refresh)
        auto = SegmentedControl([(True, "On"), (False, "Off")], auto_load)
        auto.changed.connect(lambda v: self.autoLoadChanged.emit(bool(v)))
        self._row("Load new replays", "Open a replay automatically as soon as osu! saves it "
                  "(F2 after a play, or exporting a replay).", auto)

        self._section("Appearance")
        swatches = Swatches(ACCENTS, theme.accent.name())
        swatches.changed.connect(theme.set_accent)
        self._row("Accent colour", "Used for highlights, buttons and the analyzer.", swatches)
        nearest = min(BG_LEVELS, key=lambda lv: abs(lv[0] - bg_dim))[0]
        dim = SegmentedControl(BG_LEVELS, nearest)
        dim.changed.connect(lambda v: self.bgDimChanged.emit(float(v)))
        self._row("Viewer background", "How visible the beatmap background is behind the replay.", dim)

        self._section("About")
        open_data = Button("Open folder", icons.FOLDER)
        open_data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR))))
        self._row(f"osu! Hit Analyzer {__version__}",
                  f"Settings and the beatmap index are kept in {DATA_DIR}. Delete that folder to reset "
                  "everything. Your osu! files are only ever read, never modified.", open_data)
        self.col.addStretch(1)

    def _section(self, title):
        self.col.addSpacing(8)
        self.col.addWidget(label(title.upper(), "overline"))

    def _row(self, title, description, control):
        card = Card(padding=(22, 16, 22, 16))
        row = QHBoxLayout()
        row.setSpacing(24)
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(label(title, "h3"))
        text.addWidget(description if isinstance(description, QWidget) else label(description, "caption", wrap=True))
        row.addLayout(text, 1)
        row.addWidget(control)
        card.body.addLayout(row)
        self.col.addWidget(card)
        return card

    def set_folder(self, path):
        self.folder_text.setText(str(path) if path else "Not found: choose it with Change...")
