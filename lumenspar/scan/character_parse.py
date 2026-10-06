"""Turn OCR'd character screen text into GOOD fields.

Pure text -> data, like the artifact and weapon parsers.

The subtle part is talents. Genshin *displays* a talent level that already
includes constellation bonuses (C3 and C5 each add +3 to one talent), so a
maxed character can show "Lv. 13". GOOD wants the **base** level: Genshin
Optimizer's schema clamps talents to `talentLimits[ascension]`, which tops out
at 10. Exporting the displayed number would inflate every constellation-boosted
character's build.

Which talent(s) C3/C5 boost is kit-specific -- Raiden Shogun's C3 boosts
Burst, Neuvillette's boosts Auto -- there is no rule to infer it from, so it
is not guessed here at all. `characters.read_talents` reads the boost
directly off the screen (a boosted number is drawn cyan) and hands it in
already tagged; this module only strips it and clamps to the ascension cap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Max base talent level per ascension (mirrors Genshin Optimizer's
# `talentLimits`), and the level cap per ascension (`ascensionMaxLevel`).
TALENT_LIMITS: tuple[int, ...] = (1, 1, 2, 4, 6, 8, 10)
# 95 and 100 are not new ascension phases -- Genshin's level cap increase
# (patch 6.0, Sept 2026) tops a character up past its normal level-90/phase-6
# ceiling by consuming a "Masterless Stella Fortuna" per +5 levels, without
# granting a further ascension. Talent caps stay governed by phase 6.
CAP_TO_ASCENSION: dict[int, int] = {20: 0, 40: 1, 50: 2, 60: 3, 70: 4, 80: 5,
                                    90: 6, 95: 6, 100: 6}

CONSTELLATION_TALENT_BONUS = 3

_LEVEL_RE = re.compile(r"(\d{1,3})\s*[/1lI|]\s*(\d{2,3})")
# Genshin draws the slash with a flourished top-left serif, and Tesseract reads
# it as a "7" often enough to have refused two real characters ("Level 1007100",
# "Level 90 790"). It is only tried after the strict pattern finds nothing,
# which is what keeps it safe: a genuine "Level 77/80" still contains a real
# separator, so the strict pass claims it first and the digit-7 reading never
# gets the chance to split "77" into a level of 7.
_LEVEL_RE_LOOSE = re.compile(r"(\d{1,3})\s*[/1lI|7]\s*(\d{2,3})")
_TALENT_RE = re.compile(r"(\d{1,2})")
# The level readout is only ever letters, digits, spaces and the slash, so
# anything else came from the background: a sparkle fleck sitting beside the
# number is glyph-sized, survives the speckle filter, and reads as punctuation
# ("Level 90-/ 90"), which is enough to stop the number and the slash being
# adjacent. Dropping those characters outright is safer than loosening the
# pattern to skip over them, which would also let it skip over real digits.
_LEVEL_NOISE_RE = re.compile(r"[^0-9A-Za-z/|\s]")


@dataclass(slots=True)
class CharacterPanelText:
    name: str
    level: str
    # 0-6, counted from the C icons; None when the page could not be captured,
    # which must be reported rather than exported as C0.
    constellation: int | None
    talents: dict[str, str] = field(default_factory=dict)   # auto/skill/burst
    # Whether each slot's displayed number was drawn cyan (constellation
    # bonus applied), read directly off the Talents screen -- see module
    # docstring. Missing/False for a slot means "not boosted", the same as
    # every character below C3.
    talent_boosted: dict[str, bool] = field(default_factory=dict)
    element: str | None = None      # only needed to key the Traveler
    # The flavour blurb, used only to explain a name that matched nothing.
    description: str = ""


def parse_level(text: str) -> tuple[int, int] | None:
    """'Lv. 80/90' -> (80, 5). Same shape as the weapon level badge."""
    cleaned = _LEVEL_NOISE_RE.sub(
        "", text.replace("O", "0").replace("o", "0").replace("S", "5"))
    for pattern in (_LEVEL_RE, _LEVEL_RE_LOOSE):
        for m in pattern.finditer(cleaned):
            level, cap = int(m.group(1)), int(m.group(2))
            if cap in CAP_TO_ASCENSION and 1 <= level <= 100 and level <= cap:
                return level, CAP_TO_ASCENSION[cap]
    return None


def parse_talent(text: str) -> int | None:
    """'Lv. 10' -> 10."""
    m = _TALENT_RE.search(text.replace("O", "0").replace("o", "0"))
    if not m:
        return None
    lvl = int(m.group(1))
    return lvl if 1 <= lvl <= 15 else None


def base_talent(displayed: int, boosted: bool, ascension: int) -> int:
    """Strip a constellation bonus and clamp to what the ascension allows."""
    lvl = displayed - (CONSTELLATION_TALENT_BONUS if boosted else 0)
    cap = TALENT_LIMITS[max(0, min(6, ascension))]
    return max(1, min(lvl, cap))


def expected_boost_count(constellation: int) -> int:
    """How many talents *should* be boosted at this constellation.

    Only the count is fixed (0 below C3, 1 at C3-C4, 2 at C5-C6); *which*
    talent(s) is kit-specific and is never guessed -- see module docstring.
    Used only to sanity-check what was actually observed on screen.
    """
    if constellation < 3:
        return 0
    if constellation < 5:
        return 1
    return 2


def _unmatched_name(pt: CharacterPanelText, m) -> str:
    """Explain a name that matched nothing, rather than blaming the OCR.

    "character 'Gall' matched Albedo at 60" reads like a bad read of a known
    character and sends you looking for a thresholding problem. Several
    entries on the character screen carry a *player-chosen* name -- the
    Traveler, the Wanderer once renamed, and the Manekins -- so their
    displayed name is not in any vocabulary and never will be. A Manekin can
    at least be recognised from its description, which is fixed text.
    """
    blurb = re.sub(r"[^a-z]", "", pt.description.lower())
    # "Manekin" comes back as "Manek n" -- the dotted lowercase i drops out at
    # this text size -- so match the stem rather than the whole word.
    if "manek" in blurb:
        return (f"{pt.name!r} is a Manekin (recognised from its description). "
                f"Its displayed name is whatever you named it, and the two "
                f"variants Manekin and Manekina cannot be told apart on "
                f"screen: they share one description, and their element is "
                f"player-assigned rather than fixed")
    return (f"character {pt.name!r} is not a known character name "
            f"(closest was {m.key or '—'} at {m.score:.0f}). Characters whose "
            f"name you can change -- the Traveler, a renamed Wanderer, a "
            f"Manekin -- read back as whatever you called them. Set the Traveler's "
            f"and Wanderer's names in settings so they can be recognised")


def build_character(pt: CharacterPanelText, *, min_score: float = 78.0,
                    traveler_name: str = "",
                    wanderer_name: str = ""):
    """Assemble a GOOD Character, refusing rather than guessing."""
    from ..good import Character
    from ..ocr import match as vocab

    problems: list[str] = []

    if traveler_name and vocab.normalise(pt.name) == vocab.normalise(traveler_name):
        # The Traveler's key is element-suffixed and cannot come from the name.
        if pt.element:
            key = "Traveler" + pt.element.capitalize()
        else:
            problems.append("Traveler's element could not be read, so its key "
                            "(TravelerAnemo, TravelerGeo, ...) is unknown")
            key = ""
    elif wanderer_name and vocab.normalise(pt.name) == vocab.normalise(wanderer_name):
        # Unlike the Traveler, the Wanderer has one key whatever it is called.
        key = "Wanderer"
    else:
        m = vocab.characters().match(pt.name, floor=min_score)
        if not m.ok:
            problems.append(_unmatched_name(pt, m))
        key = m.key

    lvl = parse_level(pt.level)
    if lvl is None:
        problems.append(f"unreadable level {pt.level!r}")

    if pt.constellation is None:
        problems.append("the Constellation page could not be captured")
    elif not 0 <= pt.constellation <= 6:
        problems.append(f"implausible constellation {pt.constellation}")

    talent: dict[str, int] = {}
    boosted_slots: set[str] = set()
    over: list[str] = []
    if lvl is not None:
        _, ascension = lvl
        shown: dict[str, int] = {}
        for slot in ("auto", "skill", "burst"):
            got = parse_talent(pt.talents.get(slot, ""))
            if got is None:
                problems.append(f"unreadable {slot} talent {pt.talents.get(slot, '')!r}")
            else:
                shown[slot] = got
                if pt.talent_boosted.get(slot):
                    boosted_slots.add(slot)
        for slot, got in shown.items():
            talent[slot] = base_talent(got, slot in boosted_slots, ascension)
            stripped = got - (CONSTELLATION_TALENT_BONUS
                              if slot in boosted_slots else 0)
            if stripped != talent[slot]:
                # The clamp only ever fires when something upstream is wrong:
                # a level the ascension cannot allow means the talent, the
                # boost or the character level was misread. Exporting the
                # clamped value quietly would hide that.
                over.append(f"{slot} showed {got}, which ascension "
                            f"{ascension} cannot reach; exported as "
                            f"{talent[slot]}")

    if problems:
        return None, problems

    level, ascension = lvl
    warnings: list[str] = list(over)
    expected = expected_boost_count(pt.constellation)
    if len(boosted_slots) != expected:
        seen = ", ".join(sorted(boosted_slots)) or "none"
        warnings.append(
            f"C{pt.constellation} should show {expected} talent(s) raised +3 by "
            f"constellations, but {len(boosted_slots)} ({seen}) were drawn as "
            f"boosted on the Talents screen. Levels exported exactly as "
            f"displayed, so a talent may be 3 too high or too low.")
    return Character(key=key, level=level, constellation=pt.constellation,
                     ascension=ascension, talent=talent), warnings
