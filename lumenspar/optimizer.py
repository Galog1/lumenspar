"""Artifact optimizer: a simpler Genshin Optimizer.

Searches the scanned artifacts (.GOOD) for the best 4-piece set plus an
off-piece for one character, by a damage estimate, stat weights, target values
or a ratio. The character's own stats come from the build card (the Enka
showcase) minus its equipped artifacts and their static set bonuses, so any
other artifact build can be added back on top. Combat CRIT Rate is the panel
value plus the conditional bonuses, capped at 100%, so panel crit above the
cap scores nothing.

The search is exact. Pieces that are no better than another piece of the same
slot (and the same set group) in every stat the goal uses are dropped first,
which cannot remove the best build because every objective here never
decreases when a stat increases. Only when the remaining combinations still
exceed a limit are the weakest pieces trimmed.

Units: percent stats are in percent (46.6 means 46.6%), flat stats as they
are, stat keys are GOOD keys.
"""

from __future__ import annotations

import itertools
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

import numpy as np

from . import builds, passives

KEYS = ["hp", "hp_", "atk", "atk_", "def", "def_", "eleMas", "enerRech_", "critRate_",
        "critDMG_", "heal_", "physical_dmg_", "pyro_dmg_", "hydro_dmg_", "electro_dmg_",
        "cryo_dmg_", "anemo_dmg_", "geo_dmg_", "dendro_dmg_"]
IDX = {k: i for i, k in enumerate(KEYS)}
D = len(KEYS)

SLOTS = ["flower", "plume", "sands", "goblet", "circlet"]
# The trailing number of an artifact icon name (UI_RelicIcon_<set>_<n>) per slot.
SLOT_ICON = {"flower": 4, "plume": 2, "sands": 5, "goblet": 1, "circlet": 3}

MAIN_CHOICES = {
    "sands": ["atk_", "hp_", "def_", "eleMas", "enerRech_"],
    "goblet": ["atk_", "hp_", "def_", "eleMas", "physical_dmg_", "pyro_dmg_", "hydro_dmg_",
               "electro_dmg_", "cryo_dmg_", "anemo_dmg_", "geo_dmg_", "dendro_dmg_"],
    "circlet": ["atk_", "hp_", "def_", "eleMas", "critRate_", "critDMG_", "heal_"],
}
SUBSTATS = ["hp", "hp_", "atk", "atk_", "def", "def_", "eleMas", "enerRech_", "critRate_",
            "critDMG_"]

# Most combinations one enumeration may visit before the weakest pieces are trimmed.
LIMIT_ONE_SET = 1_500_000
LIMIT_ANY_SET = 250_000
_CHUNK_ROWS = 200_000

_GAMEDATA = Path(__file__).resolve().parent / "gamedata"
# Final-stat columns shown on a result card, in order.
_CARD_STATS = (("hp", "Max HP"), ("atk", "ATK"), ("def", "DEF"), ("eleMas", "Elemental Mastery"),
               ("critRate_", "CRIT Rate"), ("critDMG_", "CRIT DMG"),
               ("enerRech_", "Energy Recharge"))
_LABELS = {key: label for key, label in builds.STATS.values()}


@lru_cache(maxsize=None)
def _stats() -> dict:
    return json.loads((_GAMEDATA / "artifact_stats.json").read_text(encoding="utf-8"))


def unit(key: str) -> float:
    """One maximum substat roll of a stat (1.0 when it is not a substat)."""
    try:
        return float(_stats()["substat_rolls"]["5"][key][-1])
    except (KeyError, IndexError):
        return 1.0


@dataclass(frozen=True)
class Piece:
    id: int            # index in the .GOOD "artifacts" list
    set_key: str
    slot: str
    rarity: int
    level: int
    main_key: str
    main_value: float
    subs: tuple[tuple[str, float], ...]
    location: str
    vec: tuple[float, ...]   # length D: main + substats


@dataclass
class Base:
    hp: float
    atk: float
    defense: float     # base values (fightPropMap 1, 4, 7)
    vec: np.ndarray    # length D, every other bonus, artifact-free


