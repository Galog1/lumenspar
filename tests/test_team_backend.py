"""The Team & damage tab: pure helpers and the saved state (no engine calls)."""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from lumenspar import builds, damage
from lumenspar.ui import team_backend as T


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def _f(fid, section, label=None, avg=1.0, variant="hydro", **extra):
    name = {"ns": "sheet", "key": label} if label else None
    return dict({"id": fid, "section": section, "name": name, "variant": variant,
                 "subVariant": variant, "multi": None, "avg": avg}, **extra)


def test_formula_rows():
    fs = [_f("auto:1:0", "auto", "hitOp.electro", crit=2.0, nonCrit=0.5),
          _f("skill:1:0", "skill", "hitOp.electro"),
          _f("skill:1:1", "skill", "hitOp.electro"),            # same label again
          _f("skill:1:2", "skill", "hitOp.electro"),
          _f("burst:2:0", "burst", "hitOp.pyro", variant="heal"),
          _f("burst:2:1", "burst", None),                       # unnamed: from the id
          _f("burst:2:2", "burst", avg=None),                   # no value: skipped
          _f("passive1:1:0", "passive1", "hitOp.electro"),
          _f("reaction:overloaded", "reaction"),
          _f("reaction:bloom", "reaction"),
          _f("reaction:swirl_pyro", "reaction")]
    rows = T.formula_rows(fs, "Furina", "Pyro", {"pyro", "electro", "anemo"})
    assert [r["key"] for r in rows] == [
        "auto:1:0", "skill:1:0", "skill:1:1", "skill:1:2", "burst:2:0", "burst:2:1",
        "passive1:1:0", "reaction:overloaded"]
    by = {r["key"]: r for r in rows}
    assert by["auto:1:0"]["group"] == "Normal Attack"
    assert by["auto:1:0"]["label"] == "After dealing Electro DMG"
    assert by["auto:1:0"]["crit"] == 2.0 and by["auto:1:0"]["nonCrit"] == 0.5
    assert by["skill:1:0"]["crit"] is None
    assert [by[k]["label"] for k in ("skill:1:0", "skill:1:1", "skill:1:2")] == [
        "After dealing Electro DMG", "After dealing Electro DMG (2)", "After dealing Electro DMG (3)"]
    assert by["skill:1:0"]["group"].startswith("Elemental Skill")
    assert by["passive1:1:0"]["group"].startswith("Passive")
    assert by["auto:1:0"]["label"] == by["passive1:1:0"]["label"]       # other group: no suffix
    assert by["burst:2:0"]["q"] == "heal" and by["burst:2:0"]["label"] == "After dealing Pyro DMG"
    assert by["burst:2:1"]["label"] == "Burst:2:1"
    assert by["reaction:overloaded"]["group"] == "Reactions"
    assert by["reaction:overloaded"]["label"] == "Overloaded"
    assert by["auto:1:0"]["q"] == "dmg"
    # a hydro member of an anemo team gets Bloom only with dendro, and no pyro Swirl
    rows = T.formula_rows(fs, "Furina", "hydro", {"hydro", "dendro", "anemo"})
    assert [r["key"] for r in rows if r["group"] == "Reactions"] == ["reaction:bloom"]
    rows = T.formula_rows(fs, "Venti", "anemo", {"anemo", "pyro"})
    assert [r["key"] for r in rows if r["group"] == "Reactions"] == ["reaction:swirl_pyro"]


def test_formula_rows_shield():
    f = _f("skill:1:0", "skill", "hitOp.electro")
    f["name"] = "Shield DMG Absorption"
    assert T.formula_rows([f], "Furina", "hydro", set())[0]["q"] == "shield"


def _state_cond(src, sheet, name, kind, section, states, label="x"):
    return {"src": src, "sheet": sheet, "name": name, "label": label, "teamBuff": False,
            "kind": kind, "section": section,
            "states": [{"value": v, "label": None} for v in states]}


