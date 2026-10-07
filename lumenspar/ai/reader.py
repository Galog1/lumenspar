"""Prompts, schemas and model-JSON -> text-struct conversion for AI reading.

Each `read_*` takes a list of frames (plus pixel facts) and returns one result
per frame in the same order, issuing exactly one Gemini request per call. The
pixel-derived facts -- rarity, locked, elixir, refinement badge, constellation
-- always come from the existing pure-numpy readers, never from the model.

A wrong entry count from the model is a hard `GeminiError`: the caller then
records every panel in the batch as failed rather than pairing answers with
panels by guesswork.
"""

from __future__ import annotations

import numpy as np

from ..scan.artifact_parse import PanelText
from ..scan.artifacts import analyse_panel, count_stars, is_locked
from ..scan.character_parse import CharacterPanelText
from ..scan.characters import R_HEADER, R_TALENTS, read_constellation
from ..scan.grid import Tile
from ..scan.layout import LayoutError
from ..scan.materials import material_title_region
from ..scan.weapon_parse import WeaponPanelText
from ..scan.weapons import analyse_weapon_panel, is_locked as weapon_locked
from ..scan.weapons import read_refinement_badge
from .gemini import Gemini, GeminiError
from .images import crop, encode_jpeg

# -- prompts ---------------------------------------------------------------

ARTIFACT_PROMPT = """Each image is the detail panel of one Genshin Impact artifact. Transcribe EXACTLY what is printed; never correct, round, infer or translate. Return a JSON array with one object per image, in order. Fields:
- slot: the piece name printed at the top, e.g. 'Flower of Life', 'Plume of Death', 'Sands of Eon', 'Goblet of Eonothem', 'Circlet of Logos'
- main_stat_label: the main stat name, e.g. 'HP', 'ATK', 'CRIT Rate', 'Energy Recharge'
- main_stat_value: the big number with its % if shown, e.g. '46.6%'
- level: the '+N' badge text
- substats: the four or fewer lines beginning with '·', each as printed e.g. 'CRIT DMG+7.8%'
- set_name: the artifact set line printed below the substats, e.g. 'Gladiator's Finale:'
- equipped: the character name after 'Equipped:' or null
If a field is not visible use an empty string."""

WEAPON_PROMPT = """Each image is the detail panel of one Genshin Impact weapon. Transcribe EXACTLY what is printed; never correct, round, infer or translate. Return a JSON array with one object per image, in order. Fields:
- name: the weapon name printed at the top
- level: the 'Lv.' level badge text, e.g. 'Lv. 80/90'
- refinement: the refinement text or badge as printed, e.g. 'Refinement Rank 3'
- equipped: the character name after 'Equipped:' or null
If a field is not visible use an empty string."""

CHARACTER_PROMPT = """Each character is shown as several images: the two images at the character's Attributes screen (the element/name header strip and the right column with the name, level and description) followed by the Talents screen region. Transcribe EXACTLY what is printed; never correct, round, infer or translate. Return a JSON array with one object per character, in order. Fields:
- name: the character's displayed name, exactly as printed
- level: the level text, e.g. 'Level 80/90'
- element: the element in the 'Pyro / Name' header, one of pyro, hydro, anemo, electro, dendro, cryo, geo, or an empty string if not visible
- description: the short italic blurb below the stats, exactly as printed (may be empty)
- talents: three objects in top-to-bottom order, one per row, each {"level": <int>, "highlighted": <bool>} where highlighted means the level number is drawn cyan/blue rather than white
If a field is not visible use an empty string (or null for talents missing a row)."""

MATERIAL_PROMPT = """Each item is shown as two images: the material's name from the detail panel title, and the number printed on its inventory tile. Transcribe EXACTLY what is printed; never correct, round, infer or translate. Return a JSON array with one object per item, in order, with fields:
- name: the material name, as in the panel title
- count: the number on the tile, an integer, or null if no number is visible."""

# -- response schemas ------------------------------------------------------

_STRING = {"type": "STRING"}
_INTEGER = {"type": "INTEGER"}
_BOOLEAN = {"type": "BOOLEAN"}

