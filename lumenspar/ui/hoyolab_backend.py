"""QML bridge for reading every character from HoYoLAB.

HoYoLAB answers its character endpoints only to a signed-in session, so the
Build Cards page opens a window (qml/HoyolabWindow.qml) with an embedded web
page: the player signs in on HoYoLAB's own login page and presses a button,
and the window runs the requests (lumenspar.hoyolab) from a HoYoLAB page.

Privacy, by construction:
- the window's profile is off the record: cookies and every other site datum
  stay in memory and are gone when the window closes, so nothing about the
  sign-in is ever written to disk (tests/test_hoyolab_backend.py checks the
  QML for this);
- the password is typed into HoYoLAB's page; no code here reads form fields,
  cookies or storage;
- only the parsed build cards leave this object, to the same collection the
  Enka.Network showcase fills.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from .. import hoyolab


def webengine_available() -> bool:
    """Whether Qt's embedded browser can be used (it is optional at run time)."""
    try:
        from PySide6 import QtWebEngineQuick  # noqa: F401
    except ImportError:
        return False
    return True


class HoyolabBackend(QObject):
    changed = Signal()
    # (uid, cards, problems): parsed build cards ready to be stored.
    cardsReady = Signal(str, object, object)

    def __init__(self, parent: QObject | None = None, available: bool | None = None) -> None:
        super().__init__(parent)
        self._available = webengine_available() if available is None else available
        self._open = False
        self._step = "login"                # "login" | "fetching"
        self._status = ""
        self._uid = ""
        self._server = ""

    # -- read by QML -------------------------------------------------------------

    @Property(bool, constant=True)
    def available(self) -> bool:
        return self._available

    @Property(bool, notify=changed)
    def open(self) -> bool:
        return self._open

    @Property(str, notify=changed)
    def step(self) -> str:
        return self._step

    @Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @Property(str, constant=True)
    def loginUrl(self) -> str:
        return hoyolab.LOGIN_URL

    @Property(str, notify=changed)
    def actUrl(self) -> str:
        return hoyolab.page_url(self._uid, self._server) if self._server else ""

    @Property(str, notify=changed)
    def fetchScript(self) -> str:
        return hoyolab.fetch_script(self._uid, self._server) if self._server else ""

    @Property(str, constant=True)
    def progressJs(self) -> str:
        return hoyolab.PROGRESS_JS

    @Property(str, constant=True)
    def resultJs(self) -> str:
        return hoyolab.RESULT_JS

    # -- actions -----------------------------------------------------------------

    @Slot(str, result=str)
    def begin(self, uid: str) -> str:
        """Open the sign-in window for a UID; returns "" or why it cannot."""
        uid = uid.strip()
        if not self._available:
            return "The embedded browser (Qt WebEngine) is not available in this install."
        server = hoyolab.server_for(uid)
        if server is None:
            return ("Enter your UID first. HoYoLAB covers global accounts "
                    "(UIDs starting with 6, 7, 8 or 9).")
        if self._open:
            return ""
        self._uid, self._server = uid, server
        self._step = "login"
        self._status = ("Sign in to HoYoLAB in this window, then press "
                        "\"Fetch my characters\".")
        self._open = True
        self.changed.emit()
        return ""

    @Slot()
    def fetchNow(self) -> None:
        self._step = "fetching"
        self._status = "Reading your characters from HoYoLAB…"
        self.changed.emit()

    @Slot()
    def cancel(self) -> None:
        """Close the window; the web profile, and with it the session, is destroyed."""
        if not self._open:
            return
        self._open = False
        self._step = "login"
        self.changed.emit()

    @Slot(str)
    def progress(self, payload: str) -> None:
        try:
            p = json.loads(payload) if payload else None
        except ValueError:
            p = None
        if p and p.get("total"):
            self._status = f"Reading characters from HoYoLAB… {p.get('done', 0)}/{p['total']}"
            self.changed.emit()

    @Slot(str, int)
    def failed(self, message: str, retcode: int) -> None:
        """A request failed in the page: back to the sign-in step if it was the session."""
        if retcode == hoyolab.NOT_SIGNED_IN:
            self._status = ("HoYoLAB did not accept the session: sign in first, then press "
                            "\"Fetch my characters\" again.")
        else:
            self._status = f"HoYoLAB refused the request ({message})."
        self._step = "login"
        self.changed.emit()

    @Slot(str)
    def finish(self, payload: str) -> None:
        """The page's result: parse it, hand the cards over and close the window."""
        try:
            raw = json.loads(payload)
            dump = os.environ.get("LUMENSPAR_HOYOLAB_DUMP")
            if dump:   # development aid: the raw game data (no session data) for fixtures
                Path(dump).write_text(payload, encoding="utf-8")
            cards, problems = hoyolab.parse(raw)
        except hoyolab.HoyolabError as exc:
            self.failed(str(exc), hoyolab.NOT_SIGNED_IN if exc.signed_out else 0)
            return
        except (ValueError, TypeError, AttributeError):
            self.failed("the answer was not in the expected format", 0)
            return
        uid = self._uid
        self._open = False
        self._step = "login"
        self._status = ""
        self.changed.emit()
        self.cardsReady.emit(uid, cards, problems)
