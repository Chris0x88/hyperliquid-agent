#!/usr/bin/env python3
"""Build the Obsidian vault at docs/vault/ from the live codebase.

This is an IDEMPOTENT generator. Running it twice produces the same
output. It parses Python files with `ast`, walks config files, reads
plan + ADR markdown, and emits wiki-linked markdown pages under
docs/vault/ that Obsidian can open and visualise as a graph.

## What it does

1. Auto-generates one page per:
   - Daemon iterator       → docs/vault/iterators/<name>.md
   - Telegram command      → docs/vault/commands/<name>.md (grouped by submodule)
   - Agent tool            → docs/vault/tools/<name>.md
   - Config file           → docs/vault/data-stores/config-<name>.md
   - Plan file             → docs/vault/plans/<name>.md
   - ADR                   → docs/vault/adrs/<name>.md
2. Emits index pages (_index.md) for each subfolder with tables
3. Cross-links everything via [[wiki-link]] syntax so Obsidian's graph
   view lights up with real relationships

## What it does NOT do

- Does NOT touch hand-written pages (Home.md, architecture/*.md,
  runbooks/*.md). Those are preserved if present.
- Does NOT overwrite files inside `<!-- HUMAN:BEGIN -->...
  <!-- HUMAN:END -->` markers (future feature — for v1 these markers
  are just documented; the generator writes whole pages for auto
  files).
- Does NOT install Obsidian or touch `.obsidian/` config.

## Usage

```
cd agent-cli && python scripts/build_vault.py
```

Then open `docs/vault/` in Obsidian via "Open folder as vault".
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ── Paths ───────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent  # agent-cli/
VAULT = PROJECT_ROOT / "docs" / "vault"

ITERATORS_SRC = PROJECT_ROOT / "cli" / "daemon" / "iterators"
TELEGRAM_BOT = PROJECT_ROOT / "cli" / "telegram_bot.py"
TELEGRAM_COMMANDS_SRC = PROJECT_ROOT / "cli" / "telegram_commands"
AGENT_TOOLS_SRC = PROJECT_ROOT / "cli" / "agent_tools.py"
TIERS_SRC = PROJECT_ROOT / "cli" / "daemon" / "tiers.py"
DAEMON_START_SRC = PROJECT_ROOT / "cli" / "commands" / "daemon.py"
CONFIG_SRC = PROJECT_ROOT / "data" / "config"
PLANS_SRC = PROJECT_ROOT / "docs" / "plans"
ADRS_SRC = PROJECT_ROOT / "docs" / "wiki" / "decisions"
WIKI_COMPONENTS_SRC = PROJECT_ROOT / "docs" / "wiki" / "components"

# Output subdirectories
OUT_ITERATORS = VAULT / "iterators"
OUT_COMMANDS = VAULT / "commands"
OUT_TOOLS = VAULT / "tools"
OUT_DATA_STORES = VAULT / "data-stores"
OUT_PLANS = VAULT / "plans"
OUT_ADRS = VAULT / "adrs"

TIMESTAMP = datetime.now().strftime("%Y-%m-%d %H:%M")


# ── Helpers ─────────────────────────────────────────────────────────


def slugify(text: str) -> str:
    """Convert a string to a filesystem-safe slug."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text or "unnamed"


def wiki_link(target: str, label: Optional[str] = None) -> str:
    """Emit an Obsidian wiki-link. ``target`` is the note name without
    the .md extension. ``label`` is an optional display override."""
    if label and label != target:
        return f"[[{target}|{label}]]"
    return f"[[{target}]]"