ARTIFACT_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "slot": _STRING,
            "main_stat_label": _STRING,
            "main_stat_value": _STRING,
            "level": _STRING,
            "substats": {"type": "ARRAY", "items": _STRING},
            "set_name": _STRING,
            "equipped": {**_STRING, "nullable": True},
        },
        "required": ["slot", "main_stat_label", "main_stat_value", "level",
                     "substats", "set_name"],
    },
}

WEAPON_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "name": _STRING,
            "level": _STRING,
            "refinement": _STRING,
            "equipped": {**_STRING, "nullable": True},
        },
        "required": ["name", "level", "refinement"],
    },
}

CHARACTER_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "name": _STRING,
            "level": _STRING,
            "element": _STRING,
            "description": _STRING,
            "talents": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "level": _INTEGER,
                        "highlighted": _BOOLEAN,
                    },
                    "required": ["level", "highlighted"],
                },
            },
        },
        "required": ["name", "level", "element", "description", "talents"],
    },
}

MATERIAL_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "name": _STRING,
            "count": {**_INTEGER, "nullable": True},
        },
        "required": ["name"],
    },
}


def _expect_count(got: list, want: int, what: str) -> None:
    """The model must answer every panel or the whole batch is refused."""
    if len(got) != want:
        raise GeminiError(f"Gemini returned {len(got)} entries for {want} {what}")


def _str(v, default: str = "") -> str:
    return v if isinstance(v, str) else default


LINE_PROMPT = "The image is a short strip of Genshin Impact UI text. Transcribe EXACTLY what is printed, as a single line; never correct, infer or translate. Use an empty string if there is no text."
LINE_SCHEMA = {"type": "OBJECT", "properties": {"text": _STRING}, "required": ["text"]}


def line_reader(gemini: Gemini):
    """A TextReader backed by Gemini, for the few navigation reads (inventory
    header, tab title) that would otherwise need Tesseract. One request each."""
    def read(img: np.ndarray) -> str:
        raw = gemini.generate_json(LINE_PROMPT, [encode_jpeg(img)], LINE_SCHEMA)
        return _str(raw.get("text")) if isinstance(raw, dict) else ""
    return read


def _artifact_panel_box(frame: np.ndarray, L) -> tuple[int, int, int, int]:
    """The whole detail panel: header top to equipped bar, panel width.

    `find_panel` already spans from the top of the frame to the bottom of the
    cream body; raise the top to just above the title text so unrelated screen
    chrome above the panel is not sent to the model.
    """
    wp = L.panel.x1 - L.panel.x0
    top = max(0, L.title.y0 - max(4, int(wp * 0.006)))
    bottom = (L.equipped.y1 + max(4, int(wp * 0.006))
              if L.equipped is not None else L.panel.y1)
    return L.panel.x0, top, L.panel.x1, min(bottom, L.panel.y1)


def read_artifacts(gemini: Gemini, frames: list[np.ndarray]) -> list[PanelText | None]:
    """Read artifact detail panels; one Gemini request for the whole batch.

    Returns a PanelText per frame, or None where the panel could not be
    segmented (index preserved so the caller can still match results to tiles).
    """
    crops: list[bytes] = []
    layouts: list = []
    for frame in frames:
        try:
            L = analyse_panel(frame)
            box = _artifact_panel_box(frame, L)
            crops.append(encode_jpeg(crop(frame, box)))
            layouts.append(L)
        except LayoutError:
            crops.append(b"")
            layouts.append(None)

    results: list[PanelText | None] = [None] * len(frames)
    valid = [i for i, c in enumerate(crops) if c]
    if not valid:
        return results
    batch_crops = [crops[i] for i in valid]

    raw = gemini.generate_json(ARTIFACT_PROMPT, batch_crops, ARTIFACT_SCHEMA)
    if not isinstance(raw, list):
        raise GeminiError("Gemini returned a non-array answer for the artifact batch")
    _expect_count(raw, len(batch_crops), "artifact panels")
    for i, entry in zip(valid, raw):
        L = layouts[i]
        if not isinstance(entry, dict):
            raise GeminiError("Gemini returned a non-object artifact entry")
        results[i] = PanelText(
            slot=_str(entry.get("slot")),
            main_label=_str(entry.get("main_stat_label")),
            main_value=_str(entry.get("main_stat_value")),
            rarity=count_stars(frames[i], L.stars) or 5,
            level=_str(entry.get("level")),
            substats=[s for s in entry.get("substats") or [] if isinstance(s, str)],
            set_line=_str(entry.get("set_name")),
            equipped=entry.get("equipped") if isinstance(entry.get("equipped"), str)
            else None,
            elixir=L.elixir,
            locked=is_locked(frames[i], L),
        )
    return results


