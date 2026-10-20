"""Build cards from an Enka.Network showcase (lumenspar/builds.py).

The showcase here is made up, but shaped exactly like Enka's responses,
including the per-roll appendPropIdList the roll counts come from.
"""

from __future__ import annotations

import json

import pytest

from lumenspar import builds
from lumenspar.wishes import icons

FURINA = 10000089


def _artifact(slot, set_id, main, main_value, subs, rolls, level=21, rarity=5):
    return {
        "itemId": 1, "reliquary": {"level": level, "mainPropId": 1, "appendPropIdList": rolls},
        "flat": {"rankLevel": rarity, "itemType": "ITEM_RELIQUARY", "equipType": slot,
                 "setId": set_id, "icon": f"UI_RelicIcon_{set_id}_4",
                 "reliquaryMainstat": {"mainPropId": main, "statValue": main_value},
                 "reliquarySubstats": [{"appendPropId": k, "statValue": v} for k, v in subs]},
    }


def _showcase():
    golden = 15032      # Golden Troupe
    arts = [
        _artifact("EQUIP_BRACER", golden, "FIGHT_PROP_HP", 4780,
                  [("FIGHT_PROP_CRITICAL", 10.5), ("FIGHT_PROP_CRITICAL_HURT", 14.0),
                   ("FIGHT_PROP_ATTACK", 19), ("FIGHT_PROP_HP_PERCENT", 4.1)],
                  # CRIT Rate x3, CRIT DMG x2, ATK x1, HP% x1 (+ one more CRIT DMG)
                  [501204, 501203, 501204, 501224, 501223, 501054, 501034, 501224]),
        _artifact("EQUIP_NECKLACE", golden, "FIGHT_PROP_ATTACK", 311,
                  [("FIGHT_PROP_CRITICAL", 3.9)], [501204]),
        _artifact("EQUIP_SHOES", golden, "FIGHT_PROP_HP_PERCENT", 46.6, [], []),
        _artifact("EQUIP_RING", golden, "FIGHT_PROP_HP_PERCENT", 46.6, [], []),
        _artifact("EQUIP_DRESS", 15031, "FIGHT_PROP_CRITICAL_HURT", 62.2,
                  [("FIGHT_PROP_ELEMENT_MASTERY", 23)], [501243], level=17),
    ]
    weapon = {"itemId": 11426, "weapon": {"level": 90, "promoteLevel": 6, "affixMap": {"111426": 0}},
              "flat": {"rankLevel": 4, "itemType": "ITEM_WEAPON", "icon": "UI_EquipIcon_Sword_Fin",
                       "weaponStats": [{"appendPropId": "FIGHT_PROP_BASE_ATTACK", "statValue": 510},
                                       {"appendPropId": "FIGHT_PROP_CHARGE_EFFICIENCY",
                                        "statValue": 45.9}]}}
    return {
        "uid": "1", "ttl": 60,
        "playerInfo": {"nickname": "Tester", "level": 60, "worldLevel": 9,
                       "finishAchievementNum": 900, "towerFloorIndex": 12, "towerLevelIndex": 3},
        "avatarInfoList": [{
            "avatarId": FURINA, "skillDepotId": 8901,
            "propMap": {"4001": {"ival": "90"}, "1002": {"ival": "6"}},
            "talentIdList": [1, 2, 3],
            "skillLevelMap": {"10891": 1, "10892": 9, "10895": 10},
            "proudSkillExtraLevelMap": {"8932": 3},      # C3: +3 Elemental Skill
            "fetterInfo": {"expLevel": 10},
            "fightPropMap": {"2000": 40000.4, "2001": 1200, "2002": 800, "28": 40,
                             "20": 0.705, "22": 2.1, "23": 1.6, "42": 0.284, "30": 0.1},
            "equipList": arts + [weapon],
        }],
    }


