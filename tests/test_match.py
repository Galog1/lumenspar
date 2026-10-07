"""Tests for the OCR vocabulary-matching layer (lumenspar.ocr.match).

The parsers lean on this layer to snap OCR'd text onto the game's known
vocabulary; these tests pin down the folding rules, the edit-distance guard
behind custom-name matching, and the fuzzy-match floors -- the "refuse rather
than guess" behaviour in its purest form.
"""

import json
from pathlib import Path

import pytest

from lumenspar.ocr import match as m

GAMEDATA = Path(__file__).resolve().parent.parent / "lumenspar" / "gamedata"


# -- normalise -------------------------------------------------------------

def test_normalise_folds_confusable_glyphs():
    # Tesseract most often swaps these pairs in the game's font.
    assert m.normalise("0") == "o"
    assert m.normalise("1") == "l"
    assert m.normalise("5") == "s"
    assert m.normalise("8") == "b"
    assert m.normalise("|") == "l"
    assert m.normalise("!") == "l"
    assert m.normalise("q") == "g"
    assert m.normalise("Qigi") == "gigi"  # the real scan that motivated "q"->"g"


def test_normalise_strips_punctuation_whitespace_and_cases():
    assert m.normalise("Gladiator's Finale") == "gladiatorsfinale"
    assert m.normalise("a-b c.") == "abc"
    assert m.normalise("  x y z  ") == "xyz"
    assert m.normalise("Lv. 70/70") == "lv7o7o"  # digits fold too (0 -> o)


# -- _within_one_edit ------------------------------------------------------

@pytest.mark.parametrize("a,b,expected", [
    ("abc", "abc", True),        # equal: zero edits is at most one
    ("abc", "axc", True),        # one glyph swap
    ("abc", "ac", True),         # one glyph dropped
    ("ac", "abc", True),         # one glyph inserted
    ("abc", "abxc", True),       # one glyph inserted in the middle
    ("abc", "ab", True),         # trailing glyph dropped
    ("abc", "axxd", False),      # two edits (swap + insert + swap)
    ("ab", "abcd", False),       # length differs by two
    ("abc", "abxy", False),      # one extra glyph and one swap = two edits
])
def test_within_one_edit(a, b, expected):
    assert m._within_one_edit(a, b) is expected


# -- custom_name -----------------------------------------------------------

def test_custom_name_blank_settings_match_nothing():
    assert m.custom_name("Gal", "", "", "") == ("", "")
    assert m.custom_name("anything", "") == ("", "")


@pytest.mark.parametrize("text,traveler,wanderer,others,role", [
    ("Gal", "Gal", "", "", "Traveler"),
    ("HatGirl", "", "HatGirl", "", "Wanderer"),
    ("Gal1", "", "", "Gal1", "other"),
])
def test_custom_name_exact_match_returns_role(text, traveler, wanderer, others, role):
    role_got, problem = m.custom_name(text, traveler, wanderer, others)
    assert role_got == role
    assert problem == ""


@pytest.mark.parametrize("text,traveler,others", [
    ("Gal", "Gal", "Gal1"),    # probe is the Traveler; Gal1 is one glyph away
    ("Gal1", "Gal", "Gal1"),   # probe is the Manekin; Gal is one glyph away
])
def test_custom_name_near_miss_is_refused(text, traveler, others):
    role, problem = m.custom_name(text, traveler_name=traveler, other_names=others)
    assert problem != ""
    # Refused entirely: neither role may win, even the exact one.
    assert "cannot be told apart" in problem


def test_custom_name_duplicate_configured_names_refused():
    role, problem = m.custom_name("Gal", traveler_name="Gal", other_names="Gal")
    assert problem != ""
    assert "normalise to" in problem


@pytest.mark.parametrize("text,kwargs", [
    ("Arlecchino", {"traveler_name": "Gal"}),
    ("", {"traveler_name": "Gal"}),
    ("   ", {"traveler_name": "Gal", "wanderer_name": "HatGirl"}),
])
def test_custom_name_unrelated_or_empty_never_matches(text, kwargs):
    assert m.custom_name(text, **kwargs) == ("", "")


# -- Vocabulary ------------------------------------------------------------

def test_characters_match_qigi_folds_to_exact_hit():
    got = m.characters().match("Qigi")
    assert got.ok
    assert got.key == "Qiqi"
    assert got.score == 100.0


def test_characters_match_exact_name_scores_100():
    got = m.characters().match("Albedo")
    assert got.ok
    assert got.name == "Albedo"
    assert got.score == 100.0


def test_characters_junk_is_rejected():
    got = m.characters().match("xxxxxxxx")
    assert not got.ok


def test_weapons_match_first_gamedata_item():
    first = json.loads((GAMEDATA / "weapons.json").read_text())["items"][0]
    got = m.weapons().match(first["name"])
    assert got.ok
    assert got.key == first["key"]
    assert got.score == 100.0


def test_near_miss_rule_accepts_below_floor_when_margin_wide():
    # A probe one glyph off "Rosaria" scores ~77 in a vocabulary whose only
    # runner-up is far behind ("Zzzzzzzzz"): between NEAR_FLOOR and the floor,
    # with a margin far wider than NEAR_MARGIN, so it is accepted.
    vocab = m.Vocabulary([
        {"key": "Rosaria", "name": "Rosaria"},
        {"key": "Zzz", "name": "Zzzzzzzzz"},
    ])
    got = vocab.match("Roxari", floor=78.0)
    assert got.ok
    assert got.key == "Rosaria"
    assert m.NEAR_FLOOR <= got.score < 78.0


def test_near_miss_rule_fires_on_real_character_names():
    # "Aixo" is a one-glyph corruption of "Aino": score 75, runner-up far
    # behind, accepted via the near-miss rule even though floor is 78.
    got = m.characters().match("Aixo")
    assert got.ok
    assert got.key == "Aino"
    assert m.NEAR_FLOOR <= got.score < 78.0


def test_locations_contain_character_keys():
    got = m.locations().match("Arlecchino")
    assert got.ok
    assert got.key == "Arlecchino"
