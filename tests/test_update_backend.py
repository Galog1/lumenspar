"""The update bridge: when it speaks up, what it refuses, what it hands over."""

import hashlib
import io
import time
from pathlib import Path

import pytest

from lumenspar import updater
from lumenspar.config import Settings
from lumenspar.ui.update_backend import UpdateBackend

BASE = "https://github.com/Galog1/lumenspar/releases/download/v9.0.0"
NEW = "9.0.0"


SAVES = []


@pytest.fixture(autouse=True)
def _never_write_the_real_config(monkeypatch):
    SAVES.clear()
    monkeypatch.setattr(Settings, "save", lambda self, path=None: SAVES.append(self.check_updates))


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


def _payload(version=NEW, data=b"installer"):
    return [{"tag_name": f"v{version}", "draft": False, "prerelease": True, "body": "Notes",
             "html_url": f"https://github.com/Galog1/lumenspar/releases/tag/v{version}",
             "assets": [{"name": f"Lumenspar-Setup-{version}.exe", "size": len(data),
                         "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                         "browser_download_url": f"{BASE}/Lumenspar-Setup-{version}.exe"}]}]


class _Resp:
    def __init__(self, data):
        self._b, self.headers = io.BytesIO(data), {"Content-Length": str(len(data))}

    def read(self, n):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _backend(tmp_path, payload=None, blocker=lambda: "", installed="windows", data=b"installer",
             monkeypatch=None):
    s = Settings()
    quits = []
    b = UpdateBackend(s, fetch=lambda url: _payload() if payload is None else payload,
                      opener=lambda req, timeout=0: _Resp(data), blocker=blocker,
                      installed_as=lambda: installed, quit_app=lambda: quits.append(1))
    b.quits = quits
    return b


def _wait(app, cond, seconds=5):
    end = time.time() + seconds
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    return cond()


def _checked(app, b, quiet=False):
    b.check(quiet=quiet)
    assert _wait(app, lambda: b.state == "idle")


def test_a_newer_release_is_announced(app, tmp_path):
    b = _backend(tmp_path)
    _checked(app, b)
    assert b.available and b.showBanner and b.latestVersion == NEW and b.notes == "Notes"
    assert b.canInstall and NEW in b.status


def test_current_or_older_is_not_an_update(app, tmp_path):
    b = _backend(tmp_path, payload=_payload("0.0.1"))
    _checked(app, b)
    assert not b.available and not b.showBanner and "up to date" in b.status
    b = _backend(tmp_path, payload=[])
    _checked(app, b)
    assert not b.available


def test_a_quiet_check_that_fails_says_nothing(app, tmp_path):
    b = _backend(tmp_path)
    b._fetch = lambda url: (_ for _ in ()).throw(updater.UpdateError("Could not reach GitHub"))
    _checked(app, b, quiet=True)
    assert b.status == "" and not b.available
    _checked(app, b, quiet=False)
    assert "Could not reach" in b.status


def test_a_quiet_check_with_nothing_new_says_nothing(app, tmp_path):
    b = _backend(tmp_path, payload=_payload("0.0.1"))
    _checked(app, b, quiet=True)
    assert b.status == ""


def test_later_hides_the_banner_but_keeps_the_update(app, tmp_path):
    b = _backend(tmp_path)
    _checked(app, b)
    b.dismiss()
    assert b.available and not b.showBanner
    assert b.canInstall                     # the menu button still works


def test_source_installs_cannot_update_themselves(app, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("lumenspar.ui.update_backend.QDesktopServices.openUrl",
                        lambda url: opened.append(url.toString()))
    b = _backend(tmp_path, installed="source")
    _checked(app, b)
    assert b.available and not b.canInstall
    b.install()
    assert opened and "releases" in opened[0] and b.state == "idle"


def test_install_is_refused_while_a_scan_runs(app, tmp_path):
    b = _backend(tmp_path, blocker=lambda: "a scan is running")
    _checked(app, b)
    b.install()
    assert b.state == "idle" and "scan is running" in b.status and not b.quits


def test_install_downloads_installs_and_quits(app, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "work_dir", lambda: tmp_path)
    started = []
    monkeypatch.setattr(updater, "apply_windows", lambda path: started.append(Path(path)))
    monkeypatch.setattr("lumenspar.ui.update_backend.QTimer.singleShot",
                        lambda ms, fn: fn())
    b = _backend(tmp_path)
    _checked(app, b)
    b.install()
    assert b.state == "downloading"
    assert _wait(app, lambda: b.quits)
    assert started and started[0].read_bytes() == b"installer"
    assert b.state == "installing"


def test_a_corrupt_download_is_not_installed(app, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "work_dir", lambda: tmp_path)
    started = []
    monkeypatch.setattr(updater, "apply_windows", lambda path: started.append(path))
    b = _backend(tmp_path, data=b"tampered")        # digest was made for b"installer"
    _checked(app, b)
    b.install()
    assert _wait(app, lambda: b.state == "idle")
    assert "incomplete" in b.status or "checksum" in b.status
    assert not started and not b.quits and not list(tmp_path.glob("Lumenspar-Setup-*"))


def test_a_scan_started_during_the_download_stops_the_install(app, tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "work_dir", lambda: tmp_path)
    started = []
    monkeypatch.setattr(updater, "apply_windows", lambda path: started.append(path))
    flag = {"busy": False}
    b = _backend(tmp_path, blocker=lambda: "a scan is running" if flag["busy"] else "")
    _checked(app, b)
    b.install()
    flag["busy"] = True
    assert _wait(app, lambda: b.state == "idle" and "scan is running" in b.status)
    assert not started and not b.quits


def test_auto_check_setting_is_saved(app, tmp_path):
    s = Settings()
    b = UpdateBackend(s, fetch=lambda url: [])
    assert b.autoCheck is True
    b.autoCheck = False
    assert s.check_updates is False and SAVES == [False]
    assert not b._timer.isActive()
    b.autoCheck = True
    assert SAVES == [False, True]


def test_no_automatic_checks_in_the_headless_self_check(app, monkeypatch):
    monkeypatch.setenv("LUMENSPAR_SMOKE_TEST", "x")
    calls = []
    b = UpdateBackend(Settings(), fetch=lambda url: calls.append(url) or [])
    b.start()
    assert not b._timer.isActive() and not calls


def test_check_updates_defaults_on_and_old_configs_load():
    assert Settings().check_updates is True
    assert Settings.load(Path("does-not-exist.json")).check_updates is True
