"""A global Escape watcher, used only to abort a running scan.

While a scan is running the game holds the keyboard focus, so the Stop button
in the window cannot be reached without alt-tabbing. Escape is the natural
abort: it also closes Genshin's inventory, so one press stops both.

Scope is deliberately narrow. The watcher is only alive during a scan, it only
ever tests for KEY_ESC, and it neither stores nor forwards any other key. It
reads `/dev/input` directly because a compositor will not hand out Escape as a
global shortcut, and the user is already in the `input` group.
"""

from __future__ import annotations

import os
import re
import select
import struct
import threading
from typing import Callable

EV_KEY = 0x01
KEY_ESC = 1
_FORMAT = "llHHi"
_SIZE = struct.calcsize(_FORMAT)

# Never listen to our own synthetic keyboard.
_OWN_DEVICE = "Lumenspar"


def keyboard_devices() -> list[str]:
    """Event nodes that carry a keyboard handler, excluding our own."""
    found: list[str] = []
    try:
        blocks = open("/proc/bus/input/devices").read().split("\n\n")
    except OSError:
        return found
    for block in blocks:
        if _OWN_DEVICE in block:
            continue
        handlers = [ln for ln in block.splitlines() if ln.startswith("H: ")]
        if not handlers or "kbd" not in handlers[0]:
            continue
        m = re.search(r"(event\d+)", handlers[0])
        if m:
            path = "/dev/input/" + m.group(1)
            if os.access(path, os.R_OK):
                found.append(path)
    return found


class EscapeWatcher:
    """Calls `on_escape` once, the first time Escape is pressed."""

    def __init__(self, on_escape: Callable[[], None]) -> None:
        self._on_escape = on_escape
        self._fds: list[int] = []
        self._thread: threading.Thread | None = None
        self._running = False

    @property
    def active(self) -> bool:
        return bool(self._fds)

    def start(self) -> int:
        if self._thread is not None:
            return len(self._fds)
        for path in keyboard_devices():
            try:
                self._fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                continue
        if not self._fds:
            return 0
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="lumenspar-esc", daemon=True
        )
        self._thread.start()
        return len(self._fds)

    def _loop(self) -> None:
        while self._running:
            try:
                ready, _, _ = select.select(self._fds, [], [], 0.2)
            except OSError:
                return
            for fd in ready:
                try:
                    data = os.read(fd, _SIZE * 32)
                except OSError:
                    continue
                for off in range(0, len(data) - _SIZE + 1, _SIZE):
                    _, _, etype, code, value = struct.unpack_from(
                        _FORMAT, data, off
                    )
                    # Key-down on Escape only; everything else is ignored.
                    if etype == EV_KEY and code == KEY_ESC and value == 1:
                        self._running = False
                        self._on_escape()
                        return

    def stop(self) -> None:
        self._running = False
        t, self._thread = self._thread, None
        if t is not None:
            t.join(timeout=1.0)
        for fd in self._fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds = []
