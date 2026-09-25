"""Image preparation for Genshin's UI text.

Game UI text is clean, anti-aliased and high-contrast, so it does not need the
heavy denoising a photo would. What it *does* need is scale: Tesseract's LSTM
engine wants roughly 30px of cap height, and inventory tile captions are far
smaller than that even at 4K. Upscale first, binarise second.

Deliberately numpy-only -- OpenCV is reserved for colour/template work, which
keeps the text path importable on a machine that has not installed it yet.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

TARGET_TEXT_HEIGHT = 40


def to_gray(bgr: np.ndarray) -> np.ndarray:
    """BGR (or BGRA) uint8 -> float32 luma."""
    b, g, r = bgr[..., 0], bgr[..., 1], bgr[..., 2]
    return (0.114 * b + 0.587 * g + 0.299 * r).astype(np.float32)


def otsu(gray: np.ndarray) -> float:
    """Otsu's threshold over a 0..255 float image."""
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 128.0
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    denom[denom == 0] = np.nan
    with np.errstate(invalid="ignore"):
        sigma_b = (mu_t * omega - mu) ** 2 / denom
    if not np.any(np.isfinite(sigma_b)):
        # A flat region (one intensity) has no between-class variance to
        # maximise. Genshin panels are often solid colour, so this is a normal
        # input, not an error -- fall back to the mean.
        return float(gray.mean())
    return float(np.nanargmax(sigma_b))


def upscale(img: np.ndarray, factor: float) -> np.ndarray:
    if factor <= 1.0:
        return img
    h, w = img.shape[:2]
    pil = Image.fromarray(img.astype(np.uint8))
    return np.asarray(
        pil.resize((max(1, int(w * factor)), max(1, int(h * factor))), Image.LANCZOS)
    )


def local_threshold(
    gray: np.ndarray, radius: int, offset: float, dark_text: bool
) -> np.ndarray:
    """Threshold each pixel against a blurred local background.

    Genshin's detail header is a strong left-to-right gradient, so a single
    global cut (Otsu) either loses the dark end or floods the light end. A
    local comparison tracks the gradient instead.
    """
    blur = np.asarray(
        Image.fromarray(gray.astype(np.uint8)).filter(ImageFilter.BoxBlur(radius))
    ).astype(np.float32)
    if dark_text:
        # The absolute floor suppresses speckle: in a flat region the local
        # comparison amplifies sensor/compression noise into fake glyphs.
        ink = (gray < blur - offset) & (gray < np.percentile(gray, 45))
    else:
        ink = (gray > blur + offset) & (gray > np.percentile(gray, 55))
    return np.where(ink, 0, 255).astype(np.uint8)


def crop_to_ink(bgr: np.ndarray, dark: bool = True, pad: int = 4,
                inset: int = 0) -> np.ndarray:
    """Trim a crop to the bounding box of its dark (or light) pixels.

    Used for the level pill, whose region also contains bright panel
    background; without trimming, the threshold separates pill from panel
    rather than glyphs from pill.
    """
    gray = to_gray(bgr)
    mask = gray < 110 if dark else gray > 170
    if not mask.any():
        return bgr
    ys, xs = np.where(mask)
    y0, y1 = max(0, ys.min() - pad), min(bgr.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(bgr.shape[1], xs.max() + pad + 1)
    if inset:
        # Step inside the shape's own border. The level badge is a dark pill on
        # a bright panel: keeping its edge means the surrounding panel becomes
        # "ink" and Tesseract reads the resulting frame as extra characters.
        y0, y1 = y0 + inset, max(y0 + inset + 1, y1 - inset)
        x0, x1 = x0 + inset, max(x0 + inset + 1, x1 - inset)
    return bgr[y0:y1, x0:x1]


def prep_text(
    bgr: np.ndarray,
    *,
    dark_text: bool | None = None,
    target_height: int = TARGET_TEXT_HEIGHT,
    pad: int = 12,
    adaptive: bool = False,
    offset: float = 10.0,
) -> np.ndarray:
    """Return a padded, upscaled, binarised (black-on-white) crop for OCR.

    `dark_text` is auto-detected from the border pixels when not given: Genshin
    uses both light-on-dark (inventory tiles) and dark-on-light (detail panels),
    and feeding Tesseract an inverted image costs a lot of accuracy.
    """
    gray = to_gray(bgr)
    h = gray.shape[0]
    if h < target_height:
        gray = upscale(gray, target_height / max(1, h)).astype(np.float32)

    if dark_text is None:
        border = np.concatenate([
            gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1],
        ])
        # A bright surround implies dark glyphs on a light panel.
        dark_text = float(np.median(border)) > 127.0

    if adaptive:
        radius = max(5, int(gray.shape[0] / 2.5))
        out = local_threshold(gray, radius, offset, dark_text)
    else:
        t = otsu(gray)
        binary = gray > t                      # True = brighter than threshold
        ink = binary if not dark_text else ~binary   # True = glyph
        out = np.where(ink, 0, 255).astype(np.uint8)  # black glyphs on white

    if pad:
        out = np.pad(out, pad, mode="constant", constant_values=255)
    return out


