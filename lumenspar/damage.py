"""Damage calculator backend: Genshin Optimizer's formula engine, run from Python.

The formulas come from Genshin Optimizer (https://github.com/frzyc/genshin-optimizer,
MIT License), its production formula engine (libs/gi/wr with the sheets and uidata
libraries, what genshin-optimizer.com runs), bundled as gamedata/go_engine.js by
tools/build_go_engine.py. It is used instead of a re-implementation because
character kits, weapons and artifact sets change every patch and GO already
keeps all of them; updating means rebuilding the bundle, not rewriting formulas.

The bundle runs in Qt's QJSEngine. Percent stats are fractions in the engine
(0.466 = 46.6%), both in inputs and outputs, unlike the rest of Lumenspar
(percent); member_from_card / member_from_good convert. Energy Recharge comes
out as the total (1.123 means 112.3%).

Process model: one `compute` takes ~1.4 s per (member, mode) and loading the
bundle ~1 s. PySide6 does not release the GIL during QJSEngine calls, so a
worker thread would still freeze the GUI; `Engine` therefore talks to a child
process (damage_worker.py). `run_sync` is the blocking in-process form used by
that worker, tests and scripts; it needs a QCoreApplication.

This module also turns the engine's labels ({ns, key, values} objects) into
readable English (gamedata/go_locale.json) and names talents and sets
(gamedata/go_labels.json), both built by tools/build_go_engine.py.
"""

from __future__ import annotations

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal
from PySide6.QtQml import QJSEngine

from . import optimizer

_GAMEDATA = Path(__file__).resolve().parent / "gamedata"
ENGINE_PATH = _GAMEDATA / "go_engine.js"
LABELS_PATH = _GAMEDATA / "go_labels.json"
LOCALE_PATH = _GAMEDATA / "go_locale.json"

ENGINE_FLAG = "--lumenspar-engine-worker"

ELEMENTS = ("pyro", "hydro", "electro", "cryo", "anemo", "geo", "dendro")


# -- conversion: Lumenspar data -> engine input ------------------------------

def _frac(key: str, value: float) -> float:
    """Percent stats (GOOD keys ending in "_") become fractions."""
    return value / 100 if key.endswith("_") else value


def _stat(key: str, value: float) -> dict:
    return {"key": key, "value": _frac(key, value)}


def _weapon(w: dict) -> dict:
    return {"key": w["key"], "level": w["level"], "ascension": w["ascension"],
            "refinement": w["refinement"]}


def member_from_card(card: dict) -> dict:
    """An engine team member from a build card (builds.py)."""
    w = card.get("weapon")
    if not w:
        raise ValueError("the build has no weapon")
    if any(t.get("base") is None for t in card.get("talents", [])):
        # Cards from HoYoLAB show in-game talent levels, bonuses included; the
        # engine needs the base levels, which only the showcase reads.
        raise ValueError("the build's base talent levels are unknown (read it from the "
                         "showcase too)")
    talents = {t["slot"]: t["base"] for t in card.get("talents", [])}
    arts = []
    for a in card.get("artifacts", []):
        stats = [_stat(a["main"]["key"], a["main"]["value"])]
        stats += [_stat(s["key"], s["value"]) for s in a.get("subs", [])]
        arts.append({"set": a["setKey"], "stats": stats})
    return {
        "char": {"key": card["key"], "level": card["level"],
                 "constellation": card.get("constellation", 0),
                 "ascension": card.get("ascension", 0),
                 "talent": {s: talents.get(s, 1) for s in ("auto", "skill", "burst")}},
        "weapon": _weapon(w),
        "artifacts": arts,
    }


DEFAULT_WEAPONS = {"sword": "FavoniusSword", "claymore": "FavoniusGreatsword",
                   "polearm": "FavoniusLance", "catalyst": "FavoniusCodex",
                   "bow": "FavoniusWarbow"}


def ascension_for(level: int) -> int:
    """The ascension phase a level implies."""
    for phase, top in enumerate((20, 40, 50, 60, 70, 80)):
        if level <= top:
            return phase
    return 6


@lru_cache(maxsize=1)
def _character_info() -> dict:
    try:
        items = json.loads((_GAMEDATA / "characters.json").read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError):
        return {}
    return {c["key"]: c for c in items if c.get("key")}


def default_settings(key: str) -> dict:
    """Settings of a character picked from the full list: maxed, no constellations."""
    info = _character_info().get(key, {})
    return {"level": 90, "constellation": 0, "auto": 9, "skill": 9, "burst": 9,
            "weapon": DEFAULT_WEAPONS.get(info.get("weaponType"), "FavoniusSword"),
            "weaponLevel": 90, "refinement": 1}


