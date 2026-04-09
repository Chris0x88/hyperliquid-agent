"""Tests for modules/oil_botpattern_tune.py — sub-system 6 L1 pure logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from modules.oil_botpattern_tune import (
    INTEGER_PARAMS,
    TUNABLE_PARAMS,
    OutcomeStats,
    ParamBound,
    TuneProposal,
    apply_proposals,
    audit_to_dict,
    build_audit_index,
    compute_outcome_stats,
    compute_proposals,
    count_gate_blocks,
    nudge_direction_funding_exit_pct,
    nudge_direction_funding_warn_pct,
    nudge_direction_long_min_edge,
    nudge_direction_short_catalyst_sev,
    nudge_direction_short_min_edge,
    parse_bounds,
)


UTC = timezone.utc


def _now() -> datetime:
    return datetime(2026, 4, 9, 10, 0, tzinfo=UTC)


def _bounds() -> dict[str, ParamBound]:
    return parse_bounds({
        "long_min_edge":                    {"min": 0.35, "max": 0.70, "type": "float"},
        "short_min_edge":                   {"min": 0.55, "max": 0.85, "type": "float"},
        "funding_warn_pct":                 {"min": 0.30, "max": 1.00, "type": "float"},
        "funding_exit_pct":                 {"min": 1.00, "max": 2.50, "type": "float"},
        "short_blocking_catalyst_severity": {"min": 3,    "max": 5,    "type": "int"},
    })


def _base_config() -> dict:
    return {
        "long_min_edge": 0.50,
        "short_min_edge": 0.70,
        "funding_warn_pct": 0.50,
        "funding_exit_pct": 1.50,
        "short_blocking_catalyst_severity": 4,
        "enabled": False,
        "instruments": ["BRENTOIL", "CL"],
    }


# ---------------------------------------------------------------------------
# ParamBound
# ---------------------------------------------------------------------------

def test_parambound_clamp_float():
    b = ParamBound("long_min_edge", 0.35, 0.70, "float")
    assert b.clamp(0.20) == 0.35
    assert b.clamp(0.50) == 0.50
    assert b.clamp(0.80) == 0.70
    assert isinstance(b.clamp(0.50), float)


def test_parambound_clamp_int_rounds():
    b = ParamBound("short_blocking_catalyst_severity", 3, 5, "int")
    assert b.clamp(2) == 3
    assert b.clamp(3.4) == 3
    assert b.clamp(4.6) == 5
    assert b.clamp(6) == 5
    assert isinstance(b.clamp(3.6), int)


def test_parambound_rejects_inverted_range():
    with pytest.raises(ValueError):
        ParamBound("bad", 0.9, 0.1, "float")


def test_parambound_rejects_bad_type():
    with pytest.raises(ValueError):
        ParamBound("bad", 0.1, 0.9, "string")


# ---------------------------------------------------------------------------
# parse_bounds
# ---------------------------------------------------------------------------

def test_parse_bounds_drops_unknown_params():
    result = parse_bounds({
        "long_min_edge": {"min": 0.35, "max": 0.70, "type": "float"},
        "rogue_param":   {"min": 0.0,  "max": 1.0,  "type": "float"},  # dropped
    })
    assert "long_min_edge" in result
    assert "rogue_param" not in result


def test_parse_bounds_rejects_malformed():
    with pytest.raises(ValueError):
        parse_bounds({"long_min_edge": {"min": "oops", "max": 0.70}})


# ---------------------------------------------------------------------------
# compute_outcome_stats
# ---------------------------------------------------------------------------

def test_outcome_stats_empty_window():
    stats = compute_outcome_stats([])
    assert stats.sample_size == 0
    assert stats.winrate == 0.0
    assert stats.long_sample == 0


def test_outcome_stats_splits_longs_shorts():
    trades = [
        {"side": "long",  "realised_pnl_usd": 100, "roe_pct": 5.0, "close_reason": "tp_hit"},
        {"side": "long",  "realised_pnl_usd": -50, "roe_pct": -2.0, "close_reason": "sl_hit"},
        {"side": "short", "realised_pnl_usd": 30,  "roe_pct": 1.5, "close_reason": "hold_cap"},
        {"side": "short", "realised_pnl_usd": -20, "roe_pct": -1.0, "close_reason": "sl_hit"},
    ]
    stats = compute_outcome_stats(trades)
    assert stats.sample_size == 4
    assert stats.long_sample == 2
    assert stats.short_sample == 2
    assert stats.long_winrate == 0.5
    assert stats.short_winrate == 0.5


def test_outcome_stats_funding_exit_rate():
    trades = [
        {"side": "long", "realised_pnl_usd": -20, "roe_pct": -2.0, "close_reason": "funding_cost_exit"},
        {"side": "long", "realised_pnl_usd": 100, "roe_pct": 5.0,  "close_reason": "tp_hit"},
        {"side": "long", "realised_pnl_usd": -10, "roe_pct": -1.0, "close_reason": "funding_cost_exit"},
    ]
    stats = compute_outcome_stats(trades)
    assert stats.long_sample == 3
    assert stats.long_funding_exit_rate == pytest.approx(2 / 3)
    assert stats.long_avg_funding_exit_roe_pct == pytest.approx(-1.5)


def test_outcome_stats_hold_hours_from_timestamps():
    trades = [
        {
            "side": "long",
            "realised_pnl_usd": 50,
            "roe_pct": 2.0,
            "entry_ts": "2026-04-01T00:00:00+00:00",
            "close_ts": "2026-04-01T05:00:00+00:00",  # 5h
        },
    ]
    stats = compute_outcome_stats(trades)
    assert stats.long_avg_hold_hours == pytest.approx(5.0)


def test_outcome_stats_hold_hours_from_holding_ms():
    trades = [
        {"side": "long", "realised_pnl_usd": 50, "roe_pct": 2.0, "holding_ms": 3 * 3600 * 1000},
    ]
    stats = compute_outcome_stats(trades)
    assert stats.long_avg_hold_hours == pytest.approx(3.0)


def test_outcome_stats_infers_side_from_signed_size():
    trades = [
        {"size": 10.0, "realised_pnl_usd": 50, "roe_pct": 2.0},   # long
        {"size": -5.0, "realised_pnl_usd": -20, "roe_pct": -1.0},  # short
    ]
    stats = compute_outcome_stats(trades)
    assert stats.long_sample == 1
    assert stats.short_sample == 1


# ---------------------------------------------------------------------------
# count_gate_blocks
# ---------------------------------------------------------------------------

def test_count_gate_blocks_filters_by_name_and_direction():
    decisions = [
        {"direction": "short", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": False, "reason": "sev4"},
        ]},
        {"direction": "short", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": True, "reason": "clear"},
        ]},
        {"direction": "long", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": False, "reason": "sev4"},
        ]},
    ]
    assert count_gate_blocks(decisions, "no_blocking_catalyst") == 2
    assert count_gate_blocks(decisions, "no_blocking_catalyst", "short") == 1


def test_count_gate_blocks_tolerates_missing_results():
    decisions = [{"direction": "long"}, {"direction": "short", "gate_results": None}]
    assert count_gate_blocks(decisions, "any") == 0


# ---------------------------------------------------------------------------
# Nudge direction heuristics
# ---------------------------------------------------------------------------

def test_long_min_edge_loosens_on_high_winrate():
    stats = OutcomeStats(long_sample=10, long_winrate=0.80)
    assert nudge_direction_long_min_edge(stats, min_sample=5) == -1


def test_long_min_edge_tightens_on_low_winrate():
    stats = OutcomeStats(long_sample=10, long_winrate=0.20)
    assert nudge_direction_long_min_edge(stats, min_sample=5) == +1


def test_long_min_edge_no_nudge_on_mid_winrate():
    stats = OutcomeStats(long_sample=10, long_winrate=0.50)
    assert nudge_direction_long_min_edge(stats, min_sample=5) == 0


def test_long_min_edge_no_nudge_below_min_sample():
    stats = OutcomeStats(long_sample=2, long_winrate=0.80)
    assert nudge_direction_long_min_edge(stats, min_sample=5) == 0


def test_short_min_edge_loosens_on_high_winrate():
    stats = OutcomeStats(short_sample=10, short_winrate=0.70)
    assert nudge_direction_short_min_edge(stats, min_sample=5) == -1


def test_short_min_edge_tightens_on_low_winrate():
    stats = OutcomeStats(short_sample=10, short_winrate=0.30)
    assert nudge_direction_short_min_edge(stats, min_sample=5) == +1


def test_funding_warn_tightens_on_losing_funding_exits():
    stats = OutcomeStats(
        long_sample=10, long_funding_exit_rate=0.40,
        long_avg_funding_exit_roe_pct=-2.5, long_avg_hold_hours=72,
    )
    assert nudge_direction_funding_warn_pct(stats, min_sample=5) == -1


def test_funding_warn_loosens_on_no_funding_exits_and_long_hold():
    stats = OutcomeStats(
        long_sample=10, long_funding_exit_rate=0.0,
        long_avg_hold_hours=8 * 24,
    )
    assert nudge_direction_funding_warn_pct(stats, min_sample=5) == +1


def test_funding_exit_only_tightens_on_clear_losses():
    stats = OutcomeStats(
        long_sample=10, long_funding_exit_rate=0.40,
        long_avg_funding_exit_roe_pct=-3.0,
    )
    assert nudge_direction_funding_exit_pct(stats, min_sample=5) == -1


def test_funding_exit_loosens_only_on_very_long_holds():
    stats = OutcomeStats(
        long_sample=10, long_funding_exit_rate=0.0,
        long_avg_hold_hours=8 * 24,  # only 8 days — not enough
    )
    assert nudge_direction_funding_exit_pct(stats, min_sample=5) == 0

    stats2 = OutcomeStats(
        long_sample=10, long_funding_exit_rate=0.0,
        long_avg_hold_hours=15 * 24,  # ≥14 days
    )
    assert nudge_direction_funding_exit_pct(stats2, min_sample=5) == +1


def test_short_catalyst_sev_tightens_when_losses_and_low_blocks():
    stats = OutcomeStats(short_sample=10, short_avg_roe_pct=-1.5)
    decisions = [
        {"direction": "short", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": True, "reason": "clear"},
        ]},
    ]
    assert nudge_direction_short_catalyst_sev(stats, decisions, min_sample=5) == +1


def test_short_catalyst_sev_loosens_when_wins_and_many_blocks():
    stats = OutcomeStats(short_sample=10, short_avg_roe_pct=1.5)
    decisions = [
        {"direction": "short", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": False, "reason": f"sev{i}"},
        ]}
        for i in range(4)
    ]
    assert nudge_direction_short_catalyst_sev(stats, decisions, min_sample=5) == -1


# ---------------------------------------------------------------------------
# compute_proposals (end-to-end of the pure layer)
# ---------------------------------------------------------------------------

def _winning_longs(n: int) -> list[dict]:
    return [
        {"side": "long", "realised_pnl_usd": 100, "roe_pct": 5.0,
         "close_reason": "tp_hit", "trade_id": f"L{i}"}
        for i in range(n)
    ]


def _losing_shorts(n: int) -> list[dict]:
    return [
        {"side": "short", "realised_pnl_usd": -50, "roe_pct": -2.0,
         "close_reason": "sl_hit", "trade_id": f"S{i}"}
        for i in range(n)
    ]


def test_compute_proposals_loosens_long_entry_on_winning_longs():
    cfg = _base_config()
    trades = _winning_longs(6)
    proposals = compute_proposals(
        current_config=cfg, bounds=_bounds(),
        trades=trades, decisions=[], audit_index={},
        now=_now(), min_sample=5, rel_step_max=0.05, rate_limit_hours=24,
    )
    # long_min_edge should be nudged DOWN from 0.50
    long_nudges = [p for p in proposals if p.param == "long_min_edge"]
    assert len(long_nudges) == 1
    assert long_nudges[0].new_value < 0.50
    assert long_nudges[0].new_value >= 0.35  # clamped to min


def test_compute_proposals_respects_rate_limit():
    cfg = _base_config()
    trades = _winning_longs(6)
    recent = (_now() - timedelta(hours=2)).isoformat()
    proposals = compute_proposals(
        current_config=cfg, bounds=_bounds(),
        trades=trades, decisions=[],
        audit_index={"long_min_edge": recent},
        now=_now(), min_sample=5, rel_step_max=0.05, rate_limit_hours=24,
    )
    assert not any(p.param == "long_min_edge" for p in proposals)


def test_compute_proposals_no_nudge_below_min_sample():
    cfg = _base_config()
    trades = _winning_longs(2)  # only 2, below min_sample=5
    proposals = compute_proposals(
        current_config=cfg, bounds=_bounds(),
        trades=trades, decisions=[], audit_index={},
        now=_now(), min_sample=5, rel_step_max=0.05, rate_limit_hours=24,
    )
    assert proposals == []


def test_compute_proposals_clamps_at_bound_and_skips_no_op():
    cfg = _base_config()
    cfg["long_min_edge"] = 0.35  # already at the floor
    trades = _winning_longs(6)
    proposals = compute_proposals(
        current_config=cfg, bounds=_bounds(),
        trades=trades, decisions=[], audit_index={},
        now=_now(), min_sample=5, rel_step_max=0.05, rate_limit_hours=24,
    )
    # Trying to loosen further from the floor → clamp → no net change → no proposal
    assert not any(p.param == "long_min_edge" for p in proposals)


def test_compute_proposals_integer_param_steps_by_one():
    cfg = _base_config()
    trades = [
        *_losing_shorts(6),
    ]
    decisions = [
        {"direction": "short", "gate_results": [
            {"name": "no_blocking_catalyst", "passed": True, "reason": "clear"},
        ]},
    ]
    proposals = compute_proposals(
        current_config=cfg, bounds=_bounds(),
        trades=trades, decisions=decisions, audit_index={},
        now=_now(), min_sample=5, rel_step_max=0.05, rate_limit_hours=24,
    )
    sev = [p for p in proposals if p.param == "short_blocking_catalyst_severity"]
    assert len(sev) == 1
    # Should increase by exactly 1 (4 → 5) and clamp at max 5
    assert sev[0].new_value == 5
    assert isinstance(sev[0].new_value, int)


def test_compute_proposals_maintains_funding_warn_exit_spread():
    """funding_exit_pct must stay ≥ funding_warn_pct + 0.5."""
    cfg = _base_config()
    cfg["funding_warn_pct"] = 0.80  # near the top
    cfg["funding_exit_pct"] = 1.30  # too close

    # Create a stats profile that asks to tighten funding_exit (lower it)
    trades = [
        {"side": "long", "realised_pnl_usd": -10, "roe_pct": -2.0,
         "close_reason": "funding_cost_exit", "trade_id": f"F{i}"}
        for i in range(4)
    ] + [
        {"side": "long", "realised_pnl_usd": 50, "roe_pct": 3.0,
         "close_reason": "tp_hit", "trade_id": f"W{i}"}
        for i in range(6)
    ]
    proposals = compute_proposals(
        current_config=cfg, bounds=_bounds(),
        trades=trades, decisions=[], audit_index={},
        now=_now(), min_sample=5, rel_step_max=0.05, rate_limit_hours=24,
    )
    for p in proposals:
        if p.param == "funding_exit_pct":
            # Must still be ≥ warn + 0.5 = 1.30
            assert p.new_value >= cfg["funding_warn_pct"] + 0.5 - 1e-9


def test_compute_proposals_skips_unknown_param_in_bounds():
    cfg = _base_config()
    trades = _winning_longs(6)
    # bounds will silently drop the rogue key via parse_bounds
    bounds = parse_bounds({
        "long_min_edge": {"min": 0.35, "max": 0.70, "type": "float"},
        "rogue": {"min": 0, "max": 1, "type": "float"},
    })
    assert "rogue" not in bounds
    proposals = compute_proposals(
        current_config=cfg, bounds=bounds,
        trades=trades, decisions=[], audit_index={},
        now=_now(), min_sample=5, rel_step_max=0.05, rate_limit_hours=24,
    )
    assert all(p.param in TUNABLE_PARAMS for p in proposals)


# ---------------------------------------------------------------------------
# apply_proposals
# ---------------------------------------------------------------------------

def test_apply_proposals_updates_config_and_audits():
    cfg = _base_config()
    proposals = [
        TuneProposal(
            param="long_min_edge",
            old_value=0.50, new_value=0.475,
            reason="test",
            stats_sample_size=10,
            stats_snapshot={},
            trade_ids_considered=["L0", "L1"],
        ),
    ]
    new_cfg, audits = apply_proposals(cfg, proposals)
    assert new_cfg["long_min_edge"] == 0.475
    assert cfg["long_min_edge"] == 0.50  # original untouched
    assert len(audits) == 1
    assert audits[0].param == "long_min_edge"
    assert audits[0].source == "l1_auto_tune"


def test_apply_proposals_preserves_structural_fields():
    cfg = _base_config()
    proposals = [
        TuneProposal(
            param="long_min_edge", old_value=0.50, new_value=0.45,
            reason="x", stats_sample_size=10, stats_snapshot={},
            trade_ids_considered=[],
        ),
    ]
    new_cfg, _ = apply_proposals(cfg, proposals)
    assert new_cfg["enabled"] is False
    assert new_cfg["instruments"] == ["BRENTOIL", "CL"]


def test_apply_proposals_integer_roundtrip():
    cfg = _base_config()
    proposals = [
        TuneProposal(
            param="short_blocking_catalyst_severity",
            old_value=4, new_value=5.0,
            reason="x", stats_sample_size=10, stats_snapshot={},
            trade_ids_considered=[],
        ),
    ]
    new_cfg, _ = apply_proposals(cfg, proposals)
    assert new_cfg["short_blocking_catalyst_severity"] == 5
    assert isinstance(new_cfg["short_blocking_catalyst_severity"], int)


def test_apply_proposals_rejects_non_whitelist_param():
    cfg = _base_config()
    proposals = [
        TuneProposal(
            param="enabled", old_value=False, new_value=True,
            reason="rogue", stats_sample_size=10, stats_snapshot={},
            trade_ids_considered=[],
        ),
    ]
    new_cfg, audits = apply_proposals(cfg, proposals)
    assert new_cfg["enabled"] is False  # untouched
    assert audits == []


def test_build_audit_index_picks_latest():
    rows = [
        {"param": "long_min_edge", "applied_at": "2026-04-08T10:00:00+00:00"},
        {"param": "long_min_edge", "applied_at": "2026-04-09T10:00:00+00:00"},
        {"param": "short_min_edge", "applied_at": "2026-04-07T12:00:00+00:00"},
        {"not_a_row": True},  # tolerated
    ]
    idx = build_audit_index(rows)
    assert idx["long_min_edge"] == "2026-04-09T10:00:00+00:00"
    assert idx["short_min_edge"] == "2026-04-07T12:00:00+00:00"


def test_audit_to_dict_serializable():
    from modules.oil_botpattern_tune import TuneAuditRecord
    rec = TuneAuditRecord(
        applied_at="2026-04-09T10:00:00+00:00",
        param="long_min_edge", old_value=0.50, new_value=0.475,
        reason="x", stats_sample_size=10, stats_snapshot={"winrate": 0.7},
        trade_ids_considered=["L0"],
    )
    d = audit_to_dict(rec)
    assert d["param"] == "long_min_edge"
    assert d["source"] == "l1_auto_tune"
    assert d["stats_snapshot"] == {"winrate": 0.7}


# ---------------------------------------------------------------------------
# Invariants (guardrails on the contract)
# ---------------------------------------------------------------------------

def test_integer_params_subset_of_tunable():
    assert INTEGER_PARAMS.issubset(set(TUNABLE_PARAMS))


def test_tunable_params_do_not_include_structural():
    forbidden = {
        "enabled", "short_legs_enabled", "instruments",
        "drawdown_brakes", "short_max_hold_hours",
        "sizing_ladder", "preferred_sl_atr_mult", "preferred_tp_atr_mult",
    }
    assert forbidden.isdisjoint(set(TUNABLE_PARAMS))
