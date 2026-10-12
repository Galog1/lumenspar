"""The artifact optimizer: set/weapon text parsing, the base character, the search."""

from __future__ import annotations

import json

import numpy as np
import pytest

from lumenspar import optimizer as opt
from lumenspar import passives

ATK_SET = "GladiatorsFinale"     # 2pc: ATK +18%.
OTHER_SET = "NoblesseOblige"     # 2pc: a conditional damage bonus, no stats
ATK_SET_ID = "15001"

MAINS = {"flower": ("hp", 4780), "plume": ("atk", 311), "sands": ("atk_", 46.6),
         "goblet": ("pyro_dmg_", 46.6), "circlet": ("critDMG_", 62.2)}


def art(set_key, slot, main=None, subs=(), loc="", level=20):
    key, _ = main or MAINS[slot]
    return {"setKey": set_key, "slotKey": slot, "rarity": 5, "level": level,
            "mainStatKey": key, "substats": [{"key": k, "value": v} for k, v in subs],
            "location": loc}


def make_base(**stats):
    vec = np.zeros(opt.D)
    for k, v in stats.items():
        vec[opt.IDX[k]] = v
    return opt.Base(300.0, 300.0, 600.0, vec)


def run(good, base, goal, cond=0.0):
    return opt.search(opt.load_pieces(good), base, "pyro", goal, lambda s: cond)


def full_set(**extra):
    """One G piece per slot, no crit anywhere."""
    return [art(ATK_SET, s, **extra) for s in opt.SLOTS]


def test_static_2pc_and_conditional_crit_texts():
    assert passives.set_static_2pc(ATK_SET) == {"atk_": 18.0}
    total = lambda t: sum(v for v, _ in passives.conditional_crit(t))
    assert total("When current HP increases or decreases, CRIT Rate will be increased by "
                 "12% for 5s. Max 3 stacks.") == 36
    assert total("When a character attacks an opponent affected by Cryo, their CRIT Rate is "
                 "increased by 20%. If the opponent is Frozen, CRIT Rate is increased by an "
                 "additional 20%.") == 40
    assert total("Moonsign: Increases CRIT Rate by 15%/30% when the party's Moonsign is "
                 "Nascent Gleam/Ascendant Gleam.") == 30
    assert passives.conditional_crit("CRIT Rate +12%") == []
    assert passives.clean("<color=#99FFFFFF>8%</color>") == "8%"


def test_weapon_passive_is_cached_and_never_raises(tmp_path):
    body = json.dumps({"data": {"affix": {"1": {"upgrade": {
        "0": "R1 text", "4": "R5 <color=#fff>text</color>"}}}}}).encode()

    def boom(url):
        raise OSError("offline")

    assert passives.weapon_passive("1", 5, lambda url: body, tmp_path) == "R5 text"
    assert passives.weapon_passive("1", 5, boom, tmp_path) == "R5 text"
    assert passives.weapon_passive("2", 1, fetch=boom, root=tmp_path) == ""


def test_base_from_card_removes_equipped_artifacts_and_set_bonus():
    def equipped(slot, key, value, subs=()):
        return {"slot": slot, "setKey": ATK_SET, "main": {"key": key, "value": value},
                "subs": [{"key": k, "value": v} for k, v in subs]}

    card = {
        "fight": {"1": 10000, "2": 4780, "3": 0, "4": 800, "5": 311, "6": 0.18 + 0.466,
                  "7": 600, "20": 0.05 + 0.10, "22": 0.5 + 0.622, "23": 1.0, "28": 0,
                  "42": 0.466},
        "artifacts": [equipped("flower", "hp", 4780, [("critRate_", 10)]),
                      equipped("plume", "atk", 311),
                      equipped("sands", "atk_", 46.6),
                      equipped("goblet", "hydro_dmg_", 46.6),
                      equipped("circlet", "critDMG_", 62.2)],
    }
    base = opt.base_from_card(card)
    assert (base.hp, base.atk, base.defense) == (10000, 800, 600)
    v = lambda k: base.vec[opt.IDX[k]]
    assert v("atk_") == pytest.approx(0)
    assert v("atk") == pytest.approx(0)
    assert v("hp") == pytest.approx(0)
    assert v("critRate_") == pytest.approx(5)
    assert v("critDMG_") == pytest.approx(50)
    assert v("hydro_dmg_") == pytest.approx(0)
    assert v("enerRech_") == pytest.approx(100)
    with pytest.raises(ValueError):
        opt.base_from_card({"artifacts": []})


