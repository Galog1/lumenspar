Lumenspar is an inventory scanner for Genshin Impact: it reads your artifacts,
weapons and materials off the screen and writes a `.GOOD` file for Genshin
Optimizer, SEELIE.me and Aspirine's calculator. Characters can be imported
exactly from your profile showcase via Enka.Network.

This release adds the **Linux AppImage**. The Windows installer is the same
app as 0.1.0, rebuilt.

> **Pre-release.** These are the first packaged builds. Linux is where the
> scanner was developed and tested, but the AppImage packaging is new; on
> Windows, a complete in-game scan has not been run yet. Please report what
> happens on yours, with the log from `Documents/Lumenspar/logs/`.

## Linux: `Lumenspar-0.2.0-x86_64.AppImage`

```sh
chmod +x Lumenspar-0.2.0-x86_64.AppImage
./Lumenspar-0.2.0-x86_64.AppImage
```

- Needs a 64-bit distribution about as new as Ubuntu 24.04: Fedora 40+,
  Ubuntu 24.04+, Debian 13, Arch and its derivatives.
- Works on Wayland and X11 through the desktop's screen-sharing portal
  (KDE, GNOME, wlroots), so PipeWire must be running; it is on any current
  desktop. Pick the game's screen when asked; it is remembered after that.
- OCR (Tesseract with English data) is built in. You can also switch to the
  AI reader (Gemini) in the Reader card.
- Input is sent through `/dev/uinput`, which current desktops give the
  logged-in user. Pressing **Escape** to stop a scan also needs read access
  to the keyboard (membership of the `input` group); without it, use the
  **Stop** button.
- If the AppImage will not start for lack of FUSE, run it with
  `--appimage-extract-and-run`.

## Windows: `Lumenspar-Setup-0.2.0.exe`

1. Run the installer. Windows SmartScreen may say it "protected your PC":
   the installer is not code-signed. Choose **More info → Run anyway**.
2. Lumenspar asks for **administrator rights** every time it starts. Genshin
   runs elevated, and Windows silently drops input sent to it by programs
   that are not.
3. The Windows build reads text with Google's **Gemini** vision model only.
   Get a free key at aistudio.google.com/apikey and paste it into the Reader
   card. Free-tier requests may be used by Google to improve its models
   (except in the EEA, UK and Switzerland). Only cropped item panels are
   sent, never your UID or the full screen.

Requires 64-bit Windows 10 or 11.

## Before scanning (both)

- In Genshin: **fullscreen** (Windowed Fullscreen on Windows), **16:9 or
  16:10**, **English** text, control type **Keyboard**.
- Press **Run self-test** first: it checks capture and text reading.
- Exports go to `Documents/Lumenspar/lumenspar.good.json`. Every scan
  overwrites it, so rename anything you want to keep. Logs are saved in
  `Documents/Lumenspar/logs/`, and screenshots of anything that could not be
  read in `Documents/Lumenspar/failures/`.
