"""QML-facing bridge for the build cards.

A fetch reads the Enka.Network showcase on a worker thread, turns it into
build cards (lumenspar.builds) and merges them into the collection kept for
that UID. Art is downloaded in the background the first time it is needed;
until then the cards show placeholders.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from .. import akasha, builds, cardart, enka
from ..wishes import icons
from .backend import _Worker


def _file_url(path: Path) -> str:
    return QUrl.fromLocalFile(str(path)).toString() if path.is_file() else ""


def _url(asset: str) -> str:
    """A cached asset as a file URL, or "" until it has been downloaded."""
    return _file_url(icons.path(asset)) if asset else ""


_CHIP_KEYS = ("avatarId", "name", "element", "rarity", "iconUrl", "inShowcase",
              "constellation", "fetched")


def backdrop_of(b: dict) -> str:
    """The name of a card's baked backdrop ("" for a character without splash art)."""
    b = builds.fill_art(b)
    return cardart.backdrop_name(b.get("splash", ""), b.get("element", ""))


def ensure_backdrop(b: dict) -> bool:
    """Bake a card's backdrop if its splash art is cached and it is not baked yet."""
    b = builds.fill_art(b)
    name = backdrop_of(b)
    if not name:
        return False
    dst = cardart.backdrop_path(name)
    if dst.is_file():
        return True
    src = icons.path(b["splash"])
    return src.is_file() and cardart.bake(src, dst, b.get("element", ""))


def decorate(b: dict) -> dict:
    """A card with roll values worked out and file URLs for the art already cached
    (QML shows placeholders until the rest arrives)."""
    card = builds.with_roll_values(builds.fill_art(b))
    card["iconUrl"] = _url(card.get("icon", ""))
    name = backdrop_of(card)
    card["bgUrl"] = _file_url(cardart.backdrop_path(name)) if name else ""
    if card.get("weapon"):
        card["weapon"] = {**card["weapon"], "iconUrl": _url(card["weapon"].get("icon", ""))}
    card["artifacts"] = [{**a, "iconUrl": _url(a.get("icon", ""))}
                         for a in card.get("artifacts", [])]
    card["fetched"] = datetime.fromtimestamp(card.get("fetchedAt", 0)).strftime("%Y-%m-%d %H:%M")
    return card


def art_names(b: dict) -> list[str]:
    """The asset names a card's art needs (icon, splash, weapon, artifacts)."""
    b = builds.fill_art(b)
    names = [b.get("icon", ""), b.get("splash", "")]
    if b.get("weapon"):
        names.append(b["weapon"].get("icon", ""))
    names += [a.get("icon", "") for a in b.get("artifacts", [])]
    return names


