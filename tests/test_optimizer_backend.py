"""The optimizer page's pure helpers (no Qt application needed)."""

from lumenspar import optimizer as O
from lumenspar.ui.optimizer_backend import deltas, goal_from_qml, score_text


def _result(damage=1000.0, score=2.0) -> O.Result:
    return O.Result([], "", {}, damage, score, 0.0)


def test_goal_defaults():
    g = goal_from_qml({})
    assert (g.scaling, g.mode, g.set_key) == ("atk", "damage", "")
    assert g.ratio == ("critRate_", 1.0, "critDMG_", 2.0)
    assert g.use_equipped is True and g.min_level == 16 and g.top == 5
    assert g.extra_crit == 0.0 and g.mains == {} and g.weights == {}


def test_goal_maps_keys_and_ratio():
    g = goal_from_qml({"scaling": "hp", "mode": "ratio", "setKey": "Foo",
                       "mains": {"sands": ["atk_", "hp_"], "plume": ["atk"]},
                       "ratio": ["critRate_", 1, "critDMG_", "2"], "extraCrit": "15",
                       "useEquipped": False, "minLevel": 20.0, "top": 3})
    assert (g.scaling, g.mode, g.set_key) == ("hp", "ratio", "Foo")
    assert g.mains == {"sands": ["atk_", "hp_"]}
    assert g.ratio == ("critRate_", 1.0, "critDMG_", 2.0)
    assert g.extra_crit == 15.0 and g.use_equipped is False
    assert g.min_level == 20 and g.top == 3


def test_goal_drops_bad_numbers_and_nonpositive_targets():
    g = goal_from_qml({"weights": {"atk_": 1, "eleMas": None, "hp_": "", "def_": "x", "critDMG_": "0.5"},
                       "targets": {"critRate_": 60, "enerRech_": 0, "eleMas": -5, "hp_": None},
                       "minimums": {"hp": 20000, "def": "abc"}})
    assert g.weights == {"atk_": 1.0, "critDMG_": 0.5}
    assert g.targets == {"critRate_": 60.0}
    assert g.minimums == {"hp": 20000.0}


def test_deltas_only_changed_rows():
    before = {k: 0.0 for k in O.KEYS}
    after = dict(before)
    before.update(hp=15000, atk=1800, pyro_dmg_=15.0, critRate_=50.0)
    after.update(hp=14000, atk=1800.02, pyro_dmg_=46.6, critRate_=50.0)
    rows = deltas(before, after, "pyro")
    assert [r["label"] for r in rows] == ["Max HP", "Pyro DMG Bonus"]
    assert rows[0]["better"] is False and rows[0]["diff"] == -1000
    assert rows[1]["better"] is True
    assert rows[1]["before"] == "15.0%" and rows[1]["after"] == "46.6%"


def test_deltas_unknown_element_uses_physical():
    before = {k: 0.0 for k in O.KEYS}
    after = dict(before, physical_dmg_=25.0)
    assert [r["label"] for r in deltas(before, after, "")] == ["Physical DMG Bonus"]


def test_score_text_modes():
    r = _result(12345.6, 7.26)
    assert score_text("damage", r) == "12,346 damage estimate"
    assert score_text("weights", r) == "7.3 weighted rolls"
    assert score_text("ratio", r) == "7.3 balanced"
    assert score_text("targets", _result(score=0.0)) == "all targets met"
    assert score_text("targets", _result(score=0.126)) == "13% short of a target"
