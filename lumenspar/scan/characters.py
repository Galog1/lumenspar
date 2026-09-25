"""Read the character screen (opened with C).

Unlike the inventory this is not a grid: characters are pages reached with the
same Q/E keys, and the fields live on three sub-screens (Attributes, Talents,
Constellation) selected from the left-hand menu.

All regions are fractions of the frame, measured from 16:9 captures.
"""

from __future__ import annotations

import re

import numpy as np
from PIL import Image

from ..ocr import engine as ocr
from ..ocr import preprocess as pp
from .character_parse import CONSTELLATION_TALENT_BONUS, TALENT_LIMITS
from .layout import Region

# Attributes screen.
R_HEADER = (0.040, 0.018, 0.240, 0.050)   # "Pyro / Arlecchino" (element / name)
R_NAME = (0.755, 0.110, 0.945, 0.165)
R_LEVEL = (0.750, 0.175, 0.975, 0.245)    # "Level 80 / 90"
# The flavour blurb under the stats. Only needed to explain an unrecognised
# name: a Manekin's displayed name is whatever the player called it, but its
# description is fixed text that says what it is.
R_DESCRIPTION = (0.755, 0.545, 0.945, 0.695)
# Talents screen: read as one block and pick the levels off in order.
R_TALENTS = (0.700, 0.110, 0.905, 0.620)
# Constellation screen: the six nodes lie on a curve, so x varies with y.
# Centres measured from the white glyph each node carries (a padlock when
# locked, line-art when unlocked), independently on two different characters'
# screens -- the two agree to within ~5px at 4K, confirming fixed UI geometry.
CONSTELLATION_NODES = (
    (0.7958, 0.2518), (0.8186, 0.3604), (0.8385, 0.4638),
    (0.8386, 0.5678), (0.8196, 0.6673), (0.7857, 0.7730),
)
# An unlocked node is wrapped in a bright element-coloured glow; a locked one
# sits flat on the background. Measured as the brightness of that halo divided
# by the plain background just outside it, sampled only on the side away from
# the constellation's name text: locked nodes score 0.95-1.03, unlocked ones
# 1.76-2.39.
#
# The ratio matters more than the numbers. Reading the node's *interior*
# instead (its colour saturation) worked on both calibration screens but only
# by 10.9 vs 22.9, and it measures a quantity that a bright patch of the
# slowly drifting background inflates directly -- which is how a C3 character
# came back as C4 on a real run. Dividing by the neighbouring background makes
# the measure self-normalising: a patch bright enough to lift the halo lifts
# the reference with it, and the ratio stays put.
NODE_RING = (0.019, 0.023)      # halo, as fractions of frame width
NODE_BACKGROUND = (0.028, 0.033)
# The halo is scored two ways, because the two survive different distortions:
# the ratio is unchanged by a contrast or gamma difference between monitors,
# and the plain difference is unchanged by a brightness wash drifting across
# the panel. Whichever is more confident wins, so a node has to defeat both to
# be misread. Measured over 18 nodes on three characters (18 = every node of a
# C1, a C3 and a C6 screen, across three elements and backgrounds):
#   ratio       locked 0.92-1.03    unlocked 1.67-2.39
#   difference  locked -8.0..+1.8   unlocked +81.3..+111.9
NODE_GLOW_RATIO = 1.35
NODE_GLOW_DIFF = 40.0
NODE_UNLOCKED = 1.0             # scores are expressed relative to the above

ELEMENTS = ("pyro", "hydro", "anemo", "electro", "dendro", "cryo", "geo")

# Left-hand menu, top to bottom. W and S move the selection, exactly as Q and E
# move between characters, so the menu never has to be clicked.
MENU_ITEMS = ("attributes", "weapons", "artifacts",
              "constellation", "talents", "profile")
MENU_Y = (0.143, 0.206, 0.270, 0.335, 0.400, 0.465)
MENU_X = (0.075, 0.190)
# The selected entry is the only one drawn in pure white (and a size larger);
# every other entry is grey or tan. Measured as a fraction of the row's area so
# it is resolution-independent: selected rows score 0.15-0.23, the best
# unselected row seen scores 0.045.
MENU_WHITE_MIN = 0.08
MENU_WHITE_RATIO = 2.0
# How many presses may pass without the selection moving before the walk is
# declared stuck, and an overall ceiling so a menu that somehow keeps changing
# cannot spin forever.
MENU_STUCK_LIMIT = 4
MENU_STEP_LIMIT = 40

