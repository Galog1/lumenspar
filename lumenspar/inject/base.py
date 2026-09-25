"""Input injection interface."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from .keys import BTN_LEFT, keycode


class InjectError(RuntimeError):
    pass


class InjectBackend(ABC):
    """Synthesises keyboard and pointer input for the focused window."""

    name = "base"

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def _key(self, code: int, pressed: bool) -> None: ...

    @abstractmethod
    def _button(self, code: int, pressed: bool) -> None: ...

    @abstractmethod
    def move_abs(self, x: float, y: float) -> None:
        """Move the pointer to absolute screen coordinates, in pixels."""

    # -- convenience -----------------------------------------------------

    def tap(self, key: str, hold: float = 0.04) -> None:
        code = keycode(key)
        self._key(code, True)
        time.sleep(hold)
        self._key(code, False)

    def click(self, x: float | None = None, y: float | None = None,
              hold: float = 0.04) -> None:
        if x is not None and y is not None:
            self.move_abs(x, y)
            time.sleep(0.02)
        self._button(BTN_LEFT, True)
        time.sleep(hold)
        self._button(BTN_LEFT, False)

    def __enter__(self) -> "InjectBackend":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