@dataclass
class Goal:
    scaling: str = "atk"                       # "atk" | "hp" | "def" | "eleMas"
    # slot -> allowed main keys (sands/goblet/circlet); missing or empty = any
    mains: dict[str, list[str]] = field(default_factory=dict)
    set_key: str = ""                          # "" = try every set
    mode: str = "damage"                       # "damage" | "weights" | "targets" | "ratio"
    weights: dict[str, float] = field(default_factory=dict)
    targets: dict[str, float] = field(default_factory=dict)
    ratio: tuple[str, float, str, float] = ("critRate_", 1.0, "critDMG_", 2.0)
    minimums: dict[str, float] = field(default_factory=dict)
    extra_crit: float = 0.0     # conditional CRIT Rate the texts cannot tell (team, passives), percent
    use_equipped: bool = True   # allow pieces other characters wear
    min_level: int = 16
    top: int = 5


@dataclass
class Result:
    pieces: list[Piece]        # SLOTS order
    set_key: str
    stats: dict[str, float]    # final values (see final_stats)
    damage: float
    score: float               # the mode's primary number (see evaluate)
    cond_crit: float


def main_value(rarity: int, level: int, key: str) -> float:
    """A main stat's value at an artifact level (0.0 if unknown)."""
    try:
        return float(_stats()["main_stats"][str(rarity)][key][level])
    except (KeyError, IndexError, TypeError):
        return 0.0


def load_pieces(good: dict) -> list[Piece]:
    """Every artifact of a .GOOD export as a Piece with its stat vector."""
    out = []
    for i, a in enumerate(good.get("artifacts", [])):
        slot = a.get("slotKey")
        if slot not in SLOTS:
            continue
        rarity, level = int(a.get("rarity") or 0), int(a.get("level") or 0)
        main_key = a.get("mainStatKey", "")
        main = main_value(rarity, level, main_key)
        vec = np.zeros(D)
        if main_key in IDX:
            vec[IDX[main_key]] += main
        subs = []
        for s in a.get("substats") or []:
            key, value = s.get("key", ""), float(s.get("value") or 0)
            if key in IDX:
                vec[IDX[key]] += value
                subs.append((key, value))
        out.append(Piece(i, a.get("setKey", ""), slot, rarity, level, main_key, main,
                         tuple(subs), a.get("location") or "", tuple(float(x) for x in vec)))
    return out


def _equipped_vec(card: dict) -> np.ndarray:
    """Stats from the card's equipped artifacts (mains and substats) plus the
    static 2-piece bonuses of every equipped set with at least two pieces."""
    vec = np.zeros(D)
    for art in card.get("artifacts") or []:
        main = art.get("main") or {}
        if main.get("key") in IDX:
            vec[IDX[main["key"]]] += float(main.get("value") or 0)
        for s in art.get("subs") or []:
            if s.get("key") in IDX:
                vec[IDX[s["key"]]] += float(s.get("value") or 0)
    counts = Counter(a.get("setKey") for a in card.get("artifacts") or [] if a.get("setKey"))
    for set_key, n in counts.items():
        if n >= 2:
            for key, value in passives.set_static_2pc(set_key).items():
                vec[IDX[key]] += value
    return vec


def base_from_card(card: dict) -> Base:
    """The character without artifacts: panel stats minus equipped artifacts and set bonuses."""
    f = card.get("fight")
    if not f:
        raise ValueError("this build card has no raw stats; fetch the showcase again")

    def g(k: str) -> float:
        return float(f.get(k, 0))

    vec = np.zeros(D)
    for key, fid, scale in (
            ("hp", "2", 1), ("hp_", "3", 100), ("atk", "5", 1), ("atk_", "6", 100),
            ("def", "8", 1), ("def_", "9", 100), ("critRate_", "20", 100),
            ("critDMG_", "22", 100), ("enerRech_", "23", 100), ("eleMas", "28", 1),
            ("heal_", "26", 100), ("physical_dmg_", "30", 100), ("pyro_dmg_", "40", 100),
            ("electro_dmg_", "41", 100), ("hydro_dmg_", "42", 100), ("dendro_dmg_", "43", 100),
            ("anemo_dmg_", "44", 100), ("geo_dmg_", "45", 100), ("cryo_dmg_", "46", 100)):
        vec[IDX[key]] = g(fid) * scale
    vec -= _equipped_vec(card)
    return Base(g("1"), g("4"), g("7"), vec)


def final_stats(base: Base, total: np.ndarray) -> np.ndarray:
    """total (N, D) = base + artifacts + set bonus -> copy with final HP/ATK/DEF totals."""
    out = np.array(total, dtype=float, copy=True)
    for flat, pct, basic in (("hp", "hp_", base.hp), ("atk", "atk_", base.atk),
                             ("def", "def_", base.defense)):
        out[:, IDX[flat]] = basic * (1 + total[:, IDX[pct]] / 100) + total[:, IDX[flat]]
    return out


