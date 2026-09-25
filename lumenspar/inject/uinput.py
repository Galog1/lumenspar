"""A virtual input device created directly through /dev/uinput.

ydotool covers keys, absolute motion and clicks, but exposes no wheel command,
and the inventory grid has to be scrolled. Rather than depend on the CLI's
feature set we create our own kernel device: the events are indistinguishable
from a physical keyboard/mouse, it works on every compositor, and it needs no
root here because the user is in the `input` group.

Three devices are created rather than one, because the kernel classifies a
node by the capabilities it advertises:

* keys live on their own node -- a node carrying both keys and absolute axes
  also gets a **joystick** handler (`js0`), and Genshin would then see a
  gamepad and switch away from keyboard control, which this tool requires;
* the absolute pointer declares BTN_TOUCH alongside the buttons, which is what
  stops it being bound as a joystick (verified: ABS+BTN_LEFT yields `js0`,
  ABS+BTN_LEFT+BTN_TOUCH does not);
* the wheel is relative-only, since mixing relative and absolute axes on one
  node is classified inconsistently.
"""

from __future__ import annotations

import ctypes
import fcntl
import os
import struct
import time

from .base import InjectBackend, InjectError
from .keys import BTN_LEFT, BTN_RIGHT, KEY

UINPUT = "/dev/uinput"

EV_SYN, EV_KEY, EV_REL, EV_ABS = 0x00, 0x01, 0x02, 0x03
SYN_REPORT = 0
ABS_X, ABS_Y = 0x00, 0x01
REL_WHEEL, REL_HWHEEL = 0x08, 0x06
BTN_TOUCH = 0x14A
ABS_MAX_VALUE = 65535

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

ABS_CNT = 64
_NAME_LEN = 80


def _user_dev(name: str, absmin=None, absmax=None) -> bytes:
    """Pack a legacy `uinput_user_dev` (widely supported, unlike UI_DEV_SETUP)."""
    buf = bytearray()
    buf += name.encode()[: _NAME_LEN - 1].ljust(_NAME_LEN, b"\0")
    buf += struct.pack("HHHH", 0x03, 0x1234, 0x5678, 1)  # bustype USB, ids
    buf += struct.pack("I", 0)                            # ff_effects_max
    for table in (absmax, absmin, None, None):            # max, min, fuzz, flat
        vals = [0] * ABS_CNT
        if table:
            for axis, v in table.items():
                vals[axis] = v
        buf += struct.pack(f"{ABS_CNT}i", *vals)
    return bytes(buf)


def _event(fd: int, etype: int, code: int, value: int) -> None:
    os.write(fd, struct.pack("llHHi", 0, 0, etype, code, value))


def _syn(fd: int) -> None:
    _event(fd, EV_SYN, SYN_REPORT, 0)


class UinputInject(InjectBackend):
    """Keyboard + absolute pointer + wheel via uinput."""

    name = "uinput"

    def __init__(self, screen: tuple[int, int] | None = None) -> None:
        self.screen = screen or (1920, 1080)
        self._kb: int | None = None       # keys only
        self._ptr: int | None = None      # absolute pointer + buttons
        self._wheel: int | None = None    # relative wheel only

    @staticmethod
    def available() -> bool:
        return os.path.exists(UINPUT) and os.access(UINPUT, os.W_OK)

    def set_screen(self, width: int, height: int) -> None:
        """Absolute coordinates are scaled against this, so keep it in sync."""
        self.screen = (max(1, width), max(1, height))

    def start(self) -> None:
        if self._kb is not None:
            return
        if not self.available():
            raise InjectError(
                f"{UINPUT} is not writable; add your user to the 'input' group"
            )
        self._kb = self._make_keyboard()
        self._ptr = self._make_pointer()
        self._wheel = self._make_wheel()
        # The compositor needs a moment to notice and configure new devices;
        # events sent before that are silently dropped.
        time.sleep(0.4)

    def _make_keyboard(self) -> int:
        fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
            for code in sorted(set(KEY.values())):
                fcntl.ioctl(fd, UI_SET_KEYBIT, code)
            os.write(fd, _user_dev("Lumenspar Keyboard"))
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError as exc:
            os.close(fd)
            raise InjectError(f"could not create uinput keyboard: {exc}") from exc
        return fd

    def _make_pointer(self) -> int:
        fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
            # BTN_TOUCH is what keeps this off the joystick subsystem.
            for btn in (BTN_LEFT, BTN_RIGHT, BTN_TOUCH):
                fcntl.ioctl(fd, UI_SET_KEYBIT, btn)
            for axis in (ABS_X, ABS_Y):
                fcntl.ioctl(fd, UI_SET_ABSBIT, axis)
            os.write(fd, _user_dev(
                "Lumenspar Pointer",
                absmin={ABS_X: 0, ABS_Y: 0},
                absmax={ABS_X: ABS_MAX_VALUE, ABS_Y: ABS_MAX_VALUE},
            ))
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError as exc:
            os.close(fd)
            raise InjectError(f"could not create uinput pointer: {exc}") from exc
        return fd

    def _make_wheel(self) -> int:
        fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
            fcntl.ioctl(fd, UI_SET_KEYBIT, BTN_LEFT)  # else it is not a pointer
            for axis in (REL_WHEEL, REL_HWHEEL):
                fcntl.ioctl(fd, UI_SET_RELBIT, axis)
            os.write(fd, _user_dev("Lumenspar Wheel"))
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except OSError as exc:
            os.close(fd)
            raise InjectError(f"could not create uinput wheel device: {exc}") from exc
        return fd

    # -- InjectBackend ---------------------------------------------------

    def _key(self, code: int, pressed: bool) -> None:
        if self._kb is None:
            raise InjectError("uinput not started")
        _event(self._kb, EV_KEY, code, 1 if pressed else 0)
        _syn(self._kb)

    def _button(self, code: int, pressed: bool) -> None:
        if self._ptr is None:
            raise InjectError("uinput not started")
        _event(self._ptr, EV_KEY, code, 1 if pressed else 0)
        _syn(self._ptr)

    def move_abs(self, x: float, y: float) -> None:
        if self._ptr is None:
            raise InjectError("uinput not started")
        w, h = self.screen
        ax = int(max(0, min(1, x / w)) * ABS_MAX_VALUE)
        ay = int(max(0, min(1, y / h)) * ABS_MAX_VALUE)
        _event(self._ptr, EV_ABS, ABS_X, ax)
        _event(self._ptr, EV_ABS, ABS_Y, ay)
        _syn(self._ptr)

    def scroll(self, clicks: int) -> None:
        """Positive scrolls up, negative scrolls down (as a real wheel does)."""
        if self._wheel is None:
            raise InjectError("uinput not started")
        step = 1 if clicks > 0 else -1
        for _ in range(abs(int(clicks))):
            _event(self._wheel, EV_REL, REL_WHEEL, step)
            _syn(self._wheel)
            time.sleep(0.02)

    def stop(self) -> None:
        for attr in ("_kb", "_ptr", "_wheel"):
            fd = getattr(self, attr)
            if fd is not None:
                try:
                    fcntl.ioctl(fd, UI_DEV_DESTROY)
                except OSError:
                    pass
                os.close(fd)
                setattr(self, attr, None)
