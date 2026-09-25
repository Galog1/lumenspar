"""ydotool/uinput injection.

Works on any compositor because it creates a real kernel input device, so the
events are indistinguishable from a physical keyboard. Needs `ydotoold`
running; on this machine that works without root because the user is in the
`input` group and /dev/uinput is group-writable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

from .base import InjectBackend, InjectError

SOCKET = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "lumenspar-ydotool.sock"
)


class YdotoolInject(InjectBackend):
    name = "ydotool"

    def __init__(self, socket: str = SOCKET) -> None:
        self.socket = socket
        self._daemon: subprocess.Popen | None = None

    @staticmethod
    def available() -> bool:
        return shutil.which("ydotool") is not None and shutil.which("ydotoold") is not None

    def start(self) -> None:
        if self._daemon is not None:
            return
        if not self.available():
            raise InjectError("ydotool/ydotoold not installed")
        if not os.access("/dev/uinput", os.W_OK):
            raise InjectError(
                "/dev/uinput is not writable; add your user to the 'input' group"
            )
        self._daemon = subprocess.Popen(
            ["ydotoold", f"--socket-path={self.socket}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(50):  # wait for the socket to appear
            if os.path.exists(self.socket):
                time.sleep(0.15)  # let the virtual device settle
                return
            time.sleep(0.1)
        raise InjectError("ydotoold did not create its socket")

    def _run(self, *args: str) -> None:
        env = {**os.environ, "YDOTOOL_SOCKET": self.socket}
        r = subprocess.run(["ydotool", *args], env=env,
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise InjectError(f"ydotool {args[0]} failed: {r.stderr.strip()[:160]}")

    def _key(self, code: int, pressed: bool) -> None:
        self._run("key", f"{code}:{1 if pressed else 0}")

    def _button(self, code: int, pressed: bool) -> None:
        # ydotool click codes: 0x00 left down/up handled via `click`
        self._run("click", "0xC0" if pressed else "0x00")

    def move_abs(self, x: float, y: float) -> None:
        self._run("mousemove", "--absolute", "-x", str(int(x)), "-y", str(int(y)))

    def stop(self) -> None:
        if self._daemon is not None:
            self._daemon.terminate()
            try:
                self._daemon.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._daemon.kill()
            self._daemon = None
        if os.path.exists(self.socket):
            try:
                os.unlink(self.socket)
            except OSError:
                pass
