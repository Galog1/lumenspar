"""Frame crops for the Gemini reader.

Frames are BGR uint8 (the live capture order -- failure dumps do
`frame[:, :, ::-1]` to get RGB, and so does this module). Crops are JPEG so
they can be inlined into a Gemini request; long sides are downscaled to keep
requests small while panel text at 1080p-4K stays legible.
"""

from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image

from ..scan.layout import Region


def encode_jpeg(crop: np.ndarray, quality: int = 88, max_side: int = 1400) -> bytes:
    """BGR uint8 crop -> JPEG bytes, downscaled so the longer side <= max_side."""
    if crop.ndim != 3 or crop.shape[2] != 3:
        raise ValueError(f"expected a BGR frame crop, got shape {crop.shape}")
    rgb = crop[:, :, ::-1]                    # BGR -> RGB for PIL
    im = Image.fromarray(np.ascontiguousarray(rgb))
    if max(im.size) > max_side:
        scale = max_side / float(max(im.size))
        im = im.resize((max(1, int(im.width * scale)),
                        max(1, int(im.height * scale))), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def crop(frame: np.ndarray, region_or_box) -> np.ndarray:
    """Crop helpers for a layout.Region or a plain (x0, y0, x1, y1) int tuple."""
    if isinstance(region_or_box, Region):
        return region_or_box.crop(frame)
    x0, y0, x1, y1 = region_or_box
    return frame[y0:y1, x0:x1]
