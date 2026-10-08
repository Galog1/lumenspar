# PyInstaller recipe for the Linux build, packaged as an AppImage by
# packaging/linux/build-appimage.sh. Run from the repository root on the build
# machine (CI uses Ubuntu 24.04, with Tesseract, GStreamer and PyGObject from
# apt -- see .github/workflows/linux-release.yml):
#     pyinstaller packaging/linux/lumenspar.spec --noconfirm

import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).resolve().parents[1]

# Tesseract and its English data ship inside the bundle, so OCR is the same on
# every host (ocr/engine.py points pytesseract at them when frozen).
tesseract = shutil.which("tesseract")
tessdata = next(p for p in (Path("/usr/share/tesseract-ocr/5/tessdata"),
                            Path("/usr/share/tesseract/tessdata"),
                            Path("/usr/share/tessdata"))
                if (p / "eng.traineddata").exists())

WINDOWS_ONLY = ("lumenspar.capture.win", "lumenspar.inject.win")

a = Analysis(
    [str(root / "packaging" / "launch.py")],
    pathex=[str(root)],
    binaries=[(tesseract, "tesseract")],
    datas=[
        (str(root / "lumenspar" / "ui" / "qml"), "lumenspar/ui/qml"),
        (str(root / "lumenspar" / "gamedata"), "lumenspar/gamedata"),
        (str(root / "install" / "lumenspar.svg"), "install"),
        (str(tessdata / "eng.traineddata"), "tesseract/tessdata"),
    ],
    hiddenimports=collect_submodules(
        "lumenspar", filter=lambda name: not name.startswith(WINDOWS_ONLY)),
    hooksconfig={
        "gi": {"module-versions": {"Gst": "1.0", "GstApp": "1.0", "GstVideo": "1.0"}},
        # Only the elements capture/portal.py builds its pipeline from:
        # pipewiresrc, videoconvert, capsfilter (coreelements) and appsink.
        "gstreamer": {"include_plugins": ["pipewire", "videoconvertscale",
                                          "coreelements", "app"]},
    },
    excludes=["tkinter", "mss", *WINDOWS_ONLY],
    noarchive=False,
)

# Use the host's libpipewire rather than bundling the build machine's. It
# loads its own plugins and config from distro-specific paths, so a bundled
# copy goes looking for Ubuntu's layout and fails elsewhere -- while every
# desktop that can screen-share has a libpipewire matching its own daemon.
a.binaries = [b for b in a.binaries if not Path(b[0]).name.startswith("libpipewire-0.3")]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Lumenspar", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Lumenspar")
