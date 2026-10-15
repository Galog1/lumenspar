"""Damage calculator backend: conversion, labels and the bundled GO engine."""

import pytest

from lumenspar import damage, optimizer


def _card(weapon=True):
    card = {
        "key": "Furina", "level": 90, "ascension": 6, "constellation": 2,
        "talents": [{"slot": "auto", "base": 9}, {"slot": "skill", "base": 10},
                    {"slot": "burst", "base": 11}],
        "artifacts": [{"setKey": "GoldenTroupe",
                       "main": {"key": "hp", "value": 4780},
                       "subs": [{"key": "critRate_", "value": 10.5},
                                {"key": "atk", "value": 19}]}],
    }
    if weapon:
        card["weapon"] = {"key": "SplendorOfTranquilWaters", "level": 90,
                          "ascension": 6, "refinement": 1}
    return card


def test_member_from_card():
    m = damage.member_from_card(_card())
    assert m["char"] == {"key": "Furina", "level": 90, "constellation": 2, "ascension": 6,
                         "talent": {"auto": 9, "skill": 10, "burst": 11}}
    assert m["weapon"]["key"] == "SplendorOfTranquilWaters"
    stats = m["artifacts"][0]["stats"]
    assert m["artifacts"][0]["set"] == "GoldenTroupe"
    assert stats[0] == {"key": "hp", "value": 4780}
    assert stats[1] == {"key": "critRate_", "value": pytest.approx(0.105)}
    assert stats[2] == {"key": "atk", "value": 19}


def test_member_from_card_needs_weapon():
    with pytest.raises(ValueError):
        damage.member_from_card(_card(weapon=False))


def _good():
    return {
        "characters": [
            {"key": "Furina", "level": 90, "ascension": 6, "constellation": 0,
             "talent": {"auto": 9, "skill": 9, "burst": 9}},
            {"key": "TravelerAnemo", "level": 80, "ascension": 6, "constellation": 1,
             "talent": {"auto": 6, "skill": 6, "burst": 6}},
        ],
        "weapons": [
            {"key": "SplendorOfTranquilWaters", "level": 90, "ascension": 6,
             "refinement": 1, "location": "Furina"},
            {"key": "Sword", "level": 1, "ascension": 0, "refinement": 1, "location": "Traveler"},
        ],
        "artifacts": [
            {"setKey": "GoldenTroupe", "slotKey": "circlet", "rarity": 5, "level": 20,
             "mainStatKey": "critRate_", "location": "Furina",
             "substats": [{"key": "critDMG_", "value": 14.0}, {"key": "hp", "value": 299}]},
            {"setKey": "GoldenTroupe", "slotKey": "flower", "rarity": 5, "level": 20,
             "mainStatKey": "hp", "location": "Furina", "substats": []},
            {"setKey": "Other", "slotKey": "flower", "rarity": 5, "level": 20,
             "mainStatKey": "hp", "location": "Nahida", "substats": []},
            {"setKey": "ViridescentVenerer", "slotKey": "sands", "rarity": 5, "level": 20,
             "mainStatKey": "eleMas", "location": "Traveler", "substats": []},
        ],
    }


def test_member_from_good():
    m = damage.member_from_good(_good(), "Furina")
    assert m["char"]["talent"] == {"auto": 9, "skill": 9, "burst": 9}
    assert m["weapon"]["key"] == "SplendorOfTranquilWaters"
    assert len(m["artifacts"]) == 2
    circlet = m["artifacts"][0]["stats"]
    assert circlet[0]["value"] == pytest.approx(optimizer.main_value(5, 20, "critRate_") / 100)
    assert circlet[1] == {"key": "critDMG_", "value": pytest.approx(0.14)}
    assert circlet[2] == {"key": "hp", "value": 299}


def test_member_from_good_traveler_and_missing():
    m = damage.member_from_good(_good(), "TravelerAnemo")
    assert m["weapon"]["key"] == "Sword"
    assert [a["set"] for a in m["artifacts"]] == ["ViridescentVenerer"]
    assert damage.member_from_good(_good(), "Nahida") is None
    good = _good()
    good["weapons"] = []
    assert damage.member_from_good(good, "Furina") is None


# -- labels (on the real go_labels.json) ---------------------------------------

def test_humanize_and_strip():
    assert damage.humanize("a4DeathStacks") == "A4 Death Stacks"
    assert damage.humanize("burstSerpentOver") == "Burst Serpent Over"
    assert damage.humanize("0EnergyNoBurst") == "0 Energy No Burst"
    assert damage.strip_tags("a <strong>b</strong>  c") == "a b c"


def test_titles_and_option_label():
    assert damage.sheet_title("reso") == "Elemental Resonance"
    assert damage.sheet_title("Skirk") == "Skirk"
    assert damage.option_label("pyro") == "Pyro"
    assert damage.option_label("2") == "2"
    assert damage.option_label("sc") == "Stellar-Conduct"


