"""Runs the analysis of the selected replays in a background thread and tells the UI."""

import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ..core import BeatmapNotFound, LoadError, ReplayLoader


@dataclass
class AnalysisResult:
    paths: list
    analyses: list = field(default_factory=list)
    missing: list = field(default_factory=list)    # replay paths whose beatmap wasn't found
    errors: list = field(default_factory=list)     # messages
    elapsed: float = 0.0


class _Job(QThread):
    status = Signal(str)
    progress = Signal(str, int, int)
    done = Signal(object)

    def __init__(self, loader, paths, heads, overrides):
        super().__init__()
        self.loader, self.paths, self.heads, self.overrides = loader, paths, heads, overrides

    def run(self):
        started = time.perf_counter()
        result = AnalysisResult(self.paths)
        n = len(self.paths)
        for i, p in enumerate(self.paths, 1):
            tag = f"[{i}/{n}]  " if n > 1 else ""
            try:
                a = self.loader.analyse(
                    p, self.heads, beatmap=self.overrides.get(str(p)),
                    status=lambda text: self.status.emit(tag + text),
                    progress=lambda d, t: self.progress.emit(
                        f"Indexing your beatmaps (first time only)  {d:,} / {t:,}", d, t))
                result.analyses.append(a)
            except BeatmapNotFound:
                result.missing.append(p)
            except LoadError as e:
                result.errors.append(str(e))
            except Exception as e:  # noqa: BLE001 - shown to the user
                result.errors.append(f"{p.name}: {e}")
                traceback.print_exc()
        result.elapsed = time.perf_counter() - started
        self.done.emit(result)


class AnalysisController(QObject):
    """started(title) -> status / progress ... -> finished(AnalysisResult).
    `ask_beatmap(replay_path)` is called (on the UI thread) when a beatmap can't be found;
    it returns a .osu path or None."""

    started = Signal(str)
    status = Signal(str)
    progress = Signal(str, int, int)
    finished = Signal(object)

    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.loader = ReplayLoader(library.install)
        library.installChanged.connect(self._install_changed)
        self.include_slider_heads = True
        self.current = []          # replay paths of the current analysis
        self.analyses = []
        self.ask_beatmap = lambda _path: None
        self._job = None
        self._pending = None

    @property
    def busy(self):
        return self._job is not None

    def _install_changed(self):
        self.loader = ReplayLoader(self.library.install)

    def analyse(self, paths, overrides=None):
        paths = [Path(p) for p in paths]
        if self._job:
            self._pending = (paths, overrides)
            return
        self.current = paths
        self.started.emit("Analysing..." if len(paths) == 1 else f"Analysing {len(paths)} replays...")
        self._job = _Job(self.loader, paths, self.include_slider_heads, overrides or {})
        self._job.status.connect(self.status)
        self._job.progress.connect(self.progress)
        self._job.done.connect(self._done)
        self._job.start()

    def reanalyse(self):
        if self.current:
            self.analyse(self.current)

    def set_slider_heads(self, on):
        self.include_slider_heads = on
        self.reanalyse()

    def reload(self):
        """Forget what was loaded and analyse the current selection again."""
        self.loader.clear()
        self.reanalyse()

    def _done(self, result):
        self._job.wait()
        self._job = None
        if self._pending:
            paths, overrides = self._pending
            self._pending = None
            self.analyse(paths, overrides)
            return
        # Beatmaps that couldn't be found automatically: ask for the .osu files
        overrides = {}
        for p in result.missing:
            f = self.ask_beatmap(p)
            if f:
                overrides[str(p)] = f
        if overrides:
            self.analyse([p for p in result.paths if p not in result.missing or str(p) in overrides],
                         overrides)
            return
        result.errors += [f"{p.name}: beatmap not found" for p in result.missing]
        self.analyses = result.analyses
        self.finished.emit(result)
