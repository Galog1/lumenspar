"""Build cards: a character's whole build, read from the Enka.Network showcase.

What akasha.cv and Enka's own cards show, computed locally: level and
constellation, talent levels with constellation bonuses, the weapon, every
artifact with its main stat, substats and how many times each substat rolled,
crit value, set bonuses, and the character's final stats as the game reports
them (Enka passes on the game's own totals, so nothing is recomputed here).

Roll counts are exact, not estimated: the showcase lists every roll an
artifact received (`appendPropIdList`), one id per roll, whose last digit is
the roll tier and whose two digits before it say which stat it went to.

Characters accumulate across fetches like the Enka roster does, so rotating
the showcase eventually covers the whole account. Only parsed builds are
stored (in the data folder), never the raw response.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from . import enka
from .config import DATA_DIR

BUILD_DIR = DATA_DIR / "builds"
_GAMEDATA = Path(__file__).resolve().parent / "gamedata"

# Artifact and weapon stats as the showcase names them -> GOOD key and label.
STATS = {
    "FIGHT_PROP_HP": ("hp", "HP"),
    "FIGHT_PROP_HP_PERCENT": ("hp_", "HP%"),
    "FIGHT_PROP_ATTACK": ("atk", "ATK"),
    "FIGHT_PROP_ATTACK_PERCENT": ("atk_", "ATK%"),
    "FIGHT_PROP_DEFENSE": ("def", "DEF"),
    "FIGHT_PROP_DEFENSE_PERCENT": ("def_", "DEF%"),
    "FIGHT_PROP_CRITICAL": ("critRate_", "CRIT Rate"),
    "FIGHT_PROP_CRITICAL_HURT": ("critDMG_", "CRIT DMG"),
    "FIGHT_PROP_CHARGE_EFFICIENCY": ("enerRech_", "Energy Recharge"),
    "FIGHT_PROP_ELEMENT_MASTERY": ("eleMas", "Elemental Mastery"),
    "FIGHT_PROP_HEAL_ADD": ("heal_", "Healing Bonus"),
    "FIGHT_PROP_PHYSICAL_ADD_HURT": ("physical_dmg_", "Physical DMG Bonus"),
    "FIGHT_PROP_FIRE_ADD_HURT": ("pyro_dmg_", "Pyro DMG Bonus"),
    "FIGHT_PROP_ELEC_ADD_HURT": ("electro_dmg_", "Electro DMG Bonus"),
    "FIGHT_PROP_WATER_ADD_HURT": ("hydro_dmg_", "Hydro DMG Bonus"),
    "FIGHT_PROP_GRASS_ADD_HURT": ("dendro_dmg_", "Dendro DMG Bonus"),
    "FIGHT_PROP_WIND_ADD_HURT": ("anemo_dmg_", "Anemo DMG Bonus"),
    "FIGHT_PROP_ROCK_ADD_HURT": ("geo_dmg_", "Geo DMG Bonus"),
    "FIGHT_PROP_ICE_ADD_HURT": ("cryo_dmg_", "Cryo DMG Bonus"),
    "FIGHT_PROP_BASE_ATTACK": ("baseAtk", "Base ATK"),
}

# The stat a roll went to: the two digits before an append-prop id's tier digit.
# Decoded from real showcases (each roll's tier values add up to the substat).
ROLL_STAT = {"02": "hp", "03": "hp_", "05": "atk", "06": "atk_", "08": "def",
             "09": "def_", "20": "critRate_", "22": "critDMG_", "23": "enerRech_",
             "24": "eleMas"}

SLOTS = {"EQUIP_BRACER": "flower", "EQUIP_NECKLACE": "plume", "EQUIP_SHOES": "sands",
         "EQUIP_RING": "goblet", "EQUIP_DRESS": "circlet"}
SLOT_ORDER = list(SLOTS.values())

# Final stats, by fightPropMap id.
_FINAL = (("2000", "hp", "Max HP", False), ("2001", "atk", "ATK", False),
          ("2002", "def", "DEF", False), ("28", "eleMas", "Elemental Mastery", False),
          ("20", "critRate_", "CRIT Rate", True), ("22", "critDMG_", "CRIT DMG", True),
          ("23", "enerRech_", "Energy Recharge", True), ("26", "heal_", "Healing Bonus", True))
_DMG_BONUS = {"30": "physical", "40": "pyro", "41": "electro", "42": "hydro",
              "43": "dendro", "44": "anemo", "45": "geo", "46": "cryo"}

_MAX_LEVEL = (20, 40, 50, 60, 70, 80, 90)

# The raw fightPropMap entries the optimizer needs to recover a character's
# stats without artifacts: base HP/ATK/DEF (1, 4, 7), flat and % bonuses
# (2/3, 5/6, 8/9), crit, ER, healing, EM, DMG bonuses and the totals.
FIGHT_KEEP = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "20", "22", "23", "26", "28",
              "30", "40", "41", "42", "43", "44", "45", "46", "2000", "2001", "2002")
_PERCENT_KEYS = {k for k, _ in STATS.values() if k.endswith("_")}


@lru_cache(maxsize=None)
def _items(name: str, by: str) -> dict:
    try:
        items = json.loads((_GAMEDATA / name).read_text(encoding="utf-8"))["items"]
    except (OSError, ValueError, KeyError):
        return {}
    return {str(i[by]): i for i in items if i.get(by) is not None}


def _clean(text: str) -> str:
    """Set-bonus text without the game's colour/markup tags."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def fmt(key: str, value: float) -> str:
    """A stat as the game shows it: 1,234 / 46.6% / 5.8%."""
    if key in _PERCENT_KEYS:
        return f"{value:.1f}%"
    return f"{round(value):,}"


def roll_counts(append_ids: list) -> Counter:
    """How many rolls each substat received (its first roll included)."""
    counts: Counter = Counter()
    for pid in append_ids or []:
        stat = ROLL_STAT.get(str(pid)[-3:-1])
        if stat:
            counts[stat] += 1
    return counts


def _artifact(equip: dict) -> dict | None:
    flat = equip.get("flat") or {}
    rel = equip.get("reliquary") or {}
    slot = SLOTS.get(flat.get("equipType", ""))
    if not slot:
        return None
    set_id = str(flat.get("setId") or "")
    if not set_id:     # older responses: the set id is in the icon name
        m = re.search(r"UI_RelicIcon_(\d+)_", flat.get("icon", ""))
        set_id = m.group(1) if m else ""
    art_set = _items("artifact_sets.json", "id").get(set_id, {})
    main = flat.get("reliquaryMainstat") or {}
    main_key, main_label = STATS.get(main.get("mainPropId", ""), ("", main.get("mainPropId", "")))
    rolls = roll_counts(rel.get("appendPropIdList"))
    subs = []
    for s in flat.get("reliquarySubstats") or []:
        key, label = STATS.get(s.get("appendPropId", ""), ("", s.get("appendPropId", "")))
        value = float(s.get("statValue", 0))
        subs.append({"key": key, "label": label, "value": value, "text": fmt(key, value),
                     "rolls": rolls.get(key, 0)})
    cv = sum(2 * s["value"] for s in subs if s["key"] == "critRate_") + \
        sum(s["value"] for s in subs if s["key"] == "critDMG_")
    return {
        "slot": slot, "setId": set_id, "setKey": art_set.get("key", ""),
        "setName": art_set.get("name", f"Set {set_id}" if set_id else "Unknown set"),
        "rarity": int(flat.get("rankLevel") or 0),
        "level": max(0, int(rel.get("level") or 1) - 1),
        "icon": flat.get("icon", ""),
        "main": {"key": main_key, "label": main_label,
                 "value": float(main.get("statValue", 0)),
                 "text": fmt(main_key, float(main.get("statValue", 0)))},
        "subs": subs,
        "critValue": round(cv, 1),
    }


