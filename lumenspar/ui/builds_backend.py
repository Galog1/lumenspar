"""QML-facing bridge for the build cards.

A fetch reads the Enka.Network showcase on a worker thread, turns it into
build cards (lumenspar.builds) and merges them into the collection kept for
that UID. Art is downloaded in the background the first time it is needed;
until then the cards show placeholders.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Property, QObject, QRectF, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QPainter, QPainterPath

from .. import builds, enka
from ..wishes import icons
from .backend import _Worker


# The card's splash-art panel, in pixels at 2x: 420x600 on the card, with the
# art scaled to cover a 600px-wide area that starts 120px left of the panel
# (the character sits right of centre in gacha art), and the card's 20px
# corner radius on its left side.
PANEL_W, PANEL_H, PANEL_SHIFT, AREA_W, RADIUS = 840, 1200, 240, 1200, 40


def panel_name(splash: str) -> str:
    return f"{splash}_card" if splash else ""


def make_panel(src: Path, dst: Path) -> bool:
    """Cut the card's left panel out of a splash art image, corners rounded.

    Done once per character, so QML shows a plain image: rounding inside the
    scene would need a shader effect, which not every graphics setup runs.
    """
    img = QImage(str(src))
    if img.isNull():
        return False
    scale = max(AREA_W / img.width(), PANEL_H / img.height())
    w, h = img.width() * scale, img.height() * scale
    x0 = (w - AREA_W) / 2 + PANEL_SHIFT          # centred in the area, top-aligned
    out = QImage(PANEL_W, PANEL_H, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, PANEL_W + 2 * RADIUS, PANEL_H), RADIUS, RADIUS)
    p.setClipPath(clip)
    p.drawImage(QRectF(-x0, 0, w, h), img)
    p.end()
    tmp = dst.with_suffix(".part")
    if not out.save(str(tmp), "PNG"):
        return False
    tmp.replace(dst)
    return True


def _url(asset: str) -> str:
    """A cached asset as a file URL, or "" until it has been downloaded."""
    if not asset:
        return ""
    f = icons.path(asset)
    return QUrl.fromLocalFile(str(f)).toString() if f.is_file() else ""


class BuildsBackend(QObject):
    changed = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    waitChanged = Signal()
    collected = Signal()          # a fetch added or changed cards (for the Drive backup)
    _artArrived = Signal()

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings          # shared with the scanner page's Backend
        self._collection = builds.latest()
        self._showcase: list[str] = []     # avatar ids in the latest fetch's order
        self._cards: list[dict] = []
        self._busy = False
        self._status = ""
        self._worker: _Worker | None = None
        self._on_done = None          # what to run, on the GUI thread, when the job ends
        self._art_fetch = False
        self._art_tried: set[str] = set()
        self._artArrived.connect(self._on_art)
        self._tick = QTimer(self, interval=1000)
        self._tick.timeout.connect(self._on_tick)
        self._publish()

    # -- what the page shows ----------------------------------------------

    @Property("QVariantList", notify=changed)
    def cards(self) -> list:
        return self._cards

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
    def cardPath(self, name: str) -> str:
        """Where "Save image" writes a card: <export folder>/cards/<name> <date>.png."""
        folder = Path(self._settings.export_dir).expanduser() / "cards"
        folder.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\- ]", "", name).strip() or "card"
        return str(folder / f"{safe} {datetime.now():%Y-%m-%d %H%M%S}.png")

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
            card = dict(b)
            card["iconUrl"] = _url(b.get("icon", ""))
            card["splashUrl"] = _url(panel_name(b.get("splash", "")))
            wanted += [b.get("icon", ""), b.get("splash", "")]
            if b.get("weapon"):
                card["weapon"] = {**b["weapon"], "iconUrl": _url(b["weapon"].get("icon", ""))}
                wanted.append(b["weapon"].get("icon", ""))
            card["artifacts"] = [{**a, "iconUrl": _url(a.get("icon", ""))}
                                 for a in b.get("artifacts", [])]
            wanted += [a.get("icon", "") for a in b.get("artifacts", [])]
            card["fetched"] = datetime.fromtimestamp(b.get("fetchedAt", 0)).strftime("%Y-%m-%d %H:%M")
            card["inShowcase"] = b["avatarId"] in self._showcase
            out.append(card)
        self._cards = out
        self.changed.emit()
        self.waitChanged.emit()
        if c and c.wait_remaining() > 0 and not self._tick.isActive():
            self._tick.start()
        missing = [n for n in icons.missing_assets(wanted) if n not in self._art_tried]
        splashes = [b["splash"] for b in cards if b.get("splash")
                    and not icons.path(panel_name(b["splash"])).is_file()
                    and panel_name(b["splash"]) not in self._art_tried]
        if (missing or splashes) and not self._art_fetch:
            self._art_fetch = True
            self._art_tried.update(missing)
            self._art_tried.update(panel_name(s) for s in splashes)
            # Small icons first, so the grid fills in before the large splash art.
            missing.sort(key=lambda n: n.startswith("UI_Gacha_AvatarImg_"))

            def fetch() -> None:
                icons.download(missing)
                for s in splashes:
                    if icons.path(s).is_file():
                        make_panel(icons.path(s), icons.path(panel_name(s)))
                self._artArrived.emit()
            threading.Thread(target=fetch, daemon=True).start()

    def _on_art(self) -> None:
        self._art_fetch = False
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
