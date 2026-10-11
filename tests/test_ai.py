"""Tests for the AI reader mode (Gemini-backed panel text).

Everything here uses a fake transport -- there is no Gemini API key on this
machine and no test may attempt a real network call. The two things being
proven are that the request/body construction is exactly what Google's REST
API expects, and that model JSON flows through the same build_* validation as
OCR text, with the pixel-derived facts still coming from pixels.
"""

import base64
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from lumenspar.ai.gemini import (Gemini, GeminiAuthError, GeminiError,
                                 GeminiModelError, GeminiQuotaError, Usage)
from lumenspar.config import Settings
from lumenspar.scan.artifact_parse import build_artifact
from lumenspar.scan.character_parse import build_character
from lumenspar.scan.grid import Grid, Tile
from lumenspar.scan.layout import Region
from lumenspar.scan.scanner import ArtifactScanner, ScanResult
from lumenspar.scan.weapon_parse import build_weapon

KEY = "test-api-key"
MODEL = "gemini-3.5-flash-lite"


def _frame(w: int = 200, h: int = 120) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _ok_response(answer: object) -> bytes:
    return json.dumps({"candidates": [{"content": {
        "parts": [{"text": json.dumps(answer)}]}}]}).encode()


class RecordingTransport:
    """Returns canned responses and records every request it is handed."""

    def __init__(self, *responses: tuple[int, bytes]):
        self.responses = list(responses)
        self.requests: list[tuple[str, str, dict, bytes | None]] = []

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, dict(headers), body))
        code, raw = self.responses[0] if len(self.responses) == 1 else self.responses.pop(0)
        return code, raw


class FakeGemini:
    """Minimal Gemini stand-in for the reader mapping tests."""

    def __init__(self, answer: object):
        self.answer = answer
        self.prompt = None
        self.images: list[bytes] = []
        self.schema = None

    def generate_json(self, prompt, images, schema):
        self.prompt = prompt
        self.images = list(images)
        self.schema = schema
        return self.answer


# -- request building -------------------------------------------------------

def test_request_shape_headers_url_and_parts():
    tr = RecordingTransport((200, _ok_response([])))
    g = Gemini(KEY, MODEL, transport=tr)
    prompt = "transcribe"
    g.generate_json(prompt, [b"\x01\x02", b"\x03"], {"type": "ARRAY"})

    method, url, headers, body = tr.requests[0]
    assert method == "POST"
    assert headers["x-goog-api-key"] == KEY
    assert "api_key" not in url and KEY not in url
    assert url.startswith("https://generativelanguage.googleapis.com/v1beta/models/")
    assert MODEL in url

    payload = json.loads(body)
    parts = payload["contents"][0]["parts"]
    assert parts[0] == {"text": prompt}
    assert parts[1] == {"text": "Image 1"}
    assert parts[2]["inline_data"]["mime_type"] == "image/jpeg"
    assert base64.b64decode(parts[2]["inline_data"]["data"]) == b"\x01\x02"
    assert parts[3] == {"text": "Image 2"}
    assert base64.b64decode(parts[4]["inline_data"]["data"]) == b"\x03"
    cfg = payload["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseSchema"] == {"type": "ARRAY"}
    assert cfg["temperature"] == 0


def test_request_body_too_large_raises():
    big = b"\x00" * (20 * 1024 * 1024)
    g = Gemini(KEY, MODEL, transport=RecordingTransport((200, b"{}")))
    with pytest.raises(GeminiError):
        g.generate_json("x", [big], {"type": "ARRAY"})
    assert g.requests_made == 0


def test_check_get_model_resource():
    tr = RecordingTransport((200, json.dumps({"displayName": "Gemini Flash" }).encode()))
    g = Gemini(KEY, MODEL, transport=tr)
    assert g.check() == "Gemini Flash"
    method, url, headers, _ = tr.requests[0]
    assert method == "GET"
    assert headers["x-goog-api-key"] == KEY
    assert KEY not in url


# -- retries and error mapping ----------------------------------------------

