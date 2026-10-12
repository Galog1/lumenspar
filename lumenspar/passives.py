"""Conditional bonuses read from set and weapon texts, for the optimizer's CRIT Rate cap.

Artifact set bonuses and weapon passives are prose, and most of them only
apply under a condition. The optimizer needs two things from them: the
always-on 2-piece stats (so they can be subtracted from the character's panel
and added back per candidate set), and any CRIT Rate that appears in combat
only (so crit above the 100% cap is not counted as useful). Both are read from
the game's own texts with a few patterns; anything the patterns do not
recognise is simply ignored.
"""

from __future__ import annotations

import json
import re
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .config import DATA_DIR
from .wishes.icons import USER_AGENT

AMBER_WEAPON = "https://gi.yatta.moe/api/v2/en/weapon/{id}"
CACHE_DIR = DATA_DIR / "passives"
_GAMEDATA = Path(__file__).resolve().parent / "gamedata"

_NUM = r"(\d+(?:\.\d+)?)"
_ELEM = r"(Pyro|Hydro|Electro|Cryo|Anemo|Geo|Dendro|Physical)"

# Plain always-on 2-piece texts -> (GOOD key or element marker, value group).
_STATIC_2PC = (
    (re.compile(r"(ATK|HP|DEF) \+" + _NUM + "%"), "pct"),
    (re.compile(r"Increases Elemental Mastery by (\d+)"), "eleMas"),
    (re.compile(r"Elemental Mastery \+(\d+)"), "eleMas"),
    (re.compile(r"Energy Recharge \+" + _NUM + "%"), "enerRech_"),
    (re.compile(r"CRIT Rate \+" + _NUM + "%"), "critRate_"),
    (re.compile(r"Healing Bonus \+" + _NUM + "%"), "heal_"),
    (re.compile(_ELEM + r" DMG Bonus \+" + _NUM + "%"), "elem"),
    (re.compile(r"(Physical) DMG \+" + _NUM + "%"), "elem"),
    (re.compile(r"Gain an? " + _NUM + "% " + _ELEM + " DMG Bonus"), "elem_rev"),
)

# CRIT Rate increases inside a longer text.
_CRIT_A = re.compile(r"CRIT Rate[^.%]{0,40}?increase[sd]? by (?:an additional )?" + _NUM
                     + "%(?:/" + _NUM + "%)?")
_CRIT_B = re.compile(r"[Ii]ncreases? (?:the )?[\w' ]{0,40}?CRIT Rate(?: of the equipping "
                     r"character)? by " + _NUM + "%(?:/" + _NUM + "%)?")
_STACKS = re.compile(r"[Mm]ax(?:imum)? (\d+) stacks")


def clean(text: str) -> str:
    """A game text without its colour/markup tags and with tidy spacing."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def _static(text: str) -> dict[str, float]:
    """The always-on stats a short bonus text gives; {} when it is anything else."""
    t = clean(text).rstrip(".")
    for pat, kind in _STATIC_2PC:
        m = pat.fullmatch(t)
        if not m:
            continue
        if kind == "pct":
            return {m.group(1).lower() + "_": float(m.group(2))}
        if kind == "elem":
            return {m.group(1).lower() + "_dmg_": float(m.group(2))}
        if kind == "elem_rev":
            return {m.group(2).lower() + "_dmg_": float(m.group(1))}
        return {kind: float(m.group(1))}
    return {}


@lru_cache(maxsize=None)
def _sets() -> dict[str, list[str]]:
    """Set key -> raw bonus texts."""
    try:
        items = json.loads((_GAMEDATA / "artifact_sets.json").read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError):
        return {}
    return {i["key"]: list(i.get("bonuses", [])) for i in items if "key" in i}


def set_bonuses(set_key: str) -> tuple[str, str]:
    """The cleaned (2-piece, 4-piece) texts of a set ("" where missing)."""
    texts = [clean(t) for t in _sets().get(set_key, [])] + ["", ""]
    return texts[0], texts[1]


def set_static_2pc(set_key: str) -> dict[str, float]:
    """The always-on stats of a set's 2-piece bonus, by GOOD key."""
    return _static(set_bonuses(set_key)[0])


def conditional_crit(text: str) -> list[tuple[float, str]]:
    """CRIT Rate increases that depend on a condition, as (value, snippet)."""
    t = clean(text)
    if _static(t):
        return []
    a = list(_CRIT_A.finditer(t))
    b = [m for m in _CRIT_B.finditer(t)
         if not any(m.start() < x.end() and x.start() < m.end() for x in a)]
    out = []
    for m in sorted(a + b, key=lambda m: m.start()):
        nums = [float(g) for g in m.groups() if g is not None]
        out.append((max(nums), m.group(0)))
    stacks = _STACKS.search(t)
    if len(out) == 1 and stacks:
        n = int(stacks.group(1))
        out[0] = (out[0][0] * n, f"{out[0][1]} (×{n} stacks)")
    return out


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def weapon_passive(weapon_id: str, refinement: int, fetch: Callable[[str], bytes] | None = None,
                   root: Path = CACHE_DIR) -> str:
    """A weapon's passive text at a refinement; "" when unavailable. Never raises.

    The texts for every refinement are cached on first use (Project Amber).
    """
    path = root / f"weapon-{weapon_id}.json"
    try:
        try:
            upgrade = json.loads(path.read_text(encoding="utf-8"))["upgrade"]
        except (OSError, ValueError, KeyError):
            data = json.loads((fetch or _download)(AMBER_WEAPON.format(id=weapon_id)))
            affix = data["data"]["affix"]
            upgrade = next(iter(affix.values()))["upgrade"]
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_text(json.dumps({"upgrade": upgrade}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        return clean(upgrade.get(str(max(0, refinement - 1)), ""))
    except Exception:
        return ""
