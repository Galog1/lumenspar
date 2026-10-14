"""Damage calculator backend: conversion, labels and the bundled GO engine."""

import pytest

from lumenspar import damage, optimizer


def _card(weapon=True):
    card = {
        "key": "Furina", "level": 90, "ascension": 6, "constellation": 2,
        "talents": [{"slot": "auto", "base": 9}, {"slot": "skill", "base": 10},
                    {"slot": "burst", "base": 11}],
        "artifacts": [{"setKey": "GoldenTroupe",
                       "main": {"key": "hp", "value": 4780},
                       "subs": [{"key": "critRate_", "value": 10.5},
                                {"key": "atk", "value": 19}]}],
    }
    if weapon:
        card["weapon"] = {"key": "SplendorOfTranquilWaters", "level": 90,
                          "ascension": 6, "refinement": 1}
    return card


def test_member_from_card():
    m = damage.member_from_card(_card())
    assert m["char"] == {"key": "Furina", "level": 90, "constellation": 2, "ascension": 6,
                         "talent": {"auto": 9, "skill": 10, "burst": 11}}
    assert m["weapon"]["key"] == "SplendorOfTranquilWaters"
    stats = m["artifacts"][0]["stats"]
    assert m["artifacts"][0]["set"] == "GoldenTroupe"
    assert stats[0] == {"key": "hp", "value": 4780}
    assert stats[1] == {"key": "critRate_", "value": pytest.approx(0.105)}
    assert stats[2] == {"key": "atk", "value": 19}


def test_member_from_card_needs_weapon():
    with pytest.raises(ValueError):
        damage.member_from_card(_card(weapon=False))


def _good():
    return {
        "characters": [
            {"key": "Furina", "level": 90, "ascension": 6, "constellation": 0,
             "talent": {"auto": 9, "skill": 9, "burst": 9}},
            {"key": "TravelerAnemo", "level": 80, "ascension": 6, "constellation": 1,
             "talent": {"auto": 6, "skill": 6, "burst": 6}},
        ],
        "weapons": [
            {"key": "SplendorOfTranquilWaters", "level": 90, "ascension": 6,
             "refinement": 1, "location": "Furina"},
            {"key": "Sword", "level": 1, "ascension": 0, "refinement": 1, "location": "Traveler"},
        ],
        "artifacts": [
            {"setKey": "GoldenTroupe", "slotKey": "circlet", "rarity": 5, "level": 20,
             "mainStatKey": "critRate_", "location": "Furina",
             "substats": [{"key": "critDMG_", "value": 14.0}, {"key": "hp", "value": 299}]},
            {"setKey": "GoldenTroupe", "slotKey": "flower", "rarity": 5, "level": 20,
             "mainStatKey": "hp", "location": "Furina", "substats": []},
            {"setKey": "Other", "slotKey": "flower", "rarity": 5, "level": 20,
             "mainStatKey": "hp", "location": "Nahida", "substats": []},
            {"setKey": "ViridescentVenerer", "slotKey": "sands", "rarity": 5, "level": 20,
             "mainStatKey": "eleMas", "location": "Traveler", "substats": []},
        ],
    }


def test_member_from_good():
    m = damage.member_from_good(_good(), "Furina")
    assert m["char"]["talent"] == {"auto": 9, "skill": 9, "burst": 9}
    assert m["weapon"]["key"] == "SplendorOfTranquilWaters"
    assert len(m["artifacts"]) == 2
    circlet = m["artifacts"][0]["stats"]
    assert circlet[0]["value"] == pytest.approx(optimizer.main_value(5, 20, "critRate_") / 100)
    assert circlet[1] == {"key": "critDMG_", "value": pytest.approx(0.14)}
    assert circlet[2] == {"key": "hp", "value": 299}


def test_member_from_good_traveler_and_missing():
    m = damage.member_from_good(_good(), "TravelerAnemo")
    assert m["weapon"]["key"] == "Sword"
    assert [a["set"] for a in m["artifacts"]] == ["ViridescentVenerer"]
    assert damage.member_from_good(_good(), "Nahida") is None
    good = _good()
    good["weapons"] = []
    assert damage.member_from_good(good, "Furina") is None


# -- labels (on the real go_labels.json) ---------------------------------------

def test_humanize_and_strip():
    assert damage.humanize("a4DeathStacks") == "A4 Death Stacks"
    assert damage.humanize("burstSerpentOver") == "Burst Serpent Over"
    assert damage.humanize("0EnergyNoBurst") == "0 Energy No Burst"
    assert damage.strip_tags("a <strong>b</strong>  c") == "a b c"


def test_cond_label():
    assert damage.cond_label("ViridescentVenerer", "swirlpyro") == "Element Swirled: Pyro"
    # no stem of {"cond"} matches: the sheet's only generic condition
    assert damage.cond_label("Azurelight", "noEnergy") == "Character has 0 energy"
    assert damage.cond_label("FinaleOfTheDeepGalleries", "0EnergyNoBurst").startswith(
        "Character has 0 energy")
    assert damage.cond_label("Skirk", "c2AfterBurst").startswith("After using Havoc: Extinction")
    assert damage.cond_label("Skirk", "a4DeathStacks") == "Death's Crossing stacks"
    assert damage.cond_label("Nobody", "c3SomeThing") == "C3: Some Thing"


