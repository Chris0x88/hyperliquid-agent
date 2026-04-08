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


# ---------- Exclusions ----------

# Directory names to skip entirely when walking the repo. These are vendored
# or generated trees that would otherwise bloat the inventory by orders of
# magnitude and slow the sweep from seconds to minutes.
EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "node_modules",
    "dist",
    "build",
    ".eggs",
    "htmlcov",
    "site-packages",
})


def _iter_py_files(root: Path) -> "list[Path]":
    """Walk `root` recursively yielding .py files, skipping excluded dirs.

    This is faster than rglob + post-filter because os.walk lets us prune
    entire subtrees before descending. On a repo with a .venv containing
    thousands of vendored Python files this is the difference between a
    sub-second scan and a ~40-second one.
    """
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune in-place so os.walk doesn't descend into excluded dirs
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                results.append(Path(dirpath) / name)
    results.sort()
    return results


# ---------- Python import scanner ----------

def scan_python_imports(root: Path) -> dict[str, Any]:
    """Walk `root` recursively and build an import graph of .py files.

    Skips common vendored/generated directories (see EXCLUDED_DIRS).

    Module names are the full dotted path from `root` (e.g. `cli.commands.account`
    for `cli/commands/account.py`) so that imports resolve unambiguously against
    nested packages. Edges are resolved in a second pass: for each raw import
    target, we try the full dotted path first and then progressively shorter
    prefixes until one matches a known module. Unresolved targets (external
    packages like `os`, `json`) are dropped — they add no signal to drift.

    Returns a dict with two keys:
    - modules: list of {name, path, size, docstring}
    - edges: list of {from, to, kind} where kind in {"import", "from-import"}
    """
    modules: list[dict[str, Any]] = []
    raw_imports: list[dict[str, str]] = []

    # ---- Pass 1: collect modules and raw imports ----

    for py_file in _iter_py_files(root):
        rel = py_file.relative_to(root)
        # Full dotted path from repo root. `cli/commands/account.py` → `cli.commands.account`.
        # For a flat fixture repo this stays a single-component name like `a`.
        module_name = rel.with_suffix("").as_posix().replace("/", ".")

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
                    raw_imports.append({
                        "from_module": module_name,
                        "target": alias.name,
                        "kind": "import",
                    })
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    raw_imports.append({
                        "from_module": module_name,
                        "target": node.module,
                        "kind": "from-import",
                    })

    # ---- Pass 2: resolve imports against known modules ----

    known_modules: set[str] = {m["name"] for m in modules}
    # Index by last component so we can also resolve tail-only matches
    # (e.g. `from foo.bar.account import X` matching a module named `account`
    # when the full path isn't present). This is needed for flat fixture repos
    # and for cases where the cartographer missed a module name.
    by_tail: dict[str, list[str]] = {}
    for name in known_modules:
        tail = name.rsplit(".", 1)[-1]
        by_tail.setdefault(tail, []).append(name)

    edges: list[dict[str, Any]] = []
    for imp in raw_imports:
        target = imp["target"]
        resolved = _resolve_import(target, known_modules, by_tail)
        if resolved is None:
            # External package (os, json, requests, etc.) — skip, no signal.
            continue
        edges.append({
            "from": imp["from_module"],
            "to": resolved,
            "kind": imp["kind"],
        })

    return {"modules": modules, "edges": edges}