class BuildsBackend(QObject):
    changed = Signal()
    chipsChanged = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    waitChanged = Signal()
    collected = Signal()          # a fetch added or changed cards (for the Drive backup)
    akashaChanged = Signal()
    metricChanged = Signal()
    _artArrived = Signal()
    _akashaArrived = Signal(object)    # (calcs by avatar id, status text)

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings          # shared with the scanner page's Backend
        self._collection = builds.latest()
        self._showcase: list[str] = []     # avatar ids in the latest fetch's order
        self._cards: list[dict] = []
        self._chips: list[dict] = []
        self._revision = 0
        self._busy = False
        self._status = ""
        self._worker: _Worker | None = None
        self._on_done = None          # what to run, on the GUI thread, when the job ends
        self._art_lock = threading.Lock()
        self._art_running = False
        self._art_icons: set[str] = set()         # small icons waiting to be downloaded
        self._art_queue: list[dict] = []          # cards waiting for their backdrop
        self._art_tried: set[str] = set()         # asset / backdrop names already attempted
        self._akasha: dict = {}            # Akasha.cv calculations by avatar id
        self._akasha_status = ""
        self._akasha_loading = False
        self._artArrived.connect(self._on_art)
        self._akashaArrived.connect(self._on_akasha)
        self._tick = QTimer(self, interval=1000)
        self._tick.timeout.connect(self._on_tick)
        self._publish()
        if self._collection:
            QTimer.singleShot(0, self._load_akasha)

    # -- what the page shows ----------------------------------------------

    # QML reads a QVariantList property by converting the whole list, so the page
    # gets a slim list for the chip grid (re-sent only when it really differs) and
    # one full card at a time through cardAt().
    @Property("QVariantList", notify=chipsChanged)
    def chips(self) -> list:
        return self._chips

    @Property(int, notify=changed)
    def count(self) -> int:
        return len(self._cards)

    @Property(int, notify=changed)
    def revision(self) -> int:
        return self._revision

    @Slot(int, result="QVariantMap")
    def cardAt(self, index: int) -> dict:
        return self._cards[index] if 0 <= index < len(self._cards) else {}

    @Property("QVariantMap", notify=changed)
    def player(self) -> dict:
        return self._collection.player if self._collection else {}

    @Property(str, notify=changed)
    def account(self) -> str:
        return self._collection.uid if self._collection else ""

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=akashaChanged)
    def akashaStatus(self) -> str:
        return self._akasha_status

    @Property(int, notify=waitChanged)
    def waitSeconds(self) -> int:
        """Seconds before Enka will have a fresh showcase (its cache time)."""
        return int(self._collection.wait_remaining() + 0.999) if self._collection else 0

    # -- actions ------------------------------------------------------------

    @Slot(str)
    def fetch(self, uid: str) -> None:
        uid = uid.strip()
        if self._busy:
            return
        if not uid.isdigit():
            self._set_status("Enter your UID first (bottom-right corner in-game).")
            return
        collection = builds.Collection(uid)
        wait = collection.wait_remaining()
        if wait > 0:
            # Enka would only return its cached copy: show what is stored.
            self._collection = collection
            self._publish()
            self._set_status(f"Enka.Network refreshes this showcase in {int(wait) + 1}s.")
            return
        result: list = []

        def job(log) -> None:
            data, ttl = enka.fetch(uid)
            player, cards, problems = builds.parse(data)
            for p in problems:
                log(p)
            new, updated = collection.merge(player, cards, ttl)
            result.append(([c["avatarId"] for c in cards], new, updated, problems))

        def done(ok: bool, err: str) -> None:
            self._finish()
            if not ok:
                self._set_status(err or "Fetch failed")
                return
            showcase, new, updated, problems = result[0]
            self._collection, self._showcase = collection, showcase
            self._publish()
            self._load_akasha()
            parts = [f"{len(showcase)} in the showcase"]
            if new:
                parts.append(f"new: {', '.join(new)}")
            if updated:
                parts.append(f"updated: {', '.join(updated)}")
            if problems and not showcase:
                parts = [problems[0]]
            self._set_status(" · ".join(parts) + f" · {len(collection.builds)} collected")
            if new or updated:
                self.collected.emit()

        self._busy = True
        self.busyChanged.emit()
        self._set_status("Reading the showcase from Enka.Network…")
        w = _Worker(job, self)
        # Connected to a method of this object, so it runs on the GUI thread.
        self._on_done = done
        w.done.connect(self._job_done)
        self._worker = w
        w.start()

    @Slot(str, object, object)
    def addHoyolab(self, uid: str, cards: list, problems: list) -> None:
        """Store the characters read from HoYoLAB (see HoyolabBackend)."""
        collection = self._collection if self._collection and self._collection.uid == uid \
            else builds.Collection(uid)
        new, updated = collection.merge_cards(cards)
        self._collection = collection
        self._publish()
        self._load_akasha()
        parts = [f"{len(cards)} characters from HoYoLAB"]
        if new:
            parts.append(f"{len(new)} new")
        if updated:
            parts.append(f"{len(updated)} updated")
        if problems:
            parts.append(f"{len(problems)} skipped: {problems[0]}")
        self._set_status(" · ".join(parts) + f" · {len(collection.builds)} collected")
        if new or updated:
            self.collected.emit()

    @Slot(bool, str)
    def _job_done(self, ok: bool, err: str) -> None:
        done, self._on_done = self._on_done, None
        if done is not None:
            done(ok, err)

    @Slot()
    def reload(self) -> None:
        """Re-read the stored collection (after a Drive sync restored cards)."""
        uid = self._collection.uid if self._collection else ""
        self._collection = builds.Collection(uid) if uid else builds.latest()
        self._publish()

    @Slot(str)
    def forget(self, avatar_id: str) -> None:
        if self._collection:
            self._collection.remove(avatar_id)
            self._publish()

    @Slot(str, result=str)
    def defaultCardFile(self, name: str) -> str:
        """The save dialog's suggested file (a file:// URL) in <export folder>/cards."""
        folder = Path(self._settings.export_dir).expanduser() / "cards"
        safe = re.sub(r"[^\w\- ]", "", name).strip() or "card"
        return QUrl.fromLocalFile(str(folder / f"{safe} {datetime.now():%Y-%m-%d}.png")).toString()

    @Slot(str, result=str)
    def chosenCardPath(self, url: str) -> str:
        """The local .png path for the file the player picked in the save dialog."""
        path = Path(QUrl(url).toLocalFile())
        if path.suffix.lower() != ".png":
            path = path.with_name(path.name + ".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    @Slot(str, bool)
    def cardSaved(self, path: str, ok: bool) -> None:
        self._set_status(f"Saved {path}" if ok else f"Could not save {path}")

    # -- internals ------------------------------------------------------------

    def _finish(self) -> None:
        w = self._worker
        if w is not None:
            w.wait(5000)
            w.deleteLater()
        self._worker = None
        self._busy = False
        self.busyChanged.emit()

    def _publish(self) -> None:
        """Rebuild the card list QML reads, with art URLs, and fetch missing art."""
        c = self._collection
        cards = c.ordered(self._showcase) if c else []
        wanted = []
        out = []
        for b in cards:
            card = decorate(b)
            wanted += art_names(b)
            card["inShowcase"] = b["avatarId"] in self._showcase
            calc = self._akasha.get(b["avatarId"])
            if calc:
                card["akasha"] = {
                    "rank": calc.rank_text(),
                    "calc": calc.name + (" · " + calc.variant_label if calc.variant_label else ""),
                    "pct": calc.top_percent,
                }
            out.append(card)
        self._cards = out
        chips = [{k: card.get(k) for k in _CHIP_KEYS} for card in out]
        self._revision += 1
        if chips != self._chips:
            self._chips = chips
            self.chipsChanged.emit()
        self.changed.emit()
        self.waitChanged.emit()
        if c and c.wait_remaining() > 0 and not self._tick.isActive():
            self._tick.start()
        self._want_art(cards, [n for n in wanted if n and not n.startswith("UI_Gacha_")])

    # -- art ---------------------------------------------------------------------

    def _want_art(self, cards: list[dict], icon_names: list[str], first: bool = False) -> None:
        """Queue what the cards still lack: small icons, then splash art and the baked
        backdrop, one card at a time so the card on screen fills in without waiting
        for the whole collection (`first` jumps the queue)."""
        missing = [n for n in icons.missing_assets(icon_names) if n not in self._art_tried]
        todo = []
        for b in cards:
            name = backdrop_of(b)
            if name and name not in self._art_tried and not cardart.backdrop_path(name).is_file():
                todo.append(builds.fill_art(b))
        with self._art_lock:
            self._art_tried.update(missing)
            self._art_icons.update(missing)
            queued = {backdrop_of(q) for q in self._art_queue}
            fresh = [b for b in todo if backdrop_of(b) not in queued]
            if first:
                keep = {backdrop_of(b) for b in todo}
                self._art_queue = todo + [q for q in self._art_queue if backdrop_of(q) not in keep]
            else:
                self._art_queue += fresh
            if self._art_running or not (self._art_icons or self._art_queue):
                return
            self._art_running = True
        threading.Thread(target=self._art_worker, daemon=True).start()

    def _art_worker(self) -> None:
        last = time.monotonic()
        while True:
            with self._art_lock:
                batch, self._art_icons = sorted(self._art_icons), set()
            if batch:
                icons.download(batch)
                self._artArrived.emit()
            with self._art_lock:
                card = self._art_queue.pop(0) if self._art_queue else None
                if card is None and not self._art_icons:
                    self._art_running = False
                    break
            if card is None:
                continue
            name = backdrop_of(card)
            self._art_tried.add(name)
            if not icons.path(card["splash"]).is_file():
                icons.download([card["splash"]])
            ensure_backdrop(card)
            # Republishing rebuilds the page's character grid, so not for every card.
            if time.monotonic() - last > 2.5 or not self._art_queue:
                last = time.monotonic()
                self._artArrived.emit()

    @Slot(str)
    def prefer(self, avatar_id: str) -> None:
        """The card on screen: its art goes to the front of the line."""
        c = self._collection
        card = c.builds.get(avatar_id) if c else None
        if card is not None:
            self._want_art([card], [], first=True)

    # -- card display -------------------------------------------------------------

    @Property(str, notify=metricChanged)
    def cardMetric(self) -> str:
        """"cv" or "rv": the figure the cards show for artifacts."""
        return self._settings.card_metric if self._settings.card_metric in ("cv", "rv") else "cv"

    @Slot(str)
    def setCardMetric(self, metric: str) -> None:
        if metric in ("cv", "rv") and metric != self._settings.card_metric:
            self._settings.card_metric = metric
            self._settings.save()
            self.metricChanged.emit()

    def _load_akasha(self) -> None:
        """Fetch the Akasha.cv ranks for the collection's UID on a worker thread."""
        if self._akasha_loading or not self._collection:
            return
        uid = self._collection.uid
        self._akasha_loading = True

        def fetch() -> None:
            try:
                lb = akasha.live_builds(uid)
                calcs, status = {}, ""
                for b in list(self._collection.builds.values()):
                    entry = lb.get(b["avatarId"])
                    if entry is None:
                        continue
                    info = akasha.build_info(uid, b["avatarId"], entry["md5"])
                    calc = akasha.pick(info.calcs, (b.get("weapon") or {}).get("name", ""))
                    if calc:
                        calcs[b["avatarId"]] = calc
                    time.sleep(akasha.PAUSE)
            except akasha.AkashaError as e:
                calcs, status = {}, f"Akasha ranks unavailable: {e}"
            self._akashaArrived.emit((calcs, status))
        threading.Thread(target=fetch, daemon=True).start()

    def _on_akasha(self, payload) -> None:
        calcs, status = payload
        if calcs or not status:
            self._akasha = calcs
        self._akasha_status = status
        self._akasha_loading = False
        self.akashaChanged.emit()
        self._publish()

    def _on_art(self) -> None:
        self._publish()

    def _on_tick(self) -> None:
        self.waitChanged.emit()
        if not self._collection or self._collection.wait_remaining() <= 0:
            self._tick.stop()

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()

    def shutdown(self) -> None:
        w = self._worker
        if w is not None and w.isRunning():
            w.wait(8000)
