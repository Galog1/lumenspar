"""QML bridge for the optimizer page.

Searches run on a worker thread; conditional CRIT Rate is read from set and
weapon texts (weapon passives are fetched once from Project Amber and cached).
"""

from __future__ import annotations

import dataclasses
import json
import math
import threading
import time
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from .. import akasha, builds, damage, passives, teamopt
from .. import optimizer as O
from ..wishes import icons
from .backend import _Worker
from .builds_backend import art_names, decorate, make_panel, panel_name
from .team_backend import formula_group

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
    if mode == "akasha":
        return f"Akasha ≈ {r.score:,.0f}"
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


def four_piece(card: dict) -> str:
    """The set key worn on four or more of the card's artifacts, or ''."""
    counts = Counter(a.get("setKey") for a in card.get("artifacts") or [] if a.get("setKey"))
    for key, n in counts.items():
        if n >= 4:
            return key
    return ""


def same_build(card: dict, sets: dict[str, int]) -> bool:
    """Whether Akasha's live build has the same sets as the card's artifacts."""
    names = builds._items("artifact_sets.json", "key")
    mine = Counter(names.get(a["setKey"], {}).get("name", a["setKey"]) for a in card["artifacts"])
    return dict(mine) == {k: v for k, v in sets.items() if v} and bool(sets)


def top1_targets(stats: dict[str, float], scaling: str, offsets: dict[str, float] | None = None
                 ) -> tuple[dict[str, float], list[str]]:
    """Target values from Akasha's top-1% average stats: crit, the scaling stat's
    total, and ER/EM when the top builds carry any. offsets (panel minus Akasha's
    own view of the player's build) move them onto the in-game panel's scale."""
    keys = ["critRate_", "critDMG_", {"atk": "atk", "hp": "hp", "def": "def", "eleMas": "eleMas"}[scaling]]
    if stats.get("enerRech_", 0) > 100.5:
        keys.append("enerRech_")
    if scaling != "eleMas" and stats.get("eleMas", 0) >= 40:
        keys.append("eleMas")
    keys = [k for k in keys if k in stats]
    off = offsets or {}
    values = {k: stats[k] + off.get(k, 0.0) for k in keys}
    targets = {k: round(values[k], 1) if k.endswith("_") else round(values[k]) for k in keys}
    return targets, keys


def merge_results(results: list[O.Result], top: int) -> list[O.Result]:
    """Results of several searches as one list: repeated piece sets dropped, best score first."""
    seen: set = set()
    out: list[O.Result] = []
    for r in sorted(results, key=lambda x: x.score, reverse=True):
        ids = tuple(p.id for p in r.pieces)
        if ids in seen:
            continue
        seen.add(ids)
        out.append(r)
        if len(out) == top:
            break
    return out


def akasha_info(model, sets: list, mains: dict, calibrated: bool, set_names: dict) -> str:
    """What was learned from a leaderboard, in words."""
    text = (f"Learned this leaderboard's formula from {model.n} builds; it reproduces them to "
            f"within about {model.rms * 100:.1f}%.")
    text += (" Calibrated on your build's Akasha result." if calibrated else
             " Your build isn't on this leaderboard (or Akasha has an older one), so results "
             "are not calibrated to it.")
    parts = [", ".join(f"{set_names.get(k, k)} {share:.0%}" for k, share in sets[:3])]
    parts += [f"{slot} " + "/".join(LABELS.get(k, k) for k, _ in mains.get(slot, [])[:3])
              for slot in _MAIN_SLOTS if mains.get(slot)]
    parts = [x for x in parts if x]
    if parts:
        text += " Top builds use " + "; ".join(parts) + "."
    if model.rms > 0.025:
        text += (" This leaderboard couldn't be learned closely (calculations that combine "
                 "several characters, such as Lunar reactions), so treat the ranks as rough.")
    return text