def _dmg_key(element: str) -> str:
    key = f"{element.lower()}_dmg_"
    return key if key in IDX else "physical_dmg_"


def evaluate(final: np.ndarray, goal: Goal, element: str,
             cond_crit: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(sort_keys, score, damage) for final stats (N, D).

    sort_keys has shape (rows, N); row 0 is the most significant and higher is
    better in every row. score is the mode's primary number (targets: the
    worst shortfall, lower is better).
    """
    c = final
    panel = c[:, IDX["critRate_"]]
    cr = np.minimum(panel + cond_crit, 100.0)
    cd = c[:, IDX["critDMG_"]]
    scale = c[:, IDX[goal.scaling]]
    dmg_bonus = c[:, IDX[_dmg_key(element)]]
    damage = scale * (1 + cr / 100 * cd / 100) * (1 + dmg_bonus / 100)

    def v(k: str) -> np.ndarray:
        # Useful panel CRIT Rate only counts up to the cap.
        if k == "critRate_":
            return np.minimum(panel, max(0.0, 100.0 - cond_crit))
        return c[:, IDX[k]]

    if goal.mode == "weights":
        score = np.zeros(len(c))
        for k, w in goal.weights.items():
            score += w * v(k) / unit(k)
        return np.array([score, damage]), score, damage
    if goal.mode == "targets":
        shorts = [np.maximum(0.0, t - v(k)) / t for k, t in goal.targets.items() if t > 0]
        if shorts:
            worst, total = np.max(shorts, axis=0), np.sum(shorts, axis=0)
        else:
            worst = total = np.zeros(len(c))
        return np.array([-np.round(worst, 3), -np.round(total, 3), damage]), worst, damage
    if goal.mode == "ratio":
        a_key, a, b_key, b = goal.ratio
        x = cr if a_key == "critRate_" else c[:, IDX[a_key]]
        y = cr if b_key == "critRate_" else c[:, IDX[b_key]]
        balanced = np.minimum(x / max(a, 1e-9), y / max(b, 1e-9))
        return np.array([np.round(balanced, 2), damage]), balanced, damage
    return damage[None, :], damage, damage


def relevant(goal: Goal, element: str) -> list[int]:
    """Stat columns the goal can use (a piece worse in all of them is useless)."""
    keys = {"atk": ["atk", "atk_"], "hp": ["hp", "hp_"], "def": ["def", "def_"],
            "eleMas": ["eleMas"]}.get(goal.scaling, [goal.scaling])
    keys += ["critRate_", "critDMG_", _dmg_key(element)]
    keys += list(goal.weights) + list(goal.targets) + list(goal.minimums)
    keys += [goal.ratio[0], goal.ratio[2]]
    for flat, pct in (("hp", "hp_"), ("atk", "atk_"), ("def", "def_")):
        if flat in keys or pct in keys:
            keys += [flat, pct]
    return [IDX[k] for k in dict.fromkeys(keys) if k in IDX]


def pareto(pieces: list[Piece], cols: list[int]) -> list[Piece]:
    """Drop pieces that another piece matches or beats in every column."""
    if len(pieces) < 2:
        return list(pieces)
    m = np.array([[p.vec[c] for c in cols] for p in pieces])
    keep = []
    for i in range(len(pieces)):
        ge = (m >= m[i]).all(axis=1)
        gt = (m > m[i]).any(axis=1)
        same = ge & ~gt                  # equal in every column
        same[i] = False
        if (ge & gt).any() or same[:i].any():
            continue
        keep.append(pieces[i])
    return keep


def _top_k(pieces: list[Piece], cols: list[int], k: int) -> list[Piece]:
    """The k pieces with the most useful stats, in max-roll units."""
    def worth(p: Piece) -> float:
        return sum(p.vec[c] / unit(KEYS[c]) for c in cols)
    return sorted(pieces, key=worth, reverse=True)[:k]


def _main_ok(p: Piece, goal: Goal) -> bool:
    allowed = goal.mains.get(p.slot)
    return not allowed or p.main_key in allowed


def _enumerate(lists: list[list[Piece]], base: Base, bonus: np.ndarray, goal: Goal,
               element: str, cond: float, should_stop: Callable[[], bool]
               ) -> tuple[list[tuple], bool]:
    """Best builds of one choice of five candidate lists; (candidates, stopped)."""
    arrs = [np.array([p.vec for p in lst]) for lst in lists]
    # The longest lists are looped over, the shortest are vectorised.
    order = sorted(range(5), key=lambda i: -len(lists[i]))
    m = 1
    while m < 5 and math.prod(len(lists[i]) for i in order[5 - m - 1:]) <= _CHUNK_ROWS:
        m += 1
    lead, trail = order[:5 - m], order[5 - m:]
    grid = np.indices([len(lists[i]) for i in trail]).reshape(m, -1)
    q = sum(arrs[i][grid[t]] for t, i in enumerate(trail))
    start = base.vec + bonus
    found: list[tuple] = []
    for combo in itertools.product(*[range(len(lists[i])) for i in lead]):
        if should_stop():
            return found, True
        row = start + sum((arrs[i][j] for i, j in zip(lead, combo)), np.zeros(D))
        final = final_stats(base, row + q)
        mask = np.ones(len(final), dtype=bool)
        for k, val in goal.minimums.items():
            mask &= final[:, IDX[k]] >= val
        if not mask.any():
            continue
        rows = np.flatnonzero(mask)
        keys, _, _ = evaluate(final[rows], goal, element, cond)
        best = np.lexsort(keys[::-1])[::-1][:goal.top]
        for j in best:
            chosen = dict(zip(lead, combo))
            for t, i in enumerate(trail):
                chosen[i] = int(grid[t][rows[j]])
            pieces = tuple(lists[i][chosen[i]] for i in range(5))
            found.append((tuple(float(x) for x in keys[:, j]), pieces))
        found = _best(found, goal.top)
    return found, False


def _best(found: list[tuple], top: int) -> list[tuple]:
    """The best `top` candidates, best first, without repeated piece sets."""
    seen, out = set(), []
    for item in sorted(found, key=lambda x: x[0], reverse=True):
        ids = tuple(p.id for p in item[1])
        if ids in seen:
            continue
        seen.add(ids)
        out.append(item)
        if len(out) == top:
            break
    return out


def _set_candidates(by_slot: dict[str, list[Piece]], set_key: str, off: str | None,
                    cols: list[int], limit: int) -> list[list[Piece]] | None:
    """Five candidate lists for one enumeration (None when a slot has no piece)."""
    lists = []
    for slot in SLOTS:
        mine = [p for p in by_slot.get(slot, []) if (p.set_key == set_key) != (slot == off)]
        if not mine:
            return None
        lists.append(pareto(mine, cols))
    if math.prod(len(x) for x in lists) > limit:
        k = max(2, int(limit ** (1 / 5)))
        lists = [_top_k(x, cols, k) if len(x) > k else x for x in lists]
    return lists


def bonus_for(set_key: str) -> np.ndarray:
    """The always-on 2-piece stats of a set as a stat vector."""
    vec = np.zeros(D)
    for key, value in passives.set_static_2pc(set_key).items():
        vec[IDX[key]] += value
    return vec


def search(pieces: list[Piece], base: Base, element: str, goal: Goal,
           cond_crit_for: Callable[[str], float], owner: str = "",
           should_stop: Callable[[], bool] = lambda: False) -> list[Result]:
    """The best builds for the goal, best first."""
    pool = [p for p in pieces if p.rarity == 5 and p.level >= goal.min_level
            and _main_ok(p, goal) and (goal.use_equipped or p.location in ("", owner))]
    cols = relevant(goal, element)
    by_slot: dict[str, list[Piece]] = {s: [] for s in SLOTS}
    for p in pool:
        by_slot[p.slot].append(p)
    if goal.set_key:
        sets = [goal.set_key]
    else:
        slots_of: dict[str, set] = {}
        for p in pool:
            slots_of.setdefault(p.set_key, set()).add(p.slot)
        sets = [s for s, slots in slots_of.items() if len(slots) >= 4]
    limit = LIMIT_ONE_SET if goal.set_key else LIMIT_ANY_SET

    best: list[tuple] = []     # (keys, pieces, set_key, cond)
    for set_key in sets:
        cond = cond_crit_for(set_key) + goal.extra_crit
        bonus = bonus_for(set_key)
        found: list[tuple] = []
        stopped = False
        for off in [None] + SLOTS:
            lists = _set_candidates(by_slot, set_key, off, cols, limit)
            if lists is None:
                continue
            got, stopped = _enumerate(lists, base, bonus, goal, element, cond, should_stop)
            found += got
            if stopped:
                break
        best = _best(best + [(k, p, set_key, cond) for k, p in found], goal.top)
        if stopped:
            break
    return [_result(item[1], item[2], item[3], base, bonus_for(item[2]), goal, element)
            for item in best]


def _result(pieces: tuple[Piece, ...], set_key: str, cond: float, base: Base,
            bonus: np.ndarray, goal: Goal, element: str) -> Result:
    total = base.vec + bonus + sum((np.array(p.vec) for p in pieces), np.zeros(D))
    final = final_stats(base, total[None, :])
    _, score, damage = evaluate(final, goal, element, cond)
    stats = {k: float(final[0, IDX[k]]) for k in KEYS}
    return Result(list(pieces), set_key, stats, float(damage[0]), float(score[0]), cond)


def current(card: dict, base: Base, element: str, goal: Goal, cond: float) -> Result:
    """The card's equipped build, scored the same way as the search results."""
    total = base.vec + _equipped_vec(card)
    final = final_stats(base, total[None, :])
    _, score, damage = evaluate(final, goal, element, cond)
    counts = Counter(a.get("setKey") for a in card.get("artifacts") or [] if a.get("setKey"))
    set_key = counts.most_common(1)[0][0] if counts else ""
    stats = {k: float(final[0, IDX[k]]) for k in KEYS}
    return Result([], set_key, stats, float(damage[0]), float(score[0]), cond)


