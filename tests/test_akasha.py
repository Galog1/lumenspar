import json
import time
import urllib.error
import urllib.parse

import numpy as np
import pytest

from lumenspar import akasha


def fake_fetch(routes, calls=None):
    """A fetch that answers with the payload of the first route found in the URL."""
    def fetch(url):
        if calls is not None:
            calls.append(url)
        for key, payload in routes.items():
            if key in url:
                return json.dumps(payload).encode("utf-8")
        raise AssertionError(f"unexpected url {url}")
    return fetch


def entry(avatar, kind, result, ranking, out_of=271693, variant=None):
    return {
        "characterId": avatar, "name": "Flins", "type": kind,
        "lastBuildUpdate": "2026-10-01T00:00:00Z",
        "calculations": {"fit": {
            "calculationId": "cid1", "name": "Lunar-Charged", "short": "LC", "details": "d",
            "result": result, "ranking": ranking, "outOf": out_of,
            "variant": variant, "weapon": {"name": "Some Spear"},
        }},
    }


def test_profile_parsing_and_cache(tmp_path):
    data = [
        entry(10000123, "Flins top 1%", 1000.0, 10),
        entry(10000123, "current", 800000.5, 51720, variant={"name": "120er", "displayName": "120% ER"}),
        {"characterId": 5, "name": "NoFit", "calculations": {}},
    ]
    fetch = fake_fetch({"getCalculationsForUser/123": {"data": data}})
    calcs = akasha.profile("123", fetch=fetch, root=tmp_path)
    assert list(calcs) == ["10000123"]
    c = calcs["10000123"]
    assert c.result == 800000.5 and c.ranking == 51720 and c.out_of == 271693
    assert c.variant == "120er" and c.variant_label == "120% ER" and c.weapon == "Some Spear"
    assert c.rank_text() == "top 19.0% · #51,720 of 271,693"
    assert c.min_er() == 120.0
    c.variant = ""
    assert c.min_er() is None
    assert akasha.Calc("1", "x", "c", "", "", "", "", "", 1.0, 0, 0, "", "").rank_text() == ""

    def boom(url):
        raise AssertionError("cache should be used")
    again = akasha.profile("123", fetch=boom, root=tmp_path)
    assert again["10000123"].ranking == 51720
    text = (tmp_path / "profile-123.json").read_text(encoding="utf-8")
    assert "owner" not in text and "nickname" not in text


def test_profile_cache_expires(tmp_path):
    fetch = fake_fetch({"getCalculationsForUser": {"data": [entry(1, "current", 5.0, 3)]}})
    t = [1000.0]
    akasha.profile("9", fetch=fetch, root=tmp_path, now=lambda: t[0])
    t[0] += akasha.PROFILE_TTL + 1
    calls = []
    akasha.profile("9", fetch=fake_fetch({"getCalculationsForUser": {"data": []}}, calls),
                   root=tmp_path, now=lambda: t[0])
    assert len(calls) == 1


def board_row(i, atk=2000.0):
    return {
        "_id": f"id{i}", "uid": 700000 + i, "owner": {"nickname": f"Player{i}"},
        "stats": {"atk": {"value": atk + i}, "critRate": {"value": 0.6},
                  "critDamage": {"value": 1.8}, "hydroDamageBonus": {"value": 0.466}},
        "artifactSets": {"Golden Troupe": {"icon": "x.png", "count": 4},
                         "Gladiator's Finale": {"icon": "y.png", "count": 1}},
        "calculation": {"result": 1000.0 + i},
    }


