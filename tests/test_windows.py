"""Windows-only code paths, exercised on Linux.

Everything here imports the production modules under test; nothing touches
`ctypes.windll` (only reachable inside functions that are never called here,
on a non-Windows host). Platform branching is driven by
`lumenspar.hostos.is_windows()`, so tests monkeypatch that one helper.
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from lumenspar import hostos
from lumenspar.capture.win import MssCapture, bgra_to_bgr
from lumenspar.capture.base import CaptureError
from lumenspar.config import Settings, _config_roots
from lumenspar.inject.keys import KEY
from lumenspar.inject.win import (
    INPUT, KEYBDINPUT, MOUSEINPUT, SCANCODES, normalise, scancode,
)
from lumenspar.inject.win_hotkey import VK_ESCAPE, WinEscapeWatcher


# -- scancode table -----------------------------------------------------

def test_scancodes_cover_every_key():
    missing = sorted({KEY[k] for k in KEY} - set(SCANCODES))
    assert not missing


def test_arrow_scancodes_carry_extended_flag():
    assert scancode(KEY["up"]) == (0x48, True)
    assert scancode(KEY["down"]) == (0x50, True)
    assert scancode(KEY["left"]) == (0x4B, True)
    assert scancode(KEY["right"]) == (0x4D, True)


def test_scancode_values():
    assert scancode(KEY["esc"]) == (0x01, False)
    assert scancode(KEY["1"]) == (0x02, False)
    assert scancode(KEY["0"]) == (0x0B, False)
    assert scancode(KEY["minus"]) == (0x0C, False)
    assert scancode(KEY["backspace"]) == (0x0E, False)
    assert scancode(KEY["tab"]) == (0x0F, False)
    assert scancode(KEY["enter"]) == (0x1C, False)
    assert scancode(KEY["leftctrl"]) == (0x1D, False)
    assert scancode(KEY["leftshift"]) == (0x2A, False)
    assert scancode(KEY["leftalt"]) == (0x38, False)
    assert scancode(KEY["space"]) == (0x39, False)
    assert scancode(KEY["f1"]) == (0x3B, False)
    assert scancode(KEY["f10"]) == (0x44, False)
    assert scancode(KEY["a"]) == (0x1E, False)
    assert scancode(KEY["z"]) == (0x2C, False)
    assert scancode(KEY["m"]) == (0x32, False)


def test_scancode_unknown_raises():
    with pytest.raises(KeyError):
        scancode(9999)


# -- mouse normalisation -------------------------------------------------

def test_normalise_corners_and_center():
    assert normalise(0, 0, 1920, 1080) == (0, 0)
    assert normalise(1920, 1080, 1920, 1080) == (65535, 65535)
    x, y = normalise(960, 540, 1920, 1080)
    assert (x, y) == (32767, 32767)  # int() truncation, as documented
    assert normalise(-10, 99999, 100, 100) == (0, 65535)  # clamped


# -- SendInput structs ---------------------------------------------------

def test_input_struct_layout():
    assert {n for n, _ in INPUT._fields_} == {"type", "u"}
    assert {n for n, _ in KEYBDINPUT._fields_} == {
        "wVk", "wScan", "dwFlags", "time", "dwExtraInfo"}
    assert {n for n, _ in MOUSEINPUT._fields_} == {
        "dx", "dy", "mouseData", "dwFlags", "time", "dwExtraInfo"}
    # 40 on Windows x64 (the target), 56 on 64-bit Linux where the ctypes
    # longs standing in for DWORD/LONG are 8 bytes. Either layout carries
    # the fields; the exact size depends on the platform's data model.
    assert ctypes.sizeof(INPUT) in (24, 40, 56)


# -- Escape watcher ------------------------------------------------------

class _KeyState:
    """Fake GetAsyncKeyState: plays back a script of key states."""

    def __init__(self, states: list[bool]) -> None:
        self.states = states
        self.calls = 0

    def __call__(self, vk: int) -> bool:
        self.calls += 1
        assert vk == VK_ESCAPE
        if self.states:
            return self.states.pop(0)
        return False


def test_win_escape_watcher_fires_once_per_press():
    fired: list[int] = []
    # Press (held a while), release, press again.
    keys = _KeyState([False, False, True, True, True, False, False, False,
                      True, False])
    w = WinEscapeWatcher(lambda: fired.append(1), poll=keys)
    assert w.start() == 1
    deadline = time.monotonic() + 5
    while len(fired) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    w.stop()
    assert fired == [1, 1], "exactly one callback per press"


def test_win_escape_watcher_inactive_after_stop():
    w = WinEscapeWatcher(lambda: None, poll=lambda vk: False)
    assert not w.active
    assert w.start() == 1
    assert w.active
    w.stop()
    assert not w.active


# -- mss capture ----------------------------------------------------------

class _FakeShot:
    def __init__(self, raw: bytes, width: int, height: int) -> None:
        self.raw = raw
        self.width = width
        self.height = height


class _FakeMss:
    monitors = [
        {"left": 0, "top": 0, "width": 2000, "height": 1200},   # virtual
        {"left": 0, "top": 0, "width": 1920, "height": 1080},   # primary
    ]

    def grab(self, monitor):
        # BGRA: red, green, blue, white -- one pixel each.
        raw = bytes([0, 0, 255, 255,   0, 255, 0, 255,
                     255, 0, 0, 255,   255, 255, 255, 255])
        return _FakeShot(raw, 2, 2)

    def close(self):
        pass


def test_bgra_to_bgr():
    shot = _FakeShot(bytes([0, 0, 255, 255,   0, 255, 0, 255,
                            255, 0, 0, 255,   255, 255, 255, 255]), 2, 2)
    out = bgra_to_bgr(shot)
    assert out.dtype == np.uint8
    assert out.shape == (2, 2, 3)
    assert out.flags["C_CONTIGUOUS"]
    assert out[0, 0].tolist() == [0, 0, 255]
    assert out[0, 1].tolist() == [0, 255, 0]
    assert out[1, 0].tolist() == [255, 0, 0]
    assert out[1, 1].tolist() == [255, 255, 255]


def test_mss_capture_grab_with_fake():
    cap = MssCapture(monitor=1, mss=_FakeMss())
    cap.start()
    assert cap.monitor_rect() == (0, 0, 1920, 1080)
    assert cap.virtual_rect() == (0, 0, 2000, 1200)
    assert cap.size == (1920, 1080)
    frame = cap.grab(timeout=0.1)
    assert frame.shape == (2, 2, 3)
    assert frame.dtype == np.uint8
    assert frame.flags["C_CONTIGUOUS"]
    assert cap.size == (2, 2)
    cap.stop()


def test_mss_capture_black_frame_raises():
    class BlackMss(_FakeMss):
        def grab(self, monitor):
            return _FakeShot(bytes(2 * 2 * 4), 2, 2)

    cap = MssCapture(monitor=1, mss=BlackMss())
    cap.start()
    with pytest.raises(CaptureError, match="all-black"):
        cap.grab(timeout=0.1)


def test_mss_capture_missing_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "mss", None)
    cap = MssCapture()
    with pytest.raises(CaptureError, match="mss"):
        cap.start()


def test_mss_capture_bad_monitor_index():
    cap = MssCapture(monitor=5, mss=_FakeMss())
    with pytest.raises(CaptureError, match="monitor"):
        cap.start()


# -- Settings, Windows-only ----------------------------------------------

def test_settings_coerces_reader_mode_on_windows(monkeypatch):
    monkeypatch.setattr(hostos, "is_windows", lambda: True)
    assert Settings().reader_mode == "ai"
    assert Settings.from_dict({"reader_mode": "local"}).reader_mode == "ai"


def test_settings_keeps_reader_mode_off_windows():
    s = Settings()
    assert s.reader_mode in ("local", "ai")
    s.reader_mode = "local"
    assert Settings.from_dict({"reader_mode": "local"}).reader_mode == "local"


# -- config roots ---------------------------------------------------------

def test_config_roots_windows_env():
    # APPDATA/LOCALAPPDATA are just directory strings; POSIX-style values
    # keep the assertion readable on any host while exercising the branch.
    cfg, data = _config_roots(True, {
        "APPDATA": "/tmp/appdata",
        "LOCALAPPDATA": "/tmp/localappdata",
    })
    assert cfg == Path("/tmp/appdata") / "lumenspar"
    assert data == Path("/tmp/localappdata") / "lumenspar"


def test_config_roots_windows_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path, raising=False)
    cfg, data = _config_roots(True, {})
    assert cfg == tmp_path / "AppData" / "Roaming" / "lumenspar"
    assert data == tmp_path / "AppData" / "Local" / "lumenspar"


def test_config_roots_linux_unaffected():
    cfg, data = _config_roots(False, {
        "XDG_CONFIG_HOME": "/tmp/cfg",
        "XDG_DATA_HOME": "/tmp/data",
    })
    assert cfg == Path("/tmp/cfg") / "lumenspar"
    assert data == Path("/tmp/data") / "lumenspar"
