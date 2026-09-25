"""Bind capture and input together for a live scan."""

from __future__ import annotations

import time

import numpy as np

from ..capture.base import CaptureBackend
from ..inject.base import InjectBackend


class LiveDriver:
    """Drives the real game: frames from the portal, input through uinput.

    Absolute pointer coordinates address the whole desktop, while frames come
    from a single output, so a click has to be mapped
    frame pixel -> fraction of the output -> logical desktop point -> device
    range. Skipping that middle step puts every click on the primary monitor.
    """

    def __init__(
        self,
        capture: CaptureBackend,
        inject: InjectBackend,
        output_logical: tuple[int, int, int, int],
        desktop_logical: tuple[int, int, int, int],
    ) -> None:
        self.capture = capture
        self.inject = inject
        self.output = output_logical      # x, y, w, h
        self.desktop = desktop_logical    # x, y, w, h
        self._frame_size: tuple[int, int] = (0, 0)

    def grab(self) -> np.ndarray:
        frame = self.capture.grab(timeout=5.0)
        h, w = frame.shape[:2]
        self._frame_size = (w, h)
        return frame

    def _to_desktop(self, x: float, y: float) -> tuple[float, float]:
        fw, fh = self._frame_size
        if not fw or not fh:
            return x, y
        ox, oy, ow, oh = self.output
        return ox + (x / fw) * ow, oy + (y / fh) * oh

    def click(self, x: int, y: int) -> None:
        dx, dy = self._to_desktop(x, y)
        gx, gy, gw, gh = self.desktop
        # move_abs scales against inject.screen, so express the point in the
        # desktop's own coordinate space.
        self.inject.set_screen(gw, gh)          # type: ignore[attr-defined]
        self.inject.click(dx - gx, dy - gy)

    def scroll(self, clicks: int) -> None:
        # Wheel-down is negative, and scrolling down is what advances the grid.
        self.inject.scroll(-abs(int(clicks)))   # type: ignore[attr-defined]

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)