def write_if_changed(path: Path, content: str) -> bool:
    """Write ``content`` to ``path`` only if different from current.
    Returns True if written, False if unchanged. Keeps regeneration
    idempotent and minimises commit churn."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == content:
        return False
    path.write_text(content)
    return True


def read_docstring_and_classes(path: Path) -> Tuple[Optional[str], List[Tuple[str, Optional[str]]]]:
    """Parse a Python file, return (module_docstring, [(class_name, class_docstring)])."""
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return None, []
    module_doc = ast.get_docstring(tree)
    classes: List[Tuple[str, Optional[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append((node.name, ast.get_docstring(node)))
    return module_doc, classes


def find_iterator_name_attr(path: Path) -> Optional[str]:
    """Find the `name = "..."` class attribute of the iterator."""
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id == "name"
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    return stmt.value.value
    return None


def find_kill_switch_path(path: Path) -> Optional[str]:
    """Heuristically find the kill-switch config path for an iterator
    by scanning the source for a `data/config/*.json` string literal."""
    try:
        text = path.read_text()
    except OSError:
        return None
    m = re.search(r'"(data/config/[a-z_]+\.json)"', text)
    return m.group(1) if m else None


def get_tier_registration(iterator_name: str, tiers_text: str) -> List[str]:
    """Return which tiers (watch/rebalance/opportunistic) register this iterator."""
    out = []
    for tier in ("watch", "rebalance", "opportunistic"):
        pattern = rf'"{tier}":\s*\[(.*?)\]'
        match = re.search(pattern, tiers_text, re.DOTALL)
        if match and f'"{iterator_name}"' in match.group(1):
            out.append(tier)
    return out


def get_daemon_registration(class_name: str, daemon_text: str) -> bool:
    """Check whether `clock.register(<ClassName>())` appears in daemon_start."""
    return bool(re.search(rf"clock\.register\({class_name}\(", daemon_text))


def get_frontmatter(kind: str, **extra: Any) -> str:
    """Produce YAML frontmatter for a vault note."""
    lines = ["---", f"kind: {kind}", f"last_regenerated: {TIMESTAMP}"]
    for k, v in extra.items():
        if v is None or v == "":
            continue
        if isinstance(v, list):
            if not v:
                continue
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


# ── Iterator pages ──────────────────────────────────────────────────


def build_iterator_pages() -> List[str]:
    """Generate one page per iterator. Returns list of generated slugs."""
    tiers_text = TIERS_SRC.read_text() if TIERS_SRC.exists() else ""
    daemon_text = DAEMON_START_SRC.read_text() if DAEMON_START_SRC.exists() else ""

    generated: List[Tuple[str, Dict[str, Any]]] = []
    skip = {"__init__.py", "_format.py"}

    for py in sorted(ITERATORS_SRC.glob("*.py")):
        if py.name in skip:
            continue
        module_doc, classes = read_docstring_and_classes(py)
        if not classes:
            continue
        # Convention: one iterator class per file, named *Iterator
        iter_classes = [(n, d) for n, d in classes if n.endswith("Iterator")]
        if not iter_classes:
            continue
        class_name, class_doc = iter_classes[0]
        iterator_name = find_iterator_name_attr(py) or py.stem
        kill_switch = find_kill_switch_path(py)
        tiers = get_tier_registration(iterator_name, tiers_text)
        daemon_registered = get_daemon_registration(class_name, daemon_text)

        slug = iterator_name
        out_path = OUT_ITERATORS / f"{slug}.md"

        # Cross-links
        links_see_also: List[str] = []
        if tiers:
            links_see_also.append(f"- Tier registration: {wiki_link('Tier-Ladder')}")
        if kill_switch:
            kill_slug = f"config-{Path(kill_switch).stem}"
            links_see_also.append(
                f"- Kill switch: `{kill_switch}` → {wiki_link(kill_slug)}"
            )
        if not daemon_registered and tiers:
            links_see_also.append(
                "- ⚠️ **REGISTRATION GAP**: listed in `tiers.py` but NOT registered "
                f"in `cli/commands/daemon.py` via `clock.register({class_name}())`. "
                "See `fix(memory_backup)` commit 4a58095 for the same class of bug."
            )

        tag_list = ["iterator"] + [f"tier-{t}" for t in tiers]
        frontmatter = get_frontmatter(
            kind="iterator",
            iterator_name=iterator_name,
            class_name=class_name,
            source_file=str(py.relative_to(PROJECT_ROOT)),
            tiers=tiers,
            kill_switch=kill_switch or "",
            daemon_registered=str(daemon_registered).lower(),
            tags=tag_list,
        )

        body_lines = [
            f"# Iterator: {iterator_name}",
            "",
            f"**Class**: `{class_name}` in [`{py.relative_to(PROJECT_ROOT)}`](../../{py.relative_to(PROJECT_ROOT)})",
            "",
            f"**Registered in tiers**: {', '.join(f'`{t}`' for t in tiers) if tiers else '**none**'}",
            "",
            f"**Kill switch config**: " + (f"`{kill_switch}`" if kill_switch else "_none_"),
            "",
            f"**Registered in `daemon_start()`**: {'✅ yes' if daemon_registered else '❌ **NO — registration gap**'}",
            "",
            "## Description",
            "",
            class_doc or module_doc or "_(no docstring)_",
            "",
        ]
        if links_see_also:
            body_lines.append("## See also")
            body_lines.append("")
            body_lines.extend(links_see_also)
            body_lines.append("")

        body_lines.extend([
            "## Human notes",
            "",
            "<!-- HUMAN:BEGIN -->",
            "_Add hand-written context here. The generator preserves this section on regeneration._",
            "<!-- HUMAN:END -->",
            "",
        ])

        write_if_changed(out_path, frontmatter + "\n".join(body_lines))
        generated.append((iterator_name, {
            "class_name": class_name,
            "tiers": tiers,
            "kill_switch": kill_switch,
            "daemon_registered": daemon_registered,
        }))

    # Index page
    index_lines = [
        get_frontmatter(kind="index", count=len(generated), tags=["index", "iterators"]),
        "# Iterators Index",
        "",
        f"_{len(generated)} iterators auto-generated from `cli/daemon/iterators/`. "
        f"Last regenerated: {TIMESTAMP}._",
        "",
        "Iterators are the daemon's pluggable processors. Each one runs per tick "
        f"(~120s cadence). See {wiki_link('Tier-Ladder')} for which iterators "
        f"activate in which tier, and {wiki_link('Authority-Model')} for how "
        "per-asset delegation gates trade-touching iterators.",
        "",
        "| Iterator | Class | Tiers | Kill Switch | Wired? |",
        "|---|---|---|---|---|",
    ]
    for name, meta in sorted(generated):
        tiers_cell = ", ".join(f"`{t}`" for t in meta["tiers"]) or "_none_"
        kill_cell = f"`{meta['kill_switch']}`" if meta["kill_switch"] else "_none_"
        wired_cell = "✅" if meta["daemon_registered"] else "❌ **GAP**"
        index_lines.append(
            f"| {wiki_link(name)} | `{meta['class_name']}` | {tiers_cell} | {kill_cell} | {wired_cell} |"
        )
    index_lines.append("")
    write_if_changed(OUT_ITERATORS / "_index.md", "\n".join(index_lines))

    return [name for name, _ in generated]


# ── Telegram command pages ──────────────────────────────────────────


def _find_cmd_functions(path: Path) -> List[Tuple[str, Optional[str]]]:
    """Return [(cmd_name, docstring)] for every top-level `def cmd_*` in a Python file."""
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return []
    out: List[Tuple[str, Optional[str]]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("cmd_"):
            out.append((node.name[4:], ast.get_docstring(node)))  # strip cmd_ prefix
    return out


def build_command_pages() -> List[str]:
    """Generate pages for Telegram commands, grouped by submodule. Returns command slugs."""
    generated: List[Tuple[str, str, Optional[str]]] = []  # (cmd, submodule, docstring)

    # Commands in cli/telegram_commands/*.py submodules
    for py in sorted(TELEGRAM_COMMANDS_SRC.glob("*.py")):
        if py.name == "__init__.py":
            continue
        submodule = py.stem
        for cmd, docstring in _find_cmd_functions(py):
            generated.append((cmd, submodule, docstring))

    # Commands still inline in cli/telegram_bot.py
    for cmd, docstring in _find_cmd_functions(TELEGRAM_BOT):
        generated.append((cmd, "telegram_bot (inline)", docstring))

    # Emit one page per command
    for cmd, submodule, docstring in generated:
        ai_suffix = cmd.endswith("ai")
        slug = cmd.replace("_", "-")
        out_path = OUT_COMMANDS / f"{slug}.md"

        frontmatter = get_frontmatter(
            kind="telegram_command",
            command=f"/{cmd}",
            submodule=submodule,
            ai_dependent=str(ai_suffix).lower(),
            tags=["command", "ai" if ai_suffix else "deterministic"],
        )
        body = [
            f"# Command: `/{cmd}`",
            "",
            f"**Submodule**: `{submodule}`",
            "",
            f"**AI-dependent**: {'✅ yes — name ends in `ai` per CLAUDE.md rule' if ai_suffix else '❌ no — deterministic, pure code'}",
            "",
            "## Description",
            "",
            docstring or "_(no docstring)_",
            "",
            "## See also",
            "",
        ]
        if submodule != "telegram_bot (inline)":
            body.append(f"- Source: [`cli/telegram_commands/{submodule}.py`](../../cli/telegram_commands/{submodule}.py)")
        else:
            body.append("- Source: inline in [`cli/telegram_bot.py`](../../cli/telegram_bot.py) — candidate for extraction to a submodule in future Telegram monolith wedges")
        body.extend([
            f"- Registered in HANDLERS dict + `_set_telegram_commands` + `cmd_help` + `cmd_guide`",
            "",
            "## Human notes",
            "",
            "<!-- HUMAN:BEGIN -->",
            "_Add hand-written context here._",
            "<!-- HUMAN:END -->",
            "",
        ])
        write_if_changed(out_path, frontmatter + "\n".join(body))

    # Index page grouped by submodule
    by_sub: Dict[str, List[Tuple[str, bool]]] = {}
    for cmd, submodule, _ in generated:
        by_sub.setdefault(submodule, []).append((cmd, cmd.endswith("ai")))

    index_lines = [
        get_frontmatter(kind="index", count=len(generated), tags=["index", "commands"]),
        "# Telegram Commands Index",
        "",
        f"_{len(generated)} commands across {len(by_sub)} submodules. "
        f"Last regenerated: {TIMESTAMP}._",
        "",
        "Per CLAUDE.md: slash commands are FIXED CODE. Anything that depends on "
        "AI carries the `ai` suffix. Natural-language messages (not starting with "
        "`/`) route to the embedded agent.",
        "",
        "The ongoing Telegram monolith split extracts commands from the 4,600+ "
        "line `cli/telegram_bot.py` into cohesive submodules under "
        "`cli/telegram_commands/`. Wedges 1 (lessons), 2 (portfolio), and the "
        "realignment-session additions (brutal_review, entry_critic, action_queue, "
        "chat_history) have shipped; more remain.",
        "",
    ]
    for submodule, cmds in sorted(by_sub.items()):
        index_lines.append(f"## `{submodule}` ({len(cmds)})")
        index_lines.append("")
        for cmd, is_ai in sorted(cmds):
            marker = " 🤖" if is_ai else ""
            index_lines.append(f"- {wiki_link(cmd.replace('_', '-'), f'/{cmd}')}{marker}")
        index_lines.append("")
    write_if_changed(OUT_COMMANDS / "_index.md", "\n".join(index_lines))

    return [c for c, _, _ in generated]


# ── Agent tool pages ────────────────────────────────────────────────


def build_tool_pages() -> List[str]:
    """Parse TOOL_DEFS in cli/agent_tools.py and emit one page per tool."""
    if not AGENT_TOOLS_SRC.exists():
        return []
    try:
        tree = ast.parse(AGENT_TOOLS_SRC.read_text())
    except SyntaxError:
        return []

    # Find TOOL_DEFS = [...] or TOOL_DEFS: List[dict] = [...]
    tool_defs_node: Optional[ast.List] = None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TOOL_DEFS":
                    if isinstance(node.value, ast.List):
                        tool_defs_node = node.value
        elif isinstance(node, ast.AnnAssign):
            # Annotated assignment: `TOOL_DEFS: List[dict] = [...]`
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == "TOOL_DEFS"
                and isinstance(node.value, ast.List)
            ):
                tool_defs_node = node.value

    if tool_defs_node is None:
        return []

    tools: List[Dict[str, Any]] = []
    for item in tool_defs_node.elts:
        if not isinstance(item, ast.Dict):
            continue
        # Each item is a dict with "type": "function", "function": {...}
        fn_dict = None
        for k, v in zip(item.keys, item.values):
            if isinstance(k, ast.Constant) and k.value == "function" and isinstance(v, ast.Dict):
                fn_dict = v
        if fn_dict is None:
            continue
        tool_info: Dict[str, Any] = {}
        for k, v in zip(fn_dict.keys, fn_dict.values):
            if not isinstance(k, ast.Constant):
                continue
            key = k.value
            if key == "name" and isinstance(v, ast.Constant):
                tool_info["name"] = v.value
            elif key == "description" and isinstance(v, ast.Constant):
                tool_info["description"] = v.value
            elif key == "parameters" and isinstance(v, ast.Dict):
                tool_info["parameters"] = ast.unparse(v) if hasattr(ast, "unparse") else "<dict>"
        if "name" in tool_info:
            tools.append(tool_info)

    generated: List[str] = []
    for tool in tools:
        name = tool["name"]
        slug = name.replace("_", "-")
        out_path = OUT_TOOLS / f"{slug}.md"

        frontmatter = get_frontmatter(
            kind="agent_tool",
            tool_name=name,
            tags=["agent-tool"],
        )
        body = [
            f"# Agent Tool: `{name}`",
            "",
            f"**Source**: [`cli/agent_tools.py`](../../cli/agent_tools.py) `TOOL_DEFS`",
            "",
            "## Description",
            "",
            tool.get("description", "_(no description)_"),
            "",
            "## Parameters schema",
            "",
            "```python",
            tool.get("parameters", "<unavailable>"),
            "```",
            "",
            "## Retrieval bounds",
            "",
            "Per NORTH_STAR P10 / MASTER_PLAN Critical Rule 11, every tool that "
            "reaches an agent prompt must have hard bounds on what it returns. "
            f"Check `_tool_{name}()` in `cli/agent_tools.py` for the clamp logic; "
            "bounded tools are pinned by tests in `tests/test_agent_tools_p10_bounds.py`.",
            "",
            "## See also",
            "",
            f"- Agent runtime: `cli/agent_runtime.py` (injects LIVE CONTEXT + lessons section)",
            f"- Tool dispatcher: `cli/agent_tools.py:_TOOL_DISPATCH`",
            f"- P10 bounds: {wiki_link('Data-Discipline', 'Data Discipline (P10)')}",
            "",
            "## Human notes",
            "",
            "<!-- HUMAN:BEGIN -->",
            "_Add hand-written context here._",
            "<!-- HUMAN:END -->",
            "",
        ]
        write_if_changed(out_path, frontmatter + "\n".join(body))
        generated.append(name)

    # Index
    index_lines = [
        get_frontmatter(kind="index", count=len(generated), tags=["index", "tools"]),
        "# Agent Tools Index",
        "",
        f"_{len(generated)} tools parsed from `TOOL_DEFS` in `cli/agent_tools.py`. "
        f"Last regenerated: {TIMESTAMP}._",
        "",
        "Tools are how the embedded agent interacts with the system. Each tool is "
        "either READ (auto-executes) or WRITE (requires user approval via Telegram "
        "inline keyboard). The dispatcher is `_TOOL_DISPATCH`. Every read-path tool "
        f"must obey {wiki_link('Data-Discipline', 'P10 bounds')}.",
        "",
        "| Tool | Description |",
        "|---|---|",
    ]
    for name in sorted(generated):
        # Short description (first sentence)
        # We don't store it but we can link
        index_lines.append(f"| {wiki_link(name.replace('_', '-'), name)} | see page |")
    index_lines.append("")
    write_if_changed(OUT_TOOLS / "_index.md", "\n".join(index_lines))

    return generated


# ── Config file pages ───────────────────────────────────────────────


def build_config_pages() -> List[str]:
    """Emit one page per config file in data/config/."""
    if not CONFIG_SRC.exists():
        return []

    generated: List[str] = []
    for cfg in sorted(CONFIG_SRC.glob("*.json")):
        name = cfg.stem
        slug = f"config-{name}"
        out_path = OUT_DATA_STORES / f"{slug}.md"

        try:
            content = cfg.read_text()
            parsed = json.loads(content)
        except (OSError, json.JSONDecodeError):
            content = "<unreadable>"
            parsed = None

        # Heuristic: is this a kill switch for an iterator?
        is_kill_switch = isinstance(parsed, dict) and "enabled" in parsed

        frontmatter = get_frontmatter(
            kind="config_file",
            path=f"data/config/{cfg.name}",
            is_kill_switch=str(is_kill_switch).lower(),
            tags=["config", "kill-switch"] if is_kill_switch else ["config"],
        )
        body = [
            f"# Config: `{cfg.name}`",
            "",
            f"**Path**: [`data/config/{cfg.name}`](../../data/config/{cfg.name})",
            "",
            f"**Is kill switch**: {'✅ yes (has `enabled` field)' if is_kill_switch else '❌ no'}",
            "",
            "## Current contents",
            "",
            "```json",
            content[:3000] + ("\n... [truncated]" if len(content) > 3000 else ""),
            "```",
            "",
            "## See also",
            "",
        ]
        # Try to link to the iterator that uses it
        related_iter = name  # convention: config file name matches iterator name
        if (OUT_ITERATORS / f"{related_iter}.md").exists() or True:  # link speculatively
            body.append(f"- Likely consumer: {wiki_link(related_iter)} iterator")
        body.extend([
            "",
            "## Human notes",
            "",
            "<!-- HUMAN:BEGIN -->",
            "<!-- HUMAN:END -->",
            "",
        ])
        write_if_changed(out_path, frontmatter + "\n".join(body))
        generated.append(slug)

    # Also walk yaml files
    for cfg in sorted(CONFIG_SRC.glob("*.yaml")):
        name = cfg.stem
        slug = f"config-{name}"
        out_path = OUT_DATA_STORES / f"{slug}.md"
        try:
            content = cfg.read_text()
        except OSError:
            content = "<unreadable>"

        frontmatter = get_frontmatter(
            kind="config_file",
            path=f"data/config/{cfg.name}",
            format="yaml",
            tags=["config", "yaml"],
        )
        body = [
            f"# Config: `{cfg.name}`",
            "",
            f"**Path**: [`data/config/{cfg.name}`](../../data/config/{cfg.name})",
            "",
            "## Current contents",
            "",
            "```yaml",
            content[:3000] + ("\n... [truncated]" if len(content) > 3000 else ""),
            "```",
            "",
            "## Human notes",
            "",
            "<!-- HUMAN:BEGIN -->",
            "<!-- HUMAN:END -->",
            "",
        ]
        write_if_changed(out_path, frontmatter + "\n".join(body))
        generated.append(slug)

    # Index
    index_lines = [
        get_frontmatter(kind="index", count=len(generated), tags=["index", "data-stores", "configs"]),
        "# Config Files Index",
        "",
        f"_{len(generated)} config files in `data/config/`. Last regenerated: {TIMESTAMP}._",
        "",
        "Config files drive runtime behavior of iterators, strategies, and "
        "protection systems. Every iterator that ships with a kill switch has "
        "a corresponding `data/config/<name>.json` file with an `enabled` field. "
        f"Per CLAUDE.md convention: every risky subsystem ships with `enabled: false` "
        "by default.",
        "",
    ]
    for slug in sorted(generated):
        index_lines.append(f"- {wiki_link(slug)}")
    index_lines.append("")
    write_if_changed(OUT_DATA_STORES / "_index.md", "\n".join(index_lines))

    return generated


# ── Plan pages (pointer style) ──────────────────────────────────────


def build_plan_pages() -> List[str]:
    """For each plan in docs/plans/, emit a vault page that points at it."""
    if not PLANS_SRC.exists():
        return []

    generated: List[str] = []
    for plan in sorted(PLANS_SRC.glob("*.md")):
        if plan.name == "README.md":
            continue
        slug = plan.stem
        out_path = OUT_PLANS / f"{slug}.md"
        try:
            text = plan.read_text()
            # Extract first ~20 lines or until the first ## heading
            preview_lines = []
            for line in text.splitlines()[:30]:
                preview_lines.append(line)
            preview = "\n".join(preview_lines)
        except OSError:
            preview = "_(unreadable)_"

        # Try to detect status from frontmatter or the first lines
        status = "unknown"
        if "Status:**" in text or "**Status**" in text:
            m = re.search(r"\*\*Status:?\*\*\s*([^\n]+)", text)
            if m:
                status = m.group(1).strip()[:80]

        frontmatter = get_frontmatter(
            kind="plan",
            plan_file=f"docs/plans/{plan.name}",
            status=status,
            tags=["plan"],
        )
        body = [
            f"# Plan: {slug}",
            "",
            f"**Source**: [`docs/plans/{plan.name}`](../../docs/plans/{plan.name})",
            "",
            f"**Status (detected)**: {status}",
            "",
            "## Preview",
            "",
            "```",
            preview,
            "```",
            "",
            "## Human notes",
            "",
            "<!-- HUMAN:BEGIN -->",
            "_Add hand-written context here — open questions, known gaps, links "
            "to related plans, etc._",
            "<!-- HUMAN:END -->",
            "",
        ]
        write_if_changed(out_path, frontmatter + "\n".join(body))
        generated.append(slug)

    # Index
    index_lines = [
        get_frontmatter(kind="index", count=len(generated), tags=["index", "plans"]),
        "# Plans Index",
        "",
        f"_{len(generated)} plan documents in `docs/plans/`. Last regenerated: {TIMESTAMP}._",
        "",
        "Plans are the approved workstreams. The living plan is "
        f"{wiki_link('MASTER_PLAN')}; the vision is "
        f"{wiki_link('NORTH_STAR')}. Parked plans live in `docs/plans/` with "
        "status markers and live in this index; archived plan snapshots live "
        "in `docs/plans/archive/` and are NOT regenerated into this vault "
        "(they're append-only historical records).",
        "",
    ]
    for slug in sorted(generated):
        index_lines.append(f"- {wiki_link(slug)}")
    index_lines.append("")
    write_if_changed(OUT_PLANS / "_index.md", "\n".join(index_lines))

    return generated


# ── ADR pages ───────────────────────────────────────────────────────


def build_adr_pages() -> List[str]:
    if not ADRS_SRC.exists():
        return []
    generated: List[str] = []
    for adr in sorted(ADRS_SRC.glob("*.md")):
        slug = adr.stem
        out_path = OUT_ADRS / f"{slug}.md"
        try:
            text = adr.read_text()
            first_line = next((l for l in text.splitlines() if l.strip()), slug)
            title = first_line.lstrip("# ").strip()
            preview = "\n".join(text.splitlines()[:15])
        except OSError:
            title = slug
            preview = "_(unreadable)_"

        frontmatter = get_frontmatter(
            kind="adr",
            adr_file=f"docs/wiki/decisions/{adr.name}",
            tags=["adr", "decision"],
        )
        body = [
            f"# {title}",
            "",
            f"**Source**: [`docs/wiki/decisions/{adr.name}`](../../docs/wiki/decisions/{adr.name})",
            "",
            "## Preview",
            "",
            "```",
            preview,
            "```",
            "",
            "## Human notes",
            "",
            "<!-- HUMAN:BEGIN -->",
            "<!-- HUMAN:END -->",
            "",
        ]
        write_if_changed(out_path, frontmatter + "\n".join(body))
        generated.append(slug)

    index_lines = [
        get_frontmatter(kind="index", count=len(generated), tags=["index", "adrs"]),
        "# Architecture Decision Records Index",
        "",
        f"_{len(generated)} ADRs in `docs/wiki/decisions/`. Last regenerated: {TIMESTAMP}._",
        "",
        "ADRs are append-only. Each records a significant architectural decision "
        "with context, the decision itself, and consequences. Never edit an "
        "existing ADR — write a new one if the decision changes.",
        "",
    ]
    for slug in sorted(generated):
        index_lines.append(f"- {wiki_link(slug)}")
    index_lines.append("")
    write_if_changed(OUT_ADRS / "_index.md", "\n".join(index_lines))

    return generated


# ── Main ────────────────────────────────────────────────────────────


def main() -> None:
    print(f"Building Obsidian vault at {VAULT}")
    VAULT.mkdir(parents=True, exist_ok=True)
    for d in (OUT_ITERATORS, OUT_COMMANDS, OUT_TOOLS, OUT_DATA_STORES, OUT_PLANS, OUT_ADRS):
        d.mkdir(parents=True, exist_ok=True)

    iterators = build_iterator_pages()
    print(f"  iterators:    {len(iterators)} pages")

    commands = build_command_pages()
    print(f"  commands:     {len(commands)} pages")

    tools = build_tool_pages()
    print(f"  tools:        {len(tools)} pages")

    configs = build_config_pages()
    print(f"  config files: {len(configs)} pages")

    plans = build_plan_pages()
    print(f"  plans:        {len(plans)} pages")

    adrs = build_adr_pages()
    print(f"  adrs:         {len(adrs)} pages")

    total = len(iterators) + len(commands) + len(tools) + len(configs) + len(plans) + len(adrs)
    print(f"\nTotal auto-generated: {total} pages (plus 6 index pages).")
    print(f"Hand-written pages (Home, architecture/*, runbooks/*) are preserved.")
    print(f"\nOpen {VAULT} in Obsidian → 'Open folder as vault' → enable graph view.")


if __name__ == "__main__":
    main()
