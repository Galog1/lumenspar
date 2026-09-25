"""Inventory tab navigation.

Genshin binds Q and E to "previous/next tab", which is far more reliable than
clicking icons whose positions shift with resolution.

Position is established by *homing* to the leftmost tab (Weapons) and then
stepping right. Homing presses Q one step at a time and checks the header after
each press, rather than pressing it a dozen times and assuming the game clamps
at the end -- if Q instead wraps around to the last tab, blind presses would
land somewhere unpredictable. Checking costs a fraction of a second per step
and removes the assumption entirely.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

# Left to right, as the game lays them out.
TAB_ORDER: tuple[str, ...] = (
    "weapons",            # weapons, followed by weapon enhancement ores
    "artifacts",
    "levelup",            # character/weapon ascension, talent books, EXP
    "food",
    "world",              # open-world gathering materials
)
TAB_INDEX = {name: i for i, name in enumerate(TAB_ORDER)}

# The tab title shown top-left, used to confirm every move. Matched loosely:
# OCR clips the longest of them ("Character Developme Items").
TAB_TITLE: dict[str, str] = {
    "weapons": "weapons",
    "artifacts": "artifacts",
    "levelup": "character developm",
    "food": "food",
    "world": "materials",
}

HOME_LIMIT = 14  # more steps than there are tabs; a safety stop, not a target


def goto_tab(
    target: str,
    tap: Callable[[str], None],
    grab: Callable[[], np.ndarray],
    sleep: Callable[[float], None],
    read_title: Callable[[np.ndarray], str],
    log: Callable[[str], None] = lambda _m: None,
    step_delay: float = 0.35,
    key_left: str = "q",
    key_right: str = "e",
    should_stop: Callable[[], bool] = lambda: False,
) -> bool:
    """Move to `target`. Returns False if the position could not be established."""
    if target not in TAB_INDEX:
        log(f"error: unknown tab {target!r}")
        return False

    def where() -> str | None:
        title = read_title(grab()).lower()
        for name, needle in TAB_TITLE.items():
            if needle in title:
                return name
        return None

    here = where()
    if here == target:
        log(f"  already on the {target} tab")
        return True

    # Home on Weapons, confirming after each step. Stepping one at a time
    # avoids assuming the tab strip clamps rather than wraps at its ends.
    steps = 0
    while here != "weapons":
        if should_stop() or steps >= HOME_LIMIT:
            log(f"error: could not reach the leftmost tab "
                f"(currently {here or 'unrecognised'})")
            return False
        tap(key_left)
        sleep(step_delay)
        here = where()
        steps += 1
    if steps:
        log(f"  homed to weapons in {steps} step(s)")

    for _ in range(TAB_INDEX[target]):
        if should_stop():
            return False
        tap(key_right)
        sleep(step_delay)
    sleep(step_delay)

    here = where()
    if here == target:
        log(f"  on the {target} tab")
        return True
    log(f"error: expected the {target} tab but landed on "
        f"{here or 'an unrecognised tab'}")
    return False
