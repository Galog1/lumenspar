Lumenspar is a Genshin Impact companion for Linux and Windows: a wish
counter with pity and 50/50 tracking, an inventory scanner that exports
`.GOOD` files, build cards, and an artifact optimizer with team damage.

## New in 0.3.5

- **Much smoother Build Cards page.** The page used to rebuild its whole
  character list every time card art arrived, which could freeze the window for
  seconds on slower computers. It now only updates what changed.
- **Save card as image asks where to save.** A Save As window opens (starting in
  your export folder) instead of writing straight to Documents.
- **Web viewer.** Build cards there now match the app: CV/RV toggle with roll
  values, element-tinted banners and Traveler art.

## Earlier: 0.3.4

- **Updates from inside Lumenspar.** A banner appears when a newer release is
  out (checked at start-up and every few hours, and from **Check for updates**
  on the main menu). **Update now** downloads the Windows installer or the
  AppImage, checks its size and GitHub's checksum, installs it and restarts
  Lumenspar. It never runs while a scan or import is going, and the automatic
  check can be switched off. **This version has to be installed by hand once;
  updates after it are one click.**
- **HoYoLAB sign-in without typing your UID first.** Leave the UID field empty,
  sign in, and Lumenspar finds your Genshin account itself (if it cannot, or
  you have several, it asks for the UID). A typed UID still works as before.

> **Pre-release.** On Windows, a complete in-game inventory scan has not
> been run yet. Please report what happens on yours, with the log from
> `Documents/Lumenspar/logs/`.

## Linux: `Lumenspar-0.3.5-x86_64.AppImage`

```sh
chmod +x Lumenspar-0.3.5-x86_64.AppImage
./Lumenspar-0.3.5-x86_64.AppImage
```

Needs a 64-bit distribution about as new as Ubuntu 24.04 (Fedora 40+,
Ubuntu 24.04+, Debian 13, Arch and its derivatives). The inventory scanner
captures the screen through the desktop's screen-sharing portal (PipeWire,
any current desktop), sends input through `/dev/uinput`, and has Tesseract
built in. If the AppImage will not start for lack of FUSE, run it with
`--appimage-extract-and-run`.

## Windows: `Lumenspar-Setup-0.3.5.exe`

The installer is not code-signed, so SmartScreen may need **More info → Run
anyway**. Lumenspar asks for administrator rights at every start, because
Genshin runs elevated and Windows drops input from programs that are not.
The Windows inventory scanner reads text with Google's Gemini model, which
needs a free API key from aistudio.google.com/apikey; the wish counter does
not need one. Requires 64-bit Windows 10 or 11.
