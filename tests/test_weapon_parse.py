"""Tests for the weapon text parser (lumenspar.scan.weapon_parse).

The two build_weapon cases are ground truth from real calibration screenshots.
"""

import pytest

from lumenspar.scan.weapon_parse import (
    MAX_LEVEL_BY_RARITY,
    WeaponPanelText,
    build_weapon,
    parse_level,
    parse_refinement,
)


# -- parse_level -----------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Lv. 80/90", (80, 6)),   # cap 90 is phase 6
    ("Lv. 90/90", (90, 6)),
    ("Lv. 70/70", (70, 4)),
    ("Lv. 7/0/70", (70, 4)),    # Tesseract reads the diagonal of 7 as a slash
    ("Lv. 1/20", (1, 0)),
    ("Lv. 50/40", None),        # level above the common cap
    ("Lv. 80/85", None),        # 85 is no ascension cap
    ("", None),
])
def test_parse_level(text, expected):
    assert parse_level(text) == expected


# -- parse_refinement ------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Refinement Rank 3", 3),
    ("R5", 5),
    ("[1]", 1),
    ("Rank &", 5),   # & folds to 5
    ("abc", None),
    ("9", None),     # above the refinement range
])
def test_parse_refinement(text, expected):
    assert parse_refinement(text) == expected


# -- build_weapon ----------------------------------------------------------

def test_build_weapon_ground_truth_thrilling_tales():
    pt = WeaponPanelText(name="Thrilling Tales of Dragon Slayers",
                         level="Lv. 70/70", refinement="Refinement Rank 5",
                         rarity=3, equipped="Equipped: Sucrose")
    weapon, problems = build_weapon(pt)
    assert problems == []
    assert weapon.key == "ThrillingTalesOfDragonSlayers"
    assert (weapon.level, weapon.ascension, weapon.refinement) == (70, 4, 5)
    assert weapon.location == "Sucrose"


def test_build_weapon_ground_truth_prototype_amber():
    pt = WeaponPanelText(name="Prototype Amber", level="Lv. 90/90",
                         refinement="Refinement Rank 3", rarity=4)
    weapon, problems = build_weapon(pt)
    assert problems == []
    assert weapon.key == "PrototypeAmber"
    assert (weapon.level, weapon.ascension, weapon.refinement) == (90, 6, 3)
    assert weapon.location == ""


def test_build_weapon_blank_equipped_bar_refused():
    weapon, problems = build_weapon(WeaponPanelText(
        name="Thrilling Tales of Dragon Slayers", level="Lv. 70/70",
        refinement="Refinement Rank 5", rarity=3, equipped=""))
    assert weapon is None
    assert any("equipped bar" in p for p in problems)


def test_build_weapon_unknown_name_refused():
    weapon, problems = build_weapon(WeaponPanelText(
        name="Totally Fake Weapon", level="Lv. 70/70",
        refinement="Refinement Rank 5", rarity=3))
    assert weapon is None
    assert any(p.startswith("weapon ") for p in problems)


def test_build_weapon_level_exceeds_rarity_cap():
    # A 2-star weapon cannot go beyond 70, so 90/90 is refused. (Note: 3-star
    # weapons cap at 90 in this game data, so a 3-star at 90/90 is accepted.)
    weapon, problems = build_weapon(WeaponPanelText(
        name="Iron Point", level="Lv. 90/90", refinement="Refinement Rank 5",
        rarity=2))
    assert weapon is None
    assert any("exceeds" in p and str(MAX_LEVEL_BY_RARITY[2]) in p
               for p in problems)


@pytest.mark.parametrize("equipped,traveler,wanderer,location", [
    ("Equipped: Gal", "Gal", "", "Traveler"),
    ("Gal", "Gal", "", "Traveler"),         # bare name, no "Equipped:" prefix
    ("Equipped: HatGirl", "", "HatGirl", "Wanderer"),
])
def test_build_weapon_custom_character_locations(equipped, traveler, wanderer,
                                                 location):
    weapon, problems = build_weapon(WeaponPanelText(
        name="Prototype Amber", level="Lv. 90/90", refinement="Refinement Rank 1",
        rarity=4, equipped=equipped), traveler_name=traveler, wanderer_name=wanderer)
    assert problems == []
    assert weapon.location == location


def test_build_weapon_manekin_refused():
    weapon, problems = build_weapon(WeaponPanelText(
        name="Prototype Amber", level="Lv. 90/90", refinement="R1", rarity=4,
        equipped="Equipped: galgoit"), other_names="galgoit")
    assert weapon is None
    assert any("Manekin" in p for p in problems)


def test_build_weapon_ambiguous_custom_name_refused():
    weapon, problems = build_weapon(WeaponPanelText(
        name="Prototype Amber", level="Lv. 90/90", refinement="R1", rarity=4,
        equipped="Equipped: Gal"), traveler_name="Gal", other_names="Gal1")
    assert weapon is None
    assert any("cannot be told apart" in p for p in problems)
