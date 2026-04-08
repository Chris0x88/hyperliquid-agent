# Guardian Angel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dev-side, in-session meta-system for the HyperLiquid_Bot repo that prevents parallel-track drift, enforces UI-completeness, detects orphaning, surfaces recurring user pain, and proactively suggests improvements — all silently, with no user commands required.

**Architecture:** Three tiers. Tier 1 is pure-Python stdlib workers (cartographer, drift, friction, gate) that do mechanical analysis. Tier 2 is background sub-agents dispatched via the Agent tool during active Claude Code sessions for natural-language synthesis. Tier 3 is a SessionStart hook + PreToolUse gate that surfaces findings through Claude's natural response. Guardian runs only while a Claude Code session is active — never in the trading agent, never on cron, never pushing to Telegram.

**Tech Stack:** Python 3.13 stdlib only (`ast`, `pathlib`, `re`, `json`, `hashlib`, `subprocess`, `datetime`). No external dependencies. Mermaid for graph output (renders natively in Claude Code). pytest for testing (already in the project's `.venv`).

**Spec:** `agent-cli/docs/superpowers/specs/2026-04-09-guardian-angel-design.md`

**Scope guardrails (from CLAUDE.md + spec):**
- Never touch `cli/agent_runtime.py`, `agent/AGENT.md`, `agent/SOUL.md`, `~/.openclaw/`, or any daemon iterator
- Never `git add -A` or `git add .` — always specific files by name
- Guardian code is read-only on `data/thesis/`, `data/agent_memory/`, `data/feedback.jsonl`, and all runtime paths
- Every component must have an env-var kill switch
- Additive-only to existing docs (MASTER_PLAN gets one new line; AUDIT_FIX_PLAN untouched)

**Test command (used throughout):**
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/ -x -q
```

---

## Phase 1 — Foundation

Ships: repo scaffolding, minimal cartographer (imports + Telegram + iterators), SessionStart hook (read-only, no sub-agent dispatch yet), guide stub.

---

### Task 1: Package scaffold + gitignore + test infra

**Files:**
- Create: `agent-cli/guardian/__init__.py`
- Create: `agent-cli/guardian/state/.gitkeep`
- Create: `agent-cli/guardian/tests/__init__.py`
- Create: `agent-cli/guardian/tests/conftest.py`
- Create: `agent-cli/guardian/tests/fixtures/.gitkeep`
- Modify: `agent-cli/.gitignore` — add `guardian/state/*` rule but keep `.gitkeep`

- [ ] **Step 1: Create the package `__init__.py`**

Write `agent-cli/guardian/__init__.py`:
```python
"""Guardian Angel — dev-side meta-system for HyperLiquid_Bot.

See docs/superpowers/specs/2026-04-09-guardian-angel-design.md for the design.
See guardian/guide.md for the user-facing contract.
"""

__version__ = "0.1.0"
```

- [ ] **Step 2: Create the state directory with a placeholder**

Write `agent-cli/guardian/state/.gitkeep`:
```
# State files land here at runtime. Gitignored except this placeholder.
```

- [ ] **Step 3: Update .gitignore**

Read `agent-cli/.gitignore` first. Append these lines (do not remove existing entries):
```
# Guardian Angel runtime state (keep directory, ignore contents)
guardian/state/*
!guardian/state/.gitkeep
```

- [ ] **Step 4: Create the test package**

Write `agent-cli/guardian/tests/__init__.py`:
```python
"""Guardian test suite. Uses real tmp dirs, no filesystem mocks."""
```

Write `agent-cli/guardian/tests/conftest.py`:
```python
"""Shared pytest fixtures for Guardian tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Iterator[Path]:
    """Provide a minimal fake repo layout for Guardian tests."""
    (tmp_path / "cli").mkdir()
    (tmp_path / "cli" / "daemon").mkdir()
    (tmp_path / "cli" / "daemon" / "iterators").mkdir()
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "wiki" / "decisions").mkdir(parents=True)
    (tmp_path / "guardian" / "state").mkdir(parents=True)
    yield tmp_path


@pytest.fixture
def write_file():
    """Helper to write a file and return its path."""
    def _write(path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path
    return _write
```

Write `agent-cli/guardian/tests/fixtures/.gitkeep`:
```
# Fixture repos for golden-file tests. Each fixture is a tiny fake repo.
```

- [ ] **Step 5: Verify pytest can discover the package**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/ --collect-only 2>&1 | tail -20
```

Expected: `no tests ran` or `collected 0 items` (no tests yet, but no import errors).

- [ ] **Step 6: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/__init__.py guardian/state/.gitkeep guardian/tests/__init__.py guardian/tests/conftest.py guardian/tests/fixtures/.gitkeep .gitignore
git commit -m "feat(guardian): package scaffold + tests + gitignore

First task of Guardian Angel Phase 1. Empty package, state dir
placeholder, pytest conftest with tmp_repo and write_file fixtures,
gitignore rule for guardian/state/.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Cartographer — Python import graph

**Files:**
- Create: `agent-cli/guardian/cartographer.py`
- Create: `agent-cli/guardian/tests/test_cartographer_imports.py`
- Create: `agent-cli/guardian/tests/fixtures/mini_repo/a.py`
- Create: `agent-cli/guardian/tests/fixtures/mini_repo/b.py`
- Create: `agent-cli/guardian/tests/fixtures/mini_repo/c.py`

- [ ] **Step 1: Create a fixture repo with 3 Python files**

Write `agent-cli/guardian/tests/fixtures/mini_repo/a.py`:
```python
"""Module A — imports from b."""
from b import foo


def main():
    return foo()
```

Write `agent-cli/guardian/tests/fixtures/mini_repo/b.py`:
```python
"""Module B — imports from c."""
import c


def foo():
    return c.bar()
```

Write `agent-cli/guardian/tests/fixtures/mini_repo/c.py`:
```python
"""Module C — leaf, no imports."""


def bar():
    return 42
```

- [ ] **Step 2: Write the failing test for import scanning**

Write `agent-cli/guardian/tests/test_cartographer_imports.py`:
```python
"""Tests for cartographer's Python import scanning."""
from __future__ import annotations

from pathlib import Path

from guardian.cartographer import scan_python_imports


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mini_repo"


def test_scan_finds_all_python_files():
    result = scan_python_imports(FIXTURE_ROOT)
    modules = {m["name"] for m in result["modules"]}
    assert modules == {"a", "b", "c"}


def test_scan_captures_edges():
    result = scan_python_imports(FIXTURE_ROOT)
    edges = {(e["from"], e["to"]) for e in result["edges"]}
    assert ("a", "b") in edges
    assert ("b", "c") in edges


def test_scan_reports_leaf_as_no_outgoing_edges():
    result = scan_python_imports(FIXTURE_ROOT)
    c_outgoing = [e for e in result["edges"] if e["from"] == "c"]
    assert c_outgoing == []


def test_scan_reports_orphan_candidates():
    # In mini_repo: a has no inbound edges, c has no outbound edges.
    result = scan_python_imports(FIXTURE_ROOT)
    inbound = {m["name"]: 0 for m in result["modules"]}
    for e in result["edges"]:
        inbound[e["to"]] = inbound.get(e["to"], 0) + 1
    # a is the entrypoint (no inbound), which is fine.
    assert inbound["a"] == 0
    assert inbound["b"] == 1
    assert inbound["c"] == 1
```

- [ ] **Step 3: Run the test to verify it fails**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_cartographer_imports.py -v 2>&1 | tail -20
```

Expected: `ModuleNotFoundError` or `ImportError` — `scan_python_imports` does not exist yet.

- [ ] **Step 4: Implement the minimal scanner**

Write `agent-cli/guardian/cartographer.py`:
```python
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
from dataclasses import dataclass, field
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
        # Module name = filename stem for single-file modules, dotted for packages
        name = rel.with_suffix("").as_posix().replace("/", ".")
        # Strip common prefixes for readability in fixture repos
        if "." not in name:
            module_name = name
        else:
            module_name = name.rsplit(".", 1)[-1] if name.count(".") == 0 else name

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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_cartographer_imports.py -v 2>&1 | tail -20
```

Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/cartographer.py guardian/tests/test_cartographer_imports.py guardian/tests/fixtures/mini_repo/a.py guardian/tests/fixtures/mini_repo/b.py guardian/tests/fixtures/mini_repo/c.py
git commit -m "feat(guardian): cartographer Python import scanner

AST-based scanner that walks a repo root, builds a module list and
an import edge list. Pure stdlib. Tested on a 3-module fixture repo.
Supports GUARDIAN_CARTOGRAPHER_ENABLED kill switch.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Cartographer — Telegram command scanner

**Files:**
- Modify: `agent-cli/guardian/cartographer.py` — add `scan_telegram_commands()`
- Create: `agent-cli/guardian/tests/test_cartographer_telegram.py`
- Create: `agent-cli/guardian/tests/fixtures/fake_telegram_bot.py`

- [ ] **Step 1: Create the fixture telegram_bot file**

Write `agent-cli/guardian/tests/fixtures/fake_telegram_bot.py`:
```python
"""Fake telegram_bot.py for cartographer tests."""


def cmd_hello(token, chat_id, args):
    return "hi"


def cmd_goodbye(token, chat_id, args):
    return "bye"


def cmd_orphan(token, chat_id, args):
    """This one is NOT in HANDLERS — should be flagged."""
    return "orphaned"


HANDLERS = {
    "/hello": cmd_hello,
    "hello": cmd_hello,
    "/goodbye": cmd_goodbye,
    "goodbye": cmd_goodbye,
}


def _set_telegram_commands():
    return [
        {"command": "hello", "description": "Say hello"},
        {"command": "goodbye", "description": "Say goodbye"},
    ]


def cmd_help(token, chat_id, args):
    return "/hello  — Say hello\n/goodbye — Say goodbye"


def cmd_guide(token, chat_id, args):
    return "Guide text: use /hello and /goodbye"
```

- [ ] **Step 2: Write the failing test**

Write `agent-cli/guardian/tests/test_cartographer_telegram.py`:
```python
"""Tests for cartographer's Telegram command scanning."""
from __future__ import annotations

from pathlib import Path

from guardian.cartographer import scan_telegram_commands

FIXTURE = Path(__file__).parent / "fixtures" / "fake_telegram_bot.py"


def test_scan_finds_all_cmd_handlers():
    result = scan_telegram_commands(FIXTURE)
    handlers = {h["name"] for h in result["handlers"]}
    assert handlers == {"cmd_hello", "cmd_goodbye", "cmd_orphan"}


def test_scan_finds_commands_in_handlers_dict():
    result = scan_telegram_commands(FIXTURE)
    assert "/hello" in result["handlers_dict_keys"]
    assert "/goodbye" in result["handlers_dict_keys"]


def test_scan_finds_set_telegram_commands_entries():
    result = scan_telegram_commands(FIXTURE)
    menu_cmds = set(result["menu_commands"])
    assert menu_cmds == {"hello", "goodbye"}


def test_scan_finds_help_entries():
    result = scan_telegram_commands(FIXTURE)
    help_mentions = set(result["help_mentions"])
    assert "/hello" in help_mentions
    assert "/goodbye" in help_mentions


def test_scan_detects_unregistered_handler():
    result = scan_telegram_commands(FIXTURE)
    # cmd_orphan has no corresponding HANDLERS entry
    handler_names = {h["name"] for h in result["handlers"]}
    dict_keys = {k.lstrip("/") for k in result["handlers_dict_keys"]}
    unregistered = {
        h.replace("cmd_", "")
        for h in handler_names
        if h.replace("cmd_", "") not in dict_keys
    }
    assert "orphan" in unregistered
```

- [ ] **Step 3: Run the test to verify it fails**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_cartographer_telegram.py -v 2>&1 | tail -20
```

Expected: `ImportError` — `scan_telegram_commands` does not exist yet.

- [ ] **Step 4: Implement the Telegram scanner**

Append to `agent-cli/guardian/cartographer.py`:
```python
# ---------- Telegram command scanner ----------

_HANDLER_DEF_RE = re.compile(r"^def (cmd_\w+)\s*\(", re.MULTILINE)
_HANDLERS_DICT_RE = re.compile(
    r"HANDLERS\s*=\s*\{(.*?)\}", re.DOTALL
)
_HANDLERS_KEY_RE = re.compile(r'["\']([^"\']+)["\']\s*:')
_SET_TG_RE = re.compile(
    r'_set_telegram_commands[^\(]*\([^)]*\)[^:]*:.*?return\s*\[(.*?)\]',
    re.DOTALL,
)
_MENU_CMD_RE = re.compile(r'"command"\s*:\s*"([^"]+)"')
_HELP_MENTION_RE = re.compile(r"/([a-z_][a-z0-9_]*)")


def scan_telegram_commands(telegram_bot_path: Path) -> dict[str, Any]:
    """Scan cli/telegram_bot.py for command handlers and registrations.

    Returns:
        {
            "handlers": [{"name": "cmd_X", "line": N}, ...],
            "handlers_dict_keys": ["/cmd", "cmd", ...],
            "menu_commands": ["cmd", ...],  # entries in _set_telegram_commands
            "help_mentions": ["/cmd", ...],  # commands mentioned in cmd_help
            "guide_mentions": ["/cmd", ...],  # commands mentioned in cmd_guide
        }
    """
    if not telegram_bot_path.exists():
        return {
            "handlers": [],
            "handlers_dict_keys": [],
            "menu_commands": [],
            "help_mentions": [],
            "guide_mentions": [],
        }

    source = telegram_bot_path.read_text(encoding="utf-8")

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

    # _set_telegram_commands() menu entries
    menu_commands: list[str] = []
    set_match = _SET_TG_RE.search(source)
    if set_match:
        menu_commands = _MENU_CMD_RE.findall(set_match.group(1))

    # Help and guide mentions — find the function bodies
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
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            body_text = ast.unparse(node)
            return list(set(_HELP_MENTION_RE.findall(body_text)))
    return []
```

- [ ] **Step 5: Run the tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_cartographer_telegram.py -v 2>&1 | tail -20
```

Expected: 5 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/cartographer.py guardian/tests/test_cartographer_telegram.py guardian/tests/fixtures/fake_telegram_bot.py
git commit -m "feat(guardian): cartographer Telegram command scanner

Scans cli/telegram_bot.py for cmd_X handlers, HANDLERS dict entries,
_set_telegram_commands() menu entries, and help/guide mentions. Uses
regex + AST for robust extraction. Enables Phase 3 Telegram-completeness
gate rule.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Cartographer — daemon iterator scanner + inventory writer

**Files:**
- Modify: `agent-cli/guardian/cartographer.py` — add `scan_iterators()`, `build_inventory()`, `write_inventory()`
- Create: `agent-cli/guardian/tests/test_cartographer_iterators.py`
- Create: `agent-cli/guardian/tests/test_cartographer_inventory.py`
- Create: `agent-cli/guardian/tests/fixtures/fake_iterators/heartbeat.py`
- Create: `agent-cli/guardian/tests/fixtures/fake_iterators/__init__.py`

- [ ] **Step 1: Create iterator fixture**

Write `agent-cli/guardian/tests/fixtures/fake_iterators/__init__.py`:
```python
"""Fake daemon iterators package."""
```

Write `agent-cli/guardian/tests/fixtures/fake_iterators/heartbeat.py`:
```python
"""Fake heartbeat iterator."""


class HeartbeatIterator:
    name = "heartbeat"
    interval_sec = 60

    def run(self, ctx):
        return {"status": "ok"}
```

- [ ] **Step 2: Write the failing tests**

Write `agent-cli/guardian/tests/test_cartographer_iterators.py`:
```python
"""Tests for cartographer's daemon iterator scanning."""
from __future__ import annotations

from pathlib import Path

from guardian.cartographer import scan_iterators

FIXTURE = Path(__file__).parent / "fixtures" / "fake_iterators"


def test_scan_finds_iterator_modules():
    result = scan_iterators(FIXTURE)
    names = {i["module"] for i in result}
    assert "heartbeat" in names


def test_scan_extracts_iterator_class_name():
    result = scan_iterators(FIXTURE)
    assert any(i["class"] == "HeartbeatIterator" for i in result)
```

Write `agent-cli/guardian/tests/test_cartographer_inventory.py`:
```python
"""Tests for cartographer's full inventory builder."""
from __future__ import annotations

import json
from pathlib import Path

from guardian.cartographer import build_inventory, write_inventory


def test_build_inventory_on_empty_repo(tmp_repo: Path):
    inv = build_inventory(tmp_repo)
    assert "modules" in inv
    assert "edges" in inv
    assert "telegram" in inv
    assert "iterators" in inv
    assert "timestamp" in inv


def test_write_inventory_creates_json(tmp_repo: Path):
    inv = build_inventory(tmp_repo)
    out_dir = tmp_repo / "guardian" / "state"
    write_inventory(inv, out_dir)
    assert (out_dir / "inventory.json").exists()
    loaded = json.loads((out_dir / "inventory.json").read_text())
    assert loaded["modules"] == inv["modules"]


def test_write_inventory_creates_mermaid(tmp_repo: Path):
    inv = build_inventory(tmp_repo)
    out_dir = tmp_repo / "guardian" / "state"
    write_inventory(inv, out_dir)
    mmd = (out_dir / "map.mmd").read_text()
    assert mmd.startswith("graph")


def test_write_inventory_rotates_previous(tmp_repo: Path, write_file):
    out_dir = tmp_repo / "guardian" / "state"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "inventory.json").write_text('{"modules": [], "edges": [], "timestamp": "old"}')
    inv = build_inventory(tmp_repo)
    write_inventory(inv, out_dir)
    # Previous snapshot should have been rotated
    assert (out_dir / "inventory.prev.json").exists()
    prev = json.loads((out_dir / "inventory.prev.json").read_text())
    assert prev["timestamp"] == "old"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_cartographer_iterators.py guardian/tests/test_cartographer_inventory.py -v 2>&1 | tail -30
```

Expected: `ImportError` — `scan_iterators`, `build_inventory`, `write_inventory` do not exist.

- [ ] **Step 4: Implement the scanners and inventory writer**

Append to `agent-cli/guardian/cartographer.py`:
```python
# ---------- Daemon iterator scanner ----------

def scan_iterators(iterators_dir: Path) -> list[dict[str, Any]]:
    """Scan cli/daemon/iterators/ for iterator modules.

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
                    "path": str(py_file.relative_to(iterators_dir.parent.parent)) if iterators_dir.parent.parent in py_file.parents else py_file.name,
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

    # Build a minimal Mermaid graph of top-level module edges
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
```

- [ ] **Step 5: Run all tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/ -v 2>&1 | tail -30
```

Expected: all tests pass (4 from Task 2, 5 from Task 3, 2 from Task 4 iterators, 4 from Task 4 inventory = 15 tests).

- [ ] **Step 6: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/cartographer.py guardian/tests/test_cartographer_iterators.py guardian/tests/test_cartographer_inventory.py guardian/tests/fixtures/fake_iterators/__init__.py guardian/tests/fixtures/fake_iterators/heartbeat.py
git commit -m "feat(guardian): cartographer iterator scan + full inventory writer

Iterator scanner finds *Iterator classes in cli/daemon/iterators/.
build_inventory() combines Python graph + Telegram commands + iterators
into a single JSON. write_inventory() writes inventory.json, map.mmd
(Mermaid), and map.md (summary), rotating the previous snapshot to
inventory.prev.json for later drift comparison.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: SessionStart hook (read-only, compact state loader)

**Files:**
- Create: `agent-cli/.claude/hooks/session_start.py`
- Create: `agent-cli/.claude/hooks/__init__.py`
- Create: `agent-cli/guardian/tests/test_session_start_hook.py`
- Modify: `agent-cli/.claude/settings.json` (create if missing)

- [ ] **Step 1: Write the failing test**

Write `agent-cli/guardian/tests/test_session_start_hook.py`:
```python
"""Tests for the SessionStart hook (read-only mode)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


HOOK_PATH = Path(__file__).parent.parent.parent / ".claude" / "hooks" / "session_start.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("session_start_hook", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hook_handles_missing_state_dir(tmp_path: Path):
    mod = _load_hook()
    result = mod.build_summary(state_dir=tmp_path / "does_not_exist")
    assert "Guardian" in result
    assert "no report" in result.lower() or "not yet run" in result.lower()


def test_hook_reads_current_report(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "current_report.md").write_text("# Test Report\nP0: orphan X\n")
    mod = _load_hook()
    result = mod.build_summary(state_dir=state)
    assert "Test Report" in result or "orphan X" in result


def test_hook_reports_staleness(tmp_path: Path):
    import os
    import time
    state = tmp_path / "state"
    state.mkdir()
    report = state / "current_report.md"
    report.write_text("# Old Report\n")
    # Set mtime to 48 hours ago
    old = time.time() - 48 * 3600
    os.utime(report, (old, old))
    mod = _load_hook()
    result = mod.build_summary(state_dir=state)
    assert "stale" in result.lower() or "48" in result or "hours" in result.lower()


def test_hook_respects_global_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_ENABLED", "0")
    mod = _load_hook()
    result = mod.build_summary(state_dir=tmp_path)
    assert result == "" or "disabled" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_session_start_hook.py -v 2>&1 | tail -20
```

Expected: `FileNotFoundError` or import error — hook doesn't exist yet.

- [ ] **Step 3: Create the hooks package marker**

Write `agent-cli/.claude/hooks/__init__.py`:
```python
"""Claude Code hooks for the HyperLiquid_Bot project."""
```

- [ ] **Step 4: Implement the SessionStart hook (read-only mode)**

Write `agent-cli/.claude/hooks/session_start.py`:
```python
#!/usr/bin/env python3
"""Guardian SessionStart hook — injects compact repo state into Claude's context.

Read-only in Phase 1. Phase 5 adds background sub-agent dispatch.
Fails open (prints empty string) on any error so Claude Code never breaks.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def is_enabled() -> bool:
    """Global Guardian kill switch."""
    return os.environ.get("GUARDIAN_ENABLED", "1") != "0"


def _report_age_hours(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 3600.0


def build_summary(state_dir: Path | None = None) -> str:
    """Build the compact summary string to inject into Claude's context.

    Returns an empty string if Guardian is disabled or there's no state.
    Returns a short markdown block otherwise. Never raises.
    """
    if not is_enabled():
        return ""

    try:
        if state_dir is None:
            # Default: relative to this hook file
            repo_root = Path(__file__).resolve().parents[2]
            state_dir = repo_root / "guardian" / "state"

        state_dir = Path(state_dir)
        if not state_dir.exists():
            return "## Guardian\nNo report yet — Guardian has not yet run. Next session will generate one.\n"

        report = state_dir / "current_report.md"
        if not report.exists():
            return "## Guardian\nNo current report. Cartographer has not yet written one.\n"

        age_hours = _report_age_hours(report)
        stale_marker = ""
        if age_hours > 24:
            stale_marker = f" ⚠️ stale ({age_hours:.0f}h old)"

        body = report.read_text(encoding="utf-8")
        # Truncate to first 200 lines to respect hook output budget
        lines = body.split("\n")
        if len(lines) > 200:
            body = "\n".join(lines[:200]) + f"\n\n... ({len(lines) - 200} more lines in guardian/state/current_report.md)"

        return f"## Guardian{stale_marker}\n\n{body}\n"

    except Exception as e:
        # Fail open: never block the session
        return f"## Guardian\n(hook error: {type(e).__name__}; see guardian/state/sweep.log)\n"


def main() -> int:
    summary = build_summary()
    if summary:
        sys.stdout.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Make the hook executable:
```bash
chmod +x /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/.claude/hooks/session_start.py
```

- [ ] **Step 5: Wire the hook into .claude/settings.json**

Read `agent-cli/.claude/settings.json` if it exists. If not, create it.

Write `agent-cli/.claude/settings.json` (if file does not exist — otherwise, merge the hooks section into the existing JSON, preserving all other keys):
```json
{
  "hooks": {
    "SessionStart": [
      {
        "command": "python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/session_start.py"
      }
    ]
  }
}
```

**Important:** if `settings.json` already exists with other content, do NOT overwrite. Read it with Read, then use Edit to add the `SessionStart` hook entry preserving all other keys.

- [ ] **Step 6: Run tests to verify they pass**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_session_start_hook.py -v 2>&1 | tail -20
```

Expected: 4 tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add .claude/hooks/__init__.py .claude/hooks/session_start.py .claude/settings.json guardian/tests/test_session_start_hook.py
git commit -m "feat(guardian): SessionStart hook (read-only Phase 1)

Loads guardian/state/current_report.md at session start and injects it
into Claude's context. Fails open on any error. Reports staleness if
the report is older than 24h. GUARDIAN_ENABLED kill switch. Wired into
.claude/settings.json. Sub-agent dispatch deferred to Phase 5.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Guide stub + /guide slash command

**Files:**
- Create: `agent-cli/guardian/guide.md`
- Create: `agent-cli/.claude/commands/guide.md`

- [ ] **Step 1: Write the Guardian guide stub**

Write `agent-cli/guardian/guide.md`:
```markdown
# Guardian Angel — User Guide

> This is the living contract between Chris and Guardian. If it's not documented here, Guardian doesn't do it.

## What is Guardian?

A dev-side meta-system that watches the HyperLiquid_Bot repo while Claude Code is working in it. It runs only during active Claude Code sessions. It does not run on cron, does not touch the trading agent, and does not push anything to Telegram.

## What does it do?

1. **Cartographer** scans the repo every session start and builds a wiring inventory (modules, imports, Telegram commands, daemon iterators).
2. **Drift Detector** (Phase 2+) compares snapshots and flags orphans, parallel tracks, plan/code mismatches, and Telegram gaps.
3. **Review Gate** (Phase 3+) blocks destructive or incomplete actions via a PreToolUse hook.
4. **Friction Surfacer** (Phase 4+) reads user logs and detects recurring pain patterns.
5. **Advisor** (Phase 5+) synthesizes everything into a natural-language report.
6. **Guide** (this document) — the contract.

## When does it run?

- **SessionStart:** reads the current report, injects a compact summary into Claude's context.
- **PreToolUse (Phase 3+):** runs gate checks on Edit/Write/Bash calls.
- **Mid-session sub-agent dispatch (Phase 5+):** when the conversation suggests deeper analysis would help.
- **Never otherwise.** When you close Claude Code, Guardian sleeps.

## How do I read a report?

`guardian/state/current_report.md` is the single source of truth. It has:
- A one-paragraph summary of repo state
- P0 findings (action required)
- P1 findings (investigate soon)
- Questions worth asking

## Slash commands

| Command | What it does |
|---|---|
| `/guide` | Prints this guide |
| `/guardian` | Force a guardian sweep now (Phase 5+) |

## Kill switches

Every component has an environment variable kill switch. Set to `0` to disable.

| Scope | Env var |
|---|---|
| Global | `GUARDIAN_ENABLED` |
| Cartographer | `GUARDIAN_CARTOGRAPHER_ENABLED` |
| Drift | `GUARDIAN_DRIFT_ENABLED` |
| Friction | `GUARDIAN_FRICTION_ENABLED` |
| Gate (all rules) | `GUARDIAN_GATE_ENABLED` |
| Gate — Telegram completeness | `GUARDIAN_RULE_TELEGRAM_COMPLETENESS` |
| Gate — Parallel track | `GUARDIAN_RULE_PARALLEL_TRACK` |
| Gate — Recent delete guard | `GUARDIAN_RULE_RECENT_DELETE` |
| Gate — Stale ADR guard | `GUARDIAN_RULE_STALE_ADR` |
| Sub-agent dispatch | `GUARDIAN_SUBAGENTS_ENABLED` |

To silence Guardian entirely for one session:
```bash
GUARDIAN_ENABLED=0 claude
```

## What Guardian never touches

- `cli/agent_runtime.py`
- `agent/AGENT.md`, `agent/SOUL.md`
- `~/.openclaw/`
- Daemon iterators
- `data/thesis/`, `data/agent_memory/`, `data/feedback.jsonl`
- Telegram bot runtime
- Existing wiki pages, ADRs, plans (only additive changes)

## Current status

**Phase 1 — Foundation.** Cartographer + SessionStart hook (read-only) shipped. No gate, no sub-agents, no drift detection yet.

See `docs/plans/GUARDIAN_PLAN.md` for the phase status table.
```

- [ ] **Step 2: Write the /guide slash command**

Write `agent-cli/.claude/commands/guide.md`:
```markdown
---
description: Print the Guardian Angel user guide
---

Read the file `agent-cli/guardian/guide.md` and print its contents to the user verbatim. This is the contract between the user and the Guardian Angel meta-system.
```

- [ ] **Step 3: Verify the files are readable**

Run:
```bash
cat /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/guardian/guide.md | head -20
cat /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/.claude/commands/guide.md
```

Expected: both files print their contents correctly.

- [ ] **Step 4: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/guide.md .claude/commands/guide.md
git commit -m "feat(guardian): guide stub + /guide slash command

Living contract document describing what Guardian is, when it runs,
how to read reports, all kill switches, and what it never touches.
Phase 1 status noted. /guide slash command reads and prints it.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — Drift Detection

Ships: orphan detection, parallel-track detection, plan/code mismatch, Telegram completeness gap reporting. Surface-only — no blocking yet.

---

### Task 7: Drift — orphan + parallel-track detection

**Files:**
- Create: `agent-cli/guardian/drift.py`
- Create: `agent-cli/guardian/tests/test_drift_orphans.py`
- Create: `agent-cli/guardian/tests/test_drift_parallel.py`

- [ ] **Step 1: Write the failing orphan test**

Write `agent-cli/guardian/tests/test_drift_orphans.py`:
```python
"""Tests for drift.detect_orphans()."""
from __future__ import annotations

from guardian.drift import detect_orphans


def test_no_orphans_when_all_modules_imported():
    inventory = {
        "modules": [{"name": "a", "path": "a.py"}, {"name": "b", "path": "b.py"}],
        "edges": [{"from": "a", "to": "b", "kind": "import"}],
    }
    # 'a' is the entrypoint, 'b' is imported by 'a'
    # Only 'b' has inbound edges; 'a' has zero inbound but is the entry.
    # detect_orphans returns modules with zero inbound AND not in entrypoint list.
    orphans = detect_orphans(inventory, entrypoints={"a"})
    assert orphans == []


def test_finds_orphan_with_no_inbound():
    inventory = {
        "modules": [
            {"name": "a", "path": "a.py"},
            {"name": "b", "path": "b.py"},
            {"name": "orphan", "path": "orphan.py"},
        ],
        "edges": [{"from": "a", "to": "b", "kind": "import"}],
    }
    orphans = detect_orphans(inventory, entrypoints={"a"})
    orphan_names = {o["name"] for o in orphans}
    assert "orphan" in orphan_names
    assert "a" not in orphan_names  # entrypoint
    assert "b" not in orphan_names  # imported
```

- [ ] **Step 2: Write the failing parallel-track test**

Write `agent-cli/guardian/tests/test_drift_parallel.py`:
```python
"""Tests for drift.detect_parallel_tracks()."""
from __future__ import annotations

from guardian.drift import detect_parallel_tracks


def test_no_parallel_tracks_when_names_distinct():
    inventory = {
        "modules": [
            {"name": "cartographer", "path": "cartographer.py", "docstring": ""},
            {"name": "risk_manager", "path": "risk_manager.py", "docstring": ""},
        ],
    }
    tracks = detect_parallel_tracks(inventory)
    assert tracks == []


def test_detects_similar_module_names():
    inventory = {
        "modules": [
            {"name": "memory_manager", "path": "memory_manager.py", "docstring": "manages memory"},
            {"name": "memory_manager_v2", "path": "memory_manager_v2.py", "docstring": "manages memory better"},
        ],
    }
    tracks = detect_parallel_tracks(inventory, similarity_threshold=0.6)
    assert len(tracks) >= 1
    names = {tuple(sorted([t["a"], t["b"]])) for t in tracks}
    assert ("memory_manager", "memory_manager_v2") in names


def test_ignores_dissimilar_modules():
    inventory = {
        "modules": [
            {"name": "alpha", "path": "alpha.py", "docstring": "alpha module"},
            {"name": "beta", "path": "beta.py", "docstring": "beta module"},
        ],
    }
    tracks = detect_parallel_tracks(inventory, similarity_threshold=0.6)
    assert tracks == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_drift_orphans.py guardian/tests/test_drift_parallel.py -v 2>&1 | tail -20
```

Expected: `ImportError` — `drift` module doesn't exist.

- [ ] **Step 4: Implement drift.py with orphan + parallel-track detection**

Write `agent-cli/guardian/drift.py`:
```python
"""Guardian drift detector — compares inventory snapshots and flags issues.

Pure stdlib. Reads inventory.json (current) and inventory.prev.json (previous)
and outputs drift_report.json + drift_report.md with severity-tagged findings.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------- Kill switch ----------

def is_enabled() -> bool:
    return os.environ.get("GUARDIAN_DRIFT_ENABLED", "1") != "0"


# ---------- Orphan detection ----------

# Default entrypoint modules that are allowed to have zero inbound edges.
DEFAULT_ENTRYPOINTS: frozenset[str] = frozenset({
    "telegram_bot",
    "daemon",
    "agent_runtime",
    "telegram_agent",
    "main",
    "__main__",
    "sweep",  # guardian's own orchestrator
})


def detect_orphans(
    inventory: dict[str, Any],
    entrypoints: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Find modules with zero inbound imports that are not entrypoints.

    Args:
        inventory: output of cartographer.build_inventory()
        entrypoints: module names allowed to have zero inbound edges

    Returns:
        List of {name, path, severity, reason} dicts.
    """
    if entrypoints is None:
        entrypoints = DEFAULT_ENTRYPOINTS

    inbound: dict[str, int] = {m["name"]: 0 for m in inventory.get("modules", [])}
    for edge in inventory.get("edges", []):
        to = edge.get("to")
        if to in inbound:
            inbound[to] += 1

    orphans: list[dict[str, Any]] = []
    modules_by_name = {m["name"]: m for m in inventory.get("modules", [])}
    for name, count in inbound.items():
        if count == 0 and name not in entrypoints:
            m = modules_by_name.get(name, {})
            orphans.append({
                "name": name,
                "path": m.get("path", "?"),
                "severity": "P1",
                "reason": "Module has zero inbound imports and is not a known entrypoint",
            })
    return orphans


# ---------- Parallel track detection ----------

def _token_set(s: str) -> set[str]:
    """Split on non-alphanumeric, lowercase, drop tokens shorter than 2 chars."""
    import re
    return {t for t in re.split(r"[^a-zA-Z0-9]+", s.lower()) if len(t) >= 2}


def _similarity(a: str, b: str) -> float:
    """Jaccard similarity of tokens extracted from two strings."""
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def detect_parallel_tracks(
    inventory: dict[str, Any],
    similarity_threshold: float = 0.6,
) -> list[dict[str, Any]]:
    """Find pairs of modules with overlapping name tokens above a threshold.

    Two modules are flagged as a parallel track if the Jaccard similarity of
    their name tokens is >= similarity_threshold.
    """
    modules = inventory.get("modules", [])
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for i, a in enumerate(modules):
        for b in modules[i + 1:]:
            if a["name"] == b["name"]:
                continue
            sim = _similarity(a["name"], b["name"])
            if sim >= similarity_threshold:
                key = tuple(sorted([a["name"], b["name"]]))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append({
                    "a": a["name"],
                    "b": b["name"],
                    "a_path": a.get("path", "?"),
                    "b_path": b.get("path", "?"),
                    "similarity": round(sim, 2),
                    "severity": "P1",
                    "reason": f"Module names share {sim:.0%} token overlap — possible parallel track",
                })
    return pairs
```

- [ ] **Step 5: Run tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_drift_orphans.py guardian/tests/test_drift_parallel.py -v 2>&1 | tail -20
```

Expected: 5 tests pass (2 orphan, 3 parallel).

- [ ] **Step 6: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/drift.py guardian/tests/test_drift_orphans.py guardian/tests/test_drift_parallel.py
git commit -m "feat(guardian): drift detector — orphans + parallel tracks

detect_orphans() flags modules with zero inbound imports that aren't
known entrypoints. detect_parallel_tracks() uses Jaccard token overlap
to flag possible duplicate systems. Both tagged P1 by default.
GUARDIAN_DRIFT_ENABLED kill switch.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Drift — Telegram completeness + plan/code mismatch + report writer

**Files:**
- Modify: `agent-cli/guardian/drift.py` — add `detect_telegram_gaps()`, `detect_plan_code_mismatch()`, `build_drift_report()`, `write_drift_report()`
- Create: `agent-cli/guardian/tests/test_drift_telegram.py`
- Create: `agent-cli/guardian/tests/test_drift_report.py`

- [ ] **Step 1: Write failing Telegram-gap test**

Write `agent-cli/guardian/tests/test_drift_telegram.py`:
```python
"""Tests for drift.detect_telegram_gaps()."""
from __future__ import annotations

from guardian.drift import detect_telegram_gaps


def test_no_gaps_when_fully_registered():
    telegram = {
        "handlers": [{"name": "cmd_hello"}, {"name": "cmd_bye"}],
        "handlers_dict_keys": ["/hello", "hello", "/bye", "bye"],
        "menu_commands": ["hello", "bye"],
        "help_mentions": ["/hello", "/bye"],
        "guide_mentions": ["/hello", "/bye"],
    }
    gaps = detect_telegram_gaps(telegram)
    assert gaps == []


def test_detects_unregistered_handler():
    telegram = {
        "handlers": [{"name": "cmd_hello"}, {"name": "cmd_orphan"}],
        "handlers_dict_keys": ["/hello", "hello"],
        "menu_commands": ["hello"],
        "help_mentions": ["/hello"],
        "guide_mentions": ["/hello"],
    }
    gaps = detect_telegram_gaps(telegram)
    orphan_gaps = [g for g in gaps if g["command"] == "orphan"]
    assert len(orphan_gaps) >= 1
    assert orphan_gaps[0]["severity"] == "P0"


def test_detects_missing_menu_entry():
    telegram = {
        "handlers": [{"name": "cmd_hello"}],
        "handlers_dict_keys": ["/hello", "hello"],
        "menu_commands": [],  # missing from menu
        "help_mentions": ["/hello"],
        "guide_mentions": ["/hello"],
    }
    gaps = detect_telegram_gaps(telegram)
    missing_menu = [g for g in gaps if "menu" in g["reason"].lower()]
    assert len(missing_menu) >= 1
```

- [ ] **Step 2: Write failing drift report test**

Write `agent-cli/guardian/tests/test_drift_report.py`:
```python
"""Tests for drift.build_drift_report() and write_drift_report()."""
from __future__ import annotations

import json
from pathlib import Path

from guardian.drift import build_drift_report, write_drift_report


def test_build_report_structure():
    inventory = {
        "modules": [{"name": "a", "path": "a.py"}, {"name": "orphan", "path": "orphan.py"}],
        "edges": [],
        "telegram": {
            "handlers": [],
            "handlers_dict_keys": [],
            "menu_commands": [],
            "help_mentions": [],
            "guide_mentions": [],
        },
        "iterators": [],
    }
    report = build_drift_report(inventory, prev_inventory=None)
    assert "orphans" in report
    assert "parallel_tracks" in report
    assert "telegram_gaps" in report
    assert "timestamp" in report
    assert "summary" in report


def test_write_report_creates_json_and_md(tmp_path: Path):
    inventory = {
        "modules": [{"name": "a", "path": "a.py"}],
        "edges": [],
        "telegram": {"handlers": [], "handlers_dict_keys": [], "menu_commands": [], "help_mentions": [], "guide_mentions": []},
        "iterators": [],
    }
    report = build_drift_report(inventory, prev_inventory=None)
    write_drift_report(report, tmp_path)
    assert (tmp_path / "drift_report.json").exists()
    assert (tmp_path / "drift_report.md").exists()
    loaded = json.loads((tmp_path / "drift_report.json").read_text())
    assert loaded["summary"] == report["summary"]


def test_report_counts_p0_findings():
    inventory = {
        "modules": [],
        "edges": [],
        "telegram": {
            "handlers": [{"name": "cmd_orphan"}],
            "handlers_dict_keys": [],
            "menu_commands": [],
            "help_mentions": [],
            "guide_mentions": [],
        },
        "iterators": [],
    }
    report = build_drift_report(inventory, prev_inventory=None)
    assert report["summary"]["p0_count"] >= 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_drift_telegram.py guardian/tests/test_drift_report.py -v 2>&1 | tail -30
```

Expected: `ImportError` — the new functions don't exist.

- [ ] **Step 4: Implement the new drift functions**

Append to `agent-cli/guardian/drift.py`:
```python
# ---------- Telegram completeness gap detection ----------

def detect_telegram_gaps(telegram: dict[str, Any]) -> list[dict[str, Any]]:
    """Find cmd_* handlers that are not fully registered.

    A handler is "fully registered" if it appears in:
    - HANDLERS dict (with at least one key)
    - _set_telegram_commands() menu list
    - cmd_help mention
    - cmd_guide mention
    """
    gaps: list[dict[str, Any]] = []

    handler_names = {h["name"].replace("cmd_", "") for h in telegram.get("handlers", [])}
    dict_keys = {k.lstrip("/") for k in telegram.get("handlers_dict_keys", [])}
    menu = set(telegram.get("menu_commands", []))
    help_set = {h.lstrip("/") for h in telegram.get("help_mentions", [])}
    guide_set = {h.lstrip("/") for h in telegram.get("guide_mentions", [])}

    for name in sorted(handler_names):
        missing = []
        if name not in dict_keys:
            missing.append("HANDLERS dict")
        if name not in menu:
            missing.append("_set_telegram_commands() menu")
        if name not in help_set:
            missing.append("cmd_help")
        if name not in guide_set:
            missing.append("cmd_guide")
        if missing:
            severity = "P0" if "HANDLERS dict" in missing else "P1"
            gaps.append({
                "command": name,
                "severity": severity,
                "missing_from": missing,
                "reason": f"cmd_{name} not registered in: {', '.join(missing)}",
            })
    return gaps


# ---------- Plan/code mismatch detection ----------

def detect_plan_code_mismatch(
    inventory: dict[str, Any],
    plan_references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find plan references to files/modules that don't exist in the inventory.

    Args:
        inventory: output of cartographer.build_inventory()
        plan_references: list of {plan, reference, kind} dicts

    Returns:
        List of mismatch findings.
    """
    known_paths = {m.get("path") for m in inventory.get("modules", [])}
    known_names = {m.get("name") for m in inventory.get("modules", [])}
    mismatches: list[dict[str, Any]] = []

    for ref in plan_references:
        reference = ref.get("reference", "")
        if not reference:
            continue
        if reference.endswith(".py"):
            if reference not in known_paths:
                mismatches.append({
                    "plan": ref.get("plan", "?"),
                    "reference": reference,
                    "severity": "P1",
                    "reason": f"Plan references file '{reference}' which does not exist",
                })
        else:
            if reference not in known_names:
                mismatches.append({
                    "plan": ref.get("plan", "?"),
                    "reference": reference,
                    "severity": "P2",
                    "reason": f"Plan references module '{reference}' which does not exist",
                })
    return mismatches


# ---------- Full drift report builder + writer ----------

def build_drift_report(
    inventory: dict[str, Any],
    prev_inventory: dict[str, Any] | None,
    plan_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble a complete drift report from an inventory + optional previous."""
    from datetime import datetime, timezone

    orphans = detect_orphans(inventory)
    parallel_tracks = detect_parallel_tracks(inventory)
    telegram_gaps = detect_telegram_gaps(inventory.get("telegram", {}))
    plan_mismatches = detect_plan_code_mismatch(inventory, plan_references or [])

    all_findings = [*orphans, *parallel_tracks, *telegram_gaps, *plan_mismatches]
    p0 = sum(1 for f in all_findings if f.get("severity") == "P0")
    p1 = sum(1 for f in all_findings if f.get("severity") == "P1")
    p2 = sum(1 for f in all_findings if f.get("severity") == "P2")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "orphans": orphans,
        "parallel_tracks": parallel_tracks,
        "telegram_gaps": telegram_gaps,
        "plan_mismatches": plan_mismatches,
        "summary": {
            "p0_count": p0,
            "p1_count": p1,
            "p2_count": p2,
            "total": len(all_findings),
        },
    }


def write_drift_report(report: dict[str, Any], state_dir: Path) -> None:
    """Write drift_report.json and drift_report.md to state_dir."""
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "drift_report.json").write_text(json.dumps(report, indent=2))

    lines = ["# Drift Report", "", f"Generated: {report.get('timestamp', 'unknown')}", ""]
    summary = report.get("summary", {})
    lines.append(f"**{summary.get('p0_count', 0)} P0** · **{summary.get('p1_count', 0)} P1** · **{summary.get('p2_count', 0)} P2**")
    lines.append("")

    if report.get("orphans"):
        lines.append("## Orphans")
        for o in report["orphans"]:
            lines.append(f"- `{o['name']}` ({o.get('path', '?')}) — {o.get('reason', '')}")
        lines.append("")

    if report.get("parallel_tracks"):
        lines.append("## Parallel Tracks")
        for p in report["parallel_tracks"]:
            lines.append(f"- `{p['a']}` ↔ `{p['b']}` (similarity {p['similarity']:.0%}) — {p.get('reason', '')}")
        lines.append("")

    if report.get("telegram_gaps"):
        lines.append("## Telegram Completeness Gaps")
        for g in report["telegram_gaps"]:
            lines.append(f"- **[{g['severity']}]** `cmd_{g['command']}` — missing from: {', '.join(g['missing_from'])}")
        lines.append("")

    if report.get("plan_mismatches"):
        lines.append("## Plan/Code Mismatches")
        for m in report["plan_mismatches"]:
            lines.append(f"- **[{m['severity']}]** `{m['plan']}` → `{m['reference']}` — {m.get('reason', '')}")
        lines.append("")

    (state_dir / "drift_report.md").write_text("\n".join(lines) + "\n")
```

- [ ] **Step 5: Run tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/ -v 2>&1 | tail -30
```

Expected: all tests pass (previous 15 + 3 telegram + 3 report = 21 total).

- [ ] **Step 6: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/drift.py guardian/tests/test_drift_telegram.py guardian/tests/test_drift_report.py
git commit -m "feat(guardian): drift — telegram gaps + plan mismatches + report writer

detect_telegram_gaps() flags cmd_X handlers missing from HANDLERS,
menu, help, or guide. detect_plan_code_mismatch() flags plan refs to
non-existent files/modules. build_drift_report() assembles all drift
signals with P0/P1/P2 severity. write_drift_report() outputs JSON + MD.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — Review Gate

Ships: PreToolUse hook with four gate rules. Each rule enabled one at a time with its own kill switch.

---

### Task 9: Gate skeleton + PreToolUse hook

**Files:**
- Create: `agent-cli/guardian/gate.py`
- Create: `agent-cli/.claude/hooks/pre_tool_use.py`
- Create: `agent-cli/guardian/tests/test_gate_skeleton.py`
- Modify: `agent-cli/.claude/settings.json` — add PreToolUse hook entry

- [ ] **Step 1: Write the failing test**

Write `agent-cli/guardian/tests/test_gate_skeleton.py`:
```python
"""Tests for gate.py skeleton."""
from __future__ import annotations

from guardian.gate import GateResult, check_tool_use


def test_gate_allows_unknown_tool():
    result = check_tool_use(tool_name="Unknown", tool_input={})
    assert isinstance(result, GateResult)
    assert result.allow is True


def test_gate_allows_when_globally_disabled(monkeypatch):
    monkeypatch.setenv("GUARDIAN_GATE_ENABLED", "0")
    result = check_tool_use(tool_name="Edit", tool_input={"file_path": "anything"})
    assert result.allow is True
    assert "disabled" in (result.reason or "").lower()


def test_gate_result_can_block():
    result = GateResult(allow=False, reason="test block", rule="test-rule")
    assert result.allow is False
    assert result.reason == "test block"
    assert result.rule == "test-rule"
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_gate_skeleton.py -v 2>&1 | tail -15
```

Expected: `ImportError`.

- [ ] **Step 3: Implement gate.py skeleton**

Write `agent-cli/guardian/gate.py`:
```python
"""Guardian review gate — PreToolUse checks on Edit/Write/Bash.

Pure stdlib. Must be fast (<100ms per call). Fail-open on any error —
Guardian's gate never blocks Claude Code itself from running.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


# ---------- Kill switches ----------

def is_enabled() -> bool:
    return os.environ.get("GUARDIAN_GATE_ENABLED", "1") != "0"


def is_rule_enabled(rule_name: str) -> bool:
    env_name = "GUARDIAN_RULE_" + rule_name.upper().replace("-", "_")
    return os.environ.get(env_name, "1") != "0"


# ---------- Result type ----------

@dataclass
class GateResult:
    """Outcome of a gate check."""
    allow: bool
    reason: str | None = None
    rule: str | None = None


# ---------- Rule registry ----------

RuleFn = Callable[[str, dict[str, Any]], GateResult | None]
_RULES: list[tuple[str, RuleFn]] = []


def register_rule(name: str):
    """Decorator to register a rule function under a name."""
    def decorator(fn: RuleFn) -> RuleFn:
        _RULES.append((name, fn))
        return fn
    return decorator


# ---------- Main check entrypoint ----------

def check_tool_use(tool_name: str, tool_input: dict[str, Any]) -> GateResult:
    """Run all enabled gate rules against a tool call.

    Returns the first block result, or GateResult(allow=True) if all pass.
    """
    if not is_enabled():
        return GateResult(allow=True, reason="Guardian gate globally disabled")

    for rule_name, rule_fn in _RULES:
        if not is_rule_enabled(rule_name):
            continue
        try:
            result = rule_fn(tool_name, tool_input)
        except Exception:
            # Fail-open on rule error
            continue
        if result is not None and not result.allow:
            return result

    return GateResult(allow=True)
```

- [ ] **Step 4: Implement the PreToolUse hook**

Write `agent-cli/.claude/hooks/pre_tool_use.py`:
```python
#!/usr/bin/env python3
"""Guardian PreToolUse hook — runs gate.py checks on Edit/Write/Bash.

Reads tool invocation JSON from stdin, runs the gate, writes a result
JSON to stdout. Fails open on any error — the hook never raises.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure guardian is importable
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            # Nothing to check; allow.
            return 0
        payload = json.loads(raw)
    except Exception:
        # Fail open: can't parse, allow.
        return 0

    tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
    tool_input = payload.get("tool_input", {}) or payload.get("toolInput", {})

    try:
        from guardian.gate import check_tool_use
        result = check_tool_use(tool_name, tool_input)
    except Exception:
        return 0

    if result.allow:
        return 0

    # Blocked — write reason to stdout as JSON, exit 2 (per Claude Code hook convention)
    sys.stdout.write(json.dumps({
        "decision": "block",
        "reason": result.reason or "Guardian gate blocked this action",
        "rule": result.rule or "unknown",
    }))
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

Make executable:
```bash
chmod +x /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/.claude/hooks/pre_tool_use.py
```

- [ ] **Step 5: Wire into .claude/settings.json**

Read `agent-cli/.claude/settings.json` first. Add the PreToolUse entry to the `hooks` object, preserving all existing keys. The resulting file should look like:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "command": "python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/session_start.py"
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Edit|Write|Bash",
        "command": "python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/pre_tool_use.py"
      }
    ]
  }
}
```

Use the Edit tool on the existing file — do not overwrite.

- [ ] **Step 6: Run tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_gate_skeleton.py -v 2>&1 | tail -20
```

Expected: 3 tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/gate.py .claude/hooks/pre_tool_use.py .claude/settings.json guardian/tests/test_gate_skeleton.py
git commit -m "feat(guardian): review gate skeleton + PreToolUse hook

Gate skeleton with rule registry, kill switches (global and per-rule),
GateResult dataclass, and fail-open check_tool_use() entrypoint. Hook
reads tool invocation JSON from stdin and blocks via exit code 2 on
rule violations. Wired into settings.json for Edit/Write/Bash matchers.
No rules registered yet — those come in Tasks 10-12.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Gate rule — telegram-completeness

**Files:**
- Modify: `agent-cli/guardian/gate.py` — add the rule
- Create: `agent-cli/guardian/tests/test_gate_telegram_rule.py`

- [ ] **Step 1: Write the failing test**

Write `agent-cli/guardian/tests/test_gate_telegram_rule.py`:
```python
"""Tests for the telegram-completeness gate rule."""
from __future__ import annotations

from pathlib import Path

from guardian.gate import check_tool_use


def test_rule_allows_edit_to_unrelated_file():
    result = check_tool_use(
        tool_name="Edit",
        tool_input={"file_path": "some/other/file.py", "old_string": "x", "new_string": "y"},
    )
    assert result.allow is True


def test_rule_allows_full_registration(tmp_path: Path, monkeypatch):
    tg = tmp_path / "cli" / "telegram_bot.py"
    tg.parent.mkdir(parents=True)
    tg.write_text("""
def cmd_new(token, chat_id, args):
    return "new"

HANDLERS = {"/new": cmd_new, "new": cmd_new}

def _set_telegram_commands():
    return [{"command": "new", "description": "new cmd"}]

def cmd_help(token, chat_id, args):
    return "/new - new"

def cmd_guide(token, chat_id, args):
    return "/new - new"
""")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Edit",
        tool_input={"file_path": str(tg), "old_string": "x", "new_string": "y"},
    )
    assert result.allow is True


def test_rule_blocks_new_handler_without_registration(tmp_path: Path, monkeypatch):
    tg = tmp_path / "cli" / "telegram_bot.py"
    tg.parent.mkdir(parents=True)
    tg.write_text("""
def cmd_orphan(token, chat_id, args):
    return "orphan"

HANDLERS = {}

def _set_telegram_commands():
    return []

def cmd_help(token, chat_id, args):
    return ""

def cmd_guide(token, chat_id, args):
    return ""
""")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(tg), "content": tg.read_text()},
    )
    assert result.allow is False
    assert "cmd_orphan" in (result.reason or "")
    assert result.rule == "telegram-completeness"


def test_rule_respects_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_RULE_TELEGRAM_COMPLETENESS", "0")
    tg = tmp_path / "cli" / "telegram_bot.py"
    tg.parent.mkdir(parents=True)
    tg.write_text("def cmd_orphan(token, chat_id, args): return 'x'\nHANDLERS = {}\n")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(tg), "content": tg.read_text()},
    )
    assert result.allow is True
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_gate_telegram_rule.py -v 2>&1 | tail -20
```

Expected: 3rd test fails (allows a blocked scenario because no rule is registered yet).

- [ ] **Step 3: Implement the rule**

Append to `agent-cli/guardian/gate.py`:
```python
# ---------- Rule: telegram-completeness ----------

@register_rule("telegram-completeness")
def _rule_telegram_completeness(tool_name: str, tool_input: dict[str, Any]) -> GateResult | None:
    """Block Edit/Write to telegram_bot.py that adds a cmd_X without registration."""
    if tool_name not in ("Edit", "Write"):
        return None

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None

    path = Path(file_path)
    if path.name != "telegram_bot.py":
        return None

    # Determine the future content of the file
    if tool_name == "Write":
        future_content = tool_input.get("content", "")
    else:  # Edit
        if not path.exists():
            return None
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            return None
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        if not old:
            return None
        replace_all = bool(tool_input.get("replace_all", False))
        if replace_all:
            future_content = current.replace(old, new)
        else:
            future_content = current.replace(old, new, 1)

    # Import the scanner lazily to keep hook startup fast
    from guardian.cartographer import scan_telegram_commands

    tmp_path = path.parent / f".{path.name}.guardian.tmp"
    try:
        tmp_path.write_text(future_content, encoding="utf-8")
        scan = scan_telegram_commands(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    handler_names = {h["name"].replace("cmd_", "") for h in scan.get("handlers", [])}
    dict_keys = {k.lstrip("/") for k in scan.get("handlers_dict_keys", [])}
    menu = set(scan.get("menu_commands", []))
    help_set = {h.lstrip("/") for h in scan.get("help_mentions", [])}
    guide_set = {h.lstrip("/") for h in scan.get("guide_mentions", [])}

    missing: list[str] = []
    for cmd in sorted(handler_names):
        gaps = []
        if cmd not in dict_keys:
            gaps.append("HANDLERS dict")
        if cmd not in menu:
            gaps.append("_set_telegram_commands() menu")
        if cmd not in help_set:
            gaps.append("cmd_help")
        if cmd not in guide_set:
            gaps.append("cmd_guide")
        if gaps:
            missing.append(f"cmd_{cmd}: missing from {', '.join(gaps)}")

    if missing:
        return GateResult(
            allow=False,
            rule="telegram-completeness",
            reason=(
                "Telegram command registration incomplete. "
                "Per CLAUDE.md, every new command must be registered in "
                "HANDLERS, _set_telegram_commands(), cmd_help, and cmd_guide. "
                "Missing:\n  " + "\n  ".join(missing)
            ),
        )

    return None
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_gate_telegram_rule.py -v 2>&1 | tail -20
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/gate.py guardian/tests/test_gate_telegram_rule.py
git commit -m "feat(guardian): gate rule — telegram-completeness

Blocks Edit/Write to cli/telegram_bot.py that would leave any cmd_X
handler unregistered in HANDLERS, _set_telegram_commands() menu,
cmd_help, or cmd_guide. Enforces the CLAUDE.md checklist mechanically.
GUARDIAN_RULE_TELEGRAM_COMPLETENESS kill switch.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Gate rules — parallel-track-warning + recent-delete-guard

**Files:**
- Modify: `agent-cli/guardian/gate.py` — add two rules
- Create: `agent-cli/guardian/tests/test_gate_parallel_rule.py`
- Create: `agent-cli/guardian/tests/test_gate_delete_rule.py`

- [ ] **Step 1: Write failing tests**

Write `agent-cli/guardian/tests/test_gate_parallel_rule.py`:
```python
"""Tests for the parallel-track-warning gate rule."""
from __future__ import annotations

from pathlib import Path

from guardian.gate import check_tool_use


def test_rule_allows_new_distinct_file(tmp_path: Path, monkeypatch):
    (tmp_path / "cartographer.py").write_text("# cartographer")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(tmp_path / "risk_manager.py"), "content": "# risk"},
    )
    assert result.allow is True


def test_rule_blocks_near_duplicate(tmp_path: Path, monkeypatch):
    (tmp_path / "memory_manager.py").write_text('"""manages memory"""')
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Write",
        tool_input={
            "file_path": str(tmp_path / "memory_manager_v2.py"),
            "content": '"""manages memory better"""',
        },
    )
    assert result.allow is False
    assert "memory_manager" in (result.reason or "")
    assert result.rule == "parallel-track-warning"


def test_rule_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_RULE_PARALLEL_TRACK", "0")
    (tmp_path / "memory_manager.py").write_text("x")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(tmp_path / "memory_manager_v2.py"), "content": "y"},
    )
    assert result.allow is True
```

Write `agent-cli/guardian/tests/test_gate_delete_rule.py`:
```python
"""Tests for the recent-delete-guard gate rule."""
from __future__ import annotations

import os
import time
from pathlib import Path

from guardian.gate import check_tool_use


def test_rule_allows_delete_of_old_file(tmp_path: Path, monkeypatch):
    old = tmp_path / "old.py"
    old.write_text("x")
    # Set ctime/mtime to 30 days ago
    t = time.time() - 30 * 86400
    os.utime(old, (t, t))
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Bash",
        tool_input={"command": f"rm {old}"},
    )
    assert result.allow is True


def test_rule_blocks_delete_of_recent_file(tmp_path: Path, monkeypatch):
    recent = tmp_path / "recent.py"
    recent.write_text("x")
    # Keep mtime as now
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Bash",
        tool_input={"command": f"rm {recent}"},
    )
    assert result.allow is False
    assert "recent.py" in (result.reason or "")


def test_rule_ignores_non_delete_bash_commands(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Bash",
        tool_input={"command": "ls -la"},
    )
    assert result.allow is True


def test_rule_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_RULE_RECENT_DELETE", "0")
    recent = tmp_path / "recent.py"
    recent.write_text("x")
    monkeypatch.chdir(tmp_path)
    result = check_tool_use(
        tool_name="Bash",
        tool_input={"command": f"rm {recent}"},
    )
    assert result.allow is True
```

- [ ] **Step 2: Run to verify tests fail**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_gate_parallel_rule.py guardian/tests/test_gate_delete_rule.py -v 2>&1 | tail -20
```

Expected: blocking tests fail (rules not registered yet).

- [ ] **Step 3: Implement the two rules**

Append to `agent-cli/guardian/gate.py`:
```python
# ---------- Rule: parallel-track-warning ----------

@register_rule("parallel-track-warning")
def _rule_parallel_track_warning(tool_name: str, tool_input: dict[str, Any]) -> GateResult | None:
    """Warn when creating a new .py file with a name overlapping an existing one."""
    if tool_name != "Write":
        return None

    file_path = tool_input.get("file_path", "")
    if not file_path.endswith(".py"):
        return None

    path = Path(file_path)
    if path.exists():
        # Not a new file
        return None

    # Scan nearby .py files (same dir + repo root + one level down)
    search_dirs: list[Path] = []
    cwd = Path.cwd()
    search_dirs.append(cwd)
    if path.parent != cwd:
        search_dirs.append(path.parent)

    existing_names: set[str] = set()
    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.glob("*.py"):
            if f == path:
                continue
            existing_names.add(f.stem)
        # One level down
        for sub in d.glob("*/*.py"):
            if sub == path:
                continue
            existing_names.add(sub.stem)

    from guardian.drift import _similarity

    new_stem = path.stem
    matches: list[tuple[str, float]] = []
    for other in existing_names:
        sim = _similarity(new_stem, other)
        if sim >= 0.6:
            matches.append((other, sim))

    if matches:
        matches.sort(key=lambda t: -t[1])
        top = matches[0]
        return GateResult(
            allow=False,
            rule="parallel-track-warning",
            reason=(
                f"Creating '{path.name}' but a similar file exists: "
                f"'{top[0]}.py' (similarity {top[1]:.0%}). "
                f"Possible parallel track. Merge into the existing file or "
                f"set GUARDIAN_RULE_PARALLEL_TRACK=0 to override."
            ),
        )
    return None


# ---------- Rule: recent-delete-guard ----------

import re as _re
import time as _time

_RM_RE = _re.compile(r"\brm\s+(?:-[a-zA-Z]+\s+)?([^\s;&|]+)")


@register_rule("recent-delete-guard")
def _rule_recent_delete_guard(tool_name: str, tool_input: dict[str, Any]) -> GateResult | None:
    """Block `rm` of files that were created or modified in the last 7 days."""
    if tool_name != "Bash":
        return None

    cmd = tool_input.get("command", "")
    if "rm " not in cmd and not cmd.strip().startswith("rm "):
        return None

    targets: list[str] = _RM_RE.findall(cmd)
    if not targets:
        return None

    threshold = _time.time() - 7 * 86400
    recent_hits: list[str] = []
    for t in targets:
        p = Path(t)
        if not p.exists():
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if mtime > threshold:
            recent_hits.append(str(p))

    if recent_hits:
        return GateResult(
            allow=False,
            rule="recent-delete-guard",
            reason=(
                f"Blocking `rm` of file(s) modified in the last 7 days: "
                f"{', '.join(recent_hits)}. "
                f"Confirm with user or set GUARDIAN_RULE_RECENT_DELETE=0 to override."
            ),
        )
    return None
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_gate_parallel_rule.py guardian/tests/test_gate_delete_rule.py -v 2>&1 | tail -25
```

Expected: 7 tests pass (3 parallel + 4 delete).

- [ ] **Step 5: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/gate.py guardian/tests/test_gate_parallel_rule.py guardian/tests/test_gate_delete_rule.py
git commit -m "feat(guardian): gate rules — parallel-track + recent-delete

parallel-track-warning blocks creation of new .py files whose name
shares >=60% token overlap with an existing file in the same dir or
cwd (catches memory_manager_v2 next to memory_manager).

recent-delete-guard blocks 'rm X' in Bash when X was modified in the
last 7 days. Both kill-switchable.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Gate rule — stale-adr-guard

**Files:**
- Modify: `agent-cli/guardian/gate.py` — add rule + session-read tracker
- Create: `agent-cli/guardian/tests/test_gate_stale_adr_rule.py`

- [ ] **Step 1: Write the failing test**

Write `agent-cli/guardian/tests/test_gate_stale_adr_rule.py`:
```python
"""Tests for the stale-adr-guard gate rule."""
from __future__ import annotations

from pathlib import Path

from guardian.gate import check_tool_use, mark_file_read, reset_session_reads


def test_rule_allows_adr_edit_after_required_reads(tmp_path: Path, monkeypatch):
    reset_session_reads()
    adr_dir = tmp_path / "docs" / "wiki" / "decisions"
    adr_dir.mkdir(parents=True)
    adr_file = adr_dir / "015-new.md"
    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True)
    master = plans_dir / "MASTER_PLAN.md"
    audit = plans_dir / "AUDIT_FIX_PLAN.md"
    master.write_text("x")
    audit.write_text("x")

    mark_file_read(str(master))
    mark_file_read(str(audit))

    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(adr_file), "content": "# ADR-015"},
    )
    assert result.allow is True


