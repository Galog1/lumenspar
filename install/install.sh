#!/bin/sh
# Install the Lumenspar launcher, menu entry and icon into ~/.local.
#
# The project runs from its source tree rather than being installed as a
# package, so the launcher only needs to know where that tree is. This bakes
# the current checkout's path in as the default, which means the repo can live
# anywhere -- not just ~/lumenspar.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

BIN="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons"

mkdir -p "$BIN" "$APPS" "$ICONS"

sed "s|\${LUMENSPAR_HOME:-\$HOME/lumenspar}|\${LUMENSPAR_HOME:-$ROOT}|" \
    "$ROOT/install/lumenspar" > "$BIN/lumenspar"
chmod +x "$BIN/lumenspar"

# Its own file name: AppImage tools (Gear Lever, AppImageLauncher) install the
# AppImage's entry as lumenspar.desktop, which would replace this one. Exec is
# the launcher's full path, since desktop sessions may not have ~/.local/bin on
# their PATH.
sed -e "s|^Name=Lumenspar$|Name=Lumenspar (local build)|" \
    -e "s|^Exec=lumenspar$|Exec=$BIN/lumenspar|" \
    "$ROOT/install/lumenspar.desktop" > "$APPS/lumenspar-local.desktop"
cp "$ROOT/install/lumenspar.svg"     "$ICONS/lumenspar.svg"

echo "installed:"
echo "  $BIN/lumenspar            (project root: $ROOT)"
echo "  $APPS/lumenspar-local.desktop"
echo "  $ICONS/lumenspar.svg"

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo; echo "note: $BIN is not on your PATH -- add it to run 'lumenspar' by name." ;;
esac