def test_render_label_lookup_and_fallback():
    assert damage.render_label(None) == ""
    assert damage.render_label("a <b>b</b>  c") == "a b c"
    assert damage.render_label({"ns": "char_Flins_gen", "key": "auto.skillParams.0"}) == "1-Hit DMG"
    assert damage.render_label({"ns": "sheet", "key": "hitOp.electro"}) == (
        "After dealing Electro DMG")
    # no "ns" means the "sheet" namespace
    assert damage.render_label({"key": "hitOp.electro"}) == "After dealing Electro DMG"
    # a missing key falls back to the humanized last part
    assert damage.render_label({"ns": "sheet", "key": "nothing.someMissingKey"}) == "Some Missing Key"
    assert damage.render_label({"ns": "nope", "key": "x.y"}) == "Y"


def test_render_label_interpolation_plural_and_children(monkeypatch):
    loc = {"sheet": {"stack_one": "{{count}} Roll", "stack_other": "{{count}} Rolls",
                     "pct": "{{value}}% <0>more</0> DMG", "a": "A", "b": "B"}}
    monkeypatch.setattr(damage, "_locale", lambda: loc)
    assert damage.render_label({"key": "stack", "values": {"count": 1}}) == "1 Roll"
    assert damage.render_label({"key": "stack", "values": {"count": 3}}) == "3 Rolls"
    assert damage.render_label({"key": "stack", "values": {"count": 2.0}}) == "2 Rolls"
    assert damage.render_label({"key": "pct", "values": {"value": 12.5}}) == "12.5% more DMG"
    assert damage.render_label({"children": [{"key": "a"}, " + ", {"key": "b"}]}) == "A + B"
    assert damage.render_label({"children": {"key": "a"}}) == "A"
    assert damage.render_label({"children": "plain"}) == "plain"
    assert damage.render_label([{"key": "a"}, {"key": "b"}]) == "AB"


def test_talent_title():
    assert damage.talent_title("Flins", "auto") == "Normal Attack"
    assert damage.talent_title("Flins", "skill") == "Elemental Skill · Ancient Rite: Arcane Light"
    assert damage.talent_title("Flins", "burst").startswith("Elemental Burst · Ancient Ritual")
    assert damage.talent_title("Flins", "passive1") == "Passive · Symphony of Winter"
    assert damage.talent_title("Flins", "constellation1") == "C1 · Part the Veil of Snow"
    assert damage.talent_title("Flins", "reaction") == "Reactions"
    assert damage.talent_title("Flins", "weapon") == "Weapon"
    assert damage.talent_title("Flins", "somethingElse") == "Something Else"
    assert damage.talent_title("Nobody", "burst") == "Elemental Burst"
    assert damage.talent_title("Nobody", "constellation3") == "C3"


# -- the engine ----------------------------------------------------------------

def _member():
    return {
        "char": {"key": "Furina", "level": 90, "constellation": 0, "ascension": 6,
                 "talent": {"auto": 9, "skill": 9, "burst": 9}},
        "weapon": {"key": "SplendorOfTranquilWaters", "level": 90, "ascension": 6,
                   "refinement": 1},
        "artifacts": [],
    }


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QCoreApplication
    return QCoreApplication.instance() or QCoreApplication([])


def _at_level(level):
    m = _member()
    m["char"]["level"] = level
    return m


def test_run_sync_compute(app):
    out = damage.run_sync("compute", {"members": [_member()], "only": [0],
                                      "modes": ["avg", "crit", "nonCrit"]})
    m = out["members"][0]
    assert m["stats"]["hp"] > 10000
    assert m["stats"]["enerRech_"] == pytest.approx(1.0)       # the total: 1.0 is 100%
    assert all(f["id"] and f["section"] for f in m["formulas"])
    assert any(f["id"].startswith("skill:") for f in m["formulas"])
    dmg = [f for f in m["formulas"] if f.get("nonCrit")]
    assert dmg
    assert any(f["crit"] > f["avg"] > f["nonCrit"] > 0 for f in dmg)


def test_compute_level_95_beats_90(app):
    def skill(level):
        res = damage.run_sync("compute", {"members": [_at_level(level)], "only": [0]})
        return next(f["avg"] for f in res["members"][0]["formulas"] if f["id"].startswith("skill:"))
    a90, a95 = skill(90), skill(95)
    assert 0 < a90 < a95 < float("inf")


def test_run_sync_conditionals(app):
    out = damage.run_sync("conditionals", {"members": [_member()]})
    assert out
    char = [c for c in out if c["kind"] == "char"]
    assert char and all(c["src"] == "0" and c["states"] for c in out)
    labels = [damage.render_label(c["label"]) for c in out]
    assert all(labels) and not any("…" in t for t in labels)
    assert any(c["kind"] == "weapon" and c["section"] == "weapon" for c in out)


def test_conditional_changes_the_numbers(app):
    base = {"members": [_member()], "only": [0]}
    conds = damage.run_sync("conditionals", base)
    c = next(c for c in conds if c["kind"] == "char" and c["name"] == "burstFanfare")

    def burst(request):
        res = damage.run_sync("compute", request)["members"][0]["formulas"]
        return next(f["avg"] for f in res if f["id"].startswith("burst:"))
    on = burst({**base, "conditional": {c["sheet"]: {c["name"]: c["states"][-1]["value"]}}})
    assert on > burst(base)