def test_search_finds_the_best_four_piece_plus_off_piece():
    good = {"artifacts": [
        art(ATK_SET, "flower", subs=[("def", 20)]),                                   # 0
        art(ATK_SET, "plume", subs=[("critRate_", 10.5), ("critDMG_", 14)]),          # 1
        art(ATK_SET, "sands", subs=[("critDMG_", 21)]),                               # 2
        art(ATK_SET, "goblet", subs=[("critRate_", 7.8), ("atk_", 5.8)]),             # 3
        art(ATK_SET, "circlet", main=("critDMG_", 62.2), subs=[("critRate_", 3.9), ("atk", 19)]),  # 4
        art(OTHER_SET, "flower", subs=[("critRate_", 10.5), ("atk_", 9.9), ("atk", 33)]),  # 5
        art(ATK_SET, "plume", subs=[("hp", 100)]),                                    # 6 weaker
        art(ATK_SET, "sands", subs=[("critDMG_", 90)], level=4),                      # 7 too low
        art(OTHER_SET, "flower", subs=[("hp", 50)]),                                  # 8 weaker
    ]}
    base = make_base(critRate_=5, critDMG_=50)
    res = run(good, base, opt.Goal(set_key=ATK_SET, top=3))
    best = res[0]
    assert [p.id for p in best.pieces] == [5, 1, 2, 3, 4]
    assert best.set_key == ATK_SET
    assert all(7 not in [p.id for p in r.pieces] for r in res)
    atk_pct = 18 + 46.6 + 5.8 + 9.9
    atk_flat = 311 + 19 + 33
    assert best.stats["atk"] == pytest.approx(300 * (1 + atk_pct / 100) + atk_flat)
    assert best.damage > res[-1].damage or len(res) == 1


def test_crit_above_the_cap_is_worthless():
    good = {"artifacts": full_set()[:4] + [
        art(ATK_SET, "circlet", main=("critRate_", 31.1)),     # 4
        art(ATK_SET, "circlet", main=("critDMG_", 62.2)),      # 5
    ]}
    base = make_base(critRate_=70, critDMG_=50)
    res = run(good, base, opt.Goal(set_key=ATK_SET, extra_crit=30))
    assert res[0].pieces[4].main_key == "critDMG_"
    # The panel above the cap scores the same as the cap itself.
    final = np.zeros((2, opt.D))
    final[:, opt.IDX["atk"]] = 1000
    final[:, opt.IDX["critDMG_"]] = 100
    final[0, opt.IDX["critRate_"]] = 70
    final[1, opt.IDX["critRate_"]] = 101
    _, _, dmg = opt.evaluate(final, opt.Goal(), "pyro", 30)
    assert dmg[0] == pytest.approx(dmg[1])


def test_minimums_filter_and_targets_mode():
    good = {"artifacts": full_set()[:2] + [
        art(ATK_SET, "goblet"), art(ATK_SET, "circlet"),                      # 2, 3
        art(ATK_SET, "sands", main=("atk_", 46.6)),                           # 4 damage
        art(ATK_SET, "sands", main=("enerRech_", 51.8)),                      # 5 recharge
    ]}
    base = make_base(critRate_=50, critDMG_=50, enerRech_=60)
    goal = opt.Goal(set_key=ATK_SET)
    assert run(good, base, goal)[0].pieces[2].id == 4

    goal = opt.Goal(set_key=ATK_SET, minimums={"enerRech_": 100})
    res = run(good, base, goal)
    assert res and all(r.stats["enerRech_"] >= 100 for r in res)
    assert res[0].pieces[2].id == 5

    goal = opt.Goal(set_key=ATK_SET, mode="targets",
                    targets={"enerRech_": 110, "critRate_": 50})
    res = run(good, base, goal)
    assert res[0].pieces[2].id == 5 and res[0].score == 0
    assert res[-1].score > 0