def test_retry_429_then_success_with_backoff():
    sleeps: list[float] = []
    tr = RecordingTransport((429, b"rate"),
                            (200, _ok_response([1, 2])))
    g = Gemini(KEY, MODEL, transport=tr, sleep=sleeps.append,
               log=lambda m: None)
    assert g.generate_json("p", [b"img"], {"type": "ARRAY"}) == [1, 2]
    assert sleeps == [4.0]
    assert g.requests_made == 2          # the failed attempt counts too


def test_quota_error_after_exhausting_retries():
    sleeps: list[float] = []
    tr = RecordingTransport((429, b"rate"))
    g = Gemini(KEY, MODEL, transport=tr, sleep=sleeps.append)
    with pytest.raises(GeminiQuotaError):
        g.generate_json("p", [b"img"], {"type": "ARRAY"})
    assert sleeps == [4.0, 8.0, 16.0, 32.0]
    assert g.requests_made == 5


def test_auth_error_is_immediate_no_retry():
    sleeps: list[float] = []
    tr = RecordingTransport((403, b"denied"))
    g = Gemini(KEY, MODEL, transport=tr, sleep=sleeps.append)
    with pytest.raises(GeminiAuthError):
        g.generate_json("p", [b"img"], {"type": "ARRAY"})
    assert sleeps == []
    assert g.requests_made == 1


def test_model_error_on_404():
    g = Gemini(KEY, MODEL, transport=RecordingTransport((404, b"no model")))
    with pytest.raises(GeminiModelError):
        g.generate_json("p", [b"img"], {"type": "ARRAY"})


def test_malformed_json_raises_gemini_error():
    tr = RecordingTransport((200, b'{"candidates":[{"content":{"parts":'
                               b'[{"text":"not json"}]}}]}'))
    g = Gemini(KEY, MODEL, transport=tr)
    with pytest.raises(GeminiError) as exc:
        g.generate_json("p", [b"img"], {"type": "ARRAY"})
    assert "JSON" in str(exc.value)


def test_missing_candidates_raises_gemini_error():
    g = Gemini(KEY, MODEL, transport=RecordingTransport((200, b"{}")))
    with pytest.raises(GeminiError):
        g.generate_json("p", [b"img"], {"type": "ARRAY"})


# -- usage counter ----------------------------------------------------------

class FakeClock:
    def __init__(self, day: date):
        self.day = day

    def __call__(self):
        return datetime(self.day.year, self.day.month, self.day.day, 12, 0,
                        tzinfo=timezone.utc)


def test_usage_counter_rolls_over_days(tmp_path):
    clock = FakeClock(date(2026, 10, 7))
    u = Usage(tmp_path / "gemini_usage.json", clock=clock)
    assert u.today() == 0
    u.add(2)
    assert u.today() == 2
    # Same day persists across instances.
    assert Usage(tmp_path / "gemini_usage.json", clock=clock).today() == 2
    clock.day = date(2026, 10, 8)
    assert u.today() == 0
    u.add(1)
    assert u.today() == 1


def test_gemini_counts_requests_in_usage(tmp_path):
    clock = FakeClock(date(2026, 10, 7))
    u = Usage(tmp_path / "gemini_usage.json", clock=clock)
    tr = RecordingTransport((429, b"rate"), (200, _ok_response([])))
    g = Gemini(KEY, MODEL, transport=tr, usage=u, sleep=lambda s: None)
    g.generate_json("p", [b"img"], {"type": "ARRAY"})
    assert u.today() == 2            # one request plus one retry


# -- reader mapping ---------------------------------------------------------

class FakeArtifactLayout:
    def __init__(self, shape):
        h, w = shape[:2]
        self.panel = Region(0, 0, w, h)
        self.title = Region(0, int(h * 0.05), w, int(h * 0.10))
        self.stars = Region(0, int(h * 0.12), w, int(h * 0.16))
        self.equipped = None
        self.elixir = True


class FakeWeaponLayout:
    def __init__(self, shape):
        h, w = shape[:2]
        self.panel = Region(0, 0, w, h)
        self.title = Region(0, int(h * 0.05), w, int(h * 0.10))
        self.stars = Region(0, int(h * 0.12), w, int(h * 0.16))
        self.equipped = None


