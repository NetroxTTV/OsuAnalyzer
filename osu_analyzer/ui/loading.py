"""Start-up loading screen with real progress.

The exe shows assets/splash.png (rendered from this widget by tools/make_splash.py) while it
unpacks itself; this window then takes its place, same size and position, and comes alive."""

import importlib
import threading
import time

from PySide6.QtCore import QEasingCurve, QEventLoop, QPoint, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QFontMetricsF, QGuiApplication, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from .. import __version__
from ..palette import DEFAULT_ACCENT
from .theme import qcolor, theme
from .widgets import paint_brand, painter

SIZE = QSize(460, 230)
FIRST_STATUS = "Starting..."


class LoadingScreen(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(SIZE)
        self.status = FIRST_STATUS
        self.fraction = 0.0
        self.accent = QColor(DEFAULT_ACCENT)     # same as splash.png, then glides to the user's accent
        self._phase = 0.0

        self._bar = QVariantAnimation(self, duration=450)
        self._bar.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._bar.valueChanged.connect(self._set_fraction)
        self._colour = QVariantAnimation(self, duration=500, startValue=QColor(self.accent), endValue=theme.accent)
        self._colour.valueChanged.connect(self._set_accent)
        self._fade = QVariantAnimation(self, duration=220, startValue=1.0, endValue=0.0)
        self._fade.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))
        self._fade.finished.connect(self.close)
        self._sheen = QTimer(self, interval=16)
        self._sheen.timeout.connect(self._tick)

    # ------------------------------------------------------------ public --

    def show_centered(self):
        """Centre on the screen under the mouse, like the exe's splash screen."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.geometry()
        self.move(QPoint(int(g.x() + 0.5 * (g.width() - SIZE.width())),
                         int(g.y() + 0.5 * (g.height() - SIZE.height()))))
        self.show()
        self._colour.start()
        self._sheen.start()
        self._pump()

    def step(self, text, fraction):
        """Show what is being done and how far along start-up is (0..1)."""
        self.status = text
        self._bar.stop()
        self._bar.setStartValue(self.fraction)
        self._bar.setEndValue(max(self.fraction, fraction))
        self._bar.start()
        self.update()
        self._pump()

    def import_modules(self, text, fraction, modules):
        """Import modules in a background thread so this screen keeps animating meanwhile."""
        self.step(text, fraction)
        errors, done = [], threading.Event()

        def work():
            try:
                for name in modules:
                    importlib.import_module(name)
            except BaseException as e:  # noqa: BLE001 - re-raised on the main thread
                errors.append(e)
            finally:
                done.set()

        threading.Thread(target=work, daemon=True).start()
        while not done.is_set():
            self._pump()
            time.sleep(0.004)
        if errors:
            raise errors[0]

    def finish(self):
        """Complete the bar, then fade out."""
        self.step("Ready", 1.0)
        QTimer.singleShot(self._bar.duration(), self._fade.start)

    # ---------------------------------------------------------- internal --

    def _pump(self):
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)

    def _set_fraction(self, v):
        self.fraction = float(v)
        self.update()

    def _set_accent(self, c):
        self.accent = QColor(c)
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.014) % 1.0
        self.update()

    def paintEvent(self, _e):
        self.paint(painter(self), sheen=self._sheen.isActive())

    def paint(self, p, sheen=False):
        r = QRectF(0, 0, SIZE.width(), SIZE.height())
        p.setPen(qcolor("#ffffff", 0.07))
        p.setBrush(theme.surface)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 18, 18)

        paint_brand(p, QRectF(36, 46, 64, 64), self.accent)
        p.setPen(theme.text)
        p.setFont(theme.semibold(19))
        p.drawText(QRectF(120, 44, 300, 36), Qt.AlignmentFlag.AlignVCenter, "Hit Analyzer")
        p.setPen(theme.muted)
        p.setFont(theme.font(10.5))
        p.drawText(QRectF(121, 80, 300, 24), Qt.AlignmentFlag.AlignVCenter, "Replay analysis for osu!")

        bar = QRectF(36, 152, SIZE.width() - 72, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("#ffffff", 0.08))
        p.drawRoundedRect(bar, 3, 3)
        if self.fraction > 0:
            fill = QRectF(bar.x(), bar.y(), max(bar.height(), bar.width() * self.fraction), bar.height())
            p.setBrush(self.accent)
            p.drawRoundedRect(fill, 3, 3)
            if sheen:
                seg = max(50.0, fill.width() * 0.35)
                x = fill.x() - seg + (fill.width() + seg) * self._phase
                g = QLinearGradient(x, 0, x + seg, 0)
                g.setColorAt(0, qcolor("#ffffff", 0))
                g.setColorAt(0.5, qcolor("#ffffff", 0.5))
                g.setColorAt(1, qcolor("#ffffff", 0))
                p.save()
                p.setClipRect(fill)
                p.setBrush(g)
                p.drawRoundedRect(fill, 3, 3)
                p.restore()

        font = theme.font(9)
        p.setFont(font)
        p.setPen(theme.muted)
        p.drawText(QRectF(36, 168, 300, 20), Qt.AlignmentFlag.AlignVCenter, self.status)
        version = f"v{__version__}"
        p.setPen(theme.subtle)
        w = QFontMetricsF(font).horizontalAdvance(version)
        p.drawText(QRectF(bar.right() - w - 2, 168, w + 2, 20), Qt.AlignmentFlag.AlignVCenter, version)


def render_splash_image():
    """The first frame of the loading screen as an image for PyInstaller's splash screen.
    Its window can only show fully opaque or fully transparent pixels, so the rounded
    corners are flattened onto the card colour and the outside is cut out."""
    screen = LoadingScreen()
    img = QImage(SIZE, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    screen.paint(p)
    p.end()
    bg = theme.surface
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            a = c.alphaF()
            if a >= 1.0:
                continue
            if a < 0.5:
                img.setPixelColor(x, y, QColor(0, 0, 0, 0))
            else:   # edge pixel: blend onto the card colour, fully opaque
                img.setPixelColor(x, y, QColor.fromRgbF(bg.redF() + (c.redF() - bg.redF()) * a,
                                                        bg.greenF() + (c.greenF() - bg.greenF()) * a,
                                                        bg.blueF() + (c.blueF() - bg.blueF()) * a))
    return img
