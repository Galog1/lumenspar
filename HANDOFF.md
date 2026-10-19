# Lumenspar handoff

State at **v0.3.5** (commit `ee7d095`, 2026-10-19). Read this first, then `README.md`
(setup, layout, status) for the rest. The repo has no personal data in it: keep it
that way (no real UIDs, tokens, or home paths in code, tests, docs or screenshots).

## What it is

A PySide6/QML Genshin Impact companion for Linux and Windows: Wish Counter,
Inventory Scanner (OCR to `.GOOD`), Build Cards, Optimizer with Team & damage.
Public repo `Galog1/lumenspar` (remote `origin`); `dev` (lumenspar-dev) is a separate
repo, never push releases there. Website and web viewer are served by GitHub Pages
from `docs/` (galog1.github.io/lumenspar, viewer at `/app/`).

## Release process (how 0.3.3 to 0.3.5 went out)

- Bump `pyproject.toml` and `lumenspar/_version.py` (Unix line endings), write the
  section in `packaging/RELEASE_NOTES.md` (the file names in it must match the new
  version), commit, then `git tag -a vX.Y.Z` and `git push origin main vX.Y.Z`.
- The tag triggers `linux-release.yml` and `windows-release.yml`: tests, PyInstaller
  build, headless self-check (`LUMENSPAR_SMOKE_TEST=<report file>`, see
  `lumenspar/selfcheck.py`), then a **pre-release** with the AppImage and installer.
- A flaky job: `gh run rerun <id> --failed` (same tag). Do not move a tag without the
  owner's explicit OK. `gh workflow run linux-release.yml --ref main` builds without
  publishing.
- PySide6 6.12: Qt WebEngine is its own wheel, `PySide6-WebEngine` (already in the
  workflows and `pyproject.toml`).
- Google Drive sign-in needs `LUMENSPAR_GOOGLE_CLIENT` at build time; it is still
  unset, so shipped builds have no Drive sign-in unless the owner sets it.
- Windows: a full in-game inventory scan has still **not** been run on Windows. The
  release notes say so.

## Done in this stretch (0.3.3 to 0.3.5)

- **HoYoLAB sign-in** (`ui/HoyolabWindow.qml`, `ui/hoyolab_backend.py`): popups for the
  security check now open in real windows on the same off-the-record profile
  (`otrProfile`), keeping `window.opener`. Guards in `tests/test_hoyolab.py`.
- **Build cards redesign**: `lumenspar/cardart.py` bakes an element-tinted backdrop
  from the splash art (numpy blur, JPEG, ~0.07 s per card); `BuildCard.qml`, bundled
  Inter font (`ui/fonts.py`), Traveler art from `avatarId`, roll values (RV) and a
  CV/RV toggle (`config.card_metric`, `builds.roll_value`).
- **In-app updates** (`lumenspar/updater.py`, `ui/update_backend.py`): banner, download,
  checksum, install, restart; switchable off. 0.3.4 had to be installed by hand once.
- **Website** (`docs/index.html`, `privacy.html`): features, HoYoLAB, updates.
- **Web viewer** (`docs/app/app.js`, `app.css`): CV/RV toggle with client-side RV
  (max-roll table copied from `builds.py`), element-tinted hero, Traveler fallback,
  scrollable chip strip. Only checked in a browser with made-up cards; never with a
  real backup. `window.lumensparShow([...])` loads fake data for previews.
- **Performance (0.3.5)**: QML converted the whole card list (about 400 KB for 95
  cards) on every read of `cards.cards`, once per chip, and the page republished every
  ~2.5 s while art arrived (about 0.3 s per republish on a fast desktop, much worse on
  a slow one). Now `BuildsBackend` exposes `chips` (slim list, re-sent only when it
  differs), `count`, `revision` and `cardAt(i)`; icons decode at display size.
- **Save card as image** now opens a Save As dialog (`BuildsPage.qml` `saveDlg`;
  `defaultCardFile`, `chosenCardPath` in `builds_backend.py`). Not clicked through on a
  real desktop.

## Open questions and unverified

- **Slowness on low-end Windows.** One friend's PC froze for a while. The card-list fix
  above is one confirmed cause, not proven to be the whole story. Still unprofiled:
  startup work, Drive sync, update check, wish import, the optimizer and team pages.
  Suggested next step: add an opt-in timing log (slow GUI-thread callbacks, long
  `_publish` calls) the friend can send back, or run the packaged build under a
  profiler on a throttled VM. Ask whether 0.3.5 helped before digging further.
- **Windows card look** with Inter and the baked backdrops: unconfirmed by the owner.
- **HoYoLAB response parsing**: written against observed shapes; may break if HoYoLAB
  changes its endpoints. Check `hoyolab_backend.py` and `hoyolab.py` first if
  "all characters" stops working.
- **Intermittent Linux headless segfault** seen once in CI (passed on rerun).
  `faulthandler` output goes next to the smoke report (`<report>.fault.txt`). Note
  that running the smoke test with a bare value like `1` writes files named `1` and
  `1.fault.txt` into the current folder; delete them.
- **Drive sign-in** cannot be tested without the client secret.
- Wording nit: `RELEASE_NOTES.md` now has an "Earlier: 0.3.4" heading followed by the
  pre-release callout, which reads as belonging to 0.3.4. Tidy next release.

## Ideas discussed, not started

- **Standalone web card page** (recommended by me, awaiting the owner's go-ahead): a page
  in `docs/` where anyone types a UID, gets cards from Enka.Network in the browser, uses
  the CV/RV toggle, and saves PNGs. No sign-in. Link it from the viewer. The optimizer
  and the damage engine would stay desktop-only (the engine is Genshin Optimizer's).
- **HoYoLAB from the web**: not possible directly (HoYoLAB's cross-origin and cookie
  rules protect it, whoever hosts the page; a VPS or Cloudflare tunnel does not change
  that). A proxy server would mean collecting user credentials and would break the
  "no server" promise, so it is off the table. The honest route is a **bookmarklet or
  userscript run on `act.hoyolab.com`** that reuses the desktop fetch script
  (`hoyolab.fetchScript`) and hands the JSON back by clipboard or file download. It may
  be blocked by HoYoLAB's page security policy: prototype and test first.

## Working notes

- Lead does the work itself; scouts/advisor only as the owner's global rules say.
- Scratch files vanish between turns; recreate harnesses when needed. Never `pkill -f`
  (it can kill your own shell); keep PIDs in variables.
- Run tests with `QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests` (461 pass, 1
  skipped at 0.3.5). No `node` on this machine, so the web viewer's JS has no syntax
  check beyond loading it in the browser pane.
- Local preview of the site: `python3 -m http.server` from `docs/`, then `/app/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. `.serena/`
  is excluded via `.git/info/exclude`; never commit it.