def test_read_artifacts_maps_model_json_and_builds(monkeypatch):
    import lumenspar.ai.reader as r

    monkeypatch.setattr(r, "analyse_panel", lambda f: FakeArtifactLayout(f.shape))
    monkeypatch.setattr(r, "count_stars", lambda f, s: 5)
    monkeypatch.setattr(r, "is_locked", lambda f, l: True)

    g = FakeGemini([{
        "slot": "Sands of Eon",
        "main_stat_label": "ATK",
        "main_stat_value": "46.6%",
        "level": "+20",
        "substats": ["CRIT Rate+8.6%", "CRIT DMG+20.2%", "DEF+23",
                     "Energy Recharge+9.1%"],
        "set_name": "Fragment of Harmonic Whimsy",
        "equipped": "Arlecchino",
    }])
    panels = r.read_artifacts(g, [_frame()])
    pt = panels[0]
    assert pt is not None
    assert pt.slot == "Sands of Eon"
    assert pt.main_label == "ATK"
    assert pt.main_value == "46.6%"
    assert pt.rarity == 5              # from the (patched) pixel reader
    assert pt.elixir is True           # from the layout, not the model
    assert pt.locked is True           # from the (patched) pixel reader
    res = build_artifact(pt)
    assert res.ok
    assert res.artifact.slotKey == "sands"
    assert res.artifact.mainStatKey == "atk_"
    assert res.artifact.lock is True


def test_read_artifacts_wrong_entry_count_refused(monkeypatch):
    import lumenspar.ai.reader as r

    monkeypatch.setattr(r, "analyse_panel", lambda f: FakeArtifactLayout(f.shape))
    monkeypatch.setattr(r, "count_stars", lambda f, s: 5)
    monkeypatch.setattr(r, "is_locked", lambda f, l: False)
    g = FakeGemini([{"slot": "Flower of Life"}])       # one entry, two panels
    with pytest.raises(GeminiError):
        r.read_artifacts(g, [_frame(), _frame()])


def test_read_weapons_prefers_pixel_refinement(monkeypatch):
    import lumenspar.ai.reader as r

    monkeypatch.setattr(r, "analyse_weapon_panel",
                        lambda f: FakeWeaponLayout(f.shape))
    monkeypatch.setattr(r, "count_stars", lambda f, s: 5)
    monkeypatch.setattr(r, "weapon_locked", lambda f, l: False)
    monkeypatch.setattr(r, "read_refinement_badge", lambda f, l: 5)

    g = FakeGemini([{
        "name": "Aquila Favonia",
        "level": "Lv. 80/90",
        "refinement": "Refinement Rank 1",     # the model, contradicted
        "equipped": None,
    }])
    (pt,) = r.read_weapons(g, [_frame()])
    assert pt.refinement == "Refinement Rank 5"      # pixels win
    weapon, problems = build_weapon(pt)
    assert weapon is not None
    assert weapon.key == "AquilaFavonia"
    assert weapon.refinement == 5


def test_read_weapons_uses_model_refinement_when_no_badge(monkeypatch):
    import lumenspar.ai.reader as r

    monkeypatch.setattr(r, "analyse_weapon_panel",
                        lambda f: FakeWeaponLayout(f.shape))
    monkeypatch.setattr(r, "count_stars", lambda f, s: 4)
    monkeypatch.setattr(r, "weapon_locked", lambda f, l: False)
    monkeypatch.setattr(r, "read_refinement_badge", lambda f, l: None)
    g = FakeGemini([{
        "name": "The Flute",
        "level": "Lv. 70/80",
        "refinement": "Refinement Rank 3",
        "equipped": None,
    }])
    (pt,) = r.read_weapons(g, [_frame()])
    assert pt.rarity == 4
    weapon, problems = build_weapon(pt)
    assert weapon is not None
    assert weapon.refinement == 3


