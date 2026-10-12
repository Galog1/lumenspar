"""Akasha.cv rankings: the player's own results, a leaderboard sample, and its damage formula.

Akasha has no documented API. The endpoints used here are the ones its own
site uses; they change without notice, so every failure becomes an
AkashaError with a readable message. Requests are few, made on user action,
cached (profile 1 h, leaderboards 24 h) and identified by User-Agent.

Leaderboard rows carry other players' UIDs and names; only their stats,
4-piece set and result are kept - identities are never stored, cache
included. Akasha scores every build with the character reset to the same
level/talents/weapon/team, so a leaderboard's result depends on the build's
stats alone, which is what makes learning its formula from a sample possible.

A player has live builds (type "current", the artifacts worn right now) and
builds saved under a name. getCalculationsForUser highlights one build per
character, which may be a saved one, so profile() can describe a build the
player no longer wears; the per-build endpoint (build_info) gives the live
build's exact ranks, plus the top-1% average stats Akasha draws on its build
graphs. The exact rank of any result is found with rank_of, through the
leaderboard's result cursor (the first build below a value carries its
absolute index).

A character has several leaderboards (categories, one per weapon); boards()
lists them. A variant is only a filter on one board: builds with Energy
Recharge at or above a floor (Variant.min_er). Rows also keep the main stats
of sands/goblet/circlet, so common() can tell which 4-piece sets and main
stats the top builds of a board use, even for a board the player is not on.
"""

from __future__ import annotations

import json
import itertools
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np

from .config import DATA_DIR
from .optimizer import D, IDX
from .wishes.icons import USER_AGENT

API = "https://akasha.cv/api/"
CACHE_DIR = DATA_DIR / "akasha"
PROFILE_TTL = 3600
BUILDS_TTL = 3600
BOARD_TTL = 86400
PAGE = 50
PAUSE = 0.6
_GAMEDATA = Path(__file__).resolve().parent / "gamedata"
_MIN_ROWS = 20

_ELEMENTS = ("pyro", "hydro", "electro", "cryo", "anemo", "geo", "dendro", "physical")

# Akasha stat name -> (our key, factor to our percent units).
STAT_MAP: dict[str, tuple[str, float]] = {
    "atk": ("atk", 1.0),
    "maxHp": ("hp", 1.0),
    "def": ("def", 1.0),
    "elementalMastery": ("eleMas", 1.0),
    "critRate": ("critRate_", 100.0),
    "critDamage": ("critDMG_", 100.0),
    "energyRecharge": ("enerRech_", 100.0),
    "healingBonus": ("heal_", 100.0),
}
for _e in _ELEMENTS:
    STAT_MAP[f"{_e}DamageBonus"] = (f"{_e}_dmg_", 100.0)


class AkashaError(Exception):
    """Akasha.cv could not be read; the message is fit to show the user."""


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _get(path: str, params: dict, fetch: Callable[[str], bytes] | None = None) -> object:
    """One Akasha.cv API call; returns the payload's "data"."""
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        return json.loads((fetch or _download)(url))["data"]
    except urllib.error.HTTPError as exc:
        raise AkashaError(f"Akasha.cv answered {exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise AkashaError(f"could not reach Akasha.cv ({exc})") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)") from exc


def _read_cache(path: Path, ttl: float, now: Callable[[], float]) -> dict | None:
    """The cached JSON at path when it is younger than ttl, else None."""
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if now() - float(cached["time"]) < ttl:
            return cached
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _write_cache(path: Path, payload: dict) -> None:
    """Atomic write; a failed cache write is not worth failing the request."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


@dataclass
class Calc:
    """One character's ranked calculation on Akasha."""
    avatar_id: str
    character: str
    calculation_id: str
    variant: str
    variant_label: str
    name: str
    short: str
    details: str
    result: float
    ranking: int
    out_of: int
    weapon: str
    updated: str
    # The sets of the build Akasha last saw ({name: pieces}), to tell whether
    # it is the build the showcase shows now.
    sets: dict[str, int] = field(default_factory=dict)

    @property
    def top_percent(self) -> float:
        return self.ranking / self.out_of * 100 if self.out_of else 0.0

    def rank_text(self) -> str:
        if self.out_of == 0:
            return ""
        p = self.top_percent
        pct = f"{p:.2f}%" if p < 1 else f"{p:.1f}%"
        return f"top {pct} · #{self.ranking:,} of {self.out_of:,}"

    def min_er(self) -> float | None:
        """The Energy Recharge floor of an "NNNer" variant; None for other variants."""
        m = re.fullmatch(r"(\d+)er", self.variant)
        return float(m.group(1)) if m else None