def test_run_sync_optimize_sorted(app):
    def piece(i, **stats):
        return dict(id=i, GoldenTroupe=1, **stats)
    family = [[piece("a", hp=4780, critRate_=0.05), piece("b", hp=4780, critRate_=0.2)],
              [piece("c", atk=311, critDMG_=0.1), piece("d", atk=311, critDMG_=0.5)],
              [piece("e", hp_=0.466)], [piece("f", hydro_dmg_=0.466)],
              [piece("g", critRate_=0.311)]]
    target = {"member": 0, "frames": [{"id": "skill:1:0", "multiplier": 1}]}
    out = damage.run_sync("optimize", {"members": [_member()], "target": target,
                                       "minimums": [], "families": [family], "top": 3})
    values = [b["value"] for b in out["builds"]]
    assert len(values) == 3 and values == sorted(values, reverse=True)
    assert set(out["builds"][0]["ids"]) == {"b", "d", "e", "f", "g"}
    none = damage.run_sync("optimize", {"members": [_member()], "target": target,
                                        "minimums": [{"key": "enerRech_", "value": 1.5}],
                                        "families": [family], "top": 3})
    assert none["builds"] == []


def _run_requests(app, reqs, timeout=60000):
    """Issue (fn, payload) requests on one Engine; return ({id: result|exc}, ids, engine)."""
    from PySide6.QtCore import QEventLoop, QTimer
    eng = damage.Engine()
    got, order = {}, []
    loop = QEventLoop()

    def done(i, v):
        got[i] = v
        order.append(i)
        if len(got) == len(reqs):
            loop.quit()
    eng.finished.connect(done)
    eng.failed.connect(lambda i, msg: done(i, RuntimeError(msg)))
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout)
    ids = [eng.request(fn, payload) for fn, payload in reqs]
    loop.exec()
    timer.stop()
    return got, order, ids, eng


def test_engine_subprocess(app):
    from PySide6.QtCore import QProcess
    got, _order, ids, eng = _run_requests(app, [
        ("compute", {"members": [_member()], "only": [0], "modes": ["avg"]})])
    proc = eng._proc
    eng.shutdown()
    assert ids[0] in got and not isinstance(got[ids[0]], Exception)
    assert got[ids[0]]["members"][0]["stats"]["hp"] > 10000
    assert proc.state() == QProcess.NotRunning


def test_engine_bad_function(app):
    got, _order, ids, eng = _run_requests(app, [("nope", {})])
    eng.shutdown()
    assert isinstance(got[ids[0]], RuntimeError)
    assert "nope" in str(got[ids[0]])


def test_engine_back_to_back_in_order(app):
    reqs = [("conditionals", {"members": [_member()]}),
            ("nope", {}),
            ("compute", {"members": [_member()], "only": [0], "modes": ["avg"]})]
    got, order, ids, eng = _run_requests(app, reqs)
    eng.shutdown()
    assert order == ids
    assert got[ids[0]] and isinstance(got[ids[1]], RuntimeError)
    assert got[ids[2]]["members"][0]["stats"]["hp"] > 10000


def test_option_label_lunar_reactions():
    assert damage.option_label("lunarbloom") == "Lunar-Bloom"
    assert damage.option_label("lunarcharged") == "Lunar-Charged"
    assert damage.option_label("lunarcrystallize") == "Lunar-Crystallize"


def test_ascension_for():
    assert [damage.ascension_for(n) for n in (1, 20, 21, 40, 41, 50, 51, 60, 61, 70, 71, 80, 81, 90, 100)] == [
        0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 6]


def test_default_settings():
    s = damage.default_settings("Furina")
    assert s == {"level": 90, "constellation": 0, "auto": 9, "skill": 9, "burst": 9,
                 "weapon": "FavoniusSword", "weaponLevel": 90, "refinement": 1}
    assert damage.default_settings("Diluc")["weapon"] == "FavoniusGreatsword"
    assert damage.default_settings("Zhongli")["weapon"] == "FavoniusLance"
    assert damage.default_settings("Nahida")["weapon"] == "FavoniusCodex"
    assert damage.default_settings("Venti")["weapon"] == "FavoniusWarbow"
    assert damage.default_settings("TravelerAnemo")["weapon"] == "FavoniusSword"
    assert damage.default_settings("Nobody")["weapon"] == "FavoniusSword"


def test_member_from_settings():
    s = damage.default_settings("Venti")
    s.update(level=72, weaponLevel=45, refinement=3, constellation=2, burst=10)
    m = damage.member_from_settings("Venti", s)
    assert m == {
        "char": {"key": "Venti", "level": 72, "constellation": 2, "ascension": 5,
                 "talent": {"auto": 9, "skill": 9, "burst": 10}},
        "weapon": {"key": "FavoniusWarbow", "level": 45, "ascension": 2, "refinement": 3},
        "artifacts": [],
    }
