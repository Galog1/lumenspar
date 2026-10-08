#!/bin/sh
# Wrap dist/Lumenspar (from PyInstaller) into an AppImage.
#     sh packaging/linux/build-appimage.sh <version> <path-to-appimagetool>
# Output: dist/Lumenspar-<version>-x86_64.AppImage
set -eu
VERSION="$1"
APPIMAGETOOL="$2"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
APPDIR="$ROOT/build/AppDir"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib"
cp -a "$ROOT/dist/Lumenspar" "$APPDIR/usr/lib/lumenspar"
cp "$ROOT/packaging/linux/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
cp "$ROOT/install/lumenspar.desktop" "$APPDIR/lumenspar.desktop"
cp "$ROOT/install/lumenspar.svg" "$APPDIR/lumenspar.svg"
ln -s lumenspar.svg "$APPDIR/.DirIcon"

ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" \
    "$ROOT/dist/Lumenspar-$VERSION-x86_64.AppImage"
