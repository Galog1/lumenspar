"""QML-facing bridge for the wish counter.

Imports run on a worker thread (they make dozens of paced web requests);
the stats are recomputed from the stored history afterwards and published
as plain lists/dicts, which QML reads directly.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from ..wishes import importer, link, stats, store
from .backend import _Worker


class WishBackend(QObject):
    changed = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    logAppended = Signal(str)
    paimonLinkChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._history = store.latest()
        self._stats = stats.all_stats(self._history.wishes) if self._history else []
        self._busy = False
        self._status = ""
        self._stop = False
        self._worker: _Worker | None = None
        self._paimon_link = ""
        self._on_success = None      # what to do once the current job has finished

    # -- what the page shows --------------------------------------------

    @Property("QVariantList", notify=changed)
    def banners(self) -> list:
        return self._stats

    @Property(str, notify=changed)
    def account(self) -> str:
        return self._history.uid if self._history else ""

    @Property(int, notify=changed)
    def totalWishes(self) -> int:
        return self._history.total() if self._history else 0

    @Property(str, notify=changed)
    def updated(self) -> str:
        if not self._history or not self._history.updated:
            return ""
        try:
            return datetime.fromisoformat(self._history.updated).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return self._history.updated

    @Property(str, notify=paimonLinkChanged)
    def paimonLink(self) -> str:
        return self._paimon_link

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    # -- actions ----------------------------------------------------------

    @Slot()
    def importFromGame(self) -> None:
        self._import(lambda log: importer.find_link(log))

    @Slot(str)
    def importFromFolder(self, url: str) -> None:
        folder = url.removeprefix("file://")
        self._import(lambda log: importer.find_link(log, folder))

    @Slot(str)
    def importFromLink(self, link: str) -> None:
        link = link.strip()
        if not link:
            self._set_status("Paste the wish history link first")
            return
        self._import(lambda log: link)

    @Slot()
    def copyPaimonLink(self) -> None:
        """Find a working wish history link and put it on the clipboard.

        The same link paimon.moe's PowerShell script produces, for pasting into
        paimon.moe's import page -- found the same way, but on Linux too.
        """
        if self._busy:
            return
        found: list[str] = []
        # A link shown from an earlier attempt may have expired since; showing
        # it next to a failure would invite pasting a dead link.
        self._paimon_link = ""
        self.paimonLinkChanged.emit()

        def job(log) -> None:
            found.append(link.paimon_link(importer.find_link(log)))
            log("Found a working link")

        def done() -> None:
            # The clipboard belongs to the GUI thread, so it is set here.
            self._paimon_link = found[0]
            self.paimonLinkChanged.emit()
            QGuiApplication.clipboard().setText(self._paimon_link)
            self._set_status("Link copied -- paste it into paimon.moe's wish import. "
                             "It stops working about a day after the history was opened.")

        self._start(job, "Link for paimon.moe", "Looking for a working wish history link…", done)

    @Slot()
    def copyPaimonLinkAgain(self) -> None:
        if self._paimon_link:
            QGuiApplication.clipboard().setText(self._paimon_link)
            self._set_status("Link copied again")

    @Slot()
    def stop(self) -> None:
        self._stop = True
        self._set_status("Stopping after the current page…")

    def _import(self, get_link) -> None:
        # Failures (no link, an expired link, a refused request) raise with a
        # message written for the user; the worker logs it as "error: …".
        def job(log) -> None:
            importer.run(get_link(log), log, should_stop=lambda: self._stop)

        def done() -> None:
            self._reload()
            self._set_status(f"Imported -- {self.totalWishes} wishes on record")

        self._start(job, "Wish import", "Importing wish history…", done)

    def _start(self, job, label: str, status: str, on_success) -> None:
        if self._busy:
            return
        self._stop = False
        self._busy = True
        self._on_success = on_success
        self.busyChanged.emit()
        self._set_status(status)
        self.logAppended.emit(f"── {label} ──")

        w = _Worker(job, self)
        w.line.connect(self.logAppended)
        w.done.connect(self._finish)
        self._worker = w
        w.start()

    def _finish(self, ok: bool, err: str) -> None:
        w = self._worker
        if w is not None:
            w.wait(5000)
            w.deleteLater()
        self._worker = None
        self._busy = False
        self.busyChanged.emit()
        on_success, self._on_success = self._on_success, None
        if ok and on_success is not None:
            on_success()
        elif not ok:
            self._set_status(err[:200] or "Failed")

    def _reload(self) -> None:
        self._history = store.latest()
        self._stats = stats.all_stats(self._history.wishes) if self._history else []
        self.changed.emit()

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()

    def shutdown(self) -> None:
        w = self._worker
        if w is not None and w.isRunning():
            self._stop = True
            w.wait(8000)
