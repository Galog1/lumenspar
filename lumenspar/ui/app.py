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

from .. import hostos
from .backend import Backend

QML_DIR = Path(__file__).resolve().parent / "qml"
ICON = Path(__file__).resolve().parents[2] / "install" / "lumenspar.svg"


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    if hostos.is_windows():
        # Microsoft Store Python ignores PATH when resolving DLL dependencies,
        # so Qt's QML plugins cannot find the Qt DLLs beside PySide6 and the
        # window fails to load ('Cannot load library ...plugin.dll').
        os.add_dll_directory(str(Path(PySide6.__file__).parent))
    # Basic is the only style that lets us restyle controls wholesale.
    QQuickStyle.setStyle("Basic")

    app = QGuiApplication(argv)
    app.setWindowIcon(QIcon(str(ICON)))
    app.setApplicationName("Lumenspar")
    app.setOrganizationName("Lumenspar")

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))
    warnings: list[str] = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))

    # Parent to the app: an unparented Backend can be collected while the
    # window still holds bindings to it, which surfaces as 'property of null'.
    backend = Backend(app)
    engine.rootContext().setContextProperty("backend", backend)

    app.aboutToQuit.connect(backend.shutdown)

    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    smoke = os.environ.get("LUMENSPAR_SMOKE_TEST")
    if smoke:
        # Release builds start the packaged app once with this set (and
        # QT_QPA_PLATFORM=offscreen): it proves the bundle carries every QML
        # module and data file the window needs, then exits without showing
        # anything. A windowed .exe has no console, so the report is a file.
        ok = bool(engine.rootObjects()) and not warnings
        report = ["ok" if ok else "FAILED",
                  f"root objects: {len(engine.rootObjects())}",
                  f"icon found: {ICON.exists()}",
                  *(f"warning: {w}" for w in warnings)]
        Path(smoke).write_text("\n".join(report) + "\n", encoding="utf-8")
        return 0 if ok else 1
    if not engine.rootObjects():
        print("failed to load QML", file=sys.stderr)
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
