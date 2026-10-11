"""Find the wish history URL the game cached.

Opening the wish history in-game makes the game load a web page whose URL
carries a temporary authkey; the game's embedded browser caches it in
`<game>/GenshinImpact_Data/webCaches/<version>/Cache/Cache_Data/data_2`.
This module finds that file and pulls the URLs out of it. The API then says
which of them still works (they expire about a day after the history was
last opened).

Finding the game:
  - Windows: the game writes its install folder into output_log.txt, which is
    how paimon.moe's script finds it.
  - Linux: the game runs under Wine or Proton, usually through An Anime Game
    Launcher (native or Flatpak), Lutris, Heroic or Bottles. Their usual
    locations are checked first; failing that, the Wine prefixes' own
    output_log.txt; failing that, a time-limited search of the home folder
    and mounted drives for a GenshinImpact_Data folder.

Reading it on Windows: while the game runs, its browser holds data_2 open
in a way that makes a plain open() fail with "Permission denied" (it allows
others to read only if they also allow the file to be deleted, which the C
runtime's open() never does). read_cache() opens it the way Windows' own
copy does -- what paimon.moe's script relies on.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

DATA_DIR_NAMES = ("GenshinImpact_Data", "YuanShen_Data")   # global, China

# An Anime Game Launcher keeps the game beside its Wine prefix; these are
# where its native and Flatpak builds put them.
_LAUNCHER_GAME_DIRS = (
    ".var/app/moe.launcher.an-anime-game-launcher/data/anime-game-launcher",
    ".local/share/anime-game-launcher",
)

# How long the fallback search of the disk may take before giving up.
SEARCH_SECONDS = 8.0
_SKIP_DIRS = {".cache", "node_modules", ".git", "__pycache__", ".npm",
              ".cargo", ".rustup", "proc", "sys", "dev", ".Trash"}

_GAME_DIR_IN_LOG = re.compile(r"([A-Za-z]:/[^\r\n]+?/(?:GenshinImpact_Data|YuanShen_Data))")
_URL = re.compile(r"(https://[^\s\x00\"']+?game_biz=[A-Za-z0-9_]*)")


def cache_files(home: Path | None = None, windows: bool | None = None,
                extra_roots: list[Path] | None = None) -> list[Path]:
    """Every webCaches data_2 file found, newest first."""
    from .. import hostos

    home = home or Path.home()
    windows = hostos.is_windows() if windows is None else windows
    data_dirs: list[Path] = []
    for root in extra_roots or []:
        data_dirs += _data_dirs_under(root, max_depth=4, deadline=time.monotonic() + 3)
    if windows:
        data_dirs += _from_windows_logs(home)
    else:
        data_dirs += _from_launchers(home)
        data_dirs += _from_wine_logs(home)
        if not data_dirs:
            deadline = time.monotonic() + SEARCH_SECONDS
            for root in _linux_search_roots(home):
                data_dirs += _data_dirs_under(root, max_depth=8, deadline=deadline)
    files = {f for d in data_dirs for f in _data_2_files(d)}
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def extract_links(data: bytes) -> list[str]:
    """Wish history URLs in a data_2 cache file, newest first.

    Entries are separated by "1/0/" (the format paimon.moe's script relies
    on); later entries are newer, so the list is reversed.
    """
    text = data.decode("utf-8", "ignore")
    links: list[str] = []
    for entry in text.split("1/0/"):
        if "webview_gacha" not in entry:
            continue
        m = _URL.search(entry)
        if m and m.group(1) not in links:
            links.append(m.group(1))
    return links[::-1]


class CacheUnreadable(OSError):
    """data_2 exists but cannot be read; the message says what to do."""


def read_cache(path: Path, shared_read=None) -> bytes:
    """data_2's bytes, even while the game has it open on Windows."""
    try:
        return path.read_bytes()
    except PermissionError as exc:
        if shared_read is None:
            if os.name != "nt":
                raise CacheUnreadable(f"Cannot read {path}: {exc.strerror}") from exc
            shared_read = _read_shared_windows
        try:
            return shared_read(path)
        except OSError as exc2:
            raise CacheUnreadable(
                f"Windows would not let Lumenspar read the game's web cache ({exc2}). "
                "Close Genshin Impact and import again -- the link stays in the cache -- "
                "or paste the link by hand.") from exc2


