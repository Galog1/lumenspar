"""QML bridge for updating Lumenspar from its GitHub releases (see lumenspar.updater).

It checks for a newer release in the background (at start-up and every few
hours while the app stays open, unless switched off), shows it in the window,
and on request downloads and installs it. Nothing is installed without the
user pressing the button, and never while a scan or import is running.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Property, QCoreApplication, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .. import updater
from ..config import Settings

RECHECK_MS = 6 * 60 * 60 * 1000       # while the app stays open
FIRST_CHECK_MS = 4000                 # let the window appear first


class UpdateBackend(QObject):
    changed = Signal()
    settingsChanged = Signal()
    # From worker threads; Qt delivers them on the GUI thread.
    _checked = Signal(object, str, bool)       # release | None, error text, was it quiet
    _progress = Signal(int, int)
    _downloaded = Signal(object, str)          # downloaded file | None, error text

    def __init__(self, settings: Settings, parent: QObject | None = None, *,
                 fetch: Callable | None = None, opener: Callable | None = None,
                 blocker: Callable[[], str] = lambda: "",
                 installed_as: Callable[[], str] = updater.how_installed,
                 quit_app: Callable[[], None] | None = None) -> None:
        super().__init__(parent)
        self._s = settings
        self._fetch = fetch or updater.fetch_json
        self._opener = opener
        self._blocker = blocker
        self._installed_as = installed_as
        self._quit = quit_app or (lambda: QCoreApplication.quit())
        self._release: updater.Release | None = None
        self._asset: updater.Asset | None = None
        self._state = "idle"               # idle | checking | downloading | installing
        self._status = ""
        self._fraction = 0.0
        self._dismissed = ""               # the version whose banner was closed
        self._stop = False
        self._checked.connect(self._on_checked)
        self._progress.connect(self._on_progress)
        self._downloaded.connect(self._on_downloaded)
        self._timer = QTimer(self)
        self._timer.setInterval(RECHECK_MS)
        self._timer.timeout.connect(lambda: self.check(quiet=True))

    # -- read by QML -------------------------------------------------------------

    @Property(str, constant=True)
    def currentVersion(self) -> str:
        return updater.__version__

    @Property(bool, notify=changed)
    def available(self) -> bool:
        return self._release is not None

    @Property(bool, notify=changed)
    def showBanner(self) -> bool:
        """An update exists and the user has not waved it away this session."""
        return self._release is not None and self._release.version != self._dismissed

    @Property(str, notify=changed)
    def latestVersion(self) -> str:
        return self._release.version if self._release else ""

    @Property(str, notify=changed)
    def notes(self) -> str:
        return self._release.notes.strip() if self._release else ""

    @Property(bool, notify=changed)
    def canInstall(self) -> bool:
        """Whether this install can update itself (a source checkout cannot)."""
        return self._asset is not None

    @Property(str, notify=changed)
    def state(self) -> str:
        return self._state

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._state != "idle"

    @Property(str, notify=changed)
    def status(self) -> str:
        return self._status

    @Property(float, notify=changed)
    def fraction(self) -> float:
        return self._fraction

    @Property(bool, notify=settingsChanged)
    def autoCheck(self) -> bool:
        return self._s.check_updates

    @autoCheck.setter
    def autoCheck(self, on: bool) -> None:
        if self._s.check_updates != on:
            self._s.check_updates = on
            self._s.save()
            self.settingsChanged.emit()
            self._schedule()

    # -- start-up ----------------------------------------------------------------

    def start(self) -> None:
        """Begin the automatic checks (not in the headless self-check)."""
        if os.environ.get("LUMENSPAR_SMOKE_TEST") or os.environ.get("LUMENSPAR_NO_UPDATE_CHECK"):
            return
        self._schedule()
        if self._s.check_updates:
            QTimer.singleShot(FIRST_CHECK_MS, lambda: self.check(quiet=True))

    def _schedule(self) -> None:
        if self._s.check_updates and not (os.environ.get("LUMENSPAR_SMOKE_TEST")
                                          or os.environ.get("LUMENSPAR_NO_UPDATE_CHECK")):
            self._timer.start()
        else:
            self._timer.stop()

    # -- checking ----------------------------------------------------------------

    @Slot()
    def checkNow(self) -> None:
        self.check(quiet=False)

    def check(self, quiet: bool = False) -> None:
        if self._state != "idle":
            return
        self._state = "checking"
        if not quiet:
            self._status = "Checking for updates…"
        self.changed.emit()
        threading.Thread(target=self._check_worker, args=(quiet,), daemon=True).start()

    def _check_worker(self, quiet: bool) -> None:
        try:
            release = updater.latest_release(self._fetch)
            self._checked.emit(release, "", quiet)
        except updater.UpdateError as exc:
            self._checked.emit(None, str(exc), quiet)
        except Exception as exc:                       # never let a thread die silently
            self._checked.emit(None, f"Could not check for updates ({type(exc).__name__}).", quiet)

    @Slot(object, str, bool)
    def _on_checked(self, release, error: str, quiet: bool) -> None:
        self._state = "idle"
        if error:
            # An automatic check that fails (offline, rate limit) stays silent.
            self._status = "" if quiet else error
        elif release is not None and updater.is_newer(release.version):
            self._release = release
            self._asset = updater.asset_for(release, self._installed_as())
            self._status = f"Lumenspar {release.version} is available."
        else:
            self._release = None
            self._asset = None
            self._status = "" if quiet else f"Lumenspar {updater.__version__} is up to date."
        self.changed.emit()

    # -- installing --------------------------------------------------------------

    @Slot()
    def install(self) -> None:
        if self._release is None or self._state != "idle":
            return
        if self._asset is None:
            self.openReleasePage()
            self._status = ("This install cannot update itself; the release page is open "
                            "in your browser.")
            self.changed.emit()
            return
        reason = self._blocker()
        if reason:
            self._status = f"Not now: {reason}. Update when it has finished."
            self.changed.emit()
            return
        self._state, self._stop, self._fraction = "downloading", False, 0.0
        self._status = f"Downloading Lumenspar {self._release.version}…"
        self.changed.emit()
        threading.Thread(target=self._download_worker, args=(self._asset,), daemon=True).start()

    def _download_worker(self, asset: updater.Asset) -> None:
        try:
            kwargs = {"opener": self._opener} if self._opener else {}
            path = updater.download(
                asset, self._download_dir(),
                progress=lambda done, total: self._progress.emit(done, total),
                should_stop=lambda: self._stop, **kwargs)
            self._downloaded.emit(path, "")
        except updater.UpdateError as exc:
            self._downloaded.emit(None, str(exc))
        except Exception as exc:
            self._downloaded.emit(None, f"The update failed ({type(exc).__name__}).")

    def _download_dir(self) -> Path:
        # An AppImage is replaced in its own folder, so the download goes there:
        # a rename across file systems would copy, and /tmp is often a RAM disk.
        appimage = os.environ.get("APPIMAGE")
        if self._installed_as() == "appimage" and appimage:
            return Path(appimage).parent / ".lumenspar-update"
        return updater.work_dir()

    @Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self._fraction = (done / total) if total else 0.0
        mb = done / 1_048_576
        self._status = (f"Downloading Lumenspar {self.latestVersion}… {mb:.0f}"
                        + (f" of {total / 1_048_576:.0f} MB" if total else " MB"))
        self.changed.emit()

    @Slot(object, str)
    def _on_downloaded(self, path, error: str) -> None:
        if error or path is None:
            self._state, self._fraction = "idle", 0.0
            self._status = error or "The update failed."
            self.changed.emit()
            return
        # A scan may have been started while the download ran.
        reason = self._blocker()
        if reason:
            self._state, self._fraction = "idle", 0.0
            self._status = f"Downloaded, but {reason}. Press Update again when it has finished."
            self.changed.emit()
            return
        self._state, self._fraction = "installing", 1.0
        self._status = "Installing… Lumenspar will restart."
        self.changed.emit()
        try:
            if self._installed_as() == "windows":
                updater.apply_windows(Path(path))
            else:
                updater.relaunch(updater.apply_appimage(Path(path)))
        except updater.UpdateError as exc:
            self._state, self._fraction = "idle", 0.0
            self._status = str(exc)
            self.changed.emit()
            return
        except OSError as exc:
            self._state, self._fraction = "idle", 0.0
            self._status = f"Could not start the update ({exc})."
            self.changed.emit()
            return
        # The installer closes us if we are still open; leaving first is cleaner.
        QTimer.singleShot(400, self._quit)

    @Slot()
    def cancel(self) -> None:
        self._stop = True

    # -- small actions -------------------------------------------------------------

    @Slot()
    def dismiss(self) -> None:
        if self._release is not None:
            self._dismissed = self._release.version
            self.changed.emit()

    @Slot()
    def openReleasePage(self) -> None:
        QDesktopServices.openUrl(QUrl(self._release.page if self._release
                                      else updater.RELEASE_PAGE))