def _akasha_for(uid: str, card: dict) -> tuple[akasha.Calc, dict, akasha.BuildInfo]:
    """The leaderboard entry, live build and per-build data Akasha holds for the card."""
    lb = akasha.live_builds(uid)
    entry = lb.get(card["avatarId"])
    if entry is None:
        raise akasha.AkashaError(
            f"Akasha has no live build of {card['name']} for this UID yet: look up your UID on "
            "akasha.cv and refresh your profile there, then try again.")
    info = akasha.build_info(uid, card["avatarId"], entry["md5"])
    calc = akasha.pick(info.calcs, (card.get("weapon") or {}).get("name", ""))
    if calc is None:
        raise akasha.AkashaError(f"Akasha has no leaderboard for {card['name']}'s build yet.")
    return calc, entry, info


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
    akashaTop1Changed = Signal()
    akashaBoardsChanged = Signal()
    akashaInfoChanged = Signal()
    teamInfoChanged = Signal()
    _critReady = Signal(object)
    _artArrived = Signal()

    def __init__(self, settings, parent: QObject | None = None, team=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.team = team                      # the TeamBackend whose team, conditions and enemy apply
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
        self._akasha_top1: dict = {}
        self._boards: list[akasha.Board] = []
        self._mine_calcs: list[akasha.Calc] = []
        self._mine_sets: dict = {}
        self._akasha_boards: list = []
        self._akasha_boards_note = ""
        self._akasha_info = ""
        self._art_fetch = False
        self._art_tried: set[str] = set()
        self._tjob: dict | None = None        # a team-damage search in progress
        self._team_connected = False
        self._team_info: dict = {}
        self._critReady.connect(self._on_crit)
        self._artArrived.connect(self._on_art)
        self._load_pieces()
        cards = self._collection.ordered() if self._collection else []
        if cards:
            self._selected = next((b for b in cards if "fight" in b), cards[0])["avatarId"]
        self._fetch_art()
        self.changed.connect(self._refresh_team_info)
        if team is not None:
            for sig in (team.changed, team.formulasUpdated, team.damageChanged):
                sig.connect(self._refresh_team_info)
        self._refresh_team_info()

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

    @Property("QVariantList", notify=akashaBoardsChanged)
    def akashaBoards(self) -> list:
        return self._akasha_boards

    @Property(str, notify=akashaBoardsChanged)
    def akashaBoardsNote(self) -> str:
        return self._akasha_boards_note

    @Property(str, notify=akashaInfoChanged)
    def akashaInfo(self) -> str:
        return self._akasha_info

    @Property("QVariantMap", notify=akashaTop1Changed)
    def akashaTop1(self) -> dict:
        return self._akasha_top1

    @Property("QVariantMap", notify=teamInfoChanged)
    def teamInfo(self) -> dict:
        return self._team_info

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    # -- actions ------------------------------------------------------------

    def _reset_akasha(self) -> None:
        self._akasha_top1 = {}
        self.akashaTop1Changed.emit()
        self._boards, self._mine_calcs, self._mine_sets = [], [], {}
        self._akasha_boards, self._akasha_boards_note, self._akasha_info = [], "", ""
        self.akashaBoardsChanged.emit()
        self.akashaInfoChanged.emit()

    @Slot(str)
    def setCharacter(self, avatar_id: str) -> None:
        self._collection = builds.latest()      # fresh: a fetch may have added cards
        present = self._collection and avatar_id in self._collection.builds
        self._selected = avatar_id if present else ""
        self._reset_akasha()
        self._results, self._raw_cards, self._current = [], [], {}
        self.resultsChanged.emit()
        self.changed.emit()
        self._fetch_art()
        self.refreshCrit("")

    @Slot()
    def reload(self) -> None:
        """Re-read the stored cards (after a fetch or a Drive sync)."""
        self._collection = builds.latest()
        before = self._selected
        cards = self._collection.ordered() if self._collection else []
        if cards and not (self._selected in self._collection.builds):
            self._selected = cards[0]["avatarId"]
        elif not cards:
            self._selected = ""
        if self._selected != before:
            self._reset_akasha()
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
        if goal.mode == "akasha":
            self._set_status("Pick an Akasha leaderboard, then Optimize.")
            return
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
            self._publish(card, results, cur, score_text(goal.mode, cur),
                          [score_text(goal.mode, r) for r in results],
                          [f"{(r.damage / cur.damage - 1) * 100:+.1f}%" if cur.damage else ""
                           for r in results])
            text = f"Searched {count} artifacts"
            if results:
                text += f" · best: {self._results[0]['setName']}, {self._results[0]['change']}"
            else:
                text += " · no build meets the requirements"
            self._set_status(text)

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

    def _publish(self, card: dict, results: list, cur: O.Result, cur_text: str,
                 texts: list[str], changes: list[str]) -> None:
        """Show a search's results next to the current build."""
        element = card["element"]
        self._raw_cards = [O.result_card(r, card) for r in results]
        self._current = {"damage": cur.damage, "damageText": f"{cur.damage:,.0f}",
                         "scoreText": cur_text,
                         "card": {**decorate(card), "inShowcase": True}}
        self._results = [
            {"rank": i + 1, "setName": _set_name(r.set_key), "damage": r.damage,
             "damageText": f"{r.damage:,.0f}",
             "change": changes[i],
             "scoreText": texts[i],
             "deltas": deltas(cur.stats, r.stats, element),
             "card": {**decorate(self._raw_cards[i]), "inShowcase": True}}
            for i, r in enumerate(results)]
        self.resultsChanged.emit()
        self._fetch_art()

    def _start(self, job, done, status: str) -> None:
        self._stop = False
        self._busy = True
        self.busyChanged.emit()
        if status:
            self._set_status(status)
        w = _Worker(job, self)
        self._on_done = done
        w.done.connect(self._job_done)
        self._worker = w
        w.start()

    @Slot()
    def loadBoards(self) -> None:
        """List the Akasha leaderboards for the selected character's weapon (network)."""
        card = self._card()
        if self._busy or card is None:
            return
        uid = self._collection.uid
        out: list = []

        def job(log) -> None:
            all_boards = akasha.boards(card["avatarId"])
            weapon = (card.get("weapon") or {}).get("name", "")
            mine_calcs, mine_sets = [], {}
            try:
                calc, entry, info = _akasha_for(uid, card)
                mine_calcs, mine_sets = info.calcs, entry["sets"]
            except akasha.AkashaError:
                pass
            out.append((all_boards, akasha.boards_for_weapon(all_boards, weapon), weapon,
                        mine_calcs, mine_sets))

        def done(ok: bool, err: str) -> None:
            self._finish()
            if not ok:
                self._set_status(err or "Akasha leaderboards unavailable")
                return
            all_boards, boards_, weapon, mine_calcs, mine_sets = out[0]
            self._boards, self._mine_calcs, self._mine_sets = boards_, mine_calcs, mine_sets
            note = ""
            if not all_boards:
                note = "Akasha has no leaderboards for this character yet."
            elif not boards_:
                note = (f"Akasha's {card['name']} leaderboards are per weapon and none uses "
                        f"{weapon}: " + ", ".join(sorted({b.weapon for b in all_boards})))
            self._akasha_boards = [
                {"calcId": b.calculation_id, "name": b.name, "short": b.short,
                 "details": b.details, "weapon": b.weapon,
                 "variants": [{"name": v.name, "label": v.label} for v in b.variants],
                 # The ER filter the player's own build is ranked under ("" = all
                 # builds): Akasha's suggested filter can exclude the build, and
                 # then every suggestion would be measured against builds it
                 # cannot match.
                 "defaultVariant": next((c.variant for c in mine_calcs
                                         if c.calculation_id == b.calculation_id),
                                        b.default_variant),
                 "yourRank": next((c.rank_text() for c in mine_calcs
                                   if c.calculation_id == b.calculation_id), "")}
                for b in boards_]
            self._akasha_boards_note = note
            self.akashaBoardsChanged.emit()
            self._set_status(note or f"{len(boards_)} Akasha leaderboards for {card['name']}")

        self._start(job, done, "Reading Akasha.cv…")

    @Slot(str, str, int, bool)
    def runAkasha(self, calc_id: str, variant: str, min_level: int, use_equipped: bool) -> None:
        """Find the best build for one Akasha leaderboard, learning everything from its top builds."""
        card = self._card()
        if self._busy:
            self._set_status("Another job is running.")
            return
        if card is None:
            self._set_status("Choose a character first.")
            return
        board = next((b for b in self._boards if b.calculation_id == calc_id), None)
        if board is None:
            self._set_status("Pick an Akasha leaderboard first.")
            return
        source = self._source
        mine_calcs, mine_sets = self._mine_calcs, self._mine_sets
        out: list = []

        def job(log) -> None:
            element = card["element"]
            calc = akasha.calc_for_board(board, variant, mine_calcs)
            rows, _top = akasha.sample(calc)
            model = akasha.fit(rows, element)
            sets, mains = akasha.common(rows)
            try:
                good = json.loads(Path(source).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RuntimeError("Could not read the artifact file … scan your inventory "
                                   "first, or choose a .GOOD file.") from exc
            pieces = O.load_pieces(good)
            base = O.base_from_card(card)
            calibrated = calc.result > 0 and same_build(card, mine_sets)
            if calibrated:
                pred = model.predict_stats(O.current(card, base, element, O.Goal(), 0.0).stats,
                                           four_piece(card))
                shift = math.log(calc.result / pred) if pred > 0 else 0.0
                model = dataclasses.replace(
                    model, default=model.default + shift,
                    factors={k: v + shift for k, v in model.factors.items()})
            set_keys = [k for k, _ in sets if k in model.factors][:4] or [k for k, _ in sets][:3]
            allowed = {slot: [k for k, _ in mains.get(slot, [])] for slot in _MAIN_SLOTS}
            minimums: dict[str, float] = {}
            v = next((x for x in board.variants if x.name == variant), None)
            if v is not None and variant:
                minimums["enerRech_"] = v.min_er
            found: list[O.Result] = []
            for key in set_keys:
                if self._stop:
                    break
                goal = O.Goal(scaling=model.scaling, mode="akasha", akasha=model, set_key=key,
                              mains=allowed, minimums=dict(minimums), use_equipped=use_equipped,
                              min_level=min_level, top=5)
                found += O.search(pieces, base, element, goal, lambda s: 0.0,
                                  owner=card["name"], should_stop=lambda: self._stop)
            results = merge_results(found, 5)
            cur = O.current(card, base, element, O.Goal(mode="akasha", akasha=model), 0.0)
            ranks: list = []
            for r in results:
                if self._stop:
                    break
                try:
                    ranks.append(akasha.rank_of(calc, r.score))
                except akasha.AkashaError:
                    ranks.append(None)
                time.sleep(akasha.PAUSE)
            cur_rank = None
            if calibrated and calc.ranking:
                cur_rank = calc.ranking
            elif not self._stop:
                try:
                    cur_rank = akasha.rank_of(calc, cur.score)
                except akasha.AkashaError:
                    pass
            names = {k: _set_name(k) for k, _ in sets}
            out.append((calc, model, sets, mains, calibrated, results, cur, ranks, cur_rank,
                        names, len(pieces)))

        def done(ok: bool, err: str) -> None:
            self._finish()
            if not ok:
                self._set_status(err or "Akasha search failed")
                return
            calc, model, sets, mains, calibrated, results, cur, ranks, cur_rank, names, _n = out[0]

            def score_of(i: int, r: O.Result) -> str:
                rank = ranks[i] if i < len(ranks) else None
                text = f"Akasha ≈ {r.score:,.0f}"
                if rank:
                    text += f" · #{rank:,}"
                    if calc.out_of:
                        text += f" · top {rank / calc.out_of * 100:.1f}%"
                return text

            if calibrated:
                rt = calc.rank_text()
                cur_text = f"Akasha {calc.result:,.0f}" + (f" · {rt}" if rt else "")
            else:
                cur_text = f"Akasha ≈ {cur.score:,.0f}" + (f" · #{cur_rank:,}" if cur_rank else "")
            self._publish(card, results, cur, cur_text,
                          [score_of(i, r) for i, r in enumerate(results)],
                          [f"{(r.score / cur.score - 1) * 100:+.1f}%" if cur.score else ""
                           for r in results])
            self._akasha_info = akasha_info(model, sets, mains, calibrated, names)
            self.akashaInfoChanged.emit()
            if results:
                best = ranks[0] if ranks else None
                text = f"Best on {board.name}: {self._results[0]['setName']}"
                text += f" · ≈ #{best:,}" if best else ""
            else:
                text = f"No build meets the requirements on {board.name}"
            self._set_status(text)

        self._start(job, done, "Learning the leaderboard and searching…")

    @Slot(str)
    def akashaTargets(self, scaling: str) -> None:
        """Fill the target values from the top 1% of the character's Akasha leaderboard."""
        card = self._card()
        if self._busy or card is None:
            return
        uid = self._collection.uid
        out: list = []

        def job(log) -> None:
            calc, entry, info = _akasha_for(uid, card)
            stats = info.top1.get(calc.calculation_id)
            if not stats:
                raise akasha.AkashaError("Akasha has no top-1% averages for this leaderboard yet.")
            base = O.base_from_card(card)
            panel = O.current(card, base, card["element"], O.Goal(), 0.0).stats
            mine = info.mine.get(calc.calculation_id, {})
            offsets = ({k: panel[k] - mine[k] for k in mine if k in panel}
                       if same_build(card, entry["sets"]) else {})
            targets, keys = top1_targets(stats, scaling, offsets)
            out.append((calc, targets, keys, bool(offsets)))

        def done(ok: bool, err: str) -> None:
            self._finish()
            if not ok:
                self._set_status(err or "Akasha targets unavailable")
                return
            calc, targets, keys, shifted = out[0]
            self._akasha_top1 = {
                "calc": calc.name + (" · " + calc.variant_label if calc.variant_label else ""),
                "rank": calc.rank_text(), "targets": targets, "priority": keys}
            self.akashaTop1Changed.emit()
            note = (" (shifted to your panel: Akasha measures a standardised C0 character with "
                    "an R1 weapon)" if shifted else
                    " (not shifted: Akasha last saw a different build — refresh your profile "
                    "on akasha.cv)")
            self._set_status(f"Targets set to the top 1% of Akasha's {calc.name} leaderboard."
                             + note)

        self._stop = False
        self._busy = True
        self.busyChanged.emit()
        self._set_status("Reading Akasha.cv…")
        w = _Worker(job, self)
        self._on_done = done
        w.done.connect(self._job_done)
        self._worker = w
        w.start()

    # -- team damage ----------------------------------------------------------

    @Slot()
    def _refresh_team_info(self) -> None:
        card = self._card()
        info = {"inTeam": False, "name": card["name"] if card else "", "targets": [],
                "defaultTarget": "", "hasFormulas": False}
        ctx = self.team.optimize_context(card["key"]) if card and self.team is not None else None
        if ctx is not None:
            info["inTeam"] = True
            hits = [f for f in ctx["formulas"] if f.get("q") == "dmg"]
            info["hasFormulas"] = bool(hits)
            info["targets"] = [
                {"key": f"{f['sheet']}:{f['name']}",
                 "label": damage.formula_label(f["sheet"], f["name"], f.get("move", "")),
                 "group": formula_group(f)} for f in hits]
            moves = [f for f in hits if f.get("move") in ("skill", "burst", "normal", "charged")]
            best = max(moves, key=lambda f: f.get("avg") or 0, default=None) or (
                hits[0] if hits else None)
            if best is not None:
                info["defaultTarget"] = f"{best['sheet']}:{best['name']}"
        if info != self._team_info:
            self._team_info = info
            self.teamInfoChanged.emit()

    @Slot(str, str, "QVariantMap", "QVariantMap", int, bool)
    def runTeam(self, target: str, set_key: str, mains: dict, minimums: dict,
                min_level: int, use_equipped: bool) -> None:
        """Find the artifacts that maximize the character's exact damage with the team."""
        card = self._card()
        if self._busy:
            self._set_status("Another job is running.")
            return
        if card is None:
            self._set_status("Choose a character first.")
            return
        ctx = self.team.optimize_context(card["key"]) if self.team is not None else None
        if ctx is None:
            self._set_status(f"Add {card['name']} to the team in Team & damage first.")
            return
        try:
            frames = teamopt.frames(target, {}, ctx["formulas"])
            base = O.base_from_card(card)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        try:
            good = json.loads(Path(self._source).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._set_status("Could not read the artifact file … scan your inventory first, "
                             "or choose a .GOOD file.")
            return
        pieces = teamopt.with_card_pieces(O.load_pieces(good), card)
        allowed = {str(slot): [str(v) for v in (values or [])]
                   for slot, values in dict(mains or {}).items() if slot in _MAIN_SLOTS}
        owner = card["key"]
        keys = [set_key] if set_key else teamopt.sets_with_four(
            pieces, allowed, min_level, use_equipped, owner)
        fams = teamopt.families(pieces, keys, allowed, min_level, use_equipped, owner)
        if not fams:
            self._set_status("No artifacts match the set and main-stat choices.")
            return
        base_req = {"members": ctx["members"], "conditionals": ctx["conditionals"],
                    "enemy": ctx["enemy"],
                    "target": {"member": ctx["index"], "frames": frames}}
        engine = self.team.engine()
        if not self._team_connected:
            self._team_connected = True
            engine.finished.connect(self._on_team_finished)
            engine.failed.connect(self._on_team_failed)
        mins = {k: v for k, v in _numbers(minimums).items() if v > 0}
        current = teamopt.card_candidates(card)
        job = {"card": card, "base": base, "by_id": {p.id: p for p in pieces},
               "cur_id": None, "search_id": None, "cur": None, "search": None}
        self._tjob = job
        if current:
            job["cur_id"] = engine.request("optimize", {
                **base_req, "minimums": [], "families": [[[c] for c in current]], "top": 1})
        job["search_id"] = engine.request("optimize", {
            **base_req, "minimums": teamopt.engine_minimums(mins), "families": fams, "top": 5})
        self._stop = False
        self._busy = True
        self.busyChanged.emit()
        self._set_status(f"Searching {len(fams)} families…")

    @Slot(int, object)
    def _on_team_finished(self, req_id: int, out) -> None:
        job = self._tjob
        if job is None:
            return
        if req_id == job["cur_id"]:
            job["cur_id"], job["cur"] = None, out
        elif req_id == job["search_id"]:
            job["search_id"], job["search"] = None, out
        else:
            return
        if job["cur_id"] is None and job["search_id"] is None:
            self._tjob = None
            self._finish()
            self._publish_team(job)

    @Slot(int, str)
    def _on_team_failed(self, req_id: int, message: str) -> None:
        job = self._tjob
        if job is None or req_id not in (job["cur_id"], job["search_id"]):
            return
        self._tjob = None
        self._finish()
        self._set_status(message)

    def _publish_team(self, job: dict) -> None:
        card, base = job["card"], job["base"]
        if card["avatarId"] != self._selected:
            return                                  # another character was chosen meanwhile
        search = job["search"] or {}
        builds_ = (job["cur"] or {}).get("builds") or []
        cur_val = builds_[0]["value"] if builds_ else 0.0
        results = []
        for b in search.get("builds", []):
            pieces = [job["by_id"][i] for i in b["ids"] if i in job["by_id"]]
            if len(pieces) == 5:
                results.append(O.result_of(pieces, base, float(b["value"])))
        cur = dataclasses.replace(O.current(card, base, card["element"], O.Goal(), 0.0),
                                  damage=cur_val, score=cur_val)
        self._publish(card, results, cur, f"Damage {cur_val:,.0f}" if cur_val else "",
                      [f"Damage {r.damage:,.0f}" for r in results],
                      [f"{(r.damage / cur_val - 1) * 100:+.1f}%" if cur_val else ""
                       for r in results])
        if results:
            best = self._results[0]
            text = f"Searched {search.get('evaluated', 0):,} builds " \
                   f"({search.get('pruned', 0):,} after pruning) · best: {best['setName']}"
            self._set_status(text + (f", {best['change']}" if best["change"] else ""))
        else:
            self._set_status("No build meets the minimums.")

    @Slot(bool, str)
    def _job_done(self, ok: bool, err: str) -> None:
        done, self._on_done = self._on_done, None
        if done is not None:
            done(ok, err)

    @Slot()
    def stop(self) -> None:
        if self._tjob is not None:           # engine requests can't be cancelled; drop theirs
            self._tjob = None
            self._finish()
            self._set_status("Stopped.")
            return
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
