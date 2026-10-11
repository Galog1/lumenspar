"""Google Drive backup: sign-in, the app-data folder, and two-way sync.

No network: Google is a fake transport. The browser half of sign-in is
played by a thread that requests the loopback redirect, as Google would.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import urllib.parse
import urllib.request

import pytest

from lumenspar import gdrive
from lumenspar.wishes import backup, store

CLIENT = "123-abc.apps.googleusercontent.com"


def _state(tmp_path, **kw) -> gdrive.DriveState:
    s = gdrive.DriveState(client_id=CLIENT, client_secret="shh", path=tmp_path / "drive.json",
                          builtin=("", ""))
    if kw.get("refresh_token"):
        kw.setdefault("token_client", CLIENT)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _id_token(email: str) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).rstrip(b"=").decode()
    return f"x.{body}.y"


def _reply(status: int, obj) -> tuple[int, bytes]:
    return status, json.dumps(obj).encode()


# -- saved state ----------------------------------------------------------------

def test_state_round_trips_and_is_owner_only(tmp_path):
    s = _state(tmp_path, refresh_token="r", email="a@b.c")
    s.save()
    assert gdrive.DriveState.load(s.path) == s
    if os.name == "posix":
        assert (s.path.stat().st_mode & 0o777) == 0o600
    assert gdrive.DriveState.load(tmp_path / "missing.json", builtin=("", "")).signed_in is False


# -- the built-in client -------------------------------------------------------------

def test_the_console_download_and_a_flat_file_both_work_as_the_builtin_client(tmp_path):
    f = tmp_path / "google_client.json"
    f.write_text(json.dumps({"installed": {"client_id": "b.apps.googleusercontent.com",
                                           "client_secret": "bs", "auth_uri": "x"}}),
                 encoding="utf-8-sig")       # PowerShell may write a byte-order mark
    assert gdrive.builtin_client(f) == ("b.apps.googleusercontent.com", "bs")
    f.write_text(json.dumps({"client_id": "c", "client_secret": "cs"}))
    assert gdrive.builtin_client(f) == ("c", "cs")
    assert gdrive.builtin_client(tmp_path / "absent.json") == ("", "")


def test_the_users_own_client_wins_and_a_sign_in_belongs_to_its_client(tmp_path):
    s = gdrive.DriveState(path=tmp_path / "d.json", builtin=("b", "bs"))
    assert s.configured and s.client == ("b", "bs") and not s.own_client
    s.refresh_token, s.token_client = "r", "b"
    assert s.signed_in
    s.client_id, s.client_secret = CLIENT, "shh"       # switching to their own project
    assert s.client == (CLIENT, "shh") and not s.signed_in
    s.client_id = s.client_secret = ""                  # and back
    assert s.signed_in


def test_a_sign_in_saved_before_token_client_existed_still_counts(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"client_id": CLIENT, "client_secret": "shh", "refresh_token": "r"}))
    assert gdrive.DriveState.load(p, builtin=("", "")).signed_in


def test_sign_in_uses_the_builtin_client_when_there_is_no_own_one(tmp_path):
    open_url, seen = _browser()
    posted = {}

    def transport(req):
        posted.update(urllib.parse.parse_qsl(req.data.decode()))
        return _reply(200, {"refresh_token": "r2", "id_token": _id_token("x@example.com")})

    s = gdrive.DriveState(path=tmp_path / "d.json", builtin=("b", "bs"))
    gdrive.sign_in(s, open_url, transport=transport, timeout=10)
    assert seen["client_id"] == "b" and posted["client_secret"] == "bs"
    assert s.signed_in and s.token_client == "b"


# -- sign-in --------------------------------------------------------------------

def test_pkce_challenge_is_s256_of_the_verifier():
    verifier, challenge = gdrive.pkce_pair()
    expect = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expect.decode() and 43 <= len(verifier) <= 128


def _browser(answer: dict | None = None):
    """Plays Google's side: reads the auth URL and redirects to the loopback."""
    seen = {}

    def open_url(url: str) -> None:
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        seen.update(q)
        params = dict(answer or {"code": "the-code"}, state=q["state"])

        def visit():
            urllib.request.urlopen(q["redirect_uri"] + "?" + urllib.parse.urlencode(params),
                                   timeout=5).read()
        threading.Thread(target=visit, daemon=True).start()
    return open_url, seen


