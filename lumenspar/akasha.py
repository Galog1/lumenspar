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
from dataclasses import asdict, dataclass, field
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


@lru_cache(maxsize=None)
def _set_keys() -> dict[str, str]:
    """Artifact set name -> our set key."""
    try:
        items = json.loads((_GAMEDATA / "artifact_sets.json").read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError):
        return {}
    return {i["name"]: i["key"] for i in items if "key" in i and "name" in i}


@dataclass
class Row:
    """A leaderboard build, anonymous: our stats, its 4-piece set key and Akasha's result."""
    stats: dict[str, float]
    set4: str
    result: float


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
    return Row(stats=stats, set4=set4, result=float(r["calculation"]["result"]))


def sample(calc: Calc, fetch: Callable[[str], bytes] | None = None, root: Path = CACHE_DIR,
           now: Callable[[], float] = time.time,
           sleep: Callable[[float], None] = time.sleep) -> tuple[list[Row], float]:
    """A spread of leaderboard builds around the player's result: (rows, top result)."""
    path = root / f"board-{calc.calculation_id}-{calc.variant or 'none'}.json"
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
    for i, cursor in enumerate(cursors):
        if i:
            sleep(PAUSE)
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
