"""The wish counter: finding the link, reading the API, storing, counting.

No network: the API is a fake transport serving scripted pages, built the way
the real getGachaLog responds (newest first, 20 a page, paged by end_id).
"""

from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path

import pytest

from lumenspar.wishes import api, importer, link, stats, store

LINK = ("https://gs.hoyoverse.com/genshin/event/e20190909gacha-v3/index.html?"
        "win_mode=fullscreen&authkey_ver=1&sign_type=2&auth_appid=webview_gacha"
        "&init_type=301&lang=en&authkey=SECRET%2Bkey&game_biz=hk4e_global")


# -- finding the link -----------------------------------------------------------

def test_links_are_pulled_from_cache_entries_newest_first():
    old = LINK.replace("SECRET", "OLD")
    data = ("junk1/0/" + old + "\x00more1/0/unrelated https://example.com/x?game_biz=a"
            "1/0/" + LINK + "\x00tail1/0/" + LINK).encode()
    assert link.extract_links(data) == [LINK, old]     # deduplicated, newest first


def _fake_game(base: Path, versions=("2.54.0.0", "2.55.0.0")) -> Path:
    data_dir = base / "Genshin Impact" / "GenshinImpact_Data"
    for v in versions:
        f = data_dir / "webCaches" / v / "Cache" / "Cache_Data" / "data_2"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"1/0/" + LINK.encode())
    return data_dir


def test_the_anime_game_launcher_flatpak_install_is_found(tmp_path):
    _fake_game(tmp_path / ".var/app/moe.launcher.an-anime-game-launcher/data/anime-game-launcher")
    files = link.cache_files(home=tmp_path, windows=False)
    assert [f.parts[-4] for f in files] and all(f.name == "data_2" for f in files)
    assert len(files) == 2


def test_a_wine_prefix_log_points_at_the_game(tmp_path):
    prefix = tmp_path / "Games" / "genshin"
    _fake_game(prefix / "drive_c" / "Games")
    log = prefix / "drive_c/users/me/AppData/LocalLow/miHoYo/Genshin Impact/output_log.txt"
    log.parent.mkdir(parents=True)
    log.write_text("Loading C:/Games/Genshin Impact/GenshinImpact_Data/Managed\n", encoding="utf-8")
    assert len(link.cache_files(home=tmp_path, windows=False)) == 2


def test_a_game_folder_picked_by_hand(tmp_path):
    _fake_game(tmp_path / "anywhere")
    assert link.links_from_folder(tmp_path / "anywhere") == [LINK]


# -- the API ----------------------------------------------------------------------

def test_the_cached_page_url_is_pointed_at_the_api():
    url = urllib.parse.urlsplit(api.api_url(LINK, "302", page=3, end_id="99"))
    q = dict(urllib.parse.parse_qsl(url.query))
    assert url.netloc == api.HOST_GLOBAL and url.path == api.PATH
    assert q["authkey"] == "SECRET+key"          # passed through intact
    assert (q["gacha_type"], q["page"], q["end_id"], q["lang"]) == ("302", "3", "99", "en-us")
    china = api.api_url(LINK.replace("hk4e_global", "hk4e_cn"), "301")
    assert urllib.parse.urlsplit(china).netloc == api.HOST_CHINA


def test_a_link_without_an_authkey_is_refused():
    with pytest.raises(api.WishApiError):
        api.api_url("https://gs.hoyoverse.com/x?game_biz=hk4e_global", "301")


class FakeServer:
    """getGachaLog over scripted histories: {gacha_type: [rows newest first]}."""

    def __init__(self, histories: dict[str, list[dict]], fail: list[dict] | None = None):
        self.histories = histories
        self.fail = list(fail or [])      # responses served before the real ones
        self.requests: list[dict] = []

    def __call__(self, url: str) -> bytes:
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.requests.append(q)
        if self.fail:
            return json.dumps(self.fail.pop(0)).encode()
        rows = self.histories.get(q["gacha_type"], [])
        if q["end_id"] != "0":
            rows = [r for r in rows if int(r["id"]) < int(q["end_id"])]
        page = rows[: int(q["size"])]
        return json.dumps({"retcode": 0, "message": "OK",
                           "data": {"region": "os_euro", "list": page}}).encode()


