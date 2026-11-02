"""Finding the osu! install, its replays, and the beatmap that matches a replay."""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

from .settings import DATA_DIR, INDEX_PATH


def find_osu_dir(explicit=None):
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("OSU_DIR"):
        candidates.append(Path(os.environ["OSU_DIR"]))
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"osu\shell\open\command") as k:
                cmd = winreg.QueryValue(k, None)
            m = re.match(r'"([^"]+)"', cmd)
            if m:
                candidates.append(Path(m.group(1)).parent)
        except OSError:
            pass
    candidates += [
        Path(os.environ.get("LOCALAPPDATA", "")) / "osu!",
        Path.home() / "Documents" / "osu!",
        Path("C:/osu!"),
        Path("D:/osu!"),
    ]
    for c in candidates:
        if (c / "osu!.exe").exists() or (c / "Songs").is_dir():
            return c
    return None


def find_songs_dir(osu_dir: Path):
    # Respect a custom BeatmapDirectory from osu!.<user>.cfg
    for cfg in osu_dir.glob("osu!.*.cfg"):
        try:
            for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("BeatmapDirectory"):
                    d = Path(line.split("=", 1)[1].strip())
                    d = d if d.is_absolute() else osu_dir / d
                    if d.is_dir():
                        return d
        except OSError:
            pass
    return osu_dir / "Songs"


def _md5(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


def find_beatmap(md5, songs_dir: Path, progress=None):
    """Find the .osu with this MD5. `progress(done, total)` is called while indexing."""
    index = {}
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        if data.get("songs_dir") == str(songs_dir):
            index = data.get("files", {})
    except (OSError, ValueError):
        pass

    for rel, (_mtime, _size, h) in index.items():
        if h == md5 and (songs_dir / rel).exists():
            return songs_dir / rel

    if progress is None:
        print(f"Indexing beatmaps in {songs_dir} (first run can take a moment)...")
    new_index, found = {}, None
    files = list(songs_dir.rglob("*.osu"))
    if progress:
        progress(0, len(files))
    for k, p in enumerate(files, 1):
        rel = str(p.relative_to(songs_dir))
        try:
            st = p.stat()
        except OSError:
            continue
        e = index.get(rel)
        h = e[2] if e and e[0] == st.st_mtime and e[1] == st.st_size else _md5(p)
        new_index[rel] = [st.st_mtime, st.st_size, h]
        if h == md5:
            found = p
        if k % 250 == 0:
            if progress:
                progress(k, len(files))
            elif k % 2000 == 0:
                print(f"  {k}/{len(files)}")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps({"songs_dir": str(songs_dir), "files": new_index}),
                              encoding="utf-8")
    except OSError:
        pass
    return found


def screen_size(osu_dir, fallback=(1920, 1080)):
    """osu! fullscreen resolution from its config, else `fallback` (the monitor size)."""
    if osu_dir:
        for cfg in Path(osu_dir).glob("osu!.*.cfg"):
            try:
                kv = dict(line.split(" = ", 1) for line in
                          cfg.read_text(encoding="utf-8", errors="replace").splitlines() if " = " in line)
                w, h = int(kv["WidthFullscreen"]), int(kv["HeightFullscreen"])
                if w > 0 and h > 0:
                    return w, h
            except (OSError, KeyError, ValueError):
                continue
    return fallback


class OsuInstall:
    """An osu!stable folder: where its songs and replays are."""

    def __init__(self, root):
        self.root = Path(root)
        self.songs_dir = find_songs_dir(self.root)
        self.replays_dir = self.root / "Replays"

    @classmethod
    def detect(cls, explicit=None):
        root = find_osu_dir(explicit)
        return cls(root) if root else None

    @property
    def exists(self):
        return self.root.exists()

    def replays(self):
        """Replay files, newest first."""
        if not self.replays_dir.is_dir():
            return []
        files = []
        for p in self.replays_dir.glob("*.osr"):
            try:
                files.append((p.stat().st_mtime, p))
            except OSError:
                continue
        return [p for _m, p in sorted(files, key=lambda e: e[0], reverse=True)]

    def find_beatmap(self, md5, progress=None):
        if not self.songs_dir.is_dir():
            return None
        return find_beatmap(md5, self.songs_dir, progress)

    def screen_size(self, fallback=(1920, 1080)):
        return screen_size(self.root, fallback)


_REPLAY_NAME = re.compile(
    r"^(?P<player>.+?) - (?P<map>.+) \((?P<date>\d{4}-\d{2}-\d{2})\) \w+(?:-(?P<n>\d+))?$")


def replay_label(path):
    """'Player - Artist - Title [Diff] (2026-10-15) Osu-3.osr'
    -> ('Artist - Title', 'Diff  ·  Player', '10-15 #4')."""
    path = Path(path)
    stem = path.name[:-4] if path.name.lower().endswith(".osr") else path.name
    m = _REPLAY_NAME.match(stem)
    if not m:
        return stem, "", ""
    date = m.group("date")[5:]
    if m.group("n"):
        date += f" #{int(m.group('n')) + 1}"
    md = re.match(r"^(.*) \[(.*)\]$", m.group("map"))
    title, diff = (md.group(1), md.group(2)) if md else (m.group("map"), "")
    return title, "  ·  ".join(x for x in (diff, m.group("player")) if x), date