CONDS = [
    _state_cond("0", "Furina", "c1Cond", "char", "constellation1", ["1"],
                label={"ns": "sheet", "key": "hitOp.electro"}),
    _state_cond("0", "SplendorOfTranquilWaters", "stacks", "weapon", "weapon", ["1", "2", "3"]),
    _state_cond("1", "Bennett", "c6Cond", "char", "constellation6", ["1"]),
    _state_cond("0", "GoldenTroupe", "set4", "artifact", "GoldenTroupe:4", ["1"]),
    _state_cond("1", "ViridescentVenerer", "swirl", "artifact", "ViridescentVenerer:4",
                ["pyro", "hydro"]),
    _state_cond("0", "reso", "nearbyDendro1", "team", "resonance", ["1"]),
    _state_cond("0", "reso", "nearbyDendro2", "team", "resonance", ["1"]),
]


def test_condition_rows_order_names_and_values():
    state = {"Furina": {"Furina": {"c1Cond": "1"}},
             T.TEAM: {"reso": {"nearbyDendro1": "1"}},
             "Bennett": {"ViridescentVenerer": {"swirl": "hydro"}}}
    rows = T.condition_rows(CONDS, ["Furina", "Bennett"], ["Furina", "Bennett"], state)
    # member 0 (char, weapon, artifact), member 1 (char, artifact), then the team
    assert [r["id"] for r in rows] == [
        "0|Furina|c1Cond", "0|SplendorOfTranquilWaters|stacks", "0|GoldenTroupe|set4",
        "1|Bennett|c6Cond", "1|ViridescentVenerer|swirl",
        "0|reso|nearbyDendro1", "0|reso|nearbyDendro2"]
    by = {r["id"]: r for r in rows}
    assert by["0|Furina|c1Cond"]["member"] == "Furina"
    assert by["0|Furina|c1Cond"]["memberKey"] == "Furina"
    assert by["1|Bennett|c6Cond"]["member"] == "Bennett"
    assert by["0|reso|nearbyDendro1"]["member"] == "Team"
    assert by["0|reso|nearbyDendro1"]["memberKey"] == "_team"
    assert by["0|Furina|c1Cond"]["value"] == "1"
    assert by["0|reso|nearbyDendro1"]["value"] == "1"
    assert by["0|reso|nearbyDendro2"]["value"] is None
    c1 = by["0|Furina|c1Cond"]
    assert c1["type"] == "bool" and c1["onValue"] == "1"
    assert c1["label"] == "After dealing Electro DMG"
    assert c1["sheetTitle"].startswith("C1")
    assert by["0|Furina|c1Cond"]["detail"] == ""
    assert by["0|SplendorOfTranquilWaters|stacks"]["type"] == "list"
    assert by["0|SplendorOfTranquilWaters|stacks"]["sheetTitle"] == damage.sheet_title(
        "SplendorOfTranquilWaters")
    assert [o["value"] for o in by["0|SplendorOfTranquilWaters|stacks"]["options"]] == ["1", "2", "3"]
    assert by["0|GoldenTroupe|set4"]["sheetTitle"] == damage.sheet_title("GoldenTroupe") + " 4-piece"
    assert by["0|reso|nearbyDendro1"]["sheetTitle"] == "Elemental Resonance"
    swirl = by["1|ViridescentVenerer|swirl"]
    assert swirl["value"] == "hydro" and swirl["kind"] == "artifact"
    assert swirl["options"] == [{"value": "pyro", "label": "Pyro"},
                                {"value": "hydro", "label": "Hydro"}]


def test_condition_rows_member_before_team_even_if_listed_late():
    conds = [_state_cond("0", "reso", "x", "team", "resonance", ["1"]),
             _state_cond("1", "Bennett", "c6Cond", "char", "constellation6", ["1"])]
    rows = T.condition_rows(conds, ["A", "Bennett"], ["A", "B"], {})
    assert [r["sheet"] for r in rows] == ["Bennett", "reso"]


