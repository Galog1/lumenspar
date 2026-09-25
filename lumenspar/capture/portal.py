"""xdg-desktop-portal ScreenCast -> PipeWire capture.

This is the sanctioned Wayland capture path and works on KDE, GNOME and
wlroots alike. We ask the portal to persist the grant (`persist_mode=2`) and
cache the returned `restore_token`, so the user sees the screen-picker dialog
once rather than on every scan.

The PipeWire stream is consumed through GStreamer (`pipewiresrc`), which hands
us a continuous feed -- far cheaper per frame than round-tripping a screenshot
IPC call for every one of the hundreds of item tiles a scan inspects.
"""

from __future__ import annotations

import os
import random
from typing import Any, Callable

import numpy as np

import dbus
from dbus.mainloop.glib import DBusGMainLoop

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import GLib, Gst, GstVideo  # noqa: E402

from .base import CaptureBackend, CaptureError

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"

SOURCE_MONITOR = 1
CURSOR_HIDDEN = 1
PERSIST_UNTIL_REVOKED = 2

_gst_ready = False


def _init_gst() -> None:
    global _gst_ready
    if not _gst_ready:
        Gst.init(None)
        _gst_ready = True


def _token() -> str:
    return f"lumenspar_{random.randint(0, 2**31):x}"