def test_rule_blocks_adr_without_reading_master_plan(tmp_path: Path, monkeypatch):
    reset_session_reads()
    adr_dir = tmp_path / "docs" / "wiki" / "decisions"
    adr_dir.mkdir(parents=True)
    adr_file = adr_dir / "016-new.md"
    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "MASTER_PLAN.md").write_text("x")
    (plans_dir / "AUDIT_FIX_PLAN.md").write_text("x")

    # Only mark AUDIT_FIX_PLAN as read — not MASTER_PLAN
    mark_file_read(str(plans_dir / "AUDIT_FIX_PLAN.md"))

    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(adr_file), "content": "# ADR-016"},
    )
    assert result.allow is False
    assert "MASTER_PLAN" in (result.reason or "")
    assert result.rule == "stale-adr-guard"


def test_rule_kill_switch(tmp_path: Path, monkeypatch):
    reset_session_reads()
    monkeypatch.setenv("GUARDIAN_RULE_STALE_ADR", "0")
    adr_file = tmp_path / "docs" / "wiki" / "decisions" / "017-new.md"
    adr_file.parent.mkdir(parents=True)
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(adr_file), "content": "# ADR-017"},
    )
    assert result.allow is True


def test_rule_ignores_non_adr_files(tmp_path: Path, monkeypatch):
    reset_session_reads()
    other = tmp_path / "some_file.py"
    result = check_tool_use(
        tool_name="Write",
        tool_input={"file_path": str(other), "content": "x"},
    )
    assert result.allow is True
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_gate_stale_adr_rule.py -v 2>&1 | tail -20
```

Expected: `ImportError` — `mark_file_read`, `reset_session_reads` don't exist.

- [ ] **Step 3: Implement the rule + session-state helpers**

Append to `agent-cli/guardian/gate.py`:
```python
# ---------- Session state: track which files have been Read this session ----------
#
# The session_start hook writes a marker file; each Read tool call via a
# companion hook (future) or explicit mark_file_read() call updates it.
# For Phase 1 we expose mark_file_read as a public helper and tests use it
# directly. Phase 5 can wire a PostToolUse hook to auto-mark Read calls.