def test_sign_in_exchanges_the_code_and_stores_the_refresh_token(tmp_path):
    open_url, seen = _browser()
    posted = {}

    def transport(req):
        posted.update(urllib.parse.parse_qsl(req.data.decode()))
        return _reply(200, {"access_token": "a", "refresh_token": "r1",
                            "id_token": _id_token("me@example.com")})

    s = _state(tmp_path)
    gdrive.sign_in(s, open_url, transport=transport, timeout=10)
    assert seen["redirect_uri"].startswith("http://127.0.0.1:")
    assert seen["code_challenge_method"] == "S256" and "drive.appdata" in seen["scope"]
    assert posted["code"] == "the-code" and posted["redirect_uri"] == seen["redirect_uri"]
    assert posted["code_verifier"] and posted["grant_type"] == "authorization_code"
    assert (s.refresh_token, s.email) == ("r1", "me@example.com")
    assert gdrive.DriveState.load(s.path).refresh_token == "r1"


def test_declined_sign_in_points_at_the_publish_step(tmp_path):
    open_url, _ = _browser({"error": "access_denied"})
    with pytest.raises(gdrive.DriveError, match=rf"\(step {gdrive.STEP_PUBLISH}\)"):
        gdrive.sign_in(_state(tmp_path), open_url, transport=lambda r: None, timeout=10)


def test_sign_in_can_be_cancelled(tmp_path):
    with pytest.raises(gdrive.DriveError, match="not completed"):
        gdrive.sign_in(_state(tmp_path), lambda url: None, should_stop=lambda: True)


def test_sign_in_needs_a_client(tmp_path):
    s = gdrive.DriveState(path=tmp_path / "d.json", builtin=("", ""))
    with pytest.raises(gdrive.DriveError, match=rf"\(step {gdrive.STEP_CLIENT}\)"):
        gdrive.sign_in(s, lambda url: None)


def test_a_wrong_client_secret_points_at_the_client_step(tmp_path):
    open_url, _ = _browser()
    with pytest.raises(gdrive.DriveError, match=rf"\(step {gdrive.STEP_CLIENT}\)"):
        gdrive.sign_in(_state(tmp_path), open_url, timeout=10,
                       transport=lambda r: _reply(401, {"error": "invalid_client"}))


# -- the app-data folder ----------------------------------------------------------

class FakeDrive:
    """Google's token endpoint and Drive's appDataFolder, in memory."""

    def __init__(self, files=None, *, refresh=200, api_enabled=True):
        self.files = dict(files or {})       # id -> (name, bytes)
        self.refresh = refresh
        self.api_enabled = api_enabled
        self.uploads = 0

    def __call__(self, req):
        url = req.full_url
        if url == gdrive.TOKEN_URL:
            if self.refresh != 200:
                return _reply(400, {"error": "invalid_grant"})
            return _reply(200, {"access_token": "tok", "expires_in": 3600})
        assert req.get_header("Authorization") == "Bearer tok"
        if not self.api_enabled:
            return _reply(403, {"error": {"message": "Drive API has not been used in project 1",
                                          "errors": [{"reason": "accessNotConfigured"}]}})
        path = urllib.parse.urlsplit(url).path
        if req.get_method() == "GET" and path.endswith("/files"):
            assert "appDataFolder" in url
            return _reply(200, {"files": [{"id": i, "name": n} for i, (n, _) in self.files.items()]})
        if req.get_method() == "GET":
            return 200, self.files[path.rsplit("/", 1)[1]][1]
        self.uploads += 1
        if req.get_method() == "PATCH":
            fid = path.rsplit("/", 1)[1]
            self.files[fid] = (self.files[fid][0], req.data)
            return _reply(200, {"id": fid})
        # multipart create: metadata part, then the content part
        parts = req.data.split(b"\r\n\r\n")
        meta = json.loads(parts[1].split(b"\r\n--")[0])
        assert meta["parents"] == ["appDataFolder"]
        content = parts[2].rsplit(b"\r\n--", 1)[0]
        fid = f"f{len(self.files) + 1}"
        self.files[fid] = (meta["name"], content)
        return _reply(200, {"id": fid})


