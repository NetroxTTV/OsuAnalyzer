"""Icons: glyphs of the Windows icon font (Segoe Fluent Icons on Windows 11,
Segoe MDL2 Assets on Windows 10), so they stay sharp at any size and DPI."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont

PLAY = ""
PAUSE = ""
PREVIOUS = ""
NEXT = ""
SETTINGS = ""
REFRESH = ""
ADD = ""
SEARCH = ""
CLOSE = ""
VOLUME = ""
MUTE = ""
FOLDER = ""
SAVE = ""
COPY = ""
VIDEO = ""
TARGET = ""
PEN = ""
MUSIC = ""
INFO = ""
CHEVRON_DOWN = ""


def icon_font(pixel_size):
    f = QFont()
    f.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
    f.setPixelSize(max(1, round(pixel_size)))
    return f


def draw_icon(painter, rect, glyph, color, pixel_size=16):
    """Draw a glyph centred in rect (QRectF / QRect)."""
    painter.save()
    painter.setFont(icon_font(pixel_size))
    painter.setPen(color)
    painter.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.restore()
