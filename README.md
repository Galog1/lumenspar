# Lumenspar

An inventory scanner for Genshin Impact (Linux; Windows with the AI reader). It reads your artifacts, weapons,
characters and materials off the screen with OCR and writes a `.GOOD` JSON file
that [Genshin Optimizer](https://frzyc.github.io/genshin-optimizer/),
[SEELIE.me](https://seelie.me) and Aspirine's calculator can import.

Built for Wayland first: capture goes through the `xdg-desktop-portal`
ScreenCast API and a PipeWire stream, so it works on KDE, GNOME and wlroots
without X11.

## Requirements

- Python 3.12+, Tesseract with English data
- Python packages: PySide6, numpy, Pillow, pytesseract, rapidfuzz, plus the
  GStreamer (`gi`), `dbus` and `evdev` bindings. Arch:
  `pyside6 python-numpy python-pillow python-pytesseract python-rapidfuzz
  gst-python python-dbus python-evdev`; Fedora:
  `python3-pyside6 python3-numpy python3-pillow python3-pytesseract
  python3-rapidfuzz python3-gobject gstreamer1 python3-dbus python3-evdev`
  (the Fedora set is what this was developed on; the Arch names are
  untested).
  `pyproject.toml` lists the pip-installable subset.
- Write access to `/dev/uinput` (usually membership of the `input` group, or
  a udev rule) so key and mouse events can be injected.
- Genshin Impact running **fullscreen** at **16:9 or 16:10**, English UI,
  control type set to **Keyboard**, inventory on **B** and character screen
  on **C** (or set your own keys in the settings column)

Lumenspar only reads the screen and sends ordinary key and mouse events; it
does not read game memory, touch game files or intercept network traffic.
Even so, automated input is against HoYoverse's Terms of Service. The risk
of acting on that is yours.

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

## Windows (AI reader only)

Windows is supported with the AI reader only; Tesseract is not used or needed.
Screen capture goes through `mss` and input through `SendInput`, so none of the
Linux packages (GStreamer, D-Bus, evdev, `/dev/uinput`) are required.

**Installer:** download `Lumenspar-Setup-<version>.exe` from the
[Releases](https://github.com/Galog1/lumenspar/releases) page. It is built by
`.github/workflows/windows-release.yml` (PyInstaller + Inno Setup) whenever a
`v*` tag is pushed; `packaging/windows/` holds the recipe. The app asks for
administrator rights on every start, for the reason below. The installer is
not code-signed, so SmartScreen may need "More info → Run anyway".

**From source:** install into a virtual environment inside the checkout. PySide6 has very deep
file paths, and installing it under Microsoft Store Python's own folder can
exceed Windows' 260-character path limit and leave it half-installed:

```bat
cd lumenspar
python -m venv .venv
.venv\Scripts\python -m pip install PySide6 numpy Pillow rapidfuzz mss tzdata
.venv\Scripts\python -m lumenspar
```

or right-click `install\lumenspar.bat` and choose **Run as administrator**; it
uses `.venv` when present. Then:

- **Run it as administrator.** Genshin runs elevated, and Windows silently
  drops input sent to it by a non-elevated program. Lumenspar refuses to start
  a scan otherwise.
- Set Genshin to **Windowed Fullscreen** (borderless). Exclusive fullscreen can
  capture as a black frame; Lumenspar reports this if it happens.
- Add a Gemini API key in the Reader card (see below). Settings live in
  `%APPDATA%\lumenspar`.
- Press **Escape** to stop a scan.

Checked on Windows 11 (3840x2160 at 150% scaling, two monitors): the test
suite, the window, screen capture and mouse placement. A full live scan on
Windows has not been run yet.

## AI reader (optional)

Text on each panel can also be read by Google's **Gemini** vision model
instead of Tesseract. The *Reader* card at the top of the settings column
switches between the two:

- **Local OCR** -- Tesseract on this machine. Offline, free, slower on
  stylised text.
- **AI (Gemini)** -- Google's vision model reads each panel, batched several
  panels per request. Needs your own free API key; far better on stylised
  text. Tesseract is *not* used in this mode, so it does not need to be
  installed.

To get a key: create one for free at <https://aistudio.google.com/apikey>
(no card needed) and paste it into the *Gemini API key* field in Settings, or
export `LUMENSPAR_GEMINI_KEY` (the environment variable wins over the stored
key). The stored key is saved in `~/.config/lumenspar/config.json`, which
Lumenspar writes with `0600` permissions.

What is sent: only the cropped detail panels and character pages the scanner
is reading -- never the UID corner, never the full screen. Keep in mind that
Google may use free-tier requests to improve its models (users in the
EEA/UK/Switzerland get paid-tier terms instead); use a paid key if that
matters to you.

The free tier is rate-limited and Google no longer publishes fixed numbers:
recently Flash-Lite was roughly 15 requests a minute and a few hundred a day
(the limits change, so check what AI Studio shows for your project -- the
counters reset at midnight Pacific time). Lumenspar sends 6 panels per
request, so a typical inventory (150 artifacts, 120 weapons, 100 characters)
is about 65 requests. Run self-test in AI mode to see the current model's
health and how many requests have been used today.

AI mode keeps every pixel-derived fact -- artifact rarity, the lock badge,
the elixir band, the weapon refinement badge, constellations -- read by the
same pure-numpy readers as before; only the *text* goes to the model. And
that text still passes the same roll-table and vocabulary validation as OCR
output, so a hallucinated digit is refused, not exported.

Check the reader against your own saved screenshots without a full scan:

```sh
python3 tools/ai_eval.py --kind artifacts calib/Artifacts/*.png
python3 tools/ai_eval.py --kind weapons calib/Weapons/*.png
```

This makes real Gemini requests (billed against your free quota) and reports
each panel through the same validation the scanner runs.

## Characters from Enka.Network

Character data can come from your in-game profile showcase via
[Enka.Network](https://enka.network) instead of the screen: exact level,
ascension, constellation and talent levels, with no OCR involved. Enter your
UID in the *Characters from Enka.Network* card and turn on **Show Character
Details** in your profile.

The showcase only holds a handful of characters, so rotate them through it:
after each change, exit to the title screen and back so the game publishes it.
*Watch showcase* re-fetches every minute (Enka serves cached data for that
long), and the characters collected so far are kept between runs. They replace
screen-scanned readings of the same characters in every export, or can be
written straight into the existing export file without a scan.

Manekins cannot be imported this way: their talents depend on the element you
gave them, which Enka's tables do not cover.

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
at; set the Traveler's (and, if renamed, the Wanderer's) name in the settings
so they can be keyed. Manekins cannot be keyed at all, but list their names
under *Other renamed characters* anyway: a name one glyph away from the
Traveler's (say "Gal" and "Gal1") is then refused as ambiguous instead of
being quietly exported under the wrong character.

Genshin Optimizer's key list lags new game content by a patch or so; items
it does not know yet are reported as unmatched rather than exported under a
guessed key. Re-run `tools/update_gamedata.py` once it catches up.

## Troubleshooting

Every refusal is logged with the item and the reason, and the frame that
caused it is saved under `~/Documents/Lumenspar/failures/` (next to the
export). That folder is the evidence for any bug report or fix: a change to
a reader is only accepted if it is measured against those frames and the
`calib/` references, not because it looks right on one screenshot.

Common causes, in rough order of likelihood:

- *Everything is refused* -- the game is not fullscreen, not 16:9/16:10, or
  the portal picked the wrong screen. **Run self-test** reports what is
  actually being captured.
- *Inputs do nothing* -- no write access to `/dev/uinput`, or the game's
  control type is not Keyboard. Alt-tabbing the game away mid-scan also
  loses the keys.
- *Level or talent numbers refused* -- the background art pushed a bright
  gradient under the text. The scanner retries on its own; a persistent
  refusal is worth a saved frame.
- *Character scan skips someone* -- a player-named character without its
  name in settings, or a Manekin (see above).
- *Gemini (AI mode): the API key was refused* -- Google rejected the key
  (self-test says *the Gemini API key was refused*). Re-create it at
  aistudio.google.com/apikey and paste the new one; the old key stops working
  the moment you create a replacement.
- *Gemini (AI mode): model does not exist* -- the model id in Settings is
  stale or wrong (self-test says *the model does not exist or is not
  available to this key*). Update it to the current Flash-Lite id shown at
  aistudio.google.com.
- *Gemini (AI mode): quota exhausted* -- free tier is rate-limited; the
  scanner retries and then reports a 429. Wait for the midnight-Pacific
  reset, or use a paid key.
- *Gemini (AI mode): scan aborts with "AI reader selected but no Gemini API
  key is set"* -- the key is missing in Settings *and* `LUMENSPAR_GEMINI_KEY`
  is not exported. Add one or the other.

## Tests

```sh
python3 -m pytest -q
```

The suite covers the text-to-data layer (OCR string parsing, roll-table
validation, name matching, GOOD export) and needs no game, screenshots or
Tesseract. The image readers themselves are verified only against `calib/`
and the saved failure frames.

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
