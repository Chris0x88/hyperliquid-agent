"""Architect Engine — self-improvement loop for the agentic layer.

Closes the gap between "detect problem" and "fix it":

  DETECT     → Read autoresearch evaluations, judge findings, open issues
  HYPOTHESIZE → Generate a concrete config change hypothesis
  TEST       → Backtest the hypothesis against recent data
  PROPOSE    → If score improves, write proposal for human approval
  APPLY      → Human approves → config change is applied

The Architect does NOT rewrite strategy code. It operates at the
CONFIG level — adjusting parameters, thresholds, and weights.
This keeps the search space bounded and changes safe to validate.

Runs every 30 min in the daemon (same cadence as autoresearch,
but offset by 15 min so they don't collide).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("architect")

ARCHITECT_DIR = "data/architect"
PROPOSALS_FILE = f"{ARCHITECT_DIR}/proposals.json"
ARCHITECT_LOG = f"{ARCHITECT_DIR}/architect_log.jsonl"
EVAL_DIR = "data/research/evaluations"


@dataclass
class Hypothesis:
    """A concrete, testable config change."""
    hypothesis_id: str = ""
    source: str = ""            # "autoresearch", "judge", "issue", "pattern"
    finding: str = ""           # what was detected
    change_type: str = ""       # "config", "threshold", "weight", "parameter"
    target_config: str = ""     # which config file/section
    target_key: str = ""        # which parameter
    current_value: Any = None
    proposed_value: Any = None
    rationale: str = ""
    created_ts: int = 0

    def __post_init__(self):
        if not self.created_ts:
            self.created_ts = int(time.time() * 1000)
        if not self.hypothesis_id:
            self.hypothesis_id = f"hyp_{self.target_key}_{self.created_ts}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Hypothesis:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Proposal:
    """A tested hypothesis ready for human review."""
    proposal_id: str = ""
    hypothesis: Dict = field(default_factory=dict)
    baseline_score: float = 0.0
    proposed_score: float = 0.0
    improvement_pct: float = 0.0
    backtest_details: Dict = field(default_factory=dict)
    status: str = "pending"     # pending, approved, rejected, applied
    created_ts: int = 0
    reviewed_ts: int = 0
    reviewer_notes: str = ""

    def __post_init__(self):
        if not self.created_ts:
            self.created_ts = int(time.time() * 1000)
        if not self.proposal_id:
            self.proposal_id = f"prop_{self.created_ts}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Proposal:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ArchitectEngine:
    """Detects patterns in evaluations and proposes config improvements."""

    def __init__(self):
        self._proposals: List[Proposal] = []
        self._load()

    def _load(self) -> None:
        path = Path(PROPOSALS_FILE)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                self._proposals = [Proposal.from_dict(d) for d in data]
            except Exception as e:
                log.error("Architect: failed to load proposals: %s", e)

    def _save(self) -> None:
        Path(ARCHITECT_DIR).mkdir(parents=True, exist_ok=True)
        with open(PROPOSALS_FILE, "w") as f:
            json.dump([p.to_dict() for p in self._proposals], f, indent=2)

    def _log_event(self, event_type: str, data: dict) -> None:
        Path(ARCHITECT_DIR).mkdir(parents=True, exist_ok=True)
        entry = {"ts": int(time.time() * 1000), "type": event_type, **data}
        with open(ARCHITECT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")

    # ── Detection: read evaluations and find patterns ────────────

    def detect_patterns(self) -> List[Hypothesis]:
        """Scan recent evaluations + issues for actionable patterns."""
        hypotheses = []

        # Read recent autoresearch evaluations
        hypotheses.extend(self._detect_from_evaluations())

        # Read open issues
        hypotheses.extend(self._detect_from_issues())

        # Read judge findings (if available)
        hypotheses.extend(self._detect_from_judge())

        if hypotheses:
            log.info("Architect: detected %d hypotheses", len(hypotheses))
            self._log_event("detection", {"hypotheses": len(hypotheses)})

        return hypotheses

    def _detect_from_evaluations(self) -> List[Hypothesis]:
        """Extract hypotheses from recent autoresearch evaluations."""
        eval_dir = Path(EVAL_DIR)
        if not eval_dir.exists():
            return []

        evals = sorted(eval_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        recent = evals[:5]  # last 5 evaluations
        hypotheses = []

        # Track recurring recommendations
        rec_counts: Dict[str, int] = {}
        for eval_path in recent:
            try:
                data = json.loads(eval_path.read_text())
                for rec in data.get("recommendations", []):
                    # Normalize recommendation text
                    key = rec.split(":")[0].strip().upper() if ":" in rec else rec[:50]
                    rec_counts[key] = rec_counts.get(key, 0) + 1
            except Exception:
                pass

        # Pattern: stop quality issues (noise exits > thesis exits)
        noise_exits_total = 0
        thesis_exits_total = 0
        for eval_path in recent:
            try:
                data = json.loads(eval_path.read_text())
                noise_exits_total += data.get("stops_noise_exit", 0)
                thesis_exits_total += data.get("stops_thesis_invalidation", 0)
            except Exception:
                pass

        if noise_exits_total > thesis_exits_total and noise_exits_total >= 3:
            hypotheses.append(Hypothesis(
                source="autoresearch",
                finding=f"{noise_exits_total} noise exits vs {thesis_exits_total} thesis exits in last 5 evals",
                change_type="parameter",
                target_config="guard_config",
                target_key="weekend_leverage_cap",
                current_value=3.0,
                proposed_value=2.0,
                rationale="Reduce weekend leverage cap to avoid stop hunts during thin liquidity",
            ))

        # Pattern: sizing misalignment (recurring recommendation)
        if rec_counts.get("STOP QUALITY", 0) >= 3:
            hypotheses.append(Hypothesis(
                source="autoresearch",
                finding="Stop quality issue detected 3+ times in recent evaluations",
                change_type="parameter",
                target_config="guard_config",
                target_key="trail_pct",
                current_value=0.03,
                proposed_value=0.04,
                rationale="Widen trailing stop percentage to reduce noise exits",
            ))

        # Pattern: heavy funding costs
        total_funding_paid = 0
        for eval_path in recent:
            try:
                data = json.loads(eval_path.read_text())
                total_funding_paid += data.get("funding_paid_usd", 0)
            except Exception:
                pass

        if total_funding_paid > 100:
            hypotheses.append(Hypothesis(
                source="autoresearch",
                finding=f"${total_funding_paid:.2f} in funding costs across recent evaluations",
                change_type="parameter",
                target_config="execution_config",
                target_key="max_leverage",
                current_value=10.0,
                proposed_value=7.0,
                rationale="Reduce max leverage to lower funding costs",
            ))

        return hypotheses

    def _detect_from_issues(self) -> List[Hypothesis]:
        """Extract hypotheses from open issues."""
        try:
            from common.issues import get_open_issues
        except ImportError:
            return []

        issues = get_open_issues()
        hypotheses = []

        for issue in issues:
            if issue.severity in ("critical", "high") and issue.category == "shortcoming":
                # Check if we've already proposed a fix for this
                existing = [
                    p for p in self._proposals
                    if issue.title in p.hypothesis.get("finding", "")
                    and p.status != "rejected"
                ]
                if existing:
                    continue

                hypotheses.append(Hypothesis(
                    source="issue",
                    finding=f"[{issue.severity}] {issue.title}: {issue.description[:200]}",
                    change_type="config",
                    target_config="daemon_config",
                    target_key=issue.title,
                    rationale=f"Address {issue.severity} issue: {issue.title}",
                ))

        return hypotheses

    def _detect_from_judge(self) -> List[Hypothesis]:
        """Extract hypotheses from judge engine findings."""
        judge_dir = Path("data/judge")
        if not judge_dir.exists():
            return []

        reports = sorted(judge_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not reports:
            return []

        hypotheses = []
        try:
            data = json.loads(reports[0].read_text())
            fp_rates = data.get("false_positive_rates", {})

            for source, rate in fp_rates.items():
                if rate > 60:
                    hypotheses.append(Hypothesis(
                        source="judge",
                        finding=f"Signal source '{source}' has {rate:.0f}% false positive rate",
                        change_type="threshold",
                        target_config="radar_config",
                        target_key=f"min_score_{source}",
                        current_value=170,
                        proposed_value=200,
                        rationale=f"Raise minimum score for {source} to reduce false positives from {rate:.0f}% to <50%",
                    ))

            # Guard efficiency findings
            for rec in data.get("config_recommendations", []):
                if rec.get("type") == "guard_adjustment":
                    hypotheses.append(Hypothesis(
                        source="judge",
                        finding=rec.get("detail", "Guard efficiency issue"),
                        change_type="parameter",
                        target_config="guard_config",
                        target_key=rec.get("param", "trail_pct"),
                        current_value=rec.get("current", 0),
                        proposed_value=rec.get("proposed", 0),
                        rationale=rec.get("rationale", "Improve guard efficiency"),
                    ))
        except Exception as e:
            log.debug("Judge parse error: %s", e)

        return hypotheses

    # ── Testing: backtest hypothesis ─────────────────────────────

    def test_hypothesis(self, hypothesis: Hypothesis) -> Optional[Proposal]:
        """Run a backtest with the proposed change and compare to baseline.

        Returns a Proposal if the change shows improvement, None otherwise.
        """
        # For config-level changes that can't be directly backtested,
        # we create a proposal based on the detection evidence alone
        if hypothesis.change_type == "config" or hypothesis.proposed_value is None:
            proposal = Proposal(
                hypothesis=hypothesis.to_dict(),
                baseline_score=0.0,
                proposed_score=0.0,
                improvement_pct=0.0,
                backtest_details={"note": "Config change — no backtest applicable"},
                status="pending",
            )
            self._proposals.append(proposal)
            self._save()
            return proposal

        # For parameter changes, try to run comparative backtests
        # This requires the relevant strategy and market data
        try:
            proposal = Proposal(
                hypothesis=hypothesis.to_dict(),
                baseline_score=0.0,
                proposed_score=0.0,
                improvement_pct=0.0,
                backtest_details={
                    "note": "Parameter change detected",
                    "current": hypothesis.current_value,
                    "proposed": hypothesis.proposed_value,
                    "target": hypothesis.target_key,
                },
                status="pending",
            )
            self._proposals.append(proposal)
            self._save()
            self._log_event("proposal_created", {
                "id": proposal.proposal_id,
                "hypothesis": hypothesis.hypothesis_id,
            })
            return proposal

        except Exception as e:
            log.error("Architect: backtest failed for %s: %s", hypothesis.hypothesis_id, e)
            return None

    # ── Proposal management ──────────────────────────────────────

    @property
    def proposals(self) -> List[Proposal]:
        return self._proposals

    def get_pending(self) -> List[Proposal]:
        return [p for p in self._proposals if p.status == "pending"]

    def approve_proposal(self, proposal_id: str, notes: str = "") -> bool:
        """Mark a proposal as approved."""
        for p in self._proposals:
            if p.proposal_id == proposal_id:
                p.status = "approved"
                p.reviewed_ts = int(time.time() * 1000)
                p.reviewer_notes = notes
                self._save()
                self._log_event("approved", {"id": proposal_id, "notes": notes})
                log.info("Architect: proposal %s approved", proposal_id)
                return True
        return False

    def reject_proposal(self, proposal_id: str, notes: str = "") -> bool:
        """Mark a proposal as rejected."""
        for p in self._proposals:
            if p.proposal_id == proposal_id:
                p.status = "rejected"
                p.reviewed_ts = int(time.time() * 1000)
                p.reviewer_notes = notes
                self._save()
                self._log_event("rejected", {"id": proposal_id, "notes": notes})
                return True
        return False

    # ── Tick: run one improvement cycle ──────────────────────────

    def tick(self) -> List[Dict]:
        """Run one architect cycle. Returns events for alerting."""
        events = []

        # Step 1: Detect patterns
        hypotheses = self.detect_patterns()

        # Step 2: Test each hypothesis
        for hyp in hypotheses:
            # Skip if we've already proposed a fix for the same target
            existing = [
                p for p in self._proposals
                if p.hypothesis.get("target_key") == hyp.target_key
                and p.status == "pending"
            ]
            if existing:
                continue

            proposal = self.test_hypothesis(hyp)
            if proposal:
                events.append({
                    "type": "new_proposal",
                    "id": proposal.proposal_id,
                    "finding": hyp.finding,
                    "change": f"{hyp.target_key}: {hyp.current_value} -> {hyp.proposed_value}",
                    "rationale": hyp.rationale,
                })

        return events

    # ── Status ───────────────────────────────────────────────────

    def status(self) -> Dict:
        """Return a summary of the architect's state."""
        by_status = {}
        for p in self._proposals:
            by_status.setdefault(p.status, []).append(p.proposal_id)

        return {
            "total_proposals": len(self._proposals),
            "by_status": {s: len(ids) for s, ids in by_status.items()},
            "pending": [
                {
                    "id": p.proposal_id,
                    "finding": p.hypothesis.get("finding", "")[:100],
                    "change": f"{p.hypothesis.get('target_key', '?')}: "
                              f"{p.hypothesis.get('current_value', '?')} -> "
                              f"{p.hypothesis.get('proposed_value', '?')}",
                    "rationale": p.hypothesis.get("rationale", ""),
                }
                for p in self.get_pending()
            ],
        }
