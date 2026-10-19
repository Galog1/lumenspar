"""HoYoLAB character import: the in-page script and parsing of its result."""

import json
from pathlib import Path

import pytest

from lumenspar import builds, hoyolab

QML = Path(__file__).resolve().parents[1] / "lumenspar" / "ui" / "qml"


def _set(name):
    return next(s for s in builds._items("artifact_sets.json", "id").values() if s["name"] == name)


def _weapon(name):
    return next(w for w in builds._items("weapons.json", "id").values() if w["name"] == name)


def _relic(pos, set_, main, subs, level=20):
    return {"id": 100 + pos, "pos": pos, "rarity": 5, "level": level,
            "set": {"id": set_["id"], "name": set_["name"]},
            "main_property": {"property_type": main[0], "value": main[1], "times": 0},
            "sub_property_list": [{"property_type": t, "value": v, "times": n}
                                  for t, v, n in subs]}


def _raw(relics=None, retcode=0):
    night = _set("Night of the Sky's Unveiling")
    ruins = _weapon("Bloodsoaked Ruins")
    relics = relics if relics is not None else [
        _relic(1, night, (2, "4,780"), [(20, "10.5%", 3), (22, "21.8%", 1), (5, "39", 1)]),
        _relic(5, night, (22, "62.2%"), [(20, "7.0%", 2), (6, "16.3%", 2), (2, "209", 1)]),
    ]
    return {
        "list": {"retcode": retcode, "data": {"list": [
            {"id": 10000120, "name": "Flins", "element": "Electro", "level": 95,
             "rarity": 5, "actived_constellation_num": 6}]}},
        "details": {"10000120": {"data": {"list": [{
            "base": {"id": 10000120, "level": 95, "element": "Electro", "rarity": 5},
            "weapon": {"id": ruins["id"], "name": "Bloodsoaked Ruins", "level": 90,
                       "promote_level": 6, "affix_level": 2, "rarity": 5,
                       "main_property": {"property_type": 4, "value": "674"},
                       "sub_property": {"property_type": 20, "value": "22.1%"}},
            "relics": relics,
            "constellations": [{"is_actived": True}] * 6,
            "skills": [{"skill_type": 1, "level": 9}, {"skill_type": 1, "level": 12},
                       {"skill_type": 1, "level": 13}, {"skill_type": 2, "level": 1}],
            "selected_properties": [
                {"property_type": 2000, "final": "18,946"}, {"property_type": 2001, "final": "2,645"},
                {"property_type": 2002, "final": "907"}, {"property_type": 28, "final": "127"},
                {"property_type": 20, "final": "70.6%"}, {"property_type": 22, "final": "236.8%"},
                {"property_type": 23, "final": "100.0%"}, {"property_type": 41, "final": "20.0%"}],
        }]}}},
        "errors": {},
    }


def test_server_for():
    assert hoyolab.server_for("700000000") == "os_euro"
    assert hoyolab.server_for("612345678") == "os_usa"
    assert hoyolab.server_for("812345678") == "os_asia"
    assert hoyolab.server_for("912345678") == "os_cht"
    assert hoyolab.server_for("112345678") is None      # a China server
    assert hoyolab.server_for("7000") is None and hoyolab.server_for("") is None
    assert "role_id=700000000&server=os_euro" in hoyolab.page_url("700000000", "os_euro")


def test_fetch_script_embeds_the_request_safely():
    js = hoyolab.fetch_script("700000000", "os_euro")
    assert '"700000000"' in js and '"os_euro"' in js
    assert "character/list" in js and "character/detail" in js
    # a hostile uid is a string literal, never code
    assert '"1; alert(1)"' in hoyolab.fetch_script("1; alert(1)", "os_euro")


def test_scripts_never_touch_credentials():
    js = hoyolab.fetch_script("700000000", "os_euro") + hoyolab.PROGRESS_JS + hoyolab.RESULT_JS
    for forbidden in ("document.cookie", "localStorage", "sessionStorage", "indexedDB",
                      "password", "type=\"password\"", "querySelector"):
        assert forbidden not in js


def test_parse_builds_a_card():
    cards, problems = hoyolab.parse(_raw())
    assert problems == [] and len(cards) == 1
    c = cards[0]
    assert (c["key"], c["name"], c["element"], c["source"]) == ("Flins", "Flins", "electro", "hoyolab")
    assert (c["level"], c["constellation"], c["avatarId"]) == (95, 6, "10000120")
    assert c["weapon"]["key"] == "BloodsoakedRuins"
    assert (c["weapon"]["level"], c["weapon"]["ascension"], c["weapon"]["refinement"]) == (90, 6, 2)
    assert [s["text"] for s in c["weapon"]["stats"]] == ["674", "22.1%"]
    assert [a["slot"] for a in c["artifacts"]] == ["flower", "circlet"]
    flower = c["artifacts"][0]
    assert flower["setKey"] == "NightOfTheSkysUnveiling" and flower["level"] == 20
    assert flower["main"]["key"] == "hp" and flower["main"]["value"] == 4780
    assert [(s["key"], s["value"], s["rolls"]) for s in flower["subs"]] == [
        ("critRate_", 10.5, 3), ("critDMG_", 21.8, 1), ("atk", 39.0, 1)]
    assert flower["icon"].startswith("UI_RelicIcon_") and flower["icon"].endswith("_4")
    assert flower["critValue"] == pytest.approx(2 * 10.5 + 21.8, abs=0.05)
    assert [t["level"] for t in c["talents"]] == [9, 12, 13]       # skill_type 1 only
    assert all(t["base"] is None for t in c["talents"])
    stats = {s["key"]: s["text"] for s in c["stats"]}
    assert stats["hp"] == "18,946" and stats["critRate_"] == "70.6%"
    assert stats["electro_dmg_"] == "20.0%"
    assert c["critValue"] == pytest.approx(sum(a["critValue"] for a in c["artifacts"]), abs=0.05)
    assert c["icon"] and c["splash"].startswith("UI_Gacha_AvatarImg_")