def _history(uid, ids, complete=("character",)) -> store.History:
    rows = [{"id": str(i), "time": "2026-01-01 00:00:00", "name": "Fischl",
             "item_type": "Character", "rank_type": "4", "gacha_type": "301"} for i in ids]
    h = store.History(uid=uid, complete=set(complete))
    h.add("character", rows)
    return h


def _remote(h: store.History) -> bytes:
    return backup._serialise(h)


def test_first_backup_uploads_every_local_account(tmp_path):
    root = tmp_path / "wishes"
    store.save(_history("111", [1, 2]), root)
    store.save(_history("222", [5]), root)
    drive = FakeDrive()
    logs = []
    assert backup.sync(gdrive.AppData(_state(tmp_path, refresh_token="r"), drive),
                       logs.append, root) == (0, 2)
    names = sorted(n for n, _ in drive.files.values())
    assert names == ["wishes-111.json", "wishes-222.json"]
    up = json.loads(next(d for n, d in drive.files.values() if n == "wishes-111.json"))
    assert [w["id"] for w in up["wishes"]["character"]] == ["1", "2"]


def test_a_fresh_install_restores_from_drive(tmp_path):
    root = tmp_path / "wishes"
    drive = FakeDrive({"x": ("wishes-111.json", _remote(_history("111", [1, 2, 3])))})
    restored, uploaded = backup.sync(gdrive.AppData(_state(tmp_path, refresh_token="r"), drive),
                                     lambda m: None, root)
    assert (restored, uploaded) == (3, 0) and drive.uploads == 0
    local = store.load("111", root)
    assert local.total() == 3 and local.complete == {"character"}


def test_both_sides_end_up_with_the_union(tmp_path):
    root = tmp_path / "wishes"
    store.save(_history("111", [1, 2, 4], complete=()), root)          # imported here
    drive = FakeDrive({"x": ("wishes-111.json", _remote(_history("111", [1, 2, 3])))})
    restored, uploaded = backup.sync(gdrive.AppData(_state(tmp_path, refresh_token="r"), drive),
                                     lambda m: None, root)
    assert (restored, uploaded) == (1, 1)
    assert [w["id"] for w in store.load("111", root).wishes["character"]] == ["1", "2", "3", "4"]
    remote = json.loads(drive.files["x"][1])
    assert [w["id"] for w in remote["wishes"]["character"]] == ["1", "2", "3", "4"]
    assert remote["complete"] == ["character"]


def test_nothing_is_uploaded_when_drive_is_current(tmp_path):
    root = tmp_path / "wishes"
    h = _history("111", [1, 2])
    store.save(h, root)
    drive = FakeDrive({"x": ("wishes-111.json", _remote(h))})
    assert backup.sync(gdrive.AppData(_state(tmp_path, refresh_token="r"), drive),
                       lambda m: None, root) == (0, 0)
    assert drive.uploads == 0


def test_an_expired_sign_in_is_forgotten_and_says_so(tmp_path):
    s = _state(tmp_path, refresh_token="r")
    with pytest.raises(gdrive.SignedOut, match=rf"step {gdrive.STEP_PUBLISH}"):
        gdrive.AppData(s, FakeDrive(refresh=400)).list()
    assert not s.signed_in and not gdrive.DriveState.load(s.path).refresh_token


def test_a_disabled_drive_api_points_at_the_api_step(tmp_path):
    with pytest.raises(gdrive.DriveError, match=rf"\(step {gdrive.STEP_API}\)"):
        gdrive.AppData(_state(tmp_path, refresh_token="r"), FakeDrive(api_enabled=False)).list()