def _rows(n: int, gacha_type: str = "301", start_id: int = 1000, five_every: int = 0,
          name: str = "Furina") -> list[dict]:
    """n wishes, newest first, ids increasing with time."""
    out = []
    for i in range(n):
        rank = "5" if five_every and (i + 1) % five_every == 0 else "3"
        out.append({"uid": "700000001", "id": str(start_id + i), "gacha_type": gacha_type,
                    "time": f"2026-10-01 12:{i // 60:02d}:{i % 60:02d}", "name": name if rank == "5" else "Slingshot",
                    "item_type": "Weapon", "rank_type": rank})
    return out[::-1]


def test_banners_are_read_page_by_page():
    server = FakeServer({"301": _rows(45)})
    rows, finished = api.WishApi(LINK, transport=server, sleep=lambda s: None).fetch(
        api.BANNERS[0], set())
    assert len(rows) == 45 and finished
    assert [r["page"] for r in server.requests] == ["1", "2", "3"]


def test_reading_stops_at_the_first_wish_already_stored():
    server = FakeServer({"301": _rows(45)})
    known = {r["id"] for r in _rows(45)[10:]}            # all but the 10 newest
    rows, _ = api.WishApi(LINK, transport=server, sleep=lambda s: None).fetch(api.BANNERS[0], known)
    assert len(rows) == 10 and len(server.requests) == 1


def test_being_told_to_slow_down_is_retried():
    waits = []
    server = FakeServer({"301": _rows(3)}, fail=[{"retcode": -110, "message": "visit too frequently"}])
    rows, _ = api.WishApi(LINK, transport=server, sleep=waits.append).fetch(api.BANNERS[0], set())
    assert len(rows) == 3 and waits == [api.BUSY_WAITS[0]]


def test_an_expired_link_says_so():
    server = FakeServer({}, fail=[{"retcode": -101, "message": "authkey timeout"}])
    with pytest.raises(api.LinkExpired):
        api.WishApi(LINK, transport=server, sleep=lambda s: None).fetch(api.BANNERS[0], set())


# -- importing and storing --------------------------------------------------------

def test_an_import_is_stored_and_the_next_one_only_reads_new_wishes(tmp_path):
    server = FakeServer({"301": _rows(45), "200": _rows(5, "200", start_id=5000)})
    h = importer.run(LINK, lambda m: None, transport=server, root=tmp_path)
    assert (h.uid, len(h.wishes["character"]), len(h.wishes["standard"])) == ("700000001", 45, 5)
    assert "authkey" not in (tmp_path / "700000001.json").read_text(encoding="utf-8")

    server.histories["301"] = _rows(47)                  # two new wishes since
    server.requests.clear()
    h = importer.run(LINK, lambda m: None, transport=server, root=tmp_path)
    assert len(h.wishes["character"]) == 47
    assert len([r for r in server.requests if r["gacha_type"] == "301"]) == 1


def test_an_interrupted_import_is_read_in_full_next_time(tmp_path):
    server = FakeServer({"301": _rows(45)})
    calls = {"n": 0}

    def stop_after_first_page():
        calls["n"] += 1
        return calls["n"] > 2          # let the first page through, then stop
    importer.run(LINK, lambda m: None, should_stop=stop_after_first_page, transport=server,
                 root=tmp_path)
    h = store.load("700000001", tmp_path)
    assert len(h.wishes["character"]) == 20 and "character" not in h.complete

    h = importer.run(LINK, lambda m: None, transport=server, root=tmp_path)
    assert len(h.wishes["character"]) == 45 and "character" in h.complete


# -- counting ---------------------------------------------------------------------

