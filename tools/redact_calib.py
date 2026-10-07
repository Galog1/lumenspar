"""Black out the player's UID in the calib/ reference screenshots.

Genshin prints "UID: nnnnnnnnn" in the bottom-right corner of every screen.
The reference captures were taken on a real account, so the repository could
not be made public with that corner intact. Measured on all 30 captures (4K
and 2000 px alike) the text sits inside x >= 0.875 W, y >= 0.965 H; the box
below adds a margin on each side. No scan region reaches it: the detail panel
read ends well above, and the only code that looks that far down is the live
frame-settling check in scan/scanner.py, which never runs on these files.

Usage:  python3 tools/redact_calib.py            # rewrites calib/**/*.png
        python3 tools/redact_calib.py --check    # exit 1 if any corner is not black
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent / "calib"
X_FRAC, Y_FRAC = 0.86, 0.955


def corner(shape: tuple[int, ...]) -> tuple[int, int]:
    h, w = shape[:2]
    return int(h * Y_FRAC), int(w * X_FRAC)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    dirty = 0
    for png in sorted(ROOT.rglob("*.png")):
        im = Image.open(png)
        arr = np.array(im)
        y, x = corner(arr.shape)
        box = arr[y:, x:, :3]
        if check:
            if box.any():
                print(f"not redacted: {png.relative_to(ROOT.parent)}")
                dirty += 1
            continue
        if not box.any():
            continue
        arr[y:, x:, :3] = 0
        Image.fromarray(arr, im.mode).save(png, optimize=True)
        print(f"redacted: {png.relative_to(ROOT.parent)}")
        dirty += 1
    if check:
        print("all redacted" if not dirty else f"{dirty} file(s) still show the corner")
        return 1 if dirty else 0
    print(f"{dirty} file(s) rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
