"""The optimizer page's pure helpers (no Qt application needed)."""

from types import SimpleNamespace

from lumenspar import optimizer as O
from lumenspar.ui.optimizer_backend import (akasha_info, deltas, four_piece, goal_from_qml, merge_results,
                                            same_build, score_text, top1_targets)


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


def test_score_text_akasha():
    assert score_text("akasha", _result(score=123456.7)) == "Akasha ≈ 123,457"


def test_four_piece():
    four = {"artifacts": [{"setKey": "GoldenTroupe"}] * 4 + [{"setKey": "Other"}]}
    split = {"artifacts": [{"setKey": "GoldenTroupe"}] * 2 + [{"setKey": "Other"}] * 2}
    assert four_piece(four) == "GoldenTroupe"
    assert four_piece(split) == ""
    assert four_piece({"artifacts": []}) == ""


def test_same_build():
    card = {"artifacts": [{"setKey": "GoldenTroupe"}] * 4 + [{"setKey": "EmblemOfSeveredFate"}]}
    match = {"Golden Troupe": 4, "Emblem of Severed Fate": 1, "Other": 0}
    other = {"Golden Troupe": 2, "Emblem of Severed Fate": 3}
    assert same_build(card, match) is True
    assert same_build(card, other) is False
    assert same_build(card, {}) is False


def test_top1_targets_atk():
    stats = {"critRate_": 70.123, "critDMG_": 150.46, "atk": 2345.6, "enerRech_": 110.04,
             "eleMas": 306.2, "hp": 20000}
    targets, keys = top1_targets(stats, "atk")
    assert keys == ["critRate_", "critDMG_", "atk", "enerRech_", "eleMas"]
    assert targets == {"critRate_": 70.1, "critDMG_": 150.5, "atk": 2346,
                       "enerRech_": 110.0, "eleMas": 306}


def test_top1_targets_hp_without_er_em():
    stats = {"critRate_": 60.0, "critDMG_": 120.0, "hp": 40000.4, "enerRech_": 100.0, "eleMas": 0}
    targets, keys = top1_targets(stats, "hp")
    assert keys == ["critRate_", "critDMG_", "hp"]
    assert targets["hp"] == 40000


def test_top1_targets_elemas_once():
    stats = {"critRate_": 50.0, "critDMG_": 100.0, "eleMas": 900.4, "enerRech_": 100.0}
    targets, keys = top1_targets(stats, "eleMas")
    assert keys == ["critRate_", "critDMG_", "eleMas"]
    assert targets["eleMas"] == 900


def test_top1_targets_offsets_shift_to_panel_scale():
    stats = {"critRate_": 70.123, "critDMG_": 150.46, "atk": 2345.6, "enerRech_": 110.04,
             "eleMas": 306.2}
    targets, keys = top1_targets(stats, "atk", {"atk": 337.0, "critRate_": -3.04, "critDMG_": 10.0})
    assert keys == ["critRate_", "critDMG_", "atk", "enerRech_", "eleMas"]
    assert targets == {"critRate_": 67.1, "critDMG_": 160.5, "atk": 2683,
                       "enerRech_": 110.0, "eleMas": 306}
    assert top1_targets(stats, "atk", None) == top1_targets(stats, "atk", {})


def _piece(i):
    return SimpleNamespace(id=i)


def _res(ids, score):
    return SimpleNamespace(pieces=[_piece(i) for i in ids], score=score)


def test_merge_results_dedupes_orders_and_trims():
    a, b, c, d = _res([1, 2], 5.0), _res([3, 4], 9.0), _res([1, 2], 7.0), _res([5, 6], 1.0)
    merged = merge_results([a, b, c, d], 3)
    assert merged == [b, c, d]
    assert merge_results([a, b, c, d], 2) == [b, c]
    assert merge_results([], 5) == []


def test_akasha_info_text():
    model = SimpleNamespace(n=180, rms=0.012)
    sets = [("A", 0.62), ("B", 0.25), ("C", 0.08), ("D", 0.05)]
    mains = {"sands": [("atk_", 0.8), ("enerRech_", 0.2)], "goblet": [("pyro_dmg_", 0.9)],
             "circlet": []}
    names = {"A": "Alpha", "B": "Beta"}
    text = akasha_info(model, sets, mains, True, names)
    assert "from 180 builds" in text and "within about 1.2%" in text
    assert "Calibrated on your build's Akasha result." in text
    assert "Alpha 62%, Beta 25%, C 8%" in text and "D 5%" not in text
    assert "sands ATK%/Energy Recharge" in text and "goblet Pyro DMG Bonus" in text
    assert "circlet" not in text
    assert "rough" not in text
    plain = akasha_info(model, sets, mains, False, names)
    assert "not calibrated" in plain and "Calibrated on" not in plain
    rough = akasha_info(SimpleNamespace(n=100, rms=0.05), sets, mains, False, names)
    assert "treat the ranks as rough" in rough
