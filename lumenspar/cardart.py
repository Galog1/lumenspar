"""The build card's backdrop, baked once per character.

QML cannot round-clip, blur or soften edges without shader effects (which not
every graphics setup runs), so the card's whole background is composed here
with QPainter and shown as one plain image: the character's splash art with a
soft element-coloured halo, rings and a dark, quiet area for the stats. The
element is part of the file name because the Traveler shares art across
elements.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPen,
                           QRadialGradient)

from .wishes import icons

# The card at 2x: 1200x640 on screen.
W, H = 2400, 1280
BANNER_W = 920              # the sharp art spans this much from the left edge
VERSION = "bg1"             # bump when the look changes, so old backdrops are redone

ELEMENT_COLORS = {"pyro": "#EF7938", "hydro": "#4CC2F1", "anemo": "#74C2A8",
                  "electro": "#B08FC2", "dendro": "#A5C83B", "cryo": "#9FD6E3",
                  "geo": "#FAB632"}
DEFAULT_COLOR = "#4FD8E8"


def backdrop_name(splash: str, element: str) -> str:
    return f"{splash}_{element or 'x'}_{VERSION}" if splash else ""


def backdrop_path(name: str, root: Path = icons.ICON_DIR) -> Path:
    return root / f"{name}.jpg"


def _box(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    k = 2 * r + 1
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    return ((np.take(c, range(k, k + n), axis) - np.take(c, range(0, n), axis)) / k
            ).astype(np.float32)


def blur(img: QImage, radius: int, shrink: int = 8) -> QImage:
    """A Gaussian-like blur (three box passes) done at 1/shrink size, stretched back."""
    w, h = img.width(), img.height()
    small = img.scaled(max(1, w // shrink), max(1, h // shrink), Qt.IgnoreAspectRatio,
                       Qt.SmoothTransformation).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    w2, h2 = small.width(), small.height()
    a = np.frombuffer(small.constBits(), np.uint8).reshape(h2, small.bytesPerLine())[:, :w2 * 4]
    a = a.reshape(h2, w2, 4).astype(np.float32)
    r = max(1, radius // shrink)
    for _ in range(3):
        a = _box(_box(a, r, 0), r, 1)
    q = QImage(np.clip(a, 0, 255).astype(np.uint8).tobytes(), w2, h2, w2 * 4,
               QImage.Format_ARGB32_Premultiplied).copy()
    return q.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def fade_right(layer: QImage, full: int, zero: int) -> QImage:
    """Scale a layer's alpha by a ramp: 1 up to x=`full`, 0 from x=`zero`."""
    p = QPainter(layer)
    p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    f = QLinearGradient(0, 0, zero, 0)
    f.setColorAt(0.0, QColor(0, 0, 0, 255))
    f.setColorAt(full / zero, QColor(0, 0, 0, 255))
    f.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(0, 0, zero, layer.height(), f)
    p.fillRect(zero, 0, layer.width() - zero, layer.height(), QColor(0, 0, 0, 0))
    p.end()
    return layer


def centre_of(img: QImage) -> float:
    """Where the character is, horizontally: the centre of mass of the art's opacity."""
    a = img.convertToFormat(QImage.Format_Alpha8)
    arr = np.frombuffer(a.constBits(), np.uint8).reshape(a.height(), a.bytesPerLine())[:, :a.width()]
    cols = arr.sum(axis=0).astype(float)
    if cols.sum() <= 0:
        return a.width() / 2
    return float((cols * np.arange(a.width())).sum() / cols.sum())


def _tint(color: QColor, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(alpha)
    return c


def bake(src: Path, dst: Path, element: str) -> bool:
    """Compose the card backdrop from a splash art file; False if it cannot be read or saved."""
    img = QImage(str(src))
    if img.isNull():
        return False
    img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    tint = QColor(ELEMENT_COLORS.get(element, DEFAULT_COLOR))
    scale = H / img.height()
    x0 = min(max(centre_of(img) * scale - BANNER_W * 0.46, 0), max(0.0, img.width() * scale - BANNER_W))
    art = img.scaled(int(img.width() * scale), H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    card_art = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    card_art.fill(Qt.transparent)
    cp = QPainter(card_art)
    cp.drawImage(QPointF(-x0, 0), art)
    cp.end()

    out = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    out.fill(QColor("#0A0E16"))
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    # a colour smudge of the art, gone before the info columns
    p.setOpacity(0.6)
    p.drawImage(0, 0, fade_right(blur(card_art, 110), 700, 1500))
    p.setOpacity(1)
    # element wash, strongest on the left
    g = QLinearGradient(0, 0, W, 0)
    g.setColorAt(0.0, _tint(tint, 0.34))
    g.setColorAt(0.5, _tint(tint, 0.07))
    g.setColorAt(1.0, _tint(tint, 0.15))
    p.fillRect(0, 0, W, H, g)
    # glow and rings behind the character
    r = QRadialGradient(QPointF(BANNER_W * 0.46, H * 0.46), 760)
    r.setColorAt(0.0, _tint(tint, 0.50))
    r.setColorAt(0.6, _tint(tint, 0.12))
    r.setColorAt(1.0, _tint(tint, 0.0))
    p.fillRect(0, 0, W, H, r)
    for radius, alpha, width in ((330, 0.34, 3), (520, 0.22, 2), (730, 0.14, 2), (960, 0.08, 2)):
        p.setPen(QPen(_tint(tint, alpha), width))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(BANNER_W * 0.46, H * 0.44), radius, radius)
    # the silhouette, tinted and softened, as an aura
    sil = QImage(card_art)
    sp = QPainter(sil)
    sp.setCompositionMode(QPainter.CompositionMode_SourceIn)
    sp.fillRect(sil.rect(), tint)
    sp.end()
    p.setOpacity(0.9)
    p.drawImage(0, 0, fade_right(blur(sil, 50), 600, 1200))
    p.setOpacity(1)
    # the sharp character, its right edge dissolving into the card
    p.drawImage(0, 0, fade_right(QImage(card_art), int(BANNER_W * 0.68), BANNER_W))
    # a darker foot for the name, a quiet area for the stats, a light vignette
    b = QLinearGradient(0, H * 0.6, 0, H)
    b.setColorAt(0.0, QColor(8, 11, 18, 0))
    b.setColorAt(1.0, QColor(8, 11, 18, 150))
    p.fillRect(0, 0, W, H, b)
    nm = QRadialGradient(QPointF(BANNER_W * 0.34, H * 1.04), 760)
    nm.setColorAt(0.0, QColor(6, 9, 15, 235))
    nm.setColorAt(1.0, QColor(6, 9, 15, 0))
    p.fillRect(0, 0, W, H, nm)
    d = QLinearGradient(0, 0, W, 0)
    d.setColorAt(0.30, QColor(8, 11, 18, 0))
    d.setColorAt(0.52, QColor(8, 11, 18, 110))
    d.setColorAt(1.0, QColor(8, 11, 18, 200))
    p.fillRect(0, 0, W, H, d)
    v = QRadialGradient(QPointF(W / 2, H / 2), W * 0.62)
    v.setColorAt(0.6, QColor(0, 0, 0, 0))
    v.setColorAt(1.0, QColor(0, 0, 0, 110))
    p.fillRect(0, 0, W, H, v)
    p.end()

    tmp = dst.with_suffix(".part")
    if not out.convertToFormat(QImage.Format_RGB32).save(str(tmp), "JPG", 88):
        return False
    tmp.replace(dst)
    return True