def _resolve_import(
    target: str,
    known_modules: set[str],
    by_tail: dict[str, list[str]],
) -> str | None:
    """Resolve a raw import target to a known module name, or None if external.

    Strategy (most specific first):
    1. Exact full-path match (e.g. `cli.commands.account` matches a module of
       the same name).
    2. Prefix match — progressively drop tail components (e.g. for
       `from cli.commands.account import X`, if only `cli.commands.account`
       exists as a module, that's matched at step 1; if only `cli.commands`
       exists, that's matched here).
    3. Tail match — if no prefix matches but the last component is a unique
       module stem in the repo (e.g. `from b import foo` in a flat repo with
       a module named `b`), use that. Only matches when there's exactly one
       candidate to avoid false positives on common names like `__init__`.
    """
    if target in known_modules:
        return target

    parts = target.split(".")
    while len(parts) > 1:
        parts.pop()
        candidate = ".".join(parts)
        if candidate in known_modules:
            return candidate

    # Tail-match fallback (single-component targets or when the full path
    # wasn't found). Only trust this when exactly one module has this tail.
    tail = target.rsplit(".", 1)[-1]
    candidates = by_tail.get(tail, [])
    if len(candidates) == 1:
        return candidates[0]

    return None


# ---------- Telegram command scanner ----------

_HANDLER_DEF_RE = re.compile(r"^def (cmd_\w+)\s*\(", re.MULTILINE)
_HANDLERS_DICT_RE = re.compile(
    r"HANDLERS\s*=\s*\{(.*?)\n\}", re.DOTALL
)
_HANDLERS_KEY_RE = re.compile(r'["\']([^"\']+)["\']\s*:')
_MENU_CMD_RE = re.compile(r'["\']command["\']\s*:\s*["\']([^"\']+)["\']')
# Match `cmd_X` identifiers appearing as dict values (right of `: `).
# Captures every handler function reference inside the HANDLERS dict.
_HANDLERS_VALUE_RE = re.compile(r":\s*(cmd_\w+)")
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
        "handlers_dict_values": [],
        "menu_commands": [],
        "help_mentions": [],
        "guide_mentions": [],
        "hidden_handlers": [],
        "menu_exempt_handlers": [],
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

    # HANDLERS dict — extract both keys (user-facing command tokens) and
    # values (handler function references). The "values" set is the
    # authoritative check for "is cmd_X routed?" because user-facing keys
    # like "addmarket!" or "disrupt-update" can legitimately differ from
    # the Python handler name cmd_addmarket_confirm / cmd_disrupt_update.
    handlers_dict_keys: list[str] = []
    handlers_dict_values: list[str] = []
    dict_match = _HANDLERS_DICT_RE.search(source)
    if dict_match:
        dict_body = dict_match.group(1)
        handlers_dict_keys = _HANDLERS_KEY_RE.findall(dict_body)
        handlers_dict_values = _HANDLERS_VALUE_RE.findall(dict_body)

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

    hidden_handlers = _extract_module_constant(source, "_GUARDIAN_HIDDEN_HANDLERS")
    menu_exempt_handlers = _extract_module_constant(source, "_GUARDIAN_MENU_EXEMPT")

    return {
        "handlers": handlers,
        "handlers_dict_keys": handlers_dict_keys,
        "handlers_dict_values": handlers_dict_values,
        "menu_commands": menu_commands,
        "help_mentions": help_mentions,
        "guide_mentions": guide_mentions,
        "hidden_handlers": hidden_handlers,
        "menu_exempt_handlers": menu_exempt_handlers,
    }


