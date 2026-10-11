"""QML-facing bridge for the wish counter.

Imports run on a worker thread (they make dozens of paced web requests);
the stats are recomputed from the stored history afterwards and published
as plain lists/dicts, which QML reads directly.

The optional Google Drive backup syncs after every import and on startup;
its errors name the setup-guide step that fixes them, which the page
highlights.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

from .. import gdrive
from ..wishes import backup, icons, importer, link, stats, store
from .backend import _Worker


class WishBackend(QObject):
    changed = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    logAppended = Signal(str)
    paimonLinkChanged = Signal()
    _iconsArrived = Signal()      # from the download thread, delivered on the GUI thread
    driveChanged = Signal()
    _browserWanted = Signal(str)  # from the sign-in thread, opened on the GUI thread

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._icon_fetch = False
        self._icon_tried: set[str] = set()   # one attempt per portrait per session
        self._iconsArrived.connect(self._on_icons)
        self._history = store.latest()
        self._stats = stats.all_stats(self._history.wishes) if self._history else []
        self._with_icons()
        self._busy = False
        self._status = ""
        self._stop = False
        self._worker: _Worker | None = None
        self._paimon_link = ""
        self._on_success = None      # what to do once the current job has finished
        self._drive_job = False       # the current job is a Drive one (own status line)
        self._signing_in = False
        self._drive = gdrive.DriveState.load()
        self._drive_status = ""
        self._drive_step = 0          # the guide step the last Drive error points at
        self._browserWanted.connect(self._open_browser)
        if self._drive.signed_in:     # pick up imports made on other computers
            QTimer.singleShot(0, lambda: self._sync("Checking Google Drive…"))

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

    @Property(bool, notify=driveChanged)
    def driveConfigured(self) -> bool:
        return self._drive.configured

    @Property(bool, notify=driveChanged)
    def driveSignedIn(self) -> bool:
        return self._drive.signed_in

    @Property(bool, constant=True)
    def driveBuiltin(self) -> bool:
        """This build carries Lumenspar's own Google client: no setup needed."""
        return bool(self._drive.builtin[0])

    @Property(bool, notify=driveChanged)
    def driveOwnClient(self) -> bool:
        return self._drive.own_client

    @Property(bool, notify=driveChanged)
    def driveSigningIn(self) -> bool:
        return self._signing_in

    @Property(str, notify=driveChanged)
    def driveEmail(self) -> str:
        return self._drive.email

    @Property(str, notify=driveChanged)
    def driveClientId(self) -> str:
        return self._drive.client_id

    @Property(str, notify=driveChanged)
    def driveLastBackup(self) -> str:
        try:
            return datetime.fromisoformat(self._drive.last_backup).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return ""

    @Property(str, notify=driveChanged)
    def driveStatus(self) -> str:
        return self._drive_status

    @Property(int, notify=driveChanged)
    def driveStep(self) -> int:
        return self._drive_step

    @Property("QVariantMap", constant=True)
    def driveSite(self) -> dict:
        return {"homepage": gdrive.HOMEPAGE_URL, "privacy": gdrive.PRIVACY_URL,
                "terms": gdrive.TERMS_URL, "domain": gdrive.AUTHORIZED_DOMAIN}

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

    @Slot(str)
    def copyText(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

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
            if self._drive.signed_in:
                self._sync("Backing up to Google Drive…")

        self._start(job, "Wish import", "Importing wish history…", done)

    # -- Google Drive -----------------------------------------------------

    @Slot(str, str)
    def saveDriveClient(self, client_id: str, client_secret: str) -> None:
        client_id, client_secret = client_id.strip(), client_secret.strip()
        if not client_id or not client_secret:
            self._drive_message("Paste both the client ID and the client secret.", gdrive.STEP_CLIENT)
            return
        if not client_id.endswith(".apps.googleusercontent.com"):
            self._drive_message("That does not look like a client ID -- it ends in "
                                "\".apps.googleusercontent.com\".", gdrive.STEP_CLIENT)
            return
        if (client_id, client_secret) != (self._drive.client_id, self._drive.client_secret):
            # A sign-in belongs to the client it was made with.
            self._drive.refresh_token = self._drive.email = ""
        self._drive.client_id, self._drive.client_secret = client_id, client_secret
        self._drive.save()
        self._drive_message("Client saved -- now sign in with Google.")

    @Slot()
    def clearDriveClient(self) -> None:
        """Forget the user's own client and go back to the built-in one."""
        self._drive.client_id = self._drive.client_secret = ""
        self._drive.save()
        self._drive_message("Using Lumenspar's own Google sign-in again." if self.driveBuiltin
                            else "Client removed.")

    @Slot()
    def signInGoogle(self) -> None:
        def job(log) -> None:
            log("Waiting for Google sign-in in the browser…")
            gdrive.sign_in(self._drive, self._browserWanted.emit,
                           should_stop=lambda: self._stop)
            log(f"Signed in as {self._drive.email or 'your Google account'}")

        def done() -> None:
            self._sync("Signed in -- syncing with Google Drive…")

        self._start(job, "Google sign-in", "Finish signing in in your browser…", done, drive=True)
        self._signing_in = self._busy
        self.driveChanged.emit()

    @Slot()
    def signOutGoogle(self) -> None:
        def job(log) -> None:
            gdrive.sign_out(self._drive)

        def done() -> None:
            self._drive_message("Signed out. The backup stays in your Google Drive.")

        self._start(job, "Google sign-out", "Signing out…", done, drive=True)

    @Slot()
    def backupNow(self) -> None:
        self._sync("Syncing with Google Drive…")

    def _sync(self, status: str) -> None:
        result: list[tuple[int, int]] = []

        def job(log) -> None:
            result.append(backup.sync(gdrive.AppData(self._drive), log))
            self._drive.last_backup = datetime.now().isoformat(timespec="seconds")
            self._drive.save()

        def done() -> None:
            restored, uploaded = result[0]
            if restored:
                self._reload()
            self._drive_message(
                f"Restored {restored} wish(es) from Google Drive" if restored else
                "Backed up" if uploaded else "Google Drive is up to date")

        self._start(job, "Google Drive backup", status, done, drive=True)

    @Slot(str)
    def _open_browser(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _drive_message(self, text: str, step: int = 0) -> None:
        self._drive_status, self._drive_step = text, step
        self.driveChanged.emit()

    def _start(self, job, label: str, status: str, on_success, drive: bool = False) -> None:
        if self._busy:
            return
        self._stop = False
        self._busy = True
        self._on_success = on_success
        self._drive_job = drive
        self.busyChanged.emit()
        if drive:
            self._drive_message(status)
        else:
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
        if self._signing_in:
            self._signing_in = False
            self.driveChanged.emit()
        if ok and on_success is not None:
            on_success()
        elif not ok and self._drive_job:
            step = re.search(r"\(step (\d)\)", err)
            self._drive_message(err[:300] or "Failed", int(step.group(1)) if step else 0)
        elif not ok:
            self._set_status(err[:200] or "Failed")

    def _reload(self) -> None:
        self._history = store.latest()
        self._stats = stats.all_stats(self._history.wishes) if self._history else []
        self._with_icons()
        self.changed.emit()

    # -- portraits --------------------------------------------------------

    def _with_icons(self) -> None:
        """Give each 5★ its cached portrait, and fetch the missing ones."""
        names = []
        for banner in self._stats:
            for five in banner["fives"]:
                icon = icons.icon_name(five["name"])
                file = icons.path(icon) if icon else None
                five["icon"] = QUrl.fromLocalFile(str(file)).toString() \
                    if file and file.is_file() else ""
                names.append(five["name"])
        # Each portrait is tried once per session: offline, a failed fetch
        # would otherwise be retried on every refresh, forever.
        wanted = [n for n in icons.missing(names) if n not in self._icon_tried]
        if wanted and not self._icon_fetch:
            self._icon_fetch = True
            self._icon_tried.update(wanted)

            def fetch() -> None:
                icons.download(wanted)
                self._iconsArrived.emit()
            threading.Thread(target=fetch, daemon=True).start()

    def _on_icons(self) -> None:
        self._icon_fetch = False
        self._with_icons()
        self.changed.emit()

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()

    def shutdown(self) -> None:
        w = self._worker
        if w is not None and w.isRunning():
            self._stop = True
            w.wait(8000)