def _region(frame: np.ndarray, spec) -> Region:
    h, w = frame.shape[:2]
    a, b, c, d = spec
    return Region(int(w * a), int(h * b), int(w * c), int(h * d))


def read_name(frame: np.ndarray) -> str:
    """Character name from the Attributes panel."""
    return ocr.read(
        pp.prep_neutral(_region(frame, R_NAME).crop(frame),
                        max_sat=70, min_val=170, cut_after_gap=1.8),
        psm=ocr.PSM_LINE).strip()


def read_level(frame: np.ndarray) -> str:
    """Raw level text, e.g. 'Level 80/90'.

    At the level-95/100 boost tiers the current-level number is drawn in a
    salmon highlight (sat ~102) rather than neutral white/grey; max_sat=110
    (measured, not guessed -- background pixels there are already excluded by
    min_val, and no genuine background pixel reaches sat>102) admits it
    without picking up any more of the background.

    `main_row` drops the scalloped underside of the ascension pips above the
    readout and the element crest beside it, both of which are the same
    neutral white and used to leave Tesseract with 'Level907%0' or nothing.
    `speck_height_frac` clears the starfield sparkle: one fleck landing on the
    "/" is enough to turn "100 / 100" into "1007100".
    """
    return ocr.read(
        pp.prep_neutral(_region(frame, R_LEVEL).crop(frame),
                        max_sat=110, min_val=100, cut_after_gap=3.0,
                        main_row=True, speck_height_frac=SPECK_HEIGHT_FRAC),
        psm=ocr.PSM_LINE).strip()


def read_description(frame: np.ndarray) -> str:
    """The flavour blurb under the stats, as one line.

    Read only to make sense of a name that matched nothing. Several characters
    carry a player-chosen name -- the Traveler, a renamed Wanderer, a Manekin
    -- so the name can be anything at all, but the blurb is fixed text.
    """
    return " ".join(ocr.read(
        pp.prep_neutral(_region(frame, R_DESCRIPTION).crop(frame),
                        max_sat=70, min_val=120),
        psm=ocr.PSM_BLOCK).split())


def read_element(frame: np.ndarray) -> str | None:
    """Element from the 'Pyro / Arlecchino' header.

    Only needed for the Traveler, whose GOOD key is element-suffixed and cannot
    be derived from the name. The header renders small, so the text is matched
    loosely against the seven element names rather than read exactly.
    """
    txt = ocr.read(
        pp.prep_neutral(_region(frame, R_HEADER).crop(frame),
                        max_sat=80, min_val=140, cut_after_gap=3.0),
        psm=ocr.PSM_LINE).lower()
    head = txt.split("/")[0] if "/" in txt else txt
    # The header begins with an element icon, which OCRs as stray characters
    # ("A. Crva / Gal"); the element is the last word before the slash.
    words = [w for w in re.split(r"[^a-z]+", head) if len(w) >= 3]
    probe = words[-1] if words else re.sub(r"[^a-z]", "", head)
    if not probe:
        return None
    try:
        from rapidfuzz import fuzz, process
        best = process.extractOne(probe, list(ELEMENTS), scorer=fuzz.WRatio)
        return best[0] if best and best[1] >= 62 else None
    except ImportError:
        return next((e for e in ELEMENTS if e in probe), None)


