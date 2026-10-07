"""Tests for the character text parser (lumenspar.scan.character_parse).

Talents are the subtle part: Genshin displays constellation-boosted values
(cyan on screen) that GOOD wants stripped back to the base level, clamped to
the ascension's talent cap.
"""

import pytest

from lumenspar.good import Character
from lumenspar.scan.character_parse import (
    TALENT_LIMITS,
    CharacterPanelText,
    base_talent,
    build_character,
    expected_boost_count,
    parse_level,
    parse_talent,
)


# -- parse_level -----------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Level 77/80", (77, 5)),
    ("Level 100 /100", (100, 6)),   # level-cap increase, still phase 6
    ("Level 95 /95", (95, 6)),
    ("Level 80 / 80", (80, 5)),
    ("Level 90-/ 90", (90, 6)),     # sparkle noise stripped
    ("Level 90 790", (90, 6)),      # loose pass: 7 read as slash
    ("Level 1007100", (100, 6)),
    ("Level 105/100", None),        # above the level cap
])
def test_parse_level(text, expected):
    assert parse_level(text) == expected


# -- parse_talent ----------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Lv. 10", 10),
    ("1O", 10),          # O folds to 0
    ("Lv. 0", None),     # below the display range
    ("16", None),        # above the display range
])
def test_parse_talent(text, expected):
    assert parse_talent(text) == expected


# -- base_talent -----------------------------------------------------------

@pytest.mark.parametrize("displayed,boosted,ascension,expected", [
    (13, True, 6, 10),       # 13 shown cyan -> strip the +3 -> 10
    (10, False, 6, 10),      # unboosted max stays 10
    (12, False, 6, 10),      # impossible unboosted value clamped to the cap
    (1, False, 0, 1),        # floor of 1
    (4, True, 0, 1),         # 4 - 3 = 1
])
def test_base_talent(displayed, boosted, ascension, expected):
    assert base_talent(displayed, boosted, ascension) == expected


def test_talent_cap_for_phase_six_is_ten():
    assert TALENT_LIMITS[6] == 10


# -- expected_boost_count --------------------------------------------------

@pytest.mark.parametrize("constellation,expected", [
    (0, 0), (1, 0), (2, 0), (3, 1), (4, 1), (5, 2), (6, 2),
])
def test_expected_boost_count(constellation, expected):
    assert expected_boost_count(constellation) == expected


# -- build_character -------------------------------------------------------

def _pt(name="Arlecchino", level="Level 80 / 90", const=0,
        talents=None, boosted=None, element=None, description=""):
    return CharacterPanelText(
        name=name, level=level, constellation=const,
        talents=talents or {"auto": "Lv. 10", "skill": "Lv. 10",
                            "burst": "Lv. 10"},
        talent_boosted=boosted or {}, element=element, description=description)


def test_build_character_traveler_gal():
    pt = _pt(name="Gal", level="Level 80 / 80", element="cryo",
             talents={"auto": "Lv. 1", "skill": "Lv. 1", "burst": "Lv. 1"})
    char, warnings = build_character(pt, traveler_name="Gal")
    assert warnings == []
    assert isinstance(char, Character)
    assert char.key == "TravelerCryo"
    assert (char.level, char.ascension) == (80, 5)
    assert char.talent == {"auto": 1, "skill": 1, "burst": 1}


def test_build_character_traveler_without_element_refused():
    char, problems = build_character(_pt(name="Gal", level="Level 80 / 80",
                                         element=None), traveler_name="Gal")
    assert char is None
    assert any("element" in p for p in problems)


def test_build_character_wanderer():
    char, problems = build_character(_pt(name="HatGirl"), wanderer_name="HatGirl")
    assert problems == []
    assert char.key == "Wanderer"


def test_build_character_arlecchino():
    char, problems = build_character(_pt())
    assert problems == []
    assert char.key == "Arlecchino"
    assert (char.level, char.ascension, char.constellation) == (80, 6, 0)
    assert char.talent == {"auto": 10, "skill": 10, "burst": 10}


def test_build_character_c3_boosts_burst_to_base_10():
    pt = _pt(const=3, talents={"auto": "Lv. 10", "skill": "Lv. 10",
                               "burst": "Lv. 13"}, boosted={"burst": True})
    char, warnings = build_character(pt)
    assert warnings == []
    assert char.talent["burst"] == 10


def test_build_character_c5_boosted_talents_strip_to_base():
    pt = _pt(const=5, talents={"auto": "Lv. 13", "skill": "Lv. 10",
                               "burst": "Lv. 13"},
             boosted={"auto": True, "burst": True})
    char, warnings = build_character(pt)
    assert warnings == []
    assert char.talent == {"auto": 10, "skill": 10, "burst": 10}


def test_build_character_boosted_13_at_phase_six_is_base_10():
    # 13 shown cyan at ascension 6 -> 13 - 3 = 10, right at the cap.
    pt = _pt(level="Level 90 / 90", const=3,
             talents={"auto": "Lv. 10", "skill": "Lv. 10", "burst": "Lv. 13"},
             boosted={"burst": True})
    char, warnings = build_character(pt)
    assert warnings == []
    assert char.talent["burst"] == 10


def test_build_character_constellation_none_refused():
    char, problems = build_character(_pt(const=None))
    assert char is None
    assert any("Constellation page" in p for p in problems)


def test_build_character_constellation_out_of_range_refused():
    char, problems = build_character(_pt(const=7))
    assert char is None
    assert any("implausible constellation" in p for p in problems)


def test_build_character_manekin_refused():
    pt = _pt(name="galgoit", description="This Manekin has chosen its own path...")
    char, problems = build_character(pt)
    assert char is None
    assert any("Manekin" in p for p in problems)


def test_build_character_ambiguous_traveler_refused():
    char, problems = build_character(_pt(name="Gal", level="Level 80 / 80",
                                         element="cryo"),
                                     traveler_name="Gal", other_names="Gal1")
    assert char is None
    assert any("cannot be told apart" in p for p in problems)


def test_build_character_unreadable_talent_refused():
    pt = _pt(talents={"auto": "", "skill": "Lv. 10", "burst": "Lv. 10"})
    char, problems = build_character(pt)
    assert char is None
    assert any("unreadable auto talent" in p for p in problems)


def test_build_character_boost_count_mismatch_warns():
    # C0 but one slot drawn as heightened: exported as displayed, with a warning.
    pt = _pt(const=0, talents={"auto": "Lv. 13", "skill": "Lv. 10",
                               "burst": "Lv. 10"}, boosted={"auto": True})
    char, warnings = build_character(pt)
    assert char is not None
    assert len(warnings) == 1
    assert "C0 should show 0 talent(s)" in warnings[0]


def test_build_character_over_cap_talent_warns():
    # Phase 5 caps talents at 8; an unboosted 9 cannot exist there.
    pt = _pt(level="Level 80 / 80", const=2,
             talents={"auto": "Lv. 8", "skill": "Lv. 9", "burst": "Lv. 8"})
    char, warnings = build_character(pt)
    assert char is not None
    assert char.talent["skill"] == 8
    assert any("ascension 5 cannot reach" in w for w in warnings)