def test_condition_rows_duplicate_labels_are_told_apart():
    conds = [_state_cond("0", "Venti", "swirlPyro", "char", "burst", ["1"], label="Swirled"),
             _state_cond("0", "Venti", "swirlHydro", "char", "burst", ["1"], label="Swirled")]
    rows = T.condition_rows(conds, ["Venti"], ["Venti"], {})
    assert [r["label"] for r in rows] == ["Swirled (Swirl Pyro)", "Swirled (Swirl Hydro)"]


def test_stat_rows():
    stats = {"hp": 21345.6, "atk": 1234.4, "def": 800, "eleMas": 120.2, "critRate_": 0.655,
             "critDMG_": 1.31, "enerRech_": 1.123, "heal_": 0, "hydro_dmg_": 0.466,
             "pyro_dmg_": 0, "physical_dmg_": 0.05, "cryo_dmg_": 0.1}
    rows = T.stat_rows(stats, "hydro")
    by = {r["label"]: r["text"] for r in rows}
    assert by["Max HP"] == "21,346"
    assert by["ATK"] == "1,234"
    assert by["DEF"] == "800"
    assert by["Elemental Mastery"] == "120"
    assert by["CRIT Rate"] == "65.5%"
    assert by["CRIT DMG"] == "131.0%"
    assert by["Energy Recharge"] == "112.3%"
    assert "Healing Bonus" not in by
    assert by["Hydro DMG Bonus"] == "46.6%"
    assert by["Cryo DMG Bonus"] == "10.0%"
    assert by["Physical DMG Bonus"] == "5.0%"
    assert "Pyro DMG Bonus" not in by
    assert [r["label"] for r in rows][:2] == ["Max HP", "ATK"]
    assert T.stat_rows(dict(stats, heal_=0.25), "hydro")[7]["text"] == "25.0%"


def test_stat_rows_own_element_always_shown():
    by = {r["label"]: r["text"] for r in T.stat_rows({"hp": 1}, "Pyro")}
    assert by["Pyro DMG Bonus"] == "0.0%"


# -- saved state ---------------------------------------------------------------------

def _make(tmp_path, monkeypatch, state_name="team.json"):
    good = {
        "characters": [
            {"key": "Furina", "level": 90, "ascension": 6, "constellation": 0,
             "talent": {"auto": 9, "skill": 9, "burst": 9}},
            {"key": "Bennett", "level": 80, "ascension": 6, "constellation": 1,
             "talent": {"auto": 6, "skill": 6, "burst": 6}},
        ],
        "weapons": [
            {"key": "SplendorOfTranquilWaters", "level": 90, "ascension": 6,
             "refinement": 1, "location": "Furina"},
            {"key": "Skyward", "level": 90, "ascension": 6, "refinement": 1,
             "location": "Bennett"},
        ],
        "artifacts": [],
    }
    export = tmp_path / "scan.GOOD.json"
    export.write_text(json.dumps(good), encoding="utf-8")
    monkeypatch.setattr(builds, "latest", lambda *a, **k: None)
    settings = SimpleNamespace(export_path=export)
    b = T.TeamBackend(settings, state_path=tmp_path / state_name)
    b._timer.stop()
    return settings, b


def test_candidates_come_from_the_scan(app, tmp_path, monkeypatch):
    _, b = _make(tmp_path, monkeypatch)
    cands = b.owned
    assert [c["key"] for c in cands] == ["Bennett", "Furina"]
    assert all(c["source"] == "scan" for c in cands)
    assert b.members == [{}, {}, {}, {}]
    assert b._engine is None


