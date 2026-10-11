"""Read wish history from HoYoverse's getGachaLog API.

This is the API the in-game wish history page itself calls. The cached page
URL supplies the authkey and account parameters; this module points it at the
API, then pages through each banner newest-first, 20 wishes at a time.

An authkey expires about a day after the wish history was last opened in-game
("authkey timeout"), and the API refuses requests that come too fast ("visit
too frequently"), so requests are paced and that refusal is retried.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

HOST_GLOBAL = "public-operation-hk4e-sg.hoyoverse.com"
HOST_CHINA = "public-operation-hk4e.mihoyo.com"
PATH = "/gacha_info/api/getGachaLog"
USER_AGENT = "Lumenspar (+https://github.com/Galog1/lumenspar)"

PAGE_SIZE = 20          # the API's maximum
PAGE_DELAY = 0.5        # seconds between pages
BUSY_WAITS = (2.0, 4.0, 8.0, 16.0)   # backoff when told to slow down


@dataclass(frozen=True, slots=True)
class Banner:
    key: str            # storage key, also used by stats
    gacha_type: str     # what the API is asked for
    label: str


# The character event query also returns the second character banner
# (gacha_type 400); both share one pity counter, so they are one history.
BANNERS = (
    Banner("character", "301", "Character Event Wish"),
    Banner("weapon", "302", "Weapon Event Wish"),
    Banner("standard", "200", "Standard Wish"),
    Banner("chronicled", "500", "Chronicled Wish"),
    Banner("beginner", "100", "Beginners' Wish"),
)

Transport = Callable[[str], bytes]


class WishApiError(Exception):
    """The API refused or failed; the message is meant for the user."""


class LinkExpired(WishApiError):
    pass


class ServiceUnreachable(WishApiError):
    """No answer at all (network, TLS): not a statement about the link."""


def _default_transport(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def api_url(link: str, gacha_type: str, *, page: int = 1, end_id: str = "0",
            size: int = PAGE_SIZE) -> str:
    """The cached page URL, re-pointed at the API for one page of one banner."""
    parts = urllib.parse.urlsplit(link.strip())
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    if "authkey" not in query:
        raise WishApiError("that link has no authkey -- copy the whole wish history link")
    china = query.get("game_biz", "").startswith("hk4e_cn") or "mihoyo.com" in parts.netloc
    query.update(lang="en-us", gacha_type=gacha_type, page=str(page), size=str(size),
                 end_id=end_id)
    return urllib.parse.urlunsplit(("https", HOST_CHINA if china else HOST_GLOBAL, PATH,
                                    urllib.parse.urlencode(query), ""))


class WishApi:
    def __init__(self, link: str, *, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 log: Callable[[str], None] = lambda m: None) -> None:
        self.link = link
        self._transport = transport or _default_transport
        self._sleep = sleep
        self._log = log
        self.region = ""

    def _get(self, url: str) -> dict:
        for wait in (*BUSY_WAITS, None):
            try:
                body = json.loads(self._transport(url).decode("utf-8"))
            except (OSError, ValueError) as exc:
                raise ServiceUnreachable(
                    f"could not reach HoYoverse's wish history service ({exc})") from exc
            code, msg = body.get("retcode"), str(body.get("message") or "")
            if code == 0:
                return body.get("data") or {}
            if code == -110 and wait is not None:        # "visit too frequently"
                self._log(f"  the service asked to slow down; waiting {wait:.0f}s")
                self._sleep(wait)
                continue
            if code == -101 or "timeout" in msg.lower():
                raise LinkExpired("the wish history link has expired -- open the wish "
                                  "history in-game again, then import")
            raise WishApiError(f"the wish history service refused the request "
                               f"({msg or code})")
        raise WishApiError("the wish history service kept asking to slow down; try again later")

    def works(self) -> bool:
        """Whether this link is still accepted (one tiny request).

        Raises ServiceUnreachable rather than answering: if the service cannot
        be reached, nothing is known about the link.
        """
        try:
            self._get(api_url(self.link, "301", size=1))
            return True
        except ServiceUnreachable:
            raise
        except WishApiError:
            return False

    def fetch(self, banner: Banner, known_ids: set[str],
              should_stop: Callable[[], bool] = lambda: False) -> tuple[list[dict], bool]:
        """Wishes on `banner` newer than any in `known_ids`, newest first.

        Returns (rows, finished): finished is False only when `should_stop`
        cut the walk short, so the caller knows older wishes may be missing.
        """
        rows: list[dict] = []
        end_id, page = "0", 1
        while not should_stop():
            data = self._get(api_url(self.link, banner.gacha_type, page=page, end_id=end_id))
            self.region = data.get("region") or self.region
            batch = data.get("list") or []
            for row in batch:
                if str(row.get("id")) in known_ids:
                    return rows, True    # everything older is already stored
                rows.append(row)
            if len(batch) < PAGE_SIZE:
                return rows, True
            end_id, page = str(batch[-1]["id"]), page + 1
            self._log(f"  {banner.label}: {len(rows)} new so far")
            self._sleep(PAGE_DELAY)
        return rows, False


def first_working(links: list[str], *, transport: Transport | None = None,
                  sleep: Callable[[float], None] = time.sleep) -> str | None:
    """The newest cached link the API still accepts."""
    for i, link in enumerate(links):
        if i:
            sleep(PAGE_DELAY)
        # ServiceUnreachable propagates: reporting "every link expired" when the
        # service was never reached sent a real user looking in the wrong place.
        if WishApi(link, transport=transport, sleep=sleep).works():
            return link
    return None
