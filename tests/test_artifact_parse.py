"""Tests for the artifact text parser (lumenspar.scan.artifact_parse).

Ground-truth expectations come from real calibration screenshots (verified by
hand against the game): the three build_artifact cases at the bottom reproduce
those panels exactly.
"""

import pytest

from lumenspar.good import SubStat
from lumenspar.scan.artifact_parse import (
    MAX_INITIAL_SUBSTATS,
    PanelText,
    build_artifact,
    parse_equipped,
    parse_level,
    parse_main_stat,
    parse_slot,
    parse_substat,
    substat_problems,
)


# -- parse_substat ---------------------------------------------------------

@pytest.mark.parametrize("line,key,value", [
    ("CRIT Rate+8.6%", "critRate_", 8.6),
    ("DEF+I7", "def", 17.0),            # I folds to 1
    ("ATK+16", "atk", 16.0),
    ("ATK+4.7%", "atk_", 4.7),
    ("Elemental Mastery+51", "eleMas", 51.0),
    ("Energy Recharge+9.1%", "enerRech_", 9.1),
    ("HP+239", "hp", 239.0),
    ("CRIT DMG+14..2%", "critDMG_", 14.2),   # doubled decimal point
    ("• CRIT DMG+7.0%", "critDMG_", 7.0),    # leading list bullet
])
def test_parse_substat(line, key, value):
    sub = parse_substat(line)
    assert sub is not None
    assert sub.key == key
    assert sub.value == value


@pytest.mark.parametrize("line", ["", "garbage here", "CRIT", "%"])
def test_parse_substat_garbage_returns_none(line):
    assert parse_substat(line) is None


# -- parse_level -----------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("+20", 20),
    ("+0", 0),
    ("+2O", 20),    # O folds to 0
    ("+25", None),  # above the artifact cap
    ("Lv 20", None),
])
def test_parse_level(text, expected):
    assert parse_level(text) == expected


# -- parse_slot ------------------------------------------------------------

@pytest.mark.parametrize("caption,expected", [
    ("Sands of Eon", "sands"),
    ("Flower of Life", "flower"),
    ("Plume of Death", "plume"),
    ("Goblet of Eonothem", "goblet"),
    ("Circlet of Logos", "circlet"),
    ("Sands of Eo", "sands"),   # fuzzy
    ("banana", None),
])
def test_parse_slot(caption, expected):
    assert parse_slot(caption) == expected


# -- parse_equipped --------------------------------------------------------

@pytest.mark.parametrize("line,expected", [
    ("Equipped: Arlecchino", "Arlecchino"),
    ("Arlecchino", None),           # no colon -> not an "equipped" line
    ("Equipped:", None),            # colon but blank name
])
def test_parse_equipped(line, expected):
    assert parse_equipped(line) == expected


# -- parse_main_stat -------------------------------------------------------

@pytest.mark.parametrize("label,value,key,number", [
    ("ATK", "46.6%", "atk_", 46.6),
    ("HP", "4,780", "hp", 4780.0),
])
def test_parse_main_stat(label, value, key, number):
    assert parse_main_stat(label, value) == (key, number)


# -- substat roll-table validation -----------------------------------------

def test_substat_problems_legal_5star_sands():
    # The real Arlecchino sands, verified against the roll table.
    subs = [SubStat("critRate_", 8.6), SubStat("critDMG_", 20.2),
            SubStat("def", 23.0), SubStat("enerRech_", 9.1)]
    assert substat_problems(subs, 5, 20) == []


def test_substat_problems_unrollable_value_flagged():
    # critRate_ 100 cannot be the sum of any 4-star rolls.
    problems = substat_problems([SubStat("critRate_", 100.0)], 4, 0)
    assert problems != []
    assert "not a value a 4-star artifact can roll" in problems[0]


def test_substat_problems_too_many_rolls_for_level():
    # Four substats at a 5-star +0, each one legal but requiring at least two
    # rolls (verified against the roll table): 8 rolls far exceeds the 4 a
    # fresh +0 can hold, so the total is impossible.
    subs = [SubStat("critRate_", 7.0), SubStat("critDMG_", 14.0),
            SubStat("def", 32.0), SubStat("enerRech_", 9.1)]
    problems = substat_problems(subs, 5, 0)
    assert problems == [
        f"substats need at least 8 rolls, but a 5-star +0 holds at most "
        f"{MAX_INITIAL_SUBSTATS[5]} (misread)"]


