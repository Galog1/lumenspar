"""Locate the artifact detail panel and its parts.

The panel is *not* a fixed layout. Two independent toggles move things:

* a "Sanctifying Elixir Definition" band appears for elixir-defined artifacts
  and pushes the level badge, substats and set name down by its own height;
* an "Equipped: <name>" bar is pinned to the panel bottom only when the piece
  is equipped, overlaying the flavour text.

So nothing below the star row sits at a constant offset. Instead we find three
colour-distinctive landmarks -- the purple elixir band, the green set-name
line, and the warm-cream equipped bar -- and cut the regions relative to them.
Landmarks are found by *counting* matching pixels per row rather than by
averaging a row: a short set name like "Celestial Gift:" covers too little of
the panel width to move a full-width mean.

All results are returned in absolute pixels for the frame handed in, so the
caller never has to care about the capture resolution.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BODY = np.array([236, 229, 215])   # panel background cream

# Header geometry, measured from 16:9 captures and expressed as a fraction of
# the panel's own width so it scales with resolution. The header is fixed:
# only the body below it moves, and only when the elixir band is present.
# (offset from the top of the orange header bar) / panel_width
# Measured against the panel's FULL width (x1 - x0), not the inset used for
# colour sampling -- mixing the two scales every offset ~5% short.
H_TITLE = (0.004, 0.128)
H_SLOT = (0.142, 0.192)
H_MAIN_LABEL = (0.308, 0.358)
H_MAIN_VALUE = (0.366, 0.464)   # generous below: clipped glyphs lose digits
H_STARS = (0.490, 0.546)
H_TEXT_W = 0.62          # right of this the artifact icon overlaps the header


@dataclass(slots=True)
class Region:
    x0: int
    y0: int
    x1: int
    y1: int

    def crop(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.y0 : self.y1, self.x0 : self.x1]

    @property
    def height(self) -> int:
        return self.y1 - self.y0


@dataclass(slots=True)
class PanelLayout:
    panel: Region
    title: Region
    slot: Region
    main_label: Region
    main_value: Region
    stars: Region
    level: Region
    substats: Region
    set_line: Region
    equipped: Region | None
    elixir: bool

    @property
    def has_equipped(self) -> bool:
        return self.equipped is not None


class LayoutError(RuntimeError):
    pass


def _longest_run(mask: np.ndarray) -> tuple[int, int]:
    best = (0, 0, 0)
    start = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start > best[0]:
                best = (i - start, start, i)
            start = None
    if start is not None and len(mask) - start > best[0]:
        best = (len(mask) - start, start, len(mask))
    return best[1], best[2]


# The detail panel occupies fixed UI geometry, identical at every resolution
# tested (4K and 2000px) and on every tab.
PANEL_X0, PANEL_X1 = 0.6815, 0.9370


def find_panel(frame: np.ndarray) -> Region:
    """Locate the detail panel on the right of the screen.

    Fixed fractions rather than detection. Detecting it from content was
    unreliable across tabs: the cream body is broken by long weapon and
    material descriptions (measured panel widths swung 753-1083px for the same
    UI), and the coloured header is muted to near-grey on 1-star items. Every
    header offset is a fraction of this width, so an unstable panel width threw
    off everything downstream.
    """
    h, w = frame.shape[:2]
    x0, x1 = int(w * PANEL_X0), int(w * PANEL_X1)

    rgb = frame[:, :, ::-1].astype(int)
    col = rgb[:, (x0 + x1) // 2]
    body_like = np.abs(col - BODY).sum(1) < 60
    ys = np.where(body_like)[0]
    if not len(ys):
        raise LayoutError("detail panel not found (is an item selected?)")
    return Region(x0, 0, x1, min(h, int(ys.max())))


def _frac_rows(rgb, x0: int, x1: int, pred, frac: float) -> np.ndarray:
    """Rows where at least `frac` of the panel width satisfies `pred`.

    Fractional width matters: the elixir band spans the panel, whereas the blue
    gems on an artifact icon do not. Testing "any purple pixel" would call
    every panel elixir-defined.
    """
    band = rgb[:, x0:x1]
    R, G, B = band[:, :, 0], band[:, :, 1], band[:, :, 2]
    return np.where(pred(R, G, B).mean(1) >= frac)[0]


def _group(rows, gap: int = 6) -> list[tuple[int, int]]:
    """Collapse row indices into contiguous spans."""
    rows = list(rows)
    if not rows:
        return []
    out, start, prev = [], rows[0], rows[0]
    for r in rows[1:]:
        if r - prev > gap:
            out.append((int(start), int(prev) + 1))
            start = r
        prev = r
    out.append((int(start), int(prev) + 1))
    return out


def analyse_panel(frame: np.ndarray) -> PanelLayout:
    """Segment the detail panel of a full-screen BGR frame."""
    panel = find_panel(frame)
    rgb = frame[:, :, ::-1].astype(int)
    px, qx = panel.x0 + 12, panel.x1 - 12
    W = qx - px

    # The header band is tinted by RARITY -- gold/orange at 5*, purple at 4*,
    # blue at 3* and so on -- so it must be found by "saturated and not the
    # cream body" rather than by any one hue.
    def _header(R, G, B):
        sat = np.maximum(np.maximum(R, G), B) - np.minimum(np.minimum(R, G), B)
        notbody = (np.abs(R - BODY[0]) + np.abs(G - BODY[1]) + np.abs(B - BODY[2])) > 60
        return (sat > 35) & notbody

    head = _frac_rows(rgb, px, qx, _header, 0.70)
    if not len(head):
        raise LayoutError("panel header bar not found")
    header_top = int(head.min())

    body = _frac_rows(rgb, px, qx,
                      lambda R, G, B: np.abs(
                          np.stack([R, G, B], -1) - BODY).sum(-1) < 40, 0.60)
    if not len(body):
        raise LayoutError("panel body not found")
    body_top = int(body.min())

    purple = _group(_frac_rows(
        rgb, px, qx,
        lambda R, G, B: (B > R + 25) & (B > G + 25) & (B > 190), 0.50))
    # The elixir band sits flush against the top of the body. Requiring that
    # adjacency stops a 4-star artifact's *purple title bar* -- rarity tints
    # the header, and 4-star is purple -- from being read as an elixir band.
    near_body = max(6, int(W * 0.02))
    purple = [p for p in purple if abs(p[1] - body_top) <= near_body]
    elixir = bool(purple)
    header_end = purple[0][0] if elixir else body_top

    gold = _group(_frac_rows(
        rgb, px, qx,
        lambda R, G, B: (R > 200) & (G > 140) & (G < 205) & (B < 130), 0.06))
    gold = [g for g in gold if g[1] <= header_end + 2]
    if not gold:
        raise LayoutError("rarity stars not found")
    star_y0, star_y1 = gold[-1]

    green = _group(_frac_rows(
        rgb, px, qx,
        lambda R, G, B: (G > R + 20) & (G > B + 20) & (G > 120), 0.02))
    green = [g for g in green if g[0] > body_top]
    if not green:
        raise LayoutError("set-name line not found in panel")
    set_y0, set_y1 = green[0]

    # Detect the bar loosely (0.35): a stricter threshold splits it into two
    # runs at lower resolutions, and taking the lower run clips the text.
    footer = _group(_frac_rows(
        rgb, px, qx,
        lambda R, G, B: (R - B > 45) & (R > 235), 0.35))
    footer = [f for f in footer if f[0] > set_y1]
    equipped = None
    if footer:
        fy0, fy1 = footer[-1]
        fy1 = min(frame.shape[0], fy1)
        # Narrow to the rows that actually carry dark glyphs. Doing this by
        # content rather than by a fixed inset keeps it resolution-independent.
        inner = rgb[fy0:fy1, px:qx]
        rows = np.where((inner.max(2) < 150).mean(1) > 0.012)[0]
        if len(rows):
            ty0 = fy0 + int(rows.min()) - 5
            ty1 = fy0 + int(rows.max()) + 6
        else:
            ty0, ty1 = fy0, fy1
        equipped = Region(panel.x0, max(0, ty0), panel.x1, min(frame.shape[0], ty1))

    # Level badge: a dark pill just under the header, whose position follows
    # the elixir band. Measured at body_top + 0.045..0.098 of panel width.
    Wp0 = panel.x1 - panel.x0
    lvl_top = body_top + int(Wp0 * 0.036)
    level = Region(panel.x0 + 8, lvl_top, panel.x0 + int(Wp0 * 0.29),
                   body_top + int(Wp0 * 0.104))
    substats = Region(panel.x0 + 6, level.y1 + 6, panel.x1 - 6, set_y0 - 4)

    Wp = panel.x1 - panel.x0          # full panel width: the header scale

    def hband(spec):
        a, b = spec
        return Region(panel.x0 + int(Wp * 0.012), header_top + int(Wp * a),
                      panel.x0 + int(Wp * H_TEXT_W), header_top + int(Wp * b))

    title = hband(H_TITLE)
    slot = hband(H_SLOT)
    main_label = hband(H_MAIN_LABEL)
    main_value = hband(H_MAIN_VALUE)
    stars = hband(H_STARS)

    if equipped is not None:
        # Skip the round character portrait on the left.
        equipped = Region(equipped.x0 + int(Wp0 * 0.155), equipped.y0,
                          equipped.x1 - int(Wp0 * 0.02), equipped.y1)

    return PanelLayout(
        panel=panel, title=title, slot=slot,
        main_label=main_label, main_value=main_value,
        stars=stars,
        level=level, substats=substats,
        set_line=Region(panel.x0, set_y0 - 6, panel.x1, set_y1 + 6),
        equipped=equipped, elixir=elixir,
    )


# -- weapons ----------------------------------------------------------------

# Weapon header/body offsets, measured from 16:9 captures as a fraction of the
# panel width. The header offsets are relative to the top of the coloured bar,
# the body ones to the top of the cream body.
W_TITLE = (0.018, 0.110)
W_STARS = (0.455, 0.585)
W_LEVEL = (0.042, 0.118)
W_REFINE = (0.125, 0.215)


@dataclass(slots=True)
class WeaponLayout:
    panel: Region
    title: Region
    stars: Region
    level: Region
    refinement: Region
    equipped: Region | None


def analyse_weapon_panel(frame: np.ndarray) -> WeaponLayout:
    """Segment a weapon detail panel.

    Weapons reuse the artifact panel's chrome -- rarity-tinted header, cream
    body, bottom "Equipped:" bar -- but carry no green set line, so they need
    their own segmentation rather than `analyse_panel`.
    """
    panel = find_panel(frame)
    rgb = frame[:, :, ::-1].astype(int)
    px, qx = panel.x0 + 12, panel.x1 - 12
    Wp = panel.x1 - panel.x0

    def _header(R, G, B):
        sat = np.maximum(np.maximum(R, G), B) - np.minimum(np.minimum(R, G), B)
        notbody = (np.abs(R - BODY[0]) + np.abs(G - BODY[1]) + np.abs(B - BODY[2])) > 60
        return (sat > 35) & notbody

    head = _frac_rows(rgb, px, qx, _header, 0.70)
    if not len(head):
        raise LayoutError("weapon panel header not found")
    header_top = int(head.min())

    body = _frac_rows(rgb, px, qx,
                      lambda R, G, B: np.abs(
                          np.stack([R, G, B], -1) - BODY).sum(-1) < 40, 0.60)
    if not len(body):
        raise LayoutError("weapon panel body not found")
    body_top = int(body.min())

    footer = _group(_frac_rows(
        rgb, px, qx, lambda R, G, B: (R - B > 45) & (R > 235), 0.35))
    footer = [f for f in footer if f[0] > body_top]
    equipped = None
    if footer:
        fy0, fy1 = footer[-1]
        fy1 = min(frame.shape[0], fy1)
        inner = rgb[fy0:fy1, px:qx]
        rows = np.where((inner.max(2) < 150).mean(1) > 0.012)[0]
        if len(rows):
            ty0, ty1 = fy0 + int(rows.min()) - 5, fy0 + int(rows.max()) + 6
        else:
            ty0, ty1 = fy0, fy1
        equipped = Region(panel.x0 + int(Wp * 0.155), max(0, ty0),
                          panel.x1 - int(Wp * 0.02), min(frame.shape[0], ty1))

    def band(anchor: int, spec, x_frac: float) -> Region:
        a, b = spec
        return Region(panel.x0 + int(Wp * 0.012), anchor + int(Wp * a),
                      panel.x0 + int(Wp * x_frac), anchor + int(Wp * b))

    return WeaponLayout(
        panel=panel,
        # The title has its own full-width bar; the icon sits below it, not
        # beside it, so the name may run the whole width of the panel.
        title=band(header_top, W_TITLE, 0.97),
        stars=band(header_top, W_STARS, 0.62),
        level=band(body_top, W_LEVEL, 0.32),
        refinement=band(body_top, W_REFINE, 0.62),
        equipped=equipped,
    )