def test_sample(tmp_path):
    rows_data = [board_row(i) for i in range(30)]
    calls, naps = [], []
    fetch = fake_fetch({"leaderboards": {"data": rows_data}}, calls)
    calc = akasha.Calc("1", "x", "cid1", "", "", "", "", "", 1010.0, 5, 100, "", "")
    rows, top = akasha.sample(calc, fetch=fetch, root=tmp_path, sleep=naps.append)
    assert len(calls) == 4 and naps == [akasha.PAUSE] * 3
    assert len(rows) == 30 and top == 1029.0
    r = rows[0]
    assert r.set4 == "GoldenTroupe"
    assert r.stats["critRate_"] == pytest.approx(60.0)
    assert r.stats["critDMG_"] == pytest.approx(180.0)
    assert r.stats["hydro_dmg_"] == pytest.approx(46.6)
    cache = tmp_path / "board2-cid1-none.json"
    text = cache.read_text(encoding="utf-8")
    for word in ("_id", "uid", "owner", "nickname"):
        assert word not in text

    def boom(url):
        raise AssertionError("cache should be used")
    rows2, top2 = akasha.sample(calc, fetch=boom, root=tmp_path)
    assert len(rows2) == 30 and top2 == top


def test_sample_too_few(tmp_path):
    fetch = fake_fetch({"leaderboards": {"data": [board_row(i) for i in range(5)]}})
    calc = akasha.Calc("1", "x", "cid2", "120er", "", "", "", "", 1010.0, 5, 100, "", "")
    with pytest.raises(akasha.AkashaError):
        akasha.sample(calc, fetch=fetch, root=tmp_path, sleep=lambda s: None)


def test_fit_recovers_formula():
    rng = np.random.default_rng(7)
    factors = {"GoldenTroupe": 10.0, "EmblemOfSeveredFate": 10.05}

    def result(atk, cr, cd, dmg, set_key):
        return float(np.exp(factors[set_key]) * (atk + 400) * (1 + min(cr + 0.2, 1) * cd)
                     * (1 + dmg + 0.6))

    rows = []
    for set_key in factors:
        for _ in range(60):
            atk = rng.uniform(1800, 2600)
            cr, cd = rng.uniform(0.4, 0.9), rng.uniform(1.2, 2.6)
            dmg = rng.uniform(0.3, 0.7)
            stats = {"atk": atk, "critRate_": cr * 100, "critDMG_": cd * 100,
                     "hydro_dmg_": dmg * 100, "hp": 20000.0, "def": 700.0, "eleMas": 80.0}
            rows.append(akasha.Row(stats, set_key, result(atk, cr, cd, dmg, set_key)))
    t0 = time.time()
    model = akasha.fit(rows, "hydro")
    assert time.time() - t0 < 20
    assert model.scaling == "atk" and model.crit is True
    assert model.rms < 0.01
    for set_key in factors:
        atk, cr, cd, dmg = 2200.0, 0.55, 1.9, 0.5
        stats = {"atk": atk, "critRate_": cr * 100, "critDMG_": cd * 100,
                 "hydro_dmg_": dmg * 100}
        truth = result(atk, cr, cd, dmg, set_key)
        assert model.predict_stats(stats, set_key) == pytest.approx(truth, rel=0.01)


def test_fit_too_few():
    with pytest.raises(akasha.AkashaError):
        akasha.fit([akasha.Row({"atk": 1.0}, "", 1.0)] * 5, "hydro")


def test_estimate_rank():
    calc = akasha.Calc("1", "x", "c", "", "", "", "", "", 1000.0, 5000, 100000, "", "")
    top = 2000.0
    assert akasha.estimate_rank(calc, top, 2500.0) == (1, pytest.approx(0.001))
    assert akasha.estimate_rank(calc, top, 1000.0)[0] == 5000
    mid = akasha.estimate_rank(calc, top, 1500.0)[0]
    assert 1 < mid < 5000
    worse, pct = akasha.estimate_rank(calc, top, 500.0)
    assert 5000 < worse <= 100000
    assert pct == pytest.approx(worse / 100000 * 100)
    assert akasha.estimate_rank(akasha.Calc("1", "x", "c", "", "", "", "", "", 1.0, 0, 0, "", ""),
                                top, 1.0) == (0, 0.0)


