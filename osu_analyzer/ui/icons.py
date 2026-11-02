"""Icons: glyphs of the Windows icon font (Segoe Fluent Icons on Windows 11,
Segoe MDL2 Assets on Windows 10), so they stay sharp at any size and DPI."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont

PLAY = "\ue768"
PAUSE = "\ue769"
PREVIOUS = "\ue892"
NEXT = "\ue893"
SETTINGS = "\ue713"
REFRESH = "\ue72c"
ADD = "\ue710"
SEARCH = "\ue721"
CLOSE = "\ue711"
VOLUME = "\ue767"
MUTE = "\ue74f"
FOLDER = "\ue838"
SAVE = "\ue74e"
COPY = "\ue8c8"
VIDEO = "\ue714"
TARGET = "\uf272"
PEN = "\uedc6"
KEYBOARD = ""
MUSIC = "\ue8d6"
INFO = "\ue946"
CHEVRON_DOWN = "\ue70d"
HISTORY = "\ue81c"
DOWNLOAD = "\ue896"
DELETE = "\ue74d"


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
