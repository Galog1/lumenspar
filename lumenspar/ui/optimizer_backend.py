"""QML bridge for the optimizer page.

Searches run on a worker thread; conditional CRIT Rate is read from set and
weapon texts (weapon passives are fetched once from Project Amber and cached).
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from .. import builds, passives
from .. import optimizer as O
from ..wishes import icons
from .backend import _Worker
from .builds_backend import art_names, decorate, make_panel, panel_name

LABELS = {"hp": "HP", "hp_": "HP%", "atk": "ATK", "atk_": "ATK%", "def": "DEF", "def_": "DEF%",
          "eleMas": "Elemental Mastery", "enerRech_": "Energy Recharge",
          "critRate_": "CRIT Rate", "critDMG_": "CRIT DMG", "heal_": "Healing Bonus"}
for _e in ("physical", "pyro", "hydro", "electro", "cryo", "anemo", "geo", "dendro"):
    LABELS[f"{_e}_dmg_"] = f"{_e.capitalize()} DMG Bonus"

_MAIN_SLOTS = ("sands", "goblet", "circlet")


def set_crit(set_key: str) -> list[tuple[float, str]]:
    """Conditional CRIT Rate of a set's 4-piece (and its 2-piece, when that is not a flat stat)."""
    two, four = passives.set_bonuses(set_key)
    found = passives.conditional_crit(four)
    if not passives.set_static_2pc(set_key):
        found += passives.conditional_crit(two)
    return found


def _num(v) -> float | None:
    """A QML value as a float, or None when it is empty or not a number."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _numbers(d) -> dict[str, float]:
    out = {}
    for k, v in (d or {}).items():
        n = _num(v)
        if n is not None:
            out[str(k)] = n
    return out


def goal_from_qml(g: dict) -> O.Goal:
    """The page's goal map as an optimizer Goal (values may come from QJSValue as any plain type)."""
    ratio = ("critRate_", 1.0, "critDMG_", 2.0)
    raw = g.get("ratio")
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        a, b = _num(raw[1]), _num(raw[3])
        if a is not None and b is not None:
            ratio = (str(raw[0]), a, str(raw[2]), b)
    mains = {}
    for slot, values in (g.get("mains") or {}).items():
        if slot in _MAIN_SLOTS:
            mains[slot] = [str(v) for v in (values or [])]
    level = _num(g.get("minLevel"))
    top = _num(g.get("top"))
    return O.Goal(
        scaling=str(g.get("scaling") or "atk"),
        mode=str(g.get("mode") or "damage"),
        set_key=str(g.get("setKey") or ""),
        mains=mains,
        weights=_numbers(g.get("weights")),
        targets={k: v for k, v in _numbers(g.get("targets")).items() if v > 0},
        minimums=_numbers(g.get("minimums")),
        ratio=ratio,
        extra_crit=_num(g.get("extraCrit")) or 0.0,
        use_equipped=bool(g.get("useEquipped", True)),
        min_level=int(level) if level is not None else 16,
        top=int(top) if top is not None else 5,
    )


def score_text(mode: str, r: O.Result) -> str:
    """The mode's primary number in words."""
    if mode == "weights":
        return f"{r.score:.1f} weighted rolls"
    if mode == "targets":
        return "all targets met" if r.score <= 0 else f"{r.score * 100:.0f}% short of a target"
    if mode == "ratio":
        return f"{r.score:.1f} balanced"
    return f"{r.damage:,.0f} damage estimate"


def deltas(before: dict, after: dict, element: str) -> list[dict]:
    """Stat rows that differ between two builds (small changes are rounding noise)."""
    dmg = f"{element.lower()}_dmg_"
    keys = ["hp", "atk", "def", "eleMas", "critRate_", "critDMG_", "enerRech_",
            dmg if dmg in O.IDX else "physical_dmg_"]
    rows = []
    for k in keys:
        diff = after[k] - before[k]
        if abs(diff) > 0.05:
            rows.append({"label": "Max HP" if k == "hp" else LABELS[k],
                         "before": builds.fmt(k, before[k]), "after": builds.fmt(k, after[k]),
                         "diff": diff, "better": after[k] >= before[k] - 1e-9})
    return rows


def _set_name(set_key: str) -> str:
    return builds._items("artifact_sets.json", "key").get(set_key, {}).get("name", set_key)


def _weapon_text(card: dict) -> str:
    weapon = card.get("weapon") or {}
    if not weapon.get("id"):
        return ""
    return passives.weapon_passive(weapon["id"], int(weapon.get("refinement") or 1))


