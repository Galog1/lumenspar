#!/usr/bin/env python3
"""Fill the missing characters of gamedata/rv_stats.json from Akasha.cv.

    python3 tools/update_rv_stats.py [--dry-run] [--only-collected]

Characters already in the table (hand-written seeds or earlier runs) are never
touched. For each missing one the average stats of the best builds on its first
Akasha leaderboard decide what Roll Value counts (anonymous rows only; names
and UIDs are never read or stored):

* start from the generic rule (builds.counted_stats) fed with the most common
  sands/goblet/circlet mains of those builds;
* add Elemental Mastery when the average EM is at least 80;
* add Energy Recharge when the average ER is at least 125%;
* swap ATK% for HP% when average max HP >= 30000, or for DEF% when average DEF
  >= 1500, in both cases only while average ATK stays under 1600.

Entries are written as {"stats": [...], "auto": true} so humans can tell them
from hand-written ones. Requests honour akasha.PAUSE and the module's cache.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lumenspar import akasha, builds, enka  # noqa: E402

TABLE = ROOT / "lumenspar" / "gamedata" / "rv_stats.json"
EM_MIN, ER_MIN, HP_MIN, DEF_MIN, ATK_MAX = 80.0, 125.0, 30000.0, 1500.0, 1600.0
TOP_ROWS = 20           # the best rows of a leaderboard sample that get averaged


def derive(avg: dict[str, float], mains: dict[str, str] | None = None) -> list[str]:
    """The counted stats for a character from its top builds' average stats and
    their usual sands/goblet/circlet mains ({slot: key}; none known = crit + ATK%)."""
    arts = [{"slot": slot, "main": {"key": key}} for slot, key in (mains or {}).items()]
    stats = builds.counted_stats(arts)
    if avg.get("eleMas", 0) >= EM_MIN and "eleMas" not in stats:
        stats.append("eleMas")
    if avg.get("enerRech_", 0) >= ER_MIN and "enerRech_" not in stats:
        stats.append("enerRech_")
    if avg.get("atk", 0) < ATK_MAX and "atk_" in stats:
        scaler = "hp_" if avg.get("hp", 0) >= HP_MIN else \
            "def_" if avg.get("def", 0) >= DEF_MIN else ""
        if scaler:
            stats[stats.index("atk_")] = scaler
    return stats


def _avatar_ids() -> dict[str, str]:
    """Character key -> Akasha/Enka character id (travelers left out)."""
    out: dict[str, str] = {}
    for aid, entry in enka._avatar_map().items():
        key = entry["key"]
        if not key.startswith("Traveler"):
            out.setdefault(key, aid.split("-")[0])
    return out


def fetch_stats(avatar_id: str) -> tuple[dict[str, float], dict[str, str]] | None:
    """(average stats, usual mains) of a character's best builds, None without a board."""
    all_boards = akasha.boards(avatar_id)
    if not all_boards:
        return None
    time.sleep(akasha.PAUSE)
    board = all_boards[0]
    calc = akasha.calc_for_board(board, board.default_variant, [])
    rows, _ = akasha.sample(calc)
    best = sorted(rows, key=lambda r: r.result, reverse=True)[:TOP_ROWS]
    avg = {k: sum(r.stats[k] for r in best if k in r.stats) / max(1, sum(
        1 for r in best if k in r.stats)) for k in {k for r in best for k in r.stats}}
    _, mains = akasha.common(rows)
    return avg, {slot: opts[0][0] for slot, opts in mains.items() if opts}


def collected_keys() -> set[str]:
    keys: set[str] = set()
    for path in (builds.BUILD_DIR.glob("*.json") if builds.BUILD_DIR.is_dir() else []):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        keys |= {b.get("key", "") for b in (data.get("builds") or {}).values()}
    return keys - {""}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the additions, write nothing")
    ap.add_argument("--only-collected", action="store_true",
                    help="only characters in the local build cards")
    args = ap.parse_args()
    data = json.loads(TABLE.read_text(encoding="utf-8"))
    table = data["characters"]
    ids = _avatar_ids()
    wanted = sorted(k for k in ids if k not in table)
    if args.only_collected:
        have = collected_keys()
        wanted = [k for k in wanted if k in have]
    added = 0
    for n, key in enumerate(wanted):
        if n:
            time.sleep(akasha.PAUSE)
        try:
            got = fetch_stats(ids[key])
        except akasha.AkashaError as exc:
            print(f"{key}: skipped ({exc})")
            if "reach" in str(exc).lower():
                print("Akasha.cv is unreachable; stopping.")
                break
            continue
        if got is None:
            print(f"{key}: no leaderboard")
            continue
        stats = derive(*got)
        print(f"{key}: {', '.join(stats)}")
        table[key] = {"stats": stats, "auto": True}
        added += 1
    if added and not args.dry_run:
        data["characters"] = dict(sorted(table.items()))
        TABLE.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{added} added" + (" (dry run, nothing written)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
