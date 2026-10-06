#!/usr/bin/env python3
"""Regenerate Lumenspar's game data lists.

Run after every Genshin patch:

    python3 tools/update_gamedata.py

Two independent sources are joined and cross-checked:

* **Genshin Optimizer consts** -- the canonical GOOD key vocabulary. An export
  whose keys disagree with these is silently rejected on import, so GO is
  treated as the source of truth for keys.
* **Project Amber** -- English display names plus rarity/element/weapon-type
  metadata, which is what OCR actually reads off the screen.

Any name whose derived key is absent from GO's list is reported rather than
written, so a patch that introduces an odd name fails loudly instead of
producing an export that silently drops items.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "lumenspar" / "gamedata"

GO_BASE = (
    "https://raw.githubusercontent.com/frzyc/genshin-optimizer/master/libs/gi/consts/src"
)
AMBER_BASE = "https://gi.yatta.moe/api/v2/en"
GO_ARTIFACT_STATS = (
    "https://raw.githubusercontent.com/frzyc/genshin-optimizer/master"
    "/libs/gi/stats/Data/Artifacts"
)

ELEMENTS = {
    "Ice": "cryo", "Wind": "anemo", "Rock": "geo", "Electric": "electro",
    "Water": "hydro", "Fire": "pyro", "Grass": "dendro",
}
WEAPON_TYPES = {
    "WEAPON_SWORD_ONE_HAND": "sword", "WEAPON_CLAYMORE": "claymore",
    "WEAPON_POLE": "polearm", "WEAPON_BOW": "bow", "WEAPON_CATALYST": "catalyst",
}


def to_key(name: str) -> str:
    """Mirror of lumenspar.good.to_key (kept standalone so the tool has no deps)."""
    cleaned = re.sub(r"[^0-9a-zA-Z ]+", "", name)
    return "".join(w[:1].upper() + w[1:] for w in cleaned.split())


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "lumenspar-updater"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


# -- TypeScript const array resolution ----------------------------------


def ts_arrays(src: str) -> dict[str, str]:
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r"export const (\w+)\s*=\s*\[(.*?)\]\s*as const", src, re.S)
    }


def resolve(name: str, arrays: dict[str, str], seen: set[str] | None = None) -> list[str]:
    """Expand a TS const array, following `...spread` references."""
    seen = seen or set()
    if name in seen:
        raise ValueError(f"circular spread through {name}")
    seen.add(name)
    body = arrays[name]
    out: list[str] = []
    for tok in re.findall(r"\.\.\.(\w+)|'([^']*)'|\"([^\"]*)\"", body):
        spread, s1, s2 = tok
        if spread:
            out.extend(resolve(spread, arrays, seen))
        else:
            out.append(s1 or s2)
    return out


def go_keys() -> dict[str, list[str]]:
    art = ts_arrays(fetch(f"{GO_BASE}/artifact.ts"))
    cha = ts_arrays(fetch(f"{GO_BASE}/character.ts"))
    wep = ts_arrays(fetch(f"{GO_BASE}/weapon.ts"))
    return {
        "artifact_sets": resolve("allArtifactSetKeys", art),
        "characters": resolve("allCharacterKeys", cha),
        "travelers": resolve("allTravelerKeys", cha),
        # `location` on artifacts/weapons uses plain "Traveler", never the
        # element-suffixed character keys.
        "locations": resolve("allLocationCharacterKeys", cha),
        "weapons": resolve("allWeaponKeys", wep),
    }


def amber(endpoint: str) -> dict:
    return json.loads(fetch(f"{AMBER_BASE}/{endpoint}"))["data"]["items"]


def decamel(key: str) -> str:
    """Approximate a display name from a GOOD key, for GO-only entries."""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", key).replace("  ", " ").strip()


def artifact_stats() -> dict:
    """Per-roll substat values and per-level main stats, in display units.

    These let the scanner tell a misread number from a real one: a substat is
    a sum of 1-6 of four fixed roll values, and a main stat is fixed outright
    by rarity and level. Percent stats are stored x100 to match how GOOD (and
    the game) write them -- 46.6, not 0.466. The correction table lists the
    handful of totals the game rounds differently from a plain sum.
    """
    def pct(key: str, vals: list[float]) -> list[float]:
        return [round(v * 100, 4) for v in vals] if key.endswith("_") else vals

    sub = json.loads(fetch(f"{GO_ARTIFACT_STATS}/artifact_sub.json"))
    main = json.loads(fetch(f"{GO_ARTIFACT_STATS}/artifact_main.json"))
    corr = json.loads(fetch(f"{GO_ARTIFACT_STATS}/artifact_sub_rolls_correction.json"))
    return {
        "substat_rolls": {r: {k: pct(k, v) for k, v in s.items()} for r, s in sub.items()},
        "main_stats": {r: {k: pct(k, v) for k, v in s.items()} for r, s in main.items()},
        "display_corrections": corr,
    }


def main() -> int:
    print("fetching Genshin Optimizer key vocabulary ...")
    go = go_keys()
    for k, v in go.items():
        print(f"  {k:14} {len(v)}")

    print("fetching Project Amber game data ...")
    avatars, weapons, relics = amber("avatar"), amber("weapon"), amber("reliquary")
    print(f"  avatar {len(avatars)}  weapon {len(weapons)}  reliquary {len(relics)}")

    OUT.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []

    def merge(amber_items, go_list, build, label):
        """Union both sources.

        Everything Amber knows stays in the dictionary even when Genshin
        Optimizer has not caught up, because an item missing from the OCR
        vocabulary does not fail loudly -- it fuzzy-matches to the nearest
        *wrong* entry and quietly corrupts the export. Unknown-to-GO keys are
        merely flagged; GO ignores keys it does not recognise on import.
        """
        go_set = set(go_list)
        out, seen = [], set()
        for raw in amber_items:
            rec = build(raw)
            if rec is None:
                continue
            rec["inGO"] = rec["key"] in go_set
            out.append(rec)
            seen.add(rec["key"])
        for k in sorted(go_set - seen):
            out.append({"key": k, "name": decamel(k), "inGO": True, "inAmber": False})
        new_amber = [r["key"] for r in out if not r.get("inGO", True)]
        go_only = [r["key"] for r in out if r.get("inAmber") is False]
        if new_amber:
            notes.append(f"{label}: {len(new_amber)} newer than GO (kept, flagged): {new_amber[:4]}")
        if go_only:
            notes.append(f"{label}: {len(go_only)} known only to GO (kept): {go_only}")
        out.sort(key=lambda r: r["key"])
        return out

    # Materials have no Genshin Optimizer vocabulary to check against -- the
    # official GOOD schema carries only characters/artifacts/weapons, and zod
    # strips anything else. SEELIE.me is the consumer that reads them, and the
    # community convention (Inventory Kamera) is the same PascalCase key, so
    # names come from Amber alone and are written unverified.
    materials = []
    for m in amber("material").values():
        name = m.get("name") or ""
        if not name:
            continue
        materials.append({
            "key": to_key(name), "name": name,
            "rarity": m.get("rank"), "type": m.get("type"),
        })
    seen_keys = set()
    materials = [m for m in materials
                 if not (m["key"] in seen_keys or seen_keys.add(m["key"]))]
    materials.sort(key=lambda m: m["key"])
    notes.append(f"materials: {len(materials)} names from Amber (no GO list to verify against)")

    chars = merge(
        [a for a in avatars.values()
         if a["name"] != "Traveler" and str(a["id"]) not in ("10000005", "10000007")],
        [k for k in go["characters"] if k not in go["travelers"]],
        lambda a: {
            "key": to_key(a["name"]), "name": a["name"], "rarity": a.get("rank"),
            "element": ELEMENTS.get(a.get("element") or ""),
            "weaponType": WEAPON_TYPES.get(a.get("weaponType") or ""),
        },
        "characters",
    )
    for tk in go["travelers"]:
        chars.append({
            "key": tk, "name": "Traveler", "rarity": 5,
            "element": tk.replace("Traveler", "").lower(),
            "weaponType": "sword", "inGO": True,
        })
    chars.sort(key=lambda c: c["key"])

    weps = merge(
        list(weapons.values()), go["weapons"],
        lambda w: {
            "key": to_key(w["name"]), "name": w["name"], "rarity": w.get("rank"),
            "type": WEAPON_TYPES.get(w.get("type") or ""),
        },
        "weapons",
    )
    sets = merge(
        list(relics.values()), go["artifact_sets"],
        lambda r: {
            "key": to_key(r["name"]), "name": r["name"],
            "rarities": sorted(r.get("levelList") or []),
        },
        "artifact sets",
    )

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for fname, items in (
        ("characters.json", chars),
        ("weapons.json", weps),
        ("artifact_sets.json", sets),
        ("locations.json", sorted(go["locations"])),
        ("materials.json", materials),
    ):
        (OUT / fname).write_text(
            json.dumps({"generated": stamp, "items": items}, indent=2, ensure_ascii=False)
        )
        print(f"  wrote {fname}: {len(items)} entries")

    stats = artifact_stats()
    (OUT / "artifact_stats.json").write_text(
        json.dumps({"generated": stamp, **stats}, indent=2))
    print(f"  wrote artifact_stats.json: rarities {sorted(stats['substat_rolls'])}")

    if notes:
        print("\nsource drift (expected between patches, not an error):")
        for n in notes:
            print("  -", n)
    print("\nall overlapping keys reconciled against Genshin Optimizer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
