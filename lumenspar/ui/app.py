"""Lumenspar GUI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from .backend import Backend

QML_DIR = Path(__file__).resolve().parent / "qml"
ICON = Path(__file__).resolve().parents[2] / "install" / "lumenspar.svg"


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    # Basic is the only style that lets us restyle controls wholesale.
    QQuickStyle.setStyle("Basic")

    app = QGuiApplication(argv)
    app.setWindowIcon(QIcon(str(ICON)))
    app.setApplicationName("Lumenspar")
    app.setOrganizationName("Lumenspar")

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))

    # Parent to the app: an unparented Backend can be collected while the
    # window still holds bindings to it, which surfaces as 'property of null'.
    backend = Backend(app)
    engine.rootContext().setContextProperty("backend", backend)

    app.aboutToQuit.connect(backend.shutdown)

    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        print("failed to load QML", file=sys.stderr)
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