def test_ratio_mode_prefers_balance():
    good = {"artifacts": full_set()[:4] + [
        art(ATK_SET, "circlet", main=("critRate_", 31.1)),                    # 4 balanced
        art(ATK_SET, "circlet", main=("critDMG_", 62.2), subs=[("atk", 200)]),  # 5 more damage
    ]}
    base = make_base(critRate_=20, critDMG_=100)
    assert run(good, base, opt.Goal(set_key=ATK_SET))[0].pieces[4].id == 5
    goal = opt.Goal(set_key=ATK_SET, mode="ratio")
    assert run(good, base, goal)[0].pieces[4].id == 4


def test_result_card_shape():
    pieces = full_set()
    pieces[0]["location"] = "Amber"
    pieces[0]["substats"] = [{"key": "critRate_", "value": 10.5}]
    good = {"artifacts": pieces}
    base = make_base(critRate_=5, critDMG_=50)
    result = run(good, base, opt.Goal(set_key=ATK_SET))[0]
    card = {"name": "Test", "element": "pyro", "level": 90, "weapon": {"name": "W"}}
    out = opt.result_card(result, card)
    assert out["name"] == "Test" and out["weapon"] == {"name": "W"}
    assert len(out["artifacts"]) == 5
    flower = out["artifacts"][0]
    assert flower["icon"] == f"UI_RelicIcon_{ATK_SET_ID}_4"
    assert flower["owner"] == "Amber"
    assert flower["setName"] == "Gladiator's Finale"
    assert flower["subs"][0]["rolls"] >= 1
    assert flower["critValue"] == 21.0
    assert [s["key"] for s in out["stats"]][:3] == ["hp", "atk", "def"]
    assert out["stats"][-1]["key"] == "pyro_dmg_"
    assert out["sets"][0]["count"] == 5 and len(out["sets"][0]["bonuses"]) == 2
    assert out["critValue"] == 21.0


def test_owner_shows_other_characters_by_name():
    piece = opt.Piece(id=0, set_key="GladiatorsFinale", slot="flower", rarity=5, level=20,
                    main_key="hp", main_value=4780.0, subs=(("critRate_", 3.9),),
                    location="YaeMiko", vec=tuple([0.0] * opt.D))
    mine = opt.Piece(**{**piece.__dict__, "id": 1, "location": "Furina"})
    res = opt.Result(pieces=[piece, mine], set_key="GladiatorsFinale",
                   stats={k: 0.0 for k in opt.KEYS}, damage=0.0, score=0.0, cond_crit=0.0)
    card = opt.result_card(res, {"key": "Furina", "name": "Furina", "artifacts": []})
    assert [a["owner"] for a in card["artifacts"]] == ["Yae Miko", ""]


class FakeModel:
    scaling = "atk"
    element = "hydro"
    crit = True

    def __init__(self):
        self.calls = []

    def predict(self, final, set_key):
        self.calls.append(set_key)
        return (final[:, opt.IDX["atk"]] * (1 + final[:, opt.IDX["critDMG_"]] / 100)
                * (2.0 if set_key == ATK_SET else 1.0))


def test_akasha_mode_uses_the_model_and_the_set_key():
    good = {"artifacts": full_set() + [
        art(ATK_SET, "circlet", main=("critRate_", 31.1), subs=[("critDMG_", 14)])]}
    base = make_base(critRate_=5, critDMG_=50)
    model = FakeModel()
    res = run(good, base, opt.Goal(mode="akasha", akasha=model, set_key=ATK_SET))
    assert res
    assert model.calls and set(model.calls) == {ATK_SET}
    row = np.zeros((1, opt.D))
    for k, v in res[0].stats.items():
        row[0, opt.IDX[k]] = v
    assert res[0].score == pytest.approx(model.predict(row, ATK_SET)[0])


def test_akasha_mode_without_a_model_raises():
    final = np.zeros((1, opt.D))
    with pytest.raises(ValueError):
        opt.evaluate(final, opt.Goal(mode="akasha"), "pyro", 0.0)
