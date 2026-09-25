"""Locate the inventory tile grid and classify tiles cheaply.

Reading a tile's rarity straight from the grid matters for speed: it lets the
scanner skip everything below the user's rarity floor without opening each
artifact, which is by far the most expensive step of a scan.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .layout import Region, find_panel

# Tile background tint by rarity, sampled above the caption strip.
# The tile lattice is fixed UI geometry, identical on every tab and at every
# resolution tested (4K and 2000px): 8 columns, measured as fractions of the
# frame width.
COL_FIRST, COL_PITCH, COL_WIDTH, N_COLS = 0.06095, 0.07625, 0.0643, 8
BODY_OF_PITCH = 0.723   # tile body height as a fraction of the row pitch

RARITY_TINT: dict[int, tuple[int, int, int]] = {
    5: (158, 116, 68),
    4: (120, 95, 150),
    3: (80, 110, 150),
    2: (75, 130, 115),
    1: (110, 110, 118),
}


@dataclass(slots=True)
class Tile:
    row: int
    col: int
    rect: Region
    rarity: int

    @property
    def center(self) -> tuple[int, int]:
        return ((self.rect.x0 + self.rect.x1) // 2,
                (self.rect.y0 + self.rect.y1) // 2)


@dataclass(slots=True)
class Grid:
    tiles: list[Tile]
    cols: int
    rows: int
    pitch_x: int
    pitch_y: int
    region: Region

    def __len__(self) -> int:
        return len(self.tiles)


class GridError(RuntimeError):
    pass


def _dominant_pitch(proj: np.ndarray, lo: int, hi: int) -> int:
    """Strongest repeating period in a projection, by autocorrelation.

    Thresholding the gaps between tiles does not generalise: artifact and
    weapon tiles are separated by wide gaps, material tiles by thin ones, and
    no single threshold splits both correctly. The repeat period is the same
    signal in both cases.
    """
    p = proj.astype(np.float64)
    p = p - p.mean()
    best, best_score = lo, -1e18
    for lag in range(lo, hi):
        if lag >= len(p):
            break
        score = float(np.dot(p[:-lag], p[lag:]) / (len(p) - lag))
        if score > best_score:
            best_score, best = score, lag
    return best


def _lattice_phase(proj: np.ndarray, pitch: int) -> int:
    """Offset of the *gaps* between tiles.

    Anchoring on gaps rather than tile centres: what a tile's projection peaks
    at varies with its contents (icon, caption strip, star row), but the gutter
    between tiles is reliably the low point.
    """
    best, best_val = 0, 1e18
    for phi in range(pitch):
        idx = np.arange(phi, len(proj), pitch)
        val = float(proj[idx].mean()) if len(idx) else 1e18
        if val < best_val:
            best_val, best = val, phi
    return best


def _group_rows(idx, gap: int = 4) -> list[tuple[int, int]]:
    """Collapse row indices into contiguous spans."""
    idx = list(idx)
    if not idx:
        return []
    out, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - prev > gap:
            out.append((int(start), int(prev) + 1))
            start = i
        prev = i
    out.append((int(start), int(prev) + 1))
    return out


def _spans(v: np.ndarray, frac: float, min_len: int) -> list[tuple[int, int]]:
    on = v > v.max() * frac
    out, start = [], None
    for i, k in enumerate(on):
        if k and start is None:
            start = i
        elif not k and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    if start is not None and len(on) - start >= min_len:
        out.append((start, len(on)))
    return out


def classify_rarity(frame: np.ndarray, rect: Region) -> int:
    """Rarity from the tile's background tint."""
    rgb = frame[:, :, ::-1].astype(int)
    h, w = rect.y1 - rect.y0, rect.x1 - rect.x0
    # Sample two thin strips down the tile's left and right margins. The centre
    # is covered by the artifact icon, the corners carry badges (padlock,
    # equipped portrait, "New"), and the outermost pixels catch the white glow
    # on the selected tile -- the margins are the only clean background.
    ys = slice(rect.y0 + int(h * 0.25), rect.y0 + int(h * 0.55))
    left = rgb[ys, rect.x0 + int(w * 0.05): rect.x0 + int(w * 0.16)]
    right = rgb[ys, rect.x1 - int(w * 0.16): rect.x1 - int(w * 0.05)]
    px = np.concatenate([left.reshape(-1, 3), right.reshape(-1, 3)])
    if len(px) < 20:
        return 0
    # Median, not mean: robust to a stray badge or glow bleeding into the strip.
    med = np.median(px, 0)
    best, dist = 0, 1e9
    for r, tint in RARITY_TINT.items():
        d = float(np.abs(med - np.array(tint)).sum())
        if d < dist:
            best, dist = r, d
    return best if dist < 190 else 0


