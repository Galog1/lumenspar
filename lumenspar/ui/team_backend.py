"""QML bridge for the Optimizer's "Team & damage" tab.

A team of up to four characters, the conditional toggles of the whole team and
each character's damage per hit, against a fixed enemy. No number is typed in:
everything is a choice. The numbers come from the bundled Genshin Optimizer
formula engine (lumenspar.damage), which runs on its own thread; this module
only builds its requests, debounces them and publishes the results.

The state (team, toggles, reactions) is saved to team.json.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .. import builds, damage, reactions
from ..config import DATA_DIR
from ..wishes import icons
from .builds_backend import _url

MOVE_GROUPS = {"normal": "Normal Attack", "charged": "Charged Attack",
               "plunging": "Plunging Attack", "skill": "Elemental Skill",
               "burst": "Elemental Burst"}

TEAM = "_team"                      # state key of the team-wide conditionals
TEAM_SHEETS = ("reso", "static")
SLOTS = 4
ENEMY = {"level": 100, "res": 10.0}  # fixed: level and resistance in percent
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


def visible_formulas(formulas: list[dict], element: str, team: set[str]) -> list[dict]:
    """The formulas to list: transformative / Lunar rows only when the member can trigger them."""
    return [f for f in formulas
            if f.get("sheet") != "static"
            or reactions.reaction_row_allowed(f.get("name", ""), element.lower(), team)]


def _thin(options: list, keep: int = 8) -> list:
    """Long option lists (e.g. Arlecchino's 40 Bond percentages) as at most
    `keep` evenly spaced choices, always including the last."""
    if len(options) <= keep:
        return list(options)
    step = (len(options) - 1) / (keep - 1)
    picks = sorted({round(i * step) for i in range(keep)})
    return [options[i] for i in picks]


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
            "options": (stack_options(c.get("min"), c.get("max")) if c.get("type") == "num"
                        else [{"value": v, "label": damage.option_label(v)}
                              for v in _thin(c.get("list", []))]),
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


def stack_options(lo, hi) -> list[dict]:
    """Choices for a stacking condition: Off, then every stack count when there
    are few of them, otherwise half and max."""
    lo = int(lo or 0)
    hi = int(hi if hi is not None else lo)
    off = {"value": 0, "label": "Off"}
    if hi - lo <= 6:
        return [off] + [{"value": v, "label": str(v)} for v in range(lo + 1, hi + 1)]
    return [off, {"value": round((lo + hi) / 2), "label": "½"}, {"value": hi, "label": "Max"}]


# -- state ------------------------------------------------------------------------

def _default_state() -> dict:
    return {"members": [{} for _ in range(SLOTS)], "selected": 0, "settings": {},
            "conditionals": {}, "reactions": {}}


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
            if isinstance(key, str) and isinstance(s, dict) and not key.startswith(SCAN):
                state["settings"][key] = dict(_clean_settings(key, s), **_FIXED)
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
    chosen = raw.get("reactions")
    if isinstance(chosen, dict):
        for key, v in chosen.items():
            if isinstance(key, str) and v in _REACTIONS and v:
                state["reactions"][key] = v
    return state


_REACTIONS = ("", "vaporize", "melt", "aggravate", "spread")
SCAN = "scan:"                      # prefix of the settings key of a scan member

# a character from the full list is always maxed
_FIXED = {"level": 90, "auto": 9, "skill": 9, "burst": 9, "weaponLevel": 90}

_LIMITS = {"level": (1, 100), "constellation": (0, 6), "auto": (1, 10), "skill": (1, 10),
           "burst": (1, 10), "weaponLevel": (1, 90), "refinement": (1, 5)}


def _clean_settings(key: str, raw: dict) -> dict:
    """Saved settings of a character: defaults for anything missing or out of range."""
    out = damage.default_settings(key.removeprefix(SCAN))
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
        self._ids: dict[str, int | None] = {"cond": None, "avg": None, "detail": None}
        self._cond_sig: tuple | None = None
        self._conds: tuple[list, list, list] = ([], [], [])   # engine list, keys, names
        self._cond_rows: list[dict] = []
        self._raw_key = ""                       # whose formulas/stats are shown
        self._raw_stats: dict = {}
        self._raw_formulas: list[dict] = []
        self._formulas_by_key: dict[str, list[dict]] = {}   # last computed formulas per character
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
        # Portraits for the team's and the player's characters, in the background.
        QTimer.singleShot(0, self.ensurePortraits)
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
            key = c.get("key") if isinstance(c, dict) else None
            if not key or key in cands:
                continue
            try:
                member = damage.member_from_good(good, key)
                if member is None:
                    dummy = {"key": "", "level": 1, "ascension": 0, "refinement": 1,
                             "location": key}
                    member = damage.member_from_good(
                        dict(good, weapons=[dummy]), key)
            except (KeyError, TypeError, ValueError):
                continue
            if member is None:
                continue
            real = damage.member_from_good(good, key) is not None
            defaults = damage.default_settings(key)
            ch, w = member["char"], member["weapon"]
            defaults.update(level=ch["level"], constellation=ch["constellation"],
                            auto=ch["talent"]["auto"], skill=ch["talent"]["skill"],
                            burst=ch["talent"]["burst"])
            if real and w.get("key"):
                defaults.update(weapon=w["key"], weaponLevel=w["level"],
                                refinement=w["refinement"])
            defaults = _clean_settings(key, defaults)
            info = chars.get(key, {})
            element = info.get("element") or (
                key.removeprefix("Traveler").lower() if key.startswith("Traveler") else "")
            cands[key] = {"key": key, "name": info.get("name") or key, "element": element,
                          "icon": info.get("icon", ""), "source": "scan", "member": None,
                          "defaults": defaults, "artifacts": member["artifacts"]}
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
            store[key] = dict(damage.default_settings(key), **_FIXED)
        return store[key]

    def _scan_settings_for(self, key: str) -> dict:
        """The settings of a scan character: what the scan says (not editable)."""
        return dict(self._cands[key]["defaults"])

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
        cand = self._cands.get(key)
        if cand is not None and cand["source"] == "scan":
            s = self._scan_settings_for(key)
            member = damage.member_from_settings(key, s)
            member["artifacts"] = cand["artifacts"]
            return dict(cand, settings=s, member=member)
        return cand

    def _entry(self, key: str) -> dict | None:
        for m in self._state["members"]:
            if m and m.get("key") == key:
                return self._slot_entry(m)
        return None

    def _public(self, entry: dict) -> dict:
        out = {"key": entry["key"], "name": entry["name"], "element": entry["element"],
               "iconUrl": _url(entry["icon"]), "source": entry["source"]}
        if entry["source"] in ("game", "scan"):
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
        names = icons.missing_assets([c["icon"] for c in self._all.values()]
                                     + [c.get("icon", "") for c in self._cands.values()])
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
        return [self._public(self._slot_entry({"key": c["key"]}) or c) for c in shown]

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
        rows = []
        for f in visible_formulas(self._raw_formulas, self._entry(key)["element"], self._team_set()):
            fk = f"{f['sheet']}:{f['name']}"
            rlabel = reactions.reaction_label(f["name"]) if f["sheet"] == "static" else None
            label = rlabel or damage.formula_label(f["sheet"], f["name"], f.get("move", ""))
            rows.append({"key": fk, "label": label,
                         "group": "Reactions" if rlabel else formula_group(f), "q": f.get("q"), "avg": f.get("avg"),
                         "crit": f.get("crit"), "nonCrit": f.get("nonCrit")})
        return rows

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
            elif self._cands[key]["source"] == "scan":
                self._scan_settings_for(key)
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
        entry = self._slot_entry(m) if m else None
        if entry is None or entry["source"] != "game" or m["key"] not in self._all:
            return
        s = entry["settings"]
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
            self._touch()

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

    def _team_set(self) -> set[str]:
        return reactions.team_elements(
            [self._slot_entry(m)["element"] for m in self._state["members"]
             if self._slot_entry(m) is not None])

    def _reaction_for(self, key: str) -> str:
        """The amplifying / catalyze reaction chosen for a member, "" if none or no longer possible."""
        e = self._entry(key)
        if e is None:
            return ""
        chosen = self._state["reactions"].get(key, "")
        return chosen if chosen in reactions.amp_options(e["element"].lower(), self._team_set()) else ""

    @Property("QVariantList", notify=changed)
    def reactionOptions(self) -> list:
        key = self._selected_key()
        if not key:
            return [{"value": "", "label": "None"}]
        opts = reactions.amp_options(self._entry(key)["element"].lower(), self._team_set())
        return [{"value": "", "label": "None"}] + [
            {"value": v, "label": v.capitalize()} for v in opts]

    @Property(str, notify=changed)
    def reaction(self) -> str:
        key = self._selected_key()
        return self._reaction_for(key) if key else ""

    @Slot(str)
    def setReaction(self, value: str) -> None:
        key = self._selected_key()
        if not key or value not in [o["value"] for o in self.reactionOptions]:
            return
        if value:
            self._state["reactions"][key] = value
        else:
            self._state["reactions"].pop(key, None)
        self.changed.emit()
        self._touch()

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

    def _touch(self) -> None:
        """Save the state and schedule a recomputation."""
        self._save()
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
        base = self._payload(active, [], [], char_key)
        return {"members": base["members"], "conditionals": base["conditionals"],
                "enemy": base["enemy"], "index": keys.index(char_key),
                "formulas": list(self._formulas_by_key.get(char_key, []))}

    def _payload(self, active: list[tuple[int, str]], only: list[int], modes: list[str],
                 enemy_key: str | None = None) -> dict:
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
        enemy = ENEMY
        if enemy_key is None:
            enemy_key = active[only[0]][1] if only else ""
        reaction = self._reaction_for(enemy_key) if enemy_key else ""
        return {"members": [self._entry(k)["member"] for _, k in active],
                "conditionals": conds,
                "enemy": {"level": enemy["level"], "res": enemy["res"] / 100,
                          "amp": reaction if reaction in ("vaporize", "melt") else "",
                          "cata": reaction if reaction in ("spread", "aggravate") else ""},
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

    @Slot(int, str)
    def _on_failed(self, req_id: int, message: str) -> None:
        purpose = self._purpose(req_id)
        if purpose is None:
            return
        self._ids[purpose] = None
        self._update_busy()
        self._set_status(message)
