Lumenspar is a Genshin Impact companion for Linux and Windows: a wish
counter with pity and 50/50 tracking, and an inventory scanner that exports
`.GOOD` files.

## New in 0.3.1

- **Google Drive backup.** Like paimon.moe, the wish history can be kept in
  your own Google Drive, so a reinstall or another computer gets it back.
  It syncs on startup, after every import, and with **Back up now**. It uses
  a free Google Cloud project of your own. The **Setup guide** on the wish
  counter page walks through it, with a button for each console page, and
  errors point back to the step that fixes them. Lumenspar can only see its
  own hidden folder in your Drive.
- **5★ portraits.** Every 5★ pull is shown as a portrait tile with its pity
  and 50/50 result. Portraits are downloaded once and cached.
- **Fix (Windows): wish import failed with "Permission denied"** while the
  game was running, because the game keeps its web cache file locked. Lumenspar
  now reads it the way Windows' own copy does, as paimon.moe's script does.
- **Fix (Linux AppImage): no internet access on Fedora, Arch and other
  non-Ubuntu distributions.** The AppImage looked for trusted certificates
  where only Ubuntu keeps them, so the wish counter, the Enka.Network import
  and the Gemini reader all failed. It now uses the system's own certificates.

> **Pre-release.** On Windows, a complete in-game inventory scan has not
> been run yet. Please report what happens on yours, with the log from
> `Documents/Lumenspar/logs/`.

## Linux: `Lumenspar-0.3.1-x86_64.AppImage`

```sh
chmod +x Lumenspar-0.3.1-x86_64.AppImage
./Lumenspar-0.3.1-x86_64.AppImage
```

Needs a 64-bit distribution about as new as Ubuntu 24.04 (Fedora 40+,
Ubuntu 24.04+, Debian 13, Arch and its derivatives). The inventory scanner
captures the screen through the desktop's screen-sharing portal (PipeWire,
any current desktop), sends input through `/dev/uinput`, and has Tesseract
built in. If the AppImage will not start for lack of FUSE, run it with
`--appimage-extract-and-run`.

## Windows: `Lumenspar-Setup-0.3.1.exe`

The installer is not code-signed, so SmartScreen may need **More info → Run
anyway**. Lumenspar asks for administrator rights at every start, because
Genshin runs elevated and Windows drops input from programs that are not.
The Windows inventory scanner reads text with Google's Gemini model, which
needs a free API key from aistudio.google.com/apikey; the wish counter does
not need one. Requires 64-bit Windows 10 or 11.
