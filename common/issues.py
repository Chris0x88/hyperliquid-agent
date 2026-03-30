"""Issue tracker — records bugs, code fixes, shortcomings found during operation.

The scheduled task and autoresearch loop write issues here.
Reviewed daily by human + AI to prioritize fixes.

File: data/research/issues.jsonl (append-only, one JSON per line)
Summary: data/research/issues_summary.md (human-readable, regenerated)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

ISSUES_FILE = "data/research/issues.jsonl"
SUMMARY_FILE = "data/research/issues_summary.md"


@dataclass
class Issue:
    """One identified bug, shortcoming, or improvement."""
    timestamp: int             # unix ms
    category: str              # "bug", "code_fix", "shortcoming", "improvement", "data_quality"
    severity: str              # "critical", "high", "medium", "low"
    title: str                 # one-line summary
    description: str           # detailed description
    source: str                # "scheduled_task", "autoresearch", "daemon", "manual"
    file_path: str = ""        # which file is affected (if known)
    resolved: bool = False
    resolution: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def log_issue(
    category: str,
    severity: str,
    title: str,
    description: str,
    source: str = "scheduled_task",
    file_path: str = "",
) -> None:
    """Append an issue to the issues log."""
    Path(ISSUES_FILE).parent.mkdir(parents=True, exist_ok=True)
    issue = Issue(
        timestamp=int(time.time() * 1000),
        category=category,
        severity=severity,
        title=title,
        description=description,
        source=source,
        file_path=file_path,
    )
    with open(ISSUES_FILE, "a") as f:
        f.write(json.dumps(issue.to_dict()) + "\n")


def get_open_issues() -> List[Issue]:
    """Load all unresolved issues."""
    if not os.path.exists(ISSUES_FILE):
        return []
    issues = []
    with open(ISSUES_FILE) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                if not d.get("resolved"):
                    issues.append(Issue.from_dict(d))
            except Exception:
                pass
    return issues


def resolve_issue(title: str, resolution: str = "fixed") -> None:
    """Mark an issue as resolved by title match."""
    if not os.path.exists(ISSUES_FILE):
        return
    lines = []
    with open(ISSUES_FILE) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
                if d.get("title") == title and not d.get("resolved"):
                    d["resolved"] = True
                    d["resolution"] = resolution
                lines.append(json.dumps(d) + "\n")
            except Exception:
                lines.append(line)
    with open(ISSUES_FILE, "w") as f:
        f.writelines(lines)


def regenerate_summary() -> str:
    """Regenerate the human-readable issues summary."""
    issues = get_open_issues()
    if not issues:
        content = "# Open Issues\n\nNo open issues.\n"
    else:
        lines = ["# Open Issues\n\n"]
        by_severity = {"critical": [], "high": [], "medium": [], "low": []}
        for i in issues:
            by_severity.get(i.severity, by_severity["low"]).append(i)

        for sev in ["critical", "high", "medium", "low"]:
            items = by_severity[sev]
            if not items:
                continue
            lines.append(f"## {sev.upper()} ({len(items)})\n\n")
            for i in items:
                ts = time.strftime("%Y-%m-%d %H:%M", time.gmtime(i.timestamp / 1000))
                lines.append(f"- **[{i.category}]** {i.title}\n")
                lines.append(f"  {i.description}\n")
                if i.file_path:
                    lines.append(f"  File: `{i.file_path}`\n")
                lines.append(f"  Source: {i.source} | {ts}\n\n")

        content = "".join(lines)

    Path(SUMMARY_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_FILE, "w") as f:
        f.write(content)
    return content
