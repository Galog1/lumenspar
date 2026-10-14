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


def test_formula_group():
    assert T.formula_group({"q": "heal", "move": "skill"}) == "Healing"
    assert T.formula_group({"q": "shield", "move": "burst"}) == "Shield"
    assert T.formula_group({"q": "dmg", "move": "normal"}) == "Normal Attack"
    assert T.formula_group({"q": "dmg", "move": "charged"}) == "Charged Attack"
    assert T.formula_group({"q": "dmg", "move": "plunging"}) == "Plunging Attack"
    assert T.formula_group({"q": "dmg", "move": "skill"}) == "Elemental Skill"
    assert T.formula_group({"q": "dmg", "move": "burst"}) == "Elemental Burst"
    assert T.formula_group({"q": "dmg", "move": ""}) == "Other"
    assert T.formula_group({"q": "dmg"}) == "Other"


CONDS = [
    {"src": "0", "sheet": "Furina", "name": "c1Cond", "type": "bool"},
    {"src": "0", "sheet": "SplendorOfTranquilWaters", "name": "stacks", "type": "num",
     "min": 0, "max": 3},
    {"src": "1", "sheet": "Bennett", "name": "c6Cond", "type": "bool"},
    {"src": "0", "sheet": "GoldenTroupe", "name": "set4", "type": "bool"},
    {"src": "1", "sheet": "ViridescentVenerer", "name": "swirl", "type": "list",
     "list": ["pyro", "hydro"]},
    {"src": "0", "sheet": "reso", "name": "nearbyDendro1", "type": "bool"},
    {"src": "1", "sheet": "reso", "name": "nearbyDendro1", "type": "bool"},
    {"src": "0", "sheet": "static", "name": "enemyFrozen", "type": "bool"},
]


def test_condition_rows_order_names_and_values():
    state = {"Furina": {"Furina": {"c1Cond": 1}},
             T.TEAM: {"reso": {"nearbyDendro1": 1}},
             "Bennett": {"ViridescentVenerer": {"swirl": "hydro"}}}
    rows = T.condition_rows(CONDS, ["Furina", "Bennett"], ["Furina", "Bennett"], state)
    # member 0 (char, weapon, artifact), member 1 (char, artifact), then the team, once each
    assert [r["id"] for r in rows] == [
        "0|Furina|c1Cond", "0|SplendorOfTranquilWaters|stacks", "0|GoldenTroupe|set4",
        "1|Bennett|c6Cond", "1|ViridescentVenerer|swirl",
        "0|reso|nearbyDendro1", "0|static|enemyFrozen"]
    by_id = {r["id"]: r for r in rows}
    assert by_id["0|Furina|c1Cond"]["member"] == "Furina"
    assert by_id["0|Furina|c1Cond"]["memberKey"] == "Furina"
    assert by_id["1|Bennett|c6Cond"]["member"] == "Bennett"
    assert by_id["0|reso|nearbyDendro1"]["member"] == "Team"
    assert by_id["0|reso|nearbyDendro1"]["memberKey"] == "_team"
    assert by_id["0|Furina|c1Cond"]["value"] == 1
    assert by_id["0|reso|nearbyDendro1"]["value"] == 1
    assert by_id["0|static|enemyFrozen"]["value"] is None
    assert by_id["0|SplendorOfTranquilWaters|stacks"]["max"] == 3
    swirl = by_id["1|ViridescentVenerer|swirl"]
    assert swirl["value"] == "hydro"
    assert swirl["options"] == [{"value": "pyro", "label": "Pyro"},
                                {"value": "hydro", "label": "Hydro"}]
    assert by_id["0|Furina|c1Cond"]["label"]
    assert by_id["0|Furina|c1Cond"]["sheetTitle"]


def test_condition_rows_member_before_team_even_if_listed_late():
    conds = [{"src": "0", "sheet": "reso", "name": "x", "type": "bool"},
             {"src": "1", "sheet": "Bennett", "name": "c6Cond", "type": "bool"}]
    rows = T.condition_rows(conds, ["A", "Bennett"], ["A", "B"], {})
    assert [r["sheet"] for r in rows] == ["Bennett", "reso"]


