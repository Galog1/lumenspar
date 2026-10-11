Lumenspar is a Genshin Impact companion for Linux and Windows. It now opens
on a main menu with two tools.

## New: Wish Counter

Pity, guarantees and 50/50 results for every banner, read from your in-game
wish history, the same way [paimon.moe](https://paimon.moe) does it, but
without its Windows-only PowerShell script.

1. Open the wish history in-game (**Wish → History**).
2. In Lumenspar: **Wish Counter → Import from game**.

Lumenspar finds the game's web cache by itself: on Windows through the
game's log, and on Linux inside An Anime Game Launcher (native or Flatpak),
Lutris, Heroic or another Wine prefix. You can also pick the game folder by
hand or paste a link. Every banner shows its 5★ and 4★ pity, whether the
next 5★ is guaranteed, your 50/50 record, and each 5★ with the pity it came
at.

The game's history only goes back about a year, so Lumenspar keeps every
wish it imports; later imports only add new ones.

**Copy link for paimon.moe** puts a working wish history link on the
clipboard, exactly as paimon.moe's own script would, ready to paste into
its import page. Treat it like a password until it expires: anyone holding
it can read your wish history.

## Inventory Scanner

Unchanged apart from moving onto its own page: it reads artifacts, weapons,
characters and materials off the screen into a `.GOOD` file for Genshin
Optimizer, SEELIE.me and Aspirine's calculator.

> **Pre-release.** The wish counter has been checked against HoYoverse's
> service and with tests, but not yet through a complete import of a real
> history. On Windows, a complete in-game inventory scan has not been run
> yet. Please report what happens on yours, with the log from
> `Documents/Lumenspar/logs/`.

## Linux: `Lumenspar-0.3.0-x86_64.AppImage`

```sh
chmod +x Lumenspar-0.3.0-x86_64.AppImage
./Lumenspar-0.3.0-x86_64.AppImage
```

Needs a 64-bit distribution about as new as Ubuntu 24.04 (Fedora 40+,
Ubuntu 24.04+, Debian 13, Arch and its derivatives). The inventory scanner
captures the screen through the desktop's screen-sharing portal (PipeWire,
any current desktop), sends input through `/dev/uinput`, and has Tesseract
built in. If the AppImage will not start for lack of FUSE, run it with
`--appimage-extract-and-run`.

## Windows: `Lumenspar-Setup-0.3.0.exe`

The installer is not code-signed, so SmartScreen may need **More info → Run
anyway**. Lumenspar asks for administrator rights at every start, because
Genshin runs elevated and Windows drops input from programs that are not.
The Windows inventory scanner reads text with Google's Gemini model, which
needs a free API key from aistudio.google.com/apikey; the wish counter does
not need one. Requires 64-bit Windows 10 or 11.