def member_from_settings(key: str, s: dict) -> dict:
    """An engine team member from editable settings: no artifacts."""
    return {
        "char": {"key": key, "level": s["level"], "constellation": s["constellation"],
                 "ascension": ascension_for(s["level"]),
                 "talent": {"auto": s["auto"], "skill": s["skill"], "burst": s["burst"]}},
        "weapon": {"key": s["weapon"], "level": s["weaponLevel"],
                   "ascension": ascension_for(s["weaponLevel"]), "refinement": s["refinement"]},
        "artifacts": [],
    }


def member_from_good(good: dict, char_key: str) -> dict | None:
    """An engine team member from a .GOOD export, or None without the character or its weapon."""
    char = next((c for c in good.get("characters", []) if c.get("key") == char_key), None)
    if char is None:
        return None
    locs = {char_key}
    if char_key.startswith("Traveler"):
        locs.add("Traveler")
    weapon = next((w for w in good.get("weapons", []) if w.get("location") in locs), None)
    if weapon is None:
        return None
    arts = []
    for a in good.get("artifacts", []):
        if a.get("location") not in locs:
            continue
        mk = a["mainStatKey"]
        main = optimizer.main_value(int(a.get("rarity") or 5), int(a.get("level") or 0), mk)
        stats = [_stat(mk, main)]
        stats += [_stat(s["key"], s["value"]) for s in a.get("substats", []) if s.get("key")]
        arts.append({"set": a["setKey"], "stats": stats})
    talent = char.get("talent") or {}
    return {
        "char": {"key": char_key, "level": char.get("level", 1),
                 "constellation": char.get("constellation", 0),
                 "ascension": char.get("ascension", 0),
                 "talent": {s: talent.get(s, 1) for s in ("auto", "skill", "burst")}},
        "weapon": _weapon(weapon),
        "artifacts": arts,
    }


# -- running the engine ------------------------------------------------------

@lru_cache(maxsize=1)
def load_source() -> str:
    return ENGINE_PATH.read_text(encoding="utf-8")


def run_sync(fn: str, payload: dict, engine: QJSEngine | None = None) -> dict | list:
    """Call LumensparGO[fn](payload) and return the parsed result (blocking).

    Uses a fresh QJSEngine on the current thread unless one created on this
    thread is given (the bundle is evaluated once per engine). Needs a
    QCoreApplication. Raises RuntimeError on a JavaScript error.
    """
    if engine is None:
        engine = QJSEngine()
    if not getattr(engine, "_go_loaded", False):
        res = engine.evaluate(load_source(), str(ENGINE_PATH))
        if res.isError():
            raise RuntimeError(res.toString())
        engine._go_loaded = True
    api = engine.globalObject().property("LumensparGO")
    func = api.property(fn)
    if not func.isCallable():
        raise RuntimeError(f"unknown engine function: {fn}")
    result = func.call([engine.toScriptValue(json.dumps(payload))])
    if result.isError():
        raise RuntimeError(result.toString())
    return json.loads(result.toString())


