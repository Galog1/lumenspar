"""The bundle self-check reports on the embedded browser."""

import pytest

from lumenspar import selfcheck


def test_webengine_check_reports_without_raising(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    (name, passed, detail), = selfcheck._webengine()
    assert name == "embedded browser (Qt WebEngine)"
    assert isinstance(passed, bool) and isinstance(detail, str)


def test_webengine_check_fails_when_the_module_is_missing(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **kw):
        if "QtWebEngineQuick" in name or (a and a[2] and "QtWebEngineQuick" in a[2]):
            raise ImportError("no webengine")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake)
    (_, passed, detail), = selfcheck._webengine()
    assert not passed and "ImportError" in detail


def test_jpeg_check_round_trips_an_image():
    pytest.importorskip("PySide6")
    (name, passed, detail), = selfcheck._jpeg()
    assert name == "JPEG images (card backdrops)"
    assert passed, detail
