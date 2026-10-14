"""Helpers of the Team damage optimizer mode (pure; no engine calls)."""

import pytest

from lumenspar import optimizer as O
from lumenspar import teamopt as T


def _piece(pid, set_key, slot, main="atk_", mv=46.6, subs=(), level=20, rarity=5, loc=""):
    return O.Piece(pid, set_key, slot, rarity, level, main, mv, tuple(subs), loc,
                   tuple([0.0] * O.D))


def _near(a, b):
    return a == pytest.approx(b)


def test_candidate_sums_and_fractions():
    p = _piece(7, "GildedDreams", "sands", "atk_", 46.6,
               [("critRate_", 3.9), ("atk_", 5.8), ("atk", 19), ("enerRech_", 10.0)])
    c = T.candidate(p)
    assert c["id"] == 7 and c["GildedDreams"] == 1
    assert _near(c["atk_"], 0.466 + 0.058)        # main and substat of one key are summed
    assert _near(c["critRate_"], 0.039)
    assert c["atk"] == 19
    assert _near(c["enerRech_"], 0.10)


def test_card_candidates_in_slot_order():
    def art(slot, set_key, mk, mv, subs=()):
        return {"slot": slot, "setKey": set_key, "main": {"key": mk, "value": mv},
                "subs": [{"key": k, "value": v} for k, v in subs]}
    card = {"artifacts": [art("circlet", "A", "critDMG_", 62.2, [("hp", 100)]),
                          art("flower", "A", "hp", 4780, [("atk_", 5.0)]),
                          art("sands", "B", "atk_", 46.6)]}
    cands = T.card_candidates(card)
    assert [c["id"] for c in cands] == ["cur0", "cur1", "cur2"]
    assert cands[0]["A"] == 1 and cands[0]["hp"] == 4780 and _near(cands[0]["atk_"], 0.05)
    assert cands[1]["B"] == 1 and _near(cands[1]["atk_"], 0.466)
    assert cands[2]["A"] == 1 and _near(cands[2]["critDMG_"], 0.622) and cands[2]["hp"] == 100
    assert T.card_candidates({}) == []


def test_engine_minimums():
    got = T.engine_minimums({"enerRech_": 160, "critRate_": 70, "eleMas": 200, "atk": 2000,
                             "pyro_dmg_": 50})
    assert got[0] == {"q": "enerRech_", "value": pytest.approx(0.6)}
    assert got[1] == {"q": "critRate_", "value": pytest.approx(0.7)}
    assert got[2] == {"q": "eleMas", "value": 200}
    assert got[3] == {"q": "atk", "value": 2000}
    assert got[4] == {"q": "dmg_", "ele": "pyro", "value": pytest.approx(0.5)}
    assert T.engine_minimums({}) == []


def _closet():
    """Set A on every slot (two pieces on the sands), one B piece on the flower and circlet."""
    out, n = [], 0
    for slot in O.SLOTS:
        out.append(_piece(n, "A", slot)); n += 1
    out.append(_piece(n, "A", "sands", "hp_", 46.6)); n += 1
    out.append(_piece(n, "B", "flower", "hp", 4780)); n += 1
    out.append(_piece(n, "B", "circlet", "critRate_", 31.1)); n += 1
    return out


def test_families_structure():
    pieces = _closet()
    fams = T.families(pieces, ["A"], {}, 16, True, "")
    # all-A plus one family per slot taking a non-A piece: only flower and circlet have one
    assert len(fams) == 3
    assert all(len(f) == 5 for f in fams)
    full = fams[0]
    assert [len(x) for x in full] == [1, 1, 2, 1, 1]
    assert all("A" in c for x in full for c in x)
    flower_off = fams[1]
    assert [c["id"] for c in flower_off[0]] == [6] and "B" in flower_off[0][0]
    assert all("A" in c for x in flower_off[1:] for c in x)
    circlet_off = fams[2]
    assert "B" in circlet_off[4][0] and all("A" in c for x in circlet_off[:4] for c in x)


def test_families_skip_empty_slots_and_unknown_sets():
    pieces = [p for p in _closet() if p.slot != "goblet"]
    assert T.families(pieces, ["A"], {}, 16, True, "") == []
    assert T.families(_closet(), ["Nope"], {}, 16, True, "") == []