class PortalCapture(CaptureBackend):
    """Capture a monitor via the ScreenCast portal and a PipeWire stream."""

    name = "portal"

    def __init__(
        self,
        restore_token: str | None = None,
        on_restore_token: Callable[[str], None] | None = None,
    ) -> None:
        self._restore_token = restore_token
        self._on_restore_token = on_restore_token

        self._bus: dbus.SessionBus | None = None
        self._portal: dbus.Interface | None = None
        self._session_path: str | None = None
        self._pipeline: Gst.Pipeline | None = None
        self._sink: Gst.Element | None = None
        self._size: tuple[int, int] = (0, 0)
        # Logical rect of the captured output within the desktop. Absolute
        # pointer coordinates span the whole desktop, so a frame pixel has to
        # be mapped through this to land on the right monitor.
        self.logical_pos: tuple[int, int] = (0, 0)
        self.logical_size: tuple[int, int] = (0, 0)

    # -- portal request plumbing ----------------------------------------

    def _request_path(self, token: str) -> str:
        assert self._bus is not None
        sender = self._bus.get_unique_name()[1:].replace(".", "_")
        return f"{PORTAL_PATH}/request/{sender}/{token}"

    def _call(self, method: str, *args: Any, **opts: Any) -> dict:
        """Invoke a portal method and block until its Response signal lands.

        Portal methods return immediately with a Request handle; the actual
        result arrives asynchronously, so we subscribe *before* calling to
        avoid racing a fast reply.
        """
        assert self._bus is not None and self._portal is not None
        token = _token()
        opts["handle_token"] = token
        box: dict[str, Any] = {}
        loop = GLib.MainLoop()

        def on_response(code: dbus.UInt32, results: dbus.Dictionary) -> None:
            box["code"] = int(code)
            box["results"] = {str(k): v for k, v in results.items()}
            if loop.is_running():
                loop.quit()

        def on_timeout() -> bool:
            box.setdefault("timeout", True)
            if loop.is_running():
                loop.quit()
            return False  # one-shot

        match = self._bus.add_signal_receiver(
            on_response,
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.Request",
            path=self._request_path(token),
        )
        source = GLib.timeout_add_seconds(180, on_timeout)
        try:
            getattr(self._portal, method)(*args, opts)
            # The blocking call can itself dispatch the Response, so only spin
            # a loop if the reply has not already landed -- otherwise run()
            # would wait for a quit() that has already been issued.
            if "code" not in box:
                loop.run()
        finally:
            GLib.source_remove(source)
            match.remove()

        if box.get("timeout"):
            raise CaptureError(f"portal {method} timed out (no response)")
        if box.get("code") != 0:
            raise CaptureError(
                f"portal {method} was cancelled or denied (code {box.get('code')})"
            )
        return box["results"]

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._pipeline is not None:
            return
        _init_gst()
        DBusGMainLoop(set_as_default=True)

        self._bus = dbus.SessionBus()
        obj = self._bus.get_object(PORTAL_BUS, PORTAL_PATH)
        self._portal = dbus.Interface(obj, SCREENCAST)

        res = self._call("CreateSession", session_handle_token=_token())
        self._session_path = str(res["session_handle"])

        select: dict[str, Any] = {
            "types": dbus.UInt32(SOURCE_MONITOR),
            "multiple": dbus.Boolean(False),
            "cursor_mode": dbus.UInt32(CURSOR_HIDDEN),
            "persist_mode": dbus.UInt32(PERSIST_UNTIL_REVOKED),
        }
        if self._restore_token:
            select["restore_token"] = self._restore_token
        self._call("SelectSources", self._session_path, **select)

        res = self._call("Start", self._session_path, "")
        new_token = res.get("restore_token")
        if new_token and self._on_restore_token:
            self._on_restore_token(str(new_token))

        streams = res.get("streams") or []
        if not streams:
            raise CaptureError("portal returned no streams")
        node_id = int(streams[0][0])
        props = {str(k): v for k, v in streams[0][1].items()}
        if "size" in props:
            # Note: this is the *logical* size, not the pixel size of the
            # frames; grab() overwrites _size from the real buffer.
            self.logical_size = (int(props["size"][0]), int(props["size"][1]))
            self._size = self.logical_size
        if "position" in props:
            self.logical_pos = (int(props["position"][0]), int(props["position"][1]))

        fd = self._portal.OpenPipeWireRemote(
            self._session_path, {}, dbus_interface=SCREENCAST
        )
        self._build_pipeline(fd.take(), node_id)

    def _build_pipeline(self, fd: int, node_id: int) -> None:
        desc = (
            f"pipewiresrc fd={fd} path={node_id} always-copy=true ! "
            "videoconvert ! video/x-raw,format=BGRx ! "
            "appsink name=sink max-buffers=1 drop=true sync=false"
        )
        self._pipeline = Gst.parse_launch(desc)
        self._sink = self._pipeline.get_by_name("sink")
        if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise CaptureError("failed to start PipeWire GStreamer pipeline")

    # -- frames ----------------------------------------------------------

    def _pull(self, timeout: float) -> "Gst.Sample | None":
        """Pull a sample, tolerating a missing gst-python override layer."""
        assert self._sink is not None
        ns = int(timeout * Gst.SECOND)
        try:
            return self._sink.try_pull_sample(ns)
        except AttributeError:
            # Without gst-python's gi overrides the convenience wrappers are
            # absent, but the underlying action signal always exists.
            return self._sink.emit("try-pull-sample", ns)

    def grab(self, timeout: float = 2.0) -> np.ndarray:
        if self._sink is None:
            raise CaptureError("capture not started")
        sample = self._pull(timeout)
        if sample is None:
            raise CaptureError("timed out waiting for a frame")

        info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            raise CaptureError("could not map video frame")
        try:
            w, h, stride = info.width, info.height, info.stride[0]
            # PipeWire pads rows to an alignment boundary, so trust the stride
            # rather than assuming width * 4 bytes per row.
            arr = np.frombuffer(mapinfo.data, dtype=np.uint8, count=stride * h)
            arr = arr.reshape(h, stride // 4, 4)[:, :w, :3]
            self._size = (w, h)
            return np.ascontiguousarray(arr)  # BGRx -> BGR
        finally:
            buf.unmap(mapinfo)

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    def stop(self) -> None:
        if self._pipeline is not None:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline.get_state(Gst.SECOND)  # settle before dropping refs
            self._pipeline = None
            self._sink = None
        if self._session_path and self._bus is not None:
            try:
                dbus.Interface(
                    self._bus.get_object(PORTAL_BUS, self._session_path),
                    "org.freedesktop.portal.Session",
                ).Close()
            except dbus.DBusException:
                pass
            self._session_path = None

