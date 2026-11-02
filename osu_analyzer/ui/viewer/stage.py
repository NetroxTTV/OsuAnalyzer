"""The viewer's canvas: beatmap background, key timeline, playfield and hit error bar."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainterPath, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import qcolor
from ..widgets import painter
from .hud import HitErrorRenderer, KeyTimelineRenderer
from .playfield import PlayfieldRenderer

BG_SATURATION = 0.55   # beatmap background is desaturated so the circles stand out
RADIUS = 16
MARGIN = 14


class BackgroundCache:
    """The beatmap background scaled to cover a size, blurred and dimmed (made once per size)."""

    def __init__(self):
        self.source = None
        self._key = None
        self._pixmap = None

    def set_image(self, path):
        self.source, self._key, self._pixmap = None, None, None
        if not path or not path.exists():
            return
        try:
            from PIL import Image
            im = Image.open(path)
            im.draft("RGB", (1920, 1080))
            self.source = im.convert("RGB")
        except Exception:  # noqa: BLE001 - unreadable image: plain background
            self.source = None

    def pixmap(self, w, h, dim, dpr):
        if self.source is None or dim <= 0 or w < 2 or h < 2:
            return None
        key = (w, h, dim, dpr)
        if key != self._key:
            from PIL import Image, ImageEnhance, ImageFilter
            src = self.source
            pw, ph = max(1, int(w * dpr / 2)), max(1, int(h * dpr / 2))   # half size: it is blurred anyway
            sc = max(pw / src.width, ph / src.height)
            img = src.resize((max(1, round(src.width * sc)), max(1, round(src.height * sc))), Image.BILINEAR)
            left, top = (img.width - pw) // 2, (img.height - ph) // 2
            img = img.crop((left, top, left + pw, top + ph)).filter(ImageFilter.GaussianBlur(2))
            img = ImageEnhance.Color(img).enhance(BG_SATURATION)
            img = ImageEnhance.Brightness(img).enhance(dim)
            data = img.tobytes()
            qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888).copy()
            self._pixmap = QPixmap.fromImage(qimg)
            self._key = key
        return self._pixmap


class Stage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 300)
        self.scene = None
        self.t = 0.0
        self.bg_dim = 0.16
        self.background = BackgroundCache()
        self.playfield = PlayfieldRenderer()
        self.timeline = KeyTimelineRenderer()
        self.error_bar = HitErrorRenderer()

    def set_scene(self, scene):
        self.scene = scene
        self.background.set_image(scene.beatmap.background if scene else None)
        self.update()

    def set_time(self, t):
        self.t = t
        self.update()

    def set_bg_dim(self, dim):
        self.bg_dim = dim
        self.update()

    def paintEvent(self, _e):
        p = painter(self)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, RADIUS, RADIUS)
        p.setClipPath(clip)
        p.fillRect(r, qcolor("#0a0a0f"))
        if self.scene is None:
            return
        bg = self.background.pixmap(self.width(), self.height(), self.bg_dim, self.devicePixelRatioF())
        if bg is not None:
            p.drawPixmap(r, bg, QRectF(bg.rect()))

        inner = r.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        top = QRectF(inner.x(), inner.y(), inner.width(), KeyTimelineRenderer.HEIGHT)
        bottom = QRectF(inner.x(), inner.bottom() - HitErrorRenderer.HEIGHT, inner.width(),
                        HitErrorRenderer.HEIGHT)
        field = QRectF(inner.x(), top.bottom() + 6, inner.width(), bottom.top() - top.bottom() - 12)
        if field.height() > 60:
            self.playfield.paint(p, field, self.scene, self.t)
        self.timeline.paint(p, top, self.scene, self.t)
        self.error_bar.paint(p, bottom, self.scene, self.t)
        p.setClipping(False)
        p.setPen(qcolor("#ffffff", 0.06))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
