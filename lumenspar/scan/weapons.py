"""Read one weapon detail panel."""

from __future__ import annotations

import numpy as np

from ..ocr import engine as ocr
from ..ocr import preprocess as pp
from .artifacts import count_stars
from .characters import DIGIT_HEIGHTS, _render
from .layout import BODY, WeaponLayout, analyse_weapon_panel
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


# The refinement rank is drawn twice: as a digit in a small square badge, and
# as "Refinement Rank N" in gold text. The badge is the dependable one. The
# text is pale gold on cream, which a dark-text threshold barely sees, and its
# last character -- the digit -- sits right at the edge of the line's region.
# The badge is dark grey with a white digit for R1-R4 and orange with a pale
# yellow digit at R5, so it is found by being a solid block of colour that is
# not the cream body, and the digit by being the brightest thing inside it.
REFINE_DIGITS = "12345"
_BADGE_MIN_DIST = 120     # summed |RGB - body| that counts as "badge colour"


def _refinement_badge(frame: np.ndarray, L: WeaponLayout) -> np.ndarray | None:
    """RGB crop of the rank badge: the first solid block of colour in the line."""
    rgb = L.refinement.crop(frame)[:, :, ::-1].astype(int)
    if rgb.size == 0:
        return None
    coloured = np.abs(rgb - BODY[None, None, :]).sum(2) > _BADGE_MIN_DIST
    cols = np.where(coloured.mean(0) > 0.25)[0]
    if not len(cols):
        return None
    # A "4" has a near-white vertical stem running the badge's full height,
    # which reads as a background column and would split the badge in two.
    # The gap before the text is ~0.26 of the line height, the stem ~0.03.
    breaks = np.where(np.diff(cols) > max(2, int(rgb.shape[0] * 0.10)))[0]
    x0, x1 = int(cols[0]), int(cols[breaks[0]] if len(breaks) else cols[-1]) + 1
    rows = np.where(coloured[:, x0:x1].mean(1) > 0.5)[0]
    if not len(rows):
        return None
    badge = rgb[int(rows[0]):int(rows[-1]) + 1, x0:x1]
    h, w = badge.shape[:2]
    # The badge is square; anything else means the line was not found where
    # the layout put it, and reading it would only produce a guess.
    return badge if h >= 8 and 0.6 < w / h < 1.6 else None


def read_refinement_badge(frame: np.ndarray, L: WeaponLayout) -> int | None:
    """The rank digit in the badge, or None when it cannot be read with confidence."""
    badge = _refinement_badge(frame, L)
    if badge is None or not ocr.available():
        return None
    h, w = badge.shape[:2]
    m = max(2, int(min(h, w) * 0.12))          # step inside the rounded border
    green = badge[m:h - m, m:w - m, 1]
    # Grey badge: digit ~204 on ~91. Orange badge: ~225 on ~164. Splitting
    # each badge halfway between its own body and its brightest pixels
    # handles both without a per-colour constant.
    body, bright = float(np.median(green)), float(np.percentile(green, 97))
    if bright - body < 40:
        return None
    ink = green > (body + bright) / 2
    runs, labels, stats = pp.components(ink)
    if not len(stats):
        return None
    keep = np.zeros(len(stats), dtype=bool)
    keep[int(np.argmax(stats[:, 4]))] = True     # the digit; drops corner glints
    ink = pp.keep_components(ink.shape, runs, labels, keep)
    ys, xs = np.nonzero(ink)
    glyph = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    votes: list[str] = []
    for height in DIGIT_HEIGHTS:
        img = _render(glyph, height)
        for psm in (ocr.PSM_CHAR, ocr.PSM_WORD):
            got = ocr.read(img, psm=psm, whitelist=REFINE_DIGITS).strip()
            if len(got) == 1:
                votes.append(got)
                break
    if not votes:
        return None
    best = max(set(votes), key=votes.count)
    # A split vote means the glyph is ambiguous: refuse rather than pick one.
    return int(best) if votes.count(best) * 2 > len(votes) else None


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
    badge = read_refinement_badge(frame, L)
    if badge is not None:
        refine = f"Refinement Rank {badge}"
    else:
        # Fallback: the gold text, which reads only now and then.
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
