"""Import characters from an Enka.Network profile showcase.

Reading a character off the screen is the hardest thing Lumenspar does: the
background art drifts behind the numbers, some names are chosen by the player,
and constellation bonuses have to be stripped from talent levels. Enka.Network
reports the same data straight from the game's profile showcase -- level,
ascension, constellation and *base* talent levels -- for whichever characters
the player has put in it. Rotating the showcase and fetching again collects
the rest, so the roster here accumulates across fetches.

Only the showcase is read: no login, nothing beyond what the profile already
publishes. Enka asks clients to identify themselves and to respect each
response's `ttl` (how long it will keep serving cached data), both done here.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR
from .good import Character

API = "https://enka.network/api/uid/{uid}/"
USER_AGENT = "Lumenspar (+https://github.com/Galog1/lumenspar)"
MAP_PATH = Path(__file__).resolve().parent / "gamedata" / "enka.json"
ROSTER_PATH = DATA_DIR / "enka_roster.json"

# Used when a response carries no ttl, and as the floor for repeated fetches:
# asking again sooner only returns the same cached showcase.
DEFAULT_TTL = 60

# Manekins take whatever element the player gives them, and their talents
# change with it; Enka's tables do not cover those, so they cannot be mapped.
MANEKIN_IDS = {10000117: "Manekin", 10000118: "Manekina"}

_STATUS = {
    400: "that UID is not in a valid format",
    404: "no player with that UID exists",
    424: "the game is under maintenance or just updated -- try again later",
    429: "Enka is rate-limiting requests -- wait a minute and try again",
    500: "Enka.Network had a server error -- try again later",
    503: "Enka.Network is down -- try again later",
}


class EnkaError(Exception):
    """A fetch that produced no usable showcase, with a message for the user."""


@lru_cache(maxsize=None)
def _avatar_map() -> dict[str, dict]:
    return json.loads(MAP_PATH.read_text())["avatars"]


def fetch(uid: str, timeout: float = 20.0) -> tuple[dict, int]:
    """Return (response, ttl seconds) for a UID's showcase."""
    uid = uid.strip()
    if not uid.isdigit():
        raise EnkaError("enter your UID (the number in the bottom-right corner in-game)")
    req = urllib.request.Request(API.format(uid=uid), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise EnkaError(f"Enka.Network: {_STATUS.get(exc.code, f'HTTP {exc.code}')}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EnkaError(f"could not reach Enka.Network ({exc})") from exc
    return data, int(data.get("ttl") or DEFAULT_TTL)


def parse(data: dict) -> tuple[list[Character], list[str]]:
    """Turn a showcase response into GOOD characters, plus any it could not map."""
    avatars = data.get("avatarInfoList")
    if not avatars:
        return [], ["the showcase is empty, or \"Show Character Details\" is turned "
                    "off in your in-game profile"]
    table = _avatar_map()
    chars: list[Character] = []
    problems: list[str] = []
    for a in avatars:
        aid = a.get("avatarId")
        entry = table.get(f"{aid}-{a.get('skillDepotId')}") or table.get(str(aid))
        if entry is None:
            if aid in MANEKIN_IDS:
                problems.append(f"{MANEKIN_IDS[aid]}: Enka.Network publishes no talent "
                                f"data for Manekins, so it cannot be imported this way")
            else:
                problems.append(f"character id {aid} is not in Lumenspar's Enka table "
                                f"(newer than this copy -- run tools/update_gamedata.py)")
            continue
        props = a.get("propMap") or {}
        levels = a.get("skillLevelMap") or {}
        if any(entry[slot] not in levels for slot in ("auto", "skill", "burst")):
            if aid in MANEKIN_IDS:
                problems.append(f"{MANEKIN_IDS[aid]}: its talents depend on the element "
                                f"you gave it, which Enka.Network's tables do not cover")
            else:
                problems.append(f"{entry['key']}: the showcase lists talents Lumenspar's "
                                f"Enka table does not know (run tools/update_gamedata.py)")
            continue
        try:
            level = int(props["4001"]["ival"])
            ascension = int(props["1002"]["ival"]) if "1002" in props else 0
            # skillLevelMap holds the levels the player has invested; the +3
            # constellation bonuses live in a separate map, so these are
            # already the base levels GOOD expects.
            talent = {slot: int(levels[entry[slot]]) for slot in ("auto", "skill", "burst")}
        except (KeyError, TypeError, ValueError):
            problems.append(f"{entry['key']}: the showcase entry is missing level or talent data")
            continue
        chars.append(Character(
            key=entry["key"], level=level, ascension=ascension,
            constellation=len(a.get("talentIdList") or []), talent=talent,
        ))
    return chars, problems


class Roster:
    """Characters collected across showcase fetches, persisted between runs.

    Rotating the showcase means each fetch sees only some characters, so the
    roster keeps every character it has seen, newest reading winning. It is
    tied to one UID: switching accounts starts a fresh roster rather than
    mixing two players' characters into one export.
    """

    def __init__(self, path: Path = ROSTER_PATH) -> None:
        self.path = path
        self.uid = ""
        self.characters: dict[str, dict] = {}
        self.next_fetch = 0.0          # wall-clock time Enka's ttl runs out
        try:
            raw = json.loads(path.read_text())
            self.uid = raw.get("uid", "")
            self.characters = raw.get("characters", {})
            self.next_fetch = float(raw.get("next_fetch", 0.0))
        except (OSError, ValueError):
            pass

    def __len__(self) -> int:
        return len(self.characters)

    def wait_remaining(self, uid: str) -> float:
        """Seconds until Enka will serve a fresh showcase for this UID."""
        if uid.strip() != self.uid:
            return 0.0
        return max(0.0, self.next_fetch - time.time())

    def merge(self, uid: str, chars: list[Character], ttl: int) -> tuple[list[str], list[str]]:
        """Add a fetch's characters; return (new keys, keys whose data changed)."""
        uid = uid.strip()
        if uid != self.uid:
            self.uid, self.characters = uid, {}
        self.next_fetch = time.time() + max(ttl, DEFAULT_TTL)
        new, changed = [], []
        now = int(time.time())
        for c in chars:
            rec = asdict(c)
            old = self.characters.get(c.key)
            if old is None:
                new.append(c.key)
            elif {k: v for k, v in old.items() if k != "fetched_at"} != rec:
                changed.append(c.key)
            self.characters[c.key] = {**rec, "fetched_at": now}
        self.save()
        return new, changed

    def clear(self) -> None:
        self.characters = {}
        self.save()

    def to_characters(self) -> list[Character]:
        return [Character(**{k: v for k, v in rec.items() if k != "fetched_at"})
                for _, rec in sorted(self.characters.items())]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "uid": self.uid, "next_fetch": self.next_fetch,
            "characters": self.characters,
        }, indent=2))


def merge_characters(ocr: list[Character], enka: list[Character]) -> tuple[list[Character], int]:
    """Enka readings replace OCR ones for the same character; OCR fills the rest.

    Returns the merged list and how many OCR readings were kept.
    """
    have = {c.key for c in enka}
    kept = [c for c in ocr if c.key not in have]
    return sorted(enka + kept, key=lambda c: c.key), len(kept)
