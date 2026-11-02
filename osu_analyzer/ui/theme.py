"""Colours, fonts and the application stylesheet. The accent colour can change at runtime:
everything reads it from `theme` when painting, and `theme.changed` tells cached views."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .. import palette
from ..core.settings import settings

FONT_FAMILIES = ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial")


def qcolor(c, alpha=None):
    """QColor from '#rrggbb', (r, g, b) or QColor; alpha 0..1 overrides the opacity."""
    col = QColor(*c) if isinstance(c, tuple) else QColor(c)
    if alpha is not None:
        col.setAlphaF(max(0.0, min(1.0, alpha)))
    return col


def mix(a, b, t):
    """Blend colour a towards b by t (0..1)."""
    a, b = qcolor(a), qcolor(b)
    t = max(0.0, min(1.0, t))
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t,
                           a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t,
                           a.alphaF() + (b.alphaF() - a.alphaF()) * t)


class Theme(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.bg = QColor(palette.BG)
        self.surface = QColor(palette.SURFACE)
        self.card = QColor(palette.CARD)
        self.elevated = QColor(palette.ELEVATED)
        self.border = QColor(palette.BORDER)
        self.text = QColor(palette.TEXT)
        self.muted = QColor(palette.MUTED)
        self.subtle = QColor(palette.SUBTLE)
        self.gold = QColor(palette.GOLD)
        self.miss = QColor(palette.MISS_RED)
        self.warning = QColor("#ffb347")
        self.accent = QColor(settings.get("accent", palette.DEFAULT_ACCENT))
        self._family = None

    # ------------------------------------------------------------- accent --

    @property
    def accent_hover(self):
        return mix(self.accent, "#ffffff", 0.16)

    @property
    def accent_pressed(self):
        return mix(self.accent, "#000000", 0.12)

    @property
    def on_accent(self):
        """Text colour readable on the accent."""
        return QColor("#14141a") if self.accent.lightnessF() > 0.55 else QColor("#ffffff")

    def accent_soft(self, alpha=0.16):
        return qcolor(self.accent, alpha)

    def set_accent(self, colour):
        self.accent = QColor(colour)
        settings.update(accent=self.accent.name())
        app = QApplication.instance()
        if app:
            app.setStyleSheet(self.stylesheet())
            for w in app.allWidgets():
                w.update()
        self.changed.emit()

    # -------------------------------------------------------------- fonts --

    @property
    def family(self):
        if self._family is None:
            available = set(QFontDatabase.families())
            self._family = next((f for f in FONT_FAMILIES if f in available), QFont().family())
        return self._family

    def font(self, size=10.0, weight=QFont.Weight.Normal):
        f = QFont(self.family)
        f.setPointSizeF(size)
        f.setWeight(weight)
        f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        return f

    def semibold(self, size=10.0):
        return self.font(size, QFont.Weight.DemiBold)

    def bold(self, size=10.0):
        return self.font(size, QFont.Weight.Bold)

    # --------------------------------------------------------- stylesheet --

    def stylesheet(self):
        c = {k: v.name() for k, v in vars(self).items() if isinstance(v, QColor)}
        c["accent_soft"] = self.accent_soft(0.35).name(QColor.NameFormat.HexArgb)
        c["on_accent"] = self.on_accent.name()
        c["family"] = self.family
        return """
        QWidget {{ color: {text}; font-family: "{family}"; font-size: 10pt; }}
        QMainWindow, #Root {{ background: {bg}; }}
        QToolTip {{ background: {elevated}; color: {text}; border: 1px solid {border};
                    border-radius: 6px; padding: 5px 8px; }}

        QLabel {{ background: transparent; }}
        QLabel[role="h1"] {{ font-size: 19pt; font-weight: 600; }}
        QLabel[role="h2"] {{ font-size: 14pt; font-weight: 600; }}
        QLabel[role="h3"] {{ font-size: 11pt; font-weight: 600; }}
        QLabel[role="body"] {{ color: {text}; }}
        QLabel[role="muted"] {{ color: {muted}; }}
        QLabel[role="caption"] {{ color: {muted}; font-size: 9pt; }}
        QLabel[role="overline"] {{ color: {muted}; font-size: 8pt; font-weight: 700;
                                   letter-spacing: 1px; }}
        QLabel[role="metric"] {{ font-size: 22pt; font-weight: 600; }}
        QLabel[role="metric-sm"] {{ font-size: 15pt; font-weight: 600; }}
        QLabel[role="warning"] {{ color: {warning}; }}

        QLineEdit {{ background: {elevated}; border: 1px solid {border}; border-radius: 8px;
                     padding: 6px 10px; selection-background-color: {accent_soft}; }}
        QLineEdit:hover {{ border-color: #3a3a4a; }}
        QLineEdit:focus {{ border-color: {accent}; }}
        QLineEdit#Bare {{ background: transparent; border: none; padding: 0; }}

        QComboBox {{ background: {elevated}; border: 1px solid {border}; border-radius: 8px;
                     padding: 6px 30px 6px 12px; min-height: 20px; }}
        QComboBox:hover {{ border-color: #3a3a4a; }}
        QComboBox:focus {{ border-color: {accent}; }}
        QComboBox::drop-down {{ border: none; width: 26px; }}
        QComboBox::down-arrow {{ image: none; }}
        QComboBox QAbstractItemView {{ background: {elevated}; border: 1px solid {border};
                     border-radius: 8px; padding: 4px; outline: 0;
                     selection-background-color: {accent_soft}; selection-color: {text}; }}

        QScrollArea {{ background: transparent; border: none; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QAbstractScrollArea {{ background: transparent; }}
        QListView {{ background: transparent; border: none; outline: 0; }}

        QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px 2px 2px 0; }}
        QScrollBar::handle:vertical {{ background-color: #3a3a4c; min-height: 36px; border-radius: 4px;
                                       margin: 0 2px; }}
        QScrollBar::handle:vertical:hover {{ background-color: #4b4b60; }}
        QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0 2px 2px 2px; }}
        QScrollBar::handle:horizontal {{ background-color: #3a3a4c; min-width: 36px; border-radius: 4px;
                                         margin: 2px 0; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

        QMenu {{ background: {elevated}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}
        QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
        QMenu::item:selected {{ background: {accent_soft}; }}

        QMessageBox, QDialog {{ background: {surface}; }}
        QMessageBox QPushButton, QDialog QPushButton {{ background: {elevated}; border: 1px solid {border};
                     border-radius: 6px; padding: 6px 18px; min-width: 60px; }}
        QMessageBox QPushButton:hover, QDialog QPushButton:hover {{ border-color: {accent}; }}
        """.format(**c)


theme = Theme()
