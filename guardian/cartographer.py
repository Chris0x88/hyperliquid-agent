"""Guardian cartographer — scans the repo and builds a wiring inventory.

Pure stdlib. Fast (<5s on the current repo). Outputs:
- state/inventory.json — structured wiring
- state/map.mmd — Mermaid graph
- state/map.md — markdown wrapper with summary stats
"""
from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any


# ---------- Kill switch ----------

def is_enabled() -> bool:
    """Global cartographer kill switch."""
    return os.environ.get("GUARDIAN_CARTOGRAPHER_ENABLED", "1") != "0"


# ---------- Python import scanner ----------

def scan_python_imports(root: Path) -> dict[str, Any]:
    """Walk `root` recursively and build an import graph of .py files.

    Returns a dict with two keys:
    - modules: list of {name, path, size, docstring}
    - edges: list of {from, to, kind} where kind in {"import", "from-import"}
    """
    modules: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for py_file in sorted(root.rglob("*.py")):
        rel = py_file.relative_to(root)
        module_name = rel.with_suffix("").as_posix().replace("/", ".")
        # For flat fixture repos, strip to the stem
        if "." not in module_name:
            pass
        else:
            module_name = module_name.split(".")[-1]

        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        docstring = ast.get_docstring(tree) or ""
        modules.append({
            "name": module_name,
            "path": rel.as_posix(),
            "size": len(source),
            "docstring": docstring.split("\n")[0][:200],
        })

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    edges.append({
                        "from": module_name,
                        "to": alias.name.split(".")[0],
                        "kind": "import",
                    })
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    edges.append({
                        "from": module_name,
                        "to": node.module.split(".")[0],
                        "kind": "from-import",
                    })

    return {"modules": modules, "edges": edges}