# --- Talents screen -------------------------------------------------------
#
# The level readout ("Lv. 13") is drawn brighter than the talent *names* beside
# it, and a constellation-boosted one is drawn cyan instead of white. Both are
# isolated by colour rather than by luminance thresholding: the backgrounds are
# saturated gradients that drift continuously, so a global Otsu threshold over
# the whole block fails somewhere on every frame, while colour separates
# cleanly. Measured across purple, teal, gold and red character backgrounds:
# `min(RGB) >= 190` catches every white readout with zero background bleed, and
# the cyan test below catches every boosted one -- also with zero bleed, even
# on the teal background whose own hue is closest to the text.
TALENT_INK_MIN = 190
# Fallback thresholds, tried in order until three labelled level rows are
# found. A lower-resolution capture renders the digits smaller and softer, and
# the strict threshold erodes them; the "three rows, each with a readable 'Lv.'
# label beside a 1-2 digit number" structure is a strong enough check to let
# the *result* choose the threshold instead of tuning one per resolution.
TALENT_INK_STEPS = (190, 165, 145)
CYAN_CHANNEL_MIN = 170
CYAN_GAP = 100          # how far G and B must sit above R
# Splits a row into words. Measured at 4K: 3-7px between the digits of a
# two-digit number, ~30px for the space after "Lv.". Stated as a fraction so it
# scales with capture resolution.
GAP_WORD = 0.015        # ~12px at 4K: splits "Lv." from the number
CYAN_INK_SHARE = 0.25   # share of a number's ink that must be cyan to count
# The panel background is a field of drifting sparkle dust, and on a pale
# character screen (Odette's white sky) the brighter flecks pass the ink test
# just as glyph strokes do. They are erased by *component height* rather than
# by area or a fixed size: measured on a 4K Odette capture, 299 dust components
# stood under 15px tall against 110 glyph components at 22-35px, an empty band
# in between. The threshold is taken relative to the region's own glyphs so it
# holds at every capture resolution.
SPECK_HEIGHT_FRAC = 0.45
# Which glyphs count as "the region's own": the largest quarter by area, whose
# median height is a stable stand-in for cap height even when dust outnumbers
# text several to one.
SPECK_REFERENCE_QUANTILE = 4
# ...and the opposite end. A teal character background (Anemo, Cryo) is itself
# close enough to the boosted-talent cyan that its brighter patches pass the
# cyan test outright -- a real Faruzan capture put 33,000 background pixels
# into the ink mask, merging whole rows together. No colour threshold
# separates them: measured across every capture, the background bleed reaches
# a full (x,255,255) just as the text does. Size does separate them, because
# the bleed arrives as one large glow blob: real glyph components top out at
# 105px tall over every frame tested, the blobs start at 130.
BLOB_HEIGHT_FRAC = 0.10         # of the talents region's height
# The level readout sits in a fixed, narrow column, so everything else in the
# region -- the drifting background on the left, the decorative talent icon on
# the right -- can simply be cut away before the rows are picked apart. This is
# what finally made the teal backgrounds readable: the flood is mostly outside
# this column, and the icon's glow used to bridge the gap to the number and
# swallow it into one unreadable group.
LEVEL_COLUMN = (0.70, 0.92)     # fractions of the region width
# Where the number's right edge lands, as a fraction of the region width.
# Genshin right-aligns the readout, so this is fixed UI geometry: measured over
# 67 confidently-read rows spanning every capture, every one fell in
# 0.8856-0.8895. Checking it is far more reliable than confirming the "Lv."
# beside it -- on a bright gold background the label's own "v" erodes and reads
# back as a bare "L", which used to throw away all three of Arataki Itto's
# rows.
LEVEL_EDGE = 0.888
LEVEL_EDGE_TOL = 0.010
# Heights an isolated digit is rendered at before OCR, and voted across.
# Measured over 17 real digit glyphs: no single height is reliable on its own
# (48px got 16/17, 96px 14/17, 128px 9/17), and the failures are not blanks but
# *confident wrong answers* -- a "9" reads as "0" at 128px. A first-success
# chain would lock that in; a majority vote across heights does not. Voting
# these three reads every real glyph correctly.
DIGIT_HEIGHTS = (40, 48, 64)
# What the game is able to draw in a level row. A talent tops out at 10, and a
# constellation raises one by +3 on top of that, so 13 is the highest number
# that can appear at all and 10 the highest that can appear in white. This is a
# rule of the game rather than a tuned bound, and it is checked here, at the
# point of reading, so that a misread digit is rejected and the next candidate
# tried. Leaving it to `base_talent`'s clamp instead would launder the misread:
# a white "14" would be silently filed as 10, which is a plausible-looking
# number nobody would ever question.
TALENT_MAX_SHOWN = TALENT_LIMITS[-1]
TALENT_MAX_SHOWN_BOOSTED = TALENT_MAX_SHOWN + CONSTELLATION_TALENT_BONUS