def test_state_round_trip(app, tmp_path, monkeypatch):
    settings, b = _make(tmp_path, monkeypatch)
    b.setMember(0, "Furina")
    b.setMember(1, "Bennett")
    b.setMember(2, "Nobody")           # not offered: ignored
    b.select(1)
    b._cond_rows = T.condition_rows(CONDS, ["Furina", "Bennett"], ["Furina", "Bennett"],
                                    b._state["conditionals"])
    b._conds = (CONDS, ["Furina", "Bennett"], ["Furina", "Bennett"])
    b.setConditional("0|Furina|c1Cond", True)
    b.setConditional("0|SplendorOfTranquilWaters|stacks", 2)
    b.setConditional("1|ViridescentVenerer|swirl", "hydro")
    b.setConditional("0|reso|nearbyDendro1", 1)
    b._timer.stop()

    saved = json.loads((tmp_path / "team.json").read_text(encoding="utf-8"))
    assert saved["members"] == [{"key": "Furina", "source": "owned"},
                                {"key": "Bennett", "source": "owned"}, {}, {}]
    assert saved["selected"] == 1
    assert "rotation" not in saved and "enemy" not in saved
    assert saved["conditionals"]["Furina"] == {"Furina": {"c1Cond": "1"},
                                               "SplendorOfTranquilWaters": {"stacks": "2"}}
    assert saved["conditionals"]["Bennett"] == {"ViridescentVenerer": {"swirl": "hydro"}}
    assert saved["conditionals"]["_team"] == {"reso": {"nearbyDendro1": "1"}}

    # removing values
    b.setConditional("0|Furina|c1Cond", False)
    b.setConditional("0|SplendorOfTranquilWaters|stacks", "")
    b.setConditional("1|ViridescentVenerer|swirl", "")
    b._timer.stop()
    assert b._state["conditionals"] == {"_team": {"reso": {"nearbyDendro1": "1"}}}

    b2 = T.TeamBackend(settings, state_path=tmp_path / "team.json")
    b2._timer.stop()
    assert b2._state == b._state
    assert [m.get("key") for m in b2.members] == ["Furina", "Bennett", None, None]
    assert b2.selected == 1
    assert b2._engine is None


def test_set_member_moves_and_clears(app, tmp_path, monkeypatch):
    _, b = _make(tmp_path, monkeypatch)
    b.setMember(0, "Furina")
    b.setMember(2, "Furina")
    assert b._state["members"] == [{}, {}, {"key": "Furina", "source": "owned"}, {}]
    b.setMember(2, "")
    assert b._state["members"] == [{}, {}, {}, {}]
    b._timer.stop()


def test_formulas_rows(app, tmp_path, monkeypatch):
    _, b = _make(tmp_path, monkeypatch)
    b.setMember(0, "Furina")
    b._raw_key = "Furina"
    b._raw_formulas = [_f("burst:1:0", "burst", "hitOp.electro", avg=10.0)]
    b._timer.stop()
    rows = b.formulas
    assert rows[0]["key"] == "burst:1:0" and "count" not in rows[0]
    assert rows[0]["group"].startswith("Elemental Burst")
    assert rows[0]["crit"] is None


def test_corrupt_or_missing_state_means_defaults(app, tmp_path, monkeypatch):
    path = tmp_path / "team.json"
    path.write_text("{not json", encoding="utf-8")
    _, b = _make(tmp_path, monkeypatch)
    assert b._state == T._default_state()
    path.write_text(json.dumps({"members": ["Furina", "Furina", 5], "selected": 9,
                                "enemy": {"level": "x"}, "seconds": -1, "rotation": {"Furina": {"a": 2}},
                                "conditionals": {"Furina": {"Furina": {"c1Cond": "1", "old": 1, "n": 2.5,
                                                                      "flag": True}}}}),
                    encoding="utf-8")
    state = T._load_state(path)
    assert state["members"] == [{"key": "Furina", "source": "owned"}, {}, {}, {}]
    assert state["selected"] == 0
    assert "rotation" not in state and "seconds" not in state and "enemy" not in state
    # strings and positive ints (old toggles, migrated later) survive
    assert state["conditionals"] == {"Furina": {"Furina": {"c1Cond": "1", "old": "1"}}}


# -- the full character list -----------------------------------------------------------

def test_old_string_members_migrate(app, tmp_path):
    path = tmp_path / "team.json"
    path.write_text(json.dumps({"members": ["Furina", "", "Bennett"]}), encoding="utf-8")
    state = T._load_state(path)
    assert state["members"] == [{"key": "Furina", "source": "owned"}, {},
                                {"key": "Bennett", "source": "owned"}, {}]
    assert state["settings"] == {}