def test_stat_rows():
    stats = {"hp": 21345.6, "atk": 1234.4, "def": 800, "eleMas": 120.2, "critRate_": 0.655,
             "critDMG_": 1.31, "enerRech_": 0.123, "heal_": 0, "hydro_dmg_": 0.466,
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


def test_rotation_total():
    formulas = [{"sheet": "Furina", "name": "skill_a", "avg": 100.0},
                {"sheet": "Furina", "name": "burst", "avg": 2500.5},
                {"sheet": "Furina", "name": "heal", "avg": None},
                {"sheet": "Furina", "name": "unused", "avg": 7}]
    counts = {"Furina:skill_a": 3, "Furina:burst": 2, "Furina:heal": 4, "Other:x": 9}
    assert T.rotation_total(formulas, counts) == pytest.approx(300 + 5001.0)
    assert T.rotation_total(formulas, {}) == 0


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
    b.setCount("Bennett:skill_a", 3)
    b.setSeconds(25.0)
    b.setEnemy(95, 20.0, "pyro", "")
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
    assert saved["rotation"] == {"Bennett": {"Bennett:skill_a": 3}}
    assert saved["seconds"] == 25.0
    assert saved["enemy"] == {"level": 95, "res": 20.0, "amp": "pyro", "cata": ""}
    assert saved["conditionals"]["Furina"] == {"Furina": {"c1Cond": 1},
                                               "SplendorOfTranquilWaters": {"stacks": 2}}
    assert saved["conditionals"]["Bennett"] == {"ViridescentVenerer": {"swirl": "hydro"}}
    assert saved["conditionals"]["_team"] == {"reso": {"nearbyDendro1": 1}}

    # removing values
    b.setConditional("0|Furina|c1Cond", False)
    b.setConditional("0|SplendorOfTranquilWaters|stacks", 0)
    b.setConditional("1|ViridescentVenerer|swirl", "")
    b.setCount("Bennett:skill_a", 0)
    b._timer.stop()
    assert b._state["conditionals"] == {"_team": {"reso": {"nearbyDendro1": 1}}}
    assert b._state["rotation"] == {}

    b2 = T.TeamBackend(settings, state_path=tmp_path / "team.json")
    b2._timer.stop()
    assert b2._state == b._state
    assert [m.get("key") for m in b2.members] == ["Furina", "Bennett", None, None]
    assert b2.selected == 1
    assert b2.enemy["level"] == 95
    assert b2._engine is None


def test_set_member_moves_and_clears(app, tmp_path, monkeypatch):
    _, b = _make(tmp_path, monkeypatch)
    b.setMember(0, "Furina")
    b.setMember(2, "Furina")
    assert b._state["members"] == [{}, {}, {"key": "Furina", "source": "owned"}, {}]
    b.setMember(2, "")
    assert b._state["members"] == [{}, {}, {}, {}]
    b._timer.stop()


def test_formulas_carry_counts(app, tmp_path, monkeypatch):
    _, b = _make(tmp_path, monkeypatch)
    b.setMember(0, "Furina")
    b.setCount("Furina:burst", 2)
    b._raw_key = "Furina"
    b._raw_formulas = [{"sheet": "Furina", "name": "burst", "move": "burst", "q": "dmg",
                        "ele": "hydro", "avg": 10.0}]
    b._timer.stop()
    rows = b.formulas
    assert rows[0]["key"] == "Furina:burst" and rows[0]["count"] == 2
    assert rows[0]["group"] == "Elemental Burst"
    assert rows[0]["crit"] is None
    assert b.rotation["stale"] is True


def test_corrupt_or_missing_state_means_defaults(app, tmp_path, monkeypatch):
    path = tmp_path / "team.json"
    path.write_text("{not json", encoding="utf-8")
    _, b = _make(tmp_path, monkeypatch)
    assert b._state == T._default_state()
    path.write_text(json.dumps({"members": ["Furina", "Furina", 5], "selected": 9,
                                "enemy": {"level": "x"}, "seconds": -1,
                                "conditionals": {"Furina": {"Furina": {"c1Cond": 1}}}}),
                    encoding="utf-8")
    state = T._load_state(path)
    assert state["members"] == [{"key": "Furina", "source": "owned"}, {}, {}, {}]
    assert state["selected"] == 0 and state["seconds"] == 20.0
    assert state["conditionals"] == {"Furina": {"Furina": {"c1Cond": 1}}}


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
    b.setSetting(1, "level", 80)
    b.setMember(1, "")
    assert b._state["settings"]["Venti"]["level"] == 80
    b.setMember(0, "Venti", "game")
    b._timer.stop()
    assert b.members[0]["settings"]["level"] == 80
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
    b.setSetting(1, "level", 5)                   # owned member: ignored
    b._timer.stop()
    assert "Furina" not in b._state["settings"]

    b2 = T.TeamBackend(settings, state_path=tmp_path / "team.json")
    b2._timer.stop()
    assert b2._state["settings"]["Venti"] == s
    assert b2.members[0]["settings"] == s
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
    b.ensurePortraits()
    b._portraits_thread.join(5)
    QCoreApplication.processEvents()
    b.ensurePortraits()
    assert calls == [["UI_AvatarIcon_Venti"]]