def _extract_module_constant(source: str, const_name: str) -> list[str]:
    """Extract a module-level frozenset/set/list/tuple constant of strings.

    Used for `_GUARDIAN_HIDDEN_HANDLERS` (handlers excluded from every
    user-facing surface) and `_GUARDIAN_MENU_EXEMPT` (handlers kept out
    of the native Telegram menu but still documented in help/guide).
    Missing constant → []. Non-literal values in the collection are skipped.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == const_name:
                    return _literal_string_elements(node.value)
    return []


def _literal_string_elements(node: ast.AST) -> list[str]:
    """Pull string constants out of a frozenset/set/list/tuple literal AST.

    Handles:
        frozenset({"a", "b"})    → ["a", "b"]
        set({"a", "b"})          → ["a", "b"]
        {"a", "b"}               → ["a", "b"]
        ["a", "b"]               → ["a", "b"]
        ("a", "b")               → ["a", "b"]
    """
    # Unwrap frozenset(...) or set(...) calls
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in ("frozenset", "set"):
            if node.args:
                return _literal_string_elements(node.args[0])
            return []
    elts: list[ast.AST] = []
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        elts = list(node.elts)
    elif isinstance(node, ast.Dict):
        elts = list(node.keys)
    results: list[str] = []
    for el in elts:
        if isinstance(el, ast.Constant) and isinstance(el.value, str):
            results.append(el.value)
    return results


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


# ---------- Daemon iterator scanner ----------

def scan_iterators(iterators_dir: Path) -> list[dict[str, Any]]:
    """Scan a daemon iterators directory for *Iterator classes.

    Returns a list of {module, path, class} dicts. An iterator is any
    .py file (not __init__) containing a class whose name ends with 'Iterator'.
    """
    results: list[dict[str, Any]] = []
    if not iterators_dir.exists():
        return results

    for py_file in sorted(iterators_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Iterator"):
                results.append({
                    "module": py_file.stem,
                    "path": py_file.name,
                    "class": node.name,
                })
                break
    return results


# ---------- Full inventory builder ----------

def build_inventory(repo_root: Path) -> dict[str, Any]:
    """Build a complete inventory of the repo for Guardian.

    Reads: Python imports, Telegram commands, daemon iterators.
    Adds: timestamp, summary stats.
    """
    from datetime import datetime, timezone

    py_graph = scan_python_imports(repo_root)

    tg_path = repo_root / "cli" / "telegram_bot.py"
    telegram = scan_telegram_commands(tg_path) if tg_path.exists() else {
        "handlers": [],
        "handlers_dict_keys": [],
        "menu_commands": [],
        "help_mentions": [],
        "guide_mentions": [],
    }

    iter_dir = repo_root / "cli" / "daemon" / "iterators"
    iterators = scan_iterators(iter_dir) if iter_dir.exists() else []

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "modules": py_graph["modules"],
        "edges": py_graph["edges"],
        "telegram": telegram,
        "iterators": iterators,
        "stats": {
            "module_count": len(py_graph["modules"]),
            "edge_count": len(py_graph["edges"]),
            "telegram_handler_count": len(telegram["handlers"]),
            "iterator_count": len(iterators),
        },
    }


def write_inventory(inventory: dict[str, Any], state_dir: Path) -> None:
    """Write inventory.json + map.mmd + map.md to state_dir.

    Rotates previous inventory.json to inventory.prev.json if present.
    """
    state_dir.mkdir(parents=True, exist_ok=True)

    current = state_dir / "inventory.json"
    if current.exists():
        (state_dir / "inventory.prev.json").write_text(current.read_text())

    current.write_text(json.dumps(inventory, indent=2))

    # Build a minimal Mermaid graph of module edges
    lines = ["graph TD"]
    seen_edges: set[tuple[str, str]] = set()
    for e in inventory.get("edges", []):
        key = (e["from"], e["to"])
        if key in seen_edges:
            continue
        seen_edges.add(key)
        lines.append(f'    {e["from"]}[{e["from"]}] --> {e["to"]}[{e["to"]}]')

    (state_dir / "map.mmd").write_text("\n".join(lines) + "\n")

    stats = inventory.get("stats", {})
    summary = (
        "# Guardian Repo Map\n\n"
        f"Generated: {inventory.get('timestamp', 'unknown')}\n\n"
        f"- Modules: {stats.get('module_count', 0)}\n"
        f"- Edges: {stats.get('edge_count', 0)}\n"
        f"- Telegram handlers: {stats.get('telegram_handler_count', 0)}\n"
        f"- Daemon iterators: {stats.get('iterator_count', 0)}\n\n"
        "See map.mmd for the Mermaid diagram.\n"
    )
    (state_dir / "map.md").write_text(summary)
