"""The artifact scan loop.

Navigation is driven by what is on screen rather than by dead reckoning. The
inventory scrolls by an unknown number of pixels per wheel click, and Genshin
animates it, so instead of assuming a scroll distance we fingerprint each row
of tiles and treat any row we have not fingerprinted before as new work. That
makes the loop tolerant of over- and under-scrolling, and of the view drifting
while an artifact is being read.
"""

from __future__ import annotations

import bisect
import hashlib
import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np

from ..config import Settings
from ..good import Artifact
from ..ocr import engine as ocr
from ..ocr import preprocess as pp
from .artifact_parse import build_artifact
from .artifacts import read_panel
from .grid import Grid, GridError, Tile, find_grid
from .layout import LayoutError, Region


# AI-mode only; raised by the Gemini client and re-exported for the scanners.
from ..ai.gemini import GeminiAuthError, GeminiError, GeminiModelError


class ScanDriver(Protocol):
    """Everything the loop needs from the outside world."""

    def grab(self) -> np.ndarray: ...
    def click(self, x: int, y: int) -> None: ...
    def scroll(self, clicks: int) -> None: ...
    def sleep(self, seconds: float) -> None: ...
    # Optional: def hover(self, x: int, y: int) -> bool -- move without clicking.


@dataclass(slots=True)
class ScanStats:
    seen: int = 0
    kept: int = 0
    skipped_rarity: int = 0
    failed: int = 0
    pages: int = 0
    retried: int = 0
    ocr_crashes: int = 0
    total_expected: int | None = None


@dataclass(slots=True)
class ScanResult:
    items: list = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    stats: ScanStats = field(default_factory=ScanStats)


# Reads the text in a cropped strip of UI. Tesseract by default; in AI mode
# without Tesseract (always the case on Windows) Gemini stands in.
TextReader = Callable[[np.ndarray], str]


def read_tab_title(frame: np.ndarray, read_text: TextReader | None = None) -> str:
    """Read the tab name from the top-left, e.g. "Character Development Items".

    More useful than the top-right counter: the materials tabs both show
    "Inventory capacity N/M" there and are indistinguishable, but their titles
    ("Character Development Items" and "Materials") are not.
    """
    h, w = frame.shape[:2]
    box = Region(int(w * 0.055), int(h * 0.012), int(w * 0.245), int(h * 0.080))
    if read_text is not None:
        return " ".join(read_text(box.crop(frame)).split())
    txt = ocr.read(pp.prep_text(box.crop(frame), dark_text=False, target_height=64),
                   psm=ocr.PSM_BLOCK)
    return " ".join(txt.split())


def read_inventory_header(frame: np.ndarray,
                          read_text: TextReader | None = None) -> tuple[str, int | None]:
    """Read the header, e.g. "Artifacts 385/2700" -> ("artifacts", 385).

    The label matters as much as the count: it is the only cheap way to notice
    that the wrong inventory tab is open before spending minutes scanning it.
    """
    h, w = frame.shape[:2]
    # The count is gold on a dark bar -- too saturated for the neutral-glyph
    # path used on the detail header, so threshold on luminance instead.
    box = Region(int(w * 0.80), int(h * 0.026), int(w * 0.945), int(h * 0.062))
    if read_text is not None:
        txt = read_text(box.crop(frame))
    else:
        txt = ocr.read(pp.prep_text(box.crop(frame), dark_text=False, target_height=70),
                       psm=ocr.PSM_LINE)
    label = "".join(c for c in txt if c.isalpha()).lower()
    digits = "".join(c if c.isdigit() else " " for c in txt).split()
    owned = None
    if len(digits) >= 2:
        try:
            n = int(digits[-2])
            owned = n if 0 < n <= 10000 else None
        except ValueError:
            owned = None
    return label, owned


def tile_fingerprint(frame: np.ndarray, tile: Tile) -> bytes:
    """Coarse hash of a tile's icon.

    Sampled from the middle of the tile so the white selection glow on the
    border does not change the fingerprint of an already-scanned tile.
    """
    r = tile.rect
    h, w = r.y1 - r.y0, r.x1 - r.x0
    core = frame[r.y0 + int(h * 0.20): r.y0 + int(h * 0.72),
                 r.x0 + int(w * 0.20): r.x1 - int(w * 0.20)]
    if core.size == 0:
        return b""
    g = core.mean(2)
    ys = np.linspace(0, g.shape[0] - 1, 8).astype(int)
    xs = np.linspace(0, g.shape[1] - 1, 8).astype(int)
    small = g[np.ix_(ys, xs)]
    return bytes(((small / 32).astype(np.uint8)).ravel())


# The band of the screen that actually scrolls, as fractions of frame height.
# Measured by diffing frames from before and after a real scroll (4K, artifact
# tab): rows 319..1917 of 2160 change, every row outside them is static UI --
# the tab bar and the "Show 5-star Artifacts" toggle above, the buttons below.
# Taken a few pixels inside those edges.
VIEWPORT_Y = (0.152, 0.882)


def scroll_viewport(grid: "Grid", frame_h: int) -> tuple[int, int]:
    """Rows to compare when measuring a scroll: the grid, kept off static UI.

    The detected grid can reach *above* the viewport: when the top row is
    partly hidden under the toggle bar, its tile rect starts behind the bar.
    The bar never moves, so with it in the comparison a small shift always
    matched best -- and since tiles repeat every row, "10px" (the true 360px
    minus one 350px row) fit nearly as well as the real answer. A real scan
    stopped at 160 of 380 artifacts that way, believing the list was stuck.
    The bottom edge used to be the frame bottom, which takes in the static
    button bar for the same reason.
    """
    top = max(grid.region.y0, int(frame_h * VIEWPORT_Y[0]))
    bottom = min(frame_h, int(frame_h * VIEWPORT_Y[1]))
    return top, max(bottom, top + 1)


