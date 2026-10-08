"""The inventory scan loop's handling of a list that stops scrolling.

A real artifact scan stopped at 160 of 380 artifacts: the wheel moved the list
10px of a requested 350px twice, and the loop announced "Reached the end of
the inventory". These tests drive `ArtifactScanner.scan` with a scripted
scroll distance -- no screenshots, no game -- to pin down what happens now:
the frames around a short scroll are saved, the cursor is parked over the grid
and the scroll retried, and a stop before the game's own count is reported as
an incomplete scan instead of the end of the list.
"""

from __future__ import annotations

import numpy as np

import lumenspar.scan.scanner as scn
from lumenspar.config import Settings
from lumenspar.scan.grid import Grid, Tile
from lumenspar.scan.layout import Region
from lumenspar.scan.scanner import ArtifactScanner

PITCH = 50


class Driver:
    def __init__(self, hover: bool = True):
        self.frame = np.zeros((120, 200, 3), np.uint8)
        self.hovers: list[tuple[int, int]] = []
        if not hover:
            self.hover = None  # a driver that cannot move without clicking

    def grab(self):
        return self.frame

    def click(self, x, y):
        pass

    def scroll(self, clicks):
        pass

    def sleep(self, seconds):
        pass

    def hover(self, x, y):  # noqa: F811 -- replaced by None above when absent
        self.hovers.append((x, y))
        return True


def _scan(monkeypatch, tmp_path, distances, expected=8, hover=True):
    """Run a scan where each measured scroll returns the next of `distances`."""
    shifts = iter(distances)
    monkeypatch.setattr(scn, "measure_scroll_shift", lambda *a, **k: next(shifts, 0))
    monkeypatch.setattr(scn, "read_inventory_header",
                        lambda f, rt=None: ("artifacts", expected))
    tiles = [Tile(row=0, col=c, rect=Region(c * 50, 0, c * 50 + 40, 40), rarity=5)
             for c in range(2)]
    monkeypatch.setattr(scn, "find_grid", lambda f: Grid(
        tiles=tiles, cols=2, rows=1, pitch_x=50, pitch_y=PITCH,
        region=Region(0, 0, 100, 60)))
    # The scroll loop is the same in both reader modes; pin the local reader
    # so the test does not depend on the platform (Windows forces AI mode).
    from lumenspar import hostos
    monkeypatch.setattr(hostos, "is_windows", lambda: False)
    driver = Driver(hover=hover)
    logs: list[str] = []
    scanner = ArtifactScanner(driver, Settings(), log=logs.append,
                              failure_dir=tmp_path)
    scanner._settled_frame = lambda: driver.frame
    scanner._parse_frame = lambda f: (object(), [])
    return scanner.scan(), driver, logs


def test_a_list_that_keeps_moving_is_scanned_to_the_reported_count(monkeypatch, tmp_path):
    # calibration click, then one full row per scroll
    result, driver, logs = _scan(monkeypatch, tmp_path, [PITCH] * 10)
    assert result.stats.seen == 8
    assert not driver.hovers
    assert not list(tmp_path.glob("*scroll*"))
    assert any("Reached the reported 8" in l for l in logs)


def test_a_short_scroll_is_retried_with_the_cursor_over_the_grid(monkeypatch, tmp_path):
    # calibration, one good scroll, then a short one that the retry recovers
    result, driver, logs = _scan(monkeypatch, tmp_path, [PITCH, PITCH, 5, PITCH, PITCH])
    assert driver.hovers == [(50, 30)]           # middle of the grid region
    assert result.stats.seen == 8                 # the scan went on to the end
    assert any("retried with the cursor over the grid: moved 50px" in l for l in logs)
    assert len(list(tmp_path.glob("fail_*_scroll_before.png"))) == 1
    assert not result.problems


def test_a_list_that_stays_stuck_is_reported_incomplete(monkeypatch, tmp_path):
    result, driver, logs = _scan(monkeypatch, tmp_path, [PITCH, PITCH], expected=380)
    assert result.stats.seen < 380
    assert not any("Reached the end" in l for l in logs)
    assert any("stopped scrolling after" in p and "of the 380" in p
               for p in result.problems)
    assert driver.hovers                          # recovery was attempted
    # frames kept for diagnosis, capped at three pairs however long it stalls
    pairs = list(tmp_path.glob("fail_*_scroll_before.png"))
    assert 1 <= len(pairs) <= 3
    assert len(list(tmp_path.glob("fail_*_scroll_after.png"))) == len(pairs)
    assert "scroll: moved" in (tmp_path / "failures.txt").read_text()


def test_without_hover_support_the_scan_still_ends_cleanly(monkeypatch, tmp_path):
    result, driver, logs = _scan(monkeypatch, tmp_path, [PITCH, PITCH], expected=380,
                                 hover=False)
    assert any("stopped scrolling after" in p for p in result.problems)


def test_the_true_end_of_a_list_is_still_called_the_end(monkeypatch, tmp_path):
    # The game reports no count (or the count was not readable): a stall is
    # the only end signal, and the old wording stands.
    result, driver, logs = _scan(monkeypatch, tmp_path, [PITCH, PITCH], expected=0)
    assert any("Reached the end of the inventory" in l for l in logs)
    assert not result.problems


def _scrolled_pair(shift: int):
    """A periodic tile grid behind static bars, before and after a scroll.

    Mirrors the real failure: tiles repeat every PITCH rows, the top row is
    partly hidden under a static toggle bar, and the grid's detected region
    starts above that bar.
    """
    rng = np.random.default_rng(7)
    h, w, pitch = 1000, 600, 100
    long = np.zeros((h * 3, w, 3), np.uint8)
    for r in range(0, h * 3, pitch):              # one "row" of tiles
        long[r + 8:r + pitch - 8, :] = 170          # tile frame, same every row
        long[r + 20:r + 60, 40:560] = rng.integers(0, 255, (40, 520, 3))  # icons differ
    def view(top):
        f = long[top:top + h].copy()
        f[:150] = 60;  f[40:90, 100:500] = 230      # static toggle bar + its text
        f[885:] = 40;  f[920:960, 50:300] = 220     # static button bar
        return f
    return view(0), view(shift)


def test_scroll_is_measured_inside_the_viewport_only():
    from lumenspar.scan.scanner import measure_scroll_shift, scroll_viewport

    before, after = _scrolled_pair(shift=110)        # one row (100) plus 10px
    grid = Grid(tiles=[], cols=8, rows=5, pitch_x=60, pitch_y=100,
                region=Region(0, 110, 600, 880))       # starts behind the bar
    top, bottom = scroll_viewport(grid, before.shape[0])
    assert (top, bottom) == (152, 882)
    assert abs(measure_scroll_shift(before, after, 0, 600, top, bottom, 260) - 110) <= 2
    # The failure itself (old bounds measuring 10px for a 360px scroll) was
    # reproduced on the real saved frames, whose near-identical artifact rows
    # make the one-row alias almost as good a fit; synthetic rows are too
    # distinct to reproduce it, so only the corrected behaviour is pinned here.