def _roll_count(rarity: int, key: str, value: float) -> int:
    try:
        top = float(_stats()["substat_rolls"][str(rarity)][key][-1])
    except (KeyError, IndexError):
        return 0
    return max(1, math.ceil(value / top - 1e-6))


def _card_artifact(p: Piece) -> dict:
    info = builds._items("artifact_sets.json", "key").get(p.set_key, {})
    set_id = str(info.get("id") or "")
    subs = [{"key": k, "label": _LABELS.get(k, k), "value": v, "text": builds.fmt(k, v),
             "rolls": _roll_count(p.rarity, k, v)} for k, v in p.subs]
    crit = sum(2 * s["value"] for s in subs if s["key"] == "critRate_") + \
        sum(s["value"] for s in subs if s["key"] == "critDMG_")
    return {
        "slot": p.slot, "setKey": p.set_key, "setName": info.get("name", p.set_key),
        "setId": set_id, "rarity": p.rarity, "level": p.level,
        "icon": f"UI_RelicIcon_{set_id}_{SLOT_ICON[p.slot]}" if set_id else "",
        "main": {"key": p.main_key, "label": _LABELS.get(p.main_key, p.main_key),
                 "value": p.main_value, "text": builds.fmt(p.main_key, p.main_value)},
        "subs": subs, "critValue": round(crit, 1), "owner": p.location,
    }