def profile(uid: str, fetch: Callable[[str], bytes] | None = None, root: Path = CACHE_DIR,
            now: Callable[[], float] = time.time) -> dict[str, Calc]:
    """The player's own ranked calculation per character (avatar id -> Calc)."""
    path = root / f"profile-{uid}.json"
    cached = _read_cache(path, PROFILE_TTL, now)
    if cached is not None:
        try:
            return {c["avatar_id"]: Calc(**c) for c in cached["calcs"]}
        except (KeyError, TypeError):
            pass
    data = _get(f"getCalculationsForUser/{uid}", {}, fetch)
    if not isinstance(data, list):
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)")
    out: dict[str, Calc] = {}
    current: set[str] = set()
    try:
        for e in data:
            if not isinstance(e, dict):
                continue
            fit = (e.get("calculations") or {}).get("fit")
            if not fit:
                continue
            variant = fit.get("variant") or {}
            calc = Calc(
                avatar_id=str(e.get("characterId")),
                character=e.get("name", ""),
                calculation_id=str(fit.get("calculationId", "")),
                variant=variant.get("name", "") or "",
                variant_label=variant.get("displayName", "") or "",
                name=fit.get("name", ""),
                short=fit.get("short", ""),
                details=fit.get("details", ""),
                result=float(fit.get("result") or 0),
                ranking=int(fit.get("ranking") or 0),
                out_of=int(fit.get("outOf") or 0),
                weapon=(fit.get("weapon") or {}).get("name", ""),
                updated=str(e.get("lastBuildUpdate", "")),
                sets={str(n): int((i or {}).get("count", 0))
                      for n, i in (e.get("artifactSets") or {}).items()},
            )
            is_current = e.get("type") == "current"
            if calc.avatar_id in out and (calc.avatar_id in current or not is_current):
                continue
            out[calc.avatar_id] = calc
            if is_current:
                current.add(calc.avatar_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)") from exc
    _write_cache(path, {"time": now(), "calcs": [asdict(c) for c in out.values()]})
    return out


def live_builds(uid: str, fetch: Callable[[str], bytes] | None = None, root: Path = CACHE_DIR,
                now: Callable[[], float] = time.time) -> dict[str, dict]:
    """The player's live builds (avatar id -> {"md5", "updated", "sets"})."""
    path = root / f"builds-{uid}.json"
    cached = _read_cache(path, BUILDS_TTL, now)
    if cached is not None and isinstance(cached.get("builds"), dict):
        return cached["builds"]
    params = {"sort": "critValue", "order": -1, "size": 100, "page": 1, "filter": "",
              "uids": "", "p": "", "fromId": "", "li": "", "uid": uid}
    data = _get("builds/", params, fetch)
    if not isinstance(data, list):
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)")
    out: dict[str, dict] = {}
    try:
        for e in data:
            if not isinstance(e, dict) or e.get("type") != "current":
                continue
            avatar = str(e["characterId"])
            build = {"md5": str(e["md5"]), "updated": int(e.get("lastBuildUpdate") or 0),
                     "sets": {str(n): int((i or {}).get("count", 0))
                              for n, i in (e.get("artifactSets") or {}).items()}}
            if avatar not in out or build["updated"] > out[avatar]["updated"]:
                out[avatar] = build
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)") from exc
    _write_cache(path, {"time": now(), "builds": out})
    return out


