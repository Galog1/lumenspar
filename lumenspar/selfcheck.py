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
    """What the build needs beyond the window."""
    if hostos.is_windows():
        return [*_tls(), *_webengine(), *_jpeg(), *_font()]
    return [*_tls(), *_tesseract(), *_gstreamer(), *_dbus(), *_webengine(), *_jpeg(), *_font()]


def _tls() -> list[Check]:
    """Trusted certificates are loaded, so HTTPS requests can be verified.

    Checked without any network: a Linux bundle carrying the build machine's
    OpenSSL found no certificates on other distributions, and every web
    request (wishes, Enka.Network, Gemini) failed. See lumenspar/netcerts.py.
    """
    try:
        import ssl
        from pathlib import Path

        loaded = ssl.create_default_context().cert_store_stats()["x509_ca"]
        capath = ssl.get_default_verify_paths().capath
        # A certificate directory is read lazily, so it counts if it has files.
        lazy = bool(capath and Path(capath).is_dir() and any(Path(capath).iterdir()))
        return [("trusted HTTPS certificates", loaded > 0 or lazy,
                 f"{loaded} loaded" + (f", directory {capath}" if lazy else ""))]
    except Exception as exc:
        return [("trusted HTTPS certificates", False, f"{type(exc).__name__}: {exc}")]


def _webengine() -> list[Check]:
    """Qt WebEngine and its QML module are in the bundle (the HoYoLAB sign-in window).

    Without them the feature quietly turns itself off, so a release that lost
    them must fail here instead. Only resolves the QML module; no browser starts.
    """
    name = "embedded browser (Qt WebEngine)"
    try:
        from PySide6 import QtWebEngineQuick  # noqa: F401
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlComponent, QQmlEngine

        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.setData(b"import QtQml\nimport QtWebEngine\n"
                          b"QtObject { property var p: WebEngineProfile {} }", QUrl())
        ready = component.status() == QQmlComponent.Status.Ready
        return [(name, ready, "" if ready else component.errorString().strip()[:160])]
    except Exception as exc:
        return [(name, False, f"{type(exc).__name__}: {exc}")]


def _jpeg() -> list[Check]:
    """Qt can write and read JPEG, which the build cards' baked backdrops are.

    A bundle without the image-format plugin would show every card on a plain
    gradient, so a release that lost it must fail here.
    """
    name = "JPEG images (card backdrops)"
    try:
        from PySide6.QtGui import QImage, QImageReader, QImageWriter
        from tempfile import TemporaryDirectory

        if b"jpg" not in QImageWriter.supportedImageFormats():
            return [(name, False, "no JPEG writer")]
        with TemporaryDirectory() as tmp:
            path = f"{tmp}/probe.jpg"
            image = QImage(8, 8, QImage.Format_RGB32)
            image.fill(0x336699)
            ok = image.save(path, "JPG", 88) and not QImageReader(path).read().isNull()
        return [(name, ok, "" if ok else "could not round-trip an image")]
    except Exception as exc:
        return [(name, False, f"{type(exc).__name__}: {exc}")]


def _font() -> list[Check]:
    """The bundled interface font is in the bundle and registered (see ui/fonts.py).

    Without it the build cards fall back to the system font and their layout,
    which is measured against Inter, can truncate or gap.
    """
    name = "interface font (Inter)"
    try:
        from PySide6.QtGui import QFontDatabase

        from .ui import fonts

        missing = [f for f in fonts.FILES if not (fonts.FONT_DIR / f).is_file()]
        if missing:
            return [(name, False, "missing " + ", ".join(missing))]
        ok = fonts.FAMILY in QFontDatabase.families()
        return [(name, ok, "" if ok else "the files are there but Qt did not register them")]
    except Exception as exc:
        return [(name, False, f"{type(exc).__name__}: {exc}")]


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