def read_weapons(gemini: Gemini, frames: list[np.ndarray]) -> list[WeaponPanelText | None]:
    """Read weapon detail panels; one Gemini request for the whole batch.

    The refinement rank badge is read from pixels when possible and prefers
    the pixel reading over the model's text; `build_weapon`'s
    `parse_refinement` understands "Refinement Rank N".
    """
    crops: list[bytes] = []
    layouts: list = []
    for frame in frames:
        try:
            L = analyse_weapon_panel(frame)
            wp = L.panel.x1 - L.panel.x0
            top = max(0, L.title.y0 - max(4, int(wp * 0.006)))
            bottom = (L.equipped.y1 + max(4, int(wp * 0.006))
                      if L.equipped is not None else L.panel.y1)
            crops.append(encode_jpeg(crop(frame, (L.panel.x0, top, L.panel.x1,
                                                  min(bottom, L.panel.y1)))))
            layouts.append(L)
        except LayoutError:
            crops.append(b"")
            layouts.append(None)

    results: list[WeaponPanelText | None] = [None] * len(frames)
    valid = [i for i, c in enumerate(crops) if c]
    if not valid:
        return results
    batch_crops = [crops[i] for i in valid]

    raw = gemini.generate_json(WEAPON_PROMPT, batch_crops, WEAPON_SCHEMA)
    if not isinstance(raw, list):
        raise GeminiError("Gemini returned a non-array answer for the weapon batch")
    _expect_count(raw, len(batch_crops), "weapon panels")
    for i, entry in zip(valid, raw):
        L = layouts[i]
        if not isinstance(entry, dict):
            raise GeminiError("Gemini returned a non-object weapon entry")
        badge = read_refinement_badge(frames[i], L)
        if badge is not None:
            refinement = f"Refinement Rank {badge}"
        else:
            refinement = _str(entry.get("refinement"))
        results[i] = WeaponPanelText(
            name=_str(entry.get("name")),
            level=_str(entry.get("level")),
            refinement=refinement,
            rarity=count_stars(frames[i], L.stars) or 0,
            equipped=entry.get("equipped") if isinstance(entry.get("equipped"), str)
            else None,
            locked=weapon_locked(frames[i], L),
        )
    return results


def read_characters(gemini: Gemini,
                    pages: list[dict[str, np.ndarray]]  # attributes/constellation/talents
                    ) -> list[CharacterPanelText | None]:
    """Read character screens; one Gemini request for the whole batch.

    Every character contributes three crops: the Attributes right-hand column
    (x 0.70-0.98, y 0.08-0.72) plus the element/name header strip (R_HEADER),
    and the Talents page cropped to R_TALENTS. The constellation is never
    asked of the model: it is counted from pixels via `read_constellation`
    when that page was captured, else None (reported, never guessed as C0).
    """
    crops: list[bytes] = []
    for page in pages:
        attrs = page.get("attributes")
        if attrs is not None:
            crops.append(_char_column(attrs))
            crops.append(_header_strip(attrs))
        if page.get("talents") is not None:
            crops.append(encode_jpeg(_region_crop(page["talents"], R_TALENTS)))

    if not crops:
        return [None] * len(pages)

    raw = gemini.generate_json(CHARACTER_PROMPT, crops, CHARACTER_SCHEMA)
    if not isinstance(raw, list):
        raise GeminiError("Gemini returned a non-array answer for the character batch")
    _expect_count(raw, len(pages), "characters")

    results: list[CharacterPanelText | None] = []
    for page, entry in zip(pages, raw):
        if page.get("attributes") is None or not isinstance(entry, dict):
            results.append(None)
            continue
        talents = entry.get("talents") or []
        slots = ("auto", "skill", "burst")
        tal: dict[str, str] = {}
        boosted: dict[str, bool] = {}
        for slot, t in zip(slots, talents[:3]):
            if isinstance(t, dict) and isinstance(t.get("level"), int):
                tal[slot] = f"Lv. {t['level']}"
                boosted[slot] = bool(t.get("highlighted"))
        constellation = (read_constellation(page["constellation"])
                         if page.get("constellation") is not None else None)
        element = _str(entry.get("element")).lower() or None
        results.append(CharacterPanelText(
            name=_str(entry.get("name")),
            level=_str(entry.get("level")),
            constellation=constellation,
            talents=tal,
            talent_boosted=boosted,
            element=element,
            description=_str(entry.get("description")),
        ))
    return results