@dataclass
class BuildInfo:
    """One build's exact calculations and Akasha's top-1% average stats per calculation."""
    calcs: list[Calc]
    top1: dict[str, dict[str, float]]
    # This build's own stats as Akasha computed them per calculation (the
    # character standardised: its level, C0, an R1 weapon), in our keys/units.
    # The difference to the in-game panel puts Akasha's averages on the
    # panel's scale.
    mine: dict[str, dict[str, float]] = field(default_factory=dict)


# Keys of a calculation's own "stats" (already in percent, unlike avgStats).
_CALC_STATS = {"maxHP": "hp", "maxATK": "atk", "maxDEF": "def", "elementalMastery": "eleMas",
               "critRate": "critRate_", "critDMG": "critDMG_"}


def build_info(uid: str, avatar_id: str, md5: str, fetch: Callable[[str], bytes] | None = None,
               root: Path = CACHE_DIR, now: Callable[[], float] = time.time) -> BuildInfo:
    """A build's ranked calculations (best first) and the top-1% average stats."""
    path = root / f"build-{md5}.json"
    cached = _read_cache(path, PROFILE_TTL, now)
    if cached is not None:
        try:
            return BuildInfo([Calc(**c) for c in cached["calcs"]],
                             {str(k): dict(v) for k, v in cached["top1"].items()},
                             {str(k): dict(v) for k, v in cached.get("mine", {}).items()})
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
    data = _get(f"leaderboards/{uid}/{md5}", {"variant": "profilePage"}, fetch)
    if not isinstance(data, dict) or not isinstance(data.get("calculations"), dict):
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)")
    calcs: list[Calc] = []
    try:
        for cid, c in data["calculations"].items():
            variant = c.get("variant") or {}
            calcs.append(Calc(
                avatar_id=avatar_id,
                character="",
                calculation_id=str(cid),
                variant=variant.get("name", "") or "",
                variant_label=variant.get("displayName", "") or "",
                name=c.get("name", ""),
                short=c.get("short", ""),
                details=c.get("details", ""),
                result=float(c.get("result") or 0),
                ranking=int(c.get("ranking") or 0),
                out_of=int(c.get("outOf") or 0),
                weapon=(c.get("weapon") or {}).get("name", ""),
                updated="",
                sets={},
            ))
    except (ValueError, TypeError, AttributeError) as exc:
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)") from exc
    calcs.sort(key=lambda c: c.top_percent if c.out_of else math.inf)
    mine: dict[str, dict[str, float]] = {}
    for cid, c in data["calculations"].items():
        raw = c.get("stats") if isinstance(c, dict) else None
        if isinstance(raw, dict):
            mine[str(cid)] = {key: float(raw[k]) for k, key in _CALC_STATS.items()
                              if isinstance(raw.get(k), (int, float))}
    top1: dict[str, dict[str, float]] = {}
    charts = data.get("chartsData")
    metas = charts.get("charts1pMetadata") if isinstance(charts, dict) else None
    for m in metas if isinstance(metas, list) else []:
        try:
            stats = {STAT_MAP[k][0]: float(v) * STAT_MAP[k][1]
                     for k, v in m.get("avgStats", {}).items() if k in STAT_MAP}
            top1[str(m["calculationId"])] = stats
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    _write_cache(path, {"time": now(), "calcs": [asdict(c) for c in calcs], "top1": top1,
                        "mine": mine})
    return BuildInfo(calcs, top1, mine)


def pick(calcs: list[Calc], weapon: str) -> Calc | None:
    """The best-ranked calculation for the given weapon, else the best overall."""
    if not calcs:
        return None
    same = [c for c in calcs if c.weapon.lower() == weapon.lower()]
    return min(same or calcs, key=lambda c: c.top_percent)