class OptimizerBackend(QObject):
    changed = Signal()
    busyChanged = Signal()
    statusChanged = Signal()
    resultsChanged = Signal()
    critChanged = Signal()
    _critReady = Signal(object)
    _artArrived = Signal()

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._collection = builds.latest()
        self._selected = ""
        self._source = str(settings.export_path)
        self._pieces: list = []
        self._piece_count = 0
        self._sets: list = []
        self._results: list = []
        self._raw_cards: list[dict] = []     # result cards before decoration, for art refreshes
        self._current: dict = {}
        self._crit: dict = {"sources": [], "total": 0.0, "note": ""}
        self._busy = False
        self._status = ""
        self._stop = False
        self._worker: _Worker | None = None
        self._on_done = None          # what to run, on the GUI thread, when the job ends
        self._art_fetch = False
        self._art_tried: set[str] = set()
        self._critReady.connect(self._on_crit)
        self._artArrived.connect(self._on_art)
        self._load_pieces()
        cards = self._collection.ordered() if self._collection else []
        if cards:
            self._selected = next((b for b in cards if "fight" in b), cards[0])["avatarId"]
        self._fetch_art()

    # -- what the page shows ----------------------------------------------

    def _card(self) -> dict | None:
        """The selected build card as stored (no art URLs)."""
        if self._collection and self._selected in self._collection.builds:
            return self._collection.builds[self._selected]
        return None

    @Property("QVariantList", notify=changed)
    def characters(self) -> list:
        cards = self._collection.ordered() if self._collection else []
        return [{"avatarId": b["avatarId"], "name": b["name"], "element": b["element"],
                 "rarity": b["rarity"], "iconUrl": decorate(b)["iconUrl"], "ready": "fight" in b}
                for b in cards]

    @Property(str, notify=changed)
    def selected(self) -> str:
        return self._selected

    @Property("QVariantMap", notify=changed)
    def card(self) -> dict:
        b = self._card()
        return {**decorate(b), "inShowcase": True} if b else {}

    @Property(str, notify=changed)
    def element(self) -> str:
        b = self._card()
        return b["element"] if b else ""

    @Property(str, notify=changed)
    def sourcePath(self) -> str:
        return self._source

    @Property(int, notify=changed)
    def pieceCount(self) -> int:
        return self._piece_count

    @Property("QVariantList", notify=changed)
    def sets(self) -> list:
        return self._sets

    @Property("QVariantMap", constant=True)
    def mainChoices(self) -> dict:
        return {slot: [{"key": k, "label": LABELS[k]} for k in keys]
                for slot, keys in O.MAIN_CHOICES.items()}

    @Property("QVariantList", constant=True)
    def substats(self) -> list:
        return [{"key": k, "label": LABELS[k]} for k in O.SUBSTATS]

    @Property("QVariantMap", notify=critChanged)
    def crit(self) -> dict:
        return self._crit

    @Property("QVariantList", notify=resultsChanged)
    def results(self) -> list:
        return self._results

    @Property("QVariantMap", notify=resultsChanged)
    def current(self) -> dict:
        return self._current

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    # -- actions ------------------------------------------------------------

    @Slot(str)
    def setCharacter(self, avatar_id: str) -> None:
        self._collection = builds.latest()      # fresh: a fetch may have added cards
        present = self._collection and avatar_id in self._collection.builds
        self._selected = avatar_id if present else ""
        self._results, self._raw_cards, self._current = [], [], {}
        self.resultsChanged.emit()
        self.changed.emit()
        self._fetch_art()
        self.refreshCrit("")

    @Slot()
    def reload(self) -> None:
        """Re-read the stored cards (after a fetch or a Drive sync)."""
        self._collection = builds.latest()
        cards = self._collection.ordered() if self._collection else []
        if cards and not (self._selected in self._collection.builds):
            self._selected = cards[0]["avatarId"]
        elif not cards:
            self._selected = ""
        self.changed.emit()
        self._fetch_art()

    @Slot(str)
    def chooseFile(self, url: str) -> None:
        self._source = url.removeprefix("file://")
        self._load_pieces()
        self.changed.emit()

    @Slot(str)
    def refreshCrit(self, set_key: str) -> None:
        """Work out the conditional CRIT Rate for the weapon (and a set) off the GUI thread."""
        card = self._card() or {}

        def work() -> None:
            weapon = card.get("weapon") or {}
            wtext = _weapon_text(card)
            sources = [{"label": f"{weapon.get('name', 'Weapon')} R{weapon.get('refinement') or 1}: {snippet}",
                        "value": v} for v, snippet in passives.conditional_crit(wtext)]
            weapon_total = sum(s["value"] for s in sources)
            if set_key:
                for v, snippet in set_crit(set_key):
                    sources.append({"label": f"{_set_name(set_key)} 4-piece: {snippet}", "value": v})
            note = "" if set_key else "Each set's own conditional CRIT Rate is added when that set is tried."
            self._critReady.emit({"sources": sources, "total": sum(s["value"] for s in sources),
                                  "note": note, "weaponTotal": weapon_total})

        threading.Thread(target=work, daemon=True).start()

    @Slot(object)
    def _on_crit(self, crit: dict) -> None:
        self._crit = crit
        self.critChanged.emit()

    @Slot("QVariantMap")
    def run(self, goal_map: dict) -> None:
        card = self._card()
        if self._busy:
            return
        if card is None:
            self._set_status("Choose a character first.")
            return
        goal = goal_from_qml(dict(goal_map))
        source = self._source
        out: list = []

        def job(log) -> None:
            try:
                good = json.loads(Path(source).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RuntimeError("Could not read the artifact file … scan your inventory "
                                   "first, or choose a .GOOD file.") from exc
            pieces = O.load_pieces(good)
            base = O.base_from_card(card)
            weapon_cond = sum(v for v, _ in passives.conditional_crit(_weapon_text(card)))
            element = card["element"]
            # O.search adds goal.extra_crit itself, so it is left out here.
            results = O.search(pieces, base, element, goal,
                               lambda s: weapon_cond + sum(v for v, _ in set_crit(s)),
                               owner=card["name"], should_stop=lambda: self._stop)
            counts = Counter(a.get("setKey") for a in card.get("artifacts") or [] if a.get("setKey"))
            equipped = counts.most_common(1)[0][0] if counts else ""
            cond = weapon_cond + sum(v for v, _ in set_crit(equipped)) + goal.extra_crit
            cur = O.current(card, base, element, goal, cond)
            out.append((len(pieces), results, cur))

        def done(ok: bool, err: str) -> None:
            self._finish()
            if not ok:
                self._set_status(err or "Search failed")
                return
            count, results, cur = out[0]
            element = card["element"]
            self._raw_cards = [O.result_card(r, card) for r in results]
            self._current = {"damage": cur.damage, "damageText": f"{cur.damage:,.0f}",
                             "scoreText": score_text(goal.mode, cur),
                             "card": {**decorate(card), "inShowcase": True}}
            self._results = [
                {"rank": i + 1, "setName": _set_name(r.set_key), "damage": r.damage,
                 "damageText": f"{r.damage:,.0f}",
                 "change": f"{(r.damage / cur.damage - 1) * 100:+.1f}%" if cur.damage else "",
                 "scoreText": score_text(goal.mode, r),
                 "deltas": deltas(cur.stats, r.stats, element),
                 "card": {**decorate(self._raw_cards[i]), "inShowcase": True}}
                for i, r in enumerate(results)]
            self.resultsChanged.emit()
            text = f"Searched {count} artifacts"
            if results:
                text += f" · best: {self._results[0]['setName']}, {self._results[0]['change']}"
            else:
                text += " · no build meets the requirements"
            self._set_status(text)
            self._fetch_art()

        self._stop = False
        self._busy = True
        self.busyChanged.emit()
        self._set_status("Searching…")
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
    def stop(self) -> None:
        self._stop = True
        self._set_status("Stopping…")

    def shutdown(self) -> None:
        self._stop = True
        w = self._worker
        if w is not None and w.isRunning():
            w.wait(8000)

    # -- internals ------------------------------------------------------------

    def _finish(self) -> None:
        w = self._worker
        if w is not None:
            w.wait(5000)
            w.deleteLater()
        self._worker = None
        self._busy = False
        self.busyChanged.emit()

    def _load_pieces(self) -> None:
        """Read the artifact scan (.GOOD) and work out the sets worth offering."""
        try:
            good = json.loads(Path(self._source).read_text(encoding="utf-8"))
            self._pieces = O.load_pieces(good)
        except (OSError, ValueError):
            self._pieces = []
            self._set_status(f"No artifact scan found at {self._source} — scan your "
                             "inventory or choose a .GOOD file.")
        five = [p for p in self._pieces if p.rarity == 5]
        self._piece_count = len(five)
        slots_of: dict[str, set] = {}
        for p in five:
            slots_of.setdefault(p.set_key, set()).add(p.slot)
        counts = Counter(p.set_key for p in five)
        self._sets = sorted(
            ({"key": k, "name": _set_name(k), "count": counts[k]}
             for k, slots in slots_of.items() if len(slots) >= 4),
            key=lambda s: (-s["count"], s["name"]))

    def _fetch_art(self) -> None:
        """Download missing art for the characters, the selected card and the results."""
        cards = self._collection.ordered() if self._collection else []
        sel = self._card()
        names = [b.get("icon", "") for b in cards]
        for b in ([sel] if sel else []) + self._raw_cards:
            names += art_names(b)
        missing = [n for n in icons.missing_assets(names) if n not in self._art_tried]
        splashes = [sel["splash"]] if sel and sel.get("splash") \
            and not icons.path(panel_name(sel["splash"])).is_file() \
            and panel_name(sel["splash"]) not in self._art_tried else []
        if (missing or splashes) and not self._art_fetch:
            self._art_fetch = True
            self._art_tried.update(missing)
            self._art_tried.update(panel_name(s) for s in splashes)

            def fetch() -> None:
                icons.download(missing)
                for s in splashes:
                    if icons.path(s).is_file():
                        make_panel(icons.path(s), icons.path(panel_name(s)))
                self._artArrived.emit()
            threading.Thread(target=fetch, daemon=True).start()

    def _on_art(self) -> None:
        """Art arrived: rebuild the cards so they pick up the new file URLs."""
        self._art_fetch = False
        card = self._card()
        if self._current and card:
            self._current["card"] = {**decorate(card), "inShowcase": True}
        for row, raw in zip(self._results, self._raw_cards):
            row["card"] = {**decorate(raw), "inShowcase": True}
        self.changed.emit()
        self.resultsChanged.emit()
        # Art asked for while this download ran (e.g. results arriving after a
        # character switch) was skipped then; fetch it now.
        self._fetch_art()

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()
