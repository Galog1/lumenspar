# PyInstaller recipe for the Windows build. Run from the repository root:
#     pyinstaller packaging/windows/lumenspar.spec --noconfirm
# Produces dist/Lumenspar/ (a folder, not a single file: it starts faster and
# is what the Inno Setup installer packages).

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).resolve().parents[1]

# Linux-only backends: they import GStreamer, D-Bus or evdev at module level
# and are never loaded on Windows (ui/backend.py picks the Windows ones).
LINUX_ONLY = ("lumenspar.capture.portal", "lumenspar.inject.uinput",
              "lumenspar.inject.hotkey", "lumenspar.inject.ydotool")

a = Analysis(
    [str(root / "packaging" / "windows" / "launch.py")],
    pathex=[str(root)],
    datas=[
        # The app finds these relative to its own modules, so keep the layout.
        (str(root / "lumenspar" / "ui" / "qml"), "lumenspar/ui/qml"),
        (str(root / "lumenspar" / "gamedata"), "lumenspar/gamedata"),
        (str(root / "install" / "lumenspar.svg"), "install"),
        *collect_data_files("tzdata"),       # zoneinfo has no system database on Windows
    ],
    hiddenimports=collect_submodules(
        "lumenspar", filter=lambda name: not name.startswith(LINUX_ONLY)),
    excludes=["tkinter", "gi", "dbus", "evdev", *LINUX_ONLY],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Lumenspar",
    icon=str(root / "packaging" / "windows" / "lumenspar.ico"),
    console=False,
    # Genshin runs elevated, and Windows drops input that a non-elevated
    # program sends to it -- so the app always asks for administrator rights.
    uac_admin=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Lumenspar")
