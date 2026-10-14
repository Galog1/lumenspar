"""QML bridge for the Optimizer's "Team & damage" tab.

A team of up to four characters, the conditional toggles of the whole team,
enemy settings, each character's damage per hit and a rotation (hit counts)
giving damage and DPS. The numbers come from the bundled Genshin Optimizer
formula engine (lumenspar.damage), which runs on its own thread; this module
only builds its requests, debounces them and publishes the results.

The state (team, toggles, enemy, rotation) is saved to team.json.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .. import builds, damage
from ..config import DATA_DIR
from ..wishes import icons
from .builds_backend import _url

MOVE_GROUPS = {"normal": "Normal Attack", "charged": "Charged Attack",
               "plunging": "Plunging Attack", "skill": "Elemental Skill",
               "burst": "Elemental Burst"}

TEAM = "_team"                      # state key of the team-wide conditionals
TEAM_SHEETS = ("reso", "static")
SLOTS = 4
_KIND_ORDER = {"char": 0, "weapon": 1, "artifact": 2}
_ELEMENTS = ("pyro", "hydro", "electro", "cryo", "anemo", "geo", "dendro", "physical")


# -- pure helpers ---------------------------------------------------------------

def formula_group(f: dict) -> str:
    """The heading a formula is listed under."""
    if f.get("q") == "heal":
        return "Healing"
    if f.get("q") == "shield":
        return "Shield"
    return MOVE_GROUPS.get(f.get("move"), "Other")


def condition_rows(conds: list[dict], keys: list[str], names: list[str], state: dict) -> list[dict]:
    """One row per conditional the engine lists, in display order.

    Members come in slot order and, within a member, the character's own
    conditions first, then the weapon's, then the artifact sets'. Team-wide
    sheets are listed once, last, and their state lives under "_team".
    """
    member_rows: list[tuple[int, int, int, dict]] = []
    team_rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for n, c in enumerate(conds):
        sheet, name = c["sheet"], c["name"]
        team = sheet in TEAM_SHEETS
        if team:
            if (sheet, name) in seen:
                continue
            seen.add((sheet, name))
            member, member_key, store = "Team", TEAM, TEAM
        else:
            src = int(c["src"])
            member, member_key, store = names[src], keys[src], keys[src]
        kind = damage.sheet_kind(sheet)
        row = {
            "id": f"{c['src']}|{sheet}|{name}",
            "member": member,
            "memberKey": member_key,
            "sheet": sheet,
            "sheetTitle": damage.sheet_title(sheet),
            "kind": kind,
            "name": name,
            "label": damage.cond_label(sheet, name),
            "detail": damage.cond_detail(sheet, name),
            "type": c.get("type"),
            "min": c.get("min"),
            "max": c.get("max"),
            "options": [{"value": v, "label": damage.option_label(v)} for v in c.get("list", [])],
            "value": ((state.get(store) or {}).get(sheet) or {}).get(name),
        }
        if team:
            team_rows.append(row)
        else:
            member_rows.append((int(c["src"]), _KIND_ORDER.get(kind, 3), n, row))
    member_rows.sort(key=lambda t: t[:3])
    rows = [r for *_, r in member_rows] + team_rows
    # GO sometimes gives several conditions of one sheet the same text
    # (e.g. Venti's per-element Stormeye swirls); tell them apart.
    seen: dict[tuple, int] = {}
    for r in rows:
        k = (r["memberKey"], r["sheet"], r["label"])
        seen[k] = seen.get(k, 0) + 1
    for r in rows:
        if seen[(r["memberKey"], r["sheet"], r["label"])] > 1:
            r["label"] = f"{r['label']} ({damage.humanize(r['name'])})"
    return rows


def _whole(v: float) -> str:
    return f"{v:,.0f}"


def _pct(v: float) -> str:
    return f"{v:.1f}%"


def stat_rows(stats: dict, element: str) -> list[dict]:
    """The selected member's computed stats as label/text rows."""
    g = stats.get
    rows = [
        {"label": "Max HP", "text": _whole(g("hp", 0))},
        {"label": "ATK", "text": _whole(g("atk", 0))},
        {"label": "DEF", "text": _whole(g("def", 0))},
        {"label": "Elemental Mastery", "text": _whole(g("eleMas", 0))},
        {"label": "CRIT Rate", "text": _pct(g("critRate_", 0) * 100)},
        {"label": "CRIT DMG", "text": _pct(g("critDMG_", 0) * 100)},
        # The engine's enerRech_ leaves out the base 100%.
        {"label": "Energy Recharge", "text": _pct((1 + g("enerRech_", 0)) * 100)},
    ]
    if g("heal_", 0) > 0:
        rows.append({"label": "Healing Bonus", "text": _pct(g("heal_", 0) * 100)})
    own = element.lower()
    order = ([own] if own in _ELEMENTS else []) + [e for e in _ELEMENTS if e != own]
    for e in order:
        v = g(f"{e}_dmg_", 0)
        if e == own or v > 0:
            rows.append({"label": f"{e.capitalize()} DMG Bonus", "text": _pct(v * 100)})
    return rows


