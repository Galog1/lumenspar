# Lumenspar

A Linux inventory scanner for Genshin Impact. It reads your artifacts, weapons,
characters and materials off the screen with OCR and writes a `.GOOD` JSON file
that [Genshin Optimizer](https://frzyc.github.io/genshin-optimizer/),
[SEELIE.me](https://seelie.me) and Aspirine's calculator can import.

Built for Wayland first: capture goes through the `xdg-desktop-portal`
ScreenCast API and a PipeWire stream, so it works on KDE, GNOME and wlroots
without X11.

## Requirements

- Python 3.12+, Tesseract with English data
- `pyside6 python-pytesseract python-rapidfuzz gst-python` (Arch names)
- Genshin Impact running **fullscreen** at **16:9 or 16:10**, English UI,
  control type set to **Keyboard**

## Setup from a clean checkout

```sh
git clone <this repo> lumenspar
cd lumenspar
sh install/install.sh
```

The scanner itself has no build step -- it runs from the source tree. Only the
system packages under Requirements need installing separately; they are not
vendored here.

## Run

Installed launcher (also appears in the application menu as **Lumenspar**):

```sh
lumenspar
```

Or straight from the source tree:

```sh
cd ~/lumenspar && python3 -m lumenspar
```

`install/install.sh` puts the launcher, menu entry and icon into `~/.local`,
baking in the path of whatever checkout it is run from -- the repo does not
have to live at `~/lumenspar`. `LUMENSPAR_HOME` still overrides it at runtime.

Press **Run self-test** first: it confirms Tesseract, the matcher and the
capture stream, and reports the resolution and aspect ratio actually being
captured.

## Notes on resolution

Lumenspar always works in *native* pixels. A scaled display reports a smaller
logical size through the portal (a 4K panel at 150% advertises 2560x1440), but
the PipeWire stream still carries full-resolution frames, so the frame itself
is treated as the source of truth. Higher native resolution means better OCR.

## Updating game data after a patch

```sh
python3 tools/update_gamedata.py
```

This rebuilds `lumenspar/gamedata/*.json` by joining Genshin Optimizer's key
vocabulary (authoritative for `.GOOD` keys) with Project Amber's English names.
Items one source knows and the other does not are kept and flagged rather than
dropped -- an item missing from the OCR vocabulary does not fail loudly, it
fuzzy-matches to the nearest wrong entry and quietly corrupts the export.

## Repository layout

- `lumenspar/` -- the application (capture, OCR, per-category scanners, UI)
- `lumenspar/gamedata/` -- generated name/key vocabularies, rebuilt by `tools/`
- `calib/` -- full-resolution reference screenshots the screen regions were
  measured against, plus a sample `.GOOD` export. These are the bulk of the
  repository's size; nothing at runtime reads them.
- `install/` -- launcher, desktop entry and icon

## Status

Capture, OCR, matching, GOOD export, settings and the UI are working, and all
four per-category scanners are calibrated against the screenshots in `calib/`.

Character scanning is the most demanding path, because Genshin's background art
drifts slowly behind the text and can push a bright gradient under a number
mid-read. Talent and level reading are measured against the saved failure
dumps at 4K. Accuracy degrades below 1080p, where some talent levels can still
be read wrongly rather than refused -- prefer scanning at the highest native
resolution available.

Several entries on the character screen carry a *player-chosen* name -- the
Traveler, a renamed Wanderer, and the Manekins -- so they cannot be matched
against the shipped vocabulary. These are reported by name rather than guessed
at; set `traveler_name` in the settings so the Traveler can be keyed.

## License

[MIT](LICENSE) -- use it, fork it, ship it, sell it. The one condition is that
the copyright notice stays with the code, so credit travels with it.

That covers the source in this repository. Two things in the tree are not mine
to license:

- `calib/` holds screenshots of Genshin Impact. The game and its assets are
  © HoYoverse; the screenshots are here only as the measurement reference the
  screen regions were derived from.
- `lumenspar/gamedata/` is generated, not authored -- `tools/update_gamedata.py`
  builds it by joining Genshin Optimizer's key vocabulary with Project Amber's
  English names. Check those projects' own terms before redistributing it.
