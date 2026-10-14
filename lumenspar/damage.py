"""Damage calculator backend: Genshin Optimizer's formula engine, run from Python.

The formulas come from Genshin Optimizer (https://github.com/frzyc/genshin-optimizer,
MIT License), its "pando" formula library, bundled as gamedata/go_engine.js by
tools/build_go_engine.py. It is used instead of a re-implementation because
character kits, weapons and artifact sets change every patch and GO already
keeps all of them; updating means rebuilding the bundle, not rewriting formulas.

The bundle runs in Qt's QJSEngine. Percent stats are fractions in the engine
(0.466 = 46.6%), both in inputs and outputs, unlike the rest of Lumenspar
(percent); member_from_card / member_from_good convert. Energy Recharge comes
out without the base 100% (0.123 means 112.3%).

Process model: one `compute` takes ~1.4 s per (member, mode) and loading the
bundle ~1 s. PySide6 does not release the GIL during QJSEngine calls, so a
worker thread would still freeze the GUI; `Engine` therefore talks to a child
process (damage_worker.py). `run_sync` is the blocking in-process form used by
that worker, tests and scripts; it needs a QCoreApplication.

This module also turns the engine's internal keys into readable English
(labels from gamedata/go_labels.json, built by tools/build_go_engine.py).
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


def _go(sheet: str) -> dict:
    return _labels().get("go", {}).get(sheet) or {}


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


def sheet_kind(sheet: str) -> str:
    kind = _game(sheet).get("kind")
    if kind in ("char", "weapon", "artifact"):
        return kind
    return "team"


_PREFIX = re.compile(r"^([ca]\d)(?=[A-Z0-9_]|$)")


# Conditions GO leaves unlabelled, or labels too tersely for a toggle.
_FIXED_LABELS = {
    ("reso", "nearbyDendro1"): "Dendro resonance: after Burning, Quicken or Bloom",
    ("reso", "nearbyDendro2"): "Dendro resonance: after Aggravate, Spread, Hyperbloom or Burgeon",
    ("static", "enemyFrozen"): "Enemy is Frozen",
    ("static", "hasShield"): "Character is shielded",
}
# Generic condition names, labelled from what they belong to.
_GENERIC = {"set4": "4-piece effect active", "set2": "2-piece effect active",
            "state": "Set effect active", "stacks": "Stacks"}


def cond_label(sheet: str, name: str) -> str:
    if (sheet, name) in _FIXED_LABELS:
        return _FIXED_LABELS[(sheet, name)]
    go = _go(sheet)
    low = name.lower()
    label = None
    # (1) exact key
    if name in go:
        label = go[name]
    # (2) "swirl<ele>" (Viridescent Venerer style)
    if label is None:
        m = re.fullmatch(r"swirl(" + "|".join(ELEMENTS) + ")", low)
        if m:
            base = go.get("condName") or go.get("cond") or (
                next(iter(go.values())) if len(go) == 1 else None)
            ele = m.group(1).capitalize()
            label = f"{base}: {ele}" if base else f"Swirled {ele}"
    # (3) a GO key (minus "cond") contained in the name, or the reverse; longest first
    if label is None:
        stems = []
        for k in go:
            stem = re.sub(r"cond$", "", k.lower())
            if len(stem) >= 2 and (stem in low or low in stem):
                stems.append((len(stem), k))
        if stems:
            label = go[max(stems)[1]]
    # (4) c<N> / a<N> prefix against a GO "...Cond" key
    if label is None:
        m = re.match(r"^(c[1-6]|a[0-4])(?=[A-Z0-9])", name)
        if m:
            keys = sorted(k for k in go if k.startswith(m.group(1)) and "cond" in k.lower())
            if keys:
                label = go[keys[0]]
    # a nested group of labels ("c2": {"bloomCondName": ...}): the entry named in this condition
    if isinstance(label, dict):
        pick = [v for k, v in label.items() if isinstance(v, str) and len(k) > 2
                and re.sub(r"(cond|condname)$", "", k.lower()) in low]
        label = pick[0] if len(pick) == 1 else None
    elif not isinstance(label, (str, type(None))):
        label = None
    # (5) the sheet's single generic GO label, when it is about this condition:
    # a generic name, or one sharing a word with the label ("noEnergy" and
    # "Character has 0 energy", but not "afterSkill")
    generic = [k for k in ("cond", "condName") if k in go]
    if label is None and len(generic) == 1:
        words = {w.lower() for w in humanize(name).split() if len(w) >= 4}
        text = strip_tags(go[generic[0]]).lower()
        if name in ("passive", "state", "stacks", "set4", "set2", "cond") or \
                any(re.search(rf"\b{re.escape(w)}\b", text) for w in words):
            label = go[generic[0]]
    if label is None and name in ("passive", "state", "stacks", "set4", "set2", "cond"):
        if name == "passive" and _game(sheet).get("passive"):
            label = _game(sheet)["passive"]
        elif name in _GENERIC:
            label = _GENERIC[name]
    # (6) the name itself
    if label is None:
        label = humanize(name)
        m = _PREFIX.match(name)
        if m and len(name) > 2:
            label = re.sub(r"^([CA]\d) ?", r"\1: ", label, count=1)
    return strip_tags(label)


def cond_detail(sheet: str, name: str) -> str:
    """The game text behind a condition (constellation, passive, weapon or set effect)."""
    g = _game(sheet)
    kind = g.get("kind")
    if kind == "char":
        m = _PREFIX.match(name)
        if not m:
            return ""
        p = m.group(1)
        key = p if p[0] == "c" else {"a1": "passive1", "a4": "passive2", "a0": "passive3"}.get(p)
        entry = g.get(key) if key else None
        if not entry:
            return ""
        return strip_tags(f"{entry.get('name', '')}: {entry.get('text', '')}")
    if kind == "weapon":
        return strip_tags(f"{g.get('passive', '')}: {g.get('passiveText', '')}")
    if kind == "artifact":
        pieces = "2" if "2" in name else "4"
        text = (g.get("effects") or {}).get(pieces, "")
        return strip_tags(f"{pieces}-piece: {text}") if text else ""
    return ""


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


def formula_label(sheet: str, name: str, move: str) -> str:
    go = _go(sheet)
    game = _game(sheet)
    if name in go:
        return strip_tags(go[name])
    params = (game.get("auto") or {}).get("params", {})
    m = re.fullmatch(r"normal_(\d+)", name)
    if m and m.group(1) in params:
        return strip_tags("Normal Attack · " + params[m.group(1)])
    if name == "charged" or name.startswith("charged_"):
        rest = name[len("charged"):].strip("_")
        if rest:
            return strip_tags("Charged Attack · " + humanize(rest))
        hit = next((v for v in params.values() if "Charged Attack DMG" in v), "")
        return strip_tags("Charged Attack · " + (hit or "DMG"))
    if name.startswith("plunging"):
        rest = name[len("plunging"):].strip("_")
        return strip_tags("Plunging Attack · " + humanize(rest or "dmg"))
    if move in ("skill", "burst"):
        title = (game.get(move) or {}).get("name")
        if title:
            return strip_tags(f"{title} · " + humanize(re.sub(rf"^{move}_", "", name)))
    return strip_tags(humanize(name))
