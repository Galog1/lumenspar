"""Checks a packaged build runs on itself, to prove it carries what it needs.

`ui/app.py` runs these when LUMENSPAR_SMOKE_TEST is set (release builds do
this in CI, headless). A frozen app can be missing a library, a plugin or a
data file without anything failing until a user reaches the feature that
needs it, so each check *uses* the thing rather than just finding the file:
Tesseract must actually read a number, GStreamer must actually provide the
elements the capture pipeline is built from.

Each check is (name, ok, detail).
"""

from __future__ import annotations

from . import hostos

Check = tuple[str, bool, str]

# The capture pipeline in capture/portal.py, element by element.
CAPTURE_ELEMENTS = ("pipewiresrc", "videoconvert", "capsfilter", "appsink")


def bundle_checks() -> list[Check]:
    """What the Linux build needs beyond the window. Windows needs none."""
    if hostos.is_windows():
        return []
    return [*_tesseract(), *_gstreamer(), *_dbus()]


def _tesseract() -> list[Check]:
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont

        from .ocr import engine

        try:
            font = ImageFont.load_default(size=56)
        except TypeError:                       # Pillow < 10.1: fixed bitmap font
            font = ImageFont.load_default()
        img = Image.new("L", (360, 110), 255)
        ImageDraw.Draw(img).text((24, 18), "4072", fill=0, font=font)
        got = engine.read(np.asarray(img), psm=engine.PSM_LINE, whitelist=engine.DIGITS)
        crashes = engine.take_crashes()
        detail = f"read {got!r}" + (f"; {crashes[0]}" if crashes else "")
        return [("tesseract reads a number", got == "4072", detail)]
    except Exception as exc:
        return [("tesseract reads a number", False, f"{type(exc).__name__}: {exc}")]


def _gstreamer() -> list[Check]:
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
        return [(f"gstreamer element {name}", Gst.ElementFactory.find(name) is not None, "")
                for name in CAPTURE_ELEMENTS]
    except Exception as exc:
        return [("gstreamer", False, f"{type(exc).__name__}: {exc}")]


def _dbus() -> list[Check]:
    try:
        import dbus  # noqa: F401
        import dbus.mainloop.glib  # noqa: F401
        return [("dbus with the GLib main loop", True, "")]
    except Exception as exc:
        return [("dbus with the GLib main loop", False, f"{type(exc).__name__}: {exc}")]