@pytest.fixture
def schedule(tmp_path, monkeypatch):
    path = tmp_path / "wish_banners.json"
    path.write_text(json.dumps({"characters": [
        {"start": "2026-09-01 06:00:00", "end": "2026-09-20 17:59:59", "featured": ["furina"]},
        {"start": "2026-09-23 06:00:00", "end": "2026-10-13 17:59:59", "featured": ["vesna", "vodyanitsa"]},
    ], "weapons": [
        {"start": "2026-09-01 06:00:00", "end": "2026-10-13 17:59:59",
         "featured": ["primordial_jade_winged-spear", "lions_roar"]},
    ]}), encoding="utf-8")
    monkeypatch.setattr(stats, "SCHEDULE_PATH", path)
    stats._schedule.cache_clear()
    yield
    stats._schedule.cache_clear()


def _wish(name, rank, time="2026-10-01 12:00:00"):
    return {"id": "1", "name": name, "rank_type": rank, "time": time}


def test_pity_counts_wishes_since_the_last_5_and_4_star(schedule):
    wishes = [_wish("x", "3")] * 9 + [_wish("Bennett", "4")] + [_wish("x", "3")] * 3
    s = stats.banner_stats("standard", wishes)
    assert (s["total"], s["pity5"], s["pity4"], s["primogems"]) == (13, 13, 3, 13 * 160)


def test_a_lost_50_50_makes_the_next_5_star_guaranteed(schedule):
    wishes = ([_wish("x", "3")] * 74 + [_wish("Diluc", "5")]                 # lost at 75
              + [_wish("x", "3")] * 9 + [_wish("Vesna", "5")]                 # guaranteed at 10
              + [_wish("x", "3")] * 40 + [_wish("Vodyanitsa", "5")])          # won at 41
    s = stats.banner_stats("character", wishes)
    assert [(f["name"], f["pity"], f["result"]) for f in s["fives"]] == [
        ("Vodyanitsa", 41, "won"), ("Vesna", 10, "guaranteed"), ("Diluc", 75, "lost")]
    assert (s["won"], s["lost"], s["guaranteed"], s["averagePity"]) == (1, 1, False, 42.0)


def test_the_featured_check_reaches_across_server_timezones(schedule):
    # A Furina pulled in America's evening of the banner's last day is past
    # its end in Asia time; the slack still counts it as featured.
    s = stats.banner_stats("character", [_wish("Furina", "5", "2026-09-21 05:00:00")])
    assert s["fives"][0]["result"] == "won"


def test_weapon_ids_match_whatever_paimon_moe_spells_them(schedule):
    s = stats.banner_stats("weapon", [_wish("Primordial Jade Winged-Spear", "5"),
                                      _wish("Lion's Roar", "5")])
    assert [f["result"] for f in s["fives"]] == ["won", "won"]


def test_a_5_star_newer_than_the_schedule_is_flagged_not_guessed(schedule):
    s = stats.banner_stats("character", [_wish("Somebody", "5", "2027-01-01 12:00:00")])
    assert s["fives"][0]["result"] == "unknown" and s["scheduleStale"]


def test_the_shipped_schedule_covers_the_current_banner():
    stats._schedule.cache_clear()
    assert stats.featured_at("characters", "2026-10-01 12:00:00")


def test_the_paimon_moe_link_matches_what_its_script_produces():
    # getlink.ps1 takes each entry's `https.+?game_biz=`: the URL up to and
    # including "game_biz=", without the value.
    import re
    entry = "1/0/" + LINK + "&other=1\x00"
    script = re.search(r"(https.+?game_biz=)", entry).group(1)
    assert link.paimon_link(link.extract_links(entry.encode())[0]) == script
    assert script.endswith("game_biz=") and "authkey=" in script


def test_an_unreachable_service_is_not_reported_as_expired_links():
    # A real AppImage could not verify HTTPS and called every link "expired".
    def offline(url):
        raise OSError("certificate verify failed")
    with pytest.raises(api.ServiceUnreachable, match="could not reach"):
        api.first_working([LINK, LINK.replace("SECRET", "OTHER")], transport=offline,
                          sleep=lambda s: None)


def test_expired_links_are_skipped_until_one_works():
    calls = []
    def server(url):
        calls.append(url)
        ok = len(calls) == 3
        return json.dumps({"retcode": 0 if ok else -101, "message": "OK" if ok else "authkey timeout",
                           "data": {"list": []}}).encode()
    links = [LINK.replace("SECRET", f"K{i}") for i in range(4)]
    assert api.first_working(links, transport=server, sleep=lambda s: None) == links[2]