def test_get_errors():
    def unreachable(url):
        raise urllib.error.URLError("no route")

    def junk(url):
        return b"not json"

    def http(url):
        raise urllib.error.HTTPError(url, 503, "down", {}, None)

    with pytest.raises(akasha.AkashaError, match="could not reach"):
        akasha._get("x", {}, unreachable)
    with pytest.raises(akasha.AkashaError, match="unexpected"):
        akasha._get("x", {"a": 1}, junk)
    with pytest.raises(akasha.AkashaError, match="503"):
        akasha._get("x", {}, http)


def build_entry(avatar, kind, md5, updated, owner="Someone"):
    return {"characterId": avatar, "md5": md5, "type": kind, "lastBuildUpdate": updated,
            "artifactSets": {"Golden Troupe": {"icon": "x.png", "count": 4}},
            "uid": 123, "owner": {"nickname": owner}}


def test_live_builds(tmp_path):
    data = [
        build_entry(1, "current", "old", 100),
        build_entry(1, "current", "new", 200),
        build_entry(1, "My saved", "saved", 900),
        build_entry(2, "current", "two", 50),
        build_entry(3, "Other", "x", 5),
    ]
    calls = []
    fetch = fake_fetch({"builds/": {"data": data}}, calls)
    builds = akasha.live_builds("123", fetch=fetch, root=tmp_path)
    assert builds == {"1": {"md5": "new", "updated": 200, "sets": {"Golden Troupe": 4}},
                      "2": {"md5": "two", "updated": 50, "sets": {"Golden Troupe": 4}}}
    assert "uid=123" in calls[0]
    text = (tmp_path / "builds-123.json").read_text(encoding="utf-8")
    assert "owner" not in text and "uid" not in text and "Someone" not in text

    def boom(url):
        raise AssertionError("cache should be used")
    assert akasha.live_builds("123", fetch=boom, root=tmp_path) == builds


def build_payload():
    return {
        "calculations": {
            "c1": {"short": "A", "name": "Alpha", "details": "d", "result": 5000.5,
                   "ranking": 500, "outOf": 1000, "weapon": {"name": "Spear"},
                   "variant": {"name": "120er", "displayName": "120% ER"},
                   "stats": {"maxATK": 2561.8, "elementalMastery": 286.6, "critRate": 70.6,
                             "critDMG": 236.85, "energyRecharge": 0, "baseATK": 1025.9}},
            "c2": {"short": "B", "name": "Beta", "result": 100.0, "ranking": 10, "outOf": 1000,
                   "weapon": {"name": "Sword"}},
        },
        "chartsData": {"charts1pMetadata": [
            {"calculationId": "c1", "avgStats": {"critRate": 0.695, "atk": 2100.0,
                                                 "energyRecharge": 1.10, "bogus": 5}},
            {"avgStats": {"atk": 1}},
        ]},
    }


def test_build_info(tmp_path):
    calls = []
    fetch = fake_fetch({"leaderboards/123/abc": {"data": build_payload()}}, calls)
    info = akasha.build_info("123", "10000123", "abc", fetch=fetch, root=tmp_path)
    assert "variant=profilePage" in calls[0]
    assert [c.calculation_id for c in info.calcs] == ["c2", "c1"]
    c1 = info.calcs[1]
    assert c1.avatar_id == "10000123" and c1.variant == "120er" and c1.variant_label == "120% ER"
    assert c1.result == 5000.5 and c1.ranking == 500 and c1.out_of == 1000 and c1.weapon == "Spear"
    c2 = info.calcs[0]
    assert c2.variant == "" and c2.variant_label == ""
    assert set(info.top1) == {"c1"}
    assert info.top1["c1"]["critRate_"] == pytest.approx(69.5)
    assert info.top1["c1"]["atk"] == 2100.0
    assert info.top1["c1"]["enerRech_"] == pytest.approx(110.0)
    assert "bogus" not in info.top1["c1"]

    def boom(url):
        raise AssertionError("cache should be used")
    again = akasha.build_info("123", "10000123", "abc", fetch=boom, root=tmp_path)
    assert [c.calculation_id for c in again.calcs] == ["c2", "c1"]
    assert again.top1 == info.top1
    # The build's own stats as Akasha computed them (already in percent).
    assert info.mine["c1"] == {"atk": 2561.8, "eleMas": 286.6, "critRate_": 70.6,
                               "critDMG_": 236.85}
    assert "c2" not in info.mine and again.mine == info.mine


