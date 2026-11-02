"""
Command line: plot where your cursor was when you hit each circle.

    python osu_hit_analyzer.py                       # file pickers
    python osu_hit_analyzer.py replay.osr            # beatmap found automatically
    python osu_hit_analyzer.py a.osr b.osr --save out.png
    python osu_hit_analyzer.py replay.osr --beatmap map.osu --frame movement
"""

import argparse
import math
import sys
from pathlib import Path

from . import __version__
from .core import BeatmapNotFound, LoadError, MISS_REASONS, OsuInstall, ReplayLoader, settings
from .palette import DEFAULT_ACCENT


def _qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pick_files(install):
    from PySide6.QtWidgets import QFileDialog
    _qt_app()
    initial = str(install.replays_dir) if install and install.replays_dir.is_dir() else ""
    files, _ = QFileDialog.getOpenFileNames(None, "Choose osu! replay(s)", initial,
                                            "osu! replay (*.osr);;All files (*.*)")
    return files


def _pick_beatmap(replay_name, install):
    from PySide6.QtWidgets import QFileDialog
    _qt_app()
    songs = str(install.songs_dir) if install and install.songs_dir.is_dir() else ""
    f, _ = QFileDialog.getOpenFileName(None, f"Beatmap not found for {replay_name} - choose the .osu file",
                                       songs, "osu! beatmap (*.osu);;All files (*.*)")
    return f or None


def _print_summary(a, bpath):
    replay, bm, hits = a.replay, a.beatmap, a.hits
    print(f"\n{replay.player} | {bm.artist} - {bm.title} [{bm.diff_name}] +{replay.mod_string}")
    print(f"  beatmap: {Path(bpath).name}")
    print(f"  radius {a.radius:.1f}px, windows 300/100/50 = "
          f"±{a.windows[0]:.1f}/{a.windows[1]:.1f}/{a.windows[2]:.1f} ms")
    if not hits:
        return
    mx = sum(h.dx for h in hits) / len(hits)
    my = sum(h.dy for h in hits) / len(hits)
    me = sum(h.error for h in hits) / len(hits)
    md = sum(math.hypot(h.dx, h.dy) / h.radius for h in hits) / len(hits)
    reasons = ", ".join(f"{sum(1 for m in a.misses if m.reason == r)} {r}" for r in MISS_REASONS)
    print(f"  {len(hits)} hits, {len(a.misses)} misses detected [{reasons}] (replay header: "
          f"{replay.n300}/{replay.n100}/{replay.n50}/{replay.nmiss}x)")
    print(f"  average hit offset: dx {mx:+.2f}px  dy {my:+.2f}px  "
          f"({math.hypot(mx, my) / a.radius * 100:.1f}% of radius)")
    print(f"  mean distance from centre: {md * 100:.1f}% of radius, mean timing {me:+.1f} ms")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plot where your cursor was when you hit each circle.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("replays", nargs="*", help=".osr file(s); opens a file picker if omitted")
    ap.add_argument("--beatmap", help=".osu file (otherwise found by MD5 in your Songs folder)")
    ap.add_argument("--osu-dir", help="osu! install folder (auto-detected)")
    ap.add_argument("--frame", choices=["screen", "movement"], default="screen",
                    help="screen = raw axes; movement = rotated so approach direction points right")
    ap.add_argument("--color", choices=["timing", "judgement"], default="timing",
                    help="colour hits by timing error or by 300/100/50")
    ap.add_argument("--circles-only", action="store_true", help="ignore slider heads")
    ap.add_argument("--save", help="save the plot to this image file instead of showing it")
    args = ap.parse_args(argv)

    install = OsuInstall.detect(args.osu_dir)
    loader = ReplayLoader(install)
    gui = not args.replays
    replay_paths = args.replays or _pick_files(install)
    if not replay_paths:
        print("No replay selected.")
        return 1

    analyses = []
    for rp in replay_paths:
        name = Path(rp).name
        try:
            try:
                bpath = args.beatmap
                a = loader.analyse(rp, not args.circles_only, beatmap=bpath)
            except BeatmapNotFound:
                bpath = _pick_beatmap(name, install) if gui else None
                if not bpath:
                    raise
                a = loader.analyse(rp, not args.circles_only, beatmap=bpath)
        except BeatmapNotFound:
            print(f"Skipping {name}: beatmap not found (use --beatmap)")
            continue
        except LoadError as e:
            print(f"Skipping {e}")
            continue
        analyses.append(a)
        _print_summary(a, a.beatmap.path)

    if not analyses:
        return 1
    from .plot import plot
    plot(analyses, frame=args.frame, color_by=args.color, save=args.save,
         accent=settings.get("accent", DEFAULT_ACCENT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
