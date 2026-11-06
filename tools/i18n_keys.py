#!/usr/bin/env python3
"""Interface texts of the computer program: every English text in the code (tr("…") / trp(one, other, …),
found with Python's own parser) and what each dictionary i18n/<code>.json still lacks.

    python3 tools/i18n_keys.py               # report
    python3 tools/i18n_keys.py --list        # the English texts, one JSON string per line
    python3 tools/i18n_keys.py --missing de  # JSON {text: ""} of what de.json lacks (for translators)
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "phonebackup"
I18N = ROOT / "i18n"


def _const(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def keys() -> dict[str, list[str]]:
    """English text → ['tr'] or ['trp', one] (trp is keyed by the plural form)."""
    out: dict[str, list[str]] = {}
    for f in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"), str(f))):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else "")
            if name in ("tr", "N_") and node.args and _const(node.args[0]) is not None:
                out.setdefault(_const(node.args[0]), ["tr"])
            elif name == "trp" and len(node.args) >= 2 and _const(node.args[1]) is not None:
                out.setdefault(_const(node.args[1]), ["trp", _const(node.args[0]) or ""])
    return out


def dictionaries() -> dict[str, dict]:
    return {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(I18N.glob("*.json"))}


def main(argv: list[str]) -> int:
    k = keys()
    if "--list" in argv:
        for t in k:
            print(json.dumps(t, ensure_ascii=False))
        return 0
    if "--missing" in argv:
        code = argv[argv.index("--missing") + 1]
        texts = dictionaries()[code]["texts"]
        print(json.dumps({t: "" for t in k if t not in texts}, ensure_ascii=False, indent=1))
        return 0
    print(f"{len(k)} texts")
    for code, d in dictionaries().items():
        missing = [t for t in k if t not in d["texts"]]
        print(f"  {code}: {len(missing)} missing")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