_SESSION_READS_FILE = Path("/tmp/guardian_session_reads.txt")


def reset_session_reads() -> None:
    """Clear the in-session read tracker (used at session start and in tests)."""
    try:
        if _SESSION_READS_FILE.exists():
            _SESSION_READS_FILE.unlink()
    except OSError:
        pass


def mark_file_read(path: str) -> None:
    """Record that a file has been Read during this session."""
    try:
        _SESSION_READS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _SESSION_READS_FILE.open("a", encoding="utf-8") as f:
            f.write(str(Path(path).resolve()) + "\n")
    except OSError:
        pass


def _has_been_read(name: str) -> bool:
    """True if any Read target's path ends with `name`."""
    if not _SESSION_READS_FILE.exists():
        return False
    try:
        lines = _SESSION_READS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(line.endswith(name) for line in lines if line)


# ---------- Rule: stale-adr-guard ----------

@register_rule("stale-adr-guard")
def _rule_stale_adr_guard(tool_name: str, tool_input: dict[str, Any]) -> GateResult | None:
    """Block Edit/Write to docs/wiki/decisions/ without MASTER_PLAN + AUDIT_FIX_PLAN reads."""
    if tool_name not in ("Edit", "Write"):
        return None

    file_path = tool_input.get("file_path", "")
    if "/docs/wiki/decisions/" not in file_path and "\\docs\\wiki\\decisions\\" not in file_path:
        return None

    missing: list[str] = []
    if not _has_been_read("MASTER_PLAN.md"):
        missing.append("docs/plans/MASTER_PLAN.md")
    if not _has_been_read("AUDIT_FIX_PLAN.md"):
        missing.append("docs/plans/AUDIT_FIX_PLAN.md")

    if missing:
        return GateResult(
            allow=False,
            rule="stale-adr-guard",
            reason=(
                "Attempting to write an ADR without reading required context first. "
                "Per CLAUDE.md and the 2026-04-07 postmortem, ADRs must be written "
                "against current state. Read these files first:\n  "
                + "\n  ".join(missing)
                + "\n\nThen retry. Or set GUARDIAN_RULE_STALE_ADR=0 to override."
            ),
        )
    return None
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_gate_stale_adr_rule.py -v 2>&1 | tail -20
```

Expected: 4 tests pass.

- [ ] **Step 5: Run the full guardian test suite**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/ -v 2>&1 | tail -40
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/gate.py guardian/tests/test_gate_stale_adr_rule.py
git commit -m "feat(guardian): gate rule — stale-adr-guard

Blocks Edit/Write to docs/wiki/decisions/ unless MASTER_PLAN.md and
AUDIT_FIX_PLAN.md have been marked read in the current session.
Enforces the 2026-04-07 postmortem rule mechanically. Session reads
tracked in /tmp/guardian_session_reads.txt. Kill switch
GUARDIAN_RULE_STALE_ADR.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Friction Surfacer

Ships: log-based friction pattern detection, surfaced silently in the SessionStart report.

---

### Task 13: Friction — log reader + repeated-correction pattern

**Files:**
- Create: `agent-cli/guardian/friction.py`
- Create: `agent-cli/guardian/tests/test_friction_patterns.py`

- [ ] **Step 1: Write the failing test**

Write `agent-cli/guardian/tests/test_friction_patterns.py`:
```python
"""Tests for friction pattern detection."""
from __future__ import annotations

