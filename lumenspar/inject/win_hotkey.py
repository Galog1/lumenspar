"""Windows Escape watcher (GetAsyncKeyState poll).

The Linux watcher (inject/hotkey.py) reads /dev/input, which does not exist
on Windows; the equivalent is GetAsyncKeyState(VK_ESCAPE). Same interface:
alive only while a scan runs, polls every 25 ms in a daemon thread and calls
`on_escape` once per key press (edge-triggered). The polling function is
injectable so tests can drive it without a real key state.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

VK_ESCAPE = 0x1B
POLL_INTERVAL = 0.025


def _escape_down(vk: int) -> bool:
    """True while the key is held down (GetAsyncKeyState's high bit)."""
    import ctypes

    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class WinEscapeWatcher:
    """Calls `on_escape` once per Escape press, until stop() is called."""

    def __init__(
        self,
        on_escape: Callable[[], None],
        poll: Callable[[int], bool] | None = None,
    ) -> None:
        self._on_escape = on_escape
        self._poll = poll or _escape_down
        self._thread: threading.Thread | None = None
        self._running = False
        self._held = False

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> int:
        if self._thread is not None:
            return 1
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="lumenspar-esc", daemon=True
        )
        self._thread.start()
        return 1

    def _loop(self) -> None:
        while self._running:
            down = self._poll(VK_ESCAPE)
            if down and not self._held:
                self._on_escape()
            self._held = down
            time.sleep(POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False
        t, self._thread = self._thread, None
        if t is not None:
            t.join(timeout=1.0)