def _weapon(equip: dict) -> dict:
    flat = equip.get("flat") or {}
    w = equip.get("weapon") or {}
    info = _items("weapons.json", "id").get(str(equip.get("itemId")), {})
    affix = w.get("affixMap") or {}
    stats = []
    for s in flat.get("weaponStats") or []:
        key, label = STATS.get(s.get("appendPropId", ""), ("", s.get("appendPropId", "")))
        value = float(s.get("statValue", 0))
        stats.append({"key": key, "label": label, "text": fmt(key, value)})
    return {
        "id": str(equip.get("itemId", "")),
        "key": info.get("key", ""), "name": info.get("name", f"Weapon {equip.get('itemId')}"),
        "rarity": int(flat.get("rankLevel") or info.get("rarity") or 0),
        "level": int(w.get("level") or 1), "ascension": int(w.get("promoteLevel") or 0),
        # 1-2★ weapons have no refinement at all.
        "refinement": int(next(iter(affix.values()), 0)) + 1,
        "icon": flat.get("icon", "") or info.get("icon", ""),
        "stats": stats,
    }


def parse(data: dict) -> tuple[dict, list[dict], list[str]]:
    """Return (player, builds, problems) for a showcase response."""
    info = data.get("playerInfo") or {}
    player = {"nickname": info.get("nickname", ""), "level": info.get("level", 0),
              "worldLevel": info.get("worldLevel", 0), "signature": info.get("signature", ""),
              "achievements": info.get("finishAchievementNum", 0),
              "abyss": (f"{info['towerFloorIndex']}-{info.get('towerLevelIndex', 0)}"
                        if info.get("towerFloorIndex") else "")}
    avatars = data.get("avatarInfoList")
    if not avatars:
        return player, [], ["the showcase is empty, or \"Show Character Details\" is turned "
                            "off in your in-game profile"]
    table = enka._avatar_map()
    chars = _items("characters.json", "key")
    builds, problems = [], []
    now = int(time.time())
    for a in avatars:
        aid = a.get("avatarId")
        entry = table.get(f"{aid}-{a.get('skillDepotId')}") or table.get(str(aid))
        if entry is None:
            name = enka.MANEKIN_IDS.get(aid)
            problems.append(f"{name}: Enka.Network publishes too little about Manekins for a "
                            f"build card" if name else
                            f"character id {aid} is newer than Lumenspar's game data "
                            f"(update Lumenspar)")
            continue
        key = entry["key"]
        char = chars.get(key, {})
        props = a.get("propMap") or {}
        level = int((props.get("4001") or {}).get("ival") or 1)
        ascension = int((props.get("1002") or {}).get("ival") or 0)
        levels = a.get("skillLevelMap") or {}
        extra = a.get("proudSkillExtraLevelMap") or {}
        talents = []
        for slot, label in (("auto", "Normal Attack"), ("skill", "Elemental Skill"),
                            ("burst", "Elemental Burst")):
            base = int(levels.get(entry.get(slot, ""), 1))
            bonus = int(extra.get((entry.get("proud") or {}).get(slot, ""), 0))
            talents.append({"slot": slot, "label": label, "base": base,
                            "level": base + bonus, "boosted": bonus > 0})
        fight = a.get("fightPropMap") or {}
        stats = [{"key": k, "label": label,
                  "text": fmt(k, float(fight.get(fid, 0)) * (100 if pct else 1))}
                 for fid, k, label, pct in _FINAL
                 if not (k == "heal_" and not fight.get(fid))]
        # The highest elemental/physical bonus, or the character's own element.
        element = char.get("element") or ""
        bonus_id = max(_DMG_BONUS, key=lambda i: (float(fight.get(i, 0)),
                                                  _DMG_BONUS[i] == element))
        if float(fight.get(bonus_id, 0)) > 0:
            name = _DMG_BONUS[bonus_id]
            stats.append({"key": f"{name}_dmg_", "label": f"{name.capitalize()} DMG Bonus",
                          "text": fmt(f"{name}_dmg_", float(fight[bonus_id]) * 100)})

        weapon, artifacts = None, []
        for equip in a.get("equipList") or []:
            if "weapon" in equip:
                weapon = _weapon(equip)
            elif "reliquary" in equip:
                art = _artifact(equip)
                if art:
                    artifacts.append(art)
        artifacts.sort(key=lambda r: SLOT_ORDER.index(r["slot"]))
        set_counts = Counter(r["setId"] for r in artifacts if r["setId"])
        sets_info = _items("artifact_sets.json", "id")
        sets = []
        for sid, n in set_counts.most_common():
            if n < 2:
                continue
            s = sets_info.get(sid, {})
            bonuses = [_clean(t) for t in s.get("bonuses", [])]
            sets.append({"name": s.get("name", f"Set {sid}"), "count": n,
                         "bonuses": bonuses[: 2 if n >= 4 else 1]})

        builds.append({
            "avatarId": str(aid), "key": key,
            "name": char.get("name") or key,
            "element": element or key.removeprefix("Traveler").lower(),
            "rarity": int(char.get("rarity") or 5),
            "icon": char.get("icon", ""),
            "splash": (char.get("icon", "").replace("UI_AvatarIcon_", "UI_Gacha_AvatarImg_")
                       if char.get("icon") else ""),
            "level": level, "ascension": ascension,
            "maxLevel": max(level, _MAX_LEVEL[min(ascension, 6)]),
            "constellation": len(a.get("talentIdList") or []),
            "friendship": int((a.get("fetterInfo") or {}).get("expLevel") or 0),
            "talents": talents, "weapon": weapon, "artifacts": artifacts, "sets": sets,
            "stats": stats,
            "critValue": round(sum(r["critValue"] for r in artifacts), 1),
            "fight": {k: float(fight[k]) for k in FIGHT_KEEP if k in fight},
            "fetchedAt": now,
        })
    return player, builds, problems


