"""Application start-up: Qt settings, theme, window icon, the main window, and the self-test."""

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .theme import theme


def resource(name):
    """File shipped with the app (next to the package, or unpacked by PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / name


def close_splash():
    try:
        import pyi_splash  # only exists inside the PyInstaller exe
        pyi_splash.close()
    except ImportError:
        pass


def dark_title_bar(window):
    """Windows 10/11: dark title bar matching the app background."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), ctypes.sizeof(on))   # immersive dark mode
        c = theme.bg
        colour = ctypes.c_int(c.red() | c.green() << 8 | c.blue() << 16)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colour), ctypes.sizeof(colour))   # caption (Win 11)
    except Exception:  # noqa: BLE001 - older Windows: default title bar
        pass


def create_app(argv=None):
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("osu! Hit Analyzer")
    app.setStyle("Fusion")
    app.setFont(theme.font(10))
    app.setStyleSheet(theme.stylesheet())
    icon = resource("assets/icon.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    return app


def selftest(out_png, replay):
    """Headless check of the packaged app: analyse a replay and save the analyzer page, no window."""
    from ..core import OsuInstall, ReplayLoader
    from .analyzer import AnalyzerPage
    create_app([sys.argv[0], "-platform", "offscreen"])
    a = ReplayLoader(OsuInstall.detect()).analyse(replay)
    page = AnalyzerPage()
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    page.resize(1400, 900)
    page.show()
    page.set_analyses([a])
    QApplication.processEvents()
    page.grab_image().save(str(out_png))
    Path(out_png).with_suffix(".txt").write_text(f"{len(a.hits)} hits, {len(a.misses)} misses\n")


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":
        close_splash()
        selftest(sys.argv[2], sys.argv[3])
        return 0
    app = create_app()

    def report(exc, val, tb):
        traceback.print_exception(exc, val, tb)
        QMessageBox.critical(None, "Error", "".join(traceback.format_exception(exc, val, tb))[-2000:])
    sys.excepthook = report

    from .main_window import MainWindow
    files = [a for a in sys.argv[1:] if a.lower().endswith(".osr")]
    window = MainWindow(files)
    dark_title_bar(window)
    close_splash()
    window.showMaximized()
    return app.exec()
