import json
import time
import urllib.error

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
    cache = tmp_path / "board-cid1-none.json"
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