def test_pick():
    a = akasha.Calc("1", "", "a", "", "", "", "", "", 1.0, 100, 1000, "Spear", "")
    b = akasha.Calc("1", "", "b", "", "", "", "", "", 1.0, 300, 1000, "spear", "")
    c = akasha.Calc("1", "", "c", "", "", "", "", "", 1.0, 10, 1000, "Sword", "")
    assert akasha.pick([a, b, c], "SPEAR") is a
    assert akasha.pick([b, c], "Bow") is c
    assert akasha.pick([], "Spear") is None


def test_rank_of():
    calc = akasha.Calc("1", "", "cid9", "120er", "", "", "", "", 1.0, 100, 1000, "", "")
    calls = []
    fetch = fake_fetch({"leaderboards": {"data": [{"index": 18183}]}}, calls)
    assert akasha.rank_of(calc, 12345.5, fetch=fetch) == 18183
    assert "p=lt%7C" in calls[0] and "12345.5" in calls[0]
    empty = fake_fetch({"leaderboards": {"data": []}})
    assert akasha.rank_of(calc, 1.0, fetch=empty) == 1001
    calc.out_of = 0
    assert akasha.rank_of(calc, 1.0, fetch=empty) == 0


def categories_payload():
    def weapon(name, cid, hidden=False, default=""):
        return {"name": name, "refinement": 1, "calculationId": cid, "defaultVariant": default,
                "hidden": hidden, "filters": [
                    {"name": "110er", "displayName": "110% ER",
                     "query": {"operator": "$gte", "field": "stats.energyRecharge.value",
                               "value": 1.0995}},
                    {"name": "120er", "displayName": "120% ER",
                     "query": {"operator": "$gte", "field": "stats.energyRecharge.value",
                               "value": 1.1995}},
                    {"name": "hp", "displayName": "HP",
                     "query": {"operator": "$gte", "field": "stats.maxHp.value", "value": 30000}},
                ]}
    return [
        {"name": "Alpha", "short": "A", "details": "da", "hidden": False, "count": 5,
         "weapons": [weapon("Spear", "c1", default="120er"), weapon("Sword", "c2"),
                     weapon("Hidden Bow", "c3", hidden=True)]},
        {"name": "Beta", "short": "B", "details": "db", "hidden": False, "count": 3,
         "weapons": [weapon("Spear", "c4")]},
        {"name": "Secret", "short": "S", "details": "", "hidden": True, "count": 1,
         "weapons": [weapon("Spear", "c5")]},
    ]


def test_boards(tmp_path):
    calls = []
    fetch = fake_fetch({"leaderboards/categories": {"data": categories_payload()}}, calls)
    found = akasha.boards("10000123", fetch=fetch, root=tmp_path)
    assert "characterId=10000123" in calls[0]
    assert [(b.calculation_id, b.weapon, b.name) for b in found] == [
        ("c1", "Spear", "Alpha"), ("c2", "Sword", "Alpha"), ("c4", "Spear", "Beta")]
    b = found[0]
    assert b.short == "A" and b.details == "da" and b.refinement == 1
    assert b.default_variant == "120er"
    assert [(v.name, v.label, v.min_er) for v in b.variants] == [
        ("110er", "110% ER", 110.0), ("120er", "120% ER", 120.0)]

    def boom(url):
        raise AssertionError("cache should be used")
    again = akasha.boards("10000123", fetch=boom, root=tmp_path)
    assert again == found


