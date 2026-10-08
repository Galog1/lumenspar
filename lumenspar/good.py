"""GOOD (Genshin Open Object Description) export.

GOOD is the interchange format consumed by Genshin Optimizer, SEELIE.me and
Aspirine's calculator. Keys are PascalCase with all punctuation and spaces
stripped ("Gladiator's Finale" -> "GladiatorsFinale"); stat keys are a fixed
lowerCamelCase vocabulary where a trailing underscore marks a percentage.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal

GOOD_VERSION = 2
SOURCE = "Lumenspar"

SlotKey = Literal["flower", "plume", "sands", "goblet", "circlet"]

SLOT_KEYS: tuple[str, ...] = ("flower", "plume", "sands", "goblet", "circlet")

# In-game slot captions -> GOOD slot keys.
SLOT_BY_CAPTION: dict[str, str] = {
    "flower of life": "flower",
    "plume of death": "plume",
    "sands of eon": "sands",
    "goblet of eonothem": "goblet",
    "circlet of logos": "circlet",
}

# In-game stat captions -> GOOD stat keys. A trailing "_" means percentage.
STAT_KEYS: dict[str, str] = {
    "hp": "hp",
    "hp%": "hp_",
    "atk": "atk",
    "atk%": "atk_",
    "def": "def",
    "def%": "def_",
    "elemental mastery": "eleMas",
    "energy recharge": "enerRech_",
    "crit rate": "critRate_",
    "crit dmg": "critDMG_",
    "healing bonus": "heal_",
    "physical dmg bonus": "physical_dmg_",
    "anemo dmg bonus": "anemo_dmg_",
    "geo dmg bonus": "geo_dmg_",
    "electro dmg bonus": "electro_dmg_",
    "hydro dmg bonus": "hydro_dmg_",
    "pyro dmg bonus": "pyro_dmg_",
    "cryo dmg bonus": "cryo_dmg_",
    "dendro dmg bonus": "dendro_dmg_",
}

PERCENT_STATS: frozenset[str] = frozenset(k for k in STAT_KEYS.values() if k.endswith("_"))


def to_key(name: str) -> str:
    """Convert a display name to a GOOD key: "Gladiator's Finale" -> GladiatorsFinale."""
    cleaned = re.sub(r"[^0-9a-zA-Z ]+", "", name)
    return "".join(w[:1].upper() + w[1:] for w in cleaned.split())


@dataclass(slots=True)
class SubStat:
    key: str
    value: float


@dataclass(slots=True)
class Artifact:
    setKey: str
    slotKey: str
    level: int
    rarity: int
    mainStatKey: str
    location: str = ""
    lock: bool = False
    substats: list[SubStat] = field(default_factory=list)


@dataclass(slots=True)
class Weapon:
    key: str
    level: int
    ascension: int
    refinement: int
    location: str = ""
    lock: bool = False


@dataclass(slots=True)
class Character:
    key: str
    level: int
    constellation: int
    ascension: int
    talent: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class GoodExport:
    """An accumulating GOOD document."""

    artifacts: list[Artifact] = field(default_factory=list)
    weapons: list[Weapon] = field(default_factory=list)
    characters: list[Character] = field(default_factory=list)
    materials: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "format": "GOOD",
            "version": GOOD_VERSION,
            "source": SOURCE,
        }
        # Omit empty categories entirely: consumers treat an absent key as
        # "not scanned" but an empty list as "scanned and you own none",
        # which would wipe existing data on import.
        if self.artifacts:
            doc["artifacts"] = [asdict(a) for a in self.artifacts]
        if self.weapons:
            doc["weapons"] = [asdict(w) for w in self.weapons]
        if self.characters:
            doc["characters"] = [asdict(c) for c in self.characters]
        if self.materials:
            doc["materials"] = dict(sorted(self.materials.items()))
        return doc

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def __len__(self) -> int:
        return (
            len(self.artifacts)
            + len(self.weapons)
            + len(self.characters)
            + len(self.materials)
        )
