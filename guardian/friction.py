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