def test_boards_for_weapon():
    mk = lambda cid, weapon: akasha.Board("n", "s", "d", cid, weapon, 1, "", [])
    allb = [mk("a", "Spear"), mk("b", "Sword"), mk("c", "spear")]
    assert [b.calculation_id for b in akasha.boards_for_weapon(allb, "SPEAR")] == ["a", "c"]
    assert akasha.boards_for_weapon(allb, "Bow") == []


def test_main_key():
    cases = {
        "ATK%": "atk_", "HP%": "hp_", "DEF%": "def_", "Elemental Mastery": "eleMas",
        "Energy Recharge": "enerRech_", "Crit RATE": "critRate_", "Crit Rate": "critRate_",
        "CRIT Rate": "critRate_", "Crit DMG": "critDMG_", "CRIT DMG": "critDMG_",
        "Healing Bonus": "heal_", "Cryo DMG Bonus": "cryo_dmg_", " pyro dmg bonus ": "pyro_dmg_",
        "Physical DMG Bonus": "physical_dmg_", "Dendro DMG Bonus": "dendro_dmg_",
        "Nonsense": "",
    }
    for label, key in cases.items():
        assert akasha._main_key(label) == key, label
    for e in ("Pyro", "Hydro", "Electro", "Cryo", "Anemo", "Geo", "Dendro", "Physical"):
        assert akasha._main_key(f"{e} DMG Bonus") == f"{e.lower()}_dmg_"


def test_row_mains():
    r = board_row(1)
    r["artifactObjects"] = {"EQUIP_SHOES": {"mainStatKey": "ATK%"},
                            "EQUIP_RING": {"mainStatKey": "Cryo DMG Bonus"},
                            "EQUIP_DRESS": {"mainStatKey": "Weird"},
                            "EQUIP_BRACER": {"mainStatKey": "HP"}}
    assert akasha._row(r).mains == {"sands": "atk_", "goblet": "cryo_dmg_"}
    assert akasha._row(board_row(2)).mains == {}


def test_common():
    def row(result, set4, **mains):
        return akasha.Row({}, set4, float(result), dict(mains))

    rows = []
    # Best half (rows 100..51): 50 rows. Worst half would add other sets/mains.
    for i in range(100, 50, -1):
        n = 100 - i
        set4 = "A" if n < 30 else "B" if n < 47 else "C" if n < 49 else ""
        sands = "atk_" if n < 40 else "enerRech_" if n < 46 else "hp_"
        goblet = "cryo_dmg_" if n < 30 else "atk_"
        rows.append(row(i, set4, sands=sands, goblet=goblet, **({"circlet": "critRate_"} if n < 10 else {})))
    for i in range(50):
        rows.append(row(i + 1, "Z", sands="def_", goblet="def_", circlet="heal_"))
    sets, mains = akasha.common(rows)
    assert sets == [("A", pytest.approx(30 / 50)), ("B", pytest.approx(17 / 50))]
    assert all(k != "C" and k != "Z" for k, _ in sets)
    assert mains["sands"] == [("atk_", pytest.approx(0.8)), ("enerRech_", pytest.approx(0.12))]
    assert mains["goblet"] == [("cryo_dmg_", pytest.approx(0.6)), ("atk_", pytest.approx(0.4))]
    assert mains["circlet"] == [("critRate_", pytest.approx(1.0))]


def test_common_small_sample_uses_all():
    rows = [akasha.Row({}, "A", float(i), {}) for i in range(10)]
    sets, mains = akasha.common(rows)
    assert sets == [("A", 1.0)] and mains == {"sands": [], "goblet": [], "circlet": []}


