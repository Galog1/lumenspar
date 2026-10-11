"""Google sign-in and Drive's hidden app-data folder, for backing up data.

Each user connects their *own* Google Cloud OAuth client (Desktop app type);
the wish counter's setup guide walks through creating one. Lumenspar asks for
two non-sensitive permissions only: its own hidden app-data folder in Drive
(which cannot see any of the user's files) and the email address, to show
who is signed in. Non-sensitive scopes need no Google review.

Sign-in is Google's installed-app flow: the browser is sent to Google, which
redirects back to a one-off loopback address (http://127.0.0.1:<port>/) that
this module listens on, protected with PKCE. The refresh token that comes
back is kept in google_drive.json in the config folder, readable by the owner
only, together with the client ID and secret (which Google itself does not
treat as secret for Desktop-app clients).
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import CONFIG_DIR

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
SCOPES = "openid email https://www.googleapis.com/auth/drive.appdata"
STATE_PATH = CONFIG_DIR / "google_drive.json"
SIGN_IN_TIMEOUT = 300.0

# The setup guide's steps, referred to by number in error messages.
STEP_API, STEP_PUBLISH, STEP_CLIENT = 2, 5, 6

# Google only publishes an app with a homepage and privacy policy on a domain
# listed as authorized. Users without a site of their own enter Lumenspar's
# project site (docs/ in the repository, served by GitHub Pages).
HOMEPAGE_URL = "https://galog1.github.io/lumenspar/"
PRIVACY_URL = "https://galog1.github.io/lumenspar/privacy.html"
AUTHORIZED_DOMAIN = "galog1.github.io"


class DriveError(Exception):
    """Something the user can act on; the message says what."""


class SignedOut(DriveError):
    """The saved sign-in no longer works (revoked, or expired in Testing mode)."""


# -- saved state -------------------------------------------------------------------

@dataclass
class DriveState:
    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    email: str = ""
    last_backup: str = ""
    path: Path = field(default=STATE_PATH, repr=False, compare=False)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def signed_in(self) -> bool:
        return self.configured and bool(self.refresh_token)

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> "DriveState":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(path=path)
        return cls(**{k: str(raw.get(k, "")) for k in
                      ("client_id", "client_secret", "refresh_token", "email", "last_backup")},
                   path=path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: getattr(self, k) for k in
                                   ("client_id", "client_secret", "refresh_token", "email",
                                    "last_backup")}, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)      # holds a refresh token
        except OSError:
            pass
        tmp.replace(self.path)


# -- HTTP --------------------------------------------------------------------------

Transport = Callable[[urllib.request.Request], tuple[int, bytes]]


def _default_transport(req: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        raise DriveError(f"could not reach Google ({exc})") from exc


def _json(body: bytes) -> dict:
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except ValueError:
        return {}


def _token_error(status: int, body: bytes) -> DriveError:
    err = _json(body).get("error", "")
    if err == "invalid_grant":
        return SignedOut(
            "Google sign-in has expired or was revoked -- sign in again. If this "
            f"happens every week, the project is still in Testing mode (step {STEP_PUBLISH}).")
    if err in ("invalid_client", "unauthorized_client"):
        return DriveError("Google rejected the client ID or secret -- check them against "
                          f"the Desktop app client you created (step {STEP_CLIENT}).")
    return DriveError(f"Google sign-in failed ({err or status})")


# -- sign-in -----------------------------------------------------------------------

def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": SCOPES, "code_challenge": challenge, "code_challenge_method": "S256",
        "state": state, "access_type": "offline", "prompt": "consent",
    })


_DONE_PAGE = (b"<!doctype html><meta charset=utf-8><title>Lumenspar</title>"
              b"<body style='font:16px sans-serif;background:#0B0E14;color:#E8EDF7;"
              b"display:grid;place-items:center;height:90vh'><div>"
              b"<h2 style='color:#4FD8E8'>%s</h2><p>%s</p></div>")


def _wait_for_redirect(server: http.server.HTTPServer, timeout: float,
                       should_stop: Callable[[], bool]) -> dict:
    """Serve the loopback address until Google redirects back to it."""
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 -- http.server's name
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            if "code" not in q and "error" not in q:
                self.send_response(404)
                self.end_headers()
                return
            result.update(q)
            ok = "code" in q
            page = _DONE_PAGE % ((b"Signed in", b"You can close this tab and go back to Lumenspar.")
                                 if ok else (b"Sign-in cancelled", b"Go back to Lumenspar."))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):  # keep the request out of stderr
            pass

    server.RequestHandlerClass = Handler
    server.timeout = 0.5
    deadline = time.monotonic() + timeout
    while not result and time.monotonic() < deadline and not should_stop():
        server.handle_request()
    return result


def sign_in(state: DriveState, open_url: Callable[[str], None], *,
            transport: Transport | None = None, timeout: float = SIGN_IN_TIMEOUT,
            should_stop: Callable[[], bool] = lambda: False) -> None:
    """Run the browser sign-in and store the refresh token and email in `state`."""
    if not state.configured:
        raise DriveError(f"Enter the client ID and secret first (step {STEP_CLIENT}).")
    server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    try:
        redirect = f"http://127.0.0.1:{server.server_address[1]}/"
        verifier, challenge = pkce_pair()
        nonce = secrets.token_urlsafe(16)
        open_url(auth_url(state.client_id, redirect, challenge, nonce))
        reply = _wait_for_redirect(server, timeout, should_stop)
    finally:
        server.server_close()
    if not reply:
        raise DriveError("Sign-in was not completed in the browser.")
    if reply.get("state") != nonce:
        raise DriveError("Sign-in answer did not match this request; try again.")
    if "error" in reply:
        if reply["error"] == "access_denied":
            raise DriveError("Google sign-in was declined. If you did not decline it, your "
                             "account may not be allowed yet: publish the app "
                             f"(step {STEP_PUBLISH}).")
        raise DriveError(f"Google sign-in failed ({reply['error']})")

    tokens = _post_token({"code": reply["code"], "client_id": state.client_id,
                          "client_secret": state.client_secret, "redirect_uri": redirect,
                          "grant_type": "authorization_code", "code_verifier": verifier},
                         transport)
    if not tokens.get("refresh_token"):
        raise DriveError("Google did not return a lasting sign-in; try signing in again.")
    state.refresh_token = tokens["refresh_token"]
    state.email = _email_from_id_token(tokens.get("id_token", ""))
    state.save()


def _post_token(form: dict, transport: Transport | None) -> dict:
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(form).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    status, body = (transport or _default_transport)(req)
    if status != 200:
        raise _token_error(status, body)
    return _json(body)


def _email_from_id_token(id_token: str) -> str:
    """The email claim of the ID token (display only, so not verified)."""
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))\
            .get("email", "")
    except (IndexError, ValueError):
        return ""


def sign_out(state: DriveState, transport: Transport | None = None) -> None:
    """Forget the sign-in, and ask Google to revoke it (best effort)."""
    token, state.refresh_token, state.email = state.refresh_token, "", ""
    state.save()
    if token:
        try:
            req = urllib.request.Request(REVOKE_URL, data=urllib.parse.urlencode(
                {"token": token}).encode(), headers={"Content-Type":
                                                     "application/x-www-form-urlencoded"})
            (transport or _default_transport)(req)
        except DriveError:
            pass


# -- the app-data folder -------------------------------------------------------------

class AppData:
    """Files in the signed-in user's hidden Drive app-data folder."""

    def __init__(self, state: DriveState, transport: Transport | None = None) -> None:
        self.state = state
        self._transport = transport or _default_transport
        self._access = ""
        self._expires = 0.0

    def _token(self) -> str:
        if not self.state.signed_in:
            raise SignedOut("Not signed in to Google Drive.")
        if not self._access or time.monotonic() > self._expires - 60:
            try:
                tokens = _post_token({"client_id": self.state.client_id,
                                      "client_secret": self.state.client_secret,
                                      "refresh_token": self.state.refresh_token,
                                      "grant_type": "refresh_token"}, self._transport)
            except SignedOut:
                self.state.refresh_token = ""
                self.state.save()
                raise
            self._access = tokens.get("access_token", "")
            self._expires = time.monotonic() + float(tokens.get("expires_in", 3600))
        return self._access

    def _call(self, method: str, url: str, data: bytes | None = None,
              content_type: str | None = None) -> bytes:
        headers = {"Authorization": f"Bearer {self._token()}"}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        status, body = self._transport(req)
        if status in (200, 201, 204):
            return body
        err = _json(body).get("error") or {}
        reasons = {e.get("reason") for e in err.get("errors", []) if isinstance(e, dict)}
        if status == 403 and ("accessNotConfigured" in reasons
                              or "has not been used" in str(err.get("message", ""))):
            raise DriveError("The Google Drive API is not enabled in your Google Cloud "
                             f"project (step {STEP_API}). It can take a few minutes to "
                             "take effect after enabling.")
        if status == 401:
            self._access = ""
        raise DriveError(f"Google Drive refused the request ({status}: "
                         f"{err.get('message', '') or 'no details'})")

    def list(self) -> dict[str, str]:
        """{file name: file id} in the app-data folder."""
        q = urllib.parse.urlencode({"spaces": "appDataFolder", "pageSize": "1000",
                                    "fields": "files(id,name)"})
        files = _json(self._call("GET", f"{DRIVE_FILES}?{q}")).get("files", [])
        return {f["name"]: f["id"] for f in files}

    def download(self, file_id: str) -> bytes:
        return self._call("GET", f"{DRIVE_FILES}/{urllib.parse.quote(file_id)}?alt=media")

    def upload(self, name: str, data: bytes, file_id: str | None = None) -> str:
        """Create `name` in the app-data folder, or replace the content of `file_id`."""
        if file_id:
            self._call("PATCH", f"{DRIVE_UPLOAD}/{urllib.parse.quote(file_id)}"
                       "?uploadType=media", data, "application/json")
            return file_id
        boundary = "lumenspar" + secrets.token_hex(8)
        meta = json.dumps({"name": name, "parents": ["appDataFolder"]}).encode()
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                + meta + f"\r\n--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode()
                + data + f"\r\n--{boundary}--\r\n".encode())
        reply = self._call("POST", f"{DRIVE_UPLOAD}?uploadType=multipart&fields=id", body,
                           f"multipart/related; boundary={boundary}")
        return _json(reply).get("id", "")