def test_all_characters(app, tmp_path, monkeypatch):
    _, b = _make(tmp_path, monkeypatch)
    allc = b.allCharacters
    by = {c["key"]: c for c in allc}
    assert by["Furina"]["name"] == "Furina" and by["Furina"]["element"] == "hydro"
    assert by["TravelerAnemo"]["name"] == "Traveler (Anemo)"
    assert "Manekin" not in by
    names = [c["name"].lower() for c in allc]
    assert names == sorted(names)
    assert len(allc) > 80


def test_set_member_game_creates_default_settings(app, tmp_path, monkeypatch):
    _, b = _make(tmp_path, monkeypatch)
    b.setMember(1, "Venti", "game")
    b.setMember(2, "Nobody", "game")       # not in the game list: ignored
    b.setMember(3, "Venti", "owned")       # not owned: ignored
    b._timer.stop()
    assert b._state["members"][1] == {"key": "Venti", "source": "game"}
    assert b._state["members"][2] == {} and b._state["members"][3] == {}
    assert b._state["settings"]["Venti"] == damage.default_settings("Venti")
    m = b.members[1]
    assert m["source"] == "game" and m["settings"]["weapon"] == "FavoniusWarbow"
    assert m["name"] == "Venti"
    entry = b._entry("Venti")
    assert entry["member"] == damage.member_from_settings("Venti", b._state["settings"]["Venti"])
    assert b._active() == [(1, "Venti")]
    # removing keeps the settings; re-adding restores them
    b.setSetting(1, "constellation", 4)
    b.setMember(1, "")
    assert b._state["settings"]["Venti"]["constellation"] == 4
    b.setMember(0, "Venti", "game")
    b._timer.stop()
    assert b.members[0]["settings"]["constellation"] == 4
    # moving a game character between slots
    assert b._state["members"][1] == {}


def test_set_setting_clamps_and_persists(app, tmp_path, monkeypatch):
    settings, b = _make(tmp_path, monkeypatch)
    b.setMember(0, "Venti", "game")
    b.setSetting(0, "level", 500)
    b.setSetting(0, "constellation", -3)
    b.setSetting(0, "auto", 0)
    b.setSetting(0, "skill", 11)
    b.setSetting(0, "burst", "7")
    b.setSetting(0, "weaponLevel", 200)
    b.setSetting(0, "refinement", 9)
    b.setSetting(0, "weapon", "SkywardHarp")
    b.setSetting(0, "weapon", "Skyward")          # not a bow: ignored
    b.setSetting(0, "bogus", 1)
    b.setSetting(1, "level", 5)                   # empty slot: ignored
    b._timer.stop()
    s = b._state["settings"]["Venti"]
    assert s == {"level": 100, "constellation": 0, "auto": 1, "skill": 10, "burst": 7,
                 "weapon": "SkywardHarp", "weaponLevel": 90, "refinement": 5}
    b.setMember(1, "Furina", "owned")
    b.setSetting(1, "constellation", 5)           # scan member: not editable
    b._timer.stop()
    assert not any(k.startswith("scan:") or k == "Furina" for k in b._state["settings"])
    assert b.members[1]["settings"]["constellation"] == 0

    b2 = T.TeamBackend(settings, state_path=tmp_path / "team.json")
    b2._timer.stop()
    fixed = dict(s, level=90, auto=9, skill=9, burst=9, weaponLevel=90)   # full-list members stay maxed
    assert b2._state["settings"]["Venti"] == fixed
    assert b2.members[0]["settings"] == fixed
    assert b2._state["members"][1] == {"key": "Furina", "source": "owned"}
    member = b2._entry("Venti")["member"]
    assert member["weapon"] == {"key": "SkywardHarp", "level": 90, "ascension": 6, "refinement": 5}


def test_weapon_choices(app, tmp_path, monkeypatch):
    _, b = _make(tmp_path, monkeypatch)
    assert b.weaponChoices == []
    b.setMember(0, "Venti", "game")
    b._timer.stop()
    keys = [w["key"] for w in b.weaponChoices]
    assert "SkywardHarp" in keys and "Skyward" not in keys
    rarities = [w["rarity"] for w in b.weaponChoices]
    assert rarities == sorted(rarities, reverse=True)


