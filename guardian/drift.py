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

# Default entrypoint module tails that are allowed to have zero inbound edges.
# Matched against the last dotted component of each module name so
# `cli.telegram_bot` and `telegram_bot` both resolve to `telegram_bot`.
DEFAULT_ENTRYPOINTS: frozenset[str] = frozenset({
    "telegram_bot",
    "daemon",
    "agent_runtime",
    "telegram_agent",
    "main",
    "__main__",
    "__init__",  # package markers are never orphans by themselves
    "conftest",  # pytest conftest files are auto-discovered
    "sweep",  # guardian's own orchestrator
    # CLI / daemon entrypoints that are invoked by shell commands or
    # discovered by the daemon's iterator registry, not by Python imports
    "setup",
    "run",
    "daily_report",
    "mcp_server",
    "chart_engine",
    "telegram_handler",
    "risk_monitor",
})

# Path substrings that mark a module as a plug-in-style entrypoint even when
# nothing imports it by name (CLI sub-commands, daemon iterators, pytest tests,
# strategy plugins, shell scripts, Claude Code hooks). These are registered
# through discovery or entry-point mechanisms the cartographer can't see
# statically.
ENTRYPOINT_PATH_PATTERNS: tuple[str, ...] = (
    "cli/commands/",
    "cli/daemon/iterators/",
    "strategies/",
    "plugins/",
    "tests/",
    "guardian/tests/",
    "guardian/hooks/",  # Claude Code hooks — invoked by settings.json
    "scripts/",  # Standalone shell-invoked Python scripts
    "githooks/",  # Git hooks
)


def _is_entrypoint(module: dict[str, Any], entrypoints: set[str] | frozenset[str]) -> bool:
    """True if this module is allowed to have zero inbound imports.

    A module is an entrypoint if:
    - Its last dotted component matches an entry in `entrypoints`, OR
    - Its path contains any of the ENTRYPOINT_PATH_PATTERNS (plug-in style).
    """
    name = module.get("name", "")
    tail = name.rsplit(".", 1)[-1] if name else ""
    if tail in entrypoints or name in entrypoints:
        return True
    path = module.get("path", "")
    return any(pattern in path for pattern in ENTRYPOINT_PATH_PATTERNS)