def test_families_mains_level_equipped_filters():
    pieces = _closet()
    fams = T.families(pieces, ["A"], {"sands": ["hp_"]}, 16, True, "")
    assert [c["id"] for c in fams[0][2]] == [5]
    assert T.families(pieces, ["A"], {"sands": ["eleMas"]}, 16, True, "") == []
    # a main list for a slot only restricts that slot; empty means any
    assert len(T.families(pieces, ["A"], {"sands": [], "goblet": []}, 16, True, "")[0][2]) == 2
    low = [_piece(0, "A", s, level=12) for s in O.SLOTS]
    assert T.families(low, ["A"], {}, 16, True, "") == []
    assert len(T.families(low, ["A"], {}, 12, True, "")) == 1
    worn = [_piece(i, "A", s, loc=loc) for i, (s, loc) in enumerate(
        zip(O.SLOTS, ["", "Me", "Other", "", ""]))]
    assert len(T.families(worn, ["A"], {}, 16, True, "Me")) == 1
    assert T.families(worn, ["A"], {}, 16, False, "Me") == []
    worn[2] = _piece(2, "A", "sands", loc="Me")
    assert len(T.families(worn, ["A"], {}, 16, False, "Me")) == 1
    four_star = [_piece(i, "A", s, rarity=4) for i, s in enumerate(O.SLOTS)]
    assert T.families(four_star, ["A"], {}, 0, True, "") == []


def test_sets_with_four():
    pieces = _closet()
    assert T.sets_with_four(pieces, {}, 16, True, "") == ["A"]     # B has two slots
    more = pieces + [_piece(20 + i, "C", s) for i, s in enumerate(O.SLOTS[:4])]
    assert T.sets_with_four(more, {}, 16, True, "") == ["A", "C"]  # 7 pieces, then 4
    assert T.sets_with_four(more, {"sands": ["eleMas"]}, 16, True, "") == ["A"]  # C loses its sands
    assert T.sets_with_four(more, {}, 20, False, "Me") == ["A", "C"]
    assert T.sets_with_four([], {}, 16, True, "") == []


FORMULAS = [
    {"sheet": "Furina", "name": "skill_dmg", "q": "dmg", "move": "skill"},
    {"sheet": "Furina", "name": "burst_dmg", "q": "dmg", "move": "burst"},
    {"sheet": "Furina", "name": "burst_heal", "q": "heal", "move": "burst"},
]


def test_frames_rotation():
    got = T.frames("rotation", {"Furina:skill_dmg": 3, "Furina:burst_heal": 2, "Furina:burst_dmg": 0},
                   FORMULAS)
    assert got == [{"sheet": "Furina", "name": "skill_dmg", "q": "dmg", "multiplier": 3},
                   {"sheet": "Furina", "name": "burst_heal", "q": "heal", "multiplier": 2}]
    # a hit the formulas don't list falls back to "dmg"
    assert T.frames("rotation", {"X:y": 1}, [])[0]["q"] == "dmg"


def test_frames_single_and_errors():
    assert T.frames("Furina:burst_dmg", {}, FORMULAS) == [
        {"sheet": "Furina", "name": "burst_dmg", "q": "dmg", "multiplier": 1}]
    with pytest.raises(ValueError):
        T.frames("rotation", {}, FORMULAS)
    with pytest.raises(ValueError):
        T.frames("rotation", {"Furina:skill_dmg": 0}, FORMULAS)
    with pytest.raises(ValueError):
        T.frames("Furina:nope", {}, FORMULAS)


def test_card_pieces_join_the_search_and_replace_scan_copies():
    card = {"key": "Skirk", "artifacts": [
        {"slot": "flower", "setKey": "GladiatorsFinale", "rarity": 5, "level": 20,
         "main": {"key": "hp", "value": 4780.0},
         "subs": [{"key": "critRate_", "value": 3.9}, {"key": "atk", "value": 19.0}]},
    ]}
    own = T.card_pieces(card)
    assert own[0].id == -1 and own[0].location == "Skirk" and own[0].slot == "flower"
    assert own[0].vec[T.IDX["critRate_"]] == 3.9
    scan_copy = T.Piece(id=7, set_key="GladiatorsFinale", slot="flower", rarity=5, level=20,
                              main_key="hp", main_value=4780.0,
                              subs=(("atk", 19.0), ("critRate_", 3.9)), location="Skirk",
                              vec=own[0].vec)
    other = T.Piece(id=8, set_key="GladiatorsFinale", slot="plume", rarity=5, level=20,
                          main_key="atk", main_value=311.0, subs=(), location="", vec=own[0].vec)
    merged = T.with_card_pieces([scan_copy, other], card)
    assert sorted(p.id for p in merged) == [-1, 8]