def test_read_characters_constellation_from_pixels(monkeypatch):
    import lumenspar.ai.reader as r

    monkeypatch.setattr(r, "read_constellation", lambda f: 4)
    g = FakeGemini([{
        "name": "Linnea",
        "level": "Level 80/90",
        "element": "Pyro",
        "description": "test blurb",
        "talents": [
            {"level": 8, "highlighted": False},
            {"level": 8, "highlighted": False},
            {"level": 8, "highlighted": False},
        ],
    }])
    pages = [{"attributes": _frame(), "constellation": _frame(),
              "talents": _frame()}]
    (pt,) = r.read_characters(g, pages)
    assert pt is not None
    assert pt.name == "Linnea"
    assert pt.constellation == 4                # pixels, not the model
    assert pt.talents == {"auto": "Lv. 8", "skill": "Lv. 8", "burst": "Lv. 8"}
    assert pt.talent_boosted == {"auto": False, "skill": False, "burst": False}
    char, notes = build_character(pt)
    assert char is not None
    assert char.key == "Linnea"
    assert char.constellation == 4
    assert char.talent == {"auto": 8, "skill": 8, "burst": 8}


def test_read_materials_maps_name_and_count(monkeypatch):
    import lumenspar.ai.reader as r

    monkeypatch.setattr(r, "material_title_region",
                        lambda f: Region(0, 0, 100, 8))
    g = FakeGemini([{"name": "A Flower Yet to Bloom", "count": 7}])
    tile = Tile(row=0, col=0, rect=Region(10, 20, 60, 40), rarity=3)
    (got,) = r.read_materials(g, [(_frame(), tile, 100)])
    assert got == ("A Flower Yet to Bloom", 7)
    assert len(g.images) == 2           # title crop + caption strip


# -- scanner batching -------------------------------------------------------

class FakeDriver:
    def __init__(self, frame):
        self.frame = frame
        self.clicks = 0
        self.grabs = 0
        self.sleeps: list[float] = []

    def grab(self):
        self.grabs += 1
        return self.frame

    def click(self, x, y):
        self.clicks += 1

    def scroll(self, clicks):
        pass

    def sleep(self, seconds):
        self.sleeps.append(seconds)


def _tiles(n: int) -> list[Tile]:
    return [Tile(row=0, col=i, rect=Region(0, 0, 50, 40), rarity=5)
            for i in range(n)]


def test_scanner_batches_2_2_1_and_accounts(monkeypatch):
    frame = _frame()
    driver = FakeDriver(frame)
    s = Settings(reader_mode="ai", gemini_api_key=KEY, ai_batch_size=2)
    scanner = ArtifactScanner(driver, s)
    scanner._settled_frame = lambda: frame
    sizes: list[int] = []
    scanner._ai_read = lambda entries: (sizes.append(len(entries))
                                        or [(object(), []) for _ in entries])
    result = ScanResult()
    for tile in _tiles(5):
        scanner._read_one(tile, result)
    scanner._flush(result)
    scanner._ai_pipe.drain()          # what scan() does at the end
    # Batches run on worker threads, so they may *start* in any order; result
    # order is pinned by test_scanner_keeps_reading_while_a_batch_is_in_flight.
    assert sorted(sizes, reverse=True) == [2, 2, 1]
    assert result.stats.kept == 5
    assert result.stats.failed == 0
    assert len(result.items) == 5
    assert not scanner._pending


def _gated_scanner(in_flight: int):
    """A scanner whose Gemini batches each wait for their own release event."""
    import threading

    frame = _frame()
    s = Settings(reader_mode="ai", gemini_api_key=KEY, ai_batch_size=2,
                 ai_in_flight=in_flight)
    scanner = ArtifactScanner(FakeDriver(frame), s)
    scanner._settled_frame = lambda: frame
    gates: list[threading.Event] = []
    started: list[int] = []

    def read(entries):
        n = len(started)
        started.append(n)
        gates[n].wait(5)
        return [((n, where), []) for where, _f, _t in entries]

    scanner._ai_read = read
    return scanner, gates


