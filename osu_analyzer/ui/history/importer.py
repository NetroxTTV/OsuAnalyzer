"""Fills the history from replays that were never opened in the app."""

import traceback

from PySide6.QtCore import QThread, Signal

from ...core import HistoryEntry, LoadError, ReplayLoader, read_replay_header


class HistoryImporter(QThread):
    """Analyses the newest replays that aren't in the history yet (up to `limit` of them).
    progress(done, total, text) while working, then done(added, skipped)."""

    progress = Signal(int, int, str)
    done = Signal(int, int)

    def __init__(self, history, install, paths, limit=50, slider_heads=True):
        super().__init__()
        self.history, self.install, self.paths = history, install, list(paths)
        self.limit, self.slider_heads = limit, slider_heads
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        added = skipped = 0
        loader = ReplayLoader(self.install)
        todo = []
        for p in self.paths:                      # newest first
            try:
                h = read_replay_header(p)
            except (OSError, ValueError, EOFError):
                continue
            if h.mode == 0 and HistoryEntry.id_for(h) not in self.history:
                todo.append(p)
            if len(todo) >= self.limit:
                break
        for i, p in enumerate(todo):
            if self._stop:
                break
            self.progress.emit(i, len(todo), p.name)
            try:
                a = loader.analyse(p, self.slider_heads, progress=lambda d, t: self.progress.emit(
                    i, len(todo), f"Indexing your beatmaps (first time only)  {d:,} / {t:,}"))
                self.history.record(a, self.slider_heads, area=None, save=False)
                added += 1
            except LoadError:
                skipped += 1
            except Exception:  # noqa: BLE001 - one broken replay must not stop the import
                traceback.print_exc()
                skipped += 1
            loader.clear()                        # keep memory flat
        self.history.save()
        self.progress.emit(len(todo), len(todo), "")
        self.done.emit(added, skipped)