# -- portraits ------------------------------------------------------------------

from lumenspar.wishes import icons


def test_portraits_are_looked_up_by_display_name():
    assert icons.icon_name("Furina") == "UI_AvatarIcon_Furina"
    assert icons.icon_name("skyward harp").startswith("UI_EquipIcon_")
    assert icons.icon_name("Nobody At All") == ""


def test_only_missing_portraits_are_fetched_and_failures_are_quiet(tmp_path):
    (tmp_path / "UI_AvatarIcon_Furina.png").write_bytes(b"\x89PNG cached")
    wanted = icons.missing(["Furina", "Furina", "Skyward Harp", "Nobody At All"], root=tmp_path)
    assert wanted == [icons.icon_name("Skyward Harp")]          # cached, duplicate, unknown skipped

    def fetch(url):
        if "Bow" in url or "Claymore" in url or "Sword" in url or "Catalyst" in url or "Pole" in url:
            return b"\x89PNG weapon"
        raise OSError("offline")
    assert icons.download(wanted + ["UI_AvatarIcon_Gone"], root=tmp_path, fetch=fetch) == 1
    assert (tmp_path / f"{wanted[0]}.png").read_bytes() == b"\x89PNG weapon"
    assert not (tmp_path / "UI_AvatarIcon_Gone.png").exists()

    # Something that is not a PNG (an error page, say) is never cached.
    assert icons.download(["UI_AvatarIcon_Html"], root=tmp_path, fetch=lambda u: b"<html>") == 0


# -- reading the cache while the game holds it open ---------------------------------

def _locked(monkeypatch, locked: set):
    real = Path.read_bytes

    def read_bytes(self):
        if self in locked:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)


def test_a_cache_file_the_game_holds_open_is_read_with_shared_access(tmp_path, monkeypatch):
    f = tmp_path / "data_2"
    f.write_bytes(b"1/0/" + LINK.encode())
    _locked(monkeypatch, {f})
    shared = []
    assert link.read_cache(f, shared_read=lambda p: shared.append(p) or b"ok") == b"ok"
    assert shared == [f]


def test_an_unreadable_cache_file_is_skipped_when_another_can_be_read(tmp_path, monkeypatch):
    new, old = tmp_path / "new", tmp_path / "old"
    new.write_bytes(b"x")
    old.write_bytes(b"1/0/" + LINK.encode())
    _locked(monkeypatch, {new})
    monkeypatch.setattr(link.os, "name", "posix")
    logs = []
    assert link.links_from_files([new, old], logs.append) == [LINK]
    assert any("Could not read" in m for m in logs)


def test_when_no_cache_file_can_be_read_the_error_says_what_to_do(tmp_path, monkeypatch):
    f = tmp_path / "data_2"
    f.write_bytes(b"x")
    _locked(monkeypatch, {f})

    def still_locked(p):
        raise PermissionError(13, "Permission denied")
    with pytest.raises(link.CacheUnreadable, match="Close Genshin Impact"):
        link.read_cache(f, shared_read=still_locked)


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing")
def test_windows_reads_a_file_held_open_the_way_the_game_holds_data_2(tmp_path):
    # The game's browser keeps data_2 open with delete access and full sharing;
    # a plain open() then fails, because it does not offer delete sharing.
    import ctypes
    from ctypes import wintypes
    f = tmp_path / "data_2"
    f.write_bytes(b"1/0/" + LINK.encode())
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE)
    delete, read, write = 0x00010000, 0x80000000, 0x40000000
    held = k32.CreateFileW(str(f), read | write | delete, 0x7, None, 3, 0x80, None)
    assert held not in (None, wintypes.HANDLE(-1).value)
    try:
        with pytest.raises(PermissionError):
            f.read_bytes()
        assert link.extract_links(link.read_cache(f)) == [LINK]
    finally:
        k32.CloseHandle(wintypes.HANDLE(held))