def rank_of(calc: Calc, value: float, fetch: Callable[[str], bytes] | None = None) -> int:
    """The exact rank a result would take on the calculation's leaderboard (0 if unknown)."""
    params = {"sort": "calculation.result", "order": -1, "size": 1, "page": 1,
              "calculationId": calc.calculation_id, "variant": calc.variant, "p": f"lt|{value}"}
    data = _get("leaderboards", params, fetch)
    if not isinstance(data, list):
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)")
    if not data:
        return calc.out_of + 1 if calc.out_of else 0
    try:
        return int(data[0]["index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)") from exc


@dataclass
class Variant:
    """An Energy Recharge filter of a leaderboard."""
    name: str
    label: str
    min_er: float


@dataclass
class Board:
    """One leaderboard of a character: a calculation with a given weapon."""
    name: str
    short: str
    details: str
    calculation_id: str
    weapon: str
    refinement: int
    default_variant: str
    variants: list[Variant]


def boards(character_id: str, fetch: Callable[[str], bytes] | None = None, root: Path = CACHE_DIR,
           now: Callable[[], float] = time.time) -> list[Board]:
    """Every visible leaderboard of a character (one per category and weapon), in Akasha's order."""
    path = root / f"boards-{character_id}.json"
    cached = _read_cache(path, BOARD_TTL, now)
    if cached is not None:
        try:
            return [Board(**{**b, "variants": [Variant(**v) for v in b["variants"]]})
                    for b in cached["boards"]]
        except (KeyError, TypeError):
            pass
    data = _get("v2/leaderboards/categories", {"characterId": character_id}, fetch)
    if not isinstance(data, list):
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)")
    out: list[Board] = []
    try:
        for cat in data:
            if not isinstance(cat, dict) or cat.get("hidden"):
                continue
            for w in cat.get("weapons") or []:
                if not isinstance(w, dict) or w.get("hidden"):
                    continue
                variants: list[Variant] = []
                for f in w.get("filters") or []:
                    q = f.get("query") or {}
                    if q.get("operator") != "$gte" or q.get("field") != "stats.energyRecharge.value":
                        continue
                    variants.append(Variant(name=str(f.get("name", "")),
                                            label=str(f.get("displayName", "") or ""),
                                            min_er=round(float(q["value"]) * 100 + 1e-6, 1)))
                out.append(Board(
                    name=cat.get("name", ""), short=cat.get("short", ""),
                    details=cat.get("details", "") or "",
                    calculation_id=str(w["calculationId"]), weapon=w.get("name", ""),
                    refinement=int(w.get("refinement") or 0),
                    default_variant=w.get("defaultVariant") or "", variants=variants))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)") from exc
    _write_cache(path, {"time": now(), "boards": [asdict(b) for b in out]})
    return out


def boards_for_weapon(all_boards: list[Board], weapon: str) -> list[Board]:
    """The boards of the given weapon; [] when it has none."""
    return [b for b in all_boards if b.weapon.lower() == weapon.lower()]


def calc_for_board(board: Board, variant: str, mine: list[Calc]) -> Calc:
    """The Calc to use for a board and variant: the player's own result on it, else an empty one."""
    label = next((v.label for v in board.variants if v.name == variant), "")
    for c in mine:
        if c.calculation_id == board.calculation_id:
            same = c.variant == variant
            return replace(c, variant=variant, variant_label=label,
                           ranking=c.ranking if same else 0, out_of=c.out_of if same else 0)
    return Calc(avatar_id="", character="", calculation_id=board.calculation_id, variant=variant,
                variant_label=label, name=board.name, short=board.short, details=board.details,
                result=0.0, ranking=0, out_of=0, weapon=board.weapon, updated="", sets={})


@lru_cache(maxsize=None)
def _set_keys() -> dict[str, str]:
    """Artifact set name -> our set key."""
    try:
        items = json.loads((_GAMEDATA / "artifact_sets.json").read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError):
        return {}
    return {i["name"]: i["key"] for i in items if "key" in i and "name" in i}


