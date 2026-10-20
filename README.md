# Lumenspar

A Genshin Impact companion for Linux and Windows, with four tools on its
main menu:

- **Wish Counter** -- pity, guarantees and 50/50 results for every banner, read
  from your in-game wish history (the same method as
  [paimon.moe](https://paimon.moe)).
- **Inventory Scanner** -- reads your artifacts, weapons, characters and
  materials off the screen with OCR and writes a `.GOOD` JSON file that
  [Genshin Optimizer](https://frzyc.github.io/genshin-optimizer/),
  [SEELIE.me](https://seelie.me) and Aspirine's calculator can import.
- **Build Cards** -- [Akasha](https://akasha.cv)-style cards for the characters
  in your profile showcase, read through [Enka.Network](https://enka.network):
  talents, weapon, artifacts with exact roll counts, crit value or roll value
  and final stats, saved as images if you like.
- **Optimizer** -- a simpler [Genshin Optimizer](https://frzyc.github.io/genshin-optimizer/):
  the best artifacts from your scan for any character, by a damage estimate,
  stat weights, target values or a stat ratio.

Built for Wayland first: capture goes through the `xdg-desktop-portal`
ScreenCast API and a PipeWire stream, so it works on KDE, GNOME and wlroots
without X11.

## Download

Ready-made builds are on the [Releases](https://github.com/Galog1/lumenspar/releases)
page:

- **Linux:** `Lumenspar-<version>-x86_64.AppImage`. Make it executable and run
  it; Tesseract, GStreamer and Qt are inside, so none of the requirements
  below apply except PipeWire (any current desktop has it) and `/dev/uinput`
  access. Needs a distribution about as new as Ubuntu 24.04. Built by
  `.github/workflows/linux-release.yml` from `packaging/linux/`.
- **Windows:** `Lumenspar-Setup-<version>.exe`; see
  [Windows](#windows-ai-reader-only) below.

The rest of this section is for running from source.

**Updates.** Lumenspar checks GitHub for a newer release when it starts (and
every few hours while it stays open) and shows a banner when there is one.
**Update now** downloads the release's installer (Windows) or AppImage (Linux),
checks its size and, when GitHub provides one, its SHA-256 checksum, installs it
and restarts Lumenspar; it never runs while a scan or import is going. The main
menu has a **Check for updates** button and a switch to turn the automatic
check off. Only the AppImage and the Windows installer can update themselves; a
source checkout is just pointed at the release page. The first release with
this feature has to be installed by hand once.

## Requirements

- Python 3.12+, Tesseract with English data
- Python packages: PySide6, numpy, Pillow, pytesseract, rapidfuzz, plus the
  GStreamer (`gi`) and `dbus` bindings. Arch:
  `pyside6 python-numpy python-pillow python-pytesseract python-rapidfuzz
  gst-python python-dbus`; Fedora:
  `python3-pyside6 python3-numpy python3-pillow python3-pytesseract
  python3-rapidfuzz python3-gobject gstreamer1 python3-dbus`
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
git clone https://github.com/Galog1/lumenspar.git
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
Linux packages (GStreamer, D-Bus, `/dev/uinput`) are required.

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

## Wish counter

Open the wish history in-game (**Wish → History**), then press **Import from
game**. Opening it leaves the page's link in the game's web cache for about a
day; Lumenspar finds it, checks which cached link still works, and reads every
banner through HoYoverse's wish history API -- the same one the in-game page
uses. This is paimon.moe's method, done locally instead of with a PowerShell
script, so it works on Linux too: the game folder is found inside An Anime Game
Launcher (native or Flatpak), Lutris, Heroic or another Wine prefix, or picked
by hand with **Choose game folder…**. A link can also be pasted directly.

**Copy link for paimon.moe** finds a working link the same way and puts it on
the clipboard in exactly the form paimon.moe's own script produces, ready to
paste into [paimon.moe's wish import](https://paimon.moe/wish/import). Treat it
like a password until it expires: anyone holding it can read your wish
history.

Per banner it shows the 5★ and 4★ pity, whether the next 5★ is guaranteed
to be featured, the 50/50 record, and every 5★ as a portrait tile with the
pity it came at. Portraits are the game's own art from Project Amber
(gi.yatta.moe), downloaded the first time they are needed and cached in
Lumenspar's data folder; they are not shipped with it.
Won or lost is decided against paimon.moe's banner schedule
(`lumenspar/gamedata/wish_banners.json`, refreshed by
`tools/update_gamedata.py`), so a 5★ from a banner newer than that file shows as
*unknown* until the game data is updated.

The API only goes back about a year, so every imported wish is kept in
`~/.local/share/lumenspar/wishes/` (`%LOCALAPPDATA%\lumenspar\wishes` on
Windows) and later imports only add new ones. The link itself, which carries a
temporary key to your wish history, is never saved.

### Google Drive backup (optional)

Like paimon.moe, the wish history can be kept in your Google Drive, so a
reinstall or another computer gets it back: press **Sign in with Google** on
the wish counter page. Lumenspar has no server; the backup goes straight from
your computer to your Drive.

Release builds sign in through Lumenspar's own Google project. Its client is
written into the build from the `LUMENSPAR_GOOGLE_CLIENT` repository secret
(the JSON the Google Cloud console downloads for a Desktop app client) and is
never committed. To use the same client when running from source, save that
JSON as `lumenspar/google_client.json`, which is git-ignored.

Without it -- in a source checkout or a fork -- or by choice (**Use your own
Google project**), you connect a free Google Cloud project of your own. The
setup guide on the wish counter page walks through it step by step, with
buttons that open each console page; when something goes wrong, the message
names the step that fixes it and the guide highlights it. Google only
publishes a project that has a homepage, a privacy policy and terms of
service on an authorized domain, so the guide offers Lumenspar's own
([docs/](docs/), served at https://galog1.github.io/lumenspar/).

The backup also holds the build cards and a ready-to-show summary per
account, which the [web viewer](https://galog1.github.io/lumenspar/app/)
([docs/app/](docs/app/)) renders in any browser, phone included: it signs in
with Google in the browser, reads that summary from the same hidden folder
and has no server of its own. It needs a *Web application* OAuth client in
the same Google project (authorized JavaScript origin
`https://galog1.github.io`), whose public client ID goes in
`docs/app/config.js`.

Lumenspar only asks for its own hidden app-data folder in Drive (it cannot
see any of your files) and your email address (to show who is signed in).
Each account is stored there as `wishes-<uid>.json`. Syncing merges both
copies by wish id (build cards: the newest reading of each character), so
neither side loses anything. It runs on startup, after
every import, and from **Back up now**. The sign-in, and the client ID and
secret of a project of your own, are kept in `google_drive.json` in the
config folder, readable only by you.

## Build cards

Enter your UID and press **Fetch showcase**. Lumenspar reads the characters in
your in-game profile showcase through Enka.Network (turn on **Show Character
Details** in your profile) and draws a card for each:

- level, friendship, constellations, and talent levels including constellation
  bonuses (marked in the element's colour);
- the weapon with its level, refinement and stats;
- every artifact with its main stat, substats and **how many times each
  substat rolled** -- exact, because the showcase lists every roll an
  artifact received -- plus each artifact's score (see below);
- the character's final stats as the game reports them, the build's total
  score and active set bonuses.

The card is drawn on the character's own splash art, with a halo and rings in
the element's colour. Switch the artifact score with **CV / RV** under the card:

- **CV**, crit value: 2 × CRIT Rate + CRIT DMG from substats;
- **RV**, roll value: every substat the build uses as a percentage of the best
  single roll that stat can get on a 5-star artifact, so 100% is one perfect
  roll and 250% two and a half. What counts follows the build: CRIT Rate and
  CRIT DMG always, the scaling stat its sands, goblet and circlet point at
  (ATK%, HP%, DEF% or Elemental Mastery; ATK% if they say nothing), and Energy
  Recharge when a main stat asks for it. Counted stats follow a per-character table
  (`gamedata/rv_stats.json`, refreshed with `tools/update_rv_stats.py`) and fall
  back to this rule. Flat stats and the rest are listed
  with their own roll value but left out of the totals; the card names what it
  counted.

The art is downloaded the first time a character is shown (the one on screen
first), and the card's backdrop is composed from it once and kept next to the
other cached images, about 200 KB per character.

The showcase holds a limited number of characters, so Lumenspar keeps every
character it has seen for that UID: swap others in, let the game publish the
showcase (going to the title screen and back is quickest), and fetch again.
Enka.Network caches a showcase for a short while; the button counts down until
a fresh one is available. **Save card as image** writes a 2400×1280 PNG to
`cards/` in the export folder.

### Every character, through HoYoLAB

The showcase shows only a few characters. **Sign in to HoYoLAB** (on the *All
characters* card) reads **every** character on the account from HoYoLAB's
battle chronicle -- the same data its own character pages show: weapon,
artifacts with how many times each substat rolled, constellations, talent
levels and the stats panel -- and makes a card for each. It covers global
accounts (UIDs starting with 6, 7, 8 or 9); characters without artifacts get a
card without them.

HoYoLAB answers these requests only to a signed-in account, so Lumenspar opens
a window with HoYoLAB's own sign-in page. There you sign in, press **Fetch my
characters**, and the window reads the list and closes. About your sign-in:

- your password is typed into HoYoLAB's page; Lumenspar's code never reads
  form fields, cookies or page storage, and sends nothing anywhere but HoYoLAB;
- the window uses an off-the-record browser profile: its cookies and other
  site data exist in memory only and are gone when the window closes, so
  nothing about the sign-in is written to disk, and you sign in again next
  time. (Chromium keeps its usual, empty certificate store in your home
  folder.) The tests check that the window's profile can never be a
  persistent one;
- only the parsed build cards are stored, in the same collection as the
  showcase's.

When a character has the same build in both sources, the card keeps HoYoLAB's
data and Enka's exact extras (the raw stat panel the optimizer needs, base
talent levels); a character whose build differs takes the newer reading. HoYoLAB
shows talent levels as in-game, with constellation bonuses included and not
marked, and does not give the optimizer's raw stats, so HoYoLAB-only characters
are not offered to the optimizer or in Team & damage until the showcase has
read them. The endpoints are unofficial and may change; Lumenspar reads them
defensively and says what it could not use. Embedded-browser caveat: some
"Continue with Google/Apple" HoYoLAB sign-ins refuse embedded browsers; email
and password works. Qt WebEngine adds roughly 150-250 MB to the app and is
optional when running from source (the button then says it is unavailable).

Art (portraits, splash art, weapon and artifact icons) comes from Project Amber
and is downloaded once, when first needed. Unlike Akasha, there are no
leaderboards: those compare builds across many players on a server, and
Lumenspar has none.

## Optimizer

Pick a character from your build cards, a scaling stat, priority stats and the
main stats you accept on sands, goblet and circlet, and Lumenspar searches your
scanned artifacts (the .GOOD export) for the best **4-piece set plus an
off-piece** from any set. It optimizes for one of:

- **Damage estimate** -- scaling stat × (1 + CRIT Rate × CRIT DMG) × (1 + DMG Bonus);
- **Stat weights** -- a weight per priority stat, scored in maximum rolls;
- **Target values** -- reach every target as evenly as possible, then the most damage;
- **Ratio** -- keep two stats balanced, e.g. CRIT Rate : CRIT DMG = 1 : 2;

with optional minimums (e.g. Energy Recharge ≥ 160%). Combat CRIT Rate is the
panel value plus **conditional CRIT Rate** -- read from the set bonus and the
weapon's passive at its refinement, plus whatever you add for team buffs --
capped at 100%, so panel crit beyond that cap is worth nothing.

The character's own stats come from the showcase: the game's totals minus the
equipped artifacts and set bonuses, which reproduces the in-game panel exactly
when the artifacts are put back. The search drops every piece that is no
better than another in all the stats the goal uses, which keeps it exact and
fast (well under a second for a few hundred artifacts). Results show as build
cards next to the current build, with the stat changes and who wears each
piece now.

**Akasha ranking** optimizes for one of the character's [Akasha](https://akasha.cv)
leaderboards, which you pick from the list (for the weapon you use, with an
optional ER requirement); nothing else needs choosing. Akasha's formulas
aren't public, but it scores every build with the character reset to the
same level, constellation, weapon and team, so a leaderboard's result depends
only on the build's stats. Lumenspar samples about 200 builds around your own
result and learns the formula from them (scaling stat, crit, DMG bonus and,
for reactions, Elemental Mastery), takes the 4-piece sets and main stats the
top builds use, searches your artifacts with each of those sets, and asks
Akasha for the exact rank each suggestion would get. When Akasha's copy of
your build matches your showcase, predictions are calibrated to your actual
result. The page says how closely the formula reproduces the sample: most
leaderboards come within about 2.5%, while calculations that combine several
characters' damage (such as Lunar reactions) are flagged as rough.

In **Target values** mode, **Use Akasha's top 1% averages** fills the targets
with the average stats of the top 1% of the character's leaderboard (the
numbers behind Akasha's build graphs), shifted onto your in-game panel's scale
-- Akasha measures a standardised C0 character with an R1 weapon, so its stats
differ from your panel by a fixed amount it reports for your own build.
Build cards show each character's Akasha rank, read from your live build.

Akasha has no documented API: Lumenspar uses the endpoints its own site uses,
sparingly (your builds and their ranks, cached for an hour; a leaderboard
list and four leaderboard pages per leaderboard, cached for a day; one small
request per suggested build for its rank; only when you ask), and keeps only stats,
4-piece sets and results from leaderboards -- never other players' UIDs or
names. If Akasha changes its site, these features stop with a message until
Lumenspar is updated.

Unlike Genshin Optimizer it does not model talents, reactions, team buffs or
conditional effects other than CRIT Rate: it ranks artifacts, not rotations.
Characters whose passives convert one stat into another (e.g. ER into DMG
Bonus) come out approximately.

## Team & damage

The Optimizer's **Team & damage** tab calculates damage the way
[Genshin Optimizer](https://frzyc.github.io/genshin-optimizer/) does -- with the
same formula engine its website runs, so every character's talents, passives and constellations,
weapon stats and passives, artifact sets, elemental resonance, team buffs,
enemy level and resistance and amplifying/catalyze reactions are included, as
GO models them.

- **Team:** up to four characters, picked from **My characters** (showcase
  builds as they are, or scanned characters with what they have equipped) or
  **All characters** -- every character in the game, with the level,
  constellation, talents, weapon and refinement you set (and no artifacts).
- **Conditions:** every conditional the team can have, as a compact tile with a
  checkbox (or a choice such as a stack count or the element swirled), grouped
  by character, weapon, set and resonance, with Genshin Optimizer's wording.
- **Damage:** each character's final stats and every damage instance, as an
  average, a crit or a non-crit hit.
- **Akasha combo:** the combo an [Akasha.cv](https://akasha.cv) leaderboard
  ranks the character by (which hits, how many times, and partial shares such
  as "Lunar-Charged DMG (60%)"), recomputed with your team. Akasha doesn't
  publish rotation lengths, so this is damage per combo rather than DPS.

The Optimize tab's **Team damage** mode searches your artifacts for the build
that maximizes one of a character's hits, or their Akasha combo, with that
team, its conditions and the enemy -- exact damage, not an estimate. It works
the way Genshin Optimizer's own solver does: the target is folded over the
team calculation so that only the character's artifact stats and set counts
remain free, pruned, compiled into a plain function, and evaluated for every
combination of a 4-piece set plus an off-piece (a few hundred to tens of
thousands of builds in about a second). The character's equipped artifacts are
always among the candidates, so a suggestion is never worse than what they wear,
even when the inventory scan is older than the showcase.

The engine is bundled by `tools/build_go_engine.py` from a pinned Genshin
Optimizer commit (its `gi/wr`, `gi/sheets` and `gi/uidata` libraries, with the
website's React/MUI parts replaced by an inert stub) and runs in Qt's own
JavaScript engine (about 0.3 s per calculation), so neither Lumenspar nor its
builds need Node.js. The script also works around Qt's older JavaScript engine
and writes GO's English texts to `go_locale.json` for the labels.

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
mid-read. Talent and level reading are measured against real 4K captures.
Accuracy degrades below 1080p, where some talent levels can still
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
- The wish counter follows [paimon.moe](https://github.com/MadeBaruna/paimon-moe)'s
  method, and `lumenspar/gamedata/wish_banners.json` is generated from its
  banner data: Copyright (c) 2021 Made Baruna, MIT License.
- `lumenspar/gamedata/go_engine.js` and `go_labels.json` are built by
  `tools/build_go_engine.py` from [Genshin Optimizer](https://github.com/frzyc/genshin-optimizer)'s
  formula engine, game data and English text: Copyright (c) frzyc and the
  Genshin Optimizer contributors, MIT License (`lumenspar/gamedata/GO_LICENSE.txt`).
- `lumenspar/fonts/` is [Inter](https://github.com/rsms/inter) 4.1 (Regular,
  SemiBold and Bold), Copyright (c) 2016 The Inter Project Authors, under the
  SIL Open Font License 1.1 (`lumenspar/fonts/OFL.txt`).
