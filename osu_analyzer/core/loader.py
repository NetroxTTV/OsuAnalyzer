"""Replay + beatmap loading, shared by the app and the command line."""

from pathlib import Path

from .analysis import analyse
from .beatmap import read_beatmap
from .replay import MOD_EZ, MOD_HR, read_replay


class LoadError(Exception):
    """The replay can't be analysed (shown to the user as is)."""


class BeatmapNotFound(LoadError):
    def __init__(self, replay_path):
        super().__init__(f"{Path(replay_path).name}: beatmap not found")
        self.replay_path = Path(replay_path)


class ReplayLoader:
    """Reads replays and finds their beatmaps, keeping what it loaded for the next time."""

    def __init__(self, install=None):
        self.install = install
        self._cache = {}   # str(replay path) -> (Replay, Beatmap)

    def clear(self):
        self._cache.clear()

    def load(self, path, beatmap=None, status=None, progress=None):
        """(Replay, Beatmap) for a replay file. `beatmap` forces the .osu file to use.
        status(text) and progress(done, total) report what is going on."""
        path = Path(path)
        key = str(path)
        if key in self._cache:
            return self._cache[key]
        status = status or (lambda _text: None)

        status(f"Reading replay  {path.name}")
        replay = read_replay(path)
        if replay.mode != 0:
            raise LoadError(f"{path.name}: not an osu!standard replay")
        bpath = beatmap
        if not bpath and self.install:
            status("Looking for the beatmap...")
            bpath = self.install.find_beatmap(replay.beatmap_md5, progress)
        if not bpath:
            raise BeatmapNotFound(path)
        status(f"Loading beatmap  {Path(bpath).name}")
        bm = read_beatmap(bpath, hard_rock=bool(replay.mods & MOD_HR), easy=bool(replay.mods & MOD_EZ))
        self._cache[key] = (replay, bm)
        return replay, bm

    def analyse(self, path, include_slider_heads=True, beatmap=None, status=None, progress=None):
        replay, bm = self.load(path, beatmap, status, progress)
        if status:
            status("Calculating hits and cursor offsets...")
        return analyse(replay, bm, include_slider_heads=include_slider_heads)
