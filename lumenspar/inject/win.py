"""Windows input injection through SendInput.

Games read hardware scancodes rather than translated keysyms, so keys are
sent with KEYEVENTF_SCANCODE and mapped from the evdev codes in `keys.py` to
PS/2 set-1 scancodes (arrows carry the E0 prefix via KEYEVENTF_EXTENDEDKEY).
Mouse moves are normalised to SendInput's 0..65535 space over the virtual
desktop.

The ctypes structs are plain C layouts and safe to define on any platform;
only the `ctypes.windll` lookups are Windows-only, and they happen lazily
inside methods so this module imports and unit-tests cleanly on Linux.
"""

from __future__ import annotations

import ctypes

from .. import hostos
from .base import InjectBackend, InjectError
from .keys import BTN_LEFT, BTN_RIGHT

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUT_UNION)]


# evdev code (keys.KEY) -> (PS/2 set-1 make scancode, extended flag).
SCANCODES: dict[int, tuple[int, bool]] = {
    1: (0x01, False),   2: (0x02, False),   3: (0x03, False),
    4: (0x04, False),   5: (0x05, False),   6: (0x06, False),
    7: (0x07, False),   8: (0x08, False),   9: (0x09, False),
    10: (0x0A, False),  11: (0x0B, False),  12: (0x0C, False),
    13: (0x0D, False),  14: (0x0E, False),  15: (0x0F, False),
    16: (0x10, False),  17: (0x11, False),  18: (0x12, False),
    19: (0x13, False),  20: (0x14, False),  21: (0x15, False),
    22: (0x16, False),  23: (0x17, False),  24: (0x18, False),
    25: (0x19, False),  28: (0x1C, False),  29: (0x1D, False),
    30: (0x1E, False),  31: (0x1F, False),  32: (0x20, False),
    33: (0x21, False),  34: (0x22, False),  35: (0x23, False),
    36: (0x24, False),  37: (0x25, False),  38: (0x26, False),
    42: (0x2A, False),  44: (0x2C, False),  45: (0x2D, False),
    46: (0x2E, False),  47: (0x2F, False),  48: (0x30, False),
    49: (0x31, False),  50: (0x32, False),  56: (0x38, False),
    57: (0x39, False),  59: (0x3B, False),  60: (0x3C, False),
    61: (0x3D, False),  62: (0x3E, False),  63: (0x3F, False),
    64: (0x40, False),  65: (0x41, False),  66: (0x42, False),
    67: (0x43, False),  68: (0x44, False),
    103: (0x48, True),  105: (0x4B, True),  106: (0x4D, True),
    108: (0x50, True),
}


def scancode(evdev_code: int) -> tuple[int, bool]:
    """PS/2 set-1 (scancode, extended flag) for an evdev code from keys.KEY."""
    try:
        return SCANCODES[evdev_code]
    except KeyError:
        raise KeyError(f"no Windows scancode for evdev code {evdev_code}") from None


def normalise(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    """Map a pixel point on a w×h screen into SendInput's 0..65535 range.

    (0, 0) maps to (0, 0) and (width, height) to (65535, 65535); fractions
    are truncated with int(), the same rounding UinputInject uses.
    """
    dx = int(x / max(1, width) * 65535)
    dy = int(y / max(1, height) * 65535)
    return max(0, min(65535, dx)), max(0, min(65535, dy))


def is_admin() -> bool:
    """True when the process runs elevated (shell32.IsUserAnAdmin)."""
    if not hostos.is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


class WinInject(InjectBackend):
    """Keyboard + mouse via SendInput (hardware scancodes, normalised mouse)."""

    name = "win"

    def __init__(self, screen: tuple[int, int] | None = None) -> None:
        self.screen = screen or (1920, 1080)
        self._user32 = None

    @staticmethod
    def available() -> bool:
        return hostos.is_windows()

    def set_screen(self, width: int, height: int) -> None:
        """Absolute coordinates are scaled against this, so keep it in sync."""
        self.screen = (max(1, width), max(1, height))

    def _api(self):
        if self._user32 is None:
            self._user32 = ctypes.windll.user32
        return self._user32

    def start(self) -> None:
        if self._user32 is not None:
            return
        if not hostos.is_windows():
            raise InjectError("WinInject is only available on Windows")
        self._api()

    def stop(self) -> None:
        pass

    def _send_input(self, inp: INPUT) -> None:
        sent = self._api().SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        if sent != 1:
            raise InjectError(
                "SendInput failed -- the game or another window is blocking input"
            )

    def _key(self, code: int, pressed: bool) -> None:
        try:
            scan, extended = SCANCODES[code]
        except KeyError:
            raise InjectError(f"no Windows scancode for evdev code {code}") from None
        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0)
        if not pressed:
            flags |= KEYEVENTF_KEYUP
        ki = KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=None)
        self._send_input(INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=ki)))

    def _button(self, code: int, pressed: bool) -> None:
        if code == BTN_LEFT:
            flag = MOUSEEVENTF_LEFTDOWN if pressed else MOUSEEVENTF_LEFTUP
        elif code == BTN_RIGHT:
            flag = MOUSEEVENTF_RIGHTDOWN if pressed else MOUSEEVENTF_RIGHTUP
        else:
            raise InjectError(f"unsupported button {code:#x}")
        self._send_mouse(0, 0, 0, flag)

    def _send_mouse(self, dx: int, dy: int, data: int, flags: int) -> None:
        mi = MOUSEINPUT(dx=dx, dy=dy, mouseData=data, dwFlags=flags,
                        time=0, dwExtraInfo=None)
        self._send_input(INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=mi)))

    def move_abs(self, x: float, y: float) -> None:
        width, height = self.screen
        nx, ny = normalise(x, y, width, height)
        self._send_mouse(nx, ny, 0,
                         MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
                         | MOUSEEVENTF_MOVE)

    def scroll(self, clicks: int) -> None:
        """Positive scrolls up, negative scrolls down (as a real wheel does)."""
        clicks = int(clicks)
        if clicks:
            self._send_mouse(0, 0, clicks * 120, MOUSEEVENTF_WHEEL)
