"""The replay list: the osu! folder's replays plus files opened by hand, kept up to date."""

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from ..core import OsuInstall, settings


class ReplayLibrary(QObject):
    """Owns the osu! install and the list of replays shown in the sidebar.

    changed       the list of entries changed
    installChanged the osu! folder changed (or was found / lost)
    newReplay     osu! just saved a replay (F2 after a play, replay export), fully written
    """

    changed = Signal()
    installChanged = Signal()
    newReplay = Signal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = settings.get("osu_dir")
        self.install = OsuInstall(root) if root and Path(root).exists() else OsuInstall.detect()
        self.entries = []          # Paths, newest first (hand-opened files on top)
        self._extra = []           # files opened from elsewhere
        self.auto_load = settings.get("auto_load", True)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._debounce = QTimer(self, singleShot=True, interval=400)
        self._debounce.timeout.connect(self._rescan_for_new)
        self._watch()

    # -------------------------------------------------------------- folder --

    @property
    def has_folder(self):
        return bool(self.install and self.install.replays_dir.is_dir())

    def set_root(self, path):
        self.install = OsuInstall(path)
        settings.update(osu_dir=str(path))
        self._watch()
        self.refresh()
        self.installChanged.emit()

    def redetect(self):
        if not (self.install and self.install.exists):
            self.install = OsuInstall.detect()
            self._watch()
            self.installChanged.emit()

    def _watch(self):
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        if self.has_folder:
            self._watcher.addPath(str(self.install.replays_dir))

    # ------------------------------------------------------------- entries --

    def refresh(self):
        files = self.install.replays() if self.has_folder else []
        known = set(files)
        self._extra = [p for p in self._extra if p not in known and p.exists()]
        self.entries = self._extra + files
        self.changed.emit()

    def add_files(self, paths):
        for p in reversed([Path(p) for p in paths]):
            if p not in self.entries:
                self._extra.insert(0, p)
        self.refresh()

    def set_auto_load(self, on):
        self.auto_load = on
        settings.update(auto_load=on)

    # ---------------------------------------------------- new replay watch --

    def _on_dir_changed(self, _path):
        self._debounce.start()

    def _rescan_for_new(self):
        known = set(self.entries)
        self.refresh()
        new = [p for p in self.entries if p not in known]
        if new and self.auto_load:
            try:
                newest = max(new, key=lambda q: q.stat().st_mtime)
            except OSError:
                return
            self._wait_until_written(newest, -1, 0)

    def _wait_until_written(self, path, last_size, tries):
        try:
            size = path.stat().st_size
        except OSError:
            return
        if (size == last_size and size > 0) or tries > 25:
            self.newReplay.emit(path)
        else:
            QTimer.singleShot(300, lambda: self._wait_until_written(path, size, tries + 1))
