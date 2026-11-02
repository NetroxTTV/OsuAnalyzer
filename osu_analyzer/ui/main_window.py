"""Main window: sidebar on the left, navigation + pages on the right. Wires the library,
the analysis controller and the pages together (they don't know about each other)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from .. import __version__
from ..core import History, current_tablet_area, replay_label, settings
from . import icons
from .analyzer import AnalyzerPage
from .controller import AnalysisController
from .history import HistoryPage
from .library import ReplayLibrary
from .settings_page import SettingsPage
from .sidebar import Sidebar
from .tablet import TabletPage
from .updates import UpdateChecker
from .viewer import ViewerPage
from .widgets import IconButton, LoadingOverlay, SegmentedControl, Surface, hbox, label, set_role

PAGES = [("viewer", "Replay Viewer", icons.VIDEO), ("analyzer", "Hit Analyzer", icons.TARGET),
         ("tablet", "Tablet Zone", icons.PEN), ("history", "History", icons.HISTORY)]


class MainWindow(QMainWindow):
    def __init__(self, initial_files=(), progress=None):
        """progress(text, fraction) reports start-up steps (to the loading screen)."""
        super().__init__()
        progress = progress or (lambda _text, _fraction: None)
        progress("Finding your osu! folder...", 0.6)
        self.setWindowTitle(f"osu! Hit Analyzer {__version__}")
        self.setMinimumSize(1180, 740)
        self.setAcceptDrops(True)
        self.page = None
        self._dirty = set()          # pages to refresh when they are shown
        self._announce = None        # replay that was loaded automatically

        self.library = ReplayLibrary(self)
        self.controller = AnalysisController(self.library, self)
        self.controller.ask_beatmap = self._ask_beatmap
        self.history = History()
        self.updater = UpdateChecker(self)

        root = QWidget(objectName="Root")
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.sidebar = Sidebar()
        lay.addWidget(self.sidebar)
        divider = Surface("border")
        divider.setFixedWidth(1)
        lay.addWidget(divider)

        main = QWidget()
        lay.addWidget(main, 1)
        col = QVBoxLayout(main)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # Top bar: page navigation + settings
        self.nav = SegmentedControl([(k, name, glyph) for k, name, glyph in PAGES], "viewer",
                                    style="soft", height=40, font_size=10)
        self.nav.changed.connect(self.show_page)
        self.settings_btn = IconButton(icons.SETTINGS, "Settings", size=38)
        self.settings_btn.clicked.connect(lambda: self.show_page("settings"))
        col.addLayout(hbox(self.nav, None, self.settings_btn, margins=(24, 16, 24, 2)))

        # Pages
        self.pages_box = QWidget()
        box = QVBoxLayout(self.pages_box)
        box.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        box.addWidget(self.stack)
        col.addWidget(self.pages_box, 1)

        progress("Building the window...", 0.7)
        self.viewer = ViewerPage()
        self.analyzer = AnalyzerPage()
        self.tablet = TabletPage(self._screen_size)
        self.history_page = HistoryPage(self.history, self.library)
        self.settings = SettingsPage(self.library.auto_load, self.viewer.bg_dim, self.updater)
        self.pages = {"viewer": self.viewer, "analyzer": self.analyzer, "tablet": self.tablet,
                      "history": self.history_page, "settings": self.settings}
        for w in self.pages.values():
            self.stack.addWidget(w)
        self.overlay = LoadingOverlay(self.pages_box)

        self.status = label("", "caption")
        col.addLayout(hbox(self.status, None, margins=(26, 0, 26, 10)))

        self._connect()
        self._shortcuts()
        progress("Reading your replays...", 0.85)
        self.library.refresh()
        self.settings.set_folder(self.library.install.root if self.library.install else None)
        self.show_page("viewer")
        if initial_files:
            self.open_paths(initial_files)
        if settings.get("check_updates", True):
            QTimer.singleShot(2500, self.updater.check)

    # ------------------------------------------------------------ wiring --

    def _connect(self):
        lib, ctl, side = self.library, self.controller, self.sidebar
        lib.changed.connect(lambda: side.set_entries(lib.entries, lib.has_folder))
        lib.installChanged.connect(self._install_changed)
        lib.newReplay.connect(self._new_replay)

        side.selectionCommitted.connect(ctl.analyse)
        side.openRequested.connect(self.open_files)
        side.refreshRequested.connect(lib.refresh)
        side.chooseFolderRequested.connect(self.choose_osu_dir)

        ctl.started.connect(self._started)
        ctl.status.connect(self.overlay.set_status)
        ctl.progress.connect(self.overlay.set_progress)
        ctl.finished.connect(self._finished)

        self.analyzer.picked.connect(self._watch_note)
        self.analyzer.sliderHeadsChanged.connect(ctl.set_slider_heads)
        self.analyzer.sliderHeadsChanged.connect(lambda on: setattr(self.history_page, "slider_heads", on))
        self.analyzer.saveRequested.connect(self.save_image)
        self.tablet.message.connect(self.set_status)
        self.history_page.message.connect(self.set_status)
        self.history_page.openRequested.connect(self._open_from_history)
        self.updater.finished.connect(self._update_checked)

        self.settings.refreshRequested.connect(self.refresh_all)
        self.settings.chooseFolderRequested.connect(self.choose_osu_dir)
        self.settings.autoLoadChanged.connect(lib.set_auto_load)
        self.settings.bgDimChanged.connect(self._bg_dim_changed)

    def _shortcuts(self):
        for i, (key, _name, _glyph) in enumerate(PAGES, 1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, lambda k=key: self.show_page(k))
        QShortcut(QKeySequence("Ctrl+,"), self, lambda: self.show_page("settings"))
        QShortcut(QKeySequence("Ctrl+O"), self, self.open_files)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_image)
        QShortcut(QKeySequence("Ctrl+F"), self, self.sidebar.focus_search)
        QShortcut(QKeySequence("F5"), self, self.library.refresh)

    # ------------------------------------------------------------- pages --

    def show_page(self, key):
        if key == self.page:
            return
        self.page = key
        self.stack.setCurrentWidget(self.pages[key])
        self.nav.set_value(key if key != "settings" else None)
        self.settings_btn.set_active(key == "settings")
        if key == "settings":
            self.settings_btn.set_badge(False)
        self.viewer.set_active(key == "viewer")
        if key in self._dirty:
            self._dirty.discard(key)
            self.pages[key].set_analyses(self.controller.analyses)
        if key == "viewer":
            self.viewer.setFocus()

    def set_status(self, text, warning=False):
        self.status.setText(text)
        set_role(self.status, "warning" if warning else "caption")

    # ---------------------------------------------------------- analysis --

    def _started(self, title):
        self.sidebar.set_current(self.controller.current)
        self.overlay.start(title)

    def _finished(self, result):
        analyses = result.analyses
        self.overlay.set_status("Drawing...")
        self.viewer.set_analyses(analyses)
        self._record_history(analyses)
        self._dirty = {"analyzer", "tablet", "history"}
        if self.page in self._dirty:
            self._dirty.discard(self.page)
            self.pages[self.page].set_analyses(analyses)
        self.overlay.stop()
        self.sidebar.set_current(self.controller.current)

        if analyses:
            hits = sum(len(a.hits) for a in analyses)
            misses = sum(len(a.misses) for a in analyses)
            bm = analyses[0].beatmap
            what = f"{bm.artist} - {bm.title} [{bm.diff_name}]" if len(analyses) == 1 else f"{len(analyses)} replays"
            text = f"{what}   ·   {hits} hits, {misses} misses   ·   loaded in {result.elapsed:.1f} s"
        else:
            text = "Nothing to show"
        if self._announce:
            text = f"New replay loaded   ·   {text}"
            self._announce = None
        if result.errors:
            text += "   ·   skipped: " + "; ".join(result.errors)
        self.set_status(text, warning=bool(result.errors))

    def _record_history(self, analyses):
        """Keep a summary of each analysed replay. The tablet area is only known for plays
        from the last day (older ones may have been played with another area)."""
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        for a in analyses:
            played = a.replay.played_at
            area = current_tablet_area() if played and played >= recent else None
            self.history.record(a, self.controller.include_slider_heads, area, save=False)
        if analyses:
            self.history.save()

    def _open_from_history(self, path):
        if not Path(path).exists():
            self.set_status(f"Replay file not found: {path}", warning=True)
            return
        self.open_paths([path])
        self.show_page("analyzer")

    def _update_checked(self, release, _error):
        if release and release.is_newer and self.page != "settings":
            self.settings_btn.set_badge(True)
            self.set_status(f"Version {release.version} is available: open Settings to download it")

    def _watch_note(self, analysis, obj):
        self.show_page("viewer")
        self.viewer.show_note(analysis, obj)

    def _ask_beatmap(self, replay_path):
        songs = self.library.install.songs_dir if self.library.install else None
        f, _ = QFileDialog.getOpenFileName(
            self, f"Beatmap not found for {replay_label(replay_path)[0]} - choose the .osu file",
            str(songs) if songs and songs.is_dir() else "", "osu! beatmap (*.osu);;All files (*.*)")
        return f or None

    # ------------------------------------------------------------ library --

    def open_paths(self, paths):
        paths = [Path(p) for p in paths]
        self.library.add_files(paths)
        self.sidebar.clear_filter()
        self.controller.analyse(paths)

    def open_files(self):
        lib = self.library
        start = str(lib.install.replays_dir) if lib.has_folder else ""
        files, _ = QFileDialog.getOpenFileNames(self, "Choose osu! replay(s)", start,
                                                "osu! replay (*.osr);;All files (*.*)")
        if files:
            self.open_paths(files)

    def choose_osu_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose your osu! folder")
        if d:
            self.library.set_root(Path(d))

    def _install_changed(self):
        install = self.library.install
        self.settings.set_folder(install.root if install else None)

    def _new_replay(self, path):
        self._announce = path
        self.sidebar.clear_filter()
        self.controller.analyse([path])

    def refresh_all(self):
        """Rescan everything: osu! folder, replay list, beatmaps, current analysis."""
        self.library.redetect()
        self.library.refresh()
        self.controller.reload()
        self.set_status("Refreshed")

    def _screen_size(self):
        scr = self.screen().size() if self.screen() else None
        fallback = (scr.width(), scr.height()) if scr else (1920, 1080)
        install = self.library.install
        return install.screen_size(fallback) if install else fallback

    def _bg_dim_changed(self, value):
        settings.update(bg_dim=value)
        self.viewer.set_bg_dim(value)

    def save_image(self):
        if not self.controller.analyses:
            self.set_status("Pick a replay first.")
            return
        self.show_page("analyzer")
        a = self.controller.analyses[0]
        default = (f"{a.replay.player} - {a.beatmap.title} [{a.beatmap.diff_name}].png"
                   if len(self.controller.analyses) == 1 else "combined.png")
        default = "".join(c for c in default if c not in '\\/:*?"<>|')
        f, _ = QFileDialog.getSaveFileName(self, "Save image", default, "PNG image (*.png)")
        if f:
            self.analyzer.grab_image().save(f, "PNG")
            self.set_status(f"Saved {f}")

    # -------------------------------------------------------- drag & drop --

    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".osr") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(".osr")]
        if files:
            self.open_paths(files)

    def closeEvent(self, e):
        self.viewer.shutdown()
        self.history_page.shutdown()
        super().closeEvent(e)

