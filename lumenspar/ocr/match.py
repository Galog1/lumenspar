"""Snap raw OCR text onto the known game vocabulary.

OCR of game captions is rarely character-perfect, but the space of legal
answers is tiny and known ahead of time, so a fuzzy match against the shipped
lists recovers nearly every read. Matches below a score floor are rejected
outright: a wrong-but-plausible item silently corrupts an export, whereas a
refusal can be surfaced to the user.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

GAMEDATA = Path(__file__).resolve().parent.parent / "gamedata"

try:
    from rapidfuzz import fuzz, process  # type: ignore
    _HAVE_RF = True
except ImportError:  # fallback keeps the module importable pre-install
    import difflib
    _HAVE_RF = False

# Glyph pairs Tesseract most often swaps in this font. Folding a pair costs
# nothing as long as no two real names differ *only* by it -- checked against
# every shipped vocabulary (characters, weapons, artifact sets, all 820
# materials, locations): zero collisions.
#
# "q" folds to "g" because a real scan read Qiqi as "Qigi", which the fuzzy
# pass scored 75 against a floor of 78 and refused. Lowering the floor would
# have been the wrong fix: real names already sit *above* it -- "Manekina" vs
# "Manekin" score 93 and the two Kamisato siblings 85 -- so the floor is not
# what keeps those apart, and dropping it would only make a genuine near-miss
# more likely to be accepted. Folding the confusable glyph instead turns this
# into an exact hit and leaves the floor doing its job.
CONFUSIONS = str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b", "|": "l",
                            "!": "l", "q": "g"})


def normalise(text: str) -> str:
    """Lowercase, drop punctuation/whitespace, and fold common OCR confusions."""
    t = text.lower().translate(CONFUSIONS)
    return re.sub(r"[^a-z0-9]+", "", t)


def _within_one_edit(a: str, b: str) -> bool:
    """True when a and b differ by at most one inserted, dropped or swapped glyph."""
    # Pure Python on purpose: rapidfuzz is optional (see _HAVE_RF above), and
    # this gates a *refusal*, so it must not fall back to some fuzzy scorer's
    # looser idea of similarity -- the caller decides the edit budget, not a
    # library's default thresholds.
    if a == b:
        return True  # zero edits is at most one
    if abs(len(a) - len(b)) > 1:
        return False  # the length alone differs by two or more glyphs
    if len(a) == len(b):
        # Same length: exactly one glyph must differ (a swap).
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    # b is one glyph longer than a: a must equal b with exactly one glyph
    # removed (an insertion on the other side is the same edit).
    return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


def custom_name(text: str, traveler_name: str = "", wanderer_name: str = "",
                other_names: str = "") -> tuple[str, str]:
    """Decide whether an OCR'd name is one of the player-named characters.

    Returns (role, problem). role is "Traveler", "Wanderer", "other" or ""
    ("" = not a custom name, fall through to the vocabulary). problem is a
    non-empty refusal message when the name is ambiguous.

    Why this guard exists: the Traveler, a renamed Wanderer and the Manekins
    all display a name the player chose, so they can never come from the
    shipped vocabulary -- the only way to recognise them is against the
    configured names. But matching those names eagerly has its own hazard:
    `normalise()` folds "1" onto "l", so a Manekin named "Gal1" reads as
    "gall" and sits one glyph away from a Traveler named "Gal" ("gal"). An OCR
    pass that drops the trailing "1" would otherwise silently assign that
    Manekin's gear and stats to the Traveler. This codebase refuses
    rather than guesses, so any read that could be two named characters is
    refused with a message naming both, instead of being handed to one of
    them.
    """
    # (role, display-name-as-configured, normalised). Entries whose normalised
    # form is empty (e.g. a settings field made of nothing but "-"/spaces)
    # can never match a probe and are dropped.
    configured: list[tuple[str, str, str]] = []
    for role, display in (("Traveler", traveler_name), ("Wanderer", wanderer_name)):
        norm = normalise(display)
        if norm:
            configured.append((role, display, norm))
    for other in (part.strip() for part in other_names.split(",") if part.strip()):
        norm = normalise(other)
        if norm:
            configured.append(("other", other, norm))

    probe = normalise(text)
    if not probe:
        return "", ""

    exact = [(r, d, n) for r, d, n in configured if n == probe]
    if not exact:
        return "", ""
    near = [(r, d, n) for r, d, n in configured
            if n != probe and _within_one_edit(probe, n)]
    exact_role, exact_display, _ = exact[0]

    if near:
        # The probe could be the exact-named character *or* a slightly mangled
        # read of the near one; neither can be ruled out. Refuse, naming both.
        _, near_display, _ = near[0]
        return exact_role, (
            f"{text!r} could be the {exact_role} {exact_display!r} or "
            f"{near_display!r}, which is one dropped glyph away; such names "
            f"cannot be told apart reliably -- rename one of them in-game or "
            f"in settings")

    if len(exact) > 1:
        # Two *configured* names normalise identically (say the Traveler and a
        # Manekin are both "Gal"): even an exact read is then ambiguous
        # between two distinct characters, so refuse rather than hand it to
        # whichever is listed first.
        _, dup_display, _ = exact[1]
        return exact_role, (
            f"{text!r} could be the {exact_role} {exact_display!r} or the "
            f"other configured name {dup_display!r} -- the two normalise to "
            f"the same string and cannot be told apart reliably; rename one "
            f"of them in-game or in settings")

    return exact_role, ""


# A score is a *ratio*, so the same single mangled glyph costs far more on a
# short name than a long one -- one bad letter in "Qiqi" is 25 points, in a
# ten-letter name 10 -- and a flat floor is therefore much stricter on short
# names than long ones for no principled reason. Rather than lower the floor
# (which admits real wrong answers: measured over 768 simulated one-glyph
# errors on real character names, dropping it to 70 doubled the wrong matches
# from 6 to 13), a near-miss is accepted only when the runner-up is far behind,
# which is what distinguishes "the OCR smudged one letter" from "two real names
# look alike". Measured on the same 768 cases this recovers 16 of 38 refusals
# and adds *zero* wrong matches; on the denser weapon/artifact/material
# vocabularies it changes nothing at all, because a crowded field never leaves
# a gap this wide.
NEAR_FLOOR = 68.0
NEAR_MARGIN = 8.0


@dataclass(slots=True)
class Match:
    key: str
    name: str
    score: float
    ok: bool


class Vocabulary:
    """A searchable set of display names for one game category."""

    def __init__(self, items: list[dict]) -> None:
        self.items = items
        self._by_norm: dict[str, dict] = {}
        for it in items:
            self._by_norm.setdefault(normalise(it["name"]), it)
        self._choices = list(self._by_norm)

    def __len__(self) -> int:
        return len(self.items)

    def match(self, text: str, *, floor: float = 78.0) -> Match:
        probe = normalise(text)
        if not probe:
            return Match("", "", 0.0, False)
        if probe in self._by_norm:  # exact hit, skip the fuzzy pass
            it = self._by_norm[probe]
            return Match(it["key"], it["name"], 100.0, True)

        if _HAVE_RF:
            got = process.extract(probe, self._choices, scorer=fuzz.WRatio, limit=2)
            cand, score = (got[0][0], got[0][1]) if got else ("", 0.0)
            runner = got[1][1] if len(got) > 1 else 0.0
        else:
            close = difflib.get_close_matches(probe, self._choices, n=2, cutoff=0.0)
            cand = close[0] if close else ""
            score = (
                difflib.SequenceMatcher(None, probe, cand).ratio() * 100.0 if cand else 0.0
            )
            runner = (difflib.SequenceMatcher(None, probe, close[1]).ratio() * 100.0
                      if len(close) > 1 else 0.0)

        if not cand:
            return Match("", "", 0.0, False)
        it = self._by_norm[cand]
        return Match(it["key"], it["name"], float(score),
                     score >= floor or (score >= NEAR_FLOOR
                                        and score - runner >= NEAR_MARGIN))


@lru_cache(maxsize=None)
def _load(name: str) -> Vocabulary:
    raw = json.loads((GAMEDATA / f"{name}.json").read_text())
    items = raw["items"]
    if items and isinstance(items[0], str):  # locations.json is a plain list
        items = [{"key": k, "name": k} for k in items]
    return Vocabulary(items)


def characters() -> Vocabulary:
    return _load("characters")


def weapons() -> Vocabulary:
    return _load("weapons")


def artifact_sets() -> Vocabulary:
    return _load("artifact_sets")


def materials() -> Vocabulary:
    return _load("materials")


def locations() -> Vocabulary:
    return _load("locations")


def backend() -> str:
    return "rapidfuzz" if _HAVE_RF else "difflib (install python-rapidfuzz)"