def _read_shared_windows(path: Path) -> bytes:
    """Open with read, write *and* delete sharing, as CopyFile does."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE)
    generic_read, share_all, open_existing, normal = 0x80000000, 0x7, 3, 0x80
    handle = k32.CreateFileW(str(path), generic_read, share_all, None, open_existing,
                             normal, None)
    if handle is None or handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    with open(msvcrt.open_osfhandle(handle, os.O_RDONLY), "rb") as f:
        return f.read()


def links_from_files(files: list[Path], log=None) -> list[str]:
    """Links from several data_2 files, newest file first; an unreadable file
    is skipped as long as another one can be read."""
    out: list[str] = []
    problem: CacheUnreadable | None = None
    read_any = False
    for f in files:
        try:
            data = read_cache(f)
        except CacheUnreadable as exc:
            problem = problem or exc
            if log:
                log(f"Could not read {f}: {exc}")
            continue
        read_any = True
        out += [u for u in extract_links(data) if u not in out]
    if not read_any and problem is not None:
        raise problem
    return out


def paimon_link(link: str) -> str:
    """The link exactly as paimon.moe's getlink.ps1 hands it over.

    That script takes each cache entry's `https.+?game_biz=` -- the URL up to
    and including "game_biz=", without its value -- and paimon.moe's importer
    expects that shape (it re-points the URL at the API itself).
    """
    cut = link.find("game_biz=")
    return link[: cut + len("game_biz=")] if cut >= 0 else link


def links_from_folder(folder: Path) -> list[str]:
    """Links from a game folder the user picked by hand."""
    files = [f for d in _data_dirs_under(folder, max_depth=4, deadline=time.monotonic() + 5)
             for f in _data_2_files(d)]
    return links_from_files(files)


# -- locating the game ----------------------------------------------------------

def _data_2_files(data_dir: Path) -> list[Path]:
    caches = data_dir / "webCaches"
    if not caches.is_dir():
        return []
    out = []
    for version in caches.iterdir():
        f = version / "Cache" / "Cache_Data" / "data_2"
        if f.is_file():
            out.append(f)
    return out


def _from_launchers(home: Path) -> list[Path]:
    out = []
    for rel in _LAUNCHER_GAME_DIRS:
        base = home / rel
        if base.is_dir():
            out += _data_dirs_under(base, max_depth=2, deadline=time.monotonic() + 2)
    return out


def _game_dir_from_log(log: Path) -> str | None:
    try:
        text = log.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    m = _GAME_DIR_IN_LOG.search(text)
    return m.group(1) if m else None


def _from_windows_logs(home: Path) -> list[Path]:
    out = []
    for name in ("Genshin Impact", "\u539f\u795e"):
        win_path = _game_dir_from_log(home / "AppData" / "LocalLow" / "miHoYo" / name
                                      / "output_log.txt")
        if win_path:
            out.append(Path(win_path))
    return [p for p in out if p.is_dir()]


def _wine_to_linux(win_path: str, prefix: Path) -> Path:
    """'C:/Games/...' inside `prefix`, or 'Z:/home/...' (Wine's view of /)."""
    drive, rest = win_path[0].lower(), win_path[3:]
    if drive == "z":
        return Path("/") / rest
    return prefix / f"drive_{drive}" / rest


def _from_wine_logs(home: Path) -> list[Path]:
    """Wine prefixes whose game log names the install folder."""
    out = []
    pattern = "drive_c/users/*/AppData/LocalLow/miHoYo/*/output_log.txt"
    roots = [home / rel for rel in _LAUNCHER_GAME_DIRS] + [home / "Games", home / ".wine",
                                                           home / ".local/share/lutris",
                                                           home / ".var/app"]
    for root in roots:
        if not root.is_dir():
            continue
        for log in list(root.glob(pattern)) + list(root.glob("*/" + pattern)) \
                + list(root.glob("*/*/" + pattern)):
            win_path = _game_dir_from_log(log)
            if win_path:
                prefix = log.parents[7]          # .../<prefix>/drive_c/users/...
                p = _wine_to_linux(win_path, prefix)
                if p.is_dir():
                    out.append(p)
    return out


def _linux_search_roots(home: Path) -> list[Path]:
    roots = [home]
    user = home.name
    for base in (Path("/run/media") / user, Path("/media") / user, Path("/mnt")):
        if base.is_dir():
            roots += [p for p in base.iterdir() if p.is_dir()]
    return roots


def _data_dirs_under(root: Path, max_depth: int, deadline: float) -> list[Path]:
    """GenshinImpact_Data / YuanShen_Data folders below `root` (bounded search)."""
    found: list[Path] = []
    if root.name in DATA_DIR_NAMES:
        return [root]
    base_depth = len(root.parts)
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        if time.monotonic() > deadline:
            break
        depth = len(Path(dirpath).parts) - base_depth
        hits = [d for d in dirnames if d in DATA_DIR_NAMES]
        found += [Path(dirpath) / d for d in hits]
        if depth >= max_depth:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames
                           if d not in _SKIP_DIRS and d not in DATA_DIR_NAMES
                           and not (d.startswith(".") and depth > 0 and d != ".var")]
    return found
