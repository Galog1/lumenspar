"""Capture backend interface.

A backend yields full-screen frames as HxWx3 uint8 BGR numpy arrays, at the
monitor's *native* pixel resolution -- never the compositor's logical/scaled
size. Every layout region in `lumenspar.scan.layout` is expressed as a
fraction of the native frame, so a scaled 4K panel and a true 1440p panel
resolve to the same normalised coordinates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class CaptureError(RuntimeError):
    """Raised when a backend cannot start or deliver frames."""


class CaptureBackend(ABC):
    """Source of native-resolution screen frames."""

    name: str = "base"

    @abstractmethod
    def start(self) -> None:
        """Acquire permission and begin streaming. Idempotent."""

    @abstractmethod
    def grab(self, timeout: float = 2.0) -> np.ndarray:
        """Return the most recent frame as HxWx3 uint8 BGR."""

    @abstractmethod
    def stop(self) -> None:
        """Release the stream and any portal session."""

    @property
    @abstractmethod
    def size(self) -> tuple[int, int]:
        """Native (width, height) of the captured stream."""

    def __enter__(self) -> "CaptureBackend":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
