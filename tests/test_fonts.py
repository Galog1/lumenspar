"""The bundled interface font (lumenspar/fonts, lumenspar/ui/fonts.py)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from lumenspar import selfcheck  # noqa: E402
from lumenspar.ui import fonts  # noqa: E402


def test_the_font_files_and_their_license_ship_with_the_app():
    for name in fonts.FILES:
        data = (fonts.FONT_DIR / name).read_bytes()
        assert data[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO"), name   # a real font file
        assert len(data) > 100_000
    licence = (fonts.FONT_DIR / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in licence and "Inter Project Authors" in licence


def test_both_packaging_recipes_and_the_source_install_include_the_font():
    root = Path(__file__).resolve().parents[1]
    for spec in ("packaging/windows/lumenspar.spec", "packaging/linux/lumenspar.spec"):
        assert '"lumenspar" / "fonts"' in (root / spec).read_text(encoding="utf-8"), spec
    assert "fonts/*.ttf" in (root / "pyproject.toml").read_text(encoding="utf-8")


def test_the_font_registers_and_the_self_check_agrees():
    """Needs a GUI application, so it runs in its own offscreen process."""
    code = (
        "import sys\n"
        "from PySide6.QtGui import QGuiApplication, QFontDatabase\n"
        "app = QGuiApplication(sys.argv)\n"
        "from lumenspar.ui import fonts\n"
        "from lumenspar import selfcheck\n"
        "assert fonts.load(), 'font did not load'\n"
        "assert fonts.FAMILY in QFontDatabase.families()\n"
        "(name, ok, detail), = selfcheck._font()\n"
        "assert ok, detail\n"
        "print('ok')\n"
    )
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True,
                         env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"},
                         timeout=60)
    assert out.returncode == 0 and "ok" in out.stdout, out.stderr[-600:]


def test_the_self_check_reports_a_missing_font(monkeypatch, tmp_path):
    monkeypatch.setattr(fonts, "FONT_DIR", tmp_path)
    (name, ok, detail), = selfcheck._font()
    assert name == "interface font (Inter)" and not ok and "Inter-Regular.ttf" in detail
