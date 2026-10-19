"""Lumenspar GUI entry point."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import PySide6
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from .. import hostos, netcerts
from . import fonts
from .backend import Backend
from .builds_backend import BuildsBackend
from .hoyolab_backend import HoyolabBackend
from .optimizer_backend import OptimizerBackend
from .team_backend import TeamBackend
from .update_backend import UpdateBackend
from .wish_backend import WishBackend

QML_DIR = Path(__file__).resolve().parent / "qml"
ICON = Path(__file__).resolve().parents[2] / "install" / "lumenspar.svg"


_FAULT_FILE = None     # kept open for the life of the process (see main)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    if os.environ.get("LUMENSPAR_SMOKE_TEST"):
        # A crashed self-check run should say where (Python's stack at the fault).
        import faulthandler
        # The packaged Windows app has no stderr (it is a windowed program), and
        # enable() raises without one: the dump goes to a file beside the report.
        global _FAULT_FILE
        _FAULT_FILE = open(os.environ["LUMENSPAR_SMOKE_TEST"] + ".fault.txt", "w",
                           encoding="utf-8")
        faulthandler.enable(file=_FAULT_FILE)
    netcerts.use_system_bundle()   # before any HTTPS request; see netcerts.py
    if hostos.is_windows():
        # Microsoft Store Python ignores PATH when resolving DLL dependencies,
        # so Qt's QML plugins cannot find the Qt DLLs beside PySide6 and the
        # window fails to load ('Cannot load library ...plugin.dll').
        os.add_dll_directory(str(Path(PySide6.__file__).parent))
    # Basic is the only style that lets us restyle controls wholesale.
    QQuickStyle.setStyle("Basic")

    # Qt's embedded browser (the HoYoLAB sign-in window) must be initialised
    # before the application object exists; without it the feature is off.
    try:
        from PySide6.QtWebEngineQuick import QtWebEngineQuick
        QtWebEngineQuick.initialize()
    except ImportError:
        pass

    app = QGuiApplication(argv)
    app.setWindowIcon(QIcon(str(ICON)))
    app.setApplicationName("Lumenspar")
    app.setOrganizationName("Lumenspar")
    if fonts.load():         # every Text item uses the bundled font, whatever the system has
        face = app.font()
        face.setFamily(fonts.FAMILY)
        app.setFont(face)

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))
    warnings: list[str] = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))

    # Parent to the app: an unparented Backend can be collected while the
    # window still holds bindings to it, which surfaces as 'property of null'.
    backend = Backend(app)
    engine.rootContext().setContextProperty("backend", backend)
    wishes = WishBackend(app)
    engine.rootContext().setContextProperty("wishes", wishes)
    cards = BuildsBackend(backend._s, app)
    engine.rootContext().setContextProperty("cards", cards)
    hoyolab = HoyolabBackend(app)
    engine.rootContext().setContextProperty("hoyolab", hoyolab)
    hoyolab.cardsReady.connect(cards.addHoyolab)

    def remember_uid(uid: str, *_rest) -> None:
        # A UID found after sign-in fills the field the other tools share.
        if uid and not backend._s.uid.strip():
            backend.uid = uid
    hoyolab.cardsReady.connect(remember_uid)
    cards.collected.connect(wishes.syncSoon)
    wishes.restoredFromDrive.connect(cards.reload)
    updates = UpdateBackend(
        backend._s, app,
        blocker=lambda: ("a scan is running" if backend.scanning
                         else "a wish import or card read is running" if wishes.busy or cards.busy
                         else ""))
    engine.rootContext().setContextProperty("updates", updates)
    team = TeamBackend(backend._s, app, lazy=True)
    engine.rootContext().setContextProperty("team", team)
    cards.collected.connect(team.reload)
    wishes.restoredFromDrive.connect(team.reload)
    optimizer = OptimizerBackend(backend._s, app, team)
    engine.rootContext().setContextProperty("optimizer", optimizer)
    cards.collected.connect(optimizer.reload)
    wishes.restoredFromDrive.connect(optimizer.reload)

    app.aboutToQuit.connect(backend.shutdown)
    app.aboutToQuit.connect(wishes.shutdown)
    app.aboutToQuit.connect(cards.shutdown)
    app.aboutToQuit.connect(optimizer.shutdown)
    app.aboutToQuit.connect(team.shutdown)

    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    smoke = os.environ.get("LUMENSPAR_SMOKE_TEST")
    if smoke:
        # Release builds start the packaged app once with this set (and
        # QT_QPA_PLATFORM=offscreen): it proves the bundle carries every QML
        # module, data file and library the app needs, then exits without
        # showing anything. A windowed .exe has no console, so the report is a
        # file. Screen capture itself is not exercised: it needs a desktop and
        # the user's screen-share grant, and the Self-test button covers it.
        from PySide6.QtCore import QTimer

        def run_checks() -> None:
            from .. import selfcheck

            checks = selfcheck.bundle_checks()
            ok = (bool(engine.rootObjects()) and not warnings
                  and all(passed for _, passed, _ in checks))
            report = ["ok" if ok else "FAILED",
                      f"root objects: {len(engine.rootObjects())}",
                      f"icon found: {ICON.exists()}",
                      *(f"{'pass' if passed else 'FAIL'}: {name}"
                        + (f" ({detail})" if detail else "")
                        for name, passed, detail in checks),
                      *(f"warning: {w}" for w in warnings)]
            Path(smoke).write_text("\n".join(report) + "\n", encoding="utf-8")
            app.exit(0 if ok else 1)

        QTimer.singleShot(0, run_checks)
        return app.exec()
    if not engine.rootObjects():
        print("failed to load QML", file=sys.stderr)
        return 1
    updates.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