_MAIN_KEYS = {
    "atk%": "atk_", "hp%": "hp_", "def%": "def_", "elemental mastery": "eleMas",
    "energy recharge": "enerRech_", "crit rate": "critRate_", "crit dmg": "critDMG_",
    "healing bonus": "heal_",
}
for _e in _ELEMENTS:
    _MAIN_KEYS[f"{_e} dmg bonus"] = f"{_e}_dmg_"

_MAIN_SLOTS = {"EQUIP_SHOES": "sands", "EQUIP_RING": "goblet", "EQUIP_DRESS": "circlet"}


def _main_key(label: str) -> str:
    """Our stat key for one of Akasha's main stat labels; "" when unknown."""
    return _MAIN_KEYS.get(str(label).strip().lower(), "")


@dataclass
class Row:
    """A leaderboard build, anonymous: our stats, its 4-piece set key, main stats and Akasha's result."""
    stats: dict[str, float]
    set4: str
    result: float
    # Main stat key of sands/goblet/circlet ({slot: key}); a missing slot is unknown.
    mains: dict[str, str] = field(default_factory=dict)


def _row(r: dict) -> Row:
    stats: dict[str, float] = {}
    for akey, (key, factor) in STAT_MAP.items():
        try:
            stats[key] = float(r["stats"][akey]["value"]) * factor
        except (KeyError, TypeError):
            continue
    # artifactSets maps set name -> {"icon", "count"}.
    set4 = ""
    for name, info in (r.get("artifactSets") or {}).items():
        if int((info or {}).get("count", 0)) >= 4:
            set4 = _set_keys().get(name, "")
            break
    mains: dict[str, str] = {}
    for akey, slot in _MAIN_SLOTS.items():
        try:
            key = _main_key(r["artifactObjects"][akey]["mainStatKey"])
        except (KeyError, TypeError):
            continue
        if key:
            mains[slot] = key
    return Row(stats=stats, set4=set4, result=float(r["calculation"]["result"]), mains=mains)


def sample(calc: Calc, fetch: Callable[[str], bytes] | None = None, root: Path = CACHE_DIR,
           now: Callable[[], float] = time.time,
           sleep: Callable[[float], None] = time.sleep) -> tuple[list[Row], float]:
    """A spread of leaderboard builds around the player's result: (rows, top result)."""
    path = root / f"board2-{calc.calculation_id}-{calc.variant or 'none'}.json"
    cached = _read_cache(path, BOARD_TTL, now)
    if cached is not None:
        try:
            return [Row(**r) for r in cached["rows"]], float(cached["top"])
        except (KeyError, TypeError, ValueError):
            pass
    params = {"sort": "calculation.result", "order": -1, "size": PAGE,
              "calculationId": calc.calculation_id, "variant": calc.variant}
    cursors = ["", f"lt|{calc.result * 1.15}", f"lt|{calc.result * 1.0001}",
               f"lt|{calc.result * 0.85}"]
    rows: list[Row] = []
    seen: set = set()
    for i in range(len(cursors)):
        if i:
            sleep(PAUSE)
            if i == 1 and calc.result <= 0:
                # Not on this leaderboard: spread below the best build instead.
                best = max((r.result for r in rows), default=0.0)
                cursors = ["", f"lt|{best * 0.97}", f"lt|{best * 0.93}", f"lt|{best * 0.88}"]
        cursor = cursors[i]
        data = _get("leaderboards", {**params, "p": cursor}, fetch)
        if not isinstance(data, list):
            raise AkashaError("Akasha.cv sent something unexpected (its site may have changed)")
        for r in data:
            if not isinstance(r, dict):
                continue
            rid = r.get("_id")
            if rid is not None:
                if rid in seen:
                    continue
                seen.add(rid)
            try:
                row = _row(r)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if row.result > 0:
                rows.append(row)
    top = max((r.result for r in rows), default=0.0)
    if len(rows) < _MIN_ROWS:
        raise AkashaError("Akasha.cv returned too few builds for this leaderboard")
    _write_cache(path, {"time": now(), "top": top, "rows": [asdict(r) for r in rows]})
    return rows, top


