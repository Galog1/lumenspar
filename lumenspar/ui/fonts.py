"""The interface font.

Inter ships inside the app (lumenspar/fonts, SIL Open Font License) so the
windows, the build cards and the images they are saved as look the same on
Linux and Windows instead of using whatever the system default is, whose
letter widths the card layout would have to guess.
"""

from __future__ import annotations

from pathlib import Path

FAMILY = "Inter"
FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"
FILES = ("Inter-Regular.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf")


def load() -> bool:
    """Register the bundled font with Qt; True if it is available.

    Needs the application object to exist. Never raises: without the font the
    interface falls back to the system one.
    """
    from PySide6.QtGui import QFontDatabase

    loaded = [QFontDatabase.addApplicationFont(str(FONT_DIR / name)) for name in FILES
              if (FONT_DIR / name).is_file()]
    return bool(loaded) and all(i >= 0 for i in loaded) and FAMILY in QFontDatabase.families()