def measure_scroll_shift(
    before: np.ndarray,
    after: np.ndarray,
    x0: int,
    x1: int,
    y_top: int,
    y_bot: int,
    max_shift: int,
    step: int = 4,
) -> int:
    """How many pixels the grid moved up between two frames.

    Scrolling down moves content up, so `after[y]` shows what `before[y + s]`
    showed. We slide a band of the new frame over the old one and take the
    offset with the lowest mean absolute difference. Columns are subsampled
    because only the vertical alignment matters.

    `y_top`/`y_bot` must bound the *scrolling* region. Including the header --
    the tab bar and the "Show 5-star Artifacts" toggle never move -- makes
    zero shift always look like the best match, so every scroll measures 0.
    """
    A = before[:, x0:x1:step].mean(2).astype(np.float32)
    B = after[:, x0:x1:step].mean(2).astype(np.float32)
    y_bot = min(y_bot, A.shape[0], B.shape[0])
    usable = y_bot - y_top
    if usable < 120:
        return 0

    # The band must sit high enough in the scrolling region that
    # `y0 + max_shift + band_h` still fits inside it, or large shifts cannot be
    # searched and the function quietly returns a truncated answer.
    y0 = y_top + 8
    band_h = min(usable // 3, y_bot - y0 - max_shift)
    if band_h < 80:
        band_h = 80
        max_shift = max(0, y_bot - y0 - band_h)
    band = B[y0 : y0 + band_h]

    best_s, best_err = 0, float("inf")
    for sft in range(0, max_shift + 1, 2):              # coarse
        seg = A[y0 + sft : y0 + sft + band_h]
        if seg.shape[0] != band_h:
            break
        err = float(np.abs(seg - band).mean())
        if err < best_err:
            best_err, best_s = err, sft
    for sft in range(max(0, best_s - 2), best_s + 3):   # refine
        seg = A[y0 + sft : y0 + sft + band_h]
        if seg.shape[0] != band_h:
            continue
        err = float(np.abs(seg - band).mean())
        if err < best_err:
            best_err, best_s = err, sft
    return best_s


def row_signature(frame: np.ndarray, tiles: list[Tile]) -> bytes:
    joined = b"".join(tile_fingerprint(frame, t) for t in tiles)
    return hashlib.blake2b(joined, digest_size=16).digest()


class _AiPipeline:
    """Send Gemini batches in the background while the scan keeps moving.

    A batch request takes several seconds, and the scan used to sit idle for
    all of it: click six items, wait for the answer, click six more. Now each
    batch goes to a worker thread and the scanner carries on capturing the
    next one. At most `max_in_flight` requests are outstanding -- past that the
    scanner waits for the oldest -- which bounds memory (a pending 4K frame is
    ~25 MB) and the request rate the free tier sees.

    Answers are settled strictly in the order the batches were sent, and
    always on the scan thread, so results, failure dumps and log lines come
    out in scan order and only the Gemini call itself runs concurrently.
    """

    def __init__(self, max_in_flight: int) -> None:
        self._max = max(1, int(max_in_flight))
        self._pool: ThreadPoolExecutor | None = None
        self._queue: deque = deque()

    def submit(self, work: Callable[[], object],
               settle: Callable[[object, BaseException | None], None]) -> None:
        while len(self._queue) >= self._max:
            self._settle_oldest()
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self._max,
                                            thread_name_prefix="gemini")
        self._queue.append((self._pool.submit(work), settle))
        self.harvest()

    def harvest(self) -> None:
        """Settle every batch that has already been answered, oldest first."""
        while self._queue and self._queue[0][0].done():
            self._settle_oldest()

    def drain(self) -> None:
        """Wait for and settle everything still outstanding."""
        while self._queue:
            self._settle_oldest()
        self._shutdown(wait=True)

    def cancel(self) -> None:
        """Drop everything outstanding (the scan is being aborted)."""
        for fut, _ in self._queue:
            fut.cancel()
        self._queue.clear()
        self._shutdown(wait=False)

    def _shutdown(self, wait: bool) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=not wait)
            self._pool = None

    def _settle_oldest(self) -> None:
        fut, settle = self._queue.popleft()
        try:
            outcome = fut.result()
        except Exception as exc:  # handed to settle, which decides what it means
            settle(None, exc)
            return
        settle(outcome, None)


def _next_failure_stamp(scanner) -> str:
    """Claim the next dump number in the failure folder, never reusing one.

    Numbering used to restart at 0001 for every scanner, so the weapon pass of
    a scan overwrote the artifact pass's screenshots wherever a number and a
    tile coincided (fail_0001_tile_r0c0.png was both), and every new run did
    the same to the last. Counting on from the highest number already in the
    folder keeps every dump. The first failure of each scanner also writes a
    header to failures.txt, so one run's entries can be told from another's.
    """
    d = scanner.failure_dir
    d.mkdir(parents=True, exist_ok=True)
    taken = [int(m.group(1)) for f in d.glob("fail_*")
             if (m := re.match(r"fail_(\d+)_", f.name))]
    seq = max(taken, default=0) + 1
    if not scanner._fail_seq:
        with (d / "failures.txt").open("a", encoding="utf-8") as fh:
            fh.write(f"── {datetime.now():%Y-%m-%d %H:%M} {scanner.item_label} scan ──\n")
    scanner._fail_seq = seq
    return f"{seq:04d}"


