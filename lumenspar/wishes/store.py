"""Wish history kept on disk, one file per account (UID).

Only the wishes themselves are stored -- never the link or its authkey, which
is a credential and expires within a day anyway.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..config import DATA_DIR

WISH_DIR = DATA_DIR / "wishes"
KEEP = ("id", "time", "name", "item_type", "rank_type", "gacha_type")


@dataclass
class History:
    uid: str
    region: str = ""
    updated: str = ""
    wishes: dict[str, list[dict]] = field(default_factory=dict)   # banner key -> oldest first
    # Banners whose stored history reaches back as far as the API goes. An
    # import that was stopped part-way leaves its banner out, so the next one
    # reads it in full instead of stopping at the first wish it already has.
    complete: set[str] = field(default_factory=set)

    def ids(self, banner: str) -> set[str]:
        return {w["id"] for w in self.wishes.get(banner, [])}

    def add(self, banner: str, rows: list[dict]) -> int:
        """Merge API rows into a banner; returns how many were new."""
        have = self.ids(banner)
        new = [{k: str(r.get(k, "")) for k in KEEP} for r in rows if str(r.get("id")) not in have]
        if new:
            merged = self.wishes.get(banner, []) + new
            self.wishes[banner] = sorted(merged, key=lambda w: int(w["id"]))
        return len(new)

    def total(self) -> int:
        return sum(len(v) for v in self.wishes.values())


def _path(uid: str, root: Path) -> Path:
    return root / f"{uid}.json"


def load(uid: str, root: Path = WISH_DIR) -> History:
    try:
        raw = json.loads(_path(uid, root).read_text(encoding="utf-8"))
        return History(uid=raw["uid"], region=raw.get("region", ""),
                       updated=raw.get("updated", ""), wishes=raw.get("wishes", {}),
                       complete=set(raw.get("complete", [])))
    except (OSError, ValueError, KeyError):
        return History(uid=uid)


def save(history: History, root: Path = WISH_DIR) -> Path:
    history.updated = datetime.now().isoformat(timespec="seconds")
    root.mkdir(parents=True, exist_ok=True)
    path = _path(history.uid, root)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"uid": history.uid, "region": history.region,
                               "updated": history.updated,
                               "complete": sorted(history.complete), "wishes": history.wishes},
                              indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def latest(root: Path = WISH_DIR) -> History | None:
    """The most recently updated account, for showing on startup."""
    files = sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return load(files[0].stem, root) if files else None
