"""Where the app keeps its data, and the user's settings (a small JSON file)."""

import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "osu-hit-analyzer"
INDEX_PATH = DATA_DIR / "beatmap_index.json"
SETTINGS_PATH = DATA_DIR / "settings.json"


class Settings:
    """Settings read once and kept in memory; every update is written straight back."""

    def __init__(self, path=SETTINGS_PATH):
        self.path = Path(path)
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def update(self, **values):
        """Merge values into the settings file (other keys are kept)."""
        self._data.update(values)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError:
            pass


settings = Settings()