def common(rows: list[Row], top_share: float = 0.5
           ) -> tuple[list[tuple[str, float]], dict[str, list[tuple[str, float]]]]:
    """What the best builds of a sample use: ([(set4 key, share)], {slot: [(main key, share)]})."""
    best = sorted(rows, key=lambda r: r.result, reverse=True)
    best = best[:min(len(best), max(_MIN_ROWS, math.ceil(len(best) * top_share)))]
    sets: dict[str, int] = {}
    for r in best:
        if r.set4:
            sets[r.set4] = sets.get(r.set4, 0) + 1
    set_shares = sorted(((k, c / len(best)) for k, c in sets.items() if c / len(best) >= 0.05),
                        key=lambda kv: -kv[1])
    mains: dict[str, list[tuple[str, float]]] = {}
    for slot in _MAIN_SLOTS.values():
        have = [r.mains[slot] for r in best if slot in r.mains]
        counts: dict[str, int] = {}
        for k in have:
            counts[k] = counts.get(k, 0) + 1
        mains[slot] = sorted(((k, c / len(have)) for k, c in counts.items()
                              if c / len(have) >= 0.10), key=lambda kv: -kv[1])
    return set_shares, mains


@dataclass
class Model:
    """A leaderboard's learned formula:
    result = exp(factor[set]) * (S + s0) * (1 + min(CR + k, 1) * CD) * (1 + DMG + d0)."""
    scaling: str
    s0: float
    k: float
    d0: float
    crit: bool
    element: str
    factors: dict[str, float]
    default: float
    rms: float
    n: int
    # Reaction calculations: x (1 + em_a * EM / (EM + em_b)), the game's
    # amplifying (2.78, 1400) or transformative-style bonus; em_a 0 = none.
    em_a: float = 0.0
    em_b: float = 1.0

    def _dmg_key(self) -> str:
        key = f"{self.element}_dmg_"
        return key if key in IDX else "physical_dmg_"

    def predict(self, final: np.ndarray, set_key: str) -> np.ndarray:
        """Predicted results for (N, D) final stats in the optimizer's KEYS layout."""
        s = final[:, IDX[self.scaling]]
        cr = final[:, IDX["critRate_"]] / 100
        cd = final[:, IDX["critDMG_"]] / 100
        dm = final[:, IDX[self._dmg_key()]] / 100
        v = np.log(np.maximum(s + self.s0, 1.0)) + np.log1p(dm + self.d0)
        if self.crit:
            v = v + np.log1p(np.minimum(cr + self.k, 1.0) * cd)
        if self.em_a:
            em = final[:, IDX["eleMas"]]
            v = v + np.log1p(self.em_a * em / (em + self.em_b))
        v = v + self.factors.get(set_key, self.default)
        return np.exp(v)

    def predict_stats(self, stats: dict[str, float], set_key: str) -> float:
        row = np.zeros((1, D))
        for key, value in stats.items():
            if key in IDX:
                row[0, IDX[key]] = value
        return float(self.predict(row, set_key)[0])


# EM bonuses a reaction calculation may carry, (a, b) in a * EM / (EM + b):
# none, amplifying reactions, and two transformative-style curves.
EM_FORMS = ((0.0, 1.0), (2.78, 1400.0), (5.0, 2000.0), (16.0, 2000.0))


