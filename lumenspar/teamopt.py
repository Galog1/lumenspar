"""Pure helpers for the "Team damage" optimizer mode (no Qt calls).

The search itself runs in the bundled Genshin Optimizer engine (damage.py,
function "optimize"): these helpers turn Lumenspar's pieces, minimums and hits
into its request. Stats there are in engine units: percent stats are fractions
and Energy Recharge is the total, base 100% included.
"""

from __future__ import annotations

from collections import Counter

from . import damage, optimizer
from .optimizer import D, IDX, SLOTS, Piece


def _add(stats: dict, key: str, value: float) -> None:
    stats[key] = stats.get(key, 0.0) + damage._frac(key, value)


def candidate(p: Piece) -> dict:
    """An engine candidate: id, the set (count 1) and the summed main and substats."""
    out: dict = {"id": p.id, p.set_key: 1}
    _add(out, p.main_key, p.main_value)
    for key, value in p.subs:
        _add(out, key, value)
    return out


def card_candidates(card: dict) -> list[dict]:
    """Candidates for a build card's equipped artifacts in SLOTS order (ids "cur0"...)."""
    arts = sorted((a for a in card.get("artifacts") or [] if a.get("slot") in SLOTS),
                  key=lambda a: SLOTS.index(a["slot"]))
    out = []
    for n, a in enumerate(arts):
        cand: dict = {"id": f"cur{n}", a["setKey"]: 1}
        main = a.get("main") or {}
        _add(cand, main.get("key", ""), float(main.get("value") or 0))
        for s in a.get("subs") or []:
            _add(cand, s["key"], float(s.get("value") or 0))
        out.append(cand)
    return out


def card_pieces(card: dict) -> list[Piece]:
    """The card's equipped artifacts as Pieces (ids -1 … -5), owned by its character.

    The showcase build is certainly the player's, but an older inventory scan
    may lack some of it; searching these as well keeps the current build
    reachable, so no suggestion can be worse than what the character wears.
    """
    out = []
    for i, a in enumerate(card.get("artifacts") or []):
        vec = [0.0] * D
        main_key, main_value = a["main"]["key"], float(a["main"]["value"])
        subs = tuple((s["key"], float(s["value"])) for s in a.get("subs") or [] if s.get("key"))
        for k, v in ((main_key, main_value), *subs):
            if k in IDX:
                vec[IDX[k]] += v
        out.append(Piece(id=-1 - i, set_key=a.get("setKey", ""), slot=a["slot"],
                         rarity=int(a.get("rarity") or 5), level=int(a.get("level") or 0),
                         main_key=main_key, main_value=main_value, subs=subs,
                         location=card.get("key", ""), vec=tuple(vec)))
    return out


def with_card_pieces(pieces: list[Piece], card: dict) -> list[Piece]:
    """Scan pieces plus the card's own, dropping scan copies of the card's pieces."""
    own = card_pieces(card)
    def sig(p: Piece) -> tuple:
        return (p.slot, p.set_key, p.main_key,
                tuple(sorted((k, round(v, 1)) for k, v in p.subs)))
    mine = {sig(p) for p in own}
    return [p for p in pieces if sig(p) not in mine] + own


def engine_minimums(minimums: dict[str, float]) -> list[dict]:
    """The optimizer's percent-unit minimums as engine final-stat minimums."""
    return [{"key": key, "value": value / 100 if key.endswith("_") else value}
            for key, value in minimums.items()]


def _usable(pieces: list[Piece], mains: dict[str, list[str]], min_level: int,
            use_equipped: bool, owner: str) -> list[Piece]:
    out = []
    for p in pieces:
        allowed = mains.get(p.slot)
        if (p.rarity == 5 and p.level >= min_level and (not allowed or p.main_key in allowed)
                and (use_equipped or p.location in ("", owner))):
            out.append(p)
    return out


def families(pieces: list[Piece], set_keys: list[str], mains: dict[str, list[str]],
             min_level: int, use_equipped: bool, owner: str) -> list[list[list[dict]]]:
    """Engine families: per set, all five pieces from it, then each slot in turn
    taking pieces of any other set. Families with an empty slot are left out."""
    pool = _usable(pieces, mains, min_level, use_equipped, owner)
    out = []
    for set_key in set_keys:
        for off in [None] + SLOTS:
            family = []
            for slot in SLOTS:
                family.append([candidate(p) for p in pool
                               if p.slot == slot and (p.set_key == set_key) != (slot == off)])
            if all(family):
                out.append(family)
    return out


def sets_with_four(pieces: list[Piece], mains: dict[str, list[str]], min_level: int,
                   use_equipped: bool, owner: str) -> list[str]:
    """Sets with usable pieces in at least four slots, the most pieces first."""
    pool = _usable(pieces, mains, min_level, use_equipped, owner)
    slots_of: dict[str, set] = {}
    for p in pool:
        slots_of.setdefault(p.set_key, set()).add(p.slot)
    counts = Counter(p.set_key for p in pool)
    return sorted((k for k, slots in slots_of.items() if len(slots) >= 4),
                  key=lambda k: (-counts[k], k))


def frames(target: str, formulas: list[dict]) -> list[dict]:
    """The engine's target: one hit, by its formula id."""
    if not any(f["id"] == target for f in formulas):
        raise ValueError("That hit isn't listed. Open Team & damage and select the character "
                         "once to list their hits.")
    return [{"id": target, "multiplier": 1}]
