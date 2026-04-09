"""Tests for modules/oil_botpattern_reflect.py — sub-system 6 L2 pure logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from modules.oil_botpattern_reflect import (
    PROPOSAL_TYPES,
    ProposedAction,
    StructuralProposal,
    compute_weekly_proposals,
    detect_funding_exit_expensive,
    detect_gate_overblock,
    detect_instrument_dead,
    detect_thesis_conflict_frequent,
    filter_window_decisions,
    filter_window_trades,
    proposal_from_dict,
    proposal_to_dict,
)


UTC = timezone.utc


def _now() -> datetime:
    return datetime(2026, 4, 9, 10, 0, tzinfo=UTC)


def _in_window_ts(days_ago: float) -> str:
    return (_now() - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def test_filter_window_trades_keeps_recent():
    trades = [
        {"close_ts": _in_window_ts(1), "realised_pnl_usd": 10},
        {"close_ts": _in_window_ts(10), "realised_pnl_usd": 5},  # outside 7d
    ]
    window_start = _now() - timedelta(days=7)
    kept = filter_window_trades(trades, window_start)
    assert len(kept) == 1


def test_filter_window_trades_drops_missing_ts():
    trades = [{"realised_pnl_usd": 10}]  # no close_ts
    kept = filter_window_trades(trades, _now() - timedelta(days=7))
    assert kept == []


def test_filter_window_decisions_keeps_recent():
    decisions = [
        {"decided_at": _in_window_ts(2), "id": "D1"},
        {"decided_at": _in_window_ts(8), "id": "D2"},
    ]
    kept = filter_window_decisions(decisions, _now() - timedelta(days=7))
    assert len(kept) == 1
    assert kept[0]["id"] == "D1"


# ---------------------------------------------------------------------------
# detect_gate_overblock
# ---------------------------------------------------------------------------

def test_gate_overblock_fires_on_many_failures():
    decisions = [
        {"id": f"D{i}", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": False, "reason": "sev4"},
        ]}
        for i in range(6)
    ]
    proposals = detect_gate_overblock(decisions, min_sample=5, now=_now())
    assert len(proposals) == 1
    assert proposals[0].type == "gate_overblock"
    assert proposals[0].evidence["gate_name"] == "no_blocking_catalyst"
    assert proposals[0].evidence["hits"] == 6


def test_gate_overblock_skips_below_min_sample():
    decisions = [
        {"id": f"D{i}", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": False},
        ]}
        for i in range(3)
    ]
    proposals = detect_gate_overblock(decisions, min_sample=5, now=_now())
    assert proposals == []


def test_gate_overblock_ignores_passing_gates():
    decisions = [
        {"id": f"D{i}", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": True, "reason": "clear"},
        ]}
        for i in range(10)
    ]
    proposals = detect_gate_overblock(decisions, min_sample=5, now=_now())
    assert proposals == []


def test_gate_overblock_handles_missing_gate_results():
    decisions = [{"id": "D1"}, {"id": "D2", "gate_results": None}]
    proposals = detect_gate_overblock(decisions, min_sample=1, now=_now())
    assert proposals == []


# ---------------------------------------------------------------------------
# detect_instrument_dead
# ---------------------------------------------------------------------------

def test_instrument_dead_fires_on_zero_wins():
    trades = [
        {"instrument": "CL", "realised_pnl_usd": -20, "trade_id": f"T{i}"}
        for i in range(5)
    ]
    proposals = detect_instrument_dead(trades, min_sample=5, now=_now())
    assert len(proposals) == 1
    assert proposals[0].type == "instrument_dead"
    assert proposals[0].evidence["instrument"] == "CL"
    assert proposals[0].evidence["wins"] == 0


def test_instrument_dead_no_fire_with_winner():
    trades = [
        {"instrument": "CL", "realised_pnl_usd": -20},
        {"instrument": "CL", "realised_pnl_usd": -10},
        {"instrument": "CL", "realised_pnl_usd": -5},
        {"instrument": "CL", "realised_pnl_usd": -1},
        {"instrument": "CL", "realised_pnl_usd": 5},  # one winner
    ]
    proposals = detect_instrument_dead(trades, min_sample=5, now=_now())
    assert proposals == []


def test_instrument_dead_no_fire_below_sample():
    trades = [
        {"instrument": "CL", "realised_pnl_usd": -20},
        {"instrument": "CL", "realised_pnl_usd": -10},
    ]
    proposals = detect_instrument_dead(trades, min_sample=5, now=_now())
    assert proposals == []


def test_instrument_dead_uses_market_field_fallback():
    trades = [
        {"market": "BRENTOIL", "realised_pnl_usd": -20}
        for _ in range(5)
    ]
    proposals = detect_instrument_dead(trades, min_sample=5, now=_now())
    assert len(proposals) == 1
    assert proposals[0].evidence["instrument"] == "BRENTOIL"


# ---------------------------------------------------------------------------
# detect_thesis_conflict_frequent
# ---------------------------------------------------------------------------

def test_thesis_conflict_fires_on_many_failures():
    decisions = [
        {"id": f"D{i}", "gate_results": [
            {"name": "thesis_conflict", "passed": False, "reason": "opposite"},
        ]}
        for i in range(5)
    ]
    proposals = detect_thesis_conflict_frequent(decisions, min_sample=5, now=_now())
    assert len(proposals) == 1
    assert proposals[0].type == "thesis_conflict_frequent"


def test_thesis_conflict_no_fire_below_sample():
    decisions = [
        {"id": "D1", "gate_results": [
            {"name": "thesis_conflict", "passed": False},
        ]},
    ]
    proposals = detect_thesis_conflict_frequent(decisions, min_sample=5, now=_now())
    assert proposals == []


# ---------------------------------------------------------------------------
# detect_funding_exit_expensive
# ---------------------------------------------------------------------------

def test_funding_exit_expensive_fires_on_losses():
    trades = [
        {"close_reason": "funding_cost_exit", "realised_pnl_usd": -20, "roe_pct": -3.0,
         "trade_id": f"F{i}"}
        for i in range(5)
    ]
    proposals = detect_funding_exit_expensive(trades, min_sample=5, now=_now())
    assert len(proposals) == 1
    assert proposals[0].type == "funding_exit_expensive"
    assert proposals[0].evidence["avg_roe_pct"] == -3.0


def test_funding_exit_expensive_no_fire_on_profitable_exits():
    trades = [
        {"close_reason": "funding_cost_exit", "realised_pnl_usd": 5, "roe_pct": 0.5}
        for _ in range(5)
    ]
    proposals = detect_funding_exit_expensive(trades, min_sample=5, now=_now())
    assert proposals == []


def test_funding_exit_expensive_no_fire_below_sample():
    trades = [
        {"close_reason": "funding_cost_exit", "realised_pnl_usd": -20, "roe_pct": -3.0},
    ]
    proposals = detect_funding_exit_expensive(trades, min_sample=5, now=_now())
    assert proposals == []


# ---------------------------------------------------------------------------
# compute_weekly_proposals — end-to-end
# ---------------------------------------------------------------------------

def test_weekly_proposals_assigns_monotonic_ids():
    trades = [
        {"close_ts": _in_window_ts(1), "instrument": "CL",
         "realised_pnl_usd": -10, "roe_pct": -1.0}
        for _ in range(6)
    ]
    decisions = [
        {"decided_at": _in_window_ts(1), "id": f"D{i}", "gate_results": [
            {"name": "thesis_conflict", "passed": False, "reason": "opposite"},
        ]}
        for i in range(5)
    ]
    proposals = compute_weekly_proposals(
        trades=trades, decisions=decisions,
        window_days=7, min_sample_per_rule=5, now=_now(), next_id=42,
    )
    assert len(proposals) >= 2
    ids = [p.id for p in proposals]
    assert ids[0] == 42
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_weekly_proposals_empty_window_returns_empty():
    proposals = compute_weekly_proposals(
        trades=[], decisions=[],
        window_days=7, min_sample_per_rule=5, now=_now(),
    )
    assert proposals == []


def test_weekly_proposals_respects_window_boundary():
    # All data is 10 days old → outside a 7-day window
    trades = [
        {"close_ts": _in_window_ts(10), "instrument": "CL",
         "realised_pnl_usd": -10, "roe_pct": -1.0}
        for _ in range(6)
    ]
    proposals = compute_weekly_proposals(
        trades=trades, decisions=[],
        window_days=7, min_sample_per_rule=5, now=_now(),
    )
    assert proposals == []


def test_weekly_proposals_types_are_subset_of_defined():
    trades = [
        {"close_ts": _in_window_ts(1), "instrument": "CL",
         "realised_pnl_usd": -10, "roe_pct": -1.0,
         "close_reason": "funding_cost_exit"}
        for _ in range(6)
    ]
    proposals = compute_weekly_proposals(
        trades=trades, decisions=[],
        window_days=7, min_sample_per_rule=5, now=_now(),
    )
    for p in proposals:
        assert p.type in PROPOSAL_TYPES


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def test_proposal_roundtrip():
    p = StructuralProposal(
        id=7, created_at="2026-04-09T10:00:00+00:00",
        type="instrument_dead",
        description="test",
        evidence={"instrument": "CL"},
        proposed_action={"kind": "advisory"},
    )
    d = proposal_to_dict(p)
    back = proposal_from_dict(d)
    assert back.id == 7
    assert back.type == "instrument_dead"
    assert back.evidence == {"instrument": "CL"}
    assert back.status == "pending"


def test_proposal_from_dict_tolerates_missing_fields():
    back = proposal_from_dict({"id": 1})
    assert back.id == 1
    assert back.type == ""
    assert back.status == "pending"