def rotation_total(formulas: list[dict], counts: dict[str, int]) -> float:
    """Damage of a rotation: hit count times average damage, summed over the counted hits."""
    total = 0.0
    for f in formulas:
        n = counts.get(f"{f['sheet']}:{f['name']}")
        if n:
            total += n * (f.get("avg") or 0)
    return total


# -- state ------------------------------------------------------------------------

def _default_state() -> dict:
    return {"members": [{} for _ in range(SLOTS)], "selected": 0, "settings": {},
            "conditionals": {},
            "enemy": {"level": 100, "res": 10.0, "amp": "", "cata": ""},
            "rotation": {}, "seconds": 20.0}


def _load_state(path: Path) -> dict:
    """The saved state; anything missing or malformed falls back to the defaults."""
    state = _default_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if not isinstance(raw, dict):
        return state
    members = raw.get("members")
    if isinstance(members, list):
        out: list[dict] = []
        seen: set[str] = set()
        for m in members[:SLOTS]:
            if isinstance(m, str):                      # old state: plain keys
                m = {"key": m, "source": "owned"}
            key = m.get("key") if isinstance(m, dict) else None
            if not isinstance(key, str) or not key or key in seen:
                out.append({})
                continue
            seen.add(key)
            out.append({"key": key, "source": "game" if m.get("source") == "game" else "owned"})
        out += [{} for _ in range(SLOTS - len(out))]
        state["members"] = out
    settings = raw.get("settings")
    if isinstance(settings, dict):
        for key, s in settings.items():
            if isinstance(key, str) and isinstance(s, dict):
                state["settings"][key] = _clean_settings(key, s)
    sel = raw.get("selected")
    if isinstance(sel, int) and not isinstance(sel, bool) and 0 <= sel < SLOTS:
        state["selected"] = sel
    conds = raw.get("conditionals")
    if isinstance(conds, dict):
        for key, sheets in conds.items():
            if not isinstance(sheets, dict):
                continue
            for sheet, values in sheets.items():
                if not isinstance(values, dict):
                    continue
                good = {n: v for n, v in values.items()
                        if isinstance(v, (int, str)) and not isinstance(v, bool)}
                if good:
                    state["conditionals"].setdefault(key, {})[sheet] = good
    enemy = raw.get("enemy")
    if isinstance(enemy, dict):
        try:
            state["enemy"]["level"] = int(enemy.get("level", 100))
            state["enemy"]["res"] = float(enemy.get("res", 10.0))
        except (TypeError, ValueError):
            pass
        for k in ("amp", "cata"):
            if isinstance(enemy.get(k), str):
                state["enemy"][k] = enemy[k]
    rotation = raw.get("rotation")
    if isinstance(rotation, dict):
        for key, counts in rotation.items():
            if isinstance(counts, dict):
                good = {k: v for k, v in counts.items()
                        if isinstance(v, int) and not isinstance(v, bool) and v > 0}
                if good:
                    state["rotation"][key] = good
    seconds = raw.get("seconds")
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0:
        state["seconds"] = float(seconds)
    return state


_LIMITS = {"level": (1, 100), "constellation": (0, 6), "auto": (1, 10), "skill": (1, 10),
           "burst": (1, 10), "weaponLevel": (1, 90), "refinement": (1, 5)}


def _clean_settings(key: str, raw: dict) -> dict:
    """Saved settings of a character: defaults for anything missing or out of range."""
    out = damage.default_settings(key)
    for field, (lo, hi) in _LIMITS.items():
        v = raw.get(field)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[field] = max(lo, min(hi, int(v)))
    if isinstance(raw.get("weapon"), str) and raw["weapon"]:
        out["weapon"] = raw["weapon"]
    return out