def fit(rows: list[Row], element: str) -> Model:
    """Learn the leaderboard's formula from a sample by a grid search over its few unknowns."""
    if len(rows) < _MIN_ROWS:
        raise AkashaError("too few leaderboard builds to learn its formula")
    probe = Model("atk", 0, 0, 0, True, element, {}, 0, 0, 0)
    dmg_key = probe._dmg_key()
    y = np.log(np.array([r.result for r in rows]))
    cr = np.array([r.stats.get("critRate_", 0.0) for r in rows]) / 100
    cd = np.array([r.stats.get("critDMG_", 0.0) for r in rows]) / 100
    dm = np.array([r.stats.get(dmg_key, 0.0) for r in rows]) / 100
    cands = {s: np.array([r.stats.get(s, 0.0) for r in rows])
             for s in ("atk", "hp", "def", "eleMas")}
    em = cands["eleMas"]

    # Sets with enough builds get their own factor; the rest share one centred group.
    counts: dict[str, int] = {}
    for r in rows:
        if r.set4:
            counts[r.set4] = counts.get(r.set4, 0) + 1
    own = sorted(k for k, c in counts.items() if c >= 5)
    labels = np.array([r.set4 if r.set4 in own else "" for r in rows])
    groups = {g: labels == g for g in own + [""]}
    groups = {g: m for g, m in groups.items() if m.any()}

    t_grid = np.arange(-0.3, 1.5001, 0.1)
    k_grid = np.arange(0, 0.8001, 0.04)
    d_grid = np.arange(0, 8.0001, 0.2)
    ld = np.log1p(dm[None, :] + d_grid[:, None])

    best_rms = math.inf
    best: tuple | None = None  # scaling, s0, crit, k, d0, em_a, em_b
    for (em_a, em_b), scaling in itertools.product(EM_FORMS, cands):
        s = cands[scaling]
        if not s.std() > 0:
            continue
        le = np.log1p(em_a * em / (em + em_b)) if em_a else 0.0
        med = float(np.median(s))
        for t in t_grid:
            s0 = float(t * med)
            ls = np.log(np.maximum(s + s0, 1.0))
            for crit in (True, False):
                for k in (k_grid if crit else [0.0]):
                    lc = np.log1p(np.minimum(cr + k, 1.0) * cd) if crit else 0.0
                    res = (y - ls - lc - le)[None, :] - ld
                    for g in groups.values():
                        res[:, g] -= res[:, g].mean(axis=1, keepdims=True)
                    rms = np.sqrt(np.mean(res ** 2, axis=1))
                    j = int(np.argmin(rms))
                    # Prefer the simpler explanation on (near) ties: crit, no EM term.
                    margin = 1e-4 if best is not None and (best[2] and not crit
                                                           or not best[5] and em_a) else 0.0
                    if rms[j] < best_rms - margin:
                        best_rms = float(rms[j])
                        best = (scaling, s0, crit, float(k), float(d_grid[j]), em_a, em_b)
    if best is None:
        raise AkashaError("could not learn this leaderboard's formula")
    scaling, s0, crit, k, d0, em_a, em_b = best
    ls = np.log(np.maximum(cands[scaling] + s0, 1.0))
    lc = np.log1p(np.minimum(cr + k, 1.0) * cd) if crit else 0.0
    le = np.log1p(em_a * em / (em + em_b)) if em_a else 0.0
    r0 = y - ls - lc - le - np.log1p(dm + d0)
    factors = {g: float(r0[m].mean()) for g, m in groups.items() if g}
    return Model(scaling=scaling, s0=s0, k=k, d0=d0, crit=crit, element=element,
                 factors=factors, default=float(r0.mean()), rms=best_rms, n=len(rows),
                 em_a=em_a, em_b=em_b)


def estimate_rank(calc: Calc, top: float, value: float) -> tuple[int, float]:
    """Roughly where a predicted result would place: (rank, top percent); (0, 0.0) if unknown."""
    if calc.out_of <= 0 or calc.ranking <= 0:
        return (0, 0.0)
    if value >= top:
        rank = 1.0
    elif value >= calc.result:
        if top <= calc.result:
            rank = float(calc.ranking)
        else:
            frac = (value - calc.result) / (top - calc.result)
            rank = math.exp(math.log(calc.ranking) * (1 - frac))
    else:
        rank = calc.ranking + (calc.out_of - calc.ranking) * (calc.result - value) \
            / max(calc.result, 1e-9)
    rank = min(max(rank, 1.0), float(calc.out_of))
    return (int(round(rank)), rank / calc.out_of * 100)
