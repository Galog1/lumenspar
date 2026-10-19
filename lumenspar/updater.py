"""Find, download and install the latest Lumenspar release from GitHub.

The pure part of the updater (the QML bridge is ui/update_backend.py).

What it will and will not do:
- It only talks to api.github.com and only downloads files that GitHub lists
  as assets of this repository's releases (`_trusted_url`); a release page
  cannot point it anywhere else.
- A download is checked against the size GitHub reports and, when GitHub
  gives one, the SHA-256 digest of the asset. A file that fails either check
  is deleted and never run. This protects against a damaged download; it is
  not a signature, so it trusts GitHub and the repository's owner.
- Windows: runs the release's installer silently over the current install,
  then starts the new version. Linux AppImage: replaces the AppImage file and
  starts it. Anything else (a source checkout) is only told a version exists.

Releases here are published as pre-releases, which GitHub's "latest release"
endpoint skips, so the release list is read instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ._version import __version__

REPO = "Galog1/lumenspar"
API = f"https://api.github.com/repos/{REPO}/releases?per_page=15"
RELEASE_PAGE = f"https://github.com/{REPO}/releases"
USER_AGENT = f"Lumenspar/{__version__} (+https://github.com/{REPO})"
_TRUSTED_PREFIX = f"https://github.com/{REPO}/releases/download/"
BAD_NAME_CHARS = "/\\:" + chr(0)           # separators, drive colon, NUL
MAX_BYTES = 600 * 1024 * 1024          # far above any real build; a runaway stop


class UpdateError(Exception):
    """Something went wrong checking, downloading or installing; message is for the user."""


# -- versions -----------------------------------------------------------------------

def parse_version(text: str) -> tuple[int, ...] | None:
    """(0, 3, 3) for "0.3.3" or "v0.3.3"; None for anything else (e.g. a dev tag)."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", str(text or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


# -- releases -----------------------------------------------------------------------

@dataclass
class Asset:
    name: str
    url: str
    size: int = 0
    sha256: str = ""


@dataclass
class Release:
    version: str                    # "0.3.4", without the leading v
    tag: str
    notes: str = ""
    page: str = RELEASE_PAGE
    assets: list[Asset] = field(default_factory=list)


def _trusted_url(url: str) -> bool:
    return isinstance(url, str) and url.startswith(_TRUSTED_PREFIX)


def parse_releases(payload) -> list[Release]:
    """Usable releases from GitHub's list, newest version first.

    Drafts are skipped; pre-releases are kept (that is how Lumenspar ships).
    """
    out = []
    for r in payload if isinstance(payload, list) else []:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        ver = parse_version(r.get("tag_name", ""))
        if ver is None:
            continue
        assets = []
        for a in r.get("assets") or []:
            if not isinstance(a, dict) or not _trusted_url(a.get("browser_download_url")):
                continue
            digest = str(a.get("digest") or "")
            assets.append(Asset(
                name=str(a.get("name") or ""), url=a["browser_download_url"],
                size=int(a.get("size") or 0),
                sha256=digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else ""))
        page = r.get("html_url")
        out.append(Release(
            version=".".join(map(str, ver)), tag=str(r.get("tag_name")),
            notes=str(r.get("body") or ""),
            page=page if isinstance(page, str) and page.startswith(f"https://github.com/{REPO}/")
            else RELEASE_PAGE, assets=assets))
    return sorted(out, key=lambda r: parse_version(r.version), reverse=True)


def fetch_json(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise UpdateError("GitHub is rate-limiting this computer; try again later.") from exc
        raise UpdateError(f"GitHub answered {exc.code} when looking for updates.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("Could not reach GitHub to look for updates.") from exc
    except ValueError as exc:
        raise UpdateError("GitHub's answer was not readable.") from exc


def latest_release(fetch: Callable[[str], object] = fetch_json) -> Release | None:
    """The newest published release, or None when there is none."""
    releases = parse_releases(fetch(API))
    return releases[0] if releases else None


# -- what this install can do about it ---------------------------------------------

def how_installed() -> str:
    """"windows", "appimage" or "source": the ways an update can be applied."""
    if sys.platform == "win32":
        return "windows" if getattr(sys, "frozen", False) else "source"
    if os.environ.get("APPIMAGE") and Path(os.environ["APPIMAGE"]).is_file():
        return "appimage"
    return "source"


def asset_for(release: Release, kind: str) -> Asset | None:
    """The release file that updates this kind of install."""
    for a in release.assets:
        n = a.name.lower()
        if kind == "windows" and n.startswith("lumenspar-setup-") and n.endswith(".exe"):
            return a
        if kind == "appimage" and n.endswith(".appimage") and "x86_64" in n:
            return a
    return None


# -- download -----------------------------------------------------------------------

def download(asset: Asset, dest_dir: Path,
             progress: Callable[[int, int], None] = lambda done, total: None,
             should_stop: Callable[[], bool] = lambda: False,
             opener: Callable = urllib.request.urlopen) -> Path:
    """Fetch an asset into `dest_dir`, verified; returns the finished file.

    The file is written as `<name>.part` and renamed only once it has the
    expected size (and digest, when known). Anything wrong deletes it.
    """
    if not _trusted_url(asset.url):
        raise UpdateError("The release file is not hosted where Lumenspar expects.")
    name = asset.name
    # Checked by hand: a backslash is a path separator only on Windows, so
    # Path(...).name would let a name like ..\evil.exe through on Linux.
    if not name or name in (".", "..") or any(c in name for c in BAD_NAME_CHARS):
        raise UpdateError("The release file has an unusable name.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    final, part = dest_dir / name, dest_dir / (name + ".part")
    sha = hashlib.sha256()
    done = 0
    try:
        req = urllib.request.Request(asset.url, headers={"User-Agent": USER_AGENT})
        with opener(req, timeout=30) as r, part.open("wb") as fh:
            total = int(r.headers.get("Content-Length") or asset.size or 0)
            if max(total, asset.size) > MAX_BYTES:
                raise UpdateError("The release file is larger than expected; not downloading it.")
            while True:
                if should_stop():
                    raise UpdateError("Update cancelled.")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                sha.update(chunk)
                done += len(chunk)
                if done > MAX_BYTES:
                    raise UpdateError("The download is larger than expected; stopped.")
                progress(done, total)
        if asset.size and done != asset.size:
            raise UpdateError(f"The download is incomplete ({done} of {asset.size} bytes).")
        if asset.sha256 and sha.hexdigest() != asset.sha256:
            raise UpdateError("The download does not match GitHub's checksum; it was discarded.")
        os.replace(part, final)
        return final
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"The download failed ({exc}).") from exc


def work_dir() -> Path:
    return Path(tempfile.gettempdir()) / "lumenspar-update"


# -- install ------------------------------------------------------------------------

def windows_install_command(installer: Path, exe: Path) -> str:
    """One cmd line: run the installer silently and wait, then start the new app.

    `start /wait` makes cmd wait for the GUI installer. The installer closes
    the running Lumenspar itself (Inno's CloseApplications), and it reuses the
    folder of the existing install, so no path is passed.
    """
    for p in (installer, exe):
        if '"' in str(p):
            raise UpdateError("The install path contains a quote; update by hand.")
    return (f'start /wait "" "{installer}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART '
            f'/CLOSEAPPLICATIONS && start "" "{exe}"')


def apply_windows(installer: Path, exe: Path | None = None) -> None:
    """Start the installer detached; the caller then quits so the files can be replaced."""
    exe = exe or Path(sys.executable)
    cmd = windows_install_command(installer, exe)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | \
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # cmd needs the whole line as one argument, quotes intact.
    subprocess.Popen(f'cmd /d /s /c "{cmd}"', creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def apply_appimage(new_file: Path, current: Path | None = None) -> Path:
    """Replace the running AppImage with `new_file`; returns the path to start."""
    current = current or Path(os.environ.get("APPIMAGE", ""))
    if not current.is_file():
        raise UpdateError("Could not find the AppImage that is running.")
    staged = current.with_name(current.name + ".new")
    try:
        # Staged beside the target: a rename across file systems would copy, and
        # a half-copied AppImage must never sit at the real path.
        staged.write_bytes(new_file.read_bytes())
        staged.chmod(0o755)
        os.replace(staged, current)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise UpdateError(f"Could not replace {current} ({exc}). Is its folder writable?") from exc
    return current


def relaunch(path: Path) -> None:
    subprocess.Popen([str(path)], start_new_session=True, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
