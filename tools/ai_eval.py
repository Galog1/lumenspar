#!/usr/bin/env python3
"""Offline evaluation of the AI reader over saved calibration screenshots.

Usage:
    python3 tools/ai_eval.py --kind artifacts calib/Artifacts/*.png
    python3 tools/ai_eval.py --kind weapons calib/Weapons/*.png [--model ...] [--batch N]

Each PNG is fed to the Gemini reader for the requested kind and then through
the same build_* validation the scanner runs; a refused item prints the set
name, level, substats and why it was refused. Pixel-derived facts (rarity,
locked, elixir, refinement badge) come from the existing pixel readers, so a
wrong answer here means the model misread text, not that a fact stopped
coming from pixels.

Requires a validated API key: it is read via Settings.load().gemini_key()
(settings or the LUMENSPAR_GEMINI_KEY env var). It makes real network calls.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lumenspar.ai.gemini import (Gemini, GeminiError,  # noqa: E402
                                 GeminiQuotaError, Usage)
from lumenspar.config import Settings  # noqa: E402

KINDS = ("artifacts", "weapons")


def load_bgr(path: Path) -> np.ndarray:
    """PNG -> BGR uint8 frame, the channel order live captures arrive in."""
    return np.ascontiguousarray(np.asarray(
        Image.open(path).convert("RGB"))[:, :, ::-1])


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate the AI reader on "
                                             "saved screenshots")
    ap.add_argument("--kind", choices=KINDS, required=True)
    ap.add_argument("paths", nargs="+", type=Path,
                    help="PNG screenshots to read")
    ap.add_argument("--model", default=None,
                    help="Gemini model id (default: settings gemini_model)")
    ap.add_argument("--batch", type=int, default=None,
                    help="panels per request (default: settings ai_batch_size)")
    args = ap.parse_args()

    s = Settings.load()
    key = s.gemini_key()
    if not key:
        sys.exit("no Gemini API key: set gemini_api_key in Settings or "
                 "export LUMENSPAR_GEMINI_KEY")
    gemini = Gemini(key, args.model or s.gemini_model, usage=Usage())
    batch = args.batch or s.ai_batch_size

    frames = [load_bgr(p) for p in args.paths]
    print(f"{args.kind}: {len(frames)} panel(s), batch {batch}, "
          f"model {gemini.model}")

    if args.kind == "artifacts":
        from lumenspar.ai.reader import read_artifacts
        from lumenspar.scan.artifact_parse import build_artifact
        for i in range(0, len(frames), batch):
            chunk = frames[i:i + batch]
            try:
                panels = read_artifacts(gemini, chunk)
            except GeminiError as exc:
                for p in args.paths[i:i + batch]:
                    print(f"  {p.name}: Gemini error: {exc}")
                if isinstance(exc, GeminiQuotaError):
                    break
                continue
            for path, panel in zip(args.paths[i:i + batch], panels):
                if panel is None:
                    print(f"  {path.name}: panel could not be segmented")
                    continue
                res = build_artifact(
                    panel, min_score=s.min_match_score,
                    traveler_name=s.traveler_name, wanderer_name=s.wanderer_name,
                    other_names=s.other_names)
                if res.ok:
                    a = res.artifact
                    print(f"  {path.name}: {a.setKey}/{a.slotKey} "
                          f"+{a.level} r{a.rarity}"
                          f" ({', '.join(f'{x.key} {x.value:g}' for x in a.substats)})")
                else:
                    print(f"  {path.name}: refused -- {" -- ".join(res.problems)}")
    else:
        from lumenspar.ai.reader import read_weapons
        from lumenspar.scan.weapon_parse import build_weapon
        for i in range(0, len(frames), batch):
            chunk = frames[i:i + batch]
            try:
                panels = read_weapons(gemini, chunk)
            except GeminiError as exc:
                for p in args.paths[i:i + batch]:
                    print(f"  {p.name}: Gemini error: {exc}")
                if isinstance(exc, GeminiQuotaError):
                    break
                continue
            for path, panel in zip(args.paths[i:i + batch], panels):
                if panel is None:
                    print(f"  {path.name}: panel could not be segmented")
                    continue
                weapon, problems = build_weapon(panel, min_score=s.min_match_score)
                if weapon is None:
                    print(f"  {path.name}: refused -- {" -- ".join(problems)}")
                else:
                    print(f"  {path.name}: {weapon.key} Lv.{weapon.level} "
                          f"R{weapon.refinement}")

    print(f"Gemini requests: {gemini.requests_made} "
          f"(today: {gemini.usage.today()})")


if __name__ == "__main__":
    main()
