"""Turn OCR'd weapon panel text into GOOD fields.

Pure text -> data, like `artifact_parse`, so it can be tested without a game.

GOOD stores `ascension` separately from `level`, but the game never shows it as
a number: it shows "Lv. 80/90", where the denominator is the current ascension
cap. That cap maps one-to-one onto the ascension index, which is far more
reliable than trying to read a phase from the UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Ascension cap shown after the slash -> GOOD ascension index.
CAP_TO_ASCENSION: dict[int, int] = {20: 0, 40: 1, 50: 2, 60: 3, 70: 4, 80: 5, 90: 6}

# A weapon cannot exceed these levels at a given rarity.
MAX_LEVEL_BY_RARITY: dict[int, int] = {1: 70, 2: 70, 3: 90, 4: 90, 5: 90}

_LEVEL_RE = re.compile(r"(\d{1,2})\s*[/1lI|]\s*(\d{2})")
# Tesseract reads the diagonal of a "7" as a slash often enough that a real
# scan refused eleven weapons at "Lv. 7/0/70" (the pill says 70/70). Tried only
# when the strict pattern yields nothing valid, so a genuine separator always
# wins; the result is still checked against the real level caps.
_LEVEL_RE_SPLIT = re.compile(r"(\d)\s*[/|]\s*(\d)\s*[/1lI|]\s*(\d{2})")
_REFINE_RE = re.compile(r"(?:rank|R)\s*([1-5])", re.IGNORECASE)


@dataclass(slots=True)
class WeaponPanelText:
    name: str
    level: str
    refinement: str
    rarity: int
    equipped: str | None = None
    locked: bool = False


def parse_level(text: str) -> tuple[int, int] | None:
    """'Lv. 80/90' -> (80, 5). Returns (level, ascension)."""
    cleaned = text.replace("O", "0").replace("o", "0").replace("S", "5")
    candidates = [(m.group(1), m.group(2)) for m in _LEVEL_RE.finditer(cleaned)]
    candidates += [(m.group(1) + m.group(2), m.group(3))
                   for m in _LEVEL_RE_SPLIT.finditer(cleaned)]
    for level_s, cap_s in candidates:
        level, cap = int(level_s), int(cap_s)
        if cap in CAP_TO_ASCENSION and 1 <= level <= 90 and level <= cap:
            # A weapon sitting exactly on its cap may already be ascended past
            # it; the game shows the *next* cap once ascended, so cap alone is
            # unambiguous.
            return level, CAP_TO_ASCENSION[cap]
    return None


def parse_refinement(text: str) -> int | None:
    """'Refinement Rank 3' -> 3, 'R5' -> 5, '[1]' -> 1.

    The panel shows the rank twice: as a small coloured badge and as text. The
    badge's colour changes with the rank, so it cannot be found by brightness,
    and OCR sometimes returns only one of the two -- accept either.
    """
    t = text.replace("&", "5")
    m = _REFINE_RE.search(t)
    if m:
        return int(m.group(1))
    digits = [int(c) for c in t if c.isdigit() and 1 <= int(c) <= 5]
    return digits[-1] if digits else None


def build_weapon(pt: WeaponPanelText, *, min_score: float = 78.0,
                 traveler_name: str = "",
                 wanderer_name: str = "",
                 other_names: str = ""):
    """Assemble a GOOD Weapon, refusing rather than guessing."""
    from ..good import Weapon
    from ..ocr import match as vocab

    problems: list[str] = []

    m = vocab.weapons().match(pt.name, floor=min_score)
    if not m.ok:
        problems.append(f"weapon {pt.name!r} matched {m.key or '—'} at {m.score:.0f}")

    lvl = parse_level(pt.level)
    if lvl is None:
        problems.append(f"unreadable level {pt.level!r}")

    ref = parse_refinement(pt.refinement)
    if ref is None:
        problems.append(f"unreadable refinement {pt.refinement!r}")

    # None means no equipped bar was drawn; an empty read means the bar is
    # there but its name came back blank. Treating the second as "unequipped"
    # silently strips the weapon off its character, so it is refused instead.
    if pt.equipped is not None and not pt.equipped.strip():
        problems.append("the equipped bar is shown but its name could not be read")
    location = ""
    if pt.equipped:
        who = pt.equipped.split(":", 1)[-1].strip() if ":" in pt.equipped else pt.equipped
        role, ambiguous = vocab.custom_name(who, traveler_name, wanderer_name,
                                            other_names)
        if ambiguous:
            problems.append(ambiguous)
        elif role == "Traveler":
            location = "Traveler"
        elif role == "Wanderer":
            location = "Wanderer"
        elif role == "other":
            # Recognised as a player-named character, but GOOD has no key for
            # Manekin gear; refusing beats exporting it under a wrong owner.
            problems.append(
                f"equipped {who!r} is one of the renamed characters listed "
                f"in settings (a Manekin); GOOD has no way to express gear "
                f"equipped on it")
        else:
            lm = vocab.locations().match(who, floor=min_score)
            if lm.ok:
                location = lm.key
            else:
                problems.append(
                    f"equipped {who!r} matched {lm.key or '—'} at {lm.score:.0f}"
                    " (if this is your Traveler or a renamed Wanderer, set its name in settings)"
                )

    if problems:
        return None, problems

    level, ascension = lvl
    cap = MAX_LEVEL_BY_RARITY.get(pt.rarity, 90)
    if level > cap:
        return None, [f"level {level} exceeds the {pt.rarity}-star maximum {cap}"]

    return Weapon(key=m.key, level=level, ascension=ascension,
                  refinement=ref, location=location, lock=pt.locked), []