# -- build_artifact: ground truth ------------------------------------------

def _sands(substats=("CRIT Rate+8.6%", "CRIT DMG+20.2%", "DEF+23",
                     "Energy Recharge+9.1%"),
           set_line="Fragment of Harmonic Whimsy", equipped="Equipped: Arlecchino",
           **kwargs):
    return PanelText(slot="Sands of Eon", main_label="ATK", main_value="46.6%",
                     rarity=5, level="+20", substats=list(substats),
                     set_line=set_line, equipped=equipped, **kwargs)


def test_build_artifact_ground_truth_arlecchino_sands():
    res = build_artifact(_sands())
    assert res.ok
    art = res.artifact
    assert art.setKey == "FragmentOfHarmonicWhimsy"
    assert art.slotKey == "sands"
    assert art.level == 20
    assert art.rarity == 5
    assert art.mainStatKey == "atk_"
    assert art.location == "Arlecchino"
    assert [(s.key, s.value) for s in art.substats] == [
        ("critRate_", 8.6), ("critDMG_", 20.2), ("def", 23.0),
        ("enerRech_", 9.1)]


def test_build_artifact_ground_truth_instructor_flower():
    pt = PanelText(slot="Flower of Life", main_label="##", main_value="##",
                   rarity=4, level="+0", substats=["DEF+17", "Elemental Mastery+13"],
                   set_line="Instructor", equipped=None)
    res = build_artifact(pt)
    assert res.ok
    art = res.artifact
    assert art.setKey == "Instructor"
    assert art.slotKey == "flower"
    assert art.level == 0
    assert art.mainStatKey == "hp"   # forced by slot, main label is garbage
    assert [s.key for s in art.substats] == ["def", "eleMas"]


def test_build_artifact_ground_truth_scarlet_proof_plume():
    pt = PanelText(slot="Plume of Death", main_label="!!", main_value="!!",
                   rarity=5, level="+0",
                   substats=["CRIT Rate+3.1%", "CRIT DMG+7.0%", "HP+239"],
                   set_line="Scarlet Proof", equipped=None)
    res = build_artifact(pt)
    assert res.ok
    art = res.artifact
    assert art.setKey == "ScarletProof"
    assert art.slotKey == "plume"
    assert art.mainStatKey == "atk"   # forced by slot
    assert art.location == ""


# -- build_artifact: equipped-bar handling ----------------------------------

def test_build_artifact_blank_equipped_bar_refused():
    res = build_artifact(_sands(equipped=""))
    assert not res.ok
    assert any("equipped bar" in p for p in res.problems)


def test_build_artifact_traveler_equipped():
    res = build_artifact(_sands(equipped="Equipped: Gal"), traveler_name="Gal")
    assert res.ok
    assert res.artifact.location == "Traveler"


def test_build_artifact_traveler_ambiguous_refused():
    res = build_artifact(_sands(equipped="Equipped: Gal"),
                         traveler_name="Gal", other_names="Gal1")
    assert not res.ok
    assert any("cannot be told apart" in p for p in res.problems)


def test_build_artifact_manekin_refused():
    res = build_artifact(_sands(equipped="Equipped: galgoit"), other_names="galgoit")
    assert not res.ok
    assert any("Manekin" in p and "GOOD" in p for p in res.problems)


def test_build_artifact_wanderer_equipped():
    res = build_artifact(_sands(equipped="Equipped: HatGirl"),
                         wanderer_name="HatGirl")
    assert res.ok
    assert res.artifact.location == "Wanderer"


# -- build_artifact: substat lines and set line ------------------------------

def test_build_artifact_unactivated_substat_skipped():
    res = build_artifact(_sands(substats=(
        "CRIT Rate+8.6%", "CRIT DMG+20.2% (unactivated)", "DEF+23",
        "Energy Recharge+9.1%")))
    assert res.ok
    assert [s.key for s in res.artifact.substats] == [
        "critRate_", "def", "enerRech_"]


def test_build_artifact_unknown_set_refused():
    res = build_artifact(_sands(set_line="Not A Real Set"))
    assert not res.ok
    assert any(p.startswith("set ") for p in res.problems)
