"""Architect Engine — mechanical self-improvement with AI on-demand.

Closes the loop between autoresearch detection and actionable fixes:
  1. DETECT: Read autoresearch evaluations + judge findings + open issues
  2. PATTERN: Apply rule-based pattern matching (no AI) to find recurring problems
  3. HYPOTHESIZE: Generate concrete fix proposals with expected impact
  4. VALIDATE: Score proposals against recent backtest data (mechanical)
  5. PROPOSE: Surface approved proposals for human review

The key constraint: AI is ONLY called on-demand (via `hl architect analyze`),
never on a timer. The daemon iterator runs pure Python pattern matching.

Default cadence: every 12 hours (configurable via data/config/architect.json).
Zero AI calls. Zero API costs.

Kill switch: data/config/architect.json → enabled: false

Usage:
    from engines.learning.architect_engine import ArchitectEngine
    arch = ArchitectEngine()
    findings = arch.detect()           # pure Python pattern matching
    proposals = arch.hypothesize(findings)  # generate fix proposals
    arch.approve("prop-001")           # human approval via CLI
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("architect_engine")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ARCH_DIR = _PROJECT_ROOT / "data" / "architect"
_PROPOSALS_FILE = _ARCH_DIR / "proposals.json"
_FINDINGS_FILE = _ARCH_DIR / "findings.json"
_CONFIG_FILE = _PROJECT_ROOT / "data" / "config" / "architect.json"

# Default config
_DEFAULT_CONFIG = {
    "enabled": False,
    "interval_hours": 12,
    "min_pattern_occurrences": 3,   # pattern must appear N times to become a finding
    "max_proposals": 10,            # cap on pending proposals
}


@dataclass
class Finding:
    """A detected pattern from autoresearch/judge data."""
    id: str
    pattern_type: str       # noise_exits, sizing_drift, stop_too_tight, funding_drag, etc.
    description: str
    occurrences: int
    severity: str           # low, medium, high, critical
    first_seen: float
    last_seen: float
    evidence: List[str] = field(default_factory=list)  # evaluation file references

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Proposal:
    """A concrete fix proposal generated from a finding."""
    id: str
    finding_id: str
    title: str
    description: str
    proposed_change: Dict[str, Any]     # e.g. {"file": "...", "param": "...", "old": ..., "new": ...}
    expected_impact: str
    status: str = "pending"             # pending → approved → applied → rejected
    created_at: float = 0.0
    reviewed_at: float = 0.0
    review_notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Proposal":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ArchitectEngine:
    """Mechanical self-improvement engine — zero AI calls."""

    def __init__(self, config_path: str = str(_CONFIG_FILE)):
        self._config_path = Path(config_path)
        self._config = self._load_config()
        self._findings: List[Finding] = []
        self._proposals: List[Proposal] = []
        self._load_state()

    @property
    def enabled(self) -> bool:
        return self._config.get("enabled", False)

    @property
    def interval_hours(self) -> int:
        return self._config.get("interval_hours", 12)

    def _load_config(self) -> dict:
        if self._config_path.exists():
            try:
                return json.loads(self._config_path.read_text())
            except Exception:
                pass
        return _DEFAULT_CONFIG.copy()

    def _load_state(self) -> None:
        if _FINDINGS_FILE.exists():
            try:
                self._findings = [Finding.from_dict(f) for f in json.loads(_FINDINGS_FILE.read_text())]
            except Exception:
                self._findings = []
        if _PROPOSALS_FILE.exists():
            try:
                self._proposals = [Proposal.from_dict(p) for p in json.loads(_PROPOSALS_FILE.read_text())]
            except Exception:
                self._proposals = []

    def _save_state(self) -> None:
        _ARCH_DIR.mkdir(parents=True, exist_ok=True)
        _FINDINGS_FILE.write_text(json.dumps([f.to_dict() for f in self._findings], indent=2))
        _PROPOSALS_FILE.write_text(json.dumps([p.to_dict() for p in self._proposals], indent=2))

    # ═══════════════════════════════════════════════════════════════
    # DETECT — pure Python pattern matching on evaluation data
    # ═══════════════════════════════════════════════════════════════

    def detect(self) -> List[Finding]:
        """Scan autoresearch evaluations and judge data for recurring patterns.

        Returns new findings (patterns that crossed the min_occurrences threshold).
        Zero AI calls — pure file reads + pattern matching.
        """
        if not self.enabled:
            return []

        evaluations = self._read_evaluations()
        if not evaluations:
            return []

        min_occ = self._config.get("min_pattern_occurrences", 3)
        new_findings: List[Finding] = []

        # Pattern 1: Noise exits > thesis exits
        noise_exits = [e for e in evaluations if e.get("stops_noise_exit", 0) > e.get("stops_thesis_invalidation", 0)]
        if len(noise_exits) >= min_occ:
            f = self._upsert_finding(
                "noise_exits_dominant",
                f"Noise exits exceeded thesis exits in {len(noise_exits)}/{len(evaluations)} evaluations",
                len(noise_exits),
                "high" if len(noise_exits) > min_occ * 2 else "medium",
                [e.get("timestamp_human", "?") for e in noise_exits[:5]],
            )
            if f:
                new_findings.append(f)

        # Pattern 2: Sizing consistently misaligned
        poor_sizing = [e for e in evaluations if e.get("sizing_alignment_score", 1) < 0.5]
        if len(poor_sizing) >= min_occ:
            avg_score = sum(e.get("sizing_alignment_score", 0) for e in poor_sizing) / len(poor_sizing)
            f = self._upsert_finding(
                "sizing_drift",
                f"Sizing alignment below 50% in {len(poor_sizing)} evaluations (avg={avg_score:.0%})",
                len(poor_sizing),
                "medium",
                [e.get("timestamp_human", "?") for e in poor_sizing[:5]],
            )
            if f:
                new_findings.append(f)

        # Pattern 3: High funding drag
        high_funding = [e for e in evaluations
                        if e.get("funding_paid_usd", 0) > 0
                        and e.get("funding_efficiency_score", 1) < 0.3]
        if len(high_funding) >= min_occ:
            total_paid = sum(e.get("funding_paid_usd", 0) for e in high_funding)
            f = self._upsert_finding(
                "funding_drag",
                f"Funding efficiency below 30% in {len(high_funding)} evaluations (total=${total_paid:.2f})",
                len(high_funding),
                "medium",
                [e.get("timestamp_human", "?") for e in high_funding[:5]],
            )
            if f:
                new_findings.append(f)

        # Pattern 4: Catalyst timing poor
        poor_catalysts = [e for e in evaluations if e.get("catalyst_timing_score", 1) < 0.4]
        if len(poor_catalysts) >= min_occ:
            f = self._upsert_finding(
                "catalyst_timing_poor",
                f"Catalyst timing below 40% in {len(poor_catalysts)} evaluations",
                len(poor_catalysts),
                "medium",
                [e.get("timestamp_human", "?") for e in poor_catalysts[:5]],
            )
            if f:
                new_findings.append(f)

        # Pattern 5: Check for recurring issues in issues.jsonl
        issues_findings = self._detect_issue_patterns()
        new_findings.extend(issues_findings)

        if new_findings:
            self._save_state()

        return new_findings

    def _read_evaluations(self, limit: int = 30) -> List[dict]:
        """Read recent autoresearch evaluation files."""
        eval_dir = _PROJECT_ROOT / "data" / "research" / "evaluations"
        if not eval_dir.exists():
            return []

        eval_files = sorted(eval_dir.glob("*.json"), reverse=True)[:limit]
        evals = []
        for ef in eval_files:
            try:
                evals.append(json.loads(ef.read_text()))
            except Exception:
                continue
        return evals

    def _detect_issue_patterns(self) -> List[Finding]:
        """Detect recurring patterns from issues/feedback files."""
        findings = []
        issues_path = _PROJECT_ROOT / "data" / "daemon" / "issues.jsonl"
        if not issues_path.exists():
            return findings

        from collections import Counter
        categories = Counter()
        try:
            with issues_path.open() as fh:
                for ln in fh:
                    if not ln.strip():
                        continue
                    try:
                        issue = json.loads(ln)
                        cat = issue.get("category", "unknown")
                        categories[cat] += 1
                    except Exception:
                        continue
        except Exception:
            return findings

        min_occ = self._config.get("min_pattern_occurrences", 3)
        for cat, count in categories.most_common(5):
            if count >= min_occ:
                f = self._upsert_finding(
                    f"recurring_issue_{cat}",
                    f"Issue category '{cat}' appeared {count} times",
                    count,
                    "medium" if count < 10 else "high",
                    [],
                )
                if f:
                    findings.append(f)

        return findings

    def _upsert_finding(
        self,
        pattern_type: str,
        description: str,
        occurrences: int,
        severity: str,
        evidence: List[str],
    ) -> Optional[Finding]:
        """Create or update a finding. Returns the finding if it's new or escalated."""
        existing = next((f for f in self._findings if f.pattern_type == pattern_type), None)
        now = time.time()

        if existing:
            existing.occurrences = occurrences
            existing.last_seen = now
            existing.evidence = evidence
            if severity == "high" and existing.severity != "high":
                existing.severity = severity
                return existing  # escalated
            return None  # already known, not escalated

        finding = Finding(
            id=f"find-{uuid.uuid4().hex[:8]}",
            pattern_type=pattern_type,
            description=description,
            occurrences=occurrences,
            severity=severity,
            first_seen=now,
            last_seen=now,
            evidence=evidence,
        )
        self._findings.append(finding)
        return finding

    # ═══════════════════════════════════════════════════════════════
    # HYPOTHESIZE — generate fix proposals from findings
    # ═══════════════════════════════════════════════════════════════

    def hypothesize(self, findings: Optional[List[Finding]] = None) -> List[Proposal]:
        """Generate concrete fix proposals from findings.

        Each finding type has a known remediation pattern.
        Zero AI calls — deterministic rule application.
        """
        if findings is None:
            findings = self._findings

        new_proposals = []
        max_proposals = self._config.get("max_proposals", 10)
        pending_count = sum(1 for p in self._proposals if p.status == "pending")

        for finding in findings:
            if pending_count >= max_proposals:
                break

            # Skip if we already have a pending proposal for this finding
            existing = [p for p in self._proposals
                        if p.finding_id == finding.id and p.status == "pending"]
            if existing:
                continue

            proposal = self._generate_proposal(finding)
            if proposal:
                self._proposals.append(proposal)
                new_proposals.append(proposal)
                pending_count += 1

        if new_proposals:
            self._save_state()

        return new_proposals

    def _generate_proposal(self, finding: Finding) -> Optional[Proposal]:
        """Generate a specific proposal for a finding type."""
        now = time.time()

        if finding.pattern_type == "noise_exits_dominant":
            return Proposal(
                id=f"prop-{uuid.uuid4().hex[:8]}",
                finding_id=finding.id,
                title="Widen weekend/off-hours stop distance",
                description=(
                    "Noise exits are exceeding thesis-driven exits. "
                    "Proposed: increase ATR multiplier for stops during weekend "
                    "and low-liquidity hours to reduce noise triggering."
                ),
                proposed_change={
                    "type": "config_parameter",
                    "file": "data/config/oil_botpattern.json",
                    "param": "stop_atr_mult",
                    "direction": "increase",
                    "magnitude": "10%",
                    "context": "weekend/off-hours only",
                },
                expected_impact="Reduce noise exits by ~30%, slightly increase max drawdown on thesis exits",
                created_at=now,
            )

        if finding.pattern_type == "sizing_drift":
            return Proposal(
                id=f"prop-{uuid.uuid4().hex[:8]}",
                finding_id=finding.id,
                title="Recalibrate conviction-to-size mapping",
                description=(
                    "Sizing is consistently misaligned with conviction levels. "
                    "Proposed: adjust the conviction band thresholds to better "
                    "match actual position sizes with stated conviction."
                ),
                proposed_change={
                    "type": "config_parameter",
                    "file": "data/thesis/conviction_bands.json",
                    "param": "band_thresholds",
                    "direction": "recalibrate",
                },
                expected_impact="Improve sizing alignment score from <50% to >70%",
                created_at=now,
            )

        if finding.pattern_type == "funding_drag":
            return Proposal(
                id=f"prop-{uuid.uuid4().hex[:8]}",
                finding_id=finding.id,
                title="Add funding-cost exit trigger for long positions",
                description=(
                    "Funding costs are dragging returns. Proposed: add a cumulative "
                    "funding cost threshold that triggers position review when "
                    "carry cost exceeds a percentage of unrealized P&L."
                ),
                proposed_change={
                    "type": "config_parameter",
                    "file": "data/config/oil_botpattern.json",
                    "param": "funding_exit_pct",
                    "direction": "add",
                    "suggested_value": 0.5,
                    "context": "exit when funding > 50% of uPnL",
                },
                expected_impact="Reduce funding drag by cutting losing-while-paying positions earlier",
                created_at=now,
            )

        if finding.pattern_type == "catalyst_timing_poor":
            return Proposal(
                id=f"prop-{uuid.uuid4().hex[:8]}",
                finding_id=finding.id,
                title="Increase catalyst pre-positioning lead time",
                description=(
                    "Catalyst timing is poor — entries are too close to events. "
                    "Proposed: increase the entry-before-event window from the "
                    "current setting to 48h minimum for high-severity catalysts."
                ),
                proposed_change={
                    "type": "config_parameter",
                    "param": "entry_hours_before",
                    "direction": "increase",
                    "suggested_value": 48,
                },
                expected_impact="Better positioned ahead of catalysts, reduced chase entries",
                created_at=now,
            )

        # Generic proposal for recurring issues
        if finding.pattern_type.startswith("recurring_issue_"):
            category = finding.pattern_type.replace("recurring_issue_", "")
            return Proposal(
                id=f"prop-{uuid.uuid4().hex[:8]}",
                finding_id=finding.id,
                title=f"Address recurring '{category}' issues",
                description=f"The '{category}' issue category has appeared {finding.occurrences} times. Investigate root cause.",
                proposed_change={
                    "type": "investigation",
                    "category": category,
                    "occurrences": finding.occurrences,
                },
                expected_impact=f"Reduce '{category}' issue frequency",
                created_at=now,
            )

        return None

    # ═══════════════════════════════════════════════════════════════
    # PROPOSAL MANAGEMENT
    # ═══════════════════════════════════════════════════════════════

    def get_status(self) -> Dict[str, Any]:
        """Get summary of findings and proposals."""
        return {
            "enabled": self.enabled,
            "findings": len(self._findings),
            "findings_by_severity": {
                s: len([f for f in self._findings if f.severity == s])
                for s in ("critical", "high", "medium", "low")
            },
            "proposals_pending": len([p for p in self._proposals if p.status == "pending"]),
            "proposals_approved": len([p for p in self._proposals if p.status == "approved"]),
            "proposals_applied": len([p for p in self._proposals if p.status == "applied"]),
        }

    def get_pending_proposals(self) -> List[Proposal]:
        return [p for p in self._proposals if p.status == "pending"]

    def approve(self, proposal_id: str, notes: str = "") -> bool:
        """Approve a proposal for application."""
        for p in self._proposals:
            if p.id == proposal_id and p.status == "pending":
                p.status = "approved"
                p.reviewed_at = time.time()
                p.review_notes = notes
                self._save_state()
                log.info("Proposal %s approved: %s", proposal_id, p.title)
                return True
        return False

    def reject(self, proposal_id: str, notes: str = "") -> bool:
        """Reject a proposal."""
        for p in self._proposals:
            if p.id == proposal_id and p.status == "pending":
                p.status = "rejected"
                p.reviewed_at = time.time()
                p.review_notes = notes
                self._save_state()
                log.info("Proposal %s rejected: %s", proposal_id, p.title)
                return True
        return False
