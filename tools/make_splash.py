"""Regenerate assets/splash.png (shown by the exe while it unpacks) from the app's loading screen,
so the two look the same and the hand-over is seamless. Run after changing ui/loading.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from osu_analyzer.ui.app import create_app  # noqa: E402

if __name__ == "__main__":
    # 1:1 pixels: the splash is drawn by a DPI-unaware window, Windows scales it like the app
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_Use96Dpi)
    create_app([sys.argv[0]])
    from osu_analyzer.ui.loading import render_splash_image
    out = ROOT / "assets" / "splash.png"
    render_splash_image().save(str(out))
    print(f"Saved {out}")