import json
from pathlib import Path

from guardian.friction import (
    detect_repeated_corrections,
    detect_recurring_errors,
    read_jsonl,
)


def test_read_jsonl_handles_missing_file(tmp_path: Path):
    result = read_jsonl(tmp_path / "does_not_exist.jsonl")
    assert result == []


def test_read_jsonl_parses_valid_entries(tmp_path: Path):
    f = tmp_path / "log.jsonl"
    f.write_text('{"a": 1}\n{"a": 2}\n')
    result = read_jsonl(f)
    assert result == [{"a": 1}, {"a": 2}]


def test_read_jsonl_skips_malformed_lines(tmp_path: Path):
    f = tmp_path / "log.jsonl"
    f.write_text('{"a": 1}\nNOT JSON\n{"a": 2}\n')
    result = read_jsonl(f)
    assert result == [{"a": 1}, {"a": 2}]


def test_detects_repeated_corrections():
    entries = [
        {"type": "user_correction", "subject": "SL_BRENTOIL", "timestamp": "2026-04-01T10:00:00Z"},
        {"type": "user_correction", "subject": "SL_BRENTOIL", "timestamp": "2026-04-02T10:00:00Z"},
        {"type": "user_correction", "subject": "SL_BRENTOIL", "timestamp": "2026-04-03T10:00:00Z"},
        {"type": "user_correction", "subject": "TP_BTC", "timestamp": "2026-04-03T11:00:00Z"},
    ]
    findings = detect_repeated_corrections(entries, threshold=3)
    subjects = {f["subject"] for f in findings}
    assert "SL_BRENTOIL" in subjects
    assert "TP_BTC" not in subjects


