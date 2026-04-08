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
