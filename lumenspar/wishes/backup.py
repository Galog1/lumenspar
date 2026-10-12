"""Two-way sync of the wish history and build cards with Google Drive.

Lumenspar's hidden app-data folder in Drive holds, per account (UID):

  wishes-<uid>.json   the wish history, in the same format as the local file
  builds-<uid>.json   the build-card collection
  view-<uid>.json     a ready-to-show summary (pity, 50/50 results, cards)
                      for the web viewer, which only renders it; the logic
                      stays here, in one place

Syncing merges both copies of the first two -- every wish either side has,
by id; for each character, the more recently read build -- so nothing is
lost whichever side is ahead: a fresh install restores everything from
Drive, and an import on any computer is added to the copy in Drive. The
view is rewritten whenever its account changed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from datetime import datetime

from .. import builds, gdrive
from . import icons, stats, store

PREFIX = "wishes-"
BUILDS_PREFIX = "builds-"
VIEW_PREFIX = "view-"
VIEW_FORMAT = 1


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


def merge_builds(into: builds.Collection, other: dict) -> int:
    """Add another copy's builds to `into`, newest reading winning per
    character, and apply its removals; returns how many changed here."""
    got = 0
    for aid, when in (other.get("removed") or {}).items():
        when = int(when)
        if when > into.removed.get(aid, 0):
            into.removed[aid] = when
        mine = into.builds.get(aid)
        if mine is not None and mine.get("fetchedAt", 0) <= when:
            del into.builds[aid]
            got += 1
    for aid, b in (other.get("builds") or {}).items():
        if b.get("fetchedAt", 0) <= into.removed.get(aid, -1):
            continue                    # removed after this reading
        mine = into.builds.get(aid)
        if mine is None or b.get("fetchedAt", 0) > mine.get("fetchedAt", 0):
            into.builds[aid] = b
            into.removed.pop(aid, None)
            got += 1
    if other.get("player") and (got or not into.player):
        into.player = other["player"]
    return got


def view(uid: str, root: Path = store.WISH_DIR, builds_root: Path = builds.BUILD_DIR) -> dict:
    """What the web viewer shows for one account."""
    out: dict = {"format": VIEW_FORMAT, "uid": uid,
                 "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "banners": [], "totalWishes": 0, "wishesUpdated": "",
                 "player": {}, "builds": []}
    if (root / f"{uid}.json").is_file():
        history = store.load(uid, root)
        banners = stats.all_stats(history.wishes)
        for banner in banners:
            for five in banner["fives"]:
                five["iconName"] = icons.icon_name(five["name"])
        out.update(banners=banners, totalWishes=history.total(),
                   wishesUpdated=history.updated, region=history.region)
    if (builds_root / f"{uid}.json").is_file():
        col = builds.Collection(uid, builds_root)
        out.update(player=col.player, builds=col.ordered())
    return out


def _remote(files: dict[str, str], prefix: str) -> dict[str, str]:
    return {name[len(prefix):-5]: fid for name, fid in files.items()
            if name.startswith(prefix) and name.endswith(".json")}


def _uids(root: Path) -> set[str]:
    return {p.stem for p in root.glob("*.json")} if root.is_dir() else set()


def sync(drive: gdrive.AppData, log: Callable[[str], None],
         root: Path = store.WISH_DIR, builds_root: Path = builds.BUILD_DIR) -> tuple[int, int]:
    """Merge every local account with Drive both ways, and refresh the views.

    Returns (items restored from Drive, files backed up).
    """
    files = drive.list()
    restored = uploaded = 0
    changed: set[str] = set()       # accounts whose view needs rewriting

    remote = _remote(files, PREFIX)
    local = _uids(root)
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
                changed.add(uid)
                if got:
                    log(f"{uid}: {got} wish(es) restored from Google Drive")
            if _same(mine, theirs):
                continue
        drive.upload(_remote_name(uid), _serialise(mine), remote.get(uid))
        uploaded += 1
        changed.add(uid)
        log(f"{uid}: backed up {mine.total()} wishes to Google Drive")

    remote = _remote(files, BUILDS_PREFIX)
    local = _uids(builds_root)
    for uid in sorted(local | set(remote)):
        col = builds.Collection(uid, builds_root)
        theirs = None
        if uid in remote:
            try:
                theirs = json.loads(drive.download(remote[uid]).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                log(f"The Drive copy of {uid}'s build cards is unreadable; replacing it")
        if theirs is not None:
            got = merge_builds(col, theirs)
            if got or uid not in local:
                col.save()
                restored += got
                changed.add(uid)
                if got:
                    log(f"{uid}: {got} build card(s) restored from Google Drive")
            if theirs.get("builds") == col.builds and theirs.get("player") == col.player \
                    and {k: int(v) for k, v in (theirs.get("removed") or {}).items()} == col.removed:
                continue
        data = json.dumps({"uid": uid, "player": col.player, "builds": col.builds,
                           "removed": col.removed}, ensure_ascii=False).encode("utf-8")
        drive.upload(f"{BUILDS_PREFIX}{uid}.json", data, remote.get(uid))
        uploaded += 1
        changed.add(uid)
        log(f"{uid}: backed up {len(col.builds)} build card(s) to Google Drive")

    remote = _remote(files, VIEW_PREFIX)
    for uid in sorted(_uids(root) | _uids(builds_root)):
        if uid in changed or uid not in remote:
            data = json.dumps(view(uid, root, builds_root), ensure_ascii=False).encode("utf-8")
            drive.upload(f"{VIEW_PREFIX}{uid}.json", data, remote.get(uid))
    return restored, uploaded