def test_detects_recurring_errors():
    entries = [
        {"level": "error", "message": "connection timeout", "timestamp": "2026-04-01T10:00:00Z"},
        {"level": "error", "message": "connection timeout", "timestamp": "2026-04-02T10:00:00Z"},
        {"level": "error", "message": "connection timeout", "timestamp": "2026-04-03T10:00:00Z"},
        {"level": "error", "message": "unrelated error", "timestamp": "2026-04-03T11:00:00Z"},
    ]
    findings = detect_recurring_errors(entries, threshold=3)
    msgs = {f["message"] for f in findings}
    assert "connection timeout" in msgs
    assert "unrelated error" not in msgs
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_friction_patterns.py -v 2>&1 | tail -20
```

Expected: `ImportError`.

- [ ] **Step 3: Implement friction.py**

Write `agent-cli/guardian/friction.py`:
```python
"""Guardian friction surfacer — reads user logs, detects recurring pain.

Pure stdlib. Read-only on all log files. Outputs friction_report.json
+ friction_report.md with severity-tagged findings.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------- Kill switch ----------

def is_enabled() -> bool:
    return os.environ.get("GUARDIAN_FRICTION_ENABLED", "1") != "0"


# ---------- JSONL reader ----------

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file and return list of dicts. Skips malformed lines."""
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries


# ---------- Pattern: repeated corrections ----------

def detect_repeated_corrections(
    entries: list[dict[str, Any]],
    threshold: int = 3,
) -> list[dict[str, Any]]:
    """Flag user corrections on the same subject appearing >= threshold times.

    Each entry must have at least {"type": "user_correction", "subject": "..."}.
    """
    counts: Counter[str] = Counter()
    latest: dict[str, str] = {}
    for e in entries:
        if e.get("type") != "user_correction":
            continue
        subj = e.get("subject")
        if not subj:
            continue
        counts[subj] += 1
        ts = e.get("timestamp", "")
        if ts > latest.get(subj, ""):
            latest[subj] = ts

    findings: list[dict[str, Any]] = []
    for subj, count in counts.items():
        if count >= threshold:
            findings.append({
                "subject": subj,
                "count": count,
                "last_seen": latest.get(subj, ""),
                "severity": "P0" if count >= 5 else "P1",
                "reason": f"User corrected '{subj}' {count} times — recurring fight",
            })
    return findings


# ---------- Pattern: recurring errors ----------

def detect_recurring_errors(
    entries: list[dict[str, Any]],
    threshold: int = 3,
) -> list[dict[str, Any]]:
    """Flag error messages appearing >= threshold times.

    Each entry must have at least {"level": "error", "message": "..."}.
    """
    counts: Counter[str] = Counter()
    latest: dict[str, str] = {}
    for e in entries:
        if e.get("level") != "error":
            continue
        msg = e.get("message")
        if not msg:
            continue
        counts[msg] += 1
        ts = e.get("timestamp", "")
        if ts > latest.get(msg, ""):
            latest[msg] = ts

    findings: list[dict[str, Any]] = []
    for msg, count in counts.items():
        if count >= threshold:
            findings.append({
                "message": msg,
                "count": count,
                "last_seen": latest.get(msg, ""),
                "severity": "P1",
                "reason": f"Error '{msg}' repeated {count} times",
            })
    return findings
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_friction_patterns.py -v 2>&1 | tail -20
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/friction.py guardian/tests/test_friction_patterns.py
git commit -m "feat(guardian): friction surfacer — logs + repeated-correction + errors

Pure-stdlib JSONL reader (read_jsonl) tolerant of malformed lines.
detect_repeated_corrections() flags user_correction entries with
same subject >=3 times (P0 at >=5). detect_recurring_errors()
flags error messages >=3 times. GUARDIAN_FRICTION_ENABLED kill switch.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Friction — report builder + writer

**Files:**
- Modify: `agent-cli/guardian/friction.py` — add `build_friction_report()`, `write_friction_report()`
- Create: `agent-cli/guardian/tests/test_friction_report.py`

- [ ] **Step 1: Write the failing test**

Write `agent-cli/guardian/tests/test_friction_report.py`:
```python
"""Tests for friction report builder and writer."""
from __future__ import annotations

import json
from pathlib import Path

from guardian.friction import build_friction_report, write_friction_report


def test_build_report_on_empty_logs(tmp_path: Path):
    report = build_friction_report(
        feedback_path=tmp_path / "nope.jsonl",
        chat_history_path=tmp_path / "nope.jsonl",
    )
    assert report["summary"]["total"] == 0
    assert report["corrections"] == []
    assert report["errors"] == []


def test_build_report_with_signals(tmp_path: Path):
    fb = tmp_path / "feedback.jsonl"
    fb.write_text(
        '\n'.join([
            '{"type":"user_correction","subject":"SL_BRENTOIL","timestamp":"2026-04-01"}',
            '{"type":"user_correction","subject":"SL_BRENTOIL","timestamp":"2026-04-02"}',
            '{"type":"user_correction","subject":"SL_BRENTOIL","timestamp":"2026-04-03"}',
        ]) + '\n'
    )
    report = build_friction_report(
        feedback_path=fb,
        chat_history_path=tmp_path / "nope.jsonl",
    )
    assert report["summary"]["total"] >= 1


def test_write_report_creates_files(tmp_path: Path):
    report = build_friction_report(
        feedback_path=tmp_path / "nope.jsonl",
        chat_history_path=tmp_path / "nope.jsonl",
    )
    out = tmp_path / "state"
    write_friction_report(report, out)
    assert (out / "friction_report.json").exists()
    assert (out / "friction_report.md").exists()
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_friction_report.py -v 2>&1 | tail -20
```

Expected: `ImportError`.

- [ ] **Step 3: Implement report builder and writer**

Append to `agent-cli/guardian/friction.py`:
```python
# ---------- Report builder ----------

def build_friction_report(
    feedback_path: Path,
    chat_history_path: Path,
) -> dict[str, Any]:
    """Read the two main log files and assemble a friction report."""
    from datetime import datetime, timezone

    feedback = read_jsonl(feedback_path)
    chat = read_jsonl(chat_history_path)
    combined = feedback + chat

    corrections = detect_repeated_corrections(combined)
    errors = detect_recurring_errors(combined)

    all_findings = [*corrections, *errors]
    p0 = sum(1 for f in all_findings if f.get("severity") == "P0")
    p1 = sum(1 for f in all_findings if f.get("severity") == "P1")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "feedback_count": len(feedback),
            "chat_history_count": len(chat),
        },
        "corrections": corrections,
        "errors": errors,
        "summary": {
            "p0_count": p0,
            "p1_count": p1,
            "total": len(all_findings),
        },
    }


# ---------- Report writer ----------

def write_friction_report(report: dict[str, Any], state_dir: Path) -> None:
    """Write friction_report.json + friction_report.md."""
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "friction_report.json").write_text(json.dumps(report, indent=2))

    lines = ["# Friction Report", "", f"Generated: {report.get('timestamp', 'unknown')}", ""]
    summary = report.get("summary", {})
    lines.append(f"**{summary.get('p0_count', 0)} P0** · **{summary.get('p1_count', 0)} P1** · **{summary.get('total', 0)} total**")
    lines.append("")

    if report.get("corrections"):
        lines.append("## Repeated Corrections")
        for c in sorted(report["corrections"], key=lambda x: -x.get("count", 0)):
            lines.append(f"- **[{c['severity']}]** `{c['subject']}` — {c['count']} times (last {c.get('last_seen', '?')})")
        lines.append("")

    if report.get("errors"):
        lines.append("## Recurring Errors")
        for e in sorted(report["errors"], key=lambda x: -x.get("count", 0)):
            lines.append(f"- **[{e['severity']}]** `{e['message']}` — {e['count']} times")
        lines.append("")

    (state_dir / "friction_report.md").write_text("\n".join(lines) + "\n")
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_friction_report.py -v 2>&1 | tail -20
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/friction.py guardian/tests/test_friction_report.py
git commit -m "feat(guardian): friction report builder + writer

build_friction_report() reads feedback.jsonl + chat_history.jsonl,
runs the pattern detectors, emits P0/P1 tagged findings with summary.
write_friction_report() outputs friction_report.json + .md.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5 — Orchestrator + Sub-Agent Dispatch

Ships: sweep.py orchestrator, SessionStart hook upgraded to dispatch a background sub-agent when state is stale, advisor sub-agent prompt.

---

### Task 15: sweep.py orchestrator

**Files:**
- Create: `agent-cli/guardian/sweep.py`
- Create: `agent-cli/guardian/tests/test_sweep.py`

- [ ] **Step 1: Write the failing test**

Write `agent-cli/guardian/tests/test_sweep.py`:
```python
"""Tests for guardian/sweep.py orchestrator."""
from __future__ import annotations

import json
from pathlib import Path

from guardian.sweep import run_sweep


def test_sweep_on_empty_repo_produces_all_outputs(tmp_repo: Path):
    state_dir = tmp_repo / "guardian" / "state"
    run_sweep(repo_root=tmp_repo, state_dir=state_dir)
    assert (state_dir / "inventory.json").exists()
    assert (state_dir / "drift_report.json").exists()
    assert (state_dir / "friction_report.json").exists()
    assert (state_dir / "sweep.log").exists()


def test_sweep_returns_summary(tmp_repo: Path):
    state_dir = tmp_repo / "guardian" / "state"
    summary = run_sweep(repo_root=tmp_repo, state_dir=state_dir)
    assert "modules" in summary
    assert "drift_p0" in summary
    assert "friction_p0" in summary
    assert "duration_s" in summary


