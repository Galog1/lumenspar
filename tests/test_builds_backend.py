"""The build cards' QML bridge: card decoration, the art queue and the CV/RV setting."""

from __future__ import annotations

import types

import pytest

pytest.importorskip("PySide6")

from lumenspar import builds, cardart  # noqa: E402
from lumenspar.ui import builds_backend as bb  # noqa: E402
from lumenspar.wishes import icons  # noqa: E402


@pytest.fixture(scope="module")
def app():
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


def _card(avatar_id="10000089", name="Furina", element="hydro", splash="UI_Gacha_AvatarImg_Furina"):
    return {"avatarId": avatar_id, "key": name, "name": name, "element": element,
            "icon": "UI_AvatarIcon_" + name, "splash": splash, "fetchedAt": 0,
            "weapon": {"icon": "UI_EquipIcon_Sword_Fin", "name": "w", "stats": []},
            "artifacts": [{"slot": "sands", "main": {"key": "atk_", "text": "46.6%", "label": "ATK%"},
                           "icon": "UI_RelicIcon_15032_4", "critValue": 10.0,
                           "subs": [{"key": "critRate_", "value": 7.8, "text": "7.8%", "rolls": 2}]}]}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Art lookups, downloads and baking pointed at a scratch folder, nothing on the network."""
    log = []

    def path(name, root=None):
        return tmp_path / f"{name}.png"

    def download(names, *a, **k):
        for n in names:
            log.append(("download", n))
            path(n).write_bytes(b"png")
        return len(list(names))

    def bake(src, dst, element):
        log.append(("bake", dst.name))
        dst.write_bytes(b"jpg")
        return True

    monkeypatch.setattr(icons, "path", path)
    monkeypatch.setattr(icons, "download", download)
    monkeypatch.setattr(cardart, "backdrop_path", lambda name, root=None: tmp_path / f"{name}.jpg")
    monkeypatch.setattr(cardart, "bake", bake)
    monkeypatch.setattr(builds, "latest", lambda: None)
    return log


def _backend(app, cards=()):
    settings = types.SimpleNamespace(card_metric="cv", saved=0)
    settings.save = lambda: setattr(settings, "saved", settings.saved + 1)
    be = bb.BuildsBackend(settings)
    by_id = {c["avatarId"]: c for c in cards}
    be._collection = types.SimpleNamespace(
        builds=by_id, ordered=lambda showcase=(): list(by_id.values()),
        wait_remaining=lambda: 0, uid="1")
    return be, settings


def test_decorate_adds_roll_values_and_art_urls(sandbox, tmp_path):
    card = bb.decorate(_card())
    assert card["rollText"].endswith("%") and card["cvText"] == "10.0"
    assert card["artifacts"][0]["subs"][0]["rvText"].endswith("%")
    assert card["bgUrl"] == "" and card["iconUrl"] == ""          # nothing cached yet
    (tmp_path / "UI_AvatarIcon_Furina.png").write_bytes(b"x")
    (tmp_path / "UI_Gacha_AvatarImg_Furina.png").write_bytes(b"x")       # the splash art
    assert bb.ensure_backdrop(_card())
    card = bb.decorate(_card())
    assert card["bgUrl"].endswith(".jpg") and card["iconUrl"].endswith("UI_AvatarIcon_Furina.png")


def test_the_traveler_is_decorated_with_art_names():
    card = bb.decorate({"avatarId": "10000007", "name": "Traveler", "element": "cryo",
                        "icon": "", "splash": "", "fetchedAt": 0, "artifacts": []})
    assert bb.backdrop_of(card).startswith("UI_Gacha_AvatarImg_PlayerGirl_cryo")
    assert "UI_Gacha_AvatarImg_PlayerGirl" in bb.art_names({"avatarId": "10000007", "icon": ""})


def test_the_selected_card_gets_its_art_first(app, sandbox, monkeypatch):
    cards = [_card("1", "Aaa", splash="S1"), _card("2", "Bbb", splash="S2"),
             _card("3", "Ccc", splash="S3")]
    be, _ = _backend(app, cards)
    started = []
    monkeypatch.setattr("threading.Thread.start", lambda self: started.append(self))
    be._want_art(cards, [])
    assert [c["splash"] for c in be._art_queue] == ["S1", "S2", "S3"]
    be.prefer("3")
    assert be._art_queue[0]["splash"] == "S3"
    assert len(be._art_queue) == 3                       # moved, not duplicated
    assert len(started) == 1                              # one worker, however often it is asked
    be._art_worker()                                      # run it here, in order
    baked = [name for kind, name in sandbox if kind == "bake"]
    assert baked[0].startswith("S3_") and len(baked) == 3
    assert be._art_running is False and be._art_queue == []


def test_cards_with_art_already_baked_are_not_queued(app, sandbox, tmp_path, monkeypatch):
    be, _ = _backend(app, [_card()])
    (tmp_path / "UI_Gacha_AvatarImg_Furina.png").write_bytes(b"x")
    assert bb.ensure_backdrop(_card())
    sandbox.clear()
    monkeypatch.setattr("threading.Thread.start", lambda self: sandbox.append("started"))
    be._want_art([_card()], [])
    be.prefer("10000089")
    assert be._art_queue == [] and sandbox == []


def test_a_failed_bake_is_not_retried_forever(app, sandbox, monkeypatch):
    be, _ = _backend(app, [_card()])
    monkeypatch.setattr(cardart, "bake", lambda *a: False)
    monkeypatch.setattr("threading.Thread.start", lambda self: None)
    be._want_art([_card()], [])
    be._art_worker()
    be._want_art([_card()], [])
    assert be._art_queue == []


def test_card_metric_is_remembered_and_validated(app):
    be, settings = _backend(app)
    seen = []
    be.metricChanged.connect(lambda: seen.append(be.cardMetric))
    assert be.cardMetric == "cv"
    be.setCardMetric("rv")
    be.setCardMetric("rv")          # no change, no extra save
    be.setCardMetric("nonsense")
    assert be.cardMetric == "rv" and settings.card_metric == "rv"
    assert settings.saved == 1 and seen == ["rv"]
    settings.card_metric = "garbage"
    assert be.cardMetric == "cv"


def test_save_dialog_suggests_and_normalises_a_png_path(app, sandbox, tmp_path):
    be, settings = _backend(app)
    settings.export_dir = str(tmp_path)
    suggested = be.defaultCardFile("Furina/../x")
    assert suggested.startswith("file://") and suggested.endswith(".png")
    assert "/cards/" in suggested and ".." not in suggested
    assert not (tmp_path / "cards").exists()                 # suggesting creates nothing
    from PySide6.QtCore import QUrl
    picked = QUrl.fromLocalFile(str(tmp_path / "mine" / "furina")).toString()
    assert be.chosenCardPath(picked) == str(tmp_path / "mine" / "furina.png")
    assert (tmp_path / "mine").is_dir()