class ArtifactScanner:
    def __init__(
        self,
        driver: ScanDriver,
        settings: Settings,
        log: Callable[[str], None] = print,
        should_stop: Callable[[], bool] = lambda: False,
        verbose: bool = False,
        failure_dir=None,
    ) -> None:
        self.d = driver
        self.s = settings
        self.log = log
        self.should_stop = should_stop
        self.verbose = verbose
        self.failure_dir = failure_dir
        self._fail_seq = 0
        self._pitch_y = 0     # cached from the loop; re-detecting per tile is slow
        self._stall_dumps = 0  # scroll-stall frame pairs saved this scan (capped)
        self._read_text: TextReader | None = None

        # AI reader mode: panels' text is batched to Gemini, pixels still own
        # rarity/locked/elixir/refinement. The scanner only collects frames
        # and flushes a batch; it never reads one here.
        if self.s.reader_mode == "ai":
            from ..ai.gemini import Gemini, Usage

            if not self.s.gemini_key():
                raise RuntimeError("AI reader selected but no Gemini API key is set")
            self._gemini = Gemini(self.s.gemini_key(), self.s.gemini_model,
                                  log=self.log, usage=Usage())
            if not ocr.available():
                from ..ai.reader import line_reader
                self._read_text = line_reader(self._gemini)
            self._pending: list[tuple[str, np.ndarray, Tile]] = []
            self._ai_abort = False
            self._ai_pipe = _AiPipeline(self.s.ai_in_flight)

    def _dbg(self, msg: str) -> None:
        if self.verbose:
            self.log(f"    [dbg] {msg}")

    # -- helpers ---------------------------------------------------------

    def _wait(self, name: str) -> None:
        self.d.sleep(self.s.wait(name))

    @staticmethod
    def _panel_box(frame: np.ndarray) -> tuple[int, int, int, int]:
        """Rough detail-panel rect, good enough for a stability check."""
        h, w = frame.shape[:2]
        return int(w * 0.66), int(h * 0.08), int(w * 0.98), int(h * 0.95)

    def _settled_frame(self) -> np.ndarray:
        """Grab until the detail panel stops changing.

        Genshin cross-fades the panel when a different artifact is selected, so
        a fixed delay is always either too short (a half-drawn panel is OCR'd
        as garbage) or wastefully long. Comparing consecutive frames adapts to
        whatever the machine and the game are actually doing.
        """
        x0, y0, x1, y1 = 0, 0, 0, 0
        budget = max(0.15, self.s.wait("panel_open"))
        step = max(0.02, self.s.wait("settle") / 3.0)
        prev = self.d.grab()
        x0, y0, x1, y1 = self._panel_box(prev)
        waited = 0.0
        while waited < budget:
            self.d.sleep(step)
            waited += step
            cur = self.d.grab()
            a = prev[y0:y1, x0:x1].astype(np.int16)
            b = cur[y0:y1, x0:x1].astype(np.int16)
            if a.shape == b.shape and float(np.abs(a - b).mean()) < 1.2:
                return cur
            prev = cur
        return prev

    # What kind of item this scanner reads; overridden by subclasses.
    item_label = "artifact"

    def _parse_frame(self, frame: np.ndarray):
        """Return (item, problems) for the currently selected item."""
        panel = read_panel(frame)
        parsed = build_artifact(panel, min_score=self.s.min_match_score,
                                traveler_name=self.s.traveler_name,
                                wanderer_name=self.s.wanderer_name,
                                other_names=self.s.other_names)
        return parsed.artifact, parsed.problems

    def _ai_read(self, entries: list[tuple[str, np.ndarray, Tile]]):
        """Read one batch of panels -> [(item, problems)] per entry.

        Subclasses override this: weapons build from WeaponPanelText,
        materials from (name, count) via the vocabulary.
        """
        from ..ai.reader import read_artifacts

        # Same build_artifact validation as `_parse_frame`, fed with the
        # model's PanelText instead of Tesseract's; pixel facts (rarity,
        # locked, elixir) were already filled in by the reader.
        panels = read_artifacts(self._gemini, [frame for _, frame, _ in entries])
        out = []
        for panel in panels:
            if panel is None:
                out.append((None, ["the panel could not be segmented"]))
                continue
            parsed = build_artifact(panel, min_score=self.s.min_match_score,
                                    traveler_name=self.s.traveler_name,
                                    wanderer_name=self.s.wanderer_name,
                                    other_names=self.s.other_names)
            out.append((parsed.artifact, parsed.problems))
        return out

    def _attempt(self, result: ScanResult):
        """One read of the currently selected item."""
        frame = self._settled_frame()
        try:
            item, problems = self._parse_frame(frame)
        except LayoutError as exc:
            return None, [str(exc)], frame
        return item, problems, frame

    def _rarity_floor(self) -> int:
        return self.s.min_artifact_rarity

    def _read_one(self, tile: Tile, result: ScanResult) -> None:
        if self.s.reader_mode == "ai":
            self._ai_read_one(tile, result)
            return
        x, y = tile.center
        self.d.click(x, y)
        self._wait("after_click")

        artifact, problems, frame = self._attempt(result)
        if artifact is None:
            # Retry once, more patiently. Most first-pass failures are a panel
            # that had not finished drawing, and a second look costs far less
            # than dropping the artifact.
            result.stats.retried += 1
            self.d.sleep(self.s.wait("panel_open"))
            artifact, problems, frame = self._attempt(result)

        if artifact is not None:
            result.items.append(artifact)
            result.stats.kept += 1
            return

        result.stats.failed += 1
        where = f"tile r{tile.row}c{tile.col}"
        result.problems.append(f"{where}: " + "; ".join(problems))
        self._save_failure(where, frame, problems)

    # -- AI reader mode ---------------------------------------------------

    def _ai_read_one(self, tile: Tile, result: ScanResult) -> None:
        """Click and grab the panel, then defer the read to the next batch.

        No OCR and no retry here: the text is read by Gemini in `_flush`, and
        a misread that slips through is still refused by `build_*`, which this
        scanner's local path also runs.
        """
        x, y = tile.center
        self.d.click(x, y)
        self._wait("after_click")
        frame = self._settled_frame()
        where = f"tile r{tile.row}c{tile.col}"
        self._pending.append((where, frame, tile))
        if len(self._pending) >= self.s.ai_batch_size:
            self._flush(result)
        else:
            self._ai_pipe.harvest()

    def _flush(self, result: ScanResult) -> None:
        """Send the pending panels to Gemini in the background."""
        pending, self._pending = self._pending, []
        if not pending:
            return
        self.log(f"  reading {len(pending)} panels with Gemini...")
        self._ai_pipe.submit(
            lambda: self._ai_read(pending),
            lambda outcomes, exc: self._settle_batch(result, pending, outcomes, exc))

    def _settle_batch(self, result: ScanResult, pending, outcomes,
                      exc: BaseException | None) -> None:
        """Account for one answered batch (runs on the scan thread).

        A hard auth/model error aborts the scan. A quota or other Gemini
        error marks the batch's items failed (with a failure dump), then
        stops the scan: thousands of dumps would otherwise follow one 429.
        Anything else is a bug and is raised, as it was before batching.
        """
        if (exc is not None and not isinstance(exc, GeminiError)) \
                or isinstance(exc, (GeminiAuthError, GeminiModelError)):
            self._ai_abort = True
            self._ai_pipe.cancel()
            raise exc
        if exc is not None:
            self._ai_abort = True
            self.log(f"  Gemini error: {exc}")
            for where, frame, _tile in pending:
                result.stats.failed += 1
                result.problems.append(f"{where}: {exc}")
                self._save_failure(where, frame, [str(exc)])
            return
        for (where, frame, _tile), (item, problems) in zip(pending, outcomes):
            if item is None:
                result.stats.failed += 1
                result.problems.append(f"{where}: " + "; ".join(problems))
                self._save_failure(where, frame, problems)
            else:
                result.items.append(item)
                result.stats.kept += 1

    def _save_scroll_stall(self, before: np.ndarray, after: np.ndarray,
                           moved: int, target: int) -> None:
        """Keep the frames around a scroll that barely moved.

        A short scroll is either the real bottom of the list or the list
        refusing to move, and only the frames can tell those apart. Capped
        per scan: the genuine end of every list produces one too.
        """
        if self.failure_dir is None or self._stall_dumps >= 3:
            return
        self._stall_dumps += 1
        try:
            from PIL import Image

            stamp = _next_failure_stamp(self)
            for tag, frame in (("before", before), ("after", after)):
                Image.fromarray(frame[:, :, ::-1]).save(
                    self.failure_dir / f"fail_{stamp}_scroll_{tag}.png")
            with (self.failure_dir / "failures.txt").open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp} scroll: moved {moved}px of {target}px requested "
                         f"(frames saved)\n")
        except Exception:
            pass  # diagnostics must never break a scan

    def _save_failure(self, where: str, frame: np.ndarray, problems: list[str]) -> None:
        """Write the offending frame out so a failure can be diagnosed later."""
        if self.failure_dir is None:
            return
        try:
            from PIL import Image

            stamp = _next_failure_stamp(self)
            Image.fromarray(frame[:, :, ::-1]).save(
                self.failure_dir / f"fail_{stamp}_{where.replace(' ', '_')}.png"
            )
            with (self.failure_dir / "failures.txt").open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp} {where}: {'; '.join(problems)}\n")
        except Exception:
            pass  # diagnostics must never break a scan

    # -- main loop -------------------------------------------------------

    def scan(self) -> ScanResult:
        result = ScanResult()
        st = result.stats

        frame = self.d.grab()
        label, st.total_expected = read_inventory_header(frame, self._read_text)
        # Materials tabs report "Inventory capacity N/M", which names no
        # category; goto_tab has already confirmed the tab by its title.
        if self.item_label != "material" and label and self.item_label not in label:
            self.log(f"error: the {label or 'current'} tab is open, but this is the "
                     f"{self.item_label} scan. Open the {self.item_label} tab first.")
            return result
        if self.item_label == "material":
            st.total_expected = None      # the capacity figure is not a count
        if st.total_expected:
            self.log(f"Inventory reports {st.total_expected} {self.item_label}s")
        else:
            self.log(f"Could not read the {self.item_label} count; "
                     "will scan until the end")

        # Rows are tracked by their position in the *whole list*, not by how
        # they look. A partial scroll changes a row's pixel offset and its
        # detected rect, so an appearance-based key makes an already-scanned
        # row look new; an absolute key does not.
        # Position is the ONLY identity used. An appearance fingerprint was
        # tried as a second guard and had to go: rows of freshly farmed
        # artifacts are routinely identical, so it discarded real rows as
        # already-seen.
        #
        # Positions are kept as absolute pixel coordinates and compared with a
        # tolerance, rather than snapped to a pitch lattice. Detected row tops
        # jitter by a few pixels, and rounding onto a lattice lets one row take
        # a neighbour's slot -- which showed up as both skipped and re-scanned
        # rows.
        offset = 0
        scanned_abs: list[int] = []

        def is_new(abs_y: int, tol: float) -> bool:
            i = bisect.bisect_left(scanned_abs, abs_y)
            for j in (i - 1, i):
                if 0 <= j < len(scanned_abs) and abs(scanned_abs[j] - abs_y) <= tol:
                    return False
            return True
        px_per_click: float | None = None
        stalls = 0

        while not self.should_stop() and not getattr(self, "_ai_abort", False):
            try:
                grid = find_grid(frame)
            except (GridError, LayoutError) as exc:
                result.problems.append(f"grid: {exc}")
                self.log(f"error: {exc}")
                break

            pitch = grid.pitch_y or 1
            by_row: dict[int, list[Tile]] = {}
            for t in grid.tiles:
                by_row.setdefault(t.row, []).append(t)

            tol = pitch * 0.5
            all_keys = []
            fresh: list[tuple[int, list[Tile]]] = []
            taken: list[int] = []
            for ri, tiles in sorted(by_row.items()):
                abs_y = tiles[0].rect.y0 + offset
                all_keys.append((round(abs_y / pitch), tiles[0].rect.y0))
                if not is_new(abs_y, tol):
                    continue
                # Guard against two detected rows collapsing onto one another
                # within a single page.
                if any(abs(t - abs_y) <= tol for t in taken):
                    continue
                taken.append(abs_y)
                fresh.append((abs_y, tiles))

            self._dbg(f"offset={offset} rows_detected={all_keys} "
                      f"fresh={[round(a / pitch) for a, _ in fresh]}")
            if not fresh:
                stalls += 1
                if stalls >= 2:
                    if st.total_expected and st.seen < st.total_expected:
                        # The game's own count says there is more. Calling this
                        # "the end" hid a scan that stopped at 160 of 380.
                        msg = (f"The list stopped scrolling after {st.seen} of the "
                               f"{st.total_expected} {self.item_label}s the game "
                               f"reports; anything after that was not scanned")
                        self.log(msg)
                        result.problems.append(msg)
                    else:
                        self.log("Reached the end of the inventory")
                    break
            else:
                stalls = 0
                st.pages += 1

            for abs_y, tiles in fresh:
                if self.should_stop() or getattr(self, "_ai_abort", False):
                    break
                bisect.insort(scanned_abs, abs_y)
                key = round(abs_y / pitch)
                for tile in tiles:
                    if self.should_stop() or getattr(self, "_ai_abort", False):
                        break
                    st.seen += 1
                    if tile.rarity and tile.rarity < self._rarity_floor():
                        st.skipped_rarity += 1
                        continue
                    self._read_one(tile, result)
                self.log(
                    f"  row {key}: kept {st.kept}, skipped {st.skipped_rarity}, "
                    f"failed {st.failed}"
                )

            if st.total_expected and st.seen >= st.total_expected:
                # Count every tile visited, not just the successful ones: the
                # Weapons tab continues into enhancement-ore stacks once the
                # weapons run out, and an unreadable weapon would otherwise
                # push the scan into them.
                self.log(f"Reached the reported {st.total_expected} "
                         f"{self.item_label}s")
                break

            # Advance by the rows just done, keeping one row of overlap so a
            # short scroll can never step over an unscanned row.
            rows_to_advance = max(1, len(fresh) - 1) if fresh else 1
            target_px = rows_to_advance * pitch
            # Never advance more than the shift measurement can resolve. It
            # needs meaningful overlap between the two frames, so cap the step
            # at half the scrolling region; beyond that the offset silently
            # drifts and rows get stepped over.
            scroll_h = max(1, grid.region.y1 - grid.region.y0)
            target_px = min(target_px, max(pitch, scroll_h // 2))
            gx0, gx1 = grid.region.x0, grid.region.x1
            # Only the tile area scrolls; the header above it is static.
            gy0, gy1 = scroll_viewport(grid, frame.shape[0])

            if px_per_click is None:
                # Calibrate once: one click, then measure what it actually did.
                self.d.scroll(1)
                self._wait("page_scroll")
                after = self.d.grab()
                moved = measure_scroll_shift(frame, after, gx0, gx1,
                                             gy0, gy1, pitch * 3)
                if moved >= 2:
                    px_per_click = float(moved)
                    self.log(f"  one wheel click scrolls ~{moved}px "
                             f"(row pitch {pitch}px)")
                else:
                    px_per_click = float(pitch)  # cannot tell; assume a row
                    self.log("  could not measure scroll distance; assuming one "
                             "row per click")
                offset += moved
                frame = after
                continue

            clicks = max(1, min(60, round(target_px / max(1.0, px_per_click))))
            before = frame
            self.d.scroll(clicks)
            self._wait("page_scroll")
            frame = self.d.grab()
            moved = measure_scroll_shift(before, frame, gx0, gx1, gy0, gy1,
                                         int(target_px * 1.6) + pitch)
            offset += moved
            self._dbg(f"requested {target_px}px via {clicks} clicks -> moved {moved}px")
            if moved < target_px * 0.5:
                self._save_scroll_stall(before, frame, moved, target_px)
                # The wheel acts on whatever is under the cursor, which is
                # wherever the last tile click left it. Park it over the middle
                # of the grid and try once more before believing the list ended.
                hover = getattr(self.d, "hover", None)
                if hover is not None and (not st.total_expected
                                          or st.seen < st.total_expected):
                    hover((gx0 + gx1) // 2, (grid.region.y0 + grid.region.y1) // 2)
                    self._wait("after_click")
                    retry_from = frame
                    self.d.scroll(clicks)
                    self._wait("page_scroll")
                    frame = self.d.grab()
                    again = measure_scroll_shift(retry_from, frame, gx0, gx1, gy0, gy1,
                                                 int(target_px * 1.6) + pitch)
                    self.log(f"  short scroll ({moved}px of {target_px}px); retried with "
                             f"the cursor over the grid: moved {again}px")
                    offset += again
                    moved += again
                    if again < target_px * 0.5:
                        self._save_scroll_stall(retry_from, frame, again, target_px)
            if moved < 2:
                stalls += 1
                self.log("  the list did not move")
            elif moved < target_px * 0.5:
                # Hit the bottom, or the wheel is being throttled.
                self.log(f"  scrolled {moved}px of {target_px}px requested")

        if self.s.reader_mode == "ai":
            self._flush(result)
            self._ai_pipe.drain()
        self.log(
            f"Done: {st.kept} kept, {st.skipped_rarity} below rarity floor, "
            f"{st.failed} unreadable ({st.retried} retried), {st.pages} pages"
        )
        if self.s.reader_mode == "ai":
            self.log(f"Gemini requests this scan: {self._gemini.requests_made} "
                     f"(today: {self._gemini.usage.today()})")
        return result


class WeaponScanner(ArtifactScanner):
    """Same grid navigation, different detail panel."""

    item_label = "weapon"

    def _rarity_floor(self) -> int:
        return self.s.min_weapon_rarity

    def _parse_frame(self, frame: np.ndarray):
        from .weapon_parse import build_weapon
        from .weapons import read_weapon_panel

        panel = read_weapon_panel(frame)
        return build_weapon(panel, min_score=self.s.min_match_score,
                            traveler_name=self.s.traveler_name,
                            wanderer_name=self.s.wanderer_name,
                            other_names=self.s.other_names)

    def _ai_read(self, entries: list[tuple[str, np.ndarray, Tile]]):
        from ..ai.reader import read_weapons
        from .weapon_parse import build_weapon

        panels = read_weapons(self._gemini, [frame for _, frame, _ in entries])
        out = []
        for panel in panels:
            if panel is None:
                out.append((None, ["the panel could not be segmented"]))
                continue
            item, problems = build_weapon(
                panel, min_score=self.s.min_match_score,
                traveler_name=self.s.traveler_name,
                wanderer_name=self.s.wanderer_name,
                other_names=self.s.other_names)
            out.append((item, problems))
        return out


class MaterialScanner(ArtifactScanner):
    """Materials: the count comes from the tile, the name from the panel."""

    item_label = "material"

    def _rarity_floor(self) -> int:
        return 1          # materials have no user-facing rarity filter

    def _read_one(self, tile: Tile, result: ScanResult) -> None:
        if self.s.reader_mode == "ai":
            self._ai_read_one(tile, result)
            return
        from ..ocr import match as vocab
        from .materials import read_material_name, read_quantity

        x, y = tile.center
        self.d.click(x, y)
        self._wait("after_click")
        frame = self._settled_frame()

        where = f"tile r{tile.row}c{tile.col}"
        try:
            qty = read_quantity(frame, tile, self._pitch_y or 350)
            name = read_material_name(frame)
        except LayoutError as exc:
            result.stats.failed += 1
            result.problems.append(f"{where}: {exc}")
            return

        m = vocab.materials().match(name, floor=self.s.min_match_score)
        if qty is None or not m.ok:
            # One patient retry, as for artifacts: most first-pass misses are a
            # panel or tile caught mid-redraw.
            result.stats.retried += 1
            self.d.sleep(self.s.wait("panel_open"))
            frame = self._settled_frame()
            try:
                qty = read_quantity(frame, tile, self._pitch_y or 350)
                name = read_material_name(frame)
                m = vocab.materials().match(name, floor=self.s.min_match_score)
            except LayoutError:
                pass

        problems = []
        if not m.ok:
            problems.append(f"material {name!r} matched {m.key or '—'} at {m.score:.0f}")
        if qty is None:
            problems.append("unreadable quantity")
        if problems:
            result.stats.failed += 1
            result.problems.append(f"{where}: " + "; ".join(problems))
            self._save_failure(where, frame, problems)
            return

        result.items.append((m.key, qty))
        result.stats.kept += 1

    def _ai_read(self, entries: list[tuple[str, np.ndarray, Tile]]):
        from ..ai.reader import read_materials
        from ..ocr import match as vocab

        # Same vocabulary check the local path runs, only upstream the
        # (name, count) came from Gemini instead of Tesseract.
        pitch = self._pitch_y or 350
        got = read_materials(self._gemini, [(frame, tile, pitch)
                                            for _, frame, tile in entries])
        out = []
        for entry in got:
            if entry is None:
                out.append((None, ["the panel could not be segmented"]))
                continue
            name, qty = entry
            m = vocab.materials().match(name, floor=self.s.min_match_score)
            problems = []
            if not m.ok:
                problems.append(
                    f"material {name!r} matched {m.key or '—'} at {m.score:.0f}")
            if qty is None:
                problems.append("unreadable quantity")
            if problems:
                out.append((None, problems))
            else:
                out.append(((m.key, qty), []))
        return out


CHAR_LIMIT = 200        # safety stop; the roster is walked until it wraps


def _ai_attributes_ok(frame) -> bool:
    """Pixel-only stand-in for the local \"level parses\" capture check.

    AI mode never runs Tesseract, but the Attributes-page check still has to
    keep a frame caught mid-drift out of the batch; \"bright ink in the level
    region\" is enough to ask Gemini.
    """
    from .characters import R_LEVEL, _region

    crop = _region(frame, R_LEVEL).crop(frame)
    if crop.size == 0:
        return False
    return bool((crop.min(2) >= 150).mean() > 0.003)


def _ai_talents_row_count(frame) -> int:
    """How many bright level-row bands the Talents screen shows (pixel-only)."""
    from .characters import R_TALENTS, _region

    crop = _region(frame, R_TALENTS).crop(frame)
    if crop.size == 0:
        return 0
    ink = crop[:, :, ::-1].astype(int).min(2) >= 190
    h, w = ink.shape
    level_col = np.zeros_like(ink)
    level_col[:, int(w * 0.70): int(w * 0.92)] = True
    ink &= level_col
    rows = ink.sum(1) > 4
    bands = 0
    prev = False
    for on in rows:
        if on and not prev:
            bands += 1
        prev = on
    return bands


class CharacterScanner:
    """Walk the character screen (C).

    Not a grid: characters are pages reached with Q/E, and the fields live on
    three sub-screens selected from the left menu, so this does not share the
    inventory scan loop. The roster has no visible count, so the walk stops
    when a name repeats.
    """

    item_label = "character"

    def __init__(self, driver, settings: Settings,
                 log: Callable[[str], None] = print,
                 should_stop: Callable[[], bool] = lambda: False,
                 tap: Callable[[str], None] | None = None,
                 failure_dir=None) -> None:
        self.d = driver
        self.s = settings
        self.log = log
        self.should_stop = should_stop
        self.tap = tap or (lambda _k: None)
        self.failure_dir = failure_dir
        self._fail_seq = 0
        # Pages whose capture was rejected, kept so the failure dump can show
        # what the scanner actually saw instead of omitting the page entirely.
        self._rejected: dict[str, np.ndarray] = {}

        # AI reader mode: text goes to Gemini in batches, the name-repeat
        # roster-wrap is detected by a pixel fingerprint (see scan()).
        if self.s.reader_mode == "ai":
            from ..ai.gemini import Gemini, Usage

            if not self.s.gemini_key():
                raise RuntimeError("AI reader selected but no Gemini API key is set")
            self._gemini = Gemini(self.s.gemini_key(), self.s.gemini_model,
                                  log=self.log, usage=Usage())
            self._pending: list[tuple[str, dict[str, np.ndarray]]] = []
            self._ai_abort = False
            self._ai_pipe = _AiPipeline(self.s.ai_in_flight)

    def _save_failure(self, where: str, frames: dict[str, np.ndarray],
                      problems: list[str]) -> None:
        """Write the offending frames out so a failure can be diagnosed later.

        Mirrors ArtifactScanner._save_failure. Characters have up to three
        frames (attributes/constellation/talents); each captured one is saved
        so a misread on any of them can be inspected without asking for a
        fresh screenshot.
        """
        if self.failure_dir is None:
            return
        try:
            from PIL import Image

            stamp = _next_failure_stamp(self)
            for page, frame in frames.items():
                Image.fromarray(frame[:, :, ::-1]).save(
                    self.failure_dir /
                    f"fail_{stamp}_{where.replace(' ', '_')}_{page}.png")
            with (self.failure_dir / "failures.txt").open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp} {where}: {'; '.join(problems)}\n")
        except Exception:
            pass  # diagnostics must never break a scan

    # -- AI reader mode ---------------------------------------------------

    @staticmethod
    def _name_fingerprint(frame: np.ndarray) -> np.ndarray | None:
        """Ink mask of the Attributes name region, for roster-wrap detection.

        The local scan stops when a name repeats; in AI mode the name cannot
        be read synchronously (it is read by Gemini in a batch), so the wrap
        is detected from the pixels instead. The name is white ink on a
        drifting background, so the mask of bright pixels is what is stable
        between two visits to the same character; it is pooled to a small
        grid and compared with a tolerance by `_same_name` rather than hashed
        exactly, so neither a flickering pixel nor a quantisation boundary
        can split or merge two visits.
        """
        from .characters import R_NAME, _region

        crop = _region(frame, R_NAME).crop(frame)
        if crop.size == 0:
            return None
        ink = (crop.min(2) >= 190).astype(np.float32)
        if ink.sum() < 20:
            return None
        rows, cols = 12, 48
        h, w = ink.shape
        ys = np.linspace(0, h, rows + 1).astype(int)
        xs = np.linspace(0, w, cols + 1).astype(int)
        small = np.zeros((rows, cols), np.float32)
        for i in range(rows):
            for j in range(cols):
                cell = ink[ys[i]:max(ys[i + 1], ys[i] + 1),
                           xs[j]:max(xs[j + 1], xs[j] + 1)]
                small[i, j] = cell.mean()
        return small

    @staticmethod
    def _same_name(a: np.ndarray, b: np.ndarray) -> bool:
        """Two name fingerprints that differ by less than a few per cent of
        the grid are the same character seen twice."""
        return bool(np.abs(a - b).mean() < 0.04)

    def _ai_flush(self, result: ScanResult) -> None:
        """Send the pending characters to Gemini in the background.

        Constellation comes from the pixel reader inside `read_characters`.
        """
        from ..ai.reader import read_characters

        pending, self._pending = self._pending, []
        if not pending:
            return
        self.log(f"  reading {len(pending)} characters with Gemini...")
        self._ai_pipe.submit(
            lambda: read_characters(self._gemini, [pages for _, pages in pending]),
            lambda panels, exc: self._ai_settle(result, pending, panels, exc))

    def _ai_settle(self, result: ScanResult, pending, panels,
                   exc: BaseException | None) -> None:
        """Account for one answered batch of characters (scan thread).

        build_character validation is unchanged. Hard auth/model errors abort
        the scan; a quota or other Gemini error fails the whole batch and
        stops the scan rather than dumping one frame per remaining character.
        """
        from .character_parse import build_character

        if (exc is not None and not isinstance(exc, GeminiError)) \
                or isinstance(exc, (GeminiAuthError, GeminiModelError)):
            self._ai_abort = True
            self._ai_pipe.cancel()
            raise exc
        if exc is not None:
            self._ai_abort = True
            self.log(f"  Gemini error: {exc}")
            for where, pages in pending:
                result.stats.failed += 1
                result.problems.append(f"{where}: {exc}")
                self._save_failure(where, pages, [str(exc)])
            return
        for (where, pages), panel in zip(pending, panels):
            label = panel.name or where if panel is not None else where
            if panel is None:
                result.stats.failed += 1
                result.problems.append(f"{where}: the Attributes page could "
                                       f"not be captured")
                self._save_failure(where, pages,
                                   ["the Attributes page could not be captured"])
                continue
            char, notes = build_character(
                panel, min_score=self.s.min_match_score,
                traveler_name=self.s.traveler_name,
                wanderer_name=self.s.wanderer_name,
                other_names=self.s.other_names)
            if char is None:
                result.stats.failed += 1
                result.problems.append(f"{label}: " + "; ".join(notes))
                self.log(f"  {label}: unreadable ({notes[0] if notes else '?'})")
                self._save_failure(label, pages, notes)
            else:
                result.items.append(char)
                result.stats.kept += 1
                extra = f"  [{notes[0]}]" if notes else ""
                self.log(f"  {char.key}: Lv{char.level} C{char.constellation} "
                         f"talents {char.talent['auto']}/{char.talent['skill']}/"
                         f"{char.talent['burst']}{extra}")
                if notes:
                    result.problems.extend(f"{char.key}: {n}" for n in notes)

    def _goto_page(self, item: str) -> bool:
        """Select a left-menu page with W/S rather than clicking it."""
        from .characters import select_menu

        return select_menu(
            item, tap=self.tap, grab=self.d.grab, sleep=self.d.sleep,
            log=self.log, key_up=self.s.key_menu_up,
            key_down=self.s.key_menu_down,
            step_delay=max(0.12, self.s.wait("after_key")),
            should_stop=self.should_stop)

    def _settled(self) -> np.ndarray:
        budget = max(0.15, self.s.wait("panel_open"))
        step = max(0.02, self.s.wait("settle") / 3.0)
        prev = self.d.grab()
        waited = 0.0
        while waited < budget:
            self.d.sleep(step)
            waited += step
            cur = self.d.grab()
            a, b = prev.astype(np.int16), cur.astype(np.int16)
            if a.shape == b.shape and float(np.abs(a - b).mean()) < 1.2:
                return cur
            prev = cur
        return prev

    def _capture_page(self, page: str, is_good
                      ) -> tuple[np.ndarray | None, bool]:
        """Grab `page`, confirming the frame really is that page, or give up.

        Two different things go wrong here and both look the same downstream.

        The background keeps drifting slowly even once the panel itself has
        stopped animating -- `_settled` only waits out the latter -- so every
        so often a bright patch sits behind a stat at the exact moment of
        capture and wipes out the contrast OCR needs. Retrying doesn't fix a
        bad threshold; it waits for the drift to move the patch elsewhere, the
        same bet the artifact/material scanners make on a redraw.

        The navigation can also land somewhere else entirely. `select_menu`
        confirms each press by re-reading the menu, but a capture backend that
        hands back the previous frame makes it press again and overshoot, and
        a real run captured the Attributes screen while asking for Talents.
        Checking the menu highlight on the captured frame is what makes that
        recoverable -- and, more importantly, keeps a wrong page out of
        `frames` entirely: nothing else downstream would notice, and
        `read_constellation` would happily count zero unlocked nodes on the
        Talents screen and export the character as C0.

        Returns `(None, True)` if the page could not be reached, and whether
        anything had to be re-captured.
        """
        from .characters import selected_menu_item

        frame = self._settled()
        retried = False
        for _ in range(2):
            on_page = selected_menu_item(frame) == page
            if on_page and is_good(frame):
                return frame, retried
            retried = True
            if not on_page and not self._goto_page(page):
                self._rejected[page] = frame
                return None, retried
            self.d.sleep(self.s.wait("panel_open"))
            frame = self._settled()
        if selected_menu_item(frame) == page:
            return frame, retried
        # Keep it anyway. Discarding the frame is what made the last round of
        # "the Constellation page could not be captured" undiagnosable: the
        # failure dump held every page *except* the one that went wrong.
        self._rejected[page] = frame
        return None, retried

    def scan(self) -> ScanResult:
        from .character_parse import CharacterPanelText, build_character
        from .characters import (read_constellation, read_description,
                                 read_element, read_level, read_name,
                                 read_talents)

        result = ScanResult()
        st = result.stats
        seen: list[str] = []
        seen_fp: list[np.ndarray] = []
        # The left-menu selection survives the Q/E character switch, so the
        # pages are walked down for one character and back up for the next
        # instead of returning to Attributes every time.
        pages = ("attributes", "constellation", "talents")
        # What a good capture of each page looks like. The Constellation page
        # has no text to read back, so being on the page is the whole check.
        from .character_parse import parse_level
        if self.s.reader_mode == "ai":
            # AI mode never calls Tesseract, so the "is this page good"
            # checks are pixel-only presence tests: bright ink in the level
            # region, and at least three bright level rows on the Talents
            # screen.
            checks = {
                "attributes": lambda f: _ai_attributes_ok(f),
                "constellation": lambda f: True,
                "talents": lambda f: _ai_talents_row_count(f) >= 3,
            }
        else:
            checks = {
                # The level has to *parse*, not merely be non-empty: a frame caught
                # mid-drift returns confident gibberish ("| @ero0790"), which a
                # non-empty test accepts and no retry ever corrects.
                "attributes": lambda f: bool(read_name(f)) and parse_level(
                    read_level(f)) is not None,
                "constellation": lambda f: True,
                "talents": lambda f: len(read_talents(f)) == 3,
            }
        forward = True

        for first in range(CHAR_LIMIT):
            if self.should_stop():
                break
            if self.s.reader_mode == "ai" and self._ai_abort:
                break

            frames: dict[str, np.ndarray] = {}
            self._rejected = {}
            order = pages if forward else pages[::-1]
            for page in order:
                if not self._goto_page(page):
                    break
                frame, retried = self._capture_page(page, checks[page])
                if retried:
                    st.retried += 1
                if frame is None:
                    break
                frames[page] = frame
            forward = not forward
            if "attributes" not in frames:
                if first == 0:
                    self.log("error: the character screen does not look open "
                             f"(press '{self.s.key_character}' first)")
                break

            if self.s.reader_mode == "ai":
                # The roster wrap is detected by a pixel fingerprint of the
                # name region -- the only "name" fact available before the
                # batch is sent to Gemini.
                fp = self._name_fingerprint(frames["attributes"])
                if fp is None:
                    self.log("error: the character screen does not look open "
                             f"(press '{self.s.key_character}' first)")
                    break
                if any(self._same_name(fp, old) for old in seen_fp):
                    self.log("Wrapped around to the first character; "
                             "all characters scanned.")
                    break
                seen_fp.append(fp)
            else:
                name = read_name(frames["attributes"])
                if not name:
                    self.log("error: the character screen does not look open "
                             f"(press '{self.s.key_character}' first)")
                    break
                if name in seen:
                    self.log(f"Wrapped around to {name}; all characters scanned.")
                    break
                seen.append(name)
            st.seen += 1

            if self.s.reader_mode == "ai":
                # The text is read in a batch; only the frames are collected
                # here. Constellation is counted from the Constellation page
                # inside the reader, never by the model.
                where = f"character {st.seen}"
                self._pending.append((where, dict(frames)))
                if len(self._pending) >= self.s.ai_batch_size:
                    self._ai_flush(result)
                else:
                    self._ai_pipe.harvest()
            else:
                level = read_level(frames["attributes"])
                element = read_element(frames["attributes"])
                description = read_description(frames["attributes"])
                constellation = (read_constellation(frames["constellation"])
                                 if "constellation" in frames else None)
                tal = read_talents(frames["talents"]) if "talents" in frames else []
                slots = ("auto", "skill", "burst")
                talents = {slot: str(lvl) for slot, (lvl, _boosted) in zip(slots, tal)}
                talent_boosted = {slot: boosted
                                 for slot, (_lvl, boosted) in zip(slots, tal)}

                panel = CharacterPanelText(name=name, level=level,
                                           constellation=constellation,
                                           talents=talents,
                                           talent_boosted=talent_boosted,
                                           element=element,
                                           description=description)
                char, notes = build_character(panel,
                                              min_score=self.s.min_match_score,
                                              traveler_name=self.s.traveler_name,
                                              wanderer_name=self.s.wanderer_name,
                                              other_names=self.s.other_names)
                crashes = ocr.take_crashes()
                if crashes:
                    # Say so explicitly. Left to speak for itself this arrives as
                    # an ordinary empty read, and the user goes looking for a
                    # threshold to tune that was never involved.
                    st.ocr_crashes += len(crashes)
                    notes = list(notes) + [f"Tesseract failed on this character's "
                                           f"images ({crashes[0]})"]
                    self.log(f"  note: Tesseract crashed reading {name} "
                             f"({crashes[0]}); continuing")
                if char is None:
                    st.failed += 1
                    result.problems.append(f"{name}: " + "; ".join(notes))
                    self.log(f"  {name}: unreadable ({notes[0] if notes else '?'})")
                    self._save_failure(
                        name,
                        {**frames,
                         **{f"{k}_rejected": v for k, v in self._rejected.items()}},
                        notes)
                else:
                    result.items.append(char)
                    st.kept += 1
                    extra = f"  [{notes[0]}]" if notes else ""
                    self.log(f"  {char.key}: Lv{char.level} C{char.constellation} "
                             f"talents {char.talent['auto']}/{char.talent['skill']}/"
                             f"{char.talent['burst']}{extra}")
                    if notes:
                        result.problems.extend(f"{char.key}: {n}" for n in notes)

            self.tap(self.s.key_tab_right)
            self.d.sleep(self.s.wait("page_scroll"))

        if self.s.reader_mode == "ai":
            self._ai_flush(result)
            self._ai_pipe.drain()
        crashed = (f", {st.ocr_crashes} OCR crashes survived"
                   if st.ocr_crashes else "")
        self.log(f"Done: {st.kept} characters, {st.failed} unreadable "
                f"({st.retried} pages re-captured for a bad background"
                f"{crashed})")
        if self.s.reader_mode == "ai":
            self.log(f"Gemini requests this scan: {self._gemini.requests_made} "
                     f"(today: {self._gemini.usage.today()})")
        return result