def test_sweep_respects_global_kill_switch(tmp_repo: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_ENABLED", "0")
    state_dir = tmp_repo / "guardian" / "state"
    summary = run_sweep(repo_root=tmp_repo, state_dir=state_dir)
    assert summary.get("skipped") is True
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_sweep.py -v 2>&1 | tail -20
```

Expected: `ImportError`.

- [ ] **Step 3: Implement sweep.py**

Write `agent-cli/guardian/sweep.py`:
```python
"""Guardian sweep orchestrator — runs the Tier 1 pipeline end-to-end.

Called by:
- SessionStart hook (directly or via a background sub-agent)
- The /guardian slash command
- Manual invocation: `python -m guardian.sweep`

Produces:
- state/inventory.json + map.mmd + map.md
- state/drift_report.json + drift_report.md
- state/friction_report.json + friction_report.md
- state/sweep.log (append-only)
- state/current_report.md (minimal — Phase 5 sub-agent will replace this)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def is_enabled() -> bool:
    return os.environ.get("GUARDIAN_ENABLED", "1") != "0"


def _log_line(state_dir: Path, msg: str) -> None:
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with (state_dir / "sweep.log").open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
    except OSError:
        pass


def run_sweep(repo_root: Path, state_dir: Path | None = None) -> dict[str, Any]:
    """Run cartographer → drift → friction → compile current_report.md.

    Returns a summary dict:
        {modules, drift_p0, drift_p1, friction_p0, friction_p1, duration_s}
    or {skipped: True} if Guardian is globally disabled.
    """
    if not is_enabled():
        return {"skipped": True, "reason": "GUARDIAN_ENABLED=0"}

    if state_dir is None:
        state_dir = repo_root / "guardian" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    _log_line(state_dir, "sweep start")

    # --- Tier 1: cartographer ---
    from guardian.cartographer import build_inventory, write_inventory
    try:
        inventory = build_inventory(repo_root)
        write_inventory(inventory, state_dir)
        _log_line(state_dir, f"cartographer ok — {inventory['stats']['module_count']} modules")
    except Exception as e:
        _log_line(state_dir, f"cartographer error: {type(e).__name__}: {e}")
        inventory = {"modules": [], "edges": [], "telegram": {}, "iterators": [], "stats": {}}

    # --- Tier 1: drift ---
    from guardian.drift import build_drift_report, write_drift_report
    prev_path = state_dir / "inventory.prev.json"
    prev_inventory = None
    if prev_path.exists():
        try:
            prev_inventory = json.loads(prev_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    try:
        drift_report = build_drift_report(inventory, prev_inventory)
        write_drift_report(drift_report, state_dir)
        _log_line(state_dir, f"drift ok — {drift_report['summary']['total']} findings")
    except Exception as e:
        _log_line(state_dir, f"drift error: {type(e).__name__}: {e}")
        drift_report = {"summary": {"p0_count": 0, "p1_count": 0, "total": 0}, "orphans": [], "parallel_tracks": [], "telegram_gaps": [], "plan_mismatches": []}

    # --- Tier 1: friction ---
    from guardian.friction import build_friction_report, write_friction_report
    feedback_path = repo_root / "data" / "feedback.jsonl"
    chat_path = repo_root / "data" / "daemon" / "chat_history.jsonl"
    try:
        friction_report = build_friction_report(
            feedback_path=feedback_path,
            chat_history_path=chat_path,
        )
        write_friction_report(friction_report, state_dir)
        _log_line(state_dir, f"friction ok — {friction_report['summary']['total']} findings")
    except Exception as e:
        _log_line(state_dir, f"friction error: {type(e).__name__}: {e}")
        friction_report = {"summary": {"p0_count": 0, "p1_count": 0, "total": 0}, "corrections": [], "errors": []}

    # --- Assemble minimal current_report.md (Phase 5 sub-agent will replace this) ---
    _write_current_report(state_dir, inventory, drift_report, friction_report)

    duration = time.monotonic() - start
    _log_line(state_dir, f"sweep done in {duration:.2f}s")

    return {
        "modules": inventory.get("stats", {}).get("module_count", 0),
        "drift_p0": drift_report.get("summary", {}).get("p0_count", 0),
        "drift_p1": drift_report.get("summary", {}).get("p1_count", 0),
        "friction_p0": friction_report.get("summary", {}).get("p0_count", 0),
        "friction_p1": friction_report.get("summary", {}).get("p1_count", 0),
        "duration_s": round(duration, 2),
    }


def _write_current_report(
    state_dir: Path,
    inventory: dict[str, Any],
    drift_report: dict[str, Any],
    friction_report: dict[str, Any],
) -> None:
    """Compile a minimal current_report.md from the tier-1 outputs.

    Phase 5 replaces this with a sub-agent synthesis. Until then this is a
    straightforward concatenation of the high-severity findings.
    """
    stats = inventory.get("stats", {})
    drift_sum = drift_report.get("summary", {})
    fric_sum = friction_report.get("summary", {})

    lines = [
        "# Guardian Current Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## State",
        f"- {stats.get('module_count', 0)} Python modules",
        f"- {stats.get('telegram_handler_count', 0)} Telegram handlers",
        f"- {stats.get('iterator_count', 0)} daemon iterators",
        "",
        "## Drift",
        f"- {drift_sum.get('p0_count', 0)} P0, {drift_sum.get('p1_count', 0)} P1, {drift_sum.get('total', 0)} total",
    ]

    # Include up to 3 P0 drift findings
    p0_drift = [f for f in (drift_report.get("orphans", []) + drift_report.get("parallel_tracks", []) + drift_report.get("telegram_gaps", []) + drift_report.get("plan_mismatches", [])) if f.get("severity") == "P0"][:3]
    if p0_drift:
        lines.append("")
        lines.append("### Top drift P0")
        for f in p0_drift:
            name = f.get("name") or f.get("command") or f.get("a") or f.get("reference") or "?"
            lines.append(f"- `{name}` — {f.get('reason', '')}")

    lines.extend([
        "",
        "## Friction",
        f"- {fric_sum.get('p0_count', 0)} P0, {fric_sum.get('p1_count', 0)} P1, {fric_sum.get('total', 0)} total",
    ])

    p0_fric = [c for c in friction_report.get("corrections", []) if c.get("severity") == "P0"][:3]
    if p0_fric:
        lines.append("")
        lines.append("### Top friction P0")
        for c in p0_fric:
            lines.append(f"- `{c['subject']}` corrected {c['count']} times")

    lines.extend([
        "",
        "_Phase 5 will replace this with a sub-agent synthesis._",
        "",
    ])

    (state_dir / "current_report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    summary = run_sweep(repo_root)
    print(json.dumps(summary, indent=2))
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_sweep.py -v 2>&1 | tail -20
```

Expected: 3 tests pass.

- [ ] **Step 5: Run a real sweep on the actual repo**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m guardian.sweep 2>&1 | tail -10
```

Expected: JSON summary with non-zero `modules`, duration under 10 seconds. Inspect `guardian/state/current_report.md` for sanity.

- [ ] **Step 6: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/sweep.py guardian/tests/test_sweep.py
git commit -m "feat(guardian): sweep.py orchestrator — tier-1 pipeline end-to-end

run_sweep() runs cartographer → drift → friction, writes all outputs
to state/, assembles a minimal current_report.md, and logs to sweep.log.
Exception-wrapped per component — if cartographer fails, drift + friction
still run. Invocable via python -m guardian.sweep.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: SessionStart hook — sub-agent dispatch + sweep execution

**Files:**
- Modify: `agent-cli/.claude/hooks/session_start.py` — add staleness check + sweep invocation
- Modify: `agent-cli/guardian/tests/test_session_start_hook.py` — add tests for staleness-triggered sweep

- [ ] **Step 1: Extend the test file**

Append to `agent-cli/guardian/tests/test_session_start_hook.py`:
```python
def test_hook_runs_sweep_when_no_report(tmp_path: Path, monkeypatch):
    # Minimal fake repo so sweep has something to look at
    (tmp_path / "guardian" / "state").mkdir(parents=True)
    (tmp_path / "cli" / "daemon" / "iterators").mkdir(parents=True)
    (tmp_path / "cli" / "telegram_bot.py").write_text("HANDLERS = {}\n")
    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.chdir(tmp_path)
    mod = _load_hook()
    result = mod.build_summary(
        state_dir=tmp_path / "guardian" / "state",
        repo_root=tmp_path,
    )
    # Should either trigger a sweep or report no report
    assert isinstance(result, str)


def test_hook_subagent_dispatch_kill_switch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GUARDIAN_SUBAGENTS_ENABLED", "0")
    (tmp_path / "guardian" / "state").mkdir(parents=True)
    mod = _load_hook()
    # Hook should not error even with sub-agents disabled
    result = mod.build_summary(
        state_dir=tmp_path / "guardian" / "state",
        repo_root=tmp_path,
    )
    assert isinstance(result, str)
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_session_start_hook.py -v 2>&1 | tail -20
```

Expected: new tests error out because `build_summary` does not accept `repo_root`.

- [ ] **Step 3: Upgrade the hook to run a sweep when state is stale**

Replace the contents of `agent-cli/.claude/hooks/session_start.py` with:
```python
#!/usr/bin/env python3
"""Guardian SessionStart hook — compact state injection + lazy sweep.

If guardian/state/current_report.md is absent or older than 24h, run the
tier-1 sweep synchronously before injecting state. The sweep is pure
stdlib and typically <5s on the current repo.

Sub-agent dispatch for natural-language synthesis is Claude's job — the
hook leaves a marker for Claude to pick up if GUARDIAN_SUBAGENTS_ENABLED
is set. Claude then dispatches a background sub-agent via the Agent tool.
Fails open on any error.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def is_enabled() -> bool:
    return os.environ.get("GUARDIAN_ENABLED", "1") != "0"


def is_subagent_dispatch_enabled() -> bool:
    return os.environ.get("GUARDIAN_SUBAGENTS_ENABLED", "1") != "0"


def _report_age_hours(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 3600.0


def _maybe_run_sweep(repo_root: Path, state_dir: Path) -> None:
    """Run a sweep if state is stale. Silent on all errors."""
    report = state_dir / "current_report.md"
    should_run = False
    if not report.exists():
        should_run = True
    else:
        try:
            if _report_age_hours(report) > 24:
                should_run = True
        except OSError:
            should_run = True

    if not should_run:
        return

    try:
        # Make guardian importable
        sys.path.insert(0, str(repo_root))
        from guardian.sweep import run_sweep
        run_sweep(repo_root=repo_root, state_dir=state_dir)
    except Exception:
        pass


def build_summary(
    state_dir: Path | None = None,
    repo_root: Path | None = None,
) -> str:
    """Build the compact summary string to inject into Claude's context.

    Returns an empty string if Guardian is disabled. Never raises.
    """
    if not is_enabled():
        return ""

    try:
        if repo_root is None:
            repo_root = Path(__file__).resolve().parents[2]
        if state_dir is None:
            state_dir = repo_root / "guardian" / "state"

        state_dir = Path(state_dir)
        repo_root = Path(repo_root)

        # Reset the per-session reads tracker for the stale-adr-guard rule
        try:
            from guardian.gate import reset_session_reads
            reset_session_reads()
        except Exception:
            pass

        # Lazy sweep if state is missing or stale
        _maybe_run_sweep(repo_root, state_dir)

        if not state_dir.exists():
            return "## Guardian\nNo state directory — Guardian has not yet been initialized.\n"

        report = state_dir / "current_report.md"
        if not report.exists():
            return "## Guardian\nNo current report. Sweep did not produce output — check guardian/state/sweep.log.\n"

        age_hours = _report_age_hours(report)
        stale_marker = ""
        if age_hours > 24:
            stale_marker = f" ⚠️ stale ({age_hours:.0f}h old)"

        body = report.read_text(encoding="utf-8")
        lines = body.split("\n")
        if len(lines) > 200:
            body = "\n".join(lines[:200]) + f"\n\n... ({len(lines) - 200} more lines in guardian/state/current_report.md)"

        header = f"## Guardian{stale_marker}\n\n"
        if is_subagent_dispatch_enabled():
            header += (
                "_If the tier-1 report above is missing the natural-language "
                "synthesis Claude normally writes, dispatch a `guardian-sweep` "
                "background sub-agent via the Agent tool (general-purpose, "
                "run_in_background=true) to refresh `guardian/state/current_report.md`._\n\n"
            )

        return header + body + "\n"

    except Exception as e:
        return f"## Guardian\n(hook error: {type(e).__name__}; see guardian/state/sweep.log)\n"


def main() -> int:
    summary = build_summary()
    if summary:
        sys.stdout.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/test_session_start_hook.py -v 2>&1 | tail -25
```

Expected: all 6 tests pass (4 from Task 5 + 2 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add .claude/hooks/session_start.py guardian/tests/test_session_start_hook.py
git commit -m "feat(guardian): SessionStart hook runs lazy sweep + dispatch marker

Hook now runs tier-1 sweep when current_report.md is missing or older
than 24h (lazy refresh). Resets the per-session reads tracker used by
the stale-adr-guard rule. When GUARDIAN_SUBAGENTS_ENABLED=1 it adds a
header note telling Claude to dispatch a background guardian-sweep
sub-agent for natural-language synthesis.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 17: /guardian slash command (manual sweep escape hatch)

**Files:**
- Create: `agent-cli/.claude/commands/guardian.md`

- [ ] **Step 1: Write the slash command definition**

Write `agent-cli/.claude/commands/guardian.md`:
```markdown
---
description: Force a Guardian sweep now (reruns cartographer, drift, friction)
---

Run a Guardian sweep immediately.

Steps:

1. Dispatch a background sub-agent via the Agent tool with subagent_type="general-purpose" and run_in_background=true. Prompt:

```
Run Guardian tier-1 sweep for HyperLiquid_Bot.

Steps:
1. cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
2. Run: .venv/bin/python -m guardian.sweep
3. Read the printed JSON summary
4. Read guardian/state/current_report.md
5. Read guardian/state/drift_report.md
6. Read guardian/state/friction_report.md
7. Synthesize a natural-language report covering:
   - One-paragraph state summary
   - Up to 3 P0 findings (action required)
   - Up to 5 P1 findings (investigate soon)
   - Questions worth asking
8. Write the synthesis to guardian/state/current_report.md (overwrite the stub)
9. Return a 3-line summary

Target: complete in under 5000 tokens.
```

2. Tell the user: "Guardian sweep dispatched in the background. I'll surface findings when it completes, or you can ask `what does guardian say` at any time to check."

3. Continue with the user's other work. When the sub-agent completes, read `guardian/state/current_report.md` and surface P0 findings naturally.
```

- [ ] **Step 2: Verify the file is readable**

Run:
```bash
cat /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/.claude/commands/guardian.md
```

Expected: the full command content prints.

- [ ] **Step 3: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add .claude/commands/guardian.md
git commit -m "feat(guardian): /guardian slash command — force sweep now

Manual escape hatch for when the user wants a fresh Guardian report
mid-session. Dispatches a background sub-agent that runs the sweep,
reads the tier-1 outputs, writes a natural-language synthesis to
current_report.md, and returns asynchronously. Documented in guide.md.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase 6 — Lock-in (Guide, ADR, Wiki, Plan)

Ships: final guide, ADR-014, wiki component page, GUARDIAN_PLAN.md status table, MASTER_PLAN.md cross-link, CLAUDE.md pointer.

---

### Task 18: Finalize guide.md + update /guide command

**Files:**
- Modify: `agent-cli/guardian/guide.md` — update Phase status to reflect all 6 phases shipped

- [ ] **Step 1: Update the guide status section**

Read `agent-cli/guardian/guide.md` and replace the "Current status" section (and anything after it) with:

```markdown
## Current status

All 6 phases shipped.

- **Phase 1 — Foundation:** cartographer (imports + Telegram + iterators), SessionStart hook, state directory, guide stub.
- **Phase 2 — Drift:** orphan detection, parallel-track detection, Telegram completeness gap reporting, plan/code mismatch, report writer.
- **Phase 3 — Gate:** PreToolUse hook with four rules — telegram-completeness, parallel-track-warning, recent-delete-guard, stale-adr-guard. Each individually kill-switchable.
- **Phase 4 — Friction:** repeated-correction pattern, recurring-error pattern, friction report builder + writer.
- **Phase 5 — Orchestrator + sub-agents:** `sweep.py` runs the full tier-1 pipeline; SessionStart hook runs a lazy sweep when state is stale; `/guardian` slash command dispatches a background sub-agent for natural-language synthesis.
- **Phase 6 — Lock-in:** this guide, ADR-014, `docs/wiki/components/guardian.md`, `docs/plans/GUARDIAN_PLAN.md`, cross-links in MASTER_PLAN.md and root CLAUDE.md.

See `docs/plans/GUARDIAN_PLAN.md` for the full status table with commit hashes.

## How to extend Guardian

- **Add a drift rule:** write a new function in `guardian/drift.py`, call it from `build_drift_report()`, write a test in `guardian/tests/`.
- **Add a friction pattern:** write a new detector in `guardian/friction.py`, call it from `build_friction_report()`, write a test.
- **Add a gate rule:** write a new function in `guardian/gate.py` decorated with `@register_rule("rule-name")`, add a kill switch env var, write a test.
- **Add a new kill switch:** document it in the Kill Switches table above.

## Known limits

- Guardian only runs while a Claude Code session is active. It cannot observe drift or friction that occurs outside of sessions.
- The parallel-track-warning rule uses a 60% Jaccard token similarity threshold and can produce false positives on files that legitimately share naming conventions.
- The stale-adr-guard rule tracks session reads via `/tmp/guardian_session_reads.txt`. On multi-user systems this could theoretically be racy — acceptable for a single-user dev setup.
- The friction surfacer assumes entries in `feedback.jsonl` have `type: "user_correction"` and `subject` fields; entries in other schemas are ignored. Extend `detect_repeated_corrections()` if the schema evolves.

## Failure modes

See `docs/wiki/decisions/014-guardian-system.md` §Risks for the full list.
```

- [ ] **Step 2: Verify the guide is well-formed**

Run:
```bash
wc -l /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/guardian/guide.md
head -5 /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/guardian/guide.md
```

Expected: non-zero line count, `# Guardian Angel — User Guide` as the first line.

- [ ] **Step 3: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add guardian/guide.md
git commit -m "docs(guardian): finalize guide with all 6 phases shipped

Updated status section to reflect Phase 1-6 completion, added 'How to
extend Guardian' section (drift rules, friction patterns, gate rules,
kill switches), documented known limits and failure modes.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 19: ADR-014, wiki component page, GUARDIAN_PLAN, cross-links

**Files:**
- Create: `agent-cli/docs/wiki/decisions/014-guardian-system.md`
- Create: `agent-cli/docs/wiki/components/guardian.md`
- Create: `agent-cli/docs/plans/GUARDIAN_PLAN.md`
- Modify: `agent-cli/docs/plans/MASTER_PLAN.md` — add one line pointing at GUARDIAN_PLAN.md
- Modify: `agent-cli/docs/wiki/README.md` — add ADR-014 to the decisions table
- Modify: `CLAUDE.md` (root) — add one bullet under Workflow

- [ ] **Step 1: Write ADR-014**

**IMPORTANT:** the `stale-adr-guard` gate rule from Task 12 will block writing to `docs/wiki/decisions/` unless MASTER_PLAN.md and AUDIT_FIX_PLAN.md have been read in this session. Before attempting to write ADR-014, use the Read tool on:
- `agent-cli/docs/plans/MASTER_PLAN.md`
- `agent-cli/docs/plans/AUDIT_FIX_PLAN.md`

Then write `agent-cli/docs/wiki/decisions/014-guardian-system.md`:
```markdown
# ADR-014: Guardian Angel — Dev-Side Meta-System

**Status:** Accepted
**Date:** 2026-04-09
**Supersedes:** none

## Context

The HyperLiquid_Bot codebase has grown past the point where any single person (or Claude session) can hold the full architecture in working memory. Chris reported six recurring failure modes:

1. Parallel tracks — new work built without integrating with existing work
2. UI-completeness gap — features shipping in code but not reaching Telegram
3. Recurring fights becoming invisible signals (e.g., repeatedly canceling auto-set SL/TPs)
4. Inability to see architectural connections visually
5. Orphaning of old good work during scope pivots
6. Reactive-only Claude behavior — Chris leads every insight

The 2026-04-07 hardening postmortem documented a concrete instance of failure mode 5 + operating on stale state: a ~600-line ADR was drafted against a repo picture that was already obsolete, wasting a brainstorming pass.

## Decision

Build Guardian Angel — a dev-side meta-system that:

1. Runs **only** while a Claude Code dev session is active. Never on cron, never in the trading agent's runtime loop, never pushing to Telegram.
2. Uses a **three-tier architecture**:
   - **Tier 1 — silent workers** (pure Python, stdlib only): `cartographer.py`, `drift.py`, `friction.py`, `gate.py`
   - **Tier 2 — background sub-agents** (dispatched via the Agent tool during active sessions, `run_in_background=true`) for natural-language synthesis
   - **Tier 3 — surface point** (SessionStart hook + PreToolUse gate): Claude reads the report silently and surfaces P0 findings in natural language, or says nothing
3. Lives entirely under `agent-cli/guardian/` + `agent-cli/.claude/hooks/` + `agent-cli/.claude/commands/`.
4. Has **zero external dependencies** (Python stdlib + Mermaid for graph output).
5. Has **kill switches on every component** (one env var each, plus `GUARDIAN_ENABLED` as global override).
6. Is **read-only** on all runtime trading data paths.

## Consequences

### Positive
- Parallel-track creation is mechanically blocked by the PreToolUse gate.
- Telegram UI-completeness is enforced by the gate rather than by human memory.
- The `/tmp/guardian_session_reads.txt` tracker + `stale-adr-guard` rule mechanically prevents the 2026-04-07 failure mode.
- Recurring user fights (SL/TP cancel loops) become visible at session start without requiring Chris to remember to check.
- Sub-agent synthesis gives Chris proactive insights without token cost when he's not working.

### Negative
- Adds ~1500 lines of Python and 6 new config files to the repo.
- First session after a long absence takes ~5s longer while the lazy sweep runs.
- Gate rules can produce false positives (all kill-switchable).
- Sub-agent dispatch costs a small but non-zero number of tokens per stale session.

## Alternatives Considered

### Alternative 1: Scheduled cron / `scheduled-tasks` MCP
Rejected. Chris explicitly said "the agent is a trader, not a self-reviewer." Running Guardian on cron would piggyback on the trading agent's operational footprint and introduce a separate autonomous Claude invocation path. In-session dispatch keeps Guardian entirely within the dev workflow.

### Alternative 2: Slash-command-heavy interface (`/map`, `/drift`, `/friction`, `/suggest`)
Rejected. Chris said "I don't want to have to run those commands." Commands-you-must-remember add cognitive load rather than reducing it. The only user-facing slash commands are `/guide` (read the contract) and `/guardian` (force a refresh).

### Alternative 3: Inline in the trading daemon
Rejected. The daemon is load-bearing and any modification risks trading safety. Guardian must not share a process space or runtime loop with trading code.

## Implementation

See:
- Design spec: `docs/superpowers/specs/2026-04-09-guardian-angel-design.md`
- Implementation plan: `docs/superpowers/plans/2026-04-09-guardian-angel.md`
- Phase status table: `docs/plans/GUARDIAN_PLAN.md`
- User guide: `guardian/guide.md`

## Risks

- **False positives in gate rules** — mitigated by per-rule kill switches and gradual rollout (one rule enabled per commit).
- **Sub-agent token costs** — mitigated by lazy dispatch (only when state is stale) and a 5000-token budget cap per sub-agent run.
- **State file corruption** — mitigated by `rm -rf guardian/state/` as a safe reset; the next sweep rebuilds from scratch.
- **Hook breakage blocking Claude Code** — mitigated by fail-open exception handling in both hooks (`session_start.py` and `pre_tool_use.py`).

## Supersession

This ADR is self-contained and supersedes nothing. If Guardian is ever retired or restructured, a successor ADR should reference this one.
```

- [ ] **Step 2: Write the wiki component page**

Write `agent-cli/docs/wiki/components/guardian.md`:
```markdown
# Guardian Angel

**Purpose:** Dev-side meta-system that prevents architectural drift and surfaces recurring pain while Claude Code is working in the repo.

**Scope:** Dev-only. Never runs in the trading daemon. Never touches agent runtime, agent prompts, auth, or runtime data paths.

## Architecture

Three tiers:

1. **Silent workers** (pure Python stdlib): `guardian/cartographer.py`, `guardian/drift.py`, `guardian/friction.py`, `guardian/gate.py`, `guardian/sweep.py`
2. **Background sub-agents** (dispatched via the Agent tool during active sessions): runs `guardian.sweep.run_sweep()` then synthesizes a natural-language report
3. **Surface point** (hooks + Claude's judgment): `.claude/hooks/session_start.py`, `.claude/hooks/pre_tool_use.py`

See ADR-014 for the full rationale.

## Key files

| File | Responsibility |
|---|---|
| `guardian/cartographer.py` | Scans the repo, builds `inventory.json` + `map.mmd` |
| `guardian/drift.py` | Detects orphans, parallel tracks, Telegram gaps, plan/code mismatches |
| `guardian/friction.py` | Reads user logs, detects repeated corrections and recurring errors |
| `guardian/gate.py` | PreToolUse rule dispatcher. Registered rules: `telegram-completeness`, `parallel-track-warning`, `recent-delete-guard`, `stale-adr-guard` |
| `guardian/sweep.py` | Runs the tier-1 pipeline end-to-end, writes `current_report.md` |
| `guardian/guide.md` | User-facing contract document |
| `.claude/hooks/session_start.py` | SessionStart hook — injects state into Claude's context, lazy sweep |
| `.claude/hooks/pre_tool_use.py` | PreToolUse hook — runs gate.py checks |
| `.claude/commands/guide.md` | `/guide` slash command |
| `.claude/commands/guardian.md` | `/guardian` manual sweep command |

## State files (gitignored)

| File | Contents |
|---|---|
| `guardian/state/inventory.json` | Current wiring inventory |
| `guardian/state/inventory.prev.json` | Previous inventory (for drift diff) |
| `guardian/state/map.mmd` | Mermaid graph |
| `guardian/state/map.md` | Summary stats |
| `guardian/state/drift_report.{json,md}` | Drift findings |
| `guardian/state/friction_report.{json,md}` | Friction findings |
| `guardian/state/current_report.md` | Compiled report read by SessionStart hook |
| `guardian/state/sweep.log` | Append-only sweep log |

## Kill switches

See `guardian/guide.md` for the full table. Global off: `GUARDIAN_ENABLED=0`.

## Testing

```bash
cd agent-cli && .venv/bin/python -m pytest guardian/tests/ -x -q
```

Fixtures live in `guardian/tests/fixtures/`. Tests use real tmp dirs (no filesystem mocks).

## Related documents

- ADR-014 — `docs/wiki/decisions/014-guardian-system.md`
- Design spec — `docs/superpowers/specs/2026-04-09-guardian-angel-design.md`
- Implementation plan — `docs/superpowers/plans/2026-04-09-guardian-angel.md`
- Phase status — `docs/plans/GUARDIAN_PLAN.md`
- User guide — `guardian/guide.md`
```

- [ ] **Step 3: Write GUARDIAN_PLAN.md status table**

Write `agent-cli/docs/plans/GUARDIAN_PLAN.md`:
```markdown
# Guardian Angel — Phase Status

**Source spec:** `docs/superpowers/specs/2026-04-09-guardian-angel-design.md`
**Implementation plan:** `docs/superpowers/plans/2026-04-09-guardian-angel.md`
**ADR:** `docs/wiki/decisions/014-guardian-system.md`

## Status

| Phase | Task | Status | Notes |
|---|---|---|---|
| 1 | Task 1 — Package scaffold | shipped | |
| 1 | Task 2 — Cartographer imports | shipped | |
| 1 | Task 3 — Cartographer Telegram | shipped | |
| 1 | Task 4 — Cartographer iterators + inventory | shipped | |
| 1 | Task 5 — SessionStart hook (read-only) | shipped | |
| 1 | Task 6 — Guide stub + /guide | shipped | |
| 2 | Task 7 — Drift orphans + parallel tracks | shipped | |
| 2 | Task 8 — Drift Telegram + plan mismatches + report | shipped | |
| 3 | Task 9 — Gate skeleton + PreToolUse hook | shipped | no rules active yet |
| 3 | Task 10 — Gate rule telegram-completeness | shipped | |
| 3 | Task 11 — Gate rules parallel-track + recent-delete | shipped | |
| 3 | Task 12 — Gate rule stale-adr-guard | shipped | |
| 4 | Task 13 — Friction log reader + patterns | shipped | |
| 4 | Task 14 — Friction report | shipped | |
| 5 | Task 15 — sweep.py orchestrator | shipped | |
| 5 | Task 16 — SessionStart hook sub-agent dispatch | shipped | |
| 5 | Task 17 — /guardian slash command | shipped | |
| 6 | Task 18 — Guide finalize | shipped | |
| 6 | Task 19 — ADR-014 + wiki + cross-links | shipped | |

Commit hashes are in git log (search for `guardian`).

## Kill status

All kill switches default to ENABLED. See `guardian/guide.md` for the full table.

## Open questions (from spec §12)

- **Q1 (surface style):** Claude surfaces findings naturally in its first response (default chosen).
- **Q2 (sweep inputs):** Cartographer uses both snapshot diff and `git log --since` for drift context.
- **Q3 (slash commands):** `/guide` + `/guardian` shipped; no other commands planned.

## Kill switches ops

To silence Guardian entirely for one session: `GUARDIAN_ENABLED=0 claude`
To disable a single gate rule: e.g., `GUARDIAN_RULE_PARALLEL_TRACK=0`
To reset Guardian state: `rm -rf agent-cli/guardian/state/*` (next sweep rebuilds)
```

- [ ] **Step 4: Add one line to MASTER_PLAN.md**

Read `agent-cli/docs/plans/MASTER_PLAN.md` first. Find the "What's Next" section (or the section that lists active plans). Use the Edit tool to add one line:

```markdown
- **Dev infrastructure:** Guardian Angel meta-system — `docs/plans/GUARDIAN_PLAN.md` (auto-runs in Claude Code sessions; see `agent-cli/guardian/guide.md`)
```

Insert after the existing "What's Next After Oil Bot Pattern" bullets — do not disturb any other content.

- [ ] **Step 5: Add ADR-014 to wiki/README.md decisions table**

Read `agent-cli/docs/wiki/README.md`. Use the Edit tool to add one row to the Architecture Decisions table after ADR-009:

```markdown
| [014](decisions/014-guardian-system.md) | Guardian Angel | Dev-side meta-system — in-session cartography, drift, gate, friction, sub-agent synthesis |
```

- [ ] **Step 6: Add one bullet to root CLAUDE.md under Workflow**

Read `/Users/cdi/Developer/HyperLiquid_Bot/CLAUDE.md`. Use the Edit tool to add to the Workflow section:

```markdown
5. **Guardian Angel auto-runs.** Guardian is a dev-side meta-system that runs automatically on SessionStart and before Edit/Write/Bash tool calls. It catches parallel tracks, Telegram command gaps, and stale-state ADRs. Read `agent-cli/guardian/guide.md` for the contract, kill switches, and how to extend it. Never disable without reason.
```

- [ ] **Step 7: Run the full guardian test suite one last time**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m pytest guardian/tests/ -v 2>&1 | tail -50
```

Expected: all tests pass.

- [ ] **Step 8: Run a real end-to-end sweep on the actual repo and inspect the output**

Run:
```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && .venv/bin/python -m guardian.sweep && head -60 guardian/state/current_report.md
```

Expected: the sweep completes, current_report.md shows real module counts and any findings.

- [ ] **Step 9: Commit all of Phase 6**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add docs/wiki/decisions/014-guardian-system.md docs/wiki/components/guardian.md docs/plans/GUARDIAN_PLAN.md docs/plans/MASTER_PLAN.md docs/wiki/README.md
git commit -m "docs(guardian): ADR-014 + wiki page + GUARDIAN_PLAN + cross-links

ADR-014 documents the three-tier architecture, in-session-only
constraint, and rationale for rejecting the cron + command-heavy
alternatives. Wiki component page mirrors the existing component
template. GUARDIAN_PLAN.md shows the phase status table following
AUDIT_FIX_PLAN.md format. MASTER_PLAN and wiki README updated with
additive pointers only.

Closes: Guardian Angel Phase 6

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"

# Commit the root CLAUDE.md change separately because it is outside the git repo rooted at agent-cli/
# If agent-cli is a submodule or the repo is rooted higher, adapt accordingly. The Claude edit to
# /Users/cdi/Developer/HyperLiquid_Bot/CLAUDE.md may need manual staging.
```

**Note:** the root `CLAUDE.md` lives at `/Users/cdi/Developer/HyperLiquid_Bot/CLAUDE.md`, which is outside the `agent-cli/` git repo. If the engineer cannot commit it, they should note the uncommitted root-CLAUDE.md change in the task output and flag for manual handling.

---

## Summary

After completing all 19 tasks, Guardian Angel ships:

- **6 Python modules** in `agent-cli/guardian/` (stdlib only)
- **2 hooks** in `agent-cli/.claude/hooks/` (SessionStart + PreToolUse)
- **2 slash commands** in `agent-cli/.claude/commands/` (`/guide` + `/guardian`)
- **4 gate rules**, each kill-switchable
- **8 drift + friction detectors**
- **~40 tests** in `agent-cli/guardian/tests/`
- **1 ADR** (014), **1 wiki page**, **1 plan status table**, **1 user guide**, **2 cross-links** (MASTER_PLAN, wiki README), **1 root CLAUDE.md bullet**
- Zero external dependencies
- Zero modifications to trading runtime, agent runtime, agent prompts, auth, daemon iterators, or Telegram bot

The entire Guardian system can be silenced with `GUARDIAN_ENABLED=0` or removed entirely by deleting `agent-cli/guardian/`, `agent-cli/.claude/hooks/`, and `agent-cli/.claude/commands/{guide,guardian}.md`, plus reverting the `.gitignore` entry and the two cross-link edits.
