"""Read one weapon detail panel."""

from __future__ import annotations

import numpy as np

from ..ocr import engine as ocr
from ..ocr import preprocess as pp
from .artifacts import count_stars
from .layout import WeaponLayout, analyse_weapon_panel
from .weapon_parse import WeaponPanelText


def is_locked(frame: np.ndarray, L: WeaponLayout) -> bool:
    Wp = L.panel.x1 - L.panel.x0
    from .layout import Region

    box = Region(L.panel.x0 + int(Wp * 0.78), L.level.y0 - int(Wp * 0.015),
                 L.panel.x1 - int(Wp * 0.02), L.level.y1 + int(Wp * 0.015))
    rgb = box.crop(frame)[:, :, ::-1].astype(int)
    if rgb.size == 0:
        return False
    R, G, B = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    return bool(((R > 140) & (R - G > 55) & (R - B > 55)).mean() > 0.06)


def read_weapon_panel(frame: np.ndarray, layout: WeaponLayout | None = None) -> WeaponPanelText:
    L = layout or analyse_weapon_panel(frame)

    name = ocr.read(
        pp.prep_neutral(L.title.crop(frame), max_sat=60, min_val=150,
                        cut_after_gap=1.6),
        psm=ocr.PSM_LINE,
    )
    # The level pill is dark on a bright panel: step inside its border first.
    lvl_crop = pp.crop_to_ink(L.level.crop(frame), dark=True, pad=0, inset=3)
    level = ocr.read(
        pp.prep_neutral(lvl_crop, max_sat=90, min_val=140, target_height=90, pad=24),
        psm=ocr.PSM_LINE,
    )
    # "Refinement Rank N" is gold-on-cream: darker than the background.
    refine = ocr.read(pp.prep_text(L.refinement.crop(frame), dark_text=True),
                      psm=ocr.PSM_LINE)
    equipped = (ocr.read(pp.prep_text(L.equipped.crop(frame), dark_text=True),
                         psm=ocr.PSM_LINE) if L.equipped else None)

    return WeaponPanelText(
        name=name,
        level=level,
        refinement=refine,
        rarity=count_stars(frame, L.stars) or 0,
        equipped=equipped,
        locked=is_locked(frame, L),
    )