def test_ensure_portraits_downloads_once(app, tmp_path, monkeypatch):
    from lumenspar.wishes import icons
    _, b = _make(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(icons, "missing_assets", lambda names: ["UI_AvatarIcon_Venti"])
    monkeypatch.setattr(icons, "download", lambda names: calls.append(list(names)) or 1)
    b._portraits_started = False      # the startup call may already have run
    b.ensurePortraits()
    b._portraits_thread.join(5)
    assert calls and calls[-1] == ["UI_AvatarIcon_Venti"]
    before = len(calls)
    b.ensurePortraits()               # a second call on the same backend does nothing
    assert len(calls) == before


# -- all scanned characters, per-member reactions -------------------------------------

def _make3(tmp_path, monkeypatch):
    good = {
        "characters": [
            {"key": "Furina", "level": 80, "ascension": 6, "constellation": 2,
             "talent": {"auto": 5, "skill": 6, "burst": 7}},
            {"key": "Xiangling", "level": 70, "ascension": 4, "constellation": 0,
             "talent": {"auto": 1, "skill": 2, "burst": 3}},
            {"key": "Zhongli", "level": 90, "ascension": 6, "constellation": 0,
             "talent": {"auto": 9, "skill": 9, "burst": 9}},
        ],
        "weapons": [{"key": "SplendorOfTranquilWaters", "level": 85, "ascension": 6,
                     "refinement": 3, "location": "Furina"}],
        "artifacts": [],
    }
    export = tmp_path / "scan3.GOOD.json"
    export.write_text(json.dumps(good), encoding="utf-8")
    monkeypatch.setattr(builds, "latest", lambda *a, **k: None)
    b = T.TeamBackend(SimpleNamespace(export_path=export), state_path=tmp_path / "t3.json")
    b._timer.stop()
    return b


def test_owned_lists_every_scanned_character(app, tmp_path, monkeypatch):
    b = _make3(tmp_path, monkeypatch)
    assert [c["key"] for c in b.owned] == ["Furina", "Xiangling", "Zhongli"]
    assert all(c["source"] == "scan" for c in b.owned)


def test_scan_member_settings_prefilled(app, tmp_path, monkeypatch):
    b = _make3(tmp_path, monkeypatch)
    b.setMember(0, "Furina")
    b.setMember(1, "Xiangling")
    b._timer.stop()
    s = b.members[0]["settings"]
    assert (s["level"], s["constellation"], s["auto"], s["skill"], s["burst"]) == (80, 2, 5, 6, 7)
    assert (s["weapon"], s["weaponLevel"], s["refinement"]) == ("SplendorOfTranquilWaters", 85, 3)
    x = b.members[1]
    assert x["source"] == "scan"
    assert x["settings"]["weapon"] == damage.default_settings("Xiangling")["weapon"]
    assert x["settings"]["level"] == 70
    b.setSetting(1, "level", 60)                  # scan members are not editable
    assert b._entry("Xiangling")["member"]["char"]["level"] == 70
    assert b._entry("Xiangling")["member"]["artifacts"] == []


def test_reaction_per_member(app, tmp_path, monkeypatch):
    b = _make3(tmp_path, monkeypatch)
    b.setMember(0, "Furina")
    b.setMember(1, "Xiangling")
    b.select(1)
    b._timer.stop()
    assert [o["value"] for o in b.reactionOptions] == ["", "vaporize"]
    b.setReaction("melt")                       # not allowed: ignored
    assert b.reaction == ""
    b.setReaction("vaporize")
    b._timer.stop()
    assert b.reaction == "vaporize"
    active = b._active()
    p = b._payload(active, [1], ["avg"])
    assert p["reactions"] == ["", "vaporize"]
    assert "amp" not in p["enemy"] and "cata" not in p["enemy"]
    assert b.optimize_context("Xiangling")["reactions"] == ["", "vaporize"]
    b.setMember(0, "")                          # team changed: choice no longer allowed
    assert b.reaction == ""
    assert b._payload(b._active(), [0], ["avg"])["reactions"] == [""]


def test_payload_merges_conditionals_of_the_whole_team(app, tmp_path, monkeypatch):
    b = _make3(tmp_path, monkeypatch)
    b.setMember(0, "Furina")
    b.setMember(1, "Xiangling")
    b._timer.stop()
    b._state["conditionals"] = {"Furina": {"Furina": {"a": "1"}},
                                "Xiangling": {"Furina": {"b": "2"}, "Xiangling": {"c": "3"}},
                                T.TEAM: {"reso": {"d": "1"}}}
    p = b._payload(b._active(), [0], ["avg"])
    assert p["conditional"] == {"Furina": {"a": "1", "b": "2"}, "Xiangling": {"c": "3"},
                                "reso": {"d": "1"}}
    ctx = b.optimize_context("Xiangling")
    assert ctx["conditional"] == p["conditional"] and ctx["index"] == 1
    assert ctx["formulas"] == [] and ctx["rows"] == []


def test_set_conditional_bool_and_list(app, tmp_path, monkeypatch):
    _, b = _make(tmp_path, monkeypatch)
    b._conds = (CONDS, ["Furina", "Bennett"], ["Furina", "Bennett"])
    b._cond_rows = T.condition_rows(*b._conds, b._state["conditionals"])
    b.setConditional("0|Furina|c1Cond", True)
    b.setConditional("0|SplendorOfTranquilWaters|stacks", 3)
    b._timer.stop()
    assert b._state["conditionals"]["Furina"] == {"Furina": {"c1Cond": "1"},
                                                  "SplendorOfTranquilWaters": {"stacks": "3"}}
    b.setConditional("0|Furina|c1Cond", False)
    b.setConditional("0|SplendorOfTranquilWaters|stacks", "")
    b._timer.stop()
    assert b._state["conditionals"] == {}


def test_old_enemy_and_rotation_state_ignored(app, tmp_path, monkeypatch):
    (tmp_path / "old.json").write_text(json.dumps(
        {"enemy": {"level": 90, "res": 15}, "rotation": {"A": {"A:b": 2}}, "seconds": 9}),
        encoding="utf-8")
    state = T._load_state(tmp_path / "old.json")
    assert state == T._default_state()
    _, b = _make(tmp_path, monkeypatch)
    b.setMember(0, "Furina")
    b._timer.stop()
    assert b._payload(b._active(), [0], ["avg"])["enemy"]["level"] == 100
    assert b._payload(b._active(), [0], ["avg"])["enemy"]["res"] == pytest.approx(0.1)


def test_long_option_lists_are_thinned():
    from lumenspar.ui.team_backend import _thin
    opts = [str(v) for v in range(10, 205, 5)]        # 39 options
    out = _thin(opts)
    assert len(out) == 8 and out[0] == "10" and out[-1] == "200"
    assert _thin(["a", "b"]) == ["a", "b"]


# -- Akasha combo -----------------------------------------------------------------------

def _combo_setup(tmp_path, monkeypatch):
    from lumenspar import akasha
    _, b = _make(tmp_path, monkeypatch)
    b.setMember(0, "Furina")
    b._timer.stop()
    boards = [akasha.Board(name="Burst nuke", short="Nuke", details="d", calculation_id="c1",
                           weapon="Other Sword", refinement=1, default_variant="", variants=[]),
              akasha.Board(name="Skill combo", short="Skill", details="dd", calculation_id="c2",
                           weapon="Splendor of Tranquil Waters", refinement=1,
                           default_variant="v", variants=[])]
    seen = []
    monkeypatch.setattr(akasha, "boards", lambda aid: boards)
    monkeypatch.setattr(akasha, "combo", lambda cid, variant="": (
        seen.append(cid) or [akasha.Hit(name="Salon Solitaire DMG", quantity=2.0,
                                        kind="x", value=100.0)]))
    monkeypatch.setattr(T, "_avatar_ids", lambda: {"Furina": "10000089"})
    rows = [{"key": "skill:1", "label": "Salon Solitaire", "group": "Skill", "q": "dmg", "avg": 100.0}]
    monkeypatch.setattr(T, "formula_rows", lambda *a, **k: rows)
    b._raw_key = "Furina"
    b._formulas_by_key["Furina"] = [{"id": "skill:1"}]
    return b, seen


def test_combo_loads_picks_weapon_board_and_matches(app, tmp_path, monkeypatch):
    b, seen = _combo_setup(tmp_path, monkeypatch)
    b._combo_work("Furina", "", "Splendor of Tranquil Waters", [])
    c = b.combo
    assert c["board"] == "c2" and seen == ["c2"]
    assert [x["id"] for x in c["boards"]] == ["c1", "c2"]
    assert c["boards"][1]["label"] == "Skill · Splendor of Tranquil Waters"
    assert c["hits"][0]["label"] == "Salon Solitaire DMG × 2"
    assert c["hits"][0]["matched"] == "Salon Solitaire"
    assert c["total"] == 200.0 and c["missing"] == 0
    ctx = b.optimize_context("Furina")
    assert ctx["combo"] == [{"id": "skill:1", "multiplier": 2.0}]
    assert ctx["comboTitle"] == "Skill combo"


def test_combo_board_choice_is_saved(app, tmp_path, monkeypatch):
    b, seen = _combo_setup(tmp_path, monkeypatch)
    b._combo_work("Furina", "", "Splendor of Tranquil Waters", [])
    b.setComboBoard("c1")
    b._combo_threads["Furina"].join()
    assert json.loads((tmp_path / "team.json").read_text(encoding="utf-8"))["combo"] == {"Furina": "c1"}
    assert b._state["combo"] == {"Furina": "c1"}
    b._combo_work("Furina", "c1", "x", [])
    assert b.combo["board"] == "c1"
    b.setComboBoard("nope")
    assert b._state["combo"] == {"Furina": "c1"}


def test_combo_error_and_unknown_character(app, tmp_path, monkeypatch):
    from lumenspar import akasha
    b, _ = _combo_setup(tmp_path, monkeypatch)

    def boom(cid, variant=""):
        raise akasha.AkashaError("no breakdown")
    monkeypatch.setattr(akasha, "combo", boom)
    b._combo_work("Furina", "", "", [])
    assert b.combo["error"] == "no breakdown" and "hits" not in b.combo
    assert b.optimize_context("Furina")["combo"] == []
    monkeypatch.setattr(T, "_avatar_ids", lambda: {})
    b._combo_work("Furina", "", "", [])
    assert "no leaderboard" in b.combo["error"]


def test_avatar_ids_skip_variants():
    ids = T._avatar_ids()
    assert ids["Jean"] == "10000003"
    assert "TravelerPyro" not in ids


def test_fix_conditionals_migrates_old_values():
    conds = [{"sheet": "Flins", "name": "c2AfterElectro", "states": [{"value": "on"}]},
             {"sheet": "Columbina", "name": "a1Stacks",
              "states": [{"value": "1"}, {"value": "2"}, {"value": "3"}]},
             {"sheet": "Sucrose", "name": "absorption",
              "states": [{"value": "hydro"}, {"value": "electro"}]}]
    state = {"Flins": {"Flins": {"c2AfterElectro": "1"}},
             "Columbina": {"Columbina": {"a1Stacks": "3", "gone": "1"}},
             "Sucrose": {"Sucrose": {"absorption": "anemo"}},
             "_team": {"static": {"hasShield": "1"}}}
    assert T.fix_conditionals(conds, state)
    assert state == {"Flins": {"Flins": {"c2AfterElectro": "on"}},
                     "Columbina": {"Columbina": {"a1Stacks": "3", "gone": "1"}},
                     "_team": {"static": {"hasShield": "1"}}}
    assert not T.fix_conditionals(conds, state)