def result_card(result: Result, card: dict) -> dict:
    """A build card showing the result's artifacts and stats, for the existing UI."""
    out = dict(card)
    arts = [_card_artifact(p) for p in result.pieces]
    # "from <character>" only for pieces someone else wears, by display name
    # (a .GOOD location is a key such as "YaeMiko").
    names = builds._items("characters.json", "key")
    for a in arts:
        loc = a["owner"]
        a["owner"] = "" if loc == card.get("key") else names.get(loc, {}).get("name", loc)
    out["artifacts"] = arts
    stats = [{"key": k, "label": label, "text": builds.fmt(k, result.stats[k])}
             for k, label in _CARD_STATS]
    if result.stats["heal_"] > 0:
        stats.append({"key": "heal_", "label": "Healing Bonus",
                      "text": builds.fmt("heal_", result.stats["heal_"])})
    dmg = max((k for k in KEYS if k.endswith("_dmg_")), key=lambda k: result.stats[k])
    if result.stats[dmg] > 0:
        stats.append({"key": dmg, "label": _LABELS[dmg], "text": builds.fmt(dmg, result.stats[dmg])})
    out["stats"] = stats
    out["critValue"] = round(sum(a["critValue"] for a in arts), 1)
    sets = []
    counts = Counter(p.set_key for p in result.pieces)
    for key, n in counts.most_common():
        if n >= 2:
            name = next((a["setName"] for a in arts if a["setKey"] == key), key)
            sets.append({"name": name, "count": n,
                         "bonuses": list(passives.set_bonuses(key)[:2 if n >= 4 else 1])})
    out["sets"] = sets
    return out
