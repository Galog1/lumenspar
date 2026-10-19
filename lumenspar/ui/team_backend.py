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

from .. import akasha, builds, damage, reactions, teamcombo
from ..config import DATA_DIR
from ..wishes import icons
from .builds_backend import _url

TEAM = "_team"                      # state key of the team-wide conditionals
SLOTS = 4
ENEMY = {"level": 100, "res": 10.0}  # fixed: level and resistance in percent
_KIND_ORDER = {"char": 0, "weapon": 1, "artifact": 2}
_ELEMENTS = ("pyro", "hydro", "electro", "cryo", "anemo", "geo", "dendro", "physical")


_AVATAR_IDS: dict[str, str] | None = None


def _avatar_ids() -> dict[str, str]:
    """{character key: avatar id} from the bundled Enka data; Traveler and Manekin
    variants (ids with a depot suffix) are left out: they have no leaderboard."""
    global _AVATAR_IDS
    if _AVATAR_IDS is None:
        try:
            raw = json.loads((Path(__file__).resolve().parent.parent / "gamedata" / "enka.json")
                             .read_text(encoding="utf-8"))
            avatars = raw.get("avatars") or {}
        except (OSError, ValueError, AttributeError):
            avatars = {}
        _AVATAR_IDS = {a["key"]: aid for aid, a in avatars.items()
                       if "-" not in aid and isinstance(a, dict) and a.get("key")}
    return _AVATAR_IDS


# -- pure helpers ---------------------------------------------------------------