def test_a_showcase_becomes_a_full_build_card():
    player, cards, problems = builds.parse(_showcase())
    assert problems == [] and player["nickname"] == "Tester" and player["abyss"] == "12-3"
    (c,) = cards
    assert (c["key"], c["name"], c["element"]) == ("Furina", "Furina", "hydro")
    assert (c["level"], c["maxLevel"], c["constellation"], c["friendship"]) == (90, 90, 3, 10)
    assert [(t["slot"], t["base"], t["level"], t["boosted"]) for t in c["talents"]] == [
        ("auto", 1, 1, False), ("skill", 9, 12, True), ("burst", 10, 10, False)]
    assert c["weapon"]["name"] == "Fleuve Cendre Ferryman" and c["weapon"]["refinement"] == 1
    assert [s["text"] for s in c["weapon"]["stats"]] == ["510", "45.9%"]
    stats = {s["key"]: s["text"] for s in c["stats"]}
    # The highest DMG bonus is shown, as a percentage.
    assert stats == {"hp": "40,000", "atk": "1,200", "def": "800", "eleMas": "40",
                     "critRate_": "70.5%", "critDMG_": "210.0%", "enerRech_": "160.0%",
                     "hydro_dmg_": "28.4%"}


def test_artifacts_carry_exact_roll_counts_and_crit_value():
    _, (c,), _ = builds.parse(_showcase())
    flower = c["artifacts"][0]
    assert flower["slot"] == "flower" and flower["setName"] == "Golden Troupe"
    assert {s["key"]: s["rolls"] for s in flower["subs"]} == {
        "critRate_": 3, "critDMG_": 3, "atk": 1, "hp_": 1}
    assert flower["critValue"] == 35.0 and flower["main"]["text"] == "4,780"
    assert [a["slot"] for a in c["artifacts"]] == builds.SLOT_ORDER
    assert c["artifacts"][-1]["level"] == 16
    assert c["critValue"] == round(35.0 + 7.8, 1)
    # 4-piece Golden Troupe: both bonuses; the single circlet earns none.
    (golden,) = c["sets"]
    assert golden["count"] == 4 and len(golden["bonuses"]) == 2
    assert "<" not in "".join(golden["bonuses"])


def test_an_empty_or_hidden_showcase_explains_itself():
    data = _showcase()
    del data["avatarInfoList"]
    _, cards, problems = builds.parse(data)
    assert cards == [] and "Show Character Details" in problems[0]


def test_unknown_characters_are_reported_not_guessed():
    data = _showcase()
    data["avatarInfoList"][0]["avatarId"] = 19999999
    _, cards, problems = builds.parse(data)
    assert cards == [] and "19999999" in problems[0]


def test_the_collection_keeps_characters_across_showcases(tmp_path):
    player, cards, _ = builds.parse(_showcase())
    col = builds.Collection("123", tmp_path)
    assert col.merge(player, cards, ttl=60) == (["Furina"], [])
    assert 0 < col.wait_remaining() <= 60
    assert col.merge(player, cards, ttl=60) == ([], [])          # unchanged
    data = _showcase()
    data["avatarInfoList"][0]["propMap"]["4001"]["ival"] = "80"
    _, changed, _ = builds.parse(data)
    assert col.merge(player, changed, ttl=60) == ([], ["Furina"])
    again = builds.Collection("123", tmp_path)                   # persisted
    assert again.builds[str(FURINA)]["level"] == 80 and again.player["nickname"] == "Tester"
    assert builds.latest(tmp_path).uid == "123"
    again.remove(str(FURINA))
    assert builds.Collection("123", tmp_path).builds == {}


def test_artifact_icons_come_from_their_own_folder():
    assert icons.asset_url("UI_RelicIcon_15031_4").endswith("/UI/reliquary/UI_RelicIcon_15031_4.png")
    assert icons.asset_url("UI_AvatarIcon_Furina").endswith("/UI/UI_AvatarIcon_Furina.png")