def test_parse_set_by_name_when_the_id_differs():
    raw = _raw()
    for r in raw["details"]["10000120"]["data"]["list"][0]["relics"]:
        r["set"]["id"] = 424242
    card = hoyolab.parse(raw)[0][0]
    assert all(a["setKey"] == "NightOfTheSkysUnveiling" for a in card["artifacts"])


def test_parse_character_without_artifacts():
    card = hoyolab.parse(_raw(relics=[]))[0][0]
    assert card["artifacts"] == [] and card["sets"] == [] and card["critValue"] == 0


def test_parse_reports_unusable_characters():
    raw = _raw()
    raw["list"]["data"]["list"].append({"id": 99999999, "name": "Newcomer", "element": "Pyro"})
    raw["details"]["99999999"] = raw["details"]["10000120"]
    raw["list"]["data"]["list"].append({"id": 10000121, "name": "Aino", "element": "Hydro"})
    raw["errors"]["10000121"] = "boom"
    cards, problems = hoyolab.parse(raw)
    assert [c["name"] for c in cards] == ["Flins"]
    assert any("Newcomer" in p for p in problems) and any("Aino" in p for p in problems)


def test_parse_signed_out_and_empty():
    with pytest.raises(hoyolab.HoyolabError) as e:
        hoyolab.parse({"list": {"retcode": 10001, "message": "Please login", "data": None}})
    assert e.value.signed_out
    with pytest.raises(hoyolab.HoyolabError) as e:
        hoyolab.parse({"list": {"retcode": 0, "data": {"list": []}}, "details": {}})
    assert not e.value.signed_out


def test_parse_traveler_by_element():
    raw = _raw()
    row = raw["list"]["data"]["list"][0]
    row.update(id=10000007, name="Lumine", element="Anemo")
    raw["details"] = {"10000007": raw["details"]["10000120"]}
    raw["details"]["10000007"]["data"]["list"][0]["base"].update(id=10000007, element="Anemo")
    assert hoyolab.parse(raw)[0][0]["key"] == "TravelerAnemo"


def test_parse_is_json_round_trippable():
    cards, _ = hoyolab.parse(json.loads(json.dumps(_raw())))
    json.dumps(cards)


# -- the sign-in window keeps nothing ----------------------------------------------

def test_sign_in_window_is_off_the_record_and_persists_nothing():
    qml = (QML / "HoyolabWindow.qml").read_text(encoding="utf-8")
    assert "offTheRecord: true" in qml
    for persistent in ("storageName", "persistentStoragePath", "persistentCookiesPolicy",
                       "cachePath", "offTheRecord: false", "httpCacheType"):
        assert persistent not in qml
    # the window never reads credentials or page storage
    for forbidden in ("document.cookie", "localStorage", "sessionStorage", "password"):
        assert forbidden not in qml.replace("Your password goes", "")


def test_every_web_view_uses_the_off_the_record_profile():
    """A view without an explicit profile falls back to Qt's default one, and a
    popup on another profile cannot adopt the page's popup request (the security
    check then hangs). `profile: profile` would resolve to the view's own property,
    so the shared profile has its own id."""
    qml = (QML / "HoyolabWindow.qml").read_text(encoding="utf-8")
    assert qml.count("WebEngineView {") == qml.count("profile: otrProfile") >= 2
    assert "id: otrProfile" in qml
    assert "profile: profile" not in qml


def test_sign_in_popups_keep_their_opener():
    """HoYoLAB's security check and social logins open popups that answer through
    window.opener; forcing them into the main view destroys the opener and the
    page waits forever."""
    qml = (QML / "HoyolabWindow.qml").read_text(encoding="utf-8")
    assert "openIn(web)" not in qml
    assert qml.count("request.openIn(popup.view)") >= 2   # main view and nested popups
    assert "onWindowCloseRequested" in qml


def test_no_other_qml_creates_a_web_profile():
    for f in QML.rglob("*.qml"):
        if f.name != "HoyolabWindow.qml":
            text = f.read_text(encoding="utf-8")
            assert "WebEngine" not in text and "QtWebEngine" not in text, f.name
