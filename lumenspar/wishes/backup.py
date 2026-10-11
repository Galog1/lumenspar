"""Two-way sync of the wish history with Google Drive.

Each account is one file, wishes-<uid>.json, in Lumenspar's hidden app-data
folder in Drive, in the same format as the local file. Syncing merges the two
copies -- every wish either side has, by id -- so nothing is lost whichever
side is ahead: a fresh install restores the history from Drive, and an
import on any computer is added to the copy in Drive.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .. import gdrive
from . import store

PREFIX = "wishes-"


def _remote_name(uid: str) -> str:
    return f"{PREFIX}{uid}.json"


def _parse(data: bytes, uid: str) -> store.History:
    raw = json.loads(data.decode("utf-8"))
    return store.History(uid=uid, region=raw.get("region", ""), updated=raw.get("updated", ""),
                         wishes=raw.get("wishes", {}), complete=set(raw.get("complete", [])))


def _serialise(history: store.History) -> bytes:
    return json.dumps({"uid": history.uid, "region": history.region,
                       "updated": history.updated, "complete": sorted(history.complete),
                       "wishes": history.wishes}, indent=1, ensure_ascii=False).encode("utf-8")


def merge(into: store.History, other: store.History) -> int:
    """Add `other`'s wishes to `into`; returns how many were new to it."""
    added = sum(into.add(banner, rows) for banner, rows in other.wishes.items())
    # A banner counts as complete once either copy reached back to its start:
    # the union of both copies then does too.
    into.complete |= other.complete
    into.region = into.region or other.region
    return added


def _same(a: store.History, b: store.History) -> bool:
    return a.complete == b.complete and \
        {k: [w["id"] for w in v] for k, v in a.wishes.items() if v} == \
        {k: [w["id"] for w in v] for k, v in b.wishes.items() if v}


def sync(drive: gdrive.AppData, log: Callable[[str], None],
         root: Path = store.WISH_DIR) -> tuple[int, int]:
    """Merge every local account with Drive both ways.

    Returns (wishes restored from Drive, accounts uploaded).
    """
    remote = {name[len(PREFIX):-5]: fid for name, fid in drive.list().items()
              if name.startswith(PREFIX) and name.endswith(".json")}
    local = {p.stem for p in root.glob("*.json")} if root.is_dir() else set()
    restored = uploaded = 0
    for uid in sorted(local | set(remote)):
        mine = store.load(uid, root)
        theirs = None
        if uid in remote:
            try:
                theirs = _parse(drive.download(remote[uid]), uid)
            except (ValueError, UnicodeDecodeError):
                log(f"The Drive copy of {uid} is unreadable; replacing it with this one")
        if theirs is not None:
            was_complete = set(mine.complete)
            got = merge(mine, theirs)
            if got or uid not in local or mine.complete != was_complete:
                store.save(mine, root)
                restored += got
                if got:
                    log(f"{uid}: {got} wish(es) restored from Google Drive")
            if _same(mine, theirs):
                continue
        drive.upload(_remote_name(uid), _serialise(mine), remote.get(uid))
        uploaded += 1
        log(f"{uid}: backed up {mine.total()} wishes to Google Drive")
    return restored, uploaded