def _truthy(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "off", "no")
    return bool(value)


def _int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _compact(cond: dict) -> None:
    """Drop empty sheets and members from a conditionals state."""
    for key in list(cond):
        for sheet in list(cond[key]):
            if not cond[key][sheet]:
                del cond[key][sheet]
        if not cond[key]:
            del cond[key]


# -- backend ----------------------------------------------------------------------

class TeamBackend(QObject):
    changed = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    conditionsChanged = Signal()
    damageChanged = Signal()
    rotationChanged = Signal()
    formulasUpdated = Signal()
    allCharactersChanged = Signal()
    _portraitsDone = Signal()

    DEBOUNCE_MS = 300

    def __init__(self, settings, parent: QObject | None = None,
                 state_path: Path | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._path = Path(state_path) if state_path is not None else DATA_DIR / "team.json"
        self._state = _load_state(self._path)
        self._cands: dict[str, dict] = {}       # key -> {key, name, element, icon, source, member}
        self._engine: damage.Engine | None = None
        self._ids: dict[str, int | None] = {"cond": None, "avg": None, "detail": None, "team": None}
        self._cond_sig: tuple | None = None
        self._conds: tuple[list, list, list] = ([], [], [])   # engine list, keys, names
        self._cond_rows: list[dict] = []
        self._raw_key = ""                       # whose formulas/stats are shown
        self._raw_stats: dict = {}
        self._raw_formulas: list[dict] = []
        self._formulas_by_key: dict[str, list[dict]] = {}   # last computed formulas per character
        self._team: dict | None = None           # a computeTeam chain in progress
        self._team_result: dict = {}             # {"seconds"?, "members": [...]} of the last chain
        self._stale = True
        self._busy = False
        self._status = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DEBOUNCE_MS)
        self._timer.timeout.connect(self._recompute)
        self._all: dict[str, dict] = self._read_all()
        self._all_public: list[dict] = []
        self._portraits_started = False
        self._portraits_thread: threading.Thread | None = None
        self._portraitsDone.connect(self._on_portraits)
        self._rebuild_all_public()
        self._read_sources()
        if any(self._active()):
            self._timer.start()

    # -- sources ------------------------------------------------------------------

    def _read_sources(self) -> None:
        """The characters that can be put in a team: build cards first, then the scan."""
        cands: dict[str, dict] = {}
        collection = builds.latest()
        for card in (collection.ordered() if collection else []):
            key = card.get("key")
            if not key or key in cands:
                continue
            try:
                member = damage.member_from_card(card)
            except (ValueError, KeyError, TypeError):
                continue
            cands[key] = {"key": key, "name": card.get("name") or key,
                          "element": card.get("element", ""), "icon": card.get("icon", ""),
                          "source": "showcase", "member": member}
        try:
            good = json.loads(Path(self._settings.export_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            good = {}
        chars = builds._items("characters.json", "key")
        for c in (good.get("characters") or []) if isinstance(good, dict) else []:
            key = c.get("key")
            if not key or key in cands:
                continue
            try:
                member = damage.member_from_good(good, key)
            except (KeyError, TypeError, ValueError):
                continue
            if member is None:
                continue
            info = chars.get(key, {})
            element = info.get("element") or (
                key.removeprefix("Traveler").lower() if key.startswith("Traveler") else "")
            cands[key] = {"key": key, "name": info.get("name") or key, "element": element,
                          "icon": info.get("icon", ""), "source": "scan", "member": member}
        self._cands = cands

    @staticmethod
    def _read_all() -> dict[str, dict]:
        """Every character of the game (characters.json), Travelers once per element."""
        out: dict[str, dict] = {}
        for key, c in builds._items("characters.json", "key").items():
            if not c.get("inGO") or not c.get("name"):
                continue
            name, element = c["name"], c.get("element") or ""
            if key.startswith("Traveler"):
                element = element or key.removeprefix("Traveler").lower()
                name = f"Traveler ({element.capitalize()})"
            out[key] = {"key": key, "name": name, "element": element,
                        "rarity": int(c.get("rarity") or 0), "icon": c.get("icon") or "",
                        "weaponType": c.get("weaponType") or "sword"}
        return out

    def _rebuild_all_public(self) -> None:
        self._all_public = [
            {"key": c["key"], "name": c["name"], "element": c["element"], "rarity": c["rarity"],
             "iconUrl": _url(c["icon"])}
            for c in sorted(self._all.values(), key=lambda c: (c["name"].lower(), c["key"]))]

    def _settings_for(self, key: str) -> dict:
        """The settings of a character from the full list, created on first use."""
        store = self._state["settings"]
        if key not in store:
            store[key] = damage.default_settings(key)
        return store[key]

    def _slot_entry(self, m: dict) -> dict | None:
        """What a slot holds, or None when empty or no longer available."""
        key = m.get("key") if m else ""
        if not key:
            return None
        if m.get("source") == "game":
            info = self._all.get(key)
            if info is None:
                return None
            s = self._settings_for(key)
            return {"key": key, "name": info["name"], "element": info["element"],
                    "icon": info["icon"], "source": "game", "settings": s,
                    "member": damage.member_from_settings(key, s)}
        return self._cands.get(key)

    def _entry(self, key: str) -> dict | None:
        for m in self._state["members"]:
            if m and m.get("key") == key:
                return self._slot_entry(m)
        return None

    def _public(self, entry: dict) -> dict:
        out = {"key": entry["key"], "name": entry["name"], "element": entry["element"],
               "iconUrl": _url(entry["icon"]), "source": entry["source"]}
        if entry["source"] == "game":
            out["settings"] = dict(entry["settings"])
        return out

    def _active(self) -> list[tuple[int, str]]:
        """(slot, key) of the non-empty slots whose character is available, in slot order."""
        return [(i, m["key"]) for i, m in enumerate(self._state["members"])
                if self._slot_entry(m) is not None]

    def _selected_key(self) -> str:
        m = self._state["members"][self._state["selected"]]
        return m["key"] if self._slot_entry(m) is not None else ""

    # -- portraits of the full list -----------------------------------------------

    @Slot()
    def ensurePortraits(self) -> None:
        """Download the portraits the full list is missing, once per session."""
        if self._portraits_started:
            return
        self._portraits_started = True
        names = icons.missing_assets(c["icon"] for c in self._all.values())
        if not names:
            return

        def work() -> None:
            try:
                icons.download(names)
            finally:
                self._portraitsDone.emit()

        self._portraits_thread = threading.Thread(target=work, daemon=True)
        self._portraits_thread.start()

    @Slot()
    def _on_portraits(self) -> None:
        self._rebuild_all_public()
        self.allCharactersChanged.emit()
        self.changed.emit()

    # -- what the page shows --------------------------------------------------------

    @Property("QVariantList", notify=changed)
    def owned(self) -> list:
        shown = sorted(self._cands.values(), key=lambda c: (c["source"] != "showcase", c["name"]))
        return [self._public(c) for c in shown]

    @Property("QVariantList", notify=allCharactersChanged)
    def allCharacters(self) -> list:
        return self._all_public

    @Property("QVariantList", notify=changed)
    def members(self) -> list:
        out = []
        for m in self._state["members"]:
            e = self._slot_entry(m)
            out.append(self._public(e) if e is not None else {})
        return out

    @Property("QVariantList", notify=changed)
    def weaponChoices(self) -> list:
        key = self._selected_key()
        if not key:
            return []
        info = self._all.get(key)
        wtype = info["weaponType"] if info else "sword"
        items = builds._items("weapons.json", "key").values()
        shown = [w for w in items if w.get("inGO") and w.get("type") == wtype and w.get("name")]
        shown.sort(key=lambda w: (-int(w.get("rarity") or 0), w["name"].lower()))
        return [{"key": w["key"], "name": w["name"], "rarity": int(w.get("rarity") or 0)}
                for w in shown]

    @Property(int, notify=changed)
    def selected(self) -> int:
        return self._state["selected"]

    @Property("QVariantList", notify=conditionsChanged)
    def conditions(self) -> list:
        return self._cond_rows

    @Property("QVariantMap", notify=changed)
    def enemy(self) -> dict:
        return dict(self._state["enemy"])

    @Property("QVariantList", notify=damageChanged)
    def stats(self) -> list:
        key = self._selected_key()
        if not key or key != self._raw_key or not self._raw_stats:
            return []
        return stat_rows(self._raw_stats, self._entry(key)["element"])

    @Property("QVariantList", notify=damageChanged)
    def formulas(self) -> list:
        key = self._selected_key()
        if not key or key != self._raw_key:
            return []
        counts = self._state["rotation"].get(key, {})
        rows = []
        for f in self._raw_formulas:
            fk = f"{f['sheet']}:{f['name']}"
            rows.append({"key": fk, "label": damage.formula_label(f["sheet"], f["name"], f.get("move", "")),
                         "group": formula_group(f), "q": f.get("q"), "avg": f.get("avg"),
                         "crit": f.get("crit"), "nonCrit": f.get("nonCrit"),
                         "count": counts.get(fk, 0)})
        return rows

    @Property("QVariantMap", notify=rotationChanged)
    def rotation(self) -> dict:
        res = self._team_result
        members = res.get("members", [])
        seconds = self._state["seconds"]
        return {"seconds": seconds, "members": members,
                "teamTotal": sum(m["total"] for m in members),
                "teamDps": sum(m["dps"] for m in members),
                "stale": self._stale or not members}

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    # -- actions --------------------------------------------------------------------

    @Slot(int, str)
    @Slot(int, str, str)
    def setMember(self, slot: int, key: str, source: str = "owned") -> None:
        if not 0 <= slot < SLOTS:
            return
        members = self._state["members"]
        if key:
            if source == "game":
                if key not in self._all:
                    return
            elif key not in self._cands:
                return
            for i, m in enumerate(members):
                if m and m.get("key") == key and i != slot:
                    members[i] = {}
            if source == "game":
                self._settings_for(key)
            members[slot] = {"key": key, "source": "game" if source == "game" else "owned"}
        else:
            members[slot] = {}
        self.changed.emit()
        self._touch()

    @Slot(int, str, "QVariant")
    def setSetting(self, slot: int, field: str, value) -> None:
        if not 0 <= slot < SLOTS:
            return
        m = self._state["members"][slot]
        if not m or m.get("source") != "game" or m.get("key") not in self._all:
            return
        s = self._settings_for(m["key"])
        if field == "weapon":
            wtype = self._all[m["key"]]["weaponType"]
            w = builds._items("weapons.json", "key").get(str(value))
            if w is None or not w.get("inGO") or w.get("type") != wtype:
                return
            s["weapon"] = w["key"]
        elif field in _LIMITS:
            lo, hi = _LIMITS[field]
            s[field] = max(lo, min(hi, _int(value)))
        else:
            return
        self._cond_sig = None                # the weapon / constellation change the toggles
        self.changed.emit()
        self._touch()

    @Slot(str)
    def addOwned(self, key: str) -> None:
        """Put an owned character in the first empty slot (the last slot when all are taken)."""
        members = self._state["members"]
        if key not in self._cands or any(m and m.get("key") == key for m in members):
            return
        slot = next((i for i, m in enumerate(members) if not m), SLOTS - 1)
        self.setMember(slot, key, "owned")

    @Slot(int)
    def select(self, slot: int) -> None:
        if 0 <= slot < SLOTS and slot != self._state["selected"]:
            self._state["selected"] = slot
            self.changed.emit()
            self.damageChanged.emit()
            self._touch(stale=False)

    @Slot(str, "QVariant")
    def setConditional(self, cond_id: str, value) -> None:
        row = next((r for r in self._cond_rows if r["id"] == cond_id), None)
        if row is None:
            return
        kind = row["type"]
        if kind == "bool":
            v = 1 if _truthy(value) else None
        elif kind == "num":
            v = _int(value) or None
        else:
            v = str(value) if value not in (None, "") else None
        store = self._state["conditionals"]
        sheets = store.setdefault(row["memberKey"], {})
        values = sheets.setdefault(row["sheet"], {})
        if v is None:
            values.pop(row["name"], None)
        else:
            values[row["name"]] = v
        _compact(store)
        self._cond_rows = condition_rows(*self._conds, self._state["conditionals"])
        self.conditionsChanged.emit()
        self._touch()

    @Slot(int, float, str, str)
    def setEnemy(self, level: int, res_percent: float, amp: str, cata: str) -> None:
        self._state["enemy"] = {"level": int(level), "res": float(res_percent),
                                "amp": amp or "", "cata": cata or ""}
        self.changed.emit()
        self._touch()

    @Slot(str, int)
    def setCount(self, formula_key: str, count: int) -> None:
        key = self._selected_key()
        if not key:
            return
        counts = self._state["rotation"].setdefault(key, {})
        if count > 0:
            counts[formula_key] = int(count)
        else:
            counts.pop(formula_key, None)
        if not counts:
            del self._state["rotation"][key]
        self.damageChanged.emit()
        self._touch(recompute=False)

    @Slot(float)
    def setSeconds(self, seconds: float) -> None:
        if seconds > 0:
            self._state["seconds"] = float(seconds)
            self._touch(recompute=False)

    @Slot()
    def reload(self) -> None:
        """Re-read the build cards and the scan."""
        self._read_sources()
        self._cond_sig = None
        self.changed.emit()
        self._touch()

    def shutdown(self) -> None:
        self._timer.stop()
        if self._engine is not None:
            self._engine.shutdown()

    # -- state changes -----------------------------------------------------------------

    def _touch(self, stale: bool = True, recompute: bool = True) -> None:
        """Save the state, mark the rotation out of date and schedule a recomputation."""
        self._save()
        if stale:
            self._cancel_team()
            if not self._stale:
                self._stale = True
            self.rotationChanged.emit()
        if recompute:
            self._timer.start()

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, indent=1), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            pass

    # -- engine --------------------------------------------------------------------------

    def _engine_get(self) -> damage.Engine:
        if self._engine is None:
            self._engine = damage.Engine(self)
            self._engine.finished.connect(self._on_finished)
            self._engine.failed.connect(self._on_failed)
        return self._engine

    def engine(self) -> damage.Engine:
        """The formula engine (created on first use), shared with the optimizer."""
        return self._engine_get()

    def optimize_context(self, char_key: str) -> dict | None:
        """What an engine search for a character needs from the team, or None when
        the character is not in it."""
        active = self._active()
        keys = [k for _, k in active]
        if char_key not in keys:
            return None
        base = self._payload(active, [], [])
        return {"members": base["members"], "conditionals": base["conditionals"],
                "enemy": base["enemy"], "index": keys.index(char_key),
                "rotation": dict(self._state["rotation"].get(char_key, {})),
                "formulas": list(self._formulas_by_key.get(char_key, []))}

    def _payload(self, active: list[tuple[int, str]], only: list[int], modes: list[str]) -> dict:
        conds: dict = {}
        stored = self._state["conditionals"]
        team = stored.get(TEAM, {})
        for idx, (_, key) in enumerate(active):
            sheets = {s: dict(v) for s, v in stored.get(key, {}).items()}
            if idx == 0:
                for s, v in team.items():
                    sheets.setdefault(s, {}).update(v)
            if sheets:
                conds[str(idx)] = sheets
        enemy = self._state["enemy"]
        return {"members": [self._entry(k)["member"] for _, k in active],
                "conditionals": conds,
                "enemy": {"level": enemy["level"], "res": enemy["res"] / 100,
                          "amp": enemy["amp"], "cata": enemy["cata"]},
                "only": only, "modes": modes}

    def _request(self, purpose: str, fn: str, payload: dict) -> None:
        self._ids[purpose] = self._engine_get().request(fn, payload)
        self._update_busy()

    def _update_busy(self) -> None:
        busy = any(v is not None for v in self._ids.values())
        if busy != self._busy:
            self._busy = busy
            self.busyChanged.emit()

    def _set_status(self, text: str) -> None:
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    def _recompute(self) -> None:
        """The debounce timer fired: refresh the toggles and the selected member's damage."""
        active = self._active()
        if not active:
            self._raw_key, self._raw_stats, self._raw_formulas = "", {}, []
            self._conds, self._cond_rows, self._cond_sig = ([], [], []), [], ()
            self._ids["avg"] = self._ids["detail"] = self._ids["cond"] = None
            self._update_busy()
            self._set_status("")
            self.conditionsChanged.emit()
            self.damageChanged.emit()
            return
        keys = tuple(k for _, k in active)
        if keys != self._cond_sig:
            self._cond_sig = keys
            self._request("cond", "conditionals",
                          {"members": [self._entry(k)["member"] for _, k in active]})
        key = self._selected_key()
        if not key:
            self._ids["avg"] = self._ids["detail"] = None
            self._update_busy()
            self._set_status("")
            self.damageChanged.emit()
            return
        idx = [k for _, k in active].index(key)
        self._ids["detail"] = None
        self._set_status(f"Calculating {self._entry(key)['name']}…")
        self._request("avg", "compute", self._payload(active, [idx], ["avg"]))

    def _purpose(self, req_id: int) -> str | None:
        return next((p for p, i in self._ids.items() if i == req_id), None)

    def _settle(self, purpose: str) -> None:
        self._ids[purpose] = None
        self._update_busy()
        if not self._busy:
            self._set_status("")

    @Slot(int, object)
    def _on_finished(self, req_id: int, out) -> None:
        purpose = self._purpose(req_id)
        if purpose is None:
            return                                   # superseded
        if purpose == "cond":
            active = self._active()
            keys = [k for _, k in active]
            names = [self._entry(k)["name"] for k in keys]
            self._conds = (list(out), keys, names)
            self._cond_rows = condition_rows(*self._conds, self._state["conditionals"])
            self._settle("cond")
            self.conditionsChanged.emit()
        elif purpose == "avg":
            active = self._active()
            key = self._selected_key()
            keys = [k for _, k in active]
            idx = keys.index(key) if key in keys else -1
            res = (out.get("members") or [None] * (idx + 1))[idx] if idx >= 0 else None
            self._ids["avg"] = None
            if res is None:
                self._settle("avg")
                return
            self._raw_key = key
            self._raw_stats = res.get("stats", {})
            self._raw_formulas = list(res.get("formulas", []))
            self._formulas_by_key[key] = self._raw_formulas
            self.formulasUpdated.emit()
            self.damageChanged.emit()
            self._update_busy()
            self._request("detail", "compute", self._payload(active, [idx], ["crit", "nonCrit"]))
        elif purpose == "detail":
            key = self._selected_key()
            keys = [k for _, k in self._active()]
            idx = keys.index(key) if key in keys else -1
            res = (out.get("members") or [None] * (idx + 1))[idx] if idx >= 0 else None
            if res is not None and key == self._raw_key:
                found = {(f["sheet"], f["name"], f.get("q")): f for f in res.get("formulas", [])}
                for f in self._raw_formulas:
                    g = found.get((f["sheet"], f["name"], f.get("q")))
                    if g:
                        f["crit"], f["nonCrit"] = g.get("crit"), g.get("nonCrit")
                self.damageChanged.emit()
            self._settle("detail")
        elif purpose == "team":
            self._on_team_member(out)

    @Slot(int, str)
    def _on_failed(self, req_id: int, message: str) -> None:
        purpose = self._purpose(req_id)
        if purpose is None:
            return
        if purpose == "team":
            self._team = None
        self._ids[purpose] = None
        self._update_busy()
        self._set_status(message)

    # -- the rotation --------------------------------------------------------------------------

    @Slot()
    def computeTeam(self) -> None:
        active = self._active()
        if not active:
            return
        self._cancel_team()
        self._team = {"active": active, "pos": 0, "formulas": {}}
        self._team_step()

    def _cancel_team(self) -> None:
        if self._team is not None:
            self._team = None
            self._ids["team"] = None
            self._update_busy()
            self._set_status("")

    def _team_step(self) -> None:
        t = self._team
        n = len(t["active"])
        self._set_status(f"Calculating team damage ({t['pos'] + 1}/{n})…")
        self._request("team", "compute", self._payload(t["active"], [t["pos"]], ["avg"]))

    def _on_team_member(self, out) -> None:
        t = self._team
        if t is None:
            self._ids["team"] = None
            self._update_busy()
            return
        pos = t["pos"]
        res = (out.get("members") or [None] * (pos + 1))[pos]
        member_key = t["active"][pos][1]
        t["formulas"][member_key] = (res or {}).get("formulas", [])
        if res is not None:
            self._formulas_by_key[member_key] = t["formulas"][member_key]
            self.formulasUpdated.emit()
        t["pos"] += 1
        if t["pos"] < len(t["active"]):
            self._team_step()
            return
        seconds = self._state["seconds"]
        members = []
        for _, key in t["active"]:
            total = rotation_total(t["formulas"].get(key, []), self._state["rotation"].get(key, {}))
            members.append({"name": self._entry(key)["name"], "total": total,
                            "dps": total / seconds})
        self._team = None
        self._team_result = {"members": members}
        self._stale = False
        self._settle("team")
        self.rotationChanged.emit()
