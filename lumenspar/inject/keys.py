"""evdev keycodes.

Games read raw scancodes rather than translated keysyms, so injection is done
with evdev codes (as in `linux/input-event-codes.h`) -- a keysym-based press
often never reaches a Wine-hosted game at all.
"""

from __future__ import annotations

KEY: dict[str, int] = {
    "escape": 1, "esc": 1,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6,
    "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "minus": 12, "equal": 13, "backspace": 14, "tab": 15,
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20,
    "y": 21, "u": 22, "i": 23, "o": 24, "p": 25,
    "enter": 28, "return": 28, "leftctrl": 29,
    "a": 30, "s": 31, "d": 32, "f": 33, "g": 34,
    "h": 35, "j": 36, "k": 37, "l": 38,
    "leftshift": 42,
    "z": 44, "x": 45, "c": 46, "v": 47, "b": 48,
    "n": 49, "m": 50,
    "leftalt": 56, "space": 57,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63,
    "f6": 64, "f7": 65, "f8": 66, "f9": 67, "f10": 68,
    "up": 103, "left": 105, "right": 106, "down": 108,
}

BTN_LEFT = 0x110
BTN_RIGHT = 0x111


def keycode(name: str) -> int:
    """Resolve a config keybind string to an evdev keycode."""
    k = name.strip().lower()
    if k not in KEY:
        raise KeyError(f"unknown key {name!r}; expected one of {sorted(KEY)[:12]}...")
    return KEY[k]
