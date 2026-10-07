"""GDI screen capture on Windows via mss (BitBlt, pure ctypes).

mss has no compiled native part, so this module imports anywhere; only the
`mss.mss()` object is created at runtime, on Windows, where Lumenspar uses
this backend instead of the Wayland portal.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .base import CaptureBackend, CaptureError


def bgra_to_bgr(shot: Any) -> np.ndarray:
    """Convert an mss ScreenShot (raw BGRA bytes) to a contiguous BGR frame."""
    arr = np.frombuffer(shot.raw, dtype=np.uint8)
    return np.ascontiguousarray(arr.reshape(shot.height, shot.width, 4)[:, :, :3])


def _open_mss() -> Any:
    """Instantiate mss, raising CaptureError with a readable message if absent."""
    try:
        import mss
    except ImportError:
        raise CaptureError(
            "mss is not installed -- the Windows build of Lumenspar ships it, "
            "so a missing mss usually means a broken install"
        ) from None
    try:
        return mss.mss()
    except Exception as exc:  # noqa: BLE001 - surface any mss startup failure
        raise CaptureError(f"could not open the screen: {exc}") from exc


class MssCapture(CaptureBackend):
    """BitBlts one monitor into an HxWx3 uint8 BGR frame, native resolution."""

    name = "mss"

    def __init__(self, monitor: int = 1, mss: Any = None) -> None:
        # Index into mss.monitors; monitors[0] is the virtual desktop and
        # monitors[1:] are the physical ones, so 1 is the primary.
        self.monitor = monitor
        self._mss = mss            # injectable for tests
        self._monitor: dict | None = None
        self._size: tuple[int, int] = (0, 0)

    def start(self) -> None:
        if self._monitor is not None:
            return
        if self._mss is None:
            self._mss = _open_mss()
        try:
            self._monitor = self._mss.monitors[self.monitor]
        except IndexError:
            raise CaptureError(
                f"monitor {self.monitor} not found "
                f"(mss reports {len(self._mss.monitors) - 1} physical monitors)"
            ) from None
        self._size = (self._monitor["width"], self._monitor["height"])

    def monitor_rect(self) -> tuple[int, int, int, int]:
        """(left, top, width, height) of the captured monitor, physical pixels."""
        if self._monitor is None:
            raise CaptureError("capture not started")
        m = self._monitor
        return m["left"], m["top"], m["width"], m["height"]

    def virtual_rect(self) -> tuple[int, int, int, int]:
        """(left, top, width, height) of the union of every monitor."""
        if self._mss is None:
            raise CaptureError("capture not started")
        m = self._mss.monitors[0]
        return m["left"], m["top"], m["width"], m["height"]

    def grab(self, timeout: float = 2.0) -> np.ndarray:
        if self._monitor is None:
            raise CaptureError("capture not started")
        try:
            shot = self._mss.grab(self._monitor)
        except Exception as exc:  # noqa: BLE001 - surface any mss failure
            raise CaptureError(f"screen grab failed: {exc}") from exc
        frame = bgra_to_bgr(shot)
        if not frame.any():
            raise CaptureError(
                "captured an all-black frame -- run Genshin in Windowed "
                "Fullscreen (borderless) so Windows lets BitBlt see it"
            )
        h, w = frame.shape[:2]
        self._size = (w, h)
        return frame

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    def stop(self) -> None:
        if self._mss is not None:
            close = getattr(self._mss, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - best effort
                    pass
            self._mss = None
            self._monitor = None