def test_scanner_keeps_reading_while_a_batch_is_in_flight():
    """The point of the pipeline: tile reads do not wait on Gemini."""
    import threading

    scanner, gates = _gated_scanner(in_flight=2)
    gates.extend(threading.Event() for _ in range(2))
    result = ScanResult()
    tiles = _tiles(4)
    for tile in tiles[:2]:
        scanner._read_one(tile, result)       # batch 0 sent, its answer held back
    for tile in tiles[2:]:
        scanner._read_one(tile, result)       # still runs: batch 1 sent too
    assert result.stats.kept == 0             # nothing answered yet
    gates[1].set()                            # the *later* batch answers first...
    gates[0].set()
    scanner._ai_pipe.drain()
    assert result.stats.kept == 4
    # ...and results still come out in scan order.
    assert [batch for batch, _where in result.items] == [0, 0, 1, 1]


def test_scanner_waits_once_the_in_flight_limit_is_reached():
    import threading

    scanner, gates = _gated_scanner(in_flight=1)
    gates.extend(threading.Event() for _ in range(2))
    result = ScanResult()
    for tile in _tiles(2):
        scanner._read_one(tile, result)       # batch 0 in flight (the limit)
    done = threading.Event()

    def next_batch():
        for tile in _tiles(2):
            scanner._read_one(tile, result)   # must wait for batch 0
        done.set()

    t = threading.Thread(target=next_batch)
    t.start()
    assert not done.wait(0.3)                 # held back by the limit
    gates[0].set()
    assert done.wait(5)                       # released once batch 0 settles
    t.join(5)
    gates[1].set()
    scanner._ai_pipe.drain()
    assert result.stats.kept == 4


def test_scanner_auth_error_aborts(monkeypatch):
    frame = _frame()
    scanner = ArtifactScanner(FakeDriver(frame),
                              Settings(reader_mode="ai", gemini_api_key=KEY,
                                       ai_batch_size=2))
    scanner._settled_frame = lambda: frame

    def boom(entries):
        raise GeminiAuthError("Gemini: the Gemini API key was refused")
    scanner._ai_read = boom
    result = ScanResult()
    with pytest.raises(GeminiAuthError):
        scanner._read_one(_tiles(1)[0], result)
        scanner._read_one(_tiles(1)[0], result)   # fills the batch -> flush
        scanner._ai_pipe.drain()                  # the answer is settled here
    assert scanner._ai_abort


def test_scanner_quota_error_fails_pending_items(monkeypatch):
    frame = _frame()
    scanner = ArtifactScanner(FakeDriver(frame),
                              Settings(reader_mode="ai", gemini_api_key=KEY,
                                       ai_batch_size=2))
    scanner._settled_frame = lambda: frame

    def boom(entries):
        raise GeminiQuotaError("Gemini: quota exhausted")
    scanner._ai_read = boom
    result = ScanResult()
    for tile in _tiles(2):
        scanner._read_one(tile, result)     # flushes inside the 2nd call
    scanner._ai_pipe.drain()
    assert scanner._ai_abort
    assert result.stats.failed == 2
    assert result.stats.kept == 0
    assert len(result.items) == 0
    assert all("quota" in p for p in result.problems)
    assert not scanner._pending


def test_scanner_scan_aborts_on_auth_error(monkeypatch):
    import lumenspar.scan.scanner as scn

    frame = _frame()
    driver = FakeDriver(frame)
    s = Settings(reader_mode="ai", gemini_api_key=KEY, ai_batch_size=2,
                 min_artifact_rarity=1)
    scanner = ArtifactScanner(driver, s)
    scanner._settled_frame = lambda: frame
    monkeypatch.setattr(scn, "read_inventory_header", lambda f, rt=None: ("artifacts", 8))
    monkeypatch.setattr(scn, "find_grid", lambda f: Grid(
        tiles=_tiles(2), cols=2, rows=1, pitch_x=50, pitch_y=50,
        region=Region(0, 0, 100, 60)))

    def boom(entries):
        raise GeminiAuthError("Gemini: the Gemini API key was refused")
    scanner._ai_read = boom
    with pytest.raises(GeminiAuthError):
        scanner.scan()
    assert scanner._ai_abort


# -- guards ---------------------------------------------------------------

