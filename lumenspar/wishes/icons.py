"""Character and weapon portraits for the wish counter.

Icons are the game's own UI art, served by Project Amber (gi.yatta.moe) under
the asset names recorded in gamedata/characters.json and weapons.json. They
are not shipped with Lumenspar: the ones a history actually needs are
downloaded once and cached in the data folder.
"""

from __future__ import annotations

import json
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

from ..config import DATA_DIR

ICON_DIR = DATA_DIR / "icons"
ASSET_URL = "https://gi.yatta.moe/assets/UI/{name}.png"
USER_AGENT = "Lumenspar (+https://github.com/Galog1/lumenspar)"
_GAMEDATA = Path(__file__).resolve().parent.parent / "gamedata"


@lru_cache(maxsize=None)
def _names() -> dict[str, str]:
    """Display name (lower-cased) -> Amber icon asset name."""
    out: dict[str, str] = {}
    for f in ("characters", "weapons"):
        try:
            items = json.loads((_GAMEDATA / f"{f}.json").read_text(encoding="utf-8"))["items"]
        except (OSError, ValueError, KeyError):
            continue
        for it in items:
            if it.get("icon") and it.get("name"):
                out.setdefault(it["name"].lower(), it["icon"])
    return out


def icon_name(item: str) -> str:
    return _names().get(item.lower(), "")


def path(name: str, root: Path = ICON_DIR) -> Path:
    return root / f"{name}.png"


def missing(items: Iterable[str], root: Path = ICON_DIR) -> list[str]:
    """Icon asset names these items need that are not cached yet."""
    names = {icon_name(i) for i in items} - {""}
    return sorted(n for n in names if not path(n, root).is_file())


def download(names: Iterable[str], root: Path = ICON_DIR,
             fetch: Callable[[str], bytes] | None = None) -> int:
    """Fetch icons into the cache; returns how many arrived. Never raises:
    a portrait that cannot be fetched just stays a placeholder."""
    def default_fetch(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()

    fetch = fetch or default_fetch
    got = 0
    for name in names:
        try:
            data = fetch(ASSET_URL.format(name=name))
            if not data.startswith(b"\x89PNG"):
                continue
            root.mkdir(parents=True, exist_ok=True)
            tmp = path(name, root).with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(path(name, root))
            got += 1
        except Exception:
            continue
    return got
