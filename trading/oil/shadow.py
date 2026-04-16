"""Oil Bot-Pattern L4 Shadow Counterfactual Evaluation — pure logic.

Spec: docs/plans/OIL_BOT_PATTERN_06_SELF_TUNE_HARNESS.md §L4

Sub-system 6 layer L4 per OIL_BOT_PATTERN_SYSTEM.md §6. Given an
approved L2 StructuralProposal and a window of recent closed trades +
decisions, this module computes a counterfactual ShadowEval: what
WOULD have happened if the proposed params had been in effect over the
window? The eval compares divergences from actual live outcomes.

The SYSTEM doc §6 describes L4 as "Every L2/L3 proposal runs in
shadow (paper) mode for ≥ N closed trades before being eligible for
promotion. The system collects its own evidence." This first-wedge
implementation is a LOOK-BACK counterfactual replay rather than a
forward paper trader — it asks "over the last N closed trades, how
would the proposed param change have performed?" rather than running
a parallel live execution. A future wedge can add a forward paper
executor once the counterfactual method is proven.

For config_change proposals, the eval simulates the param swap on the
historical trade window and reports:
- trades_in_window
- would_have_entered_same (count) — decisions where the gate outcome is
  unchanged under proposed params
- would_have_diverged (count) — decisions where the gate outcome flips
- counterfactual_pnl_estimate_usd — approximate PnL delta assuming the
  divergence causes trades to be skipped or taken differently

Contract: evaluation only. Never modifies the target config. The
iterator appends ShadowEval records to a JSONL and updates proposal
records with a `shadow_eval` sub-field.

Engine vs guard: pure computation, zero I/O.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class ShadowEval:
    """Counterfactual evaluation of a single StructuralProposal."""
    proposal_id: int
    proposal_type: str
    evaluated_at: str                      # ISO 8601
    window_days: int
    trades_in_window: int
    decisions_in_window: int
    param: str                             # key that would have been nudged
    current_value: Any
    proposed_value: Any
    would_have_entered_same: int
    would_have_diverged: int
    divergence_rate: float                 # 0.0-1.0
    sample_sufficient: bool
    counterfactual_pnl_estimate_usd: float
    notes: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _pnl(trade: dict) -> float:
    for key in ("realised_pnl_usd", "realized_pnl_usd", "pnl", "pnl_usd"):
        v = trade.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def filter_trades_in_window(
    trades: list[dict],
    now: datetime,
    window_days: int,
) -> list[dict]:
    cutoff = now - timedelta(days=window_days)
    out = []
    for t in trades:
        ts = _parse_iso(t.get("close_ts") or t.get("closed_at") or "")
        if ts is None:
            continue
        if ts >= cutoff:
            out.append(t)
    return out


def filter_decisions_in_window(
    decisions: list[dict],
    now: datetime,
    window_days: int,
) -> list[dict]:
    cutoff = now - timedelta(days=window_days)
    out = []
    for d in decisions:
        ts = _parse_iso(d.get("decided_at") or d.get("created_at") or "")
        if ts is None:
            continue
        if ts >= cutoff:
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# Counterfactual gate replays
# ---------------------------------------------------------------------------

def counterfactual_edge_threshold_replay(
    decisions: list[dict],
    current_threshold: float,
    proposed_threshold: float,
    direction_filter: str | None = None,
) -> tuple[int, int, int]:
    """For decisions whose edge is captured in the row, count how many
    would have flipped entry/skip if the min_edge threshold moved from
    `current_threshold` to `proposed_threshold`.

    Returns (same, diverged_newly_entered, diverged_newly_skipped).

    - `newly_entered`: edge was < current but ≥ proposed (threshold loosened)
    - `newly_skipped`: edge was ≥ current but < proposed (threshold tightened)
    """
    same = 0
    newly_entered = 0
    newly_skipped = 0
    for d in decisions:
        if direction_filter is not None and d.get("direction") != direction_filter:
            continue
        try:
            edge = float(d.get("edge", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        was_entered = edge >= current_threshold
        would_enter = edge >= proposed_threshold
        if was_entered == would_enter:
            same += 1
        elif would_enter and not was_entered:
            newly_entered += 1
        else:
            newly_skipped += 1
    return same, newly_entered, newly_skipped


def counterfactual_severity_floor_replay(
    decisions: list[dict],
    current_floor: int,
    proposed_floor: int,
    direction_filter: str = "short",
) -> tuple[int, int, int]:
    """For decisions blocked by the `no_blocking_catalyst` gate at a given
    severity floor, count how many would flip if the floor changed.

    The decision journal's gate_results record the failing reason
    (formatted like "blocked by sev4 X in next 24h"). We parse the
    severity number out of the reason string.

    Returns (same, newly_passed, newly_blocked).

    - newly_passed: blocked at current floor but would pass at proposed
    - newly_blocked: passed at current floor but would fail at proposed
    """
    import re

    same = 0
    newly_passed = 0
    newly_blocked = 0
    sev_re = re.compile(r"sev(\d+)")

    for d in decisions:
        if direction_filter is not None and d.get("direction") != direction_filter:
            continue

        # Find the no_blocking_catalyst gate result if present
        gate = None
        for gr in d.get("gate_results") or []:
            if gr.get("name") == "no_blocking_catalyst":
                gate = gr
                break
        if gate is None:
            # Decision predates this gate — skip; no information
            continue

        was_blocked = not gate.get("passed", True)
        # Parse the sev from the reason. If no match, we can't replay.
        reason = str(gate.get("reason") or "")
        m = sev_re.search(reason)
        if m is None:
            if was_blocked == was_blocked:
                same += 1  # no replay possible — count as unchanged
            continue

        sev = int(m.group(1))
        # Block rule: blocks iff sev >= floor
        would_block_current = sev >= current_floor
        would_block_proposed = sev >= proposed_floor

        if would_block_current == would_block_proposed:
            same += 1
        elif would_block_current and not would_block_proposed:
            newly_passed += 1
        else:
            newly_blocked += 1
    return same, newly_passed, newly_blocked


# ---------------------------------------------------------------------------
# PnL estimate
# ---------------------------------------------------------------------------

def estimate_pnl_delta(
    trades: list[dict],
    newly_entered: int,
    newly_skipped: int,
) -> float:
    """Rough estimate of PnL delta from divergences.

    Assumes the marginal newly-entered/newly-skipped trades would have
    performed at the WINDOW AVERAGE PnL per trade. This is a first-order
    approximation — a future wedge can refine with per-decision price
    replay.

    newly_entered trades add +avg_pnl each.
    newly_skipped trades subtract +avg_pnl each (forgone).
    """
    if not trades:
        return 0.0
    avg_pnl = sum(_pnl(t) for t in trades) / len(trades)
    return (newly_entered * avg_pnl) - (newly_skipped * avg_pnl)


# ---------------------------------------------------------------------------
# Core driver
# ---------------------------------------------------------------------------

FLOAT_EDGE_PARAMS: frozenset[str] = frozenset({
    "long_min_edge",
    "short_min_edge",
})

INT_SEVERITY_PARAMS: frozenset[str] = frozenset({
    "short_blocking_catalyst_severity",
})


def evaluate_proposal(
    proposal: dict,
    trades: list[dict],
    decisions: list[dict],
    now: datetime,
    window_days: int,
    min_sample: int,
) -> ShadowEval | None:
    """Compute a ShadowEval for a single approved proposal.

    Returns None if the proposal is not auto-evaluable (unknown action
    kind, unknown param, missing values). Returns a ShadowEval with
    `sample_sufficient=False` if there's not enough data to draw
    conclusions — the caller should still persist these so Chris can
    see "we looked, no signal yet".
    """
    action = proposal.get("proposed_action") or {}
    if action.get("kind") != "config_change":
        return None
    param = action.get("path")
    current_value = action.get("old_value")
    proposed_value = action.get("new_value")
    if param is None or current_value is None or proposed_value is None:
        return None

    windowed_trades = filter_trades_in_window(trades, now, window_days)
    windowed_decisions = filter_decisions_in_window(decisions, now, window_days)

    same = 0
    diverged = 0
    newly_entered = 0
    newly_skipped = 0
    notes = ""

    if param in FLOAT_EDGE_PARAMS:
        direction = "long" if param == "long_min_edge" else "short"
        try:
            cur_f = float(current_value)
            prop_f = float(proposed_value)
        except (TypeError, ValueError):
            return None
        same, newly_entered, newly_skipped = counterfactual_edge_threshold_replay(
            windowed_decisions, cur_f, prop_f, direction_filter=direction,
        )
        diverged = newly_entered + newly_skipped
        notes = (
            f"Edge-threshold replay: {newly_entered} newly entered, "
            f"{newly_skipped} newly skipped, {same} unchanged."
        )
    elif param in INT_SEVERITY_PARAMS:
        try:
            cur_i = int(current_value)
            prop_i = int(proposed_value)
        except (TypeError, ValueError):
            return None
        same, newly_entered, newly_skipped = counterfactual_severity_floor_replay(
            windowed_decisions, cur_i, prop_i, direction_filter="short",
        )
        diverged = newly_entered + newly_skipped
        notes = (
            f"Severity-floor replay: {newly_entered} newly passed, "
            f"{newly_skipped} newly blocked, {same} unchanged."
        )
    else:
        # Unknown param — cannot replay, but still record that we looked
        return ShadowEval(
            proposal_id=int(proposal.get("id", 0)),
            proposal_type=str(proposal.get("type", "")),
            evaluated_at=now.isoformat(),
            window_days=window_days,
            trades_in_window=len(windowed_trades),
            decisions_in_window=len(windowed_decisions),
            param=param,
            current_value=current_value,
            proposed_value=proposed_value,
            would_have_entered_same=0,
            would_have_diverged=0,
            divergence_rate=0.0,
            sample_sufficient=False,
            counterfactual_pnl_estimate_usd=0.0,
            notes=f"param {param!r} has no counterfactual replay rule yet",
        )

    total = same + diverged
    divergence_rate = (diverged / total) if total > 0 else 0.0
    pnl_delta = estimate_pnl_delta(windowed_trades, newly_entered, newly_skipped)
    sample_ok = len(windowed_decisions) >= min_sample

    return ShadowEval(
        proposal_id=int(proposal.get("id", 0)),
        proposal_type=str(proposal.get("type", "")),
        evaluated_at=now.isoformat(),
        window_days=window_days,
        trades_in_window=len(windowed_trades),
        decisions_in_window=len(windowed_decisions),
        param=param,
        current_value=current_value,
        proposed_value=proposed_value,
        would_have_entered_same=same,
        would_have_diverged=diverged,
        divergence_rate=divergence_rate,
        sample_sufficient=sample_ok,
        counterfactual_pnl_estimate_usd=pnl_delta,
        notes=notes,
    )


def shadow_eval_to_dict(s: ShadowEval) -> dict:
    return asdict(s)