def find_grid(frame: np.ndarray, *, min_visible: float = 0.85) -> Grid:
    """Detect the tile lattice left of the detail panel.

    Rows that are only partly on screen are dropped: their caption strip may be
    clipped, and clicking one can scroll the view underneath us.
    """
    panel = find_panel(frame)
    rgb = frame[:, :, ::-1].astype(int)
    H, W_frame = rgb.shape[:2]
    right = max(10, panel.x0 - 30)

    # Rows come from the bright caption strip under every tile ("+20", "Lv. 1",
    # or a quantity). That strip is the one feature every tab shares, and the
    # gutters above/below it are unambiguous -- unlike the gaps between tile
    # bodies, which are wide on artifacts and thin on materials, so no single
    # gap threshold splits both.
    x0 = int(W_frame * 0.03)
    strip_mask = (rgb[:, x0:right].min(2) > 185)
    strip_rows = [g for g in _group_rows(np.where(strip_mask.mean(1) > 0.45)[0])
                  if g[1] - g[0] >= max(4, H // 300)]
    if len(strip_rows) < 2:
        raise GridError("inventory grid not found (no item rows visible)")

    tile_w0 = int(W_frame * COL_WIDTH)
    pitch_x0 = int(W_frame * COL_PITCH)
    col_x0 = [int(W_frame * COL_FIRST + i * pitch_x0) for i in range(N_COLS)]

    # Keep only bands that belong to an evenly spaced series. Tile rows repeat
    # at a fixed pitch; the "Show 5-star Artifacts..." toggle above the grid is
    # also a bright full-width band but is a lone outlier. Selecting the
    # largest consistent progression removes it without any appearance
    # threshold -- gutter darkness and body saturation both vary too much
    # between tabs to be relied on.
    cand = [a for a, _ in strip_rows]
    if len(cand) >= 3:
        best_inliers: list[int] = []
        for i in range(len(cand)):
            for j in range(i + 1, len(cand)):
                step = cand[j] - cand[i]
                if step < 40:
                    continue
                inliers = [y for y in cand
                           if abs((y - cand[i]) % step) <= 6
                           or abs((y - cand[i]) % step - step) <= 6]
                if len(inliers) > len(best_inliers):
                    best_inliers = inliers
        if len(best_inliers) >= 2:
            keep = set(best_inliers)
            strip_rows = [g for g in strip_rows if g[0] in keep]

    if len(strip_rows) < 1:
        raise GridError("inventory grid not found (no item rows visible)")

    tops = [a for a, _ in strip_rows]
    strip_h = int(np.median([b - a for a, b in strip_rows]))
    diffs = np.diff(tops)
    if len(diffs) == 0:
        raise GridError("only one item row visible; cannot establish the grid")
    pitch_y = int(np.median(diffs))
    body_h = int(pitch_y * BODY_OF_PITCH)
    tile_w = int(W_frame * COL_WIDTH)
    pitch_x = int(W_frame * COL_PITCH)
    col_x = [int(W_frame * COL_FIRST + i * pitch_x) for i in range(N_COLS)]

    tiles: list[Tile] = []
    kept_rows: list[int] = []
    for ri, top in enumerate(tops):
        ry0 = top - body_h
        if ry0 < 0 or top > H:
            continue                      # row clipped by the viewport edge
        kept_rows.append(ry0)
        for ci, cx in enumerate(col_x):
            # A cell is occupied only if it has its own caption strip; a short
            # final row would otherwise produce clicks on empty background.
            cap = strip_mask[top:top + strip_h, max(0, cx - x0):max(0, cx - x0) + tile_w]
            # A modest threshold: the caption's own dark digits eat into the
            # bright area, so demanding most of it be bright drops real tiles.
            if cap.size == 0 or cap.mean() < 0.30:
                continue
            rect = Region(cx, ry0, cx + tile_w, top)
            tiles.append(Tile(ri, ci, rect, classify_rarity(frame, rect)))

    if not tiles:
        raise GridError("inventory grid is empty")

    return Grid(tiles=tiles, cols=N_COLS, rows=len(kept_rows),
                pitch_x=pitch_x, pitch_y=pitch_y,
                region=Region(col_x[0], kept_rows[0],
                              col_x[-1] + tile_w, kept_rows[-1] + body_h))
