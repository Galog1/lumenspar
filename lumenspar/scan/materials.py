"""Read the materials tabs.

Materials are cheaper to scan than artifacts or weapons: GOOD stores only
`{"MaterialKey": count}`, and the count is printed on the tile itself, so the
detail panel is opened purely to learn the item's name.
"""

from __future__ import annotations

import re

import numpy as np

from ..ocr import engine as ocr
from ..ocr import preprocess as pp
from .grid import Tile
from .layout import BODY, LayoutError, Region, _frac_rows, find_panel

# Title band, measured upward from the top of the cream body as a fraction of
# the panel width.
TITLE_ABOVE_BODY = (0.552, 0.492)


def material_title_region(frame: np.ndarray) -> Region:
    panel = find_panel(frame)
    rgb = frame[:, :, ::-1].astype(int)
    px, qx = panel.x0 + 12, panel.x1 - 12
    Wp = panel.x1 - panel.x0
    body = _frac_rows(
        rgb, px, qx,
        lambda R, G, B: np.abs(np.stack([R, G, B], -1) - BODY).sum(-1) < 40, 0.60)
    if not len(body):
        raise LayoutError("material panel body not found")
    body_top = int(body.min())
    a, b = TITLE_ABOVE_BODY
    return Region(panel.x0 + int(Wp * 0.02), body_top - int(Wp * a),
                  panel.x0 + int(Wp * 0.95), body_top - int(Wp * b))


def read_material_name(frame: np.ndarray) -> str:
    """Material name from the detail panel title."""
    box = material_title_region(frame)
    return ocr.read(
        pp.prep_neutral(box.crop(frame), max_sat=70, min_val=170, cut_after_gap=1.8),
        psm=ocr.PSM_LINE,
    ).strip()


def read_quantity(frame: np.ndarray, tile: Tile, pitch_y: int) -> int | None:
    """Stack size from the tile's caption strip.

    The strip is cropped to its own bright rows first: the band below a tile
    also catches the star tips above and the dark page background below, and
    that background reads as a stray dash.
    """
    x0, x1 = tile.rect.x0 + 6, tile.rect.x1 - 6
    y0 = tile.rect.y1
    y1 = min(frame.shape[0], y0 + int(pitch_y * 0.30))
    band = frame[y0:y1, x0:x1][:, :, ::-1].astype(int)
    if band.size == 0:
        return None
    rows = np.where((band.min(2) > 185).mean(1) > 0.6)[0]
    if len(rows) < 4:
        return None
    crop = frame[y0 + int(rows.min()) + 2 : y0 + int(rows.max()) - 1, x0:x1]
    if crop.size == 0:
        return None
    txt = ocr.read(
        pp.prep_text(pp.crop_to_ink(crop, dark=True, pad=8),
                     dark_text=True, target_height=80),
        psm=ocr.PSM_LINE,
    )
    digits = re.sub(r"[^0-9]", "", txt.replace("O", "0").replace("o", "0"))
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return None
    return n if 0 < n <= 99999 else None