def detect_orphans(
    inventory: dict[str, Any],
    entrypoints: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Find modules with zero inbound imports that are not entrypoints.

    Args:
        inventory: output of cartographer.build_inventory()
        entrypoints: module tails allowed to have zero inbound edges

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
        if count == 0:
            m = modules_by_name.get(name, {"name": name})
            if _is_entrypoint(m, entrypoints):
                continue
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


# Module stems we should never compare against anything (package markers,
# auto-generated files, test files that legitimately share naming patterns).
_PARALLEL_TRACK_SKIP_STEMS: frozenset[str] = frozenset({
    "__init__",
    "__main__",
    "conftest",
})

# Generic stem names that commonly appear in every package and are not
# parallel tracks when they occur in different packages. These are a
# natural Python idiom, not a duplication signal.
_GENERIC_STEMS: frozenset[str] = frozenset({
    "config",
    "settings",
    "constants",
    "utils",
    "helpers",
    "common",
    "base",
    "core",
    "types",
    "models",
    "schema",
    "schemas",
    "exceptions",
    "errors",
    "client",
    "server",
    "api",
    "main",
    "cli",
    "app",
    "runner",
    "logger",
    "logging",
    "metrics",
    "registry",
    "factory",
    "manager",
    "handler",
    "handlers",
    "state",
    "store",
    "cache",
    "db",
    "database",
    "adapter",
    "adapters",
})


def detect_parallel_tracks(
    inventory: dict[str, Any],
    similarity_threshold: float = 0.6,
) -> list[dict[str, Any]]:
    """Find pairs of modules with overlapping name STEMS above a threshold.

    Two modules are flagged as a parallel track if the Jaccard similarity of
    their name STEMS (last dotted component) is >= similarity_threshold.
    Comparing stems instead of full dotted paths avoids flagging sibling
    modules that share package prefixes (e.g. `cli.commands.account` vs
    `cli.commands.wallet` share `{cli, commands}` but have distinct stems
    `account` and `wallet`).

    Also skips package markers and test conftest files that legitimately
    recur across the tree.
    """
    modules = inventory.get("modules", [])
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    # Pre-compute stems and skip package markers
    candidates: list[tuple[dict[str, Any], str]] = []
    for m in modules:
        stem = m["name"].rsplit(".", 1)[-1] if m.get("name") else ""
        if stem in _PARALLEL_TRACK_SKIP_STEMS:
            continue
        # Also skip anything under tests/ — test files legitimately share
        # naming patterns (test_foo, test_foo_bar, test_foo_edge_cases).
        path = m.get("path", "")
        if "/tests/" in path or path.startswith("tests/"):
            continue
        candidates.append((m, stem))

    for i, (a, a_stem) in enumerate(candidates):
        for b, b_stem in candidates[i + 1:]:
            if a_stem == b_stem:
                # Exact stem match.
                if a["name"] == b["name"]:
                    continue
                # Generic stems (config, utils, models, etc.) commonly recur
                # across packages as a normal Python idiom, not a parallel
                # track. Skip them.
                if a_stem in _GENERIC_STEMS:
                    continue
                sim = 1.0
            else:
                sim = _similarity(a_stem, b_stem)
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


# ---------- Telegram completeness gap detection ----------

# Handler name patterns that are internal continuations, not top-level
# commands. They receive messages via HANDLERS routing or explicit dispatch
# from another command — they should NOT be registered as their own slash
# command in the menu/help/guide. Flagging them is a false positive.
#
# Pattern: a handler is an internal continuation if another command's name
# is a strict prefix of its name AND the suffix starts with a separator
# like `_confirm`, `_cancel`, `_update`, `_step`, etc.
_INTERNAL_SUFFIXES: frozenset[str] = frozenset({
    "_confirm",
    "_cancel",
    "_update",
    "_step",
    "_reply",
    "_next",
    "_prev",
    "_back",
    "_retry",
    "_ack",
})

# Handlers we never require to reference themselves in help/guide/menu
# (they're the help/guide themselves, or are synonymous aliases).
_TELEGRAM_SELF_EXEMPT: frozenset[str] = frozenset({
    "help",
    "guide",
    "start",  # Telegram's conventional welcome command
})


def _is_internal_continuation(name: str, handler_names: set[str]) -> bool:
    """True if `name` looks like `<existing>_confirm`/`_update` etc.

    These are button-handler continuations of another command and should not
    be required to register as their own slash command.
    """
    for suffix in _INTERNAL_SUFFIXES:
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            if base and base in handler_names:
                return True
    return False


def detect_telegram_gaps(telegram: dict[str, Any]) -> list[dict[str, Any]]:
    """Find cmd_* handlers that are not fully registered.

    A handler is "fully registered" if it appears in:
    - HANDLERS dict (with at least one key)
    - _set_telegram_commands() menu list
    - cmd_help mention
    - cmd_guide mention

    Exceptions:
    - Handlers whose name ends with an internal-continuation suffix like
      `_confirm`, `_cancel`, `_update` and whose base is another handler
      (e.g. `cmd_addmarket_confirm` is a continuation of `cmd_addmarket`).
      These are expected to route via HANDLERS from inside another command,
      not to appear in the menu. They are flagged separately as **P1** with
      a distinct reason: "internal continuation — confirm routing only".
      If missing from the HANDLERS dict they stay P0 (still a real bug).
    - cmd_help and cmd_guide don't need to appear in their own bodies.
      They do still need to appear in HANDLERS, the menu, and the other one.
    """
    gaps: list[dict[str, Any]] = []

    handler_names = {h["name"].replace("cmd_", "") for h in telegram.get("handlers", [])}
    # Authoritative routing check: is cmd_X referenced as a VALUE in HANDLERS?
    # User-facing keys like "addmarket!" or "disrupt-update" legitimately
    # differ from the handler name, so matching keys to names produces false
    # positives. Matching values (function references) is correct.
    dict_values = set(telegram.get("handlers_dict_values", []))
    menu = set(telegram.get("menu_commands", []))
    help_set = {h.lstrip("/") for h in telegram.get("help_mentions", [])}
    guide_set = {h.lstrip("/") for h in telegram.get("guide_mentions", [])}

    for name in sorted(handler_names):
        is_internal = _is_internal_continuation(name, handler_names)

        missing = []
        # Routing: does cmd_X appear as a value in HANDLERS?
        if f"cmd_{name}" not in dict_values:
            missing.append("HANDLERS dict")

        # Internal continuations only need HANDLERS routing — they don't
        # appear in the menu/help/guide at all.
        if not is_internal:
            if name not in menu:
                missing.append("_set_telegram_commands() menu")
            # Skip self-references in help/guide.
            if name not in _TELEGRAM_SELF_EXEMPT or name != "help":
                if name not in help_set and name != "help":
                    missing.append("cmd_help")
            if name not in _TELEGRAM_SELF_EXEMPT or name != "guide":
                if name not in guide_set and name != "guide":
                    missing.append("cmd_guide")

        if missing:
            # P0 if HANDLERS dict routing is broken — the command literally
            # can't be invoked. Otherwise P1.
            severity = "P0" if "HANDLERS dict" in missing else "P1"
            reason = f"cmd_{name} not registered in: {', '.join(missing)}"
            if is_internal and severity == "P1":
                # Internal continuations with just routing gaps are noise
                # — they come and go as commands are refactored. Downgrade.
                severity = "P2"
                reason = f"cmd_{name} is an internal continuation; {reason}"
            gaps.append({
                "command": name,
                "severity": severity,
                "missing_from": missing,
                "is_internal_continuation": is_internal,
                "reason": reason,
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
