"""The HoYoLAB sign-in bridge: what it hands over, and what it never stores."""

import json

import pytest

from lumenspar import builds, hoyolab
from lumenspar.ui.hoyolab_backend import HoyolabBackend

from .test_hoyolab import _raw


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


def _backend():
    return HoyolabBackend(available=True)


def test_begin_validates(app):
    b = HoyolabBackend(available=False)
    assert "not available" in b.begin("700000000")
    b = _backend()
    assert "UID" in b.begin("112345678")          # a China server
    assert not b.open
    assert b.begin("700000000") == "" and b.open
    assert b.step == "login" and "Sign in" in b.status
    assert "os_euro" in b.actUrl and "700000000" in b.fetchScript


def test_begin_without_a_uid_finds_the_account_after_sign_in(app):
    b = _backend()
    assert b.begin("") == "" and b.open
    assert "role_id" not in b.actUrl and b.actUrl.startswith("https://act.hoyolab.com/")
    assert 'role_id = ""' in b.fetchScript


def test_finish_uses_the_account_the_page_found(app):
    b = _backend()
    got = []
    b.cardsReady.connect(lambda uid, cards, problems: got.append(uid))
    b.begin("")
    raw = _raw()
    raw["account"] = {"uid": "700000123", "server": "os_euro"}
    b.finish(json.dumps(raw))
    assert got == ["700000123"] and not b.open


def test_finish_ignores_a_malformed_found_account(app):
    b = _backend()
    got = []
    b.cardsReady.connect(lambda uid, cards, problems: got.append(uid))
    b.begin("700000000")
    raw = _raw()
    raw["account"] = {"uid": "1; alert(1)"}
    b.finish(json.dumps(raw))
    assert got == ["700000000"]


def test_no_account_failure_says_to_enter_the_uid(app):
    b = _backend()
    b.begin("")
    b.failed("Several accounts found (700000001, 800000002)", hoyolab.NO_ACCOUNT)
    assert "enter your UID" in b.status and "700000001" in b.status
    assert b.step == "login"


def test_cancel_closes_and_forgets(app):
    b = _backend()
    b.begin("700000000")
    b.cancel()
    assert not b.open and b.step == "login"


def test_progress_and_failure(app):
    b = _backend()
    b.begin("700000000")
    b.fetchNow()
    assert b.step == "fetching"
    b.progress(json.dumps({"done": 3, "total": 97}))
    assert "3/97" in b.status
    b.progress("not json")                         # ignored
    b.failed("Please login", 10001)
    assert b.step == "login" and "sign in" in b.status.lower() and b.open
    b.failed("boom", 5)
    assert "boom" in b.status


def test_finish_hands_over_cards_and_closes(app):
    b = _backend()
    got = []
    b.cardsReady.connect(lambda uid, cards, problems: got.append((uid, cards, problems)))
    b.begin("700000000")
    b.finish(json.dumps(_raw()))
    assert not b.open
    uid, cards, problems = got[0]
    assert uid == "700000000" and [c["name"] for c in cards] == ["Flins"] and problems == []


def test_finish_signed_out_stays_open(app):
    b = _backend()
    got = []
    b.cardsReady.connect(lambda *a: got.append(a))
    b.begin("700000000")
    b.finish(json.dumps({"list": {"retcode": 10001, "data": None}}))
    assert b.open and got == [] and "sign in" in b.status.lower()
    b.finish("{broken")
    assert b.open and got == [] and "format" in b.status


def test_nothing_written_to_disk(app, tmp_path, monkeypatch):
    monkeypatch.delenv("LUMENSPAR_HOYOLAB_DUMP", raising=False)
    monkeypatch.setattr(builds, "BUILD_DIR", tmp_path / "builds")
    before = set(tmp_path.rglob("*"))
    b = _backend()
    b.begin("700000000")
    b.finish(json.dumps(_raw()))
    assert set(tmp_path.rglob("*")) == before     # the backend itself stores nothing


def test_dump_only_when_asked(app, tmp_path, monkeypatch):
    dump = tmp_path / "dump.json"
    monkeypatch.setenv("LUMENSPAR_HOYOLAB_DUMP", str(dump))
    b = _backend()
    b.begin("700000000")
    b.finish(json.dumps(_raw()))
    assert json.loads(dump.read_text())["list"]