def test_empty_key_raises_at_construction():
    driver = FakeDriver(_frame())
    s = Settings(reader_mode="ai", gemini_api_key="")
    with pytest.raises(RuntimeError, match="[Aa]PI key"):
        ArtifactScanner(driver, s)


def test_env_var_wins_over_settings(monkeypatch):
    monkeypatch.delenv("LUMENSPAR_GEMINI_KEY", raising=False)
    assert Settings(gemini_api_key="from-settings").gemini_key() == "from-settings"
    monkeypatch.setenv("LUMENSPAR_GEMINI_KEY", "from-env")
    assert Settings(gemini_api_key="from-settings").gemini_key() == "from-env"


def test_local_mode_never_builds_a_gemini_client(monkeypatch):
    import lumenspar.ai.gemini as gemini_mod
    from lumenspar import hostos

    monkeypatch.setattr(hostos, "is_windows", lambda: False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Gemini must not be instantiated in local mode")
    monkeypatch.setattr(gemini_mod, "Gemini", forbidden)
    scanner = ArtifactScanner(FakeDriver(_frame()), Settings(reader_mode="local"))
    assert not hasattr(scanner, "_gemini")


def test_artifact_scanner_ai_read_uses_the_artifact_reader(monkeypatch):
    import lumenspar.ai.reader as reader

    calls = []
    monkeypatch.setattr(reader, "read_artifacts",
                        lambda gem, frames: calls.append(len(frames)) or [None] * len(frames))
    scanner = ArtifactScanner(FakeDriver(_frame()),
                              Settings(reader_mode="ai", gemini_api_key="k"))
    out = scanner._ai_read([("t", _frame(), None), ("u", _frame(), None)])
    assert calls == [2]
    assert [item for item, _ in out] == [None, None]


class _LineGemini:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def generate_json(self, prompt, images, schema):
        self.calls += 1
        assert len(images) == 1 and schema["properties"]["text"]["type"] == "STRING"
        return {"text": self.text}


def test_line_reader_returns_the_model_text():
    from lumenspar.ai.reader import line_reader

    gem = _LineGemini("Artifacts 385/2700")
    assert line_reader(gem)(_frame()[:40, :200]) == "Artifacts 385/2700"
    assert gem.calls == 1


def test_navigation_reads_use_the_text_reader_not_tesseract(monkeypatch):
    from lumenspar.ocr import engine
    from lumenspar.scan.scanner import read_inventory_header, read_tab_title

    def no_tesseract(*a, **k):
        raise AssertionError("Tesseract must not be called")
    monkeypatch.setattr(engine, "read", no_tesseract)
    assert read_inventory_header(_frame(), lambda img: "Artifacts 385/2700") == ("artifacts", 385)
    assert read_tab_title(_frame(), lambda img: "  Character  Development Items ") == \
        "Character Development Items"


def test_ai_scanner_without_tesseract_reads_navigation_with_gemini(monkeypatch):
    from lumenspar.ocr import engine

    monkeypatch.setattr(engine, "available", lambda: False)
    scanner = ArtifactScanner(FakeDriver(_frame()),
                              Settings(reader_mode="ai", gemini_api_key="k"))
    assert scanner._read_text is not None
    monkeypatch.setattr(engine, "available", lambda: True)
    scanner = ArtifactScanner(FakeDriver(_frame()),
                              Settings(reader_mode="ai", gemini_api_key="k"))
    assert scanner._read_text is None


def test_refinement_badge_defers_to_the_model_without_tesseract(monkeypatch):
    from lumenspar.ocr import engine
    from lumenspar.scan import weapons

    monkeypatch.setattr(engine, "available", lambda: False)
    monkeypatch.setattr(weapons, "_refinement_badge", lambda frame, L: np.zeros((20, 20, 3), np.uint8))
    assert weapons.read_refinement_badge(_frame(), None) is None


def test_usage_counts_from_two_clients_add_up(tmp_path):
    from lumenspar.ai.gemini import Usage

    a, b = Usage(tmp_path / "u.json"), Usage(tmp_path / "u.json")
    a.add(); b.add(); a.add()
    assert Usage(tmp_path / "u.json").today() == 3
