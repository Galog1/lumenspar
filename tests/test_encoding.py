"""Every text file the app reads or writes names its encoding.

Without one, Python uses the system's default: UTF-8 on Linux, but an ANSI
code page (cp1252) on Windows. That silently broke two things on Windows: the
"──" header that starts every failures.txt entry could not be written, so no
failure screenshot was ever saved there; and material names containing "é"
or "—" were read as mojibake and could never match. The bug is invisible on
Linux, so this test checks the source rather than the behaviour.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_METHODS = {"read_text", "write_text"}


def _missing_encoding(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        has_encoding = any(k.arg == "encoding" for k in node.keywords)
        if name in TEXT_METHODS and isinstance(func, ast.Attribute) and not has_encoding:
            bad.append(f"{path.relative_to(ROOT)}:{node.lineno} {name}()")
        if name == "open" and not has_encoding:
            if isinstance(func, ast.Name):            # builtin open(file, mode="r")
                arg = node.args[1] if len(node.args) > 1 else None
                mode = arg.value if isinstance(arg, ast.Constant) else "r"
            else:
                # Path.open("a") takes the mode first; os.open(path, flags) and
                # Image.open(path) take a path, are not text, and are skipped.
                arg = node.args[0] if node.args else None
                mode = arg.value if isinstance(arg, ast.Constant) else None
            if isinstance(mode, str) and "b" not in mode:
                bad.append(f"{path.relative_to(ROOT)}:{node.lineno} open({mode!r})")
    return bad


def test_text_files_always_name_their_encoding():
    bad = []
    for path in sorted((ROOT / "lumenspar").rglob("*.py")) + sorted((ROOT / "tools").glob("*.py")):
        if path.name == "hotkey.py":      # reads /proc on Linux only, ASCII by definition
            continue
        bad += _missing_encoding(path)
    assert not bad, "pass encoding=\"utf-8\":\n" + "\n".join(bad)