class Engine(QObject):
    """Runs engine requests in a child process; results come back as signals.

    The child (damage_worker.py) has its own interpreter: PySide6 holds the GIL
    during QJSEngine calls, so a thread would still freeze the GUI. It starts
    in the background on construction (loading the bundle takes ~1 s) and is
    restarted on the next request if it dies.
    """

    finished = Signal(int, object)   # request id, parsed result
    failed = Signal(int, str)        # request id, message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._next_id = 0
        self._pending: set[int] = set()
        self._buf = b""
        self._proc: QProcess | None = None
        self._start()

    def _start(self) -> None:
        proc = QProcess(self)
        if getattr(sys, "frozen", False):
            program, args = sys.executable, [ENGINE_FLAG]
        else:
            root = str(Path(__file__).resolve().parent.parent)
            env = QProcessEnvironment.systemEnvironment()
            old = env.value("PYTHONPATH")
            env.insert("PYTHONPATH", root + (os.pathsep + old if old else ""))
            proc.setProcessEnvironment(env)
            proc.setWorkingDirectory(root)
            program, args = sys.executable, ["-m", "lumenspar", ENGINE_FLAG]
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.errorOccurred.connect(self._on_error)
        proc.finished.connect(self._on_exit)
        self._buf = b""
        self._proc = proc
        proc.start(program, args)

    def request(self, fn: str, payload: dict) -> int:
        if self._proc is None or self._proc.state() == QProcess.NotRunning:
            self._drop_proc()
            self._start()
        self._next_id += 1
        rid = self._next_id
        self._pending.add(rid)
        line = json.dumps({"id": rid, "fn": fn, "payload": payload}) + "\n"
        self._proc.write(line.encode("utf-8"))
        return rid

    def _on_stdout(self) -> None:
        self._buf += bytes(self._proc.readAllStandardOutput())
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            if not raw.strip():
                continue
            try:
                msg = json.loads(raw.decode("utf-8"))
                rid = msg["id"]
            except (ValueError, KeyError, TypeError):
                continue
            if rid not in self._pending:
                continue
            self._pending.discard(rid)
            if msg.get("ok"):
                self.finished.emit(rid, msg.get("result"))
            else:
                self.failed.emit(rid, str(msg.get("error") or "engine error"))

    def _on_stderr(self) -> None:
        sys.stderr.write(bytes(self._proc.readAllStandardError()).decode("utf-8", "replace"))

    def _on_error(self, _err) -> None:
        if self._proc is not None and self._proc.state() == QProcess.NotRunning:
            self._fail_pending()

    def _on_exit(self, *_args) -> None:
        self._fail_pending()

    def _fail_pending(self) -> None:
        pending, self._pending = sorted(self._pending), set()
        for rid in pending:
            self.failed.emit(rid, "The damage engine stopped unexpectedly; "
                                  "it will restart on the next request.")

    def _drop_proc(self) -> None:
        if self._proc is not None:
            self._proc.blockSignals(True)
            self._proc.deleteLater()
            self._proc = None

    def shutdown(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.state() != QProcess.NotRunning:
            proc.closeWriteChannel()
            if not proc.waitForFinished(3000):
                proc.kill()
                proc.waitForFinished(2000)


# -- readable labels ----------------------------------------------------------

@lru_cache(maxsize=1)
def _labels() -> dict:
    return json.loads(LABELS_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _locale() -> dict:
    return json.loads(LOCALE_PATH.read_text(encoding="utf-8"))


def _game(sheet: str) -> dict:
    return _labels().get("game", {}).get(sheet) or {}


def strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", text or "")).strip()


def humanize(name: str) -> str:
    """camelCase / digits to words: "a4DeathStacks" -> "A4 Death Stacks"."""
    s = name.replace("_", " ")
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s[:1].upper() + s[1:]
    return re.sub(r"\bdmg\b", "DMG", s, flags=re.IGNORECASE)


def sheet_title(sheet: str) -> str:
    name = _game(sheet).get("name")
    if name:
        return name
    if sheet == "reso":
        return "Elemental Resonance"
    if sheet == "static":
        return "Enemy & shields"
    return humanize(sheet)


def option_label(value: str) -> str:
    if value.lower() in ELEMENTS or value.lower() == "physical":
        return value.capitalize()
    if value.isdigit():
        return value
    special = {"sc": "Stellar-Conduct", "ss": "Stellar Swirl", "on": "On"}
    if value in special:
        return special[value]
    m = re.fullmatch(r"lunar([a-z]+)", value)
    if m:
        return "Lunar-" + m.group(1).capitalize()
    return humanize(value)


def _value_text(v) -> str:
    if isinstance(v, float) and v == int(v):
        v = int(v)
    elif isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return str(v)


def render_label(label) -> str:
    """The English text of an engine label: None, a string, a list, {"children"}
    or {"ns", "key", "values"} (a lookup in go_locale.json)."""
    return re.sub(r"\s+", " ", _render(label)).strip()


def _render(label) -> str:
    """render_label without collapsing spaces, so joined parts keep theirs."""
    if isinstance(label, str):
        return re.sub(r"<[^>]*>", "", label)
    if isinstance(label, list):
        return "".join(_render(x) for x in label)
    if not isinstance(label, dict):
        return ""
    if "children" in label:
        return _render(label["children"])
    key = str(label.get("key") or "")
    values = label.get("values") or {}
    parts = key.split(".")
    node = _locale().get(label.get("ns") or "sheet")
    for part in parts[:-1]:
        node = node.get(part) if isinstance(node, dict) else None
    text = None
    if isinstance(node, dict):
        last = parts[-1]
        names = [last]
        if "count" in values:
            names.insert(0, last + ("_one" if values["count"] == 1 else "_other"))
        text = next((node[n] for n in names if isinstance(node.get(n), str)), None)
    if text is None:
        return humanize(parts[-1]) if parts[-1] else ""
    text = re.sub(r"\{\{\s*(\w+)\s*\}\}",
                  lambda m: _value_text(values[m.group(1)]) if m.group(1) in values else m.group(0),
                  text)
    return re.sub(r"<[^>]*>", "", text)


def talent_title(char_key: str, section: str) -> str:
    """The heading of a talent section ("burst" -> "Elemental Burst · <name>")."""
    game = _game(char_key)

    def named(prefix: str, entry: str) -> str:
        name = (game.get(entry) or {}).get("name")
        return f"{prefix} · {name}" if name else prefix

    if section == "auto":
        return "Normal Attack"
    if section == "skill":
        return named("Elemental Skill", "skill")
    if section == "burst":
        return named("Elemental Burst", "burst")
    if section == "reaction":
        return "Reactions"
    if section == "weapon":
        return "Weapon"
    if re.fullmatch(r"passive[1-3]", section):
        return named("Passive", section)
    m = re.fullmatch(r"constellation([1-6])", section)
    if m:
        return named(f"C{m.group(1)}", f"c{m.group(1)}")
    return humanize(section)
