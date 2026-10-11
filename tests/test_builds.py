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


def test_the_splash_panel_is_cut_to_the_card_with_rounded_corners(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QColor, QImage
    from lumenspar.ui import builds_backend as bb
    src, dst = tmp_path / "splash.png", tmp_path / "panel.png"
    img = QImage(2048, 1024, QImage.Format_RGB32)
    img.fill(QColor("#336699"))
    img.save(str(src))
    assert bb.make_panel(src, dst)
    out = QImage(str(dst))
    assert (out.width(), out.height()) == (bb.PANEL_W, bb.PANEL_H)
    assert out.pixelColor(0, 0).alpha() == 0                   # rounded corner
    assert out.pixelColor(bb.PANEL_W - 1, 0).alpha() == 255      # square on the right
    assert out.pixelColor(400, 600).name() == "#336699"
    assert not bb.make_panel(tmp_path / "missing.png", dst)