def formula_rows(formulas: list[dict], char_key: str, element: str, team: set[str]) -> list[dict]:
    """The engine's formulas as list rows: label, heading and kind (dmg / heal /
    shield), in engine order; transformative / Lunar rows only when the member
    can trigger them."""
    rows: list[dict] = []
    seen: dict[tuple[str, str], int] = {}
    for f in formulas:
        if f.get("avg") is None:
            continue
        if f["id"].startswith("reaction:"):
            name = f["id"][len("reaction:"):]
            if not reactions.reaction_row_allowed(name, element.lower(), team):
                continue
            label = reactions.reaction_label(name) or damage.humanize(name)
            group = "Reactions"
        else:
            label = damage.render_label(f.get("name")) or damage.humanize(f["id"])
            group = damage.talent_title(char_key, f["section"])
        n = seen[(group, label)] = seen.get((group, label), 0) + 1
        if n > 1:
            label = f"{label} ({n})"
        q = "heal" if f.get("variant") == "heal" else ("shield" if "shield" in label.lower() else "dmg")
        rows.append({"key": f["id"], "label": label, "group": group, "q": q,
                     "avg": f["avg"], "crit": f.get("crit"), "nonCrit": f.get("nonCrit")})
    return rows


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
    conditions (elemental resonance) are listed last, and their state lives
    under "_team".
    """
    member_rows: list[tuple[int, int, int, dict]] = []
    team_rows: list[dict] = []
    for n, c in enumerate(conds):
        sheet, name, kind = c["sheet"], c["name"], c.get("kind")
        team = kind == "team"
        if team:
            member, member_key, store = "Team", TEAM, TEAM
        else:
            src = int(c["src"])
            member, member_key, store = names[src], keys[src], keys[src]
        section = str(c.get("section") or "")
        if kind == "char":
            title = damage.talent_title(member_key, section)
        elif kind == "weapon":
            title = damage.sheet_title(sheet)
        elif kind == "artifact":
            pieces = section.rpartition(":")[2]
            title = f"{damage.sheet_title(sheet)} {pieces}-piece" if pieces else damage.sheet_title(sheet)
        else:
            title = "Elemental Resonance"
        states = _thin(c.get("states") or [])
        row = {
            "id": f"{c['src']}|{sheet}|{name}",
            "member": member,
            "memberKey": member_key,
            "sheet": sheet,
            "sheetTitle": title,
            "kind": kind,
            "name": name,
            "label": damage.render_label(c.get("label")) or damage.humanize(name),
            "detail": "",
            "type": "bool" if len(c.get("states") or []) == 1 else "list",
            "options": [{"value": s["value"],
                         "label": damage.render_label(s.get("label")) or damage.option_label(s["value"])}
                        for s in states],
            "value": ((state.get(store) or {}).get(sheet) or {}).get(name),
        }
        if row["type"] == "bool":
            row["onValue"] = states[0]["value"]
        if team:
            team_rows.append(row)
        else:
            member_rows.append((int(c["src"]), _KIND_ORDER.get(kind, 3), n, row))
    member_rows.sort(key=lambda t: t[:3])
    rows = [r for *_, r in member_rows] + team_rows
    # Several conditions of one source can share a label; tell them apart.
    seen: dict[tuple, int] = {}
    for r in rows:
        k = (r["memberKey"], r["sheetTitle"], r["label"])
        seen[k] = seen.get(k, 0) + 1
    for r in rows:
        if seen[(r["memberKey"], r["sheetTitle"], r["label"])] > 1:
            r["label"] = f"{r['label']} ({damage.humanize(r['name'])})"
    return rows


def fix_conditionals(conds: list[dict], state: dict) -> bool:
    """Map saved values that are not a state of their conditional (toggles saved
    by the old engine: "1" for on, "3" for three stacks) onto one, or drop them.
    Conditionals the team no longer lists are kept. Returns whether anything changed."""
    states = {(c["sheet"], c["name"]): [s["value"] for s in c["states"]] for c in conds}
    changed = False
    for sheets in state.values():
        for sheet, values in sheets.items():
            for name, v in list(values.items()):
                allowed = states.get((sheet, name))
                if allowed is None or v in allowed:
                    continue
                if len(allowed) == 1 and v.isdigit() and int(v) > 0:
                    values[name] = allowed[0]
                else:
                    del values[name]
                changed = True
    _compact(state)
    return changed


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
        {"label": "Energy Recharge", "text": _pct(g("enerRech_", 0) * 100)},
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


# -- state ------------------------------------------------------------------------

def _default_state() -> dict:
    return {"members": [{} for _ in range(SLOTS)], "selected": 0, "settings": {},
            "conditionals": {}, "reactions": {}, "combo": {}}


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
                # numbers come from the old engine's toggles (1 = on, n = stacks);
                # fix_conditionals maps them onto the current states
                good = {n: (v if isinstance(v, str) else str(v)) for n, v in values.items()
                        if (isinstance(v, str) and v)
                        or (isinstance(v, int) and not isinstance(v, bool) and v > 0)}
                if good:
                    state["conditionals"].setdefault(key, {})[sheet] = good
    chosen = raw.get("reactions")
    if isinstance(chosen, dict):
        for key, v in chosen.items():
            if isinstance(key, str) and v in _REACTIONS and v:
                state["reactions"][key] = v
    chosen_combo = raw.get("combo")
    if isinstance(chosen_combo, dict):
        for key, v in chosen_combo.items():
            if isinstance(key, str) and isinstance(v, str) and v:
                state["combo"][key] = v
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
    comboChanged = Signal()
    _portraitsDone = Signal()
    _comboFetched = Signal(str, object, object, str)

    DEBOUNCE_MS = 300

    def __init__(self, settings, parent: QObject | None = None,
                 state_path: Path | None = None, lazy: bool = False) -> None:
        super().__init__(parent)
        self._settings = settings
        # A lazy backend leaves the damage engine (a child process of a few hundred MB
        # that takes seconds of CPU per team member) alone until activate() is called,
        # so players who never open the optimizer do not pay for it at start-up.
        self._activated = not lazy
        self._path = Path(state_path) if state_path is not None else DATA_DIR / "team.json"
        self._state = _load_state(self._path)
        self._cands: dict[str, dict] = {}       # key -> {key, name, element, icon, source, member}
        self._engine: damage.Engine | None = None
        self._ids: dict[str, int | None] = {"cond": None, "avg": None, "detail": None}
        self._cond_sig: str | None = None
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
        self._combo: dict[str, dict] = {}       # key -> {boards, board, hits, error, loading}
        self._combo_threads: dict[str, threading.Thread] = {}
        self._comboFetched.connect(self._on_combo)
        self.damageChanged.connect(self.comboChanged)
        self._rebuild_all_public()
        self._read_sources()
        # Portraits for the team's and the player's characters, in the background.
        QTimer.singleShot(0, self.ensurePortraits)
        if self._activated and any(self._active()):
            self._timer.start()

    @Slot()
    def activate(self) -> None:
        """The optimizer page was opened: start computing (once)."""
        if self._activated:
            return
        self._activated = True
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
        return formula_rows(self._raw_formulas, key, self._entry(key)["element"], self._team_set())

    def _combo_match(self, key: str) -> dict | None:
        """The key's combo hits matched to its damage rows, or None while either is missing."""
        c = self._combo.get(key)
        if not c or not c.get("hits"):
            return None
        formulas = self._formulas_by_key.get(key)
        entry = self._entry(key)
        if not formulas or entry is None:
            return None
        rows = formula_rows(formulas, key, entry["element"], self._team_set())
        if not rows:
            return None
        return teamcombo.match(c["hits"], rows)

    @Property("QVariantMap", notify=comboChanged)
    def combo(self) -> dict:
        key = self._selected_key()
        c = self._combo.get(key) if key else None
        if not c:
            return {}
        boards = c.get("boards") or []
        cur = next((b for b in boards if b.calculation_id == c.get("board")), None)
        out: dict = {
            "boards": [{"id": b.calculation_id, "label": f"{b.short or b.name} · {b.weapon}"}
                       for b in boards],
            "board": c.get("board") or "",
            "title": cur.name if cur else "",
            "details": cur.details if cur else "",
            "loading": bool(c.get("loading")),
            "error": c.get("error") or "",
        }
        m = self._combo_match(key) if key == self._raw_key else None
        if m is not None:
            out["hits"] = [{"label": f"{h['name']} × {h['quantity']:g}",
                            "matched": h["label"] or "not found",
                            "group": h["group"] or "", "total": h["total"]}
                           for h in m["hits"]]
            out["total"] = m["total"]
            out["missing"] = m["missing"]
        return out

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
            v = row["onValue"] if _truthy(value) else None
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

    # -- Akasha combo -----------------------------------------------------------------

    def _ensure_combo(self, key: str) -> None:
        """Start loading the Akasha combo of the selected member unless it is loaded or loading."""
        if not key:
            return
        c = self._combo.get(key)
        if c and (c.get("loading") or c.get("hits") or c.get("error")):
            return
        self._fetch_combo(key)

    def _fetch_combo(self, key: str, board_id: str = "") -> None:
        """Load the boards and the chosen board's hits in a background thread."""
        t = self._combo_threads.get(key)
        if t is not None and t.is_alive():
            return
        entry = self._entry(key)
        weapon = ""
        if entry is not None:
            weapon = damage.sheet_title(entry["member"]["weapon"]["key"])
        c = self._combo.setdefault(key, {"boards": [], "board": "", "hits": [], "error": "",
                                         "loading": True})
        c.update(loading=True, error="")
        if board_id:
            c["hits"] = []
        chosen = board_id or self._state["combo"].get(key, "")
        known = list(c.get("boards") or [])
        self.comboChanged.emit()
        t = threading.Thread(target=self._combo_work, args=(key, chosen, weapon, known),
                             daemon=True)
        self._combo_threads[key] = t
        t.start()

    def _combo_work(self, key: str, chosen: str, weapon: str, known: list) -> None:
        aid = _avatar_ids().get(key)
        if aid is None:
            self._comboFetched.emit(key, None, None, "Akasha.cv has no leaderboard for this character.")
            return
        try:
            boards = known or akasha.boards(aid)
            if not boards:
                raise akasha.AkashaError("Akasha.cv has no leaderboard for this character.")
            board = (next((b for b in boards if b.calculation_id == chosen), None)
                     or next((b for b in boards if b.weapon.lower() == weapon.lower()), None)
                     or boards[0])
            # The combo is the same in every ER variant, but only the unfiltered
            # board names partial hits with their share ("Lunar-Charged DMG (60%)").
            hits = akasha.combo(board.calculation_id, "")
        except (akasha.AkashaError, OSError) as exc:
            self._comboFetched.emit(key, {"boards": list(known), "board": chosen}, None, str(exc))
            return
        self._comboFetched.emit(key, {"boards": boards, "board": board.calculation_id}, hits, "")

    @Slot(str, object, object, str)
    def _on_combo(self, key: str, boards, hits, error: str) -> None:
        c = self._combo.setdefault(key, {"boards": [], "board": "", "hits": [], "error": "",
                                         "loading": False})
        c["loading"] = False
        c["error"] = error
        if boards:
            c["boards"] = list(boards["boards"])
            c["board"] = boards["board"]
        c["hits"] = list(hits) if hits else []
        self.comboChanged.emit()

    @Slot(str)
    def setComboBoard(self, calc_id: str) -> None:
        key = self._selected_key()
        c = self._combo.get(key)
        if not key or not calc_id or not c or not any(
                b.calculation_id == calc_id for b in c.get("boards") or []):
            return
        self._state["combo"][key] = calc_id
        self._save()
        c["board"] = calc_id
        self._fetch_combo(key, calc_id)

    # -- state changes -----------------------------------------------------------------

    def _touch(self) -> None:
        """Save the state and schedule a recomputation."""
        self._save()
        if self._activated:
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
        formulas = list(self._formulas_by_key.get(char_key, []))
        rows = formula_rows(formulas, char_key, self._entry(char_key)["element"], self._team_set())
        m = self._combo_match(char_key) if rows else None
        c = self._combo.get(char_key) or {}
        cur = next((b for b in c.get("boards") or [] if b.calculation_id == c.get("board")), None)
        return {"members": base["members"], "conditional": base["conditional"],
                "enemy": base["enemy"], "reactions": base["reactions"],
                "index": keys.index(char_key), "formulas": formulas, "rows": rows,
                "combo": teamcombo.frames(m) if m is not None else [],
                "comboTitle": cur.name if cur else ""}

    def _payload(self, active: list[tuple[int, str]], only: list[int], modes: list[str]) -> dict:
        conds: dict = {}
        stored = self._state["conditionals"]
        for key in [TEAM] + [k for _, k in active]:
            for sheet, values in stored.get(key, {}).items():
                conds.setdefault(sheet, {}).update(values)
        return {"members": [self._entry(k)["member"] for _, k in active],
                "conditional": conds,
                "enemy": {"level": ENEMY["level"], "res": ENEMY["res"] / 100},
                "reactions": [self._reaction_for(k) for _, k in active],
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
            self._conds, self._cond_rows, self._cond_sig = ([], [], []), [], ""
            self._ids["avg"] = self._ids["detail"] = self._ids["cond"] = None
            self._update_busy()
            self._set_status("")
            self.conditionsChanged.emit()
            self.damageChanged.emit()
            return
        payload = self._payload(active, [], [])
        sig = json.dumps(payload["members"], sort_keys=True)
        if sig != self._cond_sig:
            self._cond_sig = sig
            self._request("cond", "conditionals", payload)
        key = self._selected_key()
        if not key:
            self._ids["avg"] = self._ids["detail"] = None
            self._update_busy()
            self._set_status("")
            self.damageChanged.emit()
            return
        self._ensure_combo(key)
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
            if fix_conditionals(self._conds[0], self._state["conditionals"]):
                self._touch()
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
                found = {f["id"]: f for f in res.get("formulas", [])}
                for f in self._raw_formulas:
                    g = found.get(f["id"])
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
