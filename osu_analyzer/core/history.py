"""History: a small summary of every analysed replay, kept to follow progress over time."""

import json
import threading
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from ..settings import DATA_DIR
from .stats import HitStats

HISTORY_PATH = DATA_DIR / "history.json"


@dataclass
class HistoryEntry:
    id: str                 # replay MD5 (unique per play), else the file name
    played_at: str          # ISO 8601, UTC
    replay_path: str
    player: str
    artist: str
    title: str
    diff: str
    mods: str
    accuracy: float         # 0..1
    grade: str
    max_combo: int
    hits: int
    misses: int
    ur: float
    mean_error: float       # ms, + = late
    offset: float           # average hit distance from the centre, in radii
    offset_x: float
    offset_y: float
    mean_distance: float    # radii
    slider_heads: bool      # slider heads were counted as hits
    area: list = None       # tablet area (top, bottom, left, right) when it was analysed, if known

    @property
    def date(self):
        return datetime.fromisoformat(self.played_at)

    @property
    def miss_rate(self):
        """Misses per 100 notes."""
        n = self.hits + self.misses
        return 100 * self.misses / n if n else 0.0

    @property
    def map_name(self):
        return f"{self.artist} - {self.title} [{self.diff}]"

    @staticmethod
    def id_for(replay):
        """Replay MD5 (unique per play), else the file name."""
        return replay.replay_md5 if len(replay.replay_md5) == 32 else Path(replay.path).name

    @classmethod
    def from_analysis(cls, a, slider_heads=True, area=None):
        rp, bm = a.replay, a.beatmap
        s = HitStats.compute([a], "screen")
        played = rp.played_at
        if played is None or played.year < 2007:   # no date in the replay: use the file's
            try:
                played = datetime.fromtimestamp(Path(rp.path).stat().st_mtime, timezone.utc)
            except OSError:
                played = datetime.now(timezone.utc)
        mx, my = s.mean
        return cls(
            id=cls.id_for(rp),
            played_at=played.isoformat(), replay_path=str(rp.path), player=rp.player,
            artist=bm.artist, title=bm.title, diff=bm.diff_name, mods=rp.mod_string,
            accuracy=rp.accuracy, grade=rp.grade, max_combo=rp.max_combo,
            hits=len(a.hits), misses=len(a.misses), ur=s.unstable_rate, mean_error=s.mean_error,
            offset=s.offset, offset_x=mx, offset_y=my, mean_distance=s.mean_distance,
            slider_heads=slider_heads, area=list(area) if area else None)


class History:
    """Entries sorted by play date, stored as JSON in the app's data folder. Thread-safe."""

    def __init__(self, path=HISTORY_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._entries = {}
        known = {f.name for f in fields(HistoryEntry)}
        try:
            for d in json.loads(self.path.read_text(encoding="utf-8")):
                e = HistoryEntry(**{k: v for k, v in d.items() if k in known})
                self._entries[e.id] = e
        except (OSError, ValueError, TypeError):
            pass

    @property
    def entries(self):
        with self._lock:
            return sorted(self._entries.values(), key=lambda e: e.played_at)

    def __len__(self):
        return len(self._entries)

    def __contains__(self, entry_id):
        return entry_id in self._entries

    def record(self, analysis, slider_heads=True, area=None, save=True):
        """Add (or update) the summary of an analysis. Returns the entry, or None if kept as is:
        an entry measured with slider heads is not replaced by one without."""
        e = HistoryEntry.from_analysis(analysis, slider_heads, area)
        with self._lock:
            old = self._entries.get(e.id)
            if old and old.slider_heads and not slider_heads:
                return None
            if old and old.area and not e.area:
                e.area = old.area
            self._entries[e.id] = e
        if save:
            self.save()
        return e

    def clear(self):
        with self._lock:
            self._entries.clear()
        self.save()

    def save(self):
        with self._lock:
            data = [asdict(e) for e in sorted(self._entries.values(), key=lambda e: e.played_at)]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass
