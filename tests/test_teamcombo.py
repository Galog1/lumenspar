import pytest

from lumenspar import teamcombo
from lumenspar.akasha import Hit

SKILL = "Elemental Skill · Ancient Rite: Arcane Light"
BURST = "Elemental Burst · Ancient Ritual: Cometh the Night"

HITS = [
    Hit("Northland Spearstorm Avg DMG", 2, "E", 24452.97),
    Hit("Thunderous Symphony Avg DMG", 2, "LC", 284224.0),
    Hit("Thunderous Symphony Additional Avg DMG", 2, "LC", 413408.7),
    Hit("Normal Attack 1 Avg DMG", 3, "NA", 7984.2),
    Hit("Normal Attack 2 Avg DMG", 3, "NA", 8059.6),
    Hit("Normal Attack 3 Avg DMG", 3, "NA", 9982.4),
    Hit("Normal Attack 4 Avg DMG", 6, "NA", 5719.6),
    Hit("Normal Attack 5 Avg DMG", 3, "NA", 13708.3),
    Hit("Lunar-Charged DMG (60%)", 5, "LC", 57947.4),
]

ROWS = [
    ("auto:1:0", "1-Hit DMG", "Normal Attack", 1763.7),
    ("auto:1:1", "2-Hit DMG", "Normal Attack", 1780.4),
    ("auto:1:2", "3-Hit DMG", "Normal Attack", 2205.1),
    ("auto:1:3", "4-Hit DMG", "Normal Attack", 1263.4),
    ("auto:1:4", "5-Hit DMG", "Normal Attack", 3028.3),
    ("auto:3:0", "Charged Attack DMG", "Normal Attack", 4062.8),
    ("skill:1:0", "1-Hit DMG", SKILL, 3950.7),
    ("skill:1:1", "2-Hit DMG", SKILL, 3988.0),
    ("skill:1:2", "3-Hit DMG", SKILL, 4939.4),
    ("skill:1:3", "4-Hit DMG", SKILL, 2830.0),
    ("skill:1:4", "5-Hit DMG", SKILL, 6783.3),
    ("skill:1:5", "Charged Attack DMG", SKILL, 7797.2),
    ("skill:1:6", "Northland Spearstorm DMG", SKILL, 12100.1),
    ("burst:1:0", "Initial Skill DMG", BURST, 18725.3),
    ("burst:1:1", "Middle Phase Lunar-Charged DMG", BURST, 30667.2),
    ("burst:1:2", "Final Phase Lunar-Charged DMG", BURST, 220803.8),
    ("burst:1:5", "Thunderous Symphony DMG", BURST, 134935.6),
    ("burst:1:6", "Thunderous Symphony Additional DMG", BURST, 196270.0),
    ("reaction:lunarcharged", "Lunar-Charged", "Reactions", 48563.5),
]
ROW_DICTS = [{"key": k, "label": lb, "group": g, "avg": a} for k, lb, g, a in ROWS]


def test_parse_name():
    assert teamcombo.parse_name("Lunar-Charged DMG (60%)") == ("Lunar-Charged", 0.6)
    assert teamcombo.parse_name("Normal Attack 4 Avg DMG") == ("4-Hit", 1.0)
    assert teamcombo.parse_name("Thunderous Symphony Additional Avg DMG") == \
        ("Thunderous Symphony Additional", 1.0)


def test_flins_match():
    res = teamcombo.match(HITS, ROW_DICTS)
    keys = {h["name"]: h["key"] for h in res["hits"]}
    for i in range(5):
        assert keys[f"Normal Attack {i + 1} Avg DMG"] == f"skill:1:{i}"
    assert keys["Northland Spearstorm Avg DMG"] == "skill:1:6"
    assert keys["Thunderous Symphony Avg DMG"] == "burst:1:5"
    assert keys["Thunderous Symphony Additional Avg DMG"] == "burst:1:6"
    lc = res["hits"][-1]
    assert lc["key"] == "reaction:lunarcharged"
    assert lc["factor"] == 0.6
    assert lc["value"] == pytest.approx(48563.5 * 0.6)
    assert res["missing"] == 0 and res["matched"] == 9
    assert res["total"] == pytest.approx(sum(h["total"] for h in res["hits"]))


def test_unmatched_hit():
    res = teamcombo.match([Hit("Mystery Strike", 1, "E", 100.0)], ROW_DICTS)
    h = res["hits"][0]
    assert h["key"] is None and h["value"] is None and h["total"] is None
    assert res["matched"] == 0 and res["missing"] == 1 and res["total"] == 0


def test_frames_merge():
    matched = {"hits": [
        {"key": "a", "quantity": 2, "factor": 1.0},
        {"key": "b", "quantity": 5, "factor": 0.6},
        {"key": "a", "quantity": 1, "factor": 0.5},
        {"key": None, "quantity": 9, "factor": 1.0},
    ]}
    out = teamcombo.frames(matched)
    assert out == [{"id": "a", "multiplier": 2.5}, {"id": "b", "multiplier": 3.0}]
