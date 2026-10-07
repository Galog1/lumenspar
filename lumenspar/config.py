"""User settings, persisted to XDG config."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from typing import Any

APP = "lumenspar"

CATEGORIES: tuple[str, ...] = ("artifacts", "weapons", "characters", "materials")


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / APP
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / APP
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass(slots=True)
class Delays:
    """Pacing between UI actions, in seconds.

    Genshin animates panel transitions and lazily loads item icons; reading a
    frame too early yields a half-drawn tile. Every wait is scaled by
    `Settings.delay_scale` so a user on slower hardware can slow the whole
    scan with one control instead of tuning each value.
    """

    after_key: float = 0.25
    after_click: float = 0.18
    panel_open: float = 0.90
    page_scroll: float = 0.55
    settle: float = 0.12


@dataclass(slots=True)
class Settings:
    # what to scan
    categories: list[str] = field(default_factory=lambda: ["artifacts"])
    min_artifact_rarity: int = 4
    min_weapon_rarity: int = 3

    # pacing
    delay_scale: float = 1.0
    delays: Delays = field(default_factory=Delays)

    # output
    export_dir: str = str(Path.home() / "Documents" / "Lumenspar")
    export_name: str = "lumenspar.good.json"

    # game controls (must mirror the in-game keybinds)
    key_inventory: str = "b"
    key_character: str = "c"
    key_escape: str = "escape"
    # Genshin binds these to previous/next inventory tab.
    key_tab_left: str = "q"
    key_tab_right: str = "e"
    # W/S move the left-hand menu on the character screen.
    key_menu_up: str = "w"
    key_menu_down: str = "s"

    # The Traveler is the one character whose displayed name the player picks,
    # so it can never be matched from the shipped vocabulary. GOOD expects the
    # location "Traveler" regardless of what the game shows.
    traveler_name: str = ""
    # The Wanderer can be renamed in-game too, after which it reads back as
    # whatever the player chose. Blank means it still shows as "Wanderer".
    wanderer_name: str = ""
    # Other characters whose displayed name the player chose (Manekins),
    # comma-separated. They can't be keyed in GOOD, but knowing their names
    # lets a read that is one glyph away from the Traveler's or Wanderer's be
    # refused instead of misassigned.
    other_names: str = ""

    # Enka.Network character import: the player's UID, whose profile
    # showcase is read. Optional -- blank means characters come only from
    # the screen scan.
    uid: str = ""

    # capture
    restore_token: str = ""
    capture_backend: str = "portal"   # portal | x11
    inject_backend: str = "auto"      # auto | portal | ydotool | none

    # ocr
    ocr_lang: str = "eng"
    min_match_score: float = 78.0     # rapidfuzz score below which a read is rejected

    # reading: "local" reads every panel with Tesseract, "ai" reads the text
    # with Google's Gemini vision model (batched) and keeps the pixel-derived
    # facts -- rarity, locked, elixir, refinement badge, constellation.
    reader_mode: str = "local"        # local | ai
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    ai_batch_size: int = 6            # panels per Gemini request

    def wait(self, name: str) -> float:
        return getattr(self.delays, name) * max(0.1, self.delay_scale)

    @property
    def export_path(self) -> Path:
        return Path(self.export_dir).expanduser() / self.export_name

    def gemini_key(self) -> str:
        """The Gemini API key: the LUMENSPAR_GEMINI_KEY env var wins over settings."""
        return os.environ.get("LUMENSPAR_GEMINI_KEY") or self.gemini_api_key

    # -- persistence -----------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or CONFIG_PATH
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in raw.items() if k in known}
        if isinstance(data.get("delays"), dict):
            dk = {f.name for f in fields(Delays)}
            data["delays"] = Delays(**{k: v for k, v in data["delays"].items() if k in dk})
        # Drop unknown category names rather than letting them reach the scanner.
        if "categories" in data:
            data["categories"] = [c for c in data["categories"] if c in CATEGORIES]
        return cls(**data)

    def save(self, path: Path | None = None) -> Path:
        path = path or CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        tmp.replace(path)  # atomic: never leave a truncated config behind
        try:
            os.chmod(path, 0o600)   # the file may now hold an API key
        except OSError:
            pass                    # best effort; never break a save
        return path