def _char_column(frame: np.ndarray) -> bytes:
    """The Attributes screen's right-hand column: name, level, description."""
    h, w = frame.shape[:2]
    box = (int(w * 0.70), int(h * 0.08), int(w * 0.98), int(h * 0.72))
    return encode_jpeg(crop(frame, box))


def _header_strip(frame: np.ndarray) -> bytes:
    """The 'Pyro / Arlecchino' element/name header."""
    return encode_jpeg(_region_crop(frame, R_HEADER))


def _region_crop(frame: np.ndarray, spec) -> np.ndarray:
    h, w = frame.shape[:2]
    a, b, c, d = spec
    return frame[int(h * b):int(h * d), int(w * a):int(w * c)]


def read_materials(gemini: Gemini,
                   items: list[tuple[np.ndarray, Tile, int]]
                   ) -> list[tuple[str, int | None] | None]:
    """Read material name + count; one Gemini request for the whole batch.

    Each item contributes two crops: the detail-panel title (name) and the
    tile's caption strip (count) -- the same strip `read_quantity` uses.
    Returns (name, count) per item, or None where the panel title could not
    be located (index preserved for the caller).
    """
    crops: list[bytes] = []
    ok: list[bool] = []
    for frame, tile, pitch in items:
        try:
            name_box = material_title_region(frame)
            name_crop = encode_jpeg(crop(frame, name_box))
        except LayoutError:
            ok.append(False)
            continue
        ok.append(True)
        crops.append(name_crop)
        crops.append(encode_jpeg(_tile_caption(frame, tile, pitch)))

    results: list[tuple[str, int | None] | None] = [None] * len(items)
    valid = [i for i, good in enumerate(ok) if good]
    if not valid:
        return results
    batch_crops = crops         # pairs, in order, for the valid items only

    raw = gemini.generate_json(MATERIAL_PROMPT, batch_crops, MATERIAL_SCHEMA)
    if not isinstance(raw, list):
        raise GeminiError("Gemini returned a non-array answer for the material batch")
    _expect_count(raw, len(valid), "materials")
    for i, entry in zip(valid, raw):
        if not isinstance(entry, dict):
            raise GeminiError("Gemini returned a non-object material entry")
        count = entry.get("count")
        results[i] = (_str(entry.get("name")),
                      count if isinstance(count, int) else None)
    return results


def _tile_caption(frame: np.ndarray, tile: Tile, pitch_y: int) -> np.ndarray:
    """The tile's caption strip, narrowed to its bright rows like read_quantity."""
    x0, x1 = tile.rect.x0 + 6, tile.rect.x1 - 6
    y0 = tile.rect.y1
    y1 = min(frame.shape[0], y0 + int(pitch_y * 0.30))
    band = frame[y0:y1, x0:x1][:, :, ::-1].astype(int)   # keep read_quantity's rect
    if band.size == 0:
        return frame[y0:y1, x0:x1]
    rows = np.where((band.min(2) > 185).mean(1) > 0.6)[0]
    if len(rows) < 4:
        return frame[y0:y1, x0:x1]
    return frame[y0 + int(rows.min()) : y0 + int(rows.max()) - 1, x0:x1]