def test_cond_detail_and_titles():
    assert damage.cond_detail("Skirk", "c2AfterBurst").startswith("Into the Abyss:")
    assert damage.cond_detail("reso", "nearbyDendro1") == ""
    assert damage.sheet_title("reso") == "Elemental Resonance"
    assert damage.sheet_title("static") == "Enemy & shields"
    assert damage.sheet_title("Skirk") == "Skirk"
    assert damage.sheet_kind("Skirk") == "char"
    assert damage.sheet_kind("static") == "team"
    assert damage.option_label("pyro") == "Pyro"
    assert damage.option_label("2") == "2"
    assert damage.option_label("sc") == "Stellar-Conduct"


def test_formula_label():
    assert damage.formula_label("Skirk", "normal_0", "normal") == "Normal Attack · 1-Hit DMG"
    assert damage.formula_label("Odette", "codaStellarconductDmg", "skill") == (
        "Coda at Dawn's Tolling Stellar-Conduct DMG")
    assert damage.formula_label("Skirk", "charged", "normal").startswith("Charged Attack · ")


# -- the engine ----------------------------------------------------------------

def _member():
    return {
        "char": {"key": "Furina", "level": 90, "constellation": 0, "ascension": 6,
                 "talent": {"auto": 9, "skill": 9, "burst": 9}},
        "weapon": {"key": "SplendorOfTranquilWaters", "level": 90, "ascension": 6,
                   "refinement": 1},
        "artifacts": [],
    }


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


def test_run_sync_compute(app):
    out = damage.run_sync("compute", {"members": [_member()], "only": [0],
                                      "modes": ["avg", "crit", "nonCrit"]})
    m = out["members"][0]
    assert m["stats"]["hp"] > 10000
    dmg = [f for f in m["formulas"] if f["q"] == "dmg" and f.get("nonCrit")]
    assert dmg
    assert any(f["crit"] > f["avg"] > f["nonCrit"] > 0 for f in dmg)


def test_run_sync_conditionals(app):
    out = damage.run_sync("conditionals", {"members": [_member()]})
    assert out
    assert any(c["sheet"] == "Furina" for c in out)


def test_engine_signal(app):
    from PySide6.QtCore import QEventLoop, QTimer
    eng = damage.Engine()
    got = {}
    loop = QEventLoop()
    eng.finished.connect(lambda i, r: (got.update(id=i, res=r), loop.quit()))
    eng.failed.connect(lambda i, msg: (got.update(id=i, err=msg), loop.quit()))
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(30000)
    rid = eng.request("conditionals", {"members": [_member()]})
    loop.exec()
    eng.shutdown()
    assert got.get("id") == rid
    assert "err" not in got
    assert got["res"]


def test_option_label_lunar_reactions():
    assert damage.option_label("lunarbloom") == "Lunar-Bloom"
    assert damage.option_label("lunarcharged") == "Lunar-Charged"
    assert damage.option_label("lunarcrystallize") == "Lunar-Crystallize"


def test_ascension_for():
    assert [damage.ascension_for(n) for n in (1, 20, 21, 40, 41, 50, 51, 60, 61, 70, 71, 80, 81, 90, 100)] == [
        0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 6]


def test_default_settings():
    s = damage.default_settings("Furina")
    assert s == {"level": 90, "constellation": 0, "auto": 9, "skill": 9, "burst": 9,
                 "weapon": "FavoniusSword", "weaponLevel": 90, "refinement": 1}
    assert damage.default_settings("Diluc")["weapon"] == "FavoniusGreatsword"
    assert damage.default_settings("Zhongli")["weapon"] == "FavoniusLance"
    assert damage.default_settings("Nahida")["weapon"] == "FavoniusCodex"
    assert damage.default_settings("Venti")["weapon"] == "FavoniusWarbow"
    assert damage.default_settings("TravelerAnemo")["weapon"] == "FavoniusSword"
    assert damage.default_settings("Nobody")["weapon"] == "FavoniusSword"


def test_member_from_settings():
    s = damage.default_settings("Venti")
    s.update(level=72, weaponLevel=45, refinement=3, constellation=2, burst=10)
    m = damage.member_from_settings("Venti", s)
    assert m == {
        "char": {"key": "Venti", "level": 72, "constellation": 2, "ascension": 5,
                 "talent": {"auto": 9, "skill": 9, "burst": 10}},
        "weapon": {"key": "FavoniusWarbow", "level": 45, "ascension": 2, "refinement": 3},
        "artifacts": [],
    }


def test_cond_label_survives_nested_labels():
    assert damage.cond_label("Nahida", "c2Bloom") == "Opponent is marked by Seed of Skandha"
    assert isinstance(damage.cond_label("Yanfei", "p1Seals"), str)