def test_the_card_backdrop_is_baked_from_splash_art(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from lumenspar import cardart
    src, dst = tmp_path / "splash.png", tmp_path / "bg.jpg"
    img = QImage(2048, 1024, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.fillRect(1500, 100, 200, 800, QColor("#cc3344"))      # the "character", right of centre
    p.end()
    img.save(str(src))
    assert cardart.centre_of(img) == pytest.approx(1600, abs=2)
    assert cardart.bake(src, dst, "pyro")
    out = QImage(str(dst))
    assert (out.width(), out.height()) == (cardart.W, cardart.H)
    assert not dst.with_suffix(".part").exists()
    # the element's colour reaches the art area, while the stats area stays quiet and dark
    art, quiet = out.pixelColor(300, 640), out.pixelColor(cardart.W - 200, 640)
    assert art.red() > art.blue()
    assert quiet.lightness() < 60
    assert not cardart.bake(tmp_path / "missing.png", dst, "pyro")


def test_backdrops_are_named_per_splash_and_element():
    from lumenspar import cardart
    assert cardart.backdrop_name("", "pyro") == ""
    a = cardart.backdrop_name("UI_Gacha_AvatarImg_PlayerGirl", "cryo")
    b = cardart.backdrop_name("UI_Gacha_AvatarImg_PlayerGirl", "geo")
    assert a != b and a.startswith("UI_Gacha_AvatarImg_PlayerGirl_cryo")
    assert cardart.backdrop_path(a).suffix == ".jpg"


# -- roll value ------------------------------------------------------------------

def _rv_art(slot, main, subs):
    return {"slot": slot, "main": {"key": main}, "critValue": 0.0,
            "subs": [{"key": k, "value": v} for k, v in subs]}


def test_roll_value_is_a_percentage_of_the_best_roll():
    top = builds._max_rolls()
    assert builds.roll_value("critRate_", top["critRate_"]) == pytest.approx(100)
    assert builds.roll_value("critDMG_", top["critDMG_"] * 2.5) == pytest.approx(250)
    assert builds.roll_value("atk", top["atk"] * 0.7) == pytest.approx(70)
    assert builds.roll_value("heal_", 5.0) == 0          # not a substat
    assert builds.roll_value("critRate_", 0) == 0


def test_counted_stats_follow_what_the_main_stats_scale_with():
    assert builds.counted_stats([]) == ["critRate_", "critDMG_", "atk_"]
    hp = [_rv_art("sands", "hp_", []), _rv_art("goblet", "hp_", []),
          _rv_art("circlet", "critRate_", []), _rv_art("flower", "hp", [])]
    assert builds.counted_stats(hp) == ["critRate_", "critDMG_", "hp_"]
    em = [_rv_art("sands", "eleMas", []), _rv_art("goblet", "pyro_dmg_", []),
          _rv_art("circlet", "eleMas", [])]
    assert builds.counted_stats(em) == ["critRate_", "critDMG_", "eleMas"]
    er = [_rv_art("sands", "enerRech_", []), _rv_art("goblet", "atk_", [])]
    assert builds.counted_stats(er) == ["critRate_", "critDMG_", "atk_", "enerRech_"]
    # the flower and plume (always HP and ATK) never vote
    assert builds.counted_stats([_rv_art("flower", "hp", []), _rv_art("plume", "atk", [])]) \
        == ["critRate_", "critDMG_", "atk_"]


def test_with_roll_values_counts_only_what_the_build_uses():
    top = builds._max_rolls()
    card = {"artifacts": [
        {"slot": "sands", "main": {"key": "atk_"}, "critValue": 7.8,
         "subs": [{"key": "critRate_", "value": top["critRate_"]},      # 100%
                  {"key": "critDMG_", "value": top["critDMG_"]},        # 100%
                  {"key": "def", "value": top["def"]},                  # 100%, not counted
                  {"key": "atk_", "value": top["atk_"] / 2}]},          # 50%
        {"slot": "circlet", "main": {"key": "critRate_"}, "critValue": 0.0,
         "subs": [{"key": "atk_", "value": top["atk_"]}]}]}
    out = builds.with_roll_values(card)
    first, second = out["artifacts"]
    assert [s["counted"] for s in first["subs"]] == [True, True, False, True]
    assert first["subs"][2]["rvText"] == "100%"
    assert first["rollValue"] == pytest.approx(250, abs=0.2) and first["rollText"] == "250%"
    assert first["cvText"] == "7.8"
    assert out["rollValue"] == pytest.approx(350, abs=0.3) and out["rollText"] == "350%"
    assert out["cvText"] == "7.8"
    assert out["rvLabels"] == "CRIT Rate, CRIT DMG, ATK%"
    er = builds.with_roll_values({"artifacts": [_rv_art("sands", "enerRech_", [])]})
    assert er["rvLabels"] == "CRIT Rate, CRIT DMG, ATK%, ER"        # short names keep the caption on the card
    assert "rv" not in card["artifacts"][0]["subs"][0]            # the input is untouched


def test_rolls_with_a_thousand_separator():
    top = builds._max_rolls()
    card = {"artifacts": [{"slot": "flower", "main": {"key": "hp"}, "critValue": 0,
                           "subs": [{"key": "critRate_", "value": top["critRate_"] * 12.5}]}]}
    assert builds.with_roll_values(card)["rollText"] == "1,250%"


def test_the_traveler_gets_art_from_their_character_id():
    girl = builds.fill_art({"avatarId": "10000007", "icon": ""})
    assert girl["icon"] == "UI_AvatarIcon_PlayerGirl"
    assert girl["splash"] == "UI_Gacha_AvatarImg_PlayerGirl"
    assert builds.fill_art({"avatarId": "10000005", "icon": ""})["icon"] == "UI_AvatarIcon_PlayerBoy"
    known = {"avatarId": "10000089", "icon": "UI_AvatarIcon_Furina", "splash": "x"}
    assert builds.fill_art(known) is known
    unknown = {"avatarId": "99", "icon": ""}
    assert builds.fill_art(unknown) is unknown


# -- two sources for the same character --------------------------------------------

def _card(source=None, art_level=20, fetched=100, **extra):
    art = {"slot": "flower", "setKey": "GladiatorsFinale", "setName": "Gladiator's Finale",
           "level": art_level, "main": {"key": "hp", "value": 4780.0},
           "subs": [{"key": "critRate_", "value": 10.5}, {"key": "atk", "value": 39.0}]}
    card = {"avatarId": "10000120", "key": "Flins", "name": "Flins", "constellation": 2,
            "weapon": {"key": "BloodsoakedRuins", "level": 90, "refinement": 1},
            "artifacts": [art], "fetchedAt": fetched,
            "talents": [{"slot": "auto", "base": 9, "level": 9, "boosted": False}]}
    if source:
        card["source"] = source
    card.update(extra)
    return card


def _hoyolab(**kw):
    kw.setdefault("talents", [{"slot": "auto", "base": None, "level": 11, "boosted": False}])
    return _card("hoyolab", **kw)


def test_gear_signature_ignores_formatting_noise():
    a, b = _card(), _card()
    b["artifacts"][0]["main"]["value"] = 4780.04
    b["artifacts"][0]["subs"].reverse()
    assert builds.gear_signature(a) == builds.gear_signature(b)
    assert builds.gear_signature(a) != builds.gear_signature(_card(art_level=16))


def test_same_build_from_both_sources_keeps_hoyolab_card_and_enka_extras():
    enka_card = _card(fight={"2000": 18946.0}, friendship=10, fetched=200)
    hl = _hoyolab(fetched=100, level=95)
    for old, new in ((enka_card, hl), (hl, enka_card)):
        out = builds.reconcile(old, new)
        assert out["source"] == "hoyolab" and out["level"] == 95        # HoYoLAB's card
        assert out["fight"] == {"2000": 18946.0} and out["friendship"] == 10
        assert out["talents"][0]["base"] == 9                            # Enka's exact levels
        assert out["fetchedAt"] == 200


def test_different_build_is_just_the_newer_reading():
    enka_card = _card(fight={"2000": 1.0})
    hl = _hoyolab(art_level=16)
    assert builds.reconcile(enka_card, hl) is hl
    assert builds.reconcile(hl, enka_card) is enka_card
    changed = _hoyolab(constellation=3)
    assert builds.reconcile(_hoyolab(), changed) is changed


def test_hoyolab_refetch_keeps_what_enka_added():
    merged = builds.reconcile(_card(fight={"2000": 1.0}, friendship=7), _hoyolab())
    again = builds.reconcile(merged, _hoyolab(fetched=300))
    assert again["fight"] == {"2000": 1.0} and again["talents"][0]["base"] == 9
    assert again["friendship"] == 7 and again["fetchedAt"] == 300


def test_nothing_stored_means_the_new_card():
    card = _hoyolab()
    assert builds.reconcile(None, card) is card


def test_collection_merge_cards(tmp_path):
    c = builds.Collection("700000000", tmp_path)
    assert c.merge_cards([_hoyolab()]) == (["Flins"], [])
    assert c.merge_cards([_hoyolab(fetched=999)]) == ([], [])          # same build, later read
    assert c.merge_cards([_hoyolab(art_level=12)]) == ([], ["Flins"])
    c.remove("10000120")
    assert c.merge_cards([_hoyolab()]) == (["Flins"], []) and "10000120" not in c.removed
    assert builds.Collection("700000000", tmp_path).builds["10000120"]["source"] == "hoyolab"


def test_enka_merge_does_not_downgrade_a_hoyolab_card(tmp_path):
    c = builds.Collection("700000000", tmp_path)
    c.merge_cards([_hoyolab(level=95)])
    new, updated = c.merge({}, [_card(fight={"2000": 5.0}, fetched=500)], 0)
    stored = c.builds["10000120"]
    assert stored["source"] == "hoyolab" and stored["level"] == 95
    assert stored["fight"] == {"2000": 5.0} and (new, updated) == ([], ["Flins"])


# -- per-character roll value table ------------------------------------------------

def _rv_card(key):
    arts = [{"slot": "sands", "setId": "", "main": {"key": "atk_"},
             "subs": [{"key": "eleMas", "value": 40.0}, {"key": "atk_", "value": 5.0}]}]
    return {"key": key, "artifacts": arts}


def test_rv_table_overrides_rule():
    assert builds.counted_stats([], "Odette") == ["critRate_", "critDMG_", "atk_", "eleMas"]
    card = builds.with_roll_values(_rv_card("Odette"))
    assert card["artifacts"][0]["subs"][0]["counted"]
    assert "Elemental Mastery" in card["rvLabels"] or "EM" in card["rvLabels"]
    plain = builds.with_roll_values(_rv_card("NoSuchCharacter"))
    assert not plain["artifacts"][0]["subs"][0]["counted"]
    assert "EM" not in plain["rvLabels"]


def test_rv_unknown_key_falls_back():
    assert builds.counted_stats([], "Nobody") == builds.counted_stats([]) \
        == ["critRate_", "critDMG_", "atk_"]


def test_rv_table_dict_entry(monkeypatch):
    monkeypatch.setattr(builds, "_rv_table", lambda: {"X": {"stats": ["critRate_", "hp_"], "auto": True}})
    assert builds.counted_stats([], "X") == ["critRate_", "hp_"]


def test_rv_table_valid():
    table = json.loads((builds._GAMEDATA / "rv_stats.json").read_text(encoding="utf-8"))["characters"]
    keys = {c["key"] for c in json.loads(
        (builds._GAMEDATA / "characters.json").read_text(encoding="utf-8"))["items"]}
    allowed = {"hp_", "atk_", "def_", "eleMas", "enerRech_", "critRate_", "critDMG_"}
    assert table
    for key, entry in table.items():
        assert key in keys
        stats = entry["stats"] if isinstance(entry, dict) else entry
        assert stats and set(stats) <= allowed


def test_update_rv_stats_thresholds():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "update_rv_stats", Path(builds.__file__).resolve().parent.parent / "tools" / "update_rv_stats.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    crit = ["critRate_", "critDMG_"]
    assert tool.derive({"atk": 2000}) == crit + ["atk_"]
    assert tool.derive({"atk": 2000, "eleMas": 79}) == crit + ["atk_"]
    assert tool.derive({"atk": 2000, "eleMas": 80, "enerRech_": 125}) == crit + ["atk_", "eleMas", "enerRech_"]
    assert tool.derive({"atk": 900, "hp": 32000}) == crit + ["hp_"]
    assert tool.derive({"atk": 900, "def": 1600}) == crit + ["def_"]
    assert tool.derive({"atk": 1700, "hp": 32000}) == crit + ["atk_"]
    assert tool.derive({}, {"sands": "hp_", "goblet": "hp_", "circlet": "critRate_"}) == crit + ["hp_"]
