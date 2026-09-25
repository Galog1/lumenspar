"""Tesseract wrapper.

Uses pytesseract when present and falls back to the `tesseract` binary, so the
text pipeline works on a machine that has the engine but not the Python
binding.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

try:  # optional binding
    import pytesseract  # type: ignore
except ImportError:
    pytesseract = None

# psm 7 = one text line; psm 6 = a uniform block; psm 8 = a single word;
# psm 10 = a single character, for a glyph already isolated by segmentation.
PSM_LINE, PSM_BLOCK, PSM_WORD, PSM_CHAR = 7, 6, 8, 10

DIGITS = "0123456789"
NUMERIC = DIGITS + ".,%+"

# Leptonica refuses an image with a side over 32767 ("Image too large"), and
# every image reaching here is a small crop that some caller upscaled, so the
# only way to exceed it is an upscale that ran away on a thin sliver of ink.
# Shrinking to fit costs nothing a correct caller would have wanted.
MAX_DIM = 20000


class OcrUnavailable(RuntimeError):
    pass


_crashes: list[str] = []


def take_crashes() -> list[str]:
    """Tesseract process failures since the last call, clearing the list.

    A crash in the Tesseract *process* is not a reason to abandon a scan: it
    is one unreadable field, and the caller already knows how to report and
    save those. But it must not masquerade as an ordinary empty read either,
    or the user goes hunting for a threshold to tune that was never the
    problem -- so the reason is kept here for the scanner to surface.
    """
    out = list(_crashes)
    _crashes.clear()
    return out


def available() -> bool:
    return pytesseract is not None or shutil.which("tesseract") is not None


def _cfg(psm: int, whitelist: str | None) -> str:
    cfg = f"--oem 1 --psm {psm}"
    if whitelist:
        cfg += f" -c tessedit_char_whitelist={whitelist}"
    # Game captions are short; the dictionary hurts more than it helps because
    # proper nouns like "Kaedehara" get "corrected" into real words.
    cfg += " -c load_system_dawg=0 -c load_freq_dawg=0"
    return cfg


def read(
    img: np.ndarray,
    *,
    psm: int = PSM_LINE,
    lang: str = "eng",
    whitelist: str | None = None,
) -> str:
    """OCR a prepared (binarised) image to a stripped string.

    Returns "" rather than raising if Tesseract itself fails on this image --
    it segfaults or divides by zero on rare inputs, and a real scan lost
    fifteen characters of work to one such crash (`TesseractError(-8, '')`,
    signal 8). An empty read is already a case every caller handles: the field
    reads as unreadable, the character is reported and its frames saved.
    `take_crashes()` carries the reason out so it is not mistaken for a
    thresholding problem. A missing Tesseract still raises, since that is not
    a per-image failure and `available()` catches it before any work starts.
    """
    if not available():
        raise OcrUnavailable("tesseract is not installed")
    if img.size == 0:
        return ""
    cfg = _cfg(psm, whitelist)
    scale = MAX_DIM / max(img.shape[:2])
    if scale < 1.0:
        img = np.asarray(Image.fromarray(img).resize(
            (max(1, int(img.shape[1] * scale)),
             max(1, int(img.shape[0] * scale))), Image.LANCZOS))
    pil = Image.fromarray(img)

    if pytesseract is not None:
        try:
            return pytesseract.image_to_string(pil, lang=lang, config=cfg).strip()
        except Exception as exc:      # TesseractError, and anything it wraps
            _crashes.append(f"{type(exc).__name__}: {str(exc)[:120]}")
            return ""

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "in.png"
        pil.save(src)
        proc = subprocess.run(
            ["tesseract", str(src), "stdout", "-l", lang, *cfg.split()],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            _crashes.append(f"tesseract exited {proc.returncode}: "
                            f"{proc.stderr.strip()[:120]}")
            return ""
        return proc.stdout.strip()
