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


# ---------- Telegram command scanner ----------

_HANDLER_DEF_RE = re.compile(r"^def (cmd_\w+)\s*\(", re.MULTILINE)
_HANDLERS_DICT_RE = re.compile(
    r"HANDLERS\s*=\s*\{(.*?)\n\}", re.DOTALL
)
_HANDLERS_KEY_RE = re.compile(r'["\']([^"\']+)["\']\s*:')
_MENU_CMD_RE = re.compile(r'["\']command["\']\s*:\s*["\']([^"\']+)["\']')
_HELP_MENTION_RE = re.compile(r"/([a-z_][a-z0-9_]*)")


def scan_telegram_commands(telegram_bot_path: Path) -> dict[str, Any]:
    """Scan cli/telegram_bot.py for command handlers and registrations.

    Returns:
        {
            "handlers": [{"name": "cmd_X", "line": N}, ...],
            "handlers_dict_keys": ["/cmd", "cmd", ...],
            "menu_commands": ["cmd", ...],  # entries in _set_telegram_commands
            "help_mentions": ["cmd", ...],  # commands mentioned in cmd_help
            "guide_mentions": ["cmd", ...],  # commands mentioned in cmd_guide
        }
    """
    empty = {
        "handlers": [],
        "handlers_dict_keys": [],
        "menu_commands": [],
        "help_mentions": [],
        "guide_mentions": [],
    }
    if not telegram_bot_path.exists():
        return empty

    try:
        source = telegram_bot_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return empty

    # Handlers: def cmd_X(...)
    handlers = [
        {"name": m.group(1), "line": source[: m.start()].count("\n") + 1}
        for m in _HANDLER_DEF_RE.finditer(source)
    ]

    # HANDLERS dict keys
    handlers_dict_keys: list[str] = []
    dict_match = _HANDLERS_DICT_RE.search(source)
    if dict_match:
        handlers_dict_keys = _HANDLERS_KEY_RE.findall(dict_match.group(1))

    # _set_telegram_commands() menu entries — find the function and extract menu
    menu_commands: list[str] = []
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_set_telegram_commands":
                body_text = ast.unparse(node)
                menu_commands = _MENU_CMD_RE.findall(body_text)
                break
    except SyntaxError:
        pass

    help_mentions = _extract_help_mentions(source, "cmd_help")
    guide_mentions = _extract_help_mentions(source, "cmd_guide")

    return {
        "handlers": handlers,
        "handlers_dict_keys": handlers_dict_keys,
        "menu_commands": menu_commands,
        "help_mentions": help_mentions,
        "guide_mentions": guide_mentions,
    }


def _extract_help_mentions(source: str, func_name: str) -> list[str]:
    """Find all /cmd mentions inside a named function body."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            body_text = ast.unparse(node)
            return list(set(_HELP_MENTION_RE.findall(body_text)))
    return []