def talent_masks(crop: np.ndarray, ink_min: int = TALENT_INK_MIN
                ) -> tuple[np.ndarray, np.ndarray]:
    """(ink, cyan) boolean masks for a Talents-screen region.

    `cyan` is a subset of `ink`; a boosted number is essentially all cyan and
    an unboosted one none at all, so their ratio separates the two with an
    enormous margin rather than a tuned threshold.
    """
    rgb = crop[:, :, ::-1].astype(int)                    # BGR -> RGB
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    cyan = ((g >= CYAN_CHANNEL_MIN) & (b >= CYAN_CHANNEL_MIN)
            & (g - r >= CYAN_GAP) & (b - r >= CYAN_GAP))
    return (rgb.min(2) >= ink_min) | cyan, cyan


def _bands(mask: np.ndarray, min_px: int = 4) -> list[tuple[int, int]]:
    """Row ranges that carry ink."""
    rows = mask.sum(1) > min_px
    out, start = [], None
    for i, on in enumerate(rows):
        if on and start is None:
            start = i
        elif not on and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(rows)))
    return out


def _runs(cols: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous ink column ranges, as (first, last) inclusive."""
    xs = np.where(cols)[0]
    if not len(xs):
        return []
    out, start, prev = [], int(xs[0]), int(xs[0])
    for x in xs[1:]:
        x = int(x)
        if x - prev > 1:
            out.append((start, prev))
            start = x
        prev = x
    out.append((start, prev))
    return out


def _groups(runs, gap_px: float):
    """Group adjacent runs, splitting wherever the gap reaches `gap_px`."""
    if not runs:
        return []
    out, cur = [], [runs[0]]
    for prev, nxt in zip(runs, runs[1:]):
        if nxt[0] - prev[1] >= gap_px:
            out.append(cur)
            cur = []
        cur.append(nxt)
    out.append(cur)
    return out


def _clean_ink(mask: np.ndarray) -> np.ndarray:
    """Strip both the background glow blobs and the sparkle dust from talent ink.

    Two filters, largest first. The blob cut is a plain geometric bound -- no
    glyph in this region is a tenth of its height -- and it has to run before
    the speck filter because the speck filter calibrates itself on the largest
    components present, so a glow blob left in place drags its reference height
    down and disables it.
    """
    runs, labels, stats = pp.components(mask)
    if len(stats):
        keep = (stats[:, 1] - stats[:, 0]) <= mask.shape[0] * BLOB_HEIGHT_FRAC
        if keep.any():
            mask = pp.keep_components(mask.shape, runs, labels, keep)
    return pp.drop_short_components(mask, SPECK_HEIGHT_FRAC,
                                    SPECK_REFERENCE_QUANTILE)


def _level_spans(band: np.ndarray, width: int):
    """Candidate (label_span, number_span) pairs in a row, rightmost first.

    Splits the row on its own blank columns rather than trusting OCR to
    segment it, then offers every adjacent pair of word-groups as a possible
    "Lv." + number, for the caller to confirm by reading them.

    Offering candidates instead of picking one is what makes this survive the
    talent icon at the right of each row. The icon is only *sometimes* bright
    enough to reach the ink mask, so the number is the last group on some rows
    and the second-to-last on others, and the two gaps cannot be told apart by
    width: measured at 4K the gap after "Lv." is ~30px and the gap before the
    icon ~72px, but an earlier fixed 30px cut classified the number itself as
    the icon and silently dropped the row -- which is what left a run of
    characters with an unreadable burst talent.

    Groups of more than two runs are skipped as numbers: no talent level is
    wider than two digits, and that alone rules out every word in a talent
    *name*, so the confirming OCR is only ever asked about a plausible row.
    """
    groups = _groups(_runs(band.any(0)), width * GAP_WORD)
    for i in range(len(groups) - 1, 0, -1):
        number, label = groups[i], groups[i - 1]
        if len(number) > 2:
            continue
        yield ((label[0][0], label[-1][1]), (number[0][0], number[-1][1]))


def _ocr_mask(mask: np.ndarray, psm: int, whitelist: str) -> str:
    """OCR a boolean ink mask directly, with no thresholding step.

    The mask *is* the segmentation -- handing Tesseract a photo of a drifting
    gradient and asking it to re-threshold the text out is what used to fail.
    """
    ys, xs = np.where(mask)
    if not len(ys):
        return ""
    img = np.where(mask[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1],
                   0, 255).astype(np.uint8)
    h, w = img.shape
    if h < 96:
        # Cap the factor so a long, short strip cannot scale past Tesseract's
        # own size limit.
        img = pp.upscale(img, min(96 / max(1, h), 4000 / max(1, w)))
        img = np.where(img > 127, 255, 0).astype(np.uint8)
    return ocr.read(np.pad(img, 16, constant_values=255),
                    psm=psm, whitelist=whitelist).strip()


def _render(mask: np.ndarray, height: int) -> np.ndarray:
    """Black-on-white render of an ink mask at a given height, padded for OCR."""
    img = np.where(mask, 0, 255).astype(np.uint8)
    h, w = img.shape
    if h != height and h > 0:
        # Capped for the same reason as in `_ocr_mask`: a glyph only a pixel
        # or two tall scales by a huge factor, and the result is wide enough
        # for Tesseract to refuse the image outright.
        scale = min(height / h, ocr.MAX_DIM / max(1, w))
        img = np.asarray(Image.fromarray(img).resize(
            (max(1, int(w * scale)), height), Image.LANCZOS))
        img = np.where(img > 127, 255, 0).astype(np.uint8)
    return np.pad(img, 16, constant_values=255)


def _read_glyph(glyph: np.ndarray) -> str | None:
    """Name a single isolated digit, by majority vote across render heights."""
    votes: list[str] = []
    for height in DIGIT_HEIGHTS:
        img = _render(glyph, height)
        for psm in (ocr.PSM_CHAR, ocr.PSM_WORD):
            got = ocr.read(img, psm=psm, whitelist=ocr.DIGITS).strip()
            if len(got) == 1 and got.isdigit():
                votes.append(got)
                break
    if not votes:
        return None
    return max(set(votes), key=votes.count)


def _read_digits(slice_: np.ndarray) -> str | None:
    """Read a 1-2 digit number from an isolated ink slice.

    Each digit is read on its own. Whole-number OCR was measured to be
    unstable in a way no single setting fixed: the same legible "11" came back
    as "11", "1", "7" or nothing depending only on the scale it was rendered
    at, and PSM_LINE and PSM_WORD disagreed at every size. An isolated glyph
    has no segmentation left to get wrong, and the run count says up front how
    many digits to expect, so a short read is caught rather than silently
    accepted ("13" read as "3" was exactly this).

    The whole-slice read is kept only as a fallback, for when the digits are
    small enough that the gap between them closes and they arrive as one run.
    """
    runs = _runs(slice_.any(0))
    if not runs:
        return None

    if len(runs) <= 2:
        digits = ""
        for x0, x1 in runs:
            glyph = slice_[:, x0:x1 + 1]
            rows = np.where(glyph.any(1))[0]
            if not len(rows):
                digits = ""
                break
            got = _read_glyph(glyph[rows[0]: rows[-1] + 1])
            if got is None:
                digits = ""
                break
            digits += got
        if digits:
            return digits

    for psm in (ocr.PSM_LINE, ocr.PSM_WORD, ocr.PSM_BLOCK):
        got = _ocr_mask(slice_, psm, ocr.DIGITS)
        if re.fullmatch(r"\d{1,2}", got):
            return got
    return None


def _talents_pass(frame: np.ndarray, ink_min: int) -> list[tuple[int, bool]]:
    """Talent levels in order auto, skill, burst, each flagged as showing a
    constellation bonus.

    Which talent(s) C3/C5 boost is kit-specific (Raiden Shogun's C3 boosts
    Burst, Neuvillette's boosts Auto), so the bonus is never inferred -- the
    game draws a boosted number cyan and that is read directly.

    Rows are found from the colour mask, and each row is split into "Lv." and
    its number by that row's own blank columns, so the only thing OCR is asked
    to do is name one or two isolated digits. Reading the whole block as text
    and hunting for "Lv." tokens was tried first and was persistently
    unreliable: a legible "11" came back as "7", "1", or a quote mark
    depending on framing, and PSM_LINE vs PSM_WORD flipped which frames
    worked.
    """
    crop = _region(frame, R_TALENTS).crop(frame)
    ink, cyan = talent_masks(crop, ink_min)
    ink = _clean_ink(ink)
    height, width = ink.shape
    # Keep only the column the readout lives in. Order matters: the blob cut
    # inside `_clean_ink` has to happen first, because a background glow big
    # enough to reach this column also drags the speck filter's own reference
    # height down with it and then nothing gets cleaned at all.
    column = np.zeros_like(ink)
    column[:, int(width * LEVEL_COLUMN[0]): int(width * LEVEL_COLUMN[1])] = True
    ink &= column
    cyan &= ink

    out: list[tuple[int, bool]] = []
    # A couple of pixels of slack at the bottom of the supported resolutions,
    # where the whole region is only ~260px wide and the window would otherwise
    # be narrower than a single pixel.
    tol = max(LEVEL_EDGE_TOL, 3.0 / width)
    for top, bottom in _bands(ink):
        if len(out) == 3:
            break
        band, band_cyan = ink[top:bottom], cyan[top:bottom]
        for (lx0, lx1), (x0, x1) in _level_spans(band, width):
            # Confirm this really is a level row, so a talent *name* whose last
            # word happens to OCR as a digit cannot be mistaken for one. The
            # number's right edge carries most of the weight because it is
            # fixed UI geometry; the label beside it only has to look like
            # "Lv." at all. Requiring the label to read back as the full "lv"
            # was tried and is too strict -- on a bright gold background the
            # lowercase "v" erodes and comes back as a bare "L".
            if abs((x1 + 1) / width - LEVEL_EDGE) > tol:
                continue
            label = _ocr_mask(band[:, lx0:lx1 + 1], ocr.PSM_LINE, "LvVl.").lower()
            if "l" not in label and "v" not in label:
                continue

            digits = _read_digits(band[:, x0:x1 + 1])
            if digits is None:
                continue

            num_ink = int(band[:, x0:x1 + 1].sum())
            num_cyan = int(band_cyan[:, x0:x1 + 1].sum())
            boosted = bool(num_ink) and num_cyan >= CYAN_INK_SHARE * num_ink
            level = int(digits)
            if not 1 <= level <= (TALENT_MAX_SHOWN_BOOSTED if boosted
                                  else TALENT_MAX_SHOWN):
                continue
            out.append((level, boosted))
            break
    return out


def _node_glow(rgb: np.ndarray, cx: float, cy: float) -> float:
    """How strongly one constellation node is haloed, relative to threshold.

    Returns a score where >= NODE_UNLOCKED means unlocked. Both measures are
    taken against the background immediately outside the node, which is what
    makes this robust to the slowly drifting character-screen backgrounds: a
    patch bright enough to lift the halo lifts its own reference with it.
    """
    h, w = rgb.shape[:2]
    x, y = int(w * cx), int(h * cy)
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
    left = xx <= x                      # the constellation's name sits right
    ring = (d >= w * NODE_RING[0]) & (d < w * NODE_RING[1]) & left
    back = (d >= w * NODE_BACKGROUND[0]) & (d < w * NODE_BACKGROUND[1]) & left
    if not ring.any() or not back.any():
        return 0.0
    ring_v = float(rgb[ring].max(1).mean())
    back_v = float(rgb[back].max(1).mean())
    return max(ring_v / max(back_v, 1.0) / NODE_GLOW_RATIO,
               (ring_v - back_v) / NODE_GLOW_DIFF)


def _unlocked_prefix(scores: list[float], threshold: float) -> int:
    """How many leading nodes are unlocked.

    Constellations unlock strictly in order, so the unlocked nodes are always
    a prefix -- "1 and 6 but not 2-5" is not a state the game can be in. Fitting
    that step, rather than thresholding each node on its own, means one node
    misread against the run of its neighbours cannot invent a constellation.
    """
    best_k, best_score = 0, None
    for k in range(len(scores) + 1):
        margin = (sum(v - threshold for v in scores[:k])
                  + sum(threshold - v for v in scores[k:]))
        if best_score is None or margin > best_score:
            best_k, best_score = k, margin
    return best_k


def read_constellation(frame: np.ndarray) -> int:
    """Count unlocked constellation nodes (0-6)."""
    rgb = frame[:, :, ::-1].astype(int)
    scores = [_node_glow(rgb, cx, cy) for cx, cy in CONSTELLATION_NODES]
    return _unlocked_prefix(scores, NODE_UNLOCKED)


def traveler_key(element: str | None) -> str | None:
    """'cryo' -> 'TravelerCryo'."""
    if not element:
        return None
    return "Traveler" + element.capitalize()


def selected_menu_item(frame: np.ndarray) -> str | None:
    """Which left-menu entry is highlighted, or None if none of them is.

    Compared by how much *pure white* ink a row carries. Glyph colour alone
    (white vs tan) fails on the Constellation page, whose blue starfield
    background renders the unselected entries near-neutral grey as well; pixel
    count alone fails on the Talents page, where the longer word
    "Constellation" outscores a selected "Talents". Whiteness separates every
    calibration shot by at least 5x.
    """
    v = frame.min(2)                       # neutral brightness, colour-blind
    h, w = v.shape[:2]
    scores = []
    for name, y in zip(MENU_ITEMS, MENU_Y):
        seg = v[int(h * (y - 0.018)): int(h * (y + 0.018)),
                int(w * MENU_X[0]): int(w * MENU_X[1])]
        if seg.size == 0:
            return None
        scores.append((float((seg > 235).mean()), name))
    scores.sort(reverse=True)
    best, runner = scores[0], scores[1]
    if best[0] < MENU_WHITE_MIN or best[0] < runner[0] * MENU_WHITE_RATIO:
        return None
    return best[1]


def select_menu(target, tap, grab, sleep, log=lambda _m: None,
                key_up="w", key_down="s", step_delay=0.30,
                should_stop=lambda: False) -> bool:
    """Move the left-menu selection to `target` using W/S.

    Steps *relatively* from wherever the cursor already is, one press at a
    time with a re-read after each -- never homing to the top first. The
    selection survives the Q/E character switch, so walking the pages down for
    one character and back up for the next costs no return trip. Verifying
    each press also means it does not matter whether the list clamps or wraps.

    The budget is spent on presses that achieve *nothing*, not on presses in
    total. A flat cap was tried and gave up on two real characters: when the
    highlight cannot be read for a few frames the walk has no direction to step
    in, spends its whole allowance groping upwards, and then reports failure
    from the top of the menu having never actually tried to reach the target.
    Counting only the presses that left the selection where it was ends the
    walk when it is genuinely stuck, while letting a slow or briefly
    unreadable menu take as long as it needs.
    """
    if target not in MENU_ITEMS:
        return False
    want = MENU_ITEMS.index(target)
    here = selected_menu_item(grab())
    stuck = 0
    steps = 0
    while here != target:
        if should_stop():
            return False
        if stuck >= MENU_STUCK_LIMIT or steps >= MENU_STEP_LIMIT:
            log(f"error: wanted the {target} page but landed on "
                f"{here or 'an unknown page'}")
            return False
        # With the position unknown there is no direction to step in; walking
        # up eventually reaches the top entry, which is recognisable again.
        tap(key_up if here is None or MENU_ITEMS.index(here) > want
            else key_down)
        sleep(step_delay)
        was, here = here, selected_menu_item(grab())
        steps += 1
        stuck = stuck + 1 if here == was else 0
    return True


def read_talents(frame: np.ndarray) -> list[tuple[int, bool]]:
    """Talent levels in order auto, skill, burst, each flagged as boosted.

    See `_talents_pass` for how a row is read. This wrapper only escalates the
    ink threshold: the strict one is right for a native-resolution capture and
    keeps the background out entirely, but erodes the digits on a smaller or
    softer one, so a pass that comes up short is retried looser and the first
    complete result wins.
    """
    best: list[tuple[int, bool]] = []
    for ink_min in TALENT_INK_STEPS:
        got = _talents_pass(frame, ink_min)
        if len(got) == 3:
            return got
        if len(got) > len(best):
            best = got
    return best
