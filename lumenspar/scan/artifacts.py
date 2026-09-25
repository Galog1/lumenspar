"""Read one artifact detail panel into GOOD fields.

OCR parameters here are tuned against real 16:9 captures; see `layout` for how
the regions themselves are found.
"""

from __future__ import annotations

import numpy as np

from ..ocr import engine as ocr
from ..ocr import preprocess as pp
from .artifact_parse import PanelText
from .layout import PanelLayout, Region, analyse_panel

# Flower and Plume main stats are fixed by the game, so the slot alone decides
# them. GOOD stores only `mainStatKey`, never the value, so the value is read
# for exactly one purpose: to see whether a '%' is present.
FIXED_MAIN = {"flower": "hp", "plume": "atk"}


def _light(frame: np.ndarray, r: Region, **kw) -> np.ndarray:
    """Prepare white-on-orange header text."""
    return pp.prep_neutral(r.crop(frame), **kw)


def _dark(frame: np.ndarray, r: Region) -> np.ndarray:
    """Prepare dark text on the cream panel body."""
    return pp.prep_text(r.crop(frame), dark_text=True)


def count_stars(frame: np.ndarray, r: Region) -> int:
    """Count gold star glyphs to get rarity."""
    rgb = r.crop(frame)[:, :, ::-1].astype(int)
    if rgb.size == 0:
        return 0
    R, G, B = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    gold = (R > 200) & (G > 140) & (G < 215) & (B < 130)
    cols = gold.sum(0) > max(1, gold.shape[0] // 8)
    groups, run = 0, False
    for c in cols:
        if c and not run:
            groups += 1
        run = bool(c)
    return min(5, groups)


def is_locked(frame: np.ndarray, layout: PanelLayout) -> bool:
    """Detect the padlock badge, which is red/orange when the piece is locked."""
    Wp = layout.panel.x1 - layout.panel.x0
    box = Region(
        layout.panel.x0 + int(Wp * 0.68), layout.level.y0 - int(Wp * 0.012),
        layout.panel.x0 + int(Wp * 0.84), layout.level.y1 + int(Wp * 0.012),
    )
    rgb = box.crop(frame)[:, :, ::-1].astype(int)
    if rgb.size == 0:
        return False
    R, G, B = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    red = (R > 140) & (R - G > 55) & (R - B > 55)
    return bool(red.mean() > 0.06)


def read_panel(frame: np.ndarray, layout: PanelLayout | None = None) -> PanelText:
    """OCR every field of the currently selected artifact."""
    L = layout or analyse_panel(frame)

    slot = ocr.read(_light(frame, L.slot, max_sat=52, min_val=150),
                    psm=ocr.PSM_LINE)
    # cut_after_gap isolates the caption from the artifact icon drawn to its
    # right, whose bright edges otherwise arrive as trailing junk.
    label = ocr.read(_light(frame, L.main_label, max_sat=52, min_val=125,
                            cut_after_gap=1.5),
                     psm=ocr.PSM_LINE)
    value = ocr.read(_light(frame, L.main_value, max_sat=30, min_val=185,
                            target_height=90, cut_after_gap=1.5),
                     psm=ocr.PSM_LINE)

    # Step inside the pill: its border would otherwise become ink and read as
    # stray characters.
    lvl_crop = pp.crop_to_ink(L.level.crop(frame), dark=True, pad=0, inset=3)
    level = ocr.read(pp.prep_neutral(lvl_crop, max_sat=70, min_val=150,
                                     target_height=90, pad=24),
                     psm=ocr.PSM_WORD)

    subs = [ln for ln in ocr.read(_dark(frame, L.substats),
                                  psm=ocr.PSM_BLOCK).splitlines() if ln.strip()]
    set_line = ocr.read(_dark(frame, L.set_line), psm=ocr.PSM_LINE)
    equipped = (ocr.read(_dark(frame, L.equipped), psm=ocr.PSM_LINE)
                if L.equipped else None)

    return PanelText(
        slot=slot, main_label=label, main_value=value,
        rarity=count_stars(frame, L.stars) or 5,
        level=level, substats=subs, set_line=set_line,
        equipped=equipped, elixir=L.elixir, locked=is_locked(frame, L),
    )
