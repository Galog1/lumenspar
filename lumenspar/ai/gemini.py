"""Minimal stdlib client for the Gemini REST API (no SDK).

Only what AI reading needs: `generate_json` posts a batched vision prompt and
parses the JSON the model returns; `check` verifies the key and model for the
settings self-test. The transport is a plain callable so tests can inject a
fake; the default speaks urllib and converts HTTPError into (code, body).

Errors are mapped to user-facing messages, like `enka.EnkaError`. The API key
never appears in an exception message or in any log line.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from ..config import CONFIG_DIR

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODEL_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}"
USER_AGENT = "Lumenspar (+https://github.com/Galog1/lumenspar)"
MAX_BODY = 19 * 1024 * 1024        # Google's documented 20 MB request cap, minus slack
RETRY_WAITS = (4.0, 8.0, 16.0, 32.0)
PACIFIC = ZoneInfo("America/Los_Angeles")   # Google's quota resets at midnight Pacific

_STATUS = {
    400: "Gemini rejected the request (bad API key or malformed request)",
    401: "the Gemini API key was refused",
    403: "the Gemini API key was refused",
    404: "model '{model}' does not exist or is not available to this key -- "
         "check the model name in Settings",
    429: "Gemini free-tier quota exhausted or rate-limited (free tier is "
         "~15 requests/min and a few hundred per day) -- wait and try again",
    500: "Gemini had a server error -- try again later",
    503: "Gemini had a server error -- try again later",
}


class GeminiError(Exception):
    """A Gemini call that produced no usable answer, with a message for the user."""


class GeminiAuthError(GeminiError):
    """The API key was refused (401/403/400)."""


class GeminiQuotaError(GeminiError):
    """Rate-limited or out of quota, and the retries did not clear it."""


class GeminiModelError(GeminiError):
    """The model name does not exist or is not available to this key."""


def _map_status(code: int, model: str) -> str:
    return _STATUS.get(code, f"HTTP {code}").format(model=model)


def _default_transport(method: str, url: str, headers: dict, body: bytes | None,
                       timeout: float):
    """urllib transport: raise-free, returns (status, body bytes)."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise GeminiError(f"could not reach the Gemini API ({exc.reason})") from exc
    except TimeoutError as exc:
        raise GeminiError("the Gemini API timed out -- try again later") from exc


class Gemini:
    def __init__(self, api_key: str, model: str, *, transport=None, timeout=60.0,
                 log: Callable[[str], None] = lambda m: None,
                 sleep: Callable[[float], None] = time.sleep,
                 usage: "Usage | None" = None) -> None:
        if not api_key:
            raise GeminiError("no Gemini API key is set")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.log = log
        self.sleep = sleep
        self.usage = usage
        self.requests_made = 0
        self._transport = transport or (lambda m, u, h, b: _default_transport(
            m, u, h, b, timeout))

    def _headers(self) -> dict:
        # The key goes in a header, never in the URL, so it cannot leak into
        # logs or proxy caches.
        return {"x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT}

    def _call(self, url: str, body: dict | None) -> dict:
        """One request, mapped to the right GeminiError on a hard failure."""
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        if payload is not None and len(payload) > MAX_BODY:
            raise GeminiError("the AI reading request is too large (over ~19 MB); "
                              "reduce the batch size in Settings")
        for attempt in range(len(RETRY_WAITS) + 1):
            code, raw = self._transport("POST" if body is not None else "GET",
                                        url, self._headers(), payload)
            self._log_request()
            if code in (401, 403):
                raise GeminiAuthError(f"Gemini: {_map_status(code, self.model)}")
            if code == 404:
                raise GeminiModelError(f"Gemini: {_map_status(code, self.model)}")
            if code in (429, 500, 503):
                if attempt < len(RETRY_WAITS):
                    wait = RETRY_WAITS[attempt]
                    self.log(f"  Gemini rate-limited, retrying in {wait:.0f}s")
                    self.sleep(wait)
                    continue
                if code == 429:
                    raise GeminiQuotaError(f"Gemini: {_map_status(code, self.model)}")
                raise GeminiError(f"Gemini: {_map_status(code, self.model)}")
            if code == 400:
                raise GeminiAuthError(f"Gemini: {_map_status(code, self.model)}")
            if code != 200:
                raise GeminiError(f"Gemini: {_map_status(code, self.model)}")
            try:
                return json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise GeminiError(f"Gemini returned an unreadable response ({exc})") from exc
        raise GeminiError("Gemini request failed without a response")  # unreachable

    def _log_request(self) -> None:
        self.requests_made += 1
        if self.usage is not None:
            self.usage.add(1)

    def generate_json(self, prompt: str, images: list[bytes], schema: dict) -> object:
        """Post one batched prompt and parse the model's JSON answer."""
        parts: list[dict] = [{"text": prompt}]
        for i, data in enumerate(images, 1):
            parts.append({"text": f"Image {i}"})
            parts.append({"inline_data": {
                "mime_type": "image/jpeg", "data": base64.b64encode(data).decode("ascii"),
            }})
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0,
            },
        }
        data = self._call(API.format(model=self.model), body)
        return _extract_text(data, self.model)

    def check(self) -> str:
        """The model's displayName (or its id), for the settings self-test."""
        data = self._call(MODEL_URL.format(model=self.model), None)
        name = data.get("displayName") or data.get("name") or self.model
        return str(name)


def _extract_text(data: dict, model: str) -> object:
    """candidates[0].content.parts[0].text as parsed JSON, with clear failures."""
    feedback = data.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise GeminiError(f"Gemini refused to answer the request "
                          f"({feedback['blockReason']})")
    candidates = data.get("candidates") or []
    if not candidates:
        raise GeminiError("Gemini returned no answer (the prompt may have been "
                          "blocked) -- try again")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    if not parts or not parts[0].get("text"):
        raise GeminiError("Gemini returned an empty answer -- try again")
    try:
        return json.loads(parts[0]["text"])
    except ValueError as exc:
        raise GeminiError(f"Gemini returned malformed JSON ({exc})") from exc


class Usage:
    """Daily request counter, persisted beside the config file.

    Google resets the free-tier quota at midnight Pacific, so the day is
    computed in America/Los_Angeles. Best-effort IO: a read or write failure
    never raises -- a broken counter must not kill a scan.
    """

    def __init__(self, path: Path | None = None, *,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.path = path or (CONFIG_DIR / "gemini_usage.json")
        self._clock = clock or (lambda: datetime.now(PACIFIC))
        self._today = ""
        self._count = 0
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
            day = str(raw.get("day", ""))
            count = int(raw.get("count", 0))
            if day and count >= 0:
                self._today, self._count = day, count
        except (OSError, ValueError, TypeError):
            pass

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"day": self._today, "count": self._count}))
            tmp.replace(self.path)
        except OSError:
            pass

    def add(self, n: int = 1) -> None:
        now = self._clock().date().isoformat()
        if now != self._today:
            self._today, self._count = now, 0
        self._count += n
        if self._count < 0:
            self._count = 0
        self._save()

    def today(self) -> int:
        now = self._clock().date().isoformat()
        if now != self._today:
            self._today, self._count = now, 0
        return self._count
