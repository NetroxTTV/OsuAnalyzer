"""The viewer's canvas: beatmap background, key timeline, playfield and hit error bar."""

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QImageReader, QPainterPath, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import qcolor
from ..widgets import painter
from .hud import HitErrorRenderer, KeyTimelineRenderer
from .playfield import PlayfieldRenderer

BG_SATURATION = 0.55   # beatmap background is desaturated so the circles stand out
RADIUS = 16
MARGIN = 14


def _box_blur(a, r):
    """Box blur of an (h, w, 3) float array along both axes (radius r, edges clamped)."""
    for axis in (0, 1):
        pad = [(0, 0)] * 3
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis)
        hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
        lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
        a = (hi - lo) / (2 * r + 1)
    return a


class BackgroundCache:
    """The beatmap background scaled to cover a size, blurred, desaturated and dimmed
    (made once per size)."""

    def __init__(self):
        self.source = None
        self._key = None
        self._pixmap = None

    def set_image(self, path):
        self.source, self._key, self._pixmap = None, None, None
        if not path or not path.exists():
            return
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and size.width() > 1920:      # huge backgrounds: decode smaller
            reader.setScaledSize(size.scaled(1920, 1920, Qt.AspectRatioMode.KeepAspectRatio))
        img = reader.read()
        self.source = None if img.isNull() else img.convertToFormat(QImage.Format.Format_RGB888)

    def pixmap(self, w, h, dim, dpr):
        if self.source is None or dim <= 0 or w < 2 or h < 2:
            return None
        key = (w, h, dim, dpr)
        if key != self._key:
            pw, ph = max(1, int(w * dpr / 2)), max(1, int(h * dpr / 2))   # half size: it is blurred anyway
            img = self.source.scaled(pw, ph, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
            img = img.copy((img.width() - pw) // 2, (img.height() - ph) // 2, pw, ph)
            img = img.convertToFormat(QImage.Format.Format_RGB888)
            a = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes())
            a = a.reshape(ph, img.bytesPerLine())[:, :pw * 3].reshape(ph, pw, 3).astype(np.float32)
            a = _box_blur(_box_blur(a, 2), 2)                 # two box passes ~ gaussian
            grey = a @ np.array([0.299, 0.587, 0.114], np.float32)
            a = (grey[..., None] + (a - grey[..., None]) * BG_SATURATION) * dim
            out = np.ascontiguousarray(np.clip(a, 0, 255).astype(np.uint8))
            self._pixmap = QPixmap.fromImage(QImage(out.data, pw, ph, pw * 3, QImage.Format.Format_RGB888).copy())
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
