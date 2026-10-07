"""Turn OCR'd artifact panel text into GOOD fields.

Pure text -> data. Deliberately free of screen coordinates so it can be tested
against real captions without a running game.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations_with_replacement
from pathlib import Path

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
#
# The value may open with a glyph Tesseract confuses with "1" and contain an
# "O" for "0". Without those in the pattern the match simply starts at the
# first real digit, so "DEF+I7" exported DEF 7 instead of 17 -- a wrong number
# rather than a refusal. They are folded to digits below, and anything the
# folding gets wrong is caught by the roll-table check in build_artifact.
_SUB_TAIL = re.compile(r"(?P<value>[Il|!]?\d[\dOo.,]*)\s*(?P<pct>%?)\s*$")
_DIGIT_FOLD = str.maketrans({"I": "1", "l": "1", "|": "1", "!": "1", "O": "0", "o": "0"})
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
        # A doubled decimal point ("14..2%") is a real misread; the roll-table
        # check in build_artifact still has to accept whatever this produces.
        raw = re.sub(r"\.{2,}", ".", m.group("value").translate(_DIGIT_FOLD))
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    return SubStat(key, value)


# -- roll-table validation ------------------------------------------------
#
# A substat is never an arbitrary number: it is the sum of one to six rolls,
# each one of four fixed values for that stat and rarity. Only a few dozen
# totals are reachable per stat, so a misread digit usually lands on a number
# the game cannot produce. (The idea comes from AdeptiScanner, which snaps each
# line to the nearest legal value; here an illegal value is refused instead,
# which makes the scanner retry the frame rather than export a guess.)

_STATS_PATH = Path(__file__).resolve().parent.parent / "gamedata" / "artifact_stats.json"

# Most substats an artifact can start with, by rarity. Each upgrade every four
# levels adds exactly one roll, so an artifact can never hold more than this
# plus level // 4 rolls in total.
MAX_INITIAL_SUBSTATS = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}


def _display(value: float, percent: bool) -> float:
    """Round half-up to what the panel shows: one decimal for %, whole otherwise."""
    step = 10 if percent else 1
    return math.floor(value * step + 0.5) / step


@lru_cache(maxsize=None)
def _substat_table() -> dict[tuple[int, str], dict[float, int]]:
    """(rarity, key) -> {displayed value: fewest rolls that can produce it}.

    The source table stores each roll rounded to two decimals, while the game
    sums the exact values, so a total of n rolls may be off by up to 0.005*n.
    When that puts a sum near a rounding boundary, both neighbours are
    accepted: rejecting a real artifact is worse than letting through one
    extra value, since an illegal read is only a backstop, not the reader.
    """
    raw = json.loads(_STATS_PATH.read_text())
    corrections = raw.get("display_corrections", {})
    table: dict[tuple[int, str], dict[float, int]] = {}
    for rarity, stats in raw["substat_rolls"].items():
        for key, rolls in stats.items():
            percent = key.endswith("_")
            fewest: dict[float, int] = {}
            for n in range(1, 7):
                slack = 0.005 * n
                for combo in combinations_with_replacement(rolls, n):
                    total = sum(combo)
                    for shown in {_display(total - slack, percent),
                                  _display(total + slack, percent)}:
                        fewest[shown] = min(fewest.get(shown, n), n)
            for computed, shown in corrections.get(rarity, {}).get(key, {}).items():
                n = fewest.get(float(computed))
                if n is not None:
                    fewest[float(shown)] = min(fewest.get(float(shown), n), n)
            table[(int(rarity), key)] = fewest
    return table


def substat_problems(subs: list[SubStat], rarity: int, level: int | None) -> list[str]:
    """Reasons these substats cannot be what the panel really shows."""
    table = _substat_table()
    problems: list[str] = []
    rolls = 0
    for s in subs:
        legal = table.get((rarity, s.key))
        if legal is None:
            continue
        n = legal.get(_display(s.value, s.key.endswith("_")))
        if n is None:
            problems.append(f"substat {s.key} {s.value:g} is not a value a "
                            f"{rarity}-star artifact can roll (misread)")
        else:
            rolls += n
    if level is not None and not problems and rarity in MAX_INITIAL_SUBSTATS:
        most = MAX_INITIAL_SUBSTATS[rarity] + level // 4
        if rolls > most:
            problems.append(f"substats need at least {rolls} rolls, but a "
                            f"{rarity}-star +{level} holds at most {most} (misread)")
    return problems


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
                   traveler_name: str = "",
                   wanderer_name: str = "",
                   other_names: str = "") -> ParseResult:
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

    # None means no equipped bar was drawn; an empty read means the bar is
    # there but its name came back blank. Treating the second as "unequipped"
    # silently strips the artifact off its character, so it is refused instead.
    if pt.equipped is not None and not pt.equipped.strip():
        problems.append("the equipped bar is shown but its name could not be read")
    problems.extend(substat_problems(subs, pt.rarity, level))

    location = ""
    if pt.equipped:
        who = parse_equipped(pt.equipped) or pt.equipped
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
            m = vocab.locations().match(who, floor=min_score)
            if m.ok:
                location = m.key
            else:
                problems.append(
                    f"equipped {who!r} matched {m.key or '—'} at {m.score:.0f}"
                    " (if this is your Traveler or a renamed Wanderer, set its name in settings)"
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