class Collection:
    """Build cards gathered across showcase fetches, for one UID at a time."""

    def __init__(self, uid: str, root: Path = BUILD_DIR) -> None:
        self.uid = uid.strip()
        self.path = root / f"{self.uid}.json"
        self.player: dict = {}
        self.builds: dict[str, dict] = {}
        # Cards the player removed, and when: so a Drive sync does not bring
        # them back from another copy (a later reading of that character does).
        self.removed: dict[str, int] = {}
        self.next_fetch = 0.0
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.player = raw.get("player", {})
            self.builds = raw.get("builds", {})
            self.removed = {k: int(v) for k, v in (raw.get("removed") or {}).items()}
            self.next_fetch = float(raw.get("next_fetch", 0.0))
        except (OSError, ValueError):
            pass

    def wait_remaining(self) -> float:
        return max(0.0, self.next_fetch - time.time())

    def merge(self, player: dict, builds: list[dict], ttl: int) -> tuple[list[str], list[str]]:
        """Add a fetch's builds; return (new names, updated names)."""
        self.player = player or self.player
        self.next_fetch = time.time() + max(ttl, enka.DEFAULT_TTL)
        new, updated = [], []
        for b in builds:
            old = self.builds.get(b["avatarId"])
            same = old is not None and {k: v for k, v in old.items() if k != "fetchedAt"} == \
                {k: v for k, v in b.items() if k != "fetchedAt"}
            if old is None:
                new.append(b["name"])
            elif not same:
                updated.append(b["name"])
            if not same:
                self.builds[b["avatarId"]] = b
            self.removed.pop(b["avatarId"], None)
        self.save()
        return new, updated

    def ordered(self, showcase_first: list[str] | None = None) -> list[dict]:
        """Builds in showcase order, then the rest by when they were last seen."""
        first = [self.builds[i] for i in (showcase_first or []) if i in self.builds]
        rest = sorted((b for i, b in self.builds.items() if i not in (showcase_first or [])),
                      key=lambda b: -b.get("fetchedAt", 0))
        return first + rest

    def remove(self, avatar_id: str) -> None:
        self.builds.pop(avatar_id, None)
        self.removed[avatar_id] = int(time.time())
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"uid": self.uid, "player": self.player,
                                   "next_fetch": self.next_fetch, "builds": self.builds,
                                   "removed": self.removed},
                                  indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


def latest(root: Path = BUILD_DIR) -> Collection | None:
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if root.is_dir() else []
    return Collection(files[0].stem, root) if files else None
