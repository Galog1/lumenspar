Lumenspar is a Genshin Impact companion for Linux and Windows: a wish
counter with pity and 50/50 tracking, an inventory scanner that exports
`.GOOD` files, build cards, and an artifact optimizer with team damage.

## New in 0.3.3

- **Every character, through HoYoLAB.** The showcase only holds a few
  characters; **Sign in to HoYoLAB** (Build Cards page) reads every character
  on your account -- weapon, artifacts with roll counts, constellations,
  talents and stats -- and makes a card for each. You sign in on HoYoLAB's own
  page, in a window inside Lumenspar that keeps nothing: its browser profile
  is off the record, so the sign-in is never written to disk, and Lumenspar
  never reads your password, cookies or page storage. Characters the showcase
  also covers keep Enka.Network's exact stats. Characters seen only through
  HoYoLAB can't be used in the Optimizer or Team & damage until the showcase
  has read them. Global accounts only (UIDs starting with 6, 7, 8 or 9). This
  adds Qt's embedded browser, so the download is a good deal larger.
- **Redesigned build cards.** Each card sits on its character's splash art with
  a halo and rings in the element's colour, on consistent margins with nothing
  clipped; the character you are looking at gets its art first, and the
  Traveler finally has art too. Cards without artifacts say so.
- **Roll value.** A **CV | RV** switch under the card changes the artifact
  score. CV is crit value; RV counts every substat the build uses as a
  percentage of the best possible roll (100% is one perfect roll), with
  per-substat values and a total, and the card says what it counted.
- **A scrolling character strip** instead of a wall of 95 chips, so the card
  stays in reach.
- **The Inter font ships with the app,** so Linux and Windows draw the
  interface and the saved card images the same way (SIL Open Font License).

> **Pre-release.** On Windows, a complete in-game inventory scan has not
> been run yet. Please report what happens on yours, with the log from
> `Documents/Lumenspar/logs/`.

## Linux: `Lumenspar-0.3.3-x86_64.AppImage`

```sh
chmod +x Lumenspar-0.3.3-x86_64.AppImage
./Lumenspar-0.3.3-x86_64.AppImage
```

Needs a 64-bit distribution about as new as Ubuntu 24.04 (Fedora 40+,
Ubuntu 24.04+, Debian 13, Arch and its derivatives). The inventory scanner
captures the screen through the desktop's screen-sharing portal (PipeWire,
any current desktop), sends input through `/dev/uinput`, and has Tesseract
built in. If the AppImage will not start for lack of FUSE, run it with
`--appimage-extract-and-run`.

## Windows: `Lumenspar-Setup-0.3.3.exe`

The installer is not code-signed, so SmartScreen may need **More info → Run
anyway**. Lumenspar asks for administrator rights at every start, because
Genshin runs elevated and Windows drops input from programs that are not.
The Windows inventory scanner reads text with Google's Gemini model, which
needs a free API key from aistudio.google.com/apikey; the wish counter does
not need one. Requires 64-bit Windows 10 or 11.