def test_sample_without_own_result(tmp_path):
    first = [board_row(i) for i in range(30)]
    calls = []

    def fetch(url):
        calls.append(url)
        return json.dumps({"data": first if len(calls) == 1 else []}).encode("utf-8")

    calc = akasha.Calc("", "", "cid3", "", "", "", "", "", 0.0, 0, 0, "", "")
    rows, top = akasha.sample(calc, fetch=fetch, root=tmp_path, sleep=lambda s: None)
    assert top == 1029.0 and len(rows) == 30
    assert len(calls) == 4
    assert "p=&" in calls[0] + "&" or "p=" in calls[0]
    for url, factor in zip(calls[1:], (0.97, 0.93, 0.88)):
        assert urllib.parse.quote(f"lt|{1029.0 * factor}", safe="") in url
    assert (tmp_path / "board2-cid3-none.json").exists()


def test_calc_for_board():
    board = akasha.Board("Alpha", "A", "da", "c1", "Spear", 1, "",
                         [akasha.Variant("110er", "110% ER", 110.0),
                          akasha.Variant("120er", "120% ER", 120.0)])
    own = akasha.Calc("10000123", "Flins", "c1", "120er", "120% ER", "Alpha", "A", "da",
                      5000.0, 50, 1000, "Spear", "u", {"X": 4})
    other = akasha.Calc("10000123", "Flins", "c9", "", "", "Z", "Z", "", 1.0, 1, 2, "", "")
    same = akasha.calc_for_board(board, "120er", [other, own])
    assert same.result == 5000.0 and same.ranking == 50 and same.out_of == 1000
    assert same.variant == "120er" and same.sets == {"X": 4}
    changed = akasha.calc_for_board(board, "110er", [other, own])
    assert changed.result == 5000.0 and changed.ranking == 0 and changed.out_of == 0
    assert changed.variant == "110er" and changed.variant_label == "110% ER"
    assert own.ranking == 50 and own.variant == "120er"
    none = akasha.calc_for_board(board, "", [other])
    assert (none.avatar_id, none.calculation_id, none.variant, none.variant_label) == ("", "c1", "", "")
    assert none.name == "Alpha" and none.short == "A" and none.details == "da"
    assert none.result == 0.0 and none.ranking == 0 and none.weapon == "Spear" and none.sets == {}
    assert akasha.calc_for_board(board, "110er", []).variant_label == "110% ER"


COMBO_ADDITIONAL = [
    {"name": "Northland Spearstorm Avg DMG", "value": 24452.97, "quantity": 2, "type": "E"},
    {"name": "Normal Attack 1 Avg DMG", "value": 7984.2, "quantity": 3, "type": "NA"},
    {"name": "", "value": 5, "quantity": 1, "type": "NA"},
    {"name": "Zero", "value": 5, "quantity": 0, "type": "NA"},
    {"name": "Lunar-Charged DMG (60%)", "value": 57947.4, "quantity": 5, "type": "LC"},
]


def test_combo_parsing_and_cache(tmp_path):
    calls = []
    fetch = fake_fetch({"leaderboards": {"data": [{"calculation": {"additional": COMBO_ADDITIONAL}}]}},
                       calls)
    hits = akasha.combo("1000012000", "120er", fetch, root=tmp_path)
    assert hits == [akasha.Hit("Northland Spearstorm Avg DMG", 2.0, "E", 24452.97),
                    akasha.Hit("Normal Attack 1 Avg DMG", 3.0, "NA", 7984.2),
                    akasha.Hit("Lunar-Charged DMG (60%)", 5.0, "LC", 57947.4)]
    assert "calculationId=1000012000" in calls[0] and "variant=120er" in calls[0]
    assert akasha.combo("1000012000", "120er", fetch, root=tmp_path) == hits
    assert len(calls) == 1


def test_combo_without_breakdown(tmp_path):
    for payload in ({"data": []}, {"data": [{"calculation": {"result": 1}}]}):
        with pytest.raises(akasha.AkashaError, match="no damage breakdown"):
            akasha.combo("1", "", fake_fetch({"leaderboards": payload}), root=tmp_path)
