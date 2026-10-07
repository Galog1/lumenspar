"""QML-facing bridge.

Holds the `Settings` object and re-publishes it as Qt properties so QML can
bind directly. Long-running work (capture, OCR, scanning) runs on a worker
thread; only signals cross back to the GUI thread.
"""

from __future__ import annotations

import json
import os
import shutil
import traceback
from pathlib import Path

from PySide6.QtCore import (
    Property, QObject, QThread, QTimer, Signal, Slot, QStandardPaths,
)

from .. import enka, hostos
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
    rosterChanged = Signal()

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
        self._roster = enka.Roster()
        # Re-fetches the showcase while the player rotates it in-game.
        self._watch = QTimer(self)
        self._watch.setInterval((enka.DEFAULT_TTL + 5) * 1000)
        self._watch.timeout.connect(self._watch_tick)

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
    otherNames = _mk("other_names", str, settingsChanged)
    uid = _mk("uid", str, settingsChanged)
    keyTabLeft = _mk("key_tab_left", str, settingsChanged)
    keyTabRight = _mk("key_tab_right", str, settingsChanged)
    minMatchScore = _mk("min_match_score", float, settingsChanged)
    readerMode = _mk("reader_mode", str, settingsChanged)
    geminiApiKey = _mk("gemini_api_key", str, settingsChanged)
    geminiModel = _mk("gemini_model", str, settingsChanged)
    del _mk

    @Property(str, notify=settingsChanged)
    def exportPath(self) -> str:
        return str(self._s.export_path)

    # -- Enka.Network ----------------------------------------------------

    @Property(int, notify=rosterChanged)
    def rosterCount(self) -> int:
        return len(self._roster)

    @Property(bool, notify=rosterChanged)
    def watching(self) -> bool:
        return self._watch.isActive()

    @Slot()
    def fetchShowcase(self) -> None:
        self._fetch_showcase(quiet=False)

    def _fetch_showcase(self, quiet: bool) -> None:
        if self._scanning:
            return
        uid = self._s.uid.strip()
        wait = self._roster.wait_remaining(uid)
        if wait > 0:
            if not quiet:
                self._set_status(f"Enka.Network is still serving the last showcase; "
                                 f"try again in {wait:.0f}s")
            return
        self._s.save()      # keep the UID that was just used
        self._run(lambda log: self._enka_job(log, uid, quiet), "Showcase fetch",
                  announce=not quiet)

    def _enka_job(self, log, uid: str, quiet: bool) -> None:
        data, ttl = enka.fetch(uid)
        chars, problems = enka.parse(data)
        new, changed = self._roster.merge(uid, chars, ttl)
        self.rosterChanged.emit()
        if quiet and not (new or changed or problems):
            return
        if quiet:
            log("── Showcase fetch ──")
        if new:
            log(f"+{len(new)} new: {', '.join(new)}")
        if changed:
            log(f"updated: {', '.join(changed)}")
        if chars and not (new or changed):
            log("No new characters -- rotate your showcase, then exit to the title "
                "screen and back so the game publishes it.")
        for p in problems:
            log(f"  {p}")
        log(f"{len(self._roster)} characters collected.")

    @Slot(bool)
    def setWatching(self, on: bool) -> None:
        if on and not self._s.uid.strip():
            self._set_status("Enter your UID first")
            on = False
        if on:
            self._watch.start()
            self._fetch_showcase(quiet=False)
            self._set_status("Watching your showcase -- rotate characters in-game")
        else:
            self._watch.stop()
        self.rosterChanged.emit()

    def _watch_tick(self) -> None:
        self._fetch_showcase(quiet=True)

    @Slot()
    def clearRoster(self) -> None:
        self._roster.clear()
        self.rosterChanged.emit()
        self._set_status("Collected characters cleared")

    @Slot()
    def exportRoster(self) -> None:
        """Write the collected characters into the export file.

        Everything else already in the file (artifacts, weapons, materials,
        characters Enka has not seen) is kept, so no game scan is needed just
        to bring in characters.
        """
        if not len(self._roster):
            self._set_status("No characters collected yet")
            return
        path = self._s.export_path
        try:
            doc = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, ValueError) as exc:
            self._set_status(f"Could not read {path.name}: {exc}")
            return
        if not doc:
            from ..good import GoodExport
            doc = GoodExport().to_dict()
        roster = {c["key"]: {k: v for k, v in c.items() if k != "fetched_at"}
                  for c in self._roster.characters.values()}
        kept = [c for c in doc.get("characters", []) if c.get("key") not in roster]
        doc["characters"] = sorted([*roster.values(), *kept], key=lambda c: c["key"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
        msg = (f"Wrote {len(roster)} characters from Enka.Network"
               + (f" (kept {len(kept)} others already in the file)" if kept else "")
               + f" to {path}")
        self.logAppended.emit(msg)
        self._set_status(f"Wrote {len(roster)} characters to {path.name}")

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

    @Property(bool, constant=True)
    def geminiKeyFromEnv(self) -> bool:
        """True when LUMENSPAR_GEMINI_KEY supplies the key; QML then shows the
        env-var note and makes the Settings field read-only."""
        return bool(os.environ.get("LUMENSPAR_GEMINI_KEY"))

    @Property(bool, constant=True)
    def aiOnly(self) -> bool:
        """True on Windows, which ships without Tesseract or the portal."""
        return hostos.is_windows()

    @Property(bool, notify=settingsChanged)
    def readerReady(self) -> bool:
        """Whether the selected reader can run: Tesseract in local mode, a
        Gemini API key in AI mode. On Windows the reader is always the AI one."""
        mode = "ai" if hostos.is_windows() else self._s.reader_mode
        if mode == "local":
            return ocr_engine.available()
        return bool(self._s.gemini_key())

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
        if hostos.is_windows():
            # There is no portal on Windows; capture is automatic.
            self._set_status("Screen selection is not used on Windows")
            return
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
        """Open the capture backend on the GUI thread.

        On Windows that is a BitBlt session (mss, no setup needed); on Linux
        it is the screen portal, and D-Bus signal dispatch is bound to GLib's
        default main context, which the GUI thread owns (Qt uses
        QEventDispatcherGlib on Linux). Negotiating the portal from a worker
        thread cannot dispatch the Response signal and simply blocks until it
        is killed, so session setup has to happen here rather than inside the
        job.
        """
        if self._capture is not None:
            return True

        def _open(cap) -> bool:
            try:
                cap.start()
            except Exception as exc:
                self._set_status(f"Capture unavailable: {exc}")
                self.logAppended.emit(f"error: {exc}")
                return False
            self._capture = cap
            return True

        if hostos.is_windows():
            from ..capture.win import MssCapture

            self._set_status("Opening capture session...")
            return _open(MssCapture())
        from ..capture.portal import PortalCapture

        self._set_status("Opening capture session...")
        return _open(PortalCapture(
            restore_token=self._s.restore_token or None,
            on_restore_token=self._store_token,
        ))

    def _close_capture(self) -> None:
        if self._capture is not None:
            try:
                self._capture.stop()
            finally:
                self._capture = None

    def _self_test_job(self, log) -> None:
        from ..ocr import preprocess as pp

        if hostos.is_windows() or self._s.reader_mode == "ai":
            from ..ai.gemini import Gemini, GeminiError, Usage

            log("Checking Gemini...")
            log(f"  model: {self._s.gemini_model}")
            key = self._s.gemini_key()
            if not key:
                log("  Gemini: no API key is set -- add one in Settings or "
                    "export LUMENSPAR_GEMINI_KEY")
            else:
                try:
                    display = Gemini(key, self._s.gemini_model, log=log).check()
                except GeminiError as exc:
                    log(f"  Gemini: {exc}")
                else:
                    log(f"  Gemini: ok ({display})")
            log(f"  requests used today: {Usage().today()}")
        else:
            log("Checking Tesseract...")
            log(f"  tesseract: {'found' if ocr_engine.available() else 'MISSING'}")
            log(f"  matcher:   {ocr_match.backend()}")
            log(f"  vocabulary: {self.vocabSummary}")

        log("Grabbing a frame...")
        frame = self._capture.grab(timeout=10.0)
        h, w = frame.shape[:2]
        log(f"  captured {w}x{h} (native pixels)")
        ratio = w / h
        note = "16:9" if abs(ratio - 16 / 9) < 0.02 else (
            "16:10" if abs(ratio - 16 / 10) < 0.02 else f"{ratio:.3f} — unsupported"
        )
        log(f"  aspect ratio: {note}")

        if self._s.reader_mode == "local":
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
        if not self.readerReady:
            if self._s.reader_mode == "ai":
                msg = ("AI reader selected but no Gemini API key is set -- add one "
                       "in Settings or export LUMENSPAR_GEMINI_KEY")
            else:
                msg = "tesseract is not installed"
            self.logAppended.emit(f"error: {msg}")
            self._set_status(msg)
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
        """Rect of the captured output, and of the whole desktop."""
        if hostos.is_windows():
            # mss reports physical pixels for both rects; Qt logical geometry
            # would be wrong for pointing at a scaled Windows desktop.
            cap = self._capture
            return cap.monitor_rect(), cap.virtual_rect()
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

        from ..ai.gemini import GeminiError
        from ..good import GoodExport
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

        # Windows has one backend; Linux prefers uinput (ydotool has no wheel
        # command and the grid must scroll).
        inject = None
        if hostos.is_windows():
            from ..inject.win import WinInject, is_admin

            if not is_admin():
                log("error: Genshin runs as administrator; Windows blocks input "
                    "from a non-elevated program. Right-click Lumenspar and "
                    "choose 'Run as administrator'.")
                return
            inject = WinInject()
        else:
            from ..inject.uinput import UinputInject
            from ..inject.ydotool import YdotoolInject

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
        def _on_escape() -> None:
            self._stop_requested = True
            self.logAppended.emit("Escape pressed — stopping after this artifact.")

        if hostos.is_windows():
            from ..inject.win_hotkey import WinEscapeWatcher
            self._esc = WinEscapeWatcher(_on_escape)
        else:
            from ..inject.hotkey import EscapeWatcher
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
        except (RuntimeError, GeminiError) as exc:
            # Scanner construction can raise (e.g. "AI reader selected but no
            # Gemini API key is set") and the AI path re-raises auth/model
            # errors to abort the scan. Log it and end the job cleanly, the
            # same way every other failure surfaces in this function -- never
            # an uncaught exception in the worker thread.
            log(f"error: {exc}")
            return
        finally:
            inject.stop()
            if self._esc is not None:
                self._esc.stop()
                self._esc = None

        if len(self._roster):
            # Showcase readings are exact game data; a screen reading of the
            # same character can only be as good or worse.
            export.characters, kept = enka.merge_characters(
                export.characters, self._roster.to_characters())
            log(f"Characters: {len(self._roster)} from Enka.Network, "
                f"{kept} from the screen scan.")
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

    def _run(self, job, label: str, announce: bool = True) -> None:
        self._scanning = True
        self.scanningChanged.emit()
        self._set_status(f"{label} running…")
        if announce:
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
