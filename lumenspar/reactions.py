"""Which elemental reactions a team can trigger (pure helpers, no engine calls)."""

from __future__ import annotations

ELEMENTS = ("pyro", "hydro", "electro", "cryo", "anemo", "geo", "dendro")

_LABELS = {
    "overloaded": "Overloaded", "electrocharged": "Electro-Charged",
    "lunarcharged": "Lunar-Charged", "superconduct": "Superconduct",
    "shattered": "Shattered", "burning": "Burning", "bloom": "Bloom",
    "hyperbloom": "Hyperbloom", "burgeon": "Burgeon", "lunarbloom": "Lunar-Bloom",
    "lunarcrystallize": "Lunar-Crystallize", "crystallize": "Crystallize (shield)",
}


def team_elements(elements: list[str]) -> set[str]:
    """The elements of a team, lower-cased, without blanks."""
    return {e.lower() for e in elements if e}


def amp_options(element: str, team: set[str]) -> list[str]:
    """The amplifying / catalyze reactions a character of `element` can cause in `team`."""
    out = []
    if element in ("pyro", "hydro") and {"pyro", "hydro"} <= team:
        out.append("vaporize")
    if element in ("pyro", "cryo") and {"pyro", "cryo"} <= team:
        out.append("melt")
    if element == "electro" and "dendro" in team:
        out.append("aggravate")
    if element == "dendro" and "electro" in team:
        out.append("spread")
    return out


def reaction_row_allowed(name: str, element: str, team: set[str]) -> bool:
    """Whether a transformative / Lunar damage row applies to this member in this team."""
    def both(elements: tuple[str, ...], pair: set[str]) -> bool:
        return element in elements and pair <= team

    if name == "overloaded":
        return both(("pyro", "electro"), {"pyro", "electro"})
    if name == "superconduct":
        return both(("electro", "cryo"), {"electro", "cryo"})
    if name in ("electrocharged", "lunarcharged"):
        return both(("electro", "hydro"), {"electro", "hydro"})
    if name == "shattered":
        return {"cryo", "hydro"} <= team
    if name.startswith("swirl_"):
        return element == "anemo" and name[len("swirl_"):] in team
    if name == "burning":
        return both(("pyro", "dendro"), {"pyro", "dendro"})
    if name in ("bloom", "lunarbloom"):
        return both(("hydro", "dendro"), {"hydro", "dendro"})
    if name == "hyperbloom":
        return both(("electro",), {"hydro", "dendro"})
    if name == "burgeon":
        return both(("pyro",), {"hydro", "dendro"})
    if name in ("crystallize", "lunarcrystallize"):
        return element == "geo" and bool(team & {"pyro", "hydro", "electro", "cryo"})
    return True


def reaction_label(name: str) -> str | None:
    """A readable name for a transformative / Lunar row, or None for any other row."""
    if name in _LABELS:
        return _LABELS[name]
    if name.startswith("swirl_") and name[len("swirl_"):] in ELEMENTS:
        return f"Swirl ({name[len('swirl_'):].capitalize()})"
    return None
