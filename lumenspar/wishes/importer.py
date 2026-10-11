"""One wish history import: find a working link, read every banner, save."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import api, link, store


class ImportError_(Exception):
    """An import that could not start or finish; the message is for the user."""


NO_LINK = ("No wish history link found. Open the wish history in-game (Wish → "
           "History), then import again -- or paste the link by hand.")


def find_link(log: Callable[[str], None], game_folder: str = "",
              transport: api.Transport | None = None) -> str:
    """The newest cached link the API still accepts."""
    if game_folder:
        links = link.links_from_folder(Path(game_folder))
        log(f"Looking in {game_folder}: {len(links)} wish history link(s)")
    else:
        files = link.cache_files()
        if not files:
            raise ImportError_("Could not find Genshin Impact's web cache. Choose the game "
                               "folder by hand, or paste the wish history link.")
        log(f"Found the game's web cache: {files[0].parents[4]}")
        links = link.links_from_files(files, log)
        log(f"{len(links)} wish history link(s) in the cache")
    if not links:
        raise ImportError_(NO_LINK)
    good = api.first_working(links, transport=transport)
    if good is None:
        raise ImportError_("Every cached link has expired. " + NO_LINK)
    return good


def run(wish_link: str, log: Callable[[str], None],
        should_stop: Callable[[], bool] = lambda: False,
        transport: api.Transport | None = None,
        root: Path = store.WISH_DIR) -> store.History:
    """Read every banner through `wish_link` and merge into the stored history."""
    client = api.WishApi(wish_link, transport=transport, log=log)
    # The account is only known once a wish comes back, so start from the most
    # recently imported one and read incrementally against it. Wish ids are
    # unique across accounts: if the guess is wrong nothing matches, the
    # banner is simply read in full, and the right history is loaded below.
    history = store.latest(root)
    confirmed = False
    pending: dict[str, tuple[list[dict], bool]] = {}
    for banner in api.BANNERS:
        if should_stop():
            break
        known = history.ids(banner.key) if history and banner.key in history.complete else set()
        rows, finished = client.fetch(banner, known, should_stop)
        if rows and not confirmed:
            confirmed = True
            uid = str(rows[0]["uid"])
            if history is None or history.uid != uid:
                history = store.load(uid, root)
        pending[banner.key] = (rows, finished)
        log(f"{banner.label}: {len(rows)} new wish(es)")
    if history is None:
        raise ImportError_("The link worked but returned no wishes on any banner.")
    history.region = client.region or history.region
    added = 0
    for key, (rows, finished) in pending.items():
        added += history.add(key, rows)
        if finished:
            history.complete.add(key)
    path = store.save(history, root)
    log(f"Saved {added} new wish(es), {history.total()} in total, to {path}")
    return history
