The first Windows build of Lumenspar: an inventory scanner for Genshin Impact
that reads your artifacts, weapons and materials off the screen and writes a
`.GOOD` file for Genshin Optimizer, SEELIE.me and Aspirine's calculator.
Characters can be imported exactly from your profile showcase via
Enka.Network.

> **Pre-release.** On Windows, the window, screen capture and mouse placement
> have been checked, but a complete scan inside the game has not been run yet.
> Please report what happens on yours.

### Install

1. Download **`Lumenspar-Setup-0.1.0.exe`** below and run it.
2. Windows SmartScreen may say it "protected your PC": the installer is not
   code-signed. Choose **More info → Run anyway**.
3. Lumenspar asks for **administrator rights** every time it starts. Genshin
   runs elevated, and Windows silently drops input sent to it by programs that
   are not.

### Before scanning

- **Gemini API key** (free): the Windows build reads text with Google's
  Gemini vision model. Get a key at aistudio.google.com/apikey and paste it
  into the Reader card. Free-tier requests may be used by Google to improve
  its models (except in the EEA, UK and Switzerland). Only cropped item
  panels are sent, never your UID or the full screen.
- In Genshin: **Windowed Fullscreen**, **16:9 or 16:10**, **English** text,
  control type **Keyboard**.
- Press **Run self-test** first: it checks the capture and your Gemini key.

### Where things go

- Exports: `Documents\Lumenspar\lumenspar.good.json`. Every scan overwrites
  it, so rename anything you want to keep.
- Logs: `Documents\Lumenspar\logs\`, and screenshots of anything that could
  not be read: `Documents\Lumenspar\failures\`. Attach these to a bug report.
- Settings: `%APPDATA%\lumenspar`. Uninstalling leaves your settings and
  exports in place.

Requires 64-bit Windows 10 or 11.
