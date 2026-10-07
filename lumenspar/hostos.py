"""Host platform detection, centralised so tests can monkeypatch it.

Everything Windows-specific in this package branches on `is_windows()` rather
than checking `sys.platform` inline, and reads the helper through this module
(`hostos.is_windows()`) so a test can flip the platform to Windows on a Linux
machine by patching the one attribute.
"""

from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"


def is_windows() -> bool:
    return IS_WINDOWS