def components(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """8-connected components of a boolean mask.

    Returns `(runs, labels, stats)`:
      * `runs`   -- (m, 3) of `(y, x0, x1)`, one row per horizontal ink run,
                    `x1` exclusive, ordered top-to-bottom then left-to-right;
      * `labels` -- (m,) component index for each run;
      * `stats`  -- (k, 5) of `(y0, y1, x0, x1, area)` per component, the two
                    ends exclusive.

    Works on runs rather than pixels because that is what makes a pure-numpy
    implementation fast enough to sit in the scan loop: a talent panel has tens
    of thousands of ink pixels but only a few hundred runs, so the union-find
    is over the runs and the per-pixel work stays vectorised. Measured at 4K:
    ~10ms, against ~2s for the per-pixel flood fill this replaced.
    """
    h, w = mask.shape
    # A blank column on the right keeps a run that ends at the frame edge from
    # joining the next row's leading run once the mask is flattened.
    padded = np.zeros((h, w + 1), np.int8)
    padded[:, :w] = mask
    edges = np.diff(np.concatenate(([0], padded.reshape(-1), [0])))
    starts = np.where(edges == 1)[0]
    ends = np.where(edges == -1)[0]
    if not len(starts):
        return (np.zeros((0, 3), int), np.zeros(0, int), np.zeros((0, 5), int))
    ry = starts // (w + 1)
    x0 = starts - ry * (w + 1)
    x1 = ends - ry * (w + 1)
    runs = np.stack([ry, x0, x1], 1)

    n = len(runs)
    parent = np.arange(n)

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    # Runs are row-ordered, so the first run of each row can be found by
    # searching the row index; adjacent rows are then merged with two pointers.
    row_of = np.searchsorted(ry, np.arange(h + 1))
    for y in range(1, h):
        i, j = row_of[y - 1], row_of[y]
        end_i, end_j = row_of[y], row_of[y + 1]
        while i < end_i and j < end_j:
            # 8-connectivity: runs touch if their spans overlap or meet
            # diagonally, i.e. once each is widened by one column.
            if x1[i] >= x0[j] and x1[j] >= x0[i]:
                a, b = find(i), find(j)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            if x1[i] < x1[j]:
                i += 1
            else:
                j += 1

    roots = np.array([find(i) for i in range(n)])
    _, labels = np.unique(roots, return_inverse=True)
    k = int(labels.max()) + 1
    stats = np.empty((k, 5), int)
    stats[:, 0] = h
    stats[:, 1] = 0
    stats[:, 2] = w
    stats[:, 3] = 0
    stats[:, 4] = 0
    np.minimum.at(stats[:, 0], labels, ry)
    np.maximum.at(stats[:, 1], labels, ry + 1)
    np.minimum.at(stats[:, 2], labels, x0)
    np.maximum.at(stats[:, 3], labels, x1)
    np.add.at(stats[:, 4], labels, x1 - x0)
    return runs, labels, stats


def keep_components(shape, runs: np.ndarray, labels: np.ndarray,
                    keep: np.ndarray) -> np.ndarray:
    """Rebuild a mask from the components `keep` selects."""
    out = np.zeros(shape, dtype=bool)
    for y, a, b in runs[keep[labels]]:
        out[y, a:b] = True
    return out


def _drop_speckles(mask: np.ndarray, min_pixels: int) -> np.ndarray:
    """Erase connected components smaller than `min_pixels`.

    The starry Attributes-screen backgrounds carry bright sparkle/dust flecks
    that pass the same neutral-colour test as glyph ink -- each fleck only a
    handful of pixels, scattered too close together to be caught by the
    column-gap cut below. A real glyph stroke, even a "/" or "1", is dozens to
    hundreds of pixels. Falls back to the unfiltered mask if every component
    is small, so a crop that is genuinely all fine marks is not blanked.
    """
    if not mask.any():
        return mask
    runs, labels, stats = components(mask)
    keep = stats[:, 4] >= min_pixels
    if not keep.any():
        return mask
    return keep_components(mask.shape, runs, labels, keep)


def drop_short_components(mask: np.ndarray, frac: float = 0.45,
                          quantile: int = 4) -> np.ndarray:
    """Erase ink components shorter than `frac` of the region's own glyphs.

    A companion to `_drop_speckles`, which measures a component's *area*
    against a fixed floor. Area alone cannot separate the brighter sparkle
    flecks on the character screens: measured on a real Odette capture, flecks
    reached 188 pixels against that filter's 76-pixel floor and sailed
    through, and one sitting on top of the "/" turned "100 / 100" into
    "1007100". Raising the floor is the trap this project already fell into
    once -- it eats the at-cap salmon "95"/"100", whose glyphs arrive
    fragmented.

    Height separates them with room to spare, because a fleck is small in both
    directions while a glyph is not: on that same capture the real glyphs run
    20-60px and every fleck is under 15. The reference is the median height of
    the largest `1/quantile` of components by area, so the threshold scales
    with the capture resolution instead of being pinned to 4K.
    """
    if not mask.any():
        return mask
    runs, labels, stats = components(mask)
    if not len(stats):
        return mask
    heights = stats[:, 1] - stats[:, 0]
    ref = np.argsort(-stats[:, 4])[:max(1, len(stats) // quantile)]
    keep = heights >= max(3.0, float(np.median(heights[ref])) * frac)
    if not keep.any():
        return mask
    return keep_components(mask.shape, runs, labels, keep)


def _keep_main_row(mask: np.ndarray, min_row_px: int = 2) -> np.ndarray:
    """Keep only the horizontal band of ink that carries the most of it.

    The level readout is boxed in by other UI drawn in the same neutral white:
    the scalloped underside of the ascension pips sits directly above it and
    the element crest to its right, and both survive the colour test. They are
    separate *rows* of ink, and once Tesseract sees more than one row it stops
    treating the crop as a single line and returns mangled text, or nothing at
    all. Splitting on blank rows and keeping the heaviest band leaves the
    readout alone; a row needs a couple of pixels to count so that one stray
    fleck cannot bridge two bands into one.
    """
    rows = mask.sum(1) >= min_row_px
    best, best_ink = None, -1
    start = None
    for i, on in enumerate(np.append(rows, False)):
        if on and start is None:
            start = i
        elif not on and start is not None:
            ink = int(mask[start:i].sum())
            if ink > best_ink:
                best, best_ink = (start, i), ink
            start = None
    if best is None:
        return mask
    out = np.zeros_like(mask)
    out[best[0]:best[1]] = mask[best[0]:best[1]]
    return out


def prep_neutral(
    bgr: np.ndarray,
    *,
    max_sat: int = 40,
    min_val: int = 150,
    target_height: int = 44,
    pad: int = 14,
    cut_after_gap: float = 0.0,
    main_row: bool = False,
    speck_height_frac: float = 0.0,
) -> np.ndarray:
    """Isolate neutral-white glyphs sitting on a saturated background.

    The artifact header is a saturated orange gradient carrying pure-white
    text, so *colour* separates them far more reliably than brightness:
    measured glyph saturation is ~2 against a background of ~75. Luminance
    thresholding has to fight the gradient; this does not.
    """
    rgb = bgr[:, :, ::-1].astype(int)
    mx, mn = rgb.max(2), rgb.min(2)
    ink = ((mx - mn) <= max_sat) & (mn >= min_val)
    if ink.any():
        # Scales with the crop, same reasoning as gap_needed below: dust
        # flecks and glyph strokes both scale with capture resolution, so a
        # fraction of the (pre-trim) crop height keeps the same margin between
        # them at 1080p as at 4K. Measured on real captures: sparkle dust maxes
        # out under crop_height*0.5px; the thinnest real glyph stroke starts
        # well above it.
        ink = _drop_speckles(ink, max(20, int(round(ink.shape[0] * 0.5))))

    if speck_height_frac > 0 and ink.any():
        ink = drop_short_components(ink, speck_height_frac)

    if main_row and ink.any():
        ink = _keep_main_row(ink)

    # Trim to the glyphs. A region is cut generously to survive layout shifts,
    # so a short caption like "HP" can end up as 60px of text in a 580px-wide
    # image; Tesseract's layout analysis mishandles that aspect ratio and
    # returns nonsense even though the binarisation is clean.
    if ink.any():
        ys, xs = np.where(ink)
        y0, y1 = ys.min(), ys.max() + 1
        x0, x1 = xs.min(), xs.max() + 1
        ink = ink[y0:y1, x0:x1]

        if cut_after_gap > 0:
            # Drop everything past the first wide blank column run. Genshin
            # draws the artifact icon to the right of the header text, and its
            # bright edges survive the neutral-colour test, arriving as
            # trailing junk like "CRIT DMG ~~,". A word space is well under one
            # text-height; the gap before the icon is many times that.
            cols = ink.any(0)
            gap_needed = max(6, int(ink.shape[0] * cut_after_gap))
            run = 0
            for i, filled in enumerate(cols):
                if filled:
                    run = 0
                else:
                    run += 1
                    if run >= gap_needed:
                        ink = ink[:, : i - run + 1]
                        break

    out = np.where(ink, 0, 255).astype(np.uint8)
    if out.shape[0] < target_height:
        # A sliver of ink a pixel or two tall would otherwise scale by 20-40x
        # and come out wide enough for Tesseract to refuse the image.
        from .engine import MAX_DIM
        out = upscale(out, min(target_height / max(1, out.shape[0]),
                               MAX_DIM / max(1, out.shape[1])))
        out = np.where(out > 127, 255, 0).astype(np.uint8)
    return np.pad(out, pad, constant_values=255)
