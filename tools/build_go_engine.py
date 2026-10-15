#!/usr/bin/env python3
"""Bundle Genshin Optimizer's formula engine for Lumenspar's damage calculator.

Genshin Optimizer (MIT, https://github.com/frzyc/genshin-optimizer) models
every character's talents, passives and constellations, every weapon passive,
artifact set and elemental resonance, with their conditionals. Lumenspar
bundles the engine behind genshin-optimizer.com itself, "WR" (libs/gi/wr,
libs/gi/sheets, libs/gi/uidata), into one JavaScript file and runs it in Qt's
QJSEngine, which PySide6 already ships, instead of re-implementing it.

The sheets are written for a React UI, so the UI-only modules (React, MUI,
icons, images, i18n) are replaced by a generated inert stub whose JSX returns
plain label objects ({ns, key, values} or {children}) that Lumenspar resolves
against go_locale.json.

Outputs (committed, so neither the app nor its release builds need Node.js):
  lumenspar/gamedata/go_engine.js     the engine, polyfills first
  lumenspar/gamedata/go_labels.json   English names for formulas/conditionals
  lumenspar/gamedata/go_locale.json   GO's English locale namespaces, for labels
  lumenspar/gamedata/GO_LICENSE.txt   Genshin Optimizer's licence

Bundling needs Node.js: a local `node`/`npm` is used when present, otherwise
the build runs in a throwaway Podman container (Fedora toolbox image), so
nothing is installed on the host.

QJSEngine is an ES2017 engine with two quirks the bundle has to survive, both
handled here: missing built-ins and a broken Object.keys over Proxies (see
tools/go_engine/polyfills.js), and a function with two destructured
parameters reading the first from the second argument (worked around by
Babel's parameters transform, which moves destructuring into the body).

Usage: tools/build_go_engine.py [--commit SHA] [--work DIR]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent / "go_engine"
OUT = ROOT / "lumenspar" / "gamedata"
GO_REPO = "https://github.com/frzyc/genshin-optimizer.git"
GO_COMMIT = "05c370688e1acb500e7eb92e1c737d48150ab595"   # 2026-10-10
CONTAINER = "registry.fedoraproject.org/fedora-toolbox:44"

SPARSE = ["/LICENSE", "/tsconfig.base.json", "/package.json", "/libs/"]
STUBBED = ["react", "react/jsx-runtime", "react-dom", "@mui/material", "@mui/icons-material",
           "@mui/material/styles", "i18next", "react-i18next", "@genshin-optimizer/common/ui",
           "@genshin-optimizer/gi/svgicons", "@genshin-optimizer/common/svgicons",
           "@genshin-optimizer/gi/assets", "@genshin-optimizer/gi/i18n"]
NPM = ["esbuild", "zod", "fflate", "@babel/core", "@babel/cli",
       "@babel/plugin-transform-parameters"]

BUILD_SH = r"""
set -e
mkdir -p /tmp/deps && cd /tmp/deps
npm init -y >/dev/null
npm install --silent --no-audit --no-fund {npm} >/dev/null
ln -sfn /tmp/deps/node_modules /repo/node_modules
cd /repo
A=""
for m in {stubbed}; do A="$A --alias:$m=./lumenspar_stub.js"; done
/tmp/deps/node_modules/.bin/esbuild lumenspar_entry.ts --bundle --format=iife \
  --platform=neutral --main-fields=module,main --target=es2016 \
  --tsconfig=tsconfig.base.json '--define:process.env.NODE_ENV="production"' --jsx=automatic $A \
  --loader:.png=empty --loader:.svg=empty --loader:.webp=empty --loader:.gif=empty --loader:.jpg=empty \
  --outfile=/repo/go_esbuild.js --log-level=warning
/tmp/deps/node_modules/.bin/babel go_esbuild.js --config-file /repo/lumenspar_babel.json \
  -o /repo/go_bundle.js
