Lumenspar is a Genshin Impact companion for Linux and Windows: a wish
counter with pity and 50/50 tracking, an inventory scanner that exports
`.GOOD` files, build cards, and an artifact optimizer with team damage.

## New in 0.3.2

- **Build Cards.** Akasha-style cards of the characters in your Enka.Network
  profile showcase: stats, artifacts with their roll counts, talents, weapon
  and set bonuses, with each build's live Akasha.cv leaderboard rank.
- **Optimizer.** Finds the best artifacts from your inventory scan for a
  character: the best 4-piece set plus an off-piece, with main-stat choices,
  stat minimums and conditional crit taken into account. Optimize by stat
  weights, target values, a stat ratio, the average of Akasha's top 1%, or a
  whole Akasha leaderboard (the sets and main stats follow from it).
- **Team & damage.** Build a team of up to four from your characters or the
  full roster and see each character's exact damage per hit, calculated with
  Genshin Optimizer's own engine: talents, passives, constellations, weapons,
  artifact sets, resonance and team buffs, with every conditional buff as a
  checkbox. Includes the combo Akasha ranks the character by, recomputed with
  your team, and the Optimizer can search for the artifacts that maximize it.
  Nothing is typed in: every setting is a choice.
- **Web viewer.** Your Drive backup (wishes and build cards) can be viewed at
  galog1.github.io/lumenspar/app from any browser, signed in with the same
  Google account.
- **Fix: a Google sign-in that left out the Drive permission** now explains
  what happened instead of failing with "insufficient scopes".

> **Pre-release.** On Windows, a complete in-game inventory scan has not
> been run yet. Please report what happens on yours, with the log from
> `Documents/Lumenspar/logs/`.

## Linux: `Lumenspar-0.3.2-x86_64.AppImage`

```sh
chmod +x Lumenspar-0.3.2-x86_64.AppImage
./Lumenspar-0.3.2-x86_64.AppImage
```

Needs a 64-bit distribution about as new as Ubuntu 24.04 (Fedora 40+,
Ubuntu 24.04+, Debian 13, Arch and its derivatives). The inventory scanner
captures the screen through the desktop's screen-sharing portal (PipeWire,
any current desktop), sends input through `/dev/uinput`, and has Tesseract
built in. If the AppImage will not start for lack of FUSE, run it with
`--appimage-extract-and-run`.

## Windows: `Lumenspar-Setup-0.3.2.exe`

The installer is not code-signed, so SmartScreen may need **More info → Run
anyway**. Lumenspar asks for administrator rights at every start, because
Genshin runs elevated and Windows drops input from programs that are not.
The Windows inventory scanner reads text with Google's Gemini model, which
needs a free API key from aistudio.google.com/apikey; the wish counter does
not need one. Requires 64-bit Windows 10 or 11.
