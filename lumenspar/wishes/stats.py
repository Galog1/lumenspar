"""Pity, guarantees and 50/50 results from a stored wish history.

Follows paimon.moe's counter: per banner, how many wishes since the last 5★
and 4★, whether the next 5★ is guaranteed to be a featured one, and each
5★ with the pity it came at and whether it won or lost the 50/50.

Won or lost needs to know what was featured when the wish was made, which
comes from paimon.moe's banner schedule (gamedata/wish_banners.json, rebuilt
by tools/update_gamedata.py). Wish times are the server's local time while the
schedule is written in Asia time, and the servers are up to 13 hours apart --
so instead of converting, a 5★ counts as featured if *any* banner within 14
hours of the wish featured it. An event banner only ever gives its own
featured 5★ or a standard one, so the wider window can only misread a loss as
a win for a standard-pool 5★ that was itself featured within those 14 hours --
which has only happened around the debut banners of characters that later
joined the standard pool (Tighnari, Dehya).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

SCHEDULE_PATH = Path(__file__).resolve().parent.parent / "gamedata" / "wish_banners.json"
PRIMOGEMS_PER_WISH = 160
SLACK = timedelta(hours=14)
_TIME = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True, slots=True)
class BannerRules:
    label: str
    hard_pity: int           # 5★ guaranteed by this many wishes
    schedule: str | None     # schedule section for 50/50, or None if it has none


RULES = {
    "character": BannerRules("Character Event", 90, "characters"),
    "weapon": BannerRules("Weapon Event", 80, "weapons"),
    "standard": BannerRules("Standard", 90, None),
    # Chronicled Wish has a picked target rather than a 50/50 in the usual
    # sense, so only its pity is tracked.
    "chronicled": BannerRules("Chronicled", 90, None),
    "beginner": BannerRules("Beginners'", 90, None),
}
ORDER = ("character", "weapon", "standard", "chronicled", "beginner")


def item_id(name: str) -> str:
    """'Lion's Roar' -> 'lions_roar', the form of paimon.moe's item ids."""
    s = name.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _canon(paimon_id: str) -> str:
    # paimon.moe spells one weapon both 'primordial_jade_winged-spear' and
    # 'primordial_jade_winged_spear'; item_id turns hyphens into underscores,
    # so schedule ids do the same.
    return paimon_id.replace("-", "_")


@lru_cache(maxsize=None)
def _schedule(path: str) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for section in ("characters", "weapons"):
        out[section] = [(datetime.strptime(b["start"], _TIME) - SLACK,
                         datetime.strptime(b["end"], _TIME) + SLACK,
                         frozenset(_canon(i) for i in b.get("featured", [])))
                        for b in raw.get(section, [])]
    return out


def featured_at(section: str, when: str) -> frozenset[str] | None:
    """Featured 5★ ids around `when`, or None if the schedule does not cover it."""
    t = datetime.strptime(when, _TIME)
    hits = [f for start, end, f in _schedule(str(SCHEDULE_PATH)).get(section, []) if start <= t <= end]
    return frozenset().union(*hits) if hits else None


def win_rate(won: int, lost: int) -> float | None:
    """Percent of decided 50/50s that were won (one decimal), or None when none were decided."""
    return round(100 * won / (won + lost), 1) if won + lost else None


def fifty_fifty(banners: list[dict]) -> dict:
    """The 50/50 record across every banner that has one: won, lost and the win rate."""
    won = sum(b["won"] for b in banners if b["hasFiftyFifty"])
    lost = sum(b["lost"] for b in banners if b["hasFiftyFifty"])
    return {"won": won, "lost": lost, "winRate": win_rate(won, lost)}


def banner_stats(key: str, wishes: list[dict]) -> dict:
    """Everything the counter shows for one banner. `wishes` oldest first."""
    rules = RULES[key]
    pity5 = pity4 = 0
    guaranteed: bool | None = False if rules.schedule else None
    fives: list[dict] = []
    won = lost = fours = 0
    unknown = False
    for w in wishes:
        pity5 += 1
        pity4 += 1
        rank = w.get("rank_type")
        if rank == "4":
            fours += 1
            pity4 = 0
        elif rank == "5":
            entry = {"name": w["name"], "time": w["time"], "pity": pity5, "result": ""}
            if rules.schedule:
                featured = featured_at(rules.schedule, w["time"])
                if featured is None:
                    entry["result"] = "unknown"
                    unknown = True
                elif item_id(w["name"]) in featured:
                    entry["result"] = "guaranteed" if guaranteed else "won"
                    won += 0 if guaranteed else 1
                    guaranteed = False
                else:
                    entry["result"] = "lost"
                    lost += 1
                    guaranteed = True
            fives.append(entry)
            pity5 = 0
    total = len(wishes)
    pities = [f["pity"] for f in fives]
    return {
        "key": key,
        "label": rules.label,
        "total": total,
        "primogems": total * PRIMOGEMS_PER_WISH,
        "pity5": pity5,
        "hardPity": rules.hard_pity,
        "pity4": pity4,
        "fiveCount": len(fives),
        "fourCount": fours,
        "averagePity": round(sum(pities) / len(pities), 1) if pities else 0,
        "hasFiftyFifty": bool(rules.schedule),
        "guaranteed": bool(guaranteed),
        "won": won,
        "lost": lost,
        "winRate": win_rate(won, lost),
        # A 5★ newer than the bundled schedule: its result, and so the
        # guarantee, cannot be known until the game data is updated.
        "scheduleStale": unknown,
        "fives": fives[::-1],                     # newest first
    }


def all_stats(wishes: dict[str, list[dict]]) -> list[dict]:
    return [banner_stats(k, wishes.get(k, [])) for k in ORDER if wishes.get(k)]