rm -f /repo/node_modules
"""

# Textual patches to the bundle (Babel's compact output): (reason, old, new,
# expected count). A patch that stops matching fails the build loudly. WR needs
# none: its level tables already reach 100 and it does not use Function.toString.
PATCHES: list[tuple[str, str, str, int]] = []


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def checkout(work: Path, commit: str) -> Path:
    repo = work / "genshin-optimizer"
    if not repo.exists():
        run(["git", "clone", "--quiet", "--filter=blob:none", "--sparse", "--no-checkout",
             GO_REPO, str(repo)])
    run(["git", "-C", str(repo), "sparse-checkout", "set", "--no-cone", *SPARSE])
    run(["git", "-C", str(repo), "fetch", "--quiet", "--depth", "1", "origin", commit])
    run(["git", "-C", str(repo), "checkout", "--quiet", commit])
    return repo


def write_stub(repo: Path) -> None:
    """Generate the inert stub for UI-only modules: it must export every name
    the sources import from them, or esbuild fails on the missing export."""
    imp = re.compile(r"import\s+(?:type\s+)?(?:(\w+)\s*,?\s*)?(?:\{([^}]*)\})?\s*from\s*'([^']+)'", re.S)
    names = {"jsx", "jsxs", "Fragment"}
    for f in [*(repo / "libs").rglob("*.ts"), *(repo / "libs").rglob("*.tsx")]:
        for _, named, mod in imp.findall(f.read_text(encoding="utf-8", errors="ignore")):
            if mod in STUBBED or mod.startswith("@mui/"):
                for n in (named or "").split(","):
                    n = re.sub(r"^\s*type\s+", "", n.strip()).split(" as ")[0].strip()
                    if re.fullmatch(r"[A-Za-z_$][\w$]*", n):
                        names.add(n)
    names -= {"jsx", "jsxs", "default"}
    lines = [
        "// Inert stand-in for UI-only modules (React, MUI, icons, images, i18n).",
        "const handler = { get(t, k) { if (k === Symbol.toPrimitive || k === 'toString') "
        "return () => ''; return stub },",
        "  apply() { return null }, construct() { return {} } }",
        "const stub = new Proxy(function () { return null }, handler)",
        "// JSX elements become plain label objects: <Translate ns key18 values/> -> "
        "{ns, key, values};",
        "// anything else keeps its children so Lumenspar can join the text.",
        "function label(type, props) {",
        "  props = props || {}",
        "  if (props.key18 !== undefined) return { ns: props.ns, key: props.key18, "
        "values: props.values }",
        "  return { children: props.children }",
        "}",
        "export const jsx = label",
        "export const jsxs = label",
        *(f"export const {n} = stub" for n in sorted(names)),
        "export default stub",
    ]
    (repo / "lumenspar_stub.js").write_text("\n".join(lines) + "\n", encoding="utf-8")


def bundle(repo: Path) -> str:
    write_stub(repo)
    shutil.copy(HERE / "entry.ts", repo / "lumenspar_entry.ts")
    (repo / "lumenspar_babel.json").write_text(json.dumps(
        {"plugins": ["@babel/plugin-transform-parameters"], "comments": False}),
        encoding="utf-8")
    script = BUILD_SH.format(npm=" ".join(NPM), stubbed=" ".join(STUBBED))
    if shutil.which("node") and shutil.which("npm"):
        # Local Node: same steps, with /repo pointing at the checkout.
        script = script.replace("/repo", str(repo))
        run(["bash", "-c", script])
    elif shutil.which("podman"):
        run(["podman", "run", "--rm", "-v", f"{repo}:/repo:Z", "-w", "/repo", CONTAINER,
             "bash", "-c", "dnf -y -q install nodejs-npm >/dev/null 2>&1\n" + script])
    else:
        sys.exit("Needs Node.js (node + npm) or Podman to bundle the engine.")
    js = (repo / "go_bundle.js").read_text(encoding="utf-8")
    for reason, old, new, count in PATCHES:
        found = js.count(old)
        if found != count:
            sys.exit(f"patch no longer applies ({found} matches, expected {count}): {reason}")
        js = js.replace(old, new)
    return js


def labels(repo: Path) -> dict:
    """English labels Lumenspar shows: GO's conditional/formula names and the
    game's talent hit names, passive and constellation names, set effects."""
    loc = repo / "libs/gi/localization/assets/locales/en"
    dm = repo / "libs/gi/dm-localization/assets/locales/en"
    out: dict = {"go": {}, "game": {}}
    for f in sorted(loc.glob("*.json")):
        m = re.fullmatch(r"(char|weapon|artifact)_(.+)", f.stem)
        if m:
            out["go"][m.group(2)] = json.loads(f.read_text(encoding="utf-8"))
    for f in sorted(dm.glob("*_gen.json")):
        m = re.fullmatch(r"(char|weapon|artifact)_(.+)_gen", f.stem)
        if not m:
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        kind, key = m.groups()
        keep: dict = {"kind": kind, "name": d.get("name") or d.get("setName", "")}
        if kind == "char":
            for t in ("auto", "skill", "burst"):
                v = d.get(t) or {}
                keep[t] = {"name": v.get("name", ""),
                           "params": {k: s for k, s in (v.get("skillParams") or {}).items() if s}}
            for n in ("passive1", "passive2", "passive3", "passive4"):
                if d.get(n):
                    keep[n] = {"name": d[n].get("name", ""), "text": _text(d[n].get("description"))}
            for c in range(1, 7):
                v = d.get(f"constellation{c}")
                if v:
                    keep[f"c{c}"] = {"name": v.get("name", ""), "text": _text(v.get("description"))}
        elif kind == "weapon":
            keep["passive"] = d.get("passiveName", "")
            desc = d.get("passiveDescription") or {}
            keep["passiveText"] = _text(desc.get("0") if isinstance(desc, dict) else desc)
        else:
            effects = d.get("setEffects") or {}
            keep["effects"] = {k: _text(v) for k, v in effects.items()}
        out["game"][key] = keep
    return out


