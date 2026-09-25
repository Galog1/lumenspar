"""Turn OCR'd artifact panel text into GOOD fields.

Pure text -> data. Deliberately free of screen coordinates so it can be tested
against real captions without a running game.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..good import SLOT_BY_CAPTION, STAT_KEYS, SubStat

try:
    from rapidfuzz import fuzz, process
    _HAVE_RF = True
except ImportError:
    _HAVE_RF = False

# "CRIT Rate+8.6%", "DEF+23", "Elemental Mastery+37".
# Anchored on the trailing number rather than on a literal '+': the separator
# is small and frequently misread ("CRIT DMGH17.1%"), and demanding it would
# throw away an otherwise perfect line.
_SUB_TAIL = re.compile(r"(?P<value>\d[\d.,]*)\s*(?P<pct>%?)\s*$")
_LEVEL_RE = re.compile(r"\+\s*(\d{1,2})")

# Leading bullets/noise Tesseract emits for the "·" list marker.
_BULLET = re.compile(r"^[\s•·\-\*oO°.,:+»«|]+")

_STAT_NAMES = list(STAT_KEYS)


def _clean(text: str) -> str:
    return _BULLET.sub("", text).strip()


def _stat_key(name: str, percent: bool) -> str | None:
    """Resolve a stat caption to a GOOD key, tolerating OCR damage.

    The percent suffix is what separates flat from scaling stats: 'ATK+16' is
    `atk` while 'ATK+4.7%' is `atk_`, and confusing them corrupts a build.
    """
    # Strip punctuation before matching: OCR of the header often trails junk
    # picked up from the artifact icon ("CRIT DMG ~~,").
    probe = re.sub(r"[^a-z0-9% ]+", " ", name.strip().lower())
    probe = re.sub(r"\s+", " ", probe).strip()
    lookup = probe + ("%" if percent else "")
    if lookup in STAT_KEYS:
        return STAT_KEYS[lookup]

    # Elemental Mastery and Energy Recharge never carry a bare/percent twin,
    # so match the name alone before giving up.
    if probe in STAT_KEYS:
        return STAT_KEYS[probe]

    if _HAVE_RF:
        best = process.extractOne(probe, _STAT_NAMES, scorer=fuzz.WRatio)
        if best and best[1] >= 82:
            cand = best[0]
            # Re-apply the percent decision to the matched base name.
            base = cand.rstrip("%")
            keyed = base + ("%" if percent else "")
            return STAT_KEYS.get(keyed) or STAT_KEYS.get(cand)
    return None


def parse_substat(line: str) -> SubStat | None:
    """'CRIT Rate+8.6%' -> SubStat('critRate_', 8.6)."""
    text = _clean(line)
    m = _SUB_TAIL.search(text)
    if not m:
        return None
    # Trim the separator glyph off the name; fuzzy matching absorbs the rest.
    name = text[: m.start()].rstrip(" +HhtT*·-—:_")
    key = _stat_key(name, bool(m.group("pct")))
    if key is None:
        return None
    try:
        value = float(m.group("value").replace(",", ""))
    except ValueError:
        return None
    return SubStat(key, value)


def parse_main_stat(label: str, value: str) -> tuple[str, float] | None:
    """('ATK', '46.6%') -> ('atk_', 46.6); ('HP', '4,780') -> ('hp', 4780.0)."""
    raw = value.strip()
    percent = raw.endswith("%")
    num = re.sub(r"[^\d.]", "", raw)
    key = _stat_key(label, percent)
    if key is None or not num:
        return None
    try:
        return key, float(num)
    except ValueError:
        return None


def parse_level(text: str) -> int | None:
    """'+20' -> 20."""
    m = _LEVEL_RE.search(text.replace("O", "0").replace("o", "0"))
    if not m:
        return None
    lvl = int(m.group(1))
    return lvl if 0 <= lvl <= 20 else None


def parse_slot(caption: str) -> str | None:
    """'Sands of Eon' -> 'sands'."""
    probe = re.sub(r"[^a-z ]", "", caption.strip().lower())
    probe = re.sub(r"\s+", " ", probe).strip()
    if probe in SLOT_BY_CAPTION:
        return SLOT_BY_CAPTION[probe]
    if _HAVE_RF:
        best = process.extractOne(probe, list(SLOT_BY_CAPTION), scorer=fuzz.WRatio)
        if best and best[1] >= 80:
            return SLOT_BY_CAPTION[best[0]]
    return None


def parse_equipped(line: str) -> str | None:
    """'Equipped: Arlecchino' -> 'Arlecchino' (raw name, matched separately)."""
    if ":" not in line:
        return None
    name = line.split(":", 1)[1].strip()
    return name or None


def parse_set_line(line: str) -> str:
    """Strip the trailing colon from the green set-name line."""
    return _clean(line).rstrip(":").strip()


@dataclass(slots=True)
class PanelText:
    """The raw strings lifted from one artifact detail panel."""

    slot: str
    main_label: str
    main_value: str
    rarity: int
    level: str
    substats: list[str]
    set_line: str
    equipped: str | None = None
    elixir: bool = False
    locked: bool = False


@dataclass(slots=True)
class ParseResult:
    artifact: object | None
    problems: list[str]

    @property
    def ok(self) -> bool:
        return self.artifact is not None


def build_artifact(pt: PanelText, *, min_score: float = 78.0,
                   traveler_name: str = "") -> ParseResult:
    """Assemble a GOOD Artifact, refusing rather than guessing on bad reads."""
    from ..good import Artifact
    from ..ocr import match as vocab

    problems: list[str] = []

    slot = parse_slot(pt.slot)
    if slot is None:
        problems.append(f"unrecognised slot {pt.slot!r}")

    # Flower and Plume main stats are fixed by the game, so the slot is a more
    # reliable source than OCR of a two-letter caption.
    FIXED = {"flower": "hp", "plume": "atk"}
    main = parse_main_stat(pt.main_label, pt.main_value)
    if slot in FIXED:
        main = (FIXED[slot], main[1] if main else 0.0)
    elif main is None:
        problems.append(f"unrecognised main stat {pt.main_label!r} {pt.main_value!r}")

    level = parse_level(pt.level)
    if level is None:
        problems.append(f"unreadable level {pt.level!r}")

    set_match = vocab.artifact_sets().match(parse_set_line(pt.set_line), floor=min_score)
    if not set_match.ok:
        problems.append(
            f"set {pt.set_line!r} matched {set_match.key or '—'} at {set_match.score:.0f}"
        )

    subs = []
    for line in pt.substats:
        # A substat can be present but not yet in effect ("(unactivated)").
        # It contributes nothing, so exporting it would inflate an optimiser's
        # numbers; skip it rather than refuse the whole artifact.
        if "unactiv" in re.sub(r"[^a-z]", "", line.lower()):
            continue
        s = parse_substat(line)
        if s is None:
            problems.append(f"unreadable substat {line!r}")
        else:
            subs.append(s)

    location = ""
    if pt.equipped:
        who = parse_equipped(pt.equipped) or pt.equipped
        if traveler_name and vocab.normalise(who) == vocab.normalise(traveler_name):
            location = "Traveler"
        else:
            m = vocab.locations().match(who, floor=min_score)
            if m.ok:
                location = m.key
            else:
                problems.append(
                    f"equipped {who!r} matched {m.key or '—'} at {m.score:.0f}"
                    " (if this is your Traveler, set its name in settings)"
                )

    if problems:
        return ParseResult(None, problems)

    return ParseResult(
        Artifact(
            setKey=set_match.key,
            slotKey=slot,
            level=level,
            rarity=pt.rarity,
            mainStatKey=main[0],
            location=location,
            lock=pt.locked,
            substats=subs,
        ),
        [],
    )
