"""QML-facing bridge.

Holds the `Settings` object and re-publishes it as Qt properties so QML can
bind directly. Long-running work (capture, OCR, scanning) runs on a worker
thread; only signals cross back to the GUI thread.
"""

from __future__ import annotations

import shutil
import traceback
from pathlib import Path

from PySide6.QtCore import (
    Property, QObject, QThread, Signal, Slot, QStandardPaths,
)

from ..config import CATEGORIES, Settings
from ..ocr import engine as ocr_engine
from ..ocr import match as ocr_match


class _Worker(QThread):
    """Runs a callable off the GUI thread, reporting progress as text."""

    line = Signal(str)
    done = Signal(bool, str)

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self._fn(self.line.emit)
        except Exception as exc:  # surfaced in the UI log, never a silent stop
            self.line.emit(f"error: {exc}")
            self.done.emit(False, str(exc))
            traceback.print_exc()
            return
        self.done.emit(True, "")


class Backend(QObject):
    settingsChanged = Signal()
    statusChanged = Signal()
    logAppended = Signal(str)
    scanningChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._s = Settings.load()
        self._scanning = False
        self._status = ""
        self._worker: _Worker | None = None
        self._capture = None  # PortalCapture, owned by the GUI thread
        self._inject = None
        self._stop_requested = False
        self._esc = None

    # -- categories ------------------------------------------------------

    @Property("QStringList", constant=True)
    def allCategories(self) -> list[str]:
        return list(CATEGORIES)

    @Property("QStringList", notify=settingsChanged)
    def categories(self) -> list[str]:
        """Selected categories.

        Must be a Property, not a Slot: QML only re-evaluates a binding when a
        bound Property's notify signal fires, so `checked: hasCategory(...)`
        evaluated once at load and never updated -- the chips could not be
        ticked or unticked.
        """
        return list(self._s.categories)

    @Slot(str, result=bool)
    def hasCategory(self, name: str) -> bool:
        return name in self._s.categories

    @Slot(str, bool)
    def setCategory(self, name: str, on: bool) -> None:
        if name not in CATEGORIES:
            return
        cur = set(self._s.categories)
        cur.add(name) if on else cur.discard(name)
        # Preserve the canonical order rather than set iteration order.
        self._s.categories = [c for c in CATEGORIES if c in cur]
        self.settingsChanged.emit()

    # -- simple scalar settings ------------------------------------------

    def _mk(name: str, typ, notify):  # noqa: N805 - property factory
        """Re-publish a Settings field as a bindable Qt property.

        The notify signal is passed in explicitly: a function nested in a
        class body cannot close over names in that class's namespace.
        """

        def getter(self):
            return getattr(self._s, name)

        def setter(self, v) -> None:
            if getattr(self._s, name) != v:
                setattr(self._s, name, v)
                self.settingsChanged.emit()

        return Property(typ, getter, setter, notify=notify)

    minArtifactRarity = _mk("min_artifact_rarity", int, settingsChanged)
    minWeaponRarity = _mk("min_weapon_rarity", int, settingsChanged)
    delayScale = _mk("delay_scale", float, settingsChanged)
    exportDir = _mk("export_dir", str, settingsChanged)
    exportName = _mk("export_name", str, settingsChanged)
    keyInventory = _mk("key_inventory", str, settingsChanged)
    keyCharacter = _mk("key_character", str, settingsChanged)
    travelerName = _mk("traveler_name", str, settingsChanged)
    wandererName = _mk("wanderer_name", str, settingsChanged)
    keyTabLeft = _mk("key_tab_left", str, settingsChanged)
    keyTabRight = _mk("key_tab_right", str, settingsChanged)
    minMatchScore = _mk("min_match_score", float, settingsChanged)
    del _mk

    @Property(str, notify=settingsChanged)
    def exportPath(self) -> str:
        return str(self._s.export_path)

    # -- status ----------------------------------------------------------

    @Property(bool, notify=scanningChanged)
    def scanning(self) -> bool:
        return self._scanning

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()

    @Property(bool, constant=True)
    def ocrReady(self) -> bool:
        return ocr_engine.available()

    @Property(str, constant=True)
    def matcherBackend(self) -> str:
        return ocr_match.backend()

    @Property(str, constant=True)
    def vocabSummary(self) -> str:
        return (
            f"{len(ocr_match.characters())} characters · "
            f"{len(ocr_match.weapons())} weapons · "
            f"{len(ocr_match.artifact_sets())} artifact sets"
        )

    # -- actions ---------------------------------------------------------

    @Slot()
    def save(self) -> None:
        path = self._s.save()
        self._set_status(f"Saved settings to {path}")

    @Slot(str)
    def setExportDirFromUrl(self, url: str) -> None:
        self._s.export_dir = url.removeprefix("file://") or self._s.export_dir
        self.settingsChanged.emit()

    @Slot(result=str)
    def defaultExportUrl(self) -> str:
        d = Path(self._s.export_dir).expanduser()
        if not d.exists():
            d = Path(
                QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
            )
        return d.as_uri()

    @Slot()
    def repickScreen(self) -> None:
        """Forget the cached portal grant so the picker reappears next run."""
        self._s.restore_token = ""
        self._s.save()
        self._close_capture()
        self._set_status("Screen selection cleared — you'll be asked again next scan")
        self.settingsChanged.emit()

    @Slot()
    def selfTest(self) -> None:
        """Verify capture + OCR without touching the game."""
        if self._scanning:
            return
        if not self._prepare_capture():
            return
        self._run(self._self_test_job, "Self-test")

    def _prepare_capture(self) -> bool:
        """Open the portal session on the GUI thread.

        D-Bus signal dispatch is bound to GLib's default main context, which
        the GUI thread owns (Qt uses QEventDispatcherGlib on Linux).
        Negotiating the portal from a worker thread cannot dispatch the
        Response signal and simply blocks until it is killed, so session
        setup has to happen here rather than inside the job.
        """
        if self._capture is not None:
            return True
        from ..capture.portal import PortalCapture

        self._set_status("Opening capture session…")
        cap = PortalCapture(
            restore_token=self._s.restore_token or None,
            on_restore_token=self._store_token,
        )
        try:
            cap.start()
        except Exception as exc:
            self._set_status(f"Capture unavailable: {exc}")
            self.logAppended.emit(f"error: {exc}")
            return False
        self._capture = cap
        return True

    def _close_capture(self) -> None:
        if self._capture is not None:
            try:
                self._capture.stop()
            finally:
                self._capture = None

    def _self_test_job(self, log) -> None:
        from ..ocr import preprocess as pp

        log("Checking Tesseract…")
        log(f"  tesseract: {'found' if ocr_engine.available() else 'MISSING'}")
        log(f"  matcher:   {ocr_match.backend()}")
        log(f"  vocabulary: {self.vocabSummary}")

        log("Grabbing a frame…")
        frame = self._capture.grab(timeout=10.0)
        h, w = frame.shape[:2]
        log(f"  captured {w}x{h} (native pixels)")
        ratio = w / h
        note = "16:9" if abs(ratio - 16 / 9) < 0.02 else (
            "16:10" if abs(ratio - 16 / 10) < 0.02 else f"{ratio:.3f} — unsupported"
        )
        log(f"  aspect ratio: {note}")

        # Read a broad band rather than one fixed corner: a blank corner would
        # make a healthy OCR install look broken.
        band = frame[h // 6 : h // 2, : w // 2]
        txt = ocr_engine.read(pp.prep_text(band), psm=ocr_engine.PSM_BLOCK)
        words = [t for t in txt.split() if len(t) > 1]
        if words:
            log(f"  OCR read {len(words)} words, e.g. {' '.join(words[:5])!r}")
        else:
            log("  OCR read no text in the sample area (that may be fine)")
        log("Self-test complete.")

    def _store_token(self, token: str) -> None:
        self._s.restore_token = token
        self._s.save()

    @Slot()
    def startScan(self) -> None:
        if self._scanning:
            return
        if not self._s.categories:
            self._set_status("Select at least one category to scan")
            return
        if not self._prepare_capture():
            return
        self._stop_requested = False
        self._run(self._scan_job, "Scan")

    @Slot()
    def stopScan(self) -> None:
        self._stop_requested = True
        if self._worker is not None:
            self._worker.requestInterruption()
            self._set_status("Stopping after the current artifact…")

    def _screens(self) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
        """Logical rect of the captured output, and of the whole desktop."""
        from PySide6.QtGui import QGuiApplication

        cap = self._capture
        pos = getattr(cap, "logical_pos", (0, 0))
        size = getattr(cap, "logical_size", (0, 0))
        app = QGuiApplication.instance()
        vg = app.primaryScreen().virtualGeometry()
        desktop = (vg.x(), vg.y(), vg.width(), vg.height())

        if size and size[0]:
            return (pos[0], pos[1], size[0], size[1]), desktop
        # The portal did not report geometry: fall back to the screen whose
        # logical size best matches, rather than guessing the primary one.
        best = app.primaryScreen()
        g = best.geometry()
        return (g.x(), g.y(), g.width(), g.height()), desktop

    def _scan_job(self, log) -> None:
        import time

        from ..good import GoodExport
        from ..inject.uinput import UinputInject
        from ..inject.ydotool import YdotoolInject
        from ..scan.driver import LiveDriver
        from ..scan.scanner import (ArtifactScanner, CharacterScanner,
                                    MaterialScanner, WeaponScanner,
                                    read_inventory_header, read_tab_title)
        from ..scan.tabs import goto_tab

        # Each entry is (category, tab). Materials live on two separate tabs.
        plan: list[tuple[str, str]] = []
        for c in self._s.categories:
            if c == "artifacts":
                plan.append(("artifacts", "artifacts"))
            elif c == "weapons":
                plan.append(("weapons", "weapons"))
            elif c == "materials":
                plan.append(("materials", "levelup"))
                plan.append(("materials", "world"))
            elif c == "characters":
                plan.append(("characters", "__screen__"))
        if not plan:
            log("Select at least one category to scan.")
            return

        # uinput first: ydotool has no wheel command and the grid must scroll.
        inject = None
        if self._s.inject_backend in ("auto", "uinput") and UinputInject.available():
            inject = UinputInject()
        elif YdotoolInject.available():
            inject = YdotoolInject()
            log("warning: ydotool cannot scroll; only the first page will scan")
        if inject is None:
            raise RuntimeError("no usable input backend (need /dev/uinput or ydotool)")

        log(f"Input backend: {inject.name}")
        inject.start()

        # Escape aborts: while scanning, the game holds focus and the Stop
        # button cannot be reached without alt-tabbing.
        from ..inject.hotkey import EscapeWatcher

        def _on_escape() -> None:
            self._stop_requested = True
            self.logAppended.emit("Escape pressed — stopping after this artifact.")

        self._esc = EscapeWatcher(_on_escape)
        watched = self._esc.start()
        if watched:
            log(f"Press Escape at any time to stop ({watched} keyboards watched).")
        else:
            log("warning: could not watch for Escape; use the Stop button.")

        try:
            output, desktop = self._screens()
            log(f"Capturing output at {output}; desktop is {desktop[2]}x{desktop[3]}")
            log("")
            log("Switch to Genshin now — artifact inventory open, fullscreen.")
            for n in (5, 4, 3, 2, 1):
                if self._stop_requested:
                    log("Cancelled before starting.")
                    return
                log(f"  starting in {n}…")
                time.sleep(1.0)

            driver = LiveDriver(self._capture, inject, output, desktop)
            failures = Path(self._s.export_dir).expanduser() / "failures"
            export = GoodExport()
            problems: list[str] = []
            # Make sure the inventory is actually open before driving tabs.
            label, _ = read_inventory_header(driver.grab())
            if not label:
                log(f"Inventory does not look open; pressing "
                    f"'{self._s.key_inventory}'.")
                inject.tap(self._s.key_inventory)
                time.sleep(self._s.wait("panel_open"))

            for category, tab in plan:
                if self._stop_requested:
                    break
                log("")
                if category == "characters":
                    # A separate screen, not an inventory tab.
                    log("── Scanning characters ──")
                    log(f"Opening the character screen ('{self._s.key_character}').")
                    inject.tap(self._s.key_character)
                    time.sleep(self._s.wait("panel_open"))
                    res = CharacterScanner(
                        driver, self._s, log=log,
                        should_stop=lambda: self._stop_requested,
                        tap=lambda k: inject.tap(k),
                        failure_dir=failures).scan()
                    problems.extend(res.problems)
                    export.characters.extend(res.items)
                    inject.tap(self._s.key_escape)
                    time.sleep(self._s.wait("panel_open"))
                    continue
                log(f"── Scanning {category} ({tab} tab) ──")
                if not goto_tab(
                    tab,
                    tap=lambda k: inject.tap(k),
                    grab=driver.grab,
                    sleep=time.sleep,
                    read_title=read_tab_title,
                    log=log,
                    step_delay=max(0.15, self._s.wait("after_key")),
                    key_left=self._s.key_tab_left,
                    key_right=self._s.key_tab_right,
                    should_stop=lambda: self._stop_requested,
                ):
                    log(f"Skipping {category}: could not reach the {tab} tab.")
                    continue
                cls = {"artifacts": ArtifactScanner,
                       "weapons": WeaponScanner,
                       "materials": MaterialScanner}[category]
                res = cls(driver, self._s, log=log,
                          should_stop=lambda: self._stop_requested,
                          failure_dir=failures).scan()
                problems.extend(res.problems)
                if category == "artifacts":
                    export.artifacts.extend(res.items)
                elif category == "weapons":
                    export.weapons.extend(res.items)
                else:
                    for key, count in res.items:
                        # The same material can appear on both tabs; keep the
                        # larger reading rather than summing a double count.
                        export.materials[key] = max(export.materials.get(key, 0), count)
        finally:
            inject.stop()
            if self._esc is not None:
                self._esc.stop()
                self._esc = None

        if not len(export):
            log("Nothing was read; no file was written.")
            return
        path = export.write(self._s.export_path)
        log("")
        log(f"Wrote {len(export.artifacts)} artifacts, {len(export.weapons)} weapons, "
            f"{len(export.characters)} characters and {len(export.materials)} "
            f"materials to {path}")
        if problems:
            log(f"{len(problems)} item(s) could not be read; first few:")
            for p in problems[:5]:
                log(f"  - {p}")
            log(f"Full details and screenshots: {failures}")

    def _run(self, job, label: str) -> None:
        self._scanning = True
        self.scanningChanged.emit()
        self._set_status(f"{label} running…")
        self.logAppended.emit(f"── {label} ──")

        w = _Worker(job, self)
        w.line.connect(self.logAppended)
        w.done.connect(lambda ok, err: self._finish(label, ok, err))
        self._worker = w
        w.start()

    def _finish(self, label: str, ok: bool, err: str) -> None:
        # `done` is delivered queued, so run() may not have returned yet.
        # Dropping the last reference here would destroy a live QThread, which
        # Qt turns into an abort rather than an exception.
        w = self._worker
        if w is not None:
            w.wait(5000)
            w.deleteLater()
        self._worker = None
        self._scanning = False
        self.scanningChanged.emit()
        self._set_status(f"{label} finished" if ok else f"{label} failed: {err[:80]}")

    def shutdown(self) -> None:
        """Block until any in-flight job has stopped. Call before quitting."""
        w = self._worker
        if w is not None and w.isRunning():
            w.requestInterruption()
            w.wait(8000)
        self._close_capture()