def _text(v) -> str:
    """Datamine rich text (dict of paragraphs with tags) as plain text."""
    if isinstance(v, dict):
        v = " ".join(str(x) for _, x in sorted(v.items(), key=lambda kv: int(kv[0])
                                                if str(kv[0]).isdigit() else 0))
    v = re.sub(r"<br/?>", " ", str(v or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", v)).strip()


def locale(repo: Path) -> dict:
    """Every English locale namespace (file stem -> parsed JSON), which the
    label objects emitted by the stub refer to."""
    out: dict = {}
    for d in ("libs/gi/localization/assets/locales/en", "libs/gi/dm-localization/assets/locales/en"):
        for f in sorted((repo / d).glob("*.json")):
            out[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--commit", default=GO_COMMIT, help="Genshin Optimizer commit to bundle")
    ap.add_argument("--work", type=Path, help="reuse this work directory (default: temporary)")
    args = ap.parse_args()

    work = args.work or Path(tempfile.mkdtemp(prefix="lumenspar-go-"))
    work.mkdir(parents=True, exist_ok=True)
    repo = checkout(work, args.commit)
    js = bundle(repo)
    polyfills = (HERE / "polyfills.js").read_text(encoding="utf-8")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    header = (f"// Genshin Optimizer formula engine, commit {args.commit}, bundled {stamp}\n"
              f"// by tools/build_go_engine.py. MIT License: see GO_LICENSE.txt.\n")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "go_engine.js").write_text(header + polyfills + "\n" + js, encoding="utf-8")
    (OUT / "go_labels.json").write_text(
        json.dumps({"commit": args.commit, **labels(repo)}, ensure_ascii=False,
                   separators=(",", ":")), encoding="utf-8")
    (OUT / "go_locale.json").write_text(
        json.dumps(locale(repo), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    shutil.copy(repo / "LICENSE", OUT / "GO_LICENSE.txt")
    for f in ("go_engine.js", "go_labels.json", "go_locale.json", "GO_LICENSE.txt"):
        print(f"wrote {OUT / f} ({(OUT / f).stat().st_size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
