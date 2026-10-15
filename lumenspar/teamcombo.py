"""Akasha's combo, found again among Lumenspar's damage rows.

Akasha ranks a character by the damage of a fixed combo; its breakdown names
each hit and how often it lands. These helpers find the same hits among
Lumenspar's damage rows so the combo can be recomputed for the player's own
team (and optimized for).
"""

from __future__ import annotations

import math
import re

_DROP = {"dmg", "avg", "the", "of", ""}
_WEIGHT = 0.15


def parse_name(name: str) -> tuple[str, float]:
    """(hit text, factor): "Lunar-Charged DMG (60%)" -> ("Lunar-Charged", 0.6)."""
    factor = 1.0
    m = re.search(r"\(\s*(\d+(?:\.\d+)?)\s*%\s*\)", name)
    if m:
        factor = float(m.group(1)) / 100
        name = name[:m.start()] + name[m.end():]
    text = name.strip()
    while True:
        new = re.sub(r"\s*\b(?:avg\s+dmg|dmg|avg)\s*$", "", text, flags=re.I).strip()
        if new == text:
            break
        text = new
    text = re.sub(r"\bNormal Attack (\d+)\b", r"\1-Hit", text, flags=re.I)
    return text.strip(), factor


def tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t not in _DROP}


def match(hits: list, rows: list[dict]) -> dict:
    """Pair each hit with the most similar damage row (by words, then by size)."""
    out: list[dict] = []
    row_tokens = [tokens(r.get("label") or "") for r in rows]
    for hit in hits:
        text, factor = parse_name(hit.name)
        a = tokens(text)
        best = None
        best_score = -math.inf
        for row, b in zip(rows, row_tokens):
            avg = row.get("avg")
            if not isinstance(avg, (int, float)) or avg <= 0:
                continue
            union = a | b
            sim = len(a & b) / len(union) if union else 0.0
            if sim == 0:
                continue
            score = sim - _WEIGHT * abs(math.log(avg / hit.value)) if hit.value > 0 else sim
            if score > best_score:
                best, best_score = row, score
        value = best["avg"] * factor if best else None
        out.append({"name": hit.name, "quantity": hit.quantity, "factor": factor,
                    "key": best["key"] if best else None,
                    "label": best.get("label") if best else None,
                    "group": best.get("group") if best else None,
                    "value": value,
                    "total": value * hit.quantity if value is not None else None})
    matched = [h for h in out if h["key"] is not None]
    return {"hits": out, "total": sum(h["total"] for h in matched),
            "matched": len(matched), "missing": len(out) - len(matched)}


def frames(matched: dict) -> list[dict]:
    """Engine target frames for the matched hits; repeated rows add up."""
    merged: dict[str, float] = {}
    for h in matched["hits"]:
        if h["key"] is not None:
            merged[h["key"]] = merged.get(h["key"], 0.0) + h["quantity"] * h["factor"]
    return [{"id": k, "multiplier": m} for k, m in merged.items()]
