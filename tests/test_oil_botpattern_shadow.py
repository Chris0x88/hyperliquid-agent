"""Tests for modules/oil_botpattern_shadow.py — sub-system 6 L4 pure logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modules.oil_botpattern_shadow import (
    ShadowEval,
    counterfactual_edge_threshold_replay,
    counterfactual_severity_floor_replay,
    estimate_pnl_delta,
    evaluate_proposal,
    filter_decisions_in_window,
    filter_trades_in_window,
    shadow_eval_to_dict,
)


UTC = timezone.utc


def _now() -> datetime:
    return datetime(2026, 4, 9, 10, 0, tzinfo=UTC)


def _in_window_ts(days_ago: float) -> str:
    return (_now() - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# Window filters
# ---------------------------------------------------------------------------

def test_filter_trades_in_window_keeps_recent():
    trades = [
        {"close_ts": _in_window_ts(1)},
        {"close_ts": _in_window_ts(45)},  # outside 30d
    ]
    kept = filter_trades_in_window(trades, _now(), 30)
    assert len(kept) == 1


def test_filter_decisions_in_window_uses_decided_at():
    decisions = [
        {"decided_at": _in_window_ts(2)},
        {"decided_at": _in_window_ts(50)},
    ]
    kept = filter_decisions_in_window(decisions, _now(), 30)
    assert len(kept) == 1


# ---------------------------------------------------------------------------
# counterfactual_edge_threshold_replay
# ---------------------------------------------------------------------------

def test_edge_replay_detects_newly_entered():
    decisions = [
        {"direction": "long", "edge": 0.45},
        {"direction": "long", "edge": 0.50},
    ]
    # Tightening current 0.50 → proposed 0.45 would let 0.45 in (newly entered)
    same, newly_entered, newly_skipped = counterfactual_edge_threshold_replay(
        decisions, current_threshold=0.50, proposed_threshold=0.45,
        direction_filter="long",
    )
    assert newly_entered == 1
    assert newly_skipped == 0
    assert same == 1  # 0.50 stays entered


def test_edge_replay_detects_newly_skipped():
    decisions = [
        {"direction": "long", "edge": 0.45},  # would remain below
        {"direction": "long", "edge": 0.55},  # was entered, now blocked
    ]
    same, newly_entered, newly_skipped = counterfactual_edge_threshold_replay(
        decisions, current_threshold=0.50, proposed_threshold=0.60,
        direction_filter="long",
    )
    assert newly_entered == 0
    assert newly_skipped == 1
    assert same == 1


def test_edge_replay_ignores_wrong_direction():
    decisions = [
        {"direction": "short", "edge": 0.80},
    ]
    same, ne, ns = counterfactual_edge_threshold_replay(
        decisions, 0.50, 0.45, direction_filter="long",
    )
    assert same == 0 and ne == 0 and ns == 0


def test_edge_replay_handles_bad_edge_gracefully():
    decisions = [{"direction": "long", "edge": "oops"}]
    same, ne, ns = counterfactual_edge_threshold_replay(
        decisions, 0.50, 0.45, direction_filter="long",
    )
    assert (same, ne, ns) == (0, 0, 0)


# ---------------------------------------------------------------------------
# counterfactual_severity_floor_replay
# ---------------------------------------------------------------------------

def test_severity_replay_newly_passed():
    # Floor was 4, proposed 5 — a sev4 block would now pass
    decisions = [
        {"direction": "short", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": False,
             "reason": "blocked by sev4 X in next 24h"},
        ]},
    ]
    same, newly_passed, newly_blocked = counterfactual_severity_floor_replay(
        decisions, current_floor=4, proposed_floor=5,
    )
    assert newly_passed == 1
    assert newly_blocked == 0
    assert same == 0


def test_severity_replay_newly_blocked():
    # Floor was 5, proposed 4 — a passing sev4 would now block
    decisions = [
        {"direction": "short", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": True,
             "reason": "clear"},  # no sev captured
        ]},
    ]
    # Passing + no sev in reason → cannot replay → same++
    same, np, nb = counterfactual_severity_floor_replay(
        decisions, current_floor=5, proposed_floor=4,
    )
    assert same == 1
    assert np == 0 and nb == 0


def test_severity_replay_same_at_unchanged_floor():
    decisions = [
        {"direction": "short", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": False,
             "reason": "blocked by sev5 X"},
        ]},
    ]
    same, np, nb = counterfactual_severity_floor_replay(
        decisions, current_floor=4, proposed_floor=5,
    )
    # sev5 blocks at floor 4 AND floor 5 → same
    assert same == 1


def test_severity_replay_skips_non_short_decisions():
    decisions = [{"direction": "long", "gate_results": []}]
    same, np, nb = counterfactual_severity_floor_replay(
        decisions, 4, 5,
    )
    assert (same, np, nb) == (0, 0, 0)


# ---------------------------------------------------------------------------
# estimate_pnl_delta
# ---------------------------------------------------------------------------

def test_estimate_pnl_delta_empty_trades():
    assert estimate_pnl_delta([], 5, 0) == 0.0


def test_estimate_pnl_delta_signs():
    trades = [
        {"realised_pnl_usd": 100},
        {"realised_pnl_usd": 0},
    ]
    # avg = 50
    # newly_entered=2 → +100; newly_skipped=0
    assert estimate_pnl_delta(trades, 2, 0) == 100
    # newly_entered=0 → -100 (forgone 2 × avg)
    assert estimate_pnl_delta(trades, 0, 2) == -100


# ---------------------------------------------------------------------------
# evaluate_proposal
# ---------------------------------------------------------------------------

def _approved_edge_proposal() -> dict:
    return {
        "id": 42,
        "type": "gate_overblock",
        "status": "approved",
        "proposed_action": {
            "kind": "config_change",
            "target": "data/config/oil_botpattern.json",
            "path": "long_min_edge",
            "old_value": 0.50,
            "new_value": 0.45,
        },
    }


def _approved_severity_proposal() -> dict:
    return {
        "id": 7,
        "type": "gate_overblock",
        "status": "approved",
        "proposed_action": {
            "kind": "config_change",
            "target": "data/config/oil_botpattern.json",
            "path": "short_blocking_catalyst_severity",
            "old_value": 4,
            "new_value": 5,
        },
    }


def test_evaluate_edge_proposal_returns_eval():
    decisions = [
        {"direction": "long", "edge": 0.47, "decided_at": _in_window_ts(2)},
        {"direction": "long", "edge": 0.51, "decided_at": _in_window_ts(3)},
        {"direction": "long", "edge": 0.60, "decided_at": _in_window_ts(4)},
        {"direction": "long", "edge": 0.48, "decided_at": _in_window_ts(5)},
        {"direction": "long", "edge": 0.55, "decided_at": _in_window_ts(6)},
    ]
    trades = [
        {"close_ts": _in_window_ts(1), "realised_pnl_usd": 50}
        for _ in range(5)
    ]
    result = evaluate_proposal(
        _approved_edge_proposal(), trades, decisions,
        now=_now(), window_days=30, min_sample=5,
    )
    assert result is not None
    assert result.proposal_id == 42
    assert result.param == "long_min_edge"
    assert result.sample_sufficient is True
    assert result.would_have_diverged >= 1  # 0.47 and 0.48 flip in


def test_evaluate_severity_proposal_returns_eval():
    decisions = [
        {"direction": "short", "decided_at": _in_window_ts(2), "gate_results": [
            {"name": "no_blocking_catalyst", "passed": False,
             "reason": "blocked by sev4 X"},
        ]},
        {"direction": "short", "decided_at": _in_window_ts(3), "gate_results": [
            {"name": "no_blocking_catalyst", "passed": False,
             "reason": "blocked by sev5 Y"},
        ]},
    ]
    result = evaluate_proposal(
        _approved_severity_proposal(), [], decisions,
        now=_now(), window_days=30, min_sample=2,
    )
    assert result is not None
    assert result.param == "short_blocking_catalyst_severity"
    # sev4 → newly_passed (now floor 5, no longer blocks)
    # sev5 → same (still blocks)
    assert result.would_have_diverged == 1


def test_evaluate_rejects_non_config_change():
    proposal = _approved_edge_proposal()
    proposal["proposed_action"]["kind"] = "advisory"
    result = evaluate_proposal(
        proposal, [], [], now=_now(), window_days=30, min_sample=1,
    )
    assert result is None


def test_evaluate_rejects_missing_values():
    proposal = _approved_edge_proposal()
    proposal["proposed_action"].pop("new_value")
    result = evaluate_proposal(
        proposal, [], [], now=_now(), window_days=30, min_sample=1,
    )
    assert result is None


def test_evaluate_unknown_param_returns_advisory_eval():
    proposal = _approved_edge_proposal()
    proposal["proposed_action"]["path"] = "unknown_param"
    result = evaluate_proposal(
        proposal, [], [], now=_now(), window_days=30, min_sample=1,
    )
    assert result is not None
    assert result.sample_sufficient is False
    assert "no counterfactual replay rule" in result.notes


def test_evaluate_insufficient_sample_flagged():
    decisions = [{"direction": "long", "edge": 0.5, "decided_at": _in_window_ts(1)}]
    result = evaluate_proposal(
        _approved_edge_proposal(), [], decisions,
        now=_now(), window_days=30, min_sample=10,
    )
    assert result is not None
    assert result.sample_sufficient is False


def test_shadow_eval_to_dict_serializable():
    eval_obj = ShadowEval(
        proposal_id=1, proposal_type="x", evaluated_at="t",
        window_days=30, trades_in_window=5, decisions_in_window=10,
        param="long_min_edge", current_value=0.5, proposed_value=0.45,
        would_have_entered_same=5, would_have_diverged=2,
        divergence_rate=0.2, sample_sufficient=True,
        counterfactual_pnl_estimate_usd=100.0,
    )
    d = shadow_eval_to_dict(eval_obj)
    assert d["proposal_id"] == 1
    assert d["param"] == "long_min_edge"
    assert d["counterfactual_pnl_estimate_usd"] == 100.0
