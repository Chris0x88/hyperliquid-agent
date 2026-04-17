"""Tests for engines/checklist/evaluators.py — pure unit tests, no network."""
from __future__ import annotations

import pytest

from engines.checklist.evaluators import (
    eval_sl_on_exchange,
    eval_tp_on_exchange,
    eval_cumulative_risk,
    eval_leverage_vs_thesis,
    eval_funding_cost,
    eval_weekend_leverage,
    eval_sweep_risk,
    eval_overnight_fills,
    eval_cascade_events,
)

# ── Fixtures ──────────────────────────────────────────────────

SILVER_LONG = {
    "coin": "xyz:SILVER",
    "size": 50.0,
    "entry": 75.0,
    "upnl": -300.0,
    "leverage": "25",
    "margin_used": 3000.0,
    "liq": 68.0,
}

SILVER_LONG_NO_LIQ = {
    "coin": "xyz:SILVER",
    "size": 50.0,
    "entry": 75.0,
    "upnl": 0.0,
    "leverage": "25",
    "margin_used": 3000.0,
}

SL_ORDER = {
    "coin": "xyz:SILVER",
    "tpsl": "sl",
    "orderType": "Stop Market",
    "reduceOnly": True,
    "triggerPx": "68.0",
}

TP_ORDER = {
    "coin": "xyz:SILVER",
    "tpsl": "tp",
    "orderType": "Take Profit Market",
    "reduceOnly": True,
    "triggerPx": "95.0",
}

SILVER_THESIS = {
    "market": "xyz:SILVER",
    "direction": "long",
    "conviction": 0.55,
    "recommended_leverage": 3.0,
    "weekend_leverage_cap": 2.0,
    "take_profit_price": 95.0,
}


def _base_ctx(**overrides):
    ctx = {
        "positions": [SILVER_LONG],
        "orders": [SL_ORDER, TP_ORDER],
        "total_equity": 10000.0,
        "thesis": SILVER_THESIS,
        "market_price": 72.0,
        "atr": 2.5,
        "funding_rate": 0.0001,
        "catalysts": [],
        "heatmap_zones": [],
        "cascades": [],
        "bot_patterns": [],
        "closed_since": [],
        "filled_orders": [],
        "sweep_result": None,
        "is_friday_brisbane": False,
    }
    ctx.update(overrides)
    return ctx


# ── sl_on_exchange ────────────────────────────────────────────

class TestSlOnExchange:
    def test_pass_when_sl_present(self):
        ctx = _base_ctx()
        status, reason, data = eval_sl_on_exchange("xyz:SILVER", ctx)
        assert status == "pass"

    def test_fail_when_sl_missing(self):
        ctx = _base_ctx(orders=[TP_ORDER])  # only TP, no SL
        status, reason, data = eval_sl_on_exchange("xyz:SILVER", ctx)
        assert status == "fail"
        assert "UNPROTECTED" in reason

    def test_skip_when_no_position(self):
        ctx = _base_ctx(positions=[])
        status, reason, data = eval_sl_on_exchange("xyz:SILVER", ctx)
        assert status == "skip"

    def test_handles_bare_coin_name(self):
        """Bare coin name (without xyz:) should still match."""
        bare_pos = dict(SILVER_LONG, coin="SILVER")
        bare_order = dict(SL_ORDER, coin="SILVER")
        ctx = _base_ctx(positions=[bare_pos], orders=[bare_order])
        status, _, _ = eval_sl_on_exchange("xyz:SILVER", ctx)
        assert status == "pass"


# ── tp_on_exchange ────────────────────────────────────────────

class TestTpOnExchange:
    def test_pass_when_tp_present(self):
        ctx = _base_ctx()
        status, reason, data = eval_tp_on_exchange("xyz:SILVER", ctx)
        assert status == "pass"

    def test_warn_when_tp_missing(self):
        ctx = _base_ctx(orders=[SL_ORDER])  # only SL, no TP
        status, reason, data = eval_tp_on_exchange("xyz:SILVER", ctx)
        assert status == "warn"
        assert "No TP" in reason

    def test_warn_includes_thesis_tp_hint(self):
        ctx = _base_ctx(orders=[SL_ORDER])
        status, reason, data = eval_tp_on_exchange("xyz:SILVER", ctx)
        assert "95" in reason  # thesis TP at $95

    def test_skip_when_no_position(self):
        ctx = _base_ctx(positions=[])
        status, _, _ = eval_tp_on_exchange("xyz:SILVER", ctx)
        assert status == "skip"


# ── cumulative_risk ───────────────────────────────────────────

class TestCumulativeRisk:
    def test_pass_when_low_risk(self):
        ctx = _base_ctx(total_equity=100000.0)  # 3000/100000 = 3%
        status, reason, data = eval_cumulative_risk("xyz:SILVER", ctx)
        assert status == "pass"
        assert data["open_risk_pct"] == pytest.approx(3.0, rel=0.01)

    def test_warn_at_8_pct(self):
        ctx = _base_ctx(total_equity=37000.0)  # 3000/37000 ≈ 8.1%
        status, reason, data = eval_cumulative_risk("xyz:SILVER", ctx)
        assert status == "warn"

    def test_fail_at_10_pct(self):
        ctx = _base_ctx(total_equity=28000.0)  # 3000/28000 ≈ 10.7%
        status, reason, data = eval_cumulative_risk("xyz:SILVER", ctx)
        assert status == "fail"

    def test_skip_when_equity_unknown(self):
        ctx = _base_ctx(total_equity=0)
        status, _, _ = eval_cumulative_risk("xyz:SILVER", ctx)
        assert status == "skip"

    def test_multi_position_sum(self):
        """Multiple positions should be summed for margin."""
        extra_pos = dict(SILVER_LONG, coin="xyz:GOLD", margin_used=1500.0)
        ctx = _base_ctx(positions=[SILVER_LONG, extra_pos], total_equity=45000.0)
        # 4500/45000 = 10% — should FAIL
        status, reason, data = eval_cumulative_risk("xyz:SILVER", ctx)
        assert status == "fail"
        assert data["total_margin_usd"] == pytest.approx(4500.0)


# ── leverage_vs_thesis ────────────────────────────────────────

class TestLeverageVsThesis:
    def test_fail_when_way_over_thesis(self):
        # 25x actual vs 3x thesis = ratio 8.3 → FAIL
        ctx = _base_ctx()
        status, reason, data = eval_leverage_vs_thesis("xyz:SILVER", ctx)
        assert status == "fail"
        assert data["ratio"] > 3.0

    def test_warn_when_moderately_over(self):
        # 7x actual vs 3x thesis = ratio 2.3 → WARN
        pos = dict(SILVER_LONG, leverage="7")
        ctx = _base_ctx(positions=[pos])
        status, reason, data = eval_leverage_vs_thesis("xyz:SILVER", ctx)
        assert status == "warn"
        assert 2.0 < data["ratio"] <= 3.0

    def test_pass_when_within_2x(self):
        # 3x actual vs 3x thesis = ratio 1.0 → PASS
        pos = dict(SILVER_LONG, leverage="3")
        ctx = _base_ctx(positions=[pos])
        status, reason, data = eval_leverage_vs_thesis("xyz:SILVER", ctx)
        assert status == "pass"

    def test_skip_when_no_thesis_leverage(self):
        ctx = _base_ctx(thesis={})
        status, _, _ = eval_leverage_vs_thesis("xyz:SILVER", ctx)
        assert status == "skip"

    def test_skip_when_no_position(self):
        ctx = _base_ctx(positions=[])
        status, _, _ = eval_leverage_vs_thesis("xyz:SILVER", ctx)
        assert status == "skip"


# ── funding_cost ──────────────────────────────────────────────

class TestFundingCost:
    def test_pass_when_acceptable(self):
        # 0.0001/h * 8760 = 0.876% annualised — well under 30%
        ctx = _base_ctx(funding_rate=0.0001)
        status, reason, data = eval_funding_cost("xyz:SILVER", ctx)
        assert status == "pass"

    def test_warn_when_over_30_pct(self):
        # 0.0003 * 3 * 365 * 100 = 32.85% annualised → WARN
        ctx = _base_ctx(funding_rate=0.0003)
        status, reason, data = eval_funding_cost("xyz:SILVER", ctx)
        assert status == "warn"
        assert data["annualized_pct"] > 30.0

    def test_fail_when_over_60_pct(self):
        # 0.0006 * 3 * 365 * 100 = 65.7% annualised → FAIL
        ctx = _base_ctx(funding_rate=0.0006)
        status, reason, data = eval_funding_cost("xyz:SILVER", ctx)
        assert status == "fail"

    def test_pass_receiving_funding_as_short(self):
        # Short position receiving positive funding
        # 0.0006 * 3 * 365 * 100 = 65.7% but receiving as short = tailwind
        short_pos = dict(SILVER_LONG, size=-50.0)
        ctx = _base_ctx(positions=[short_pos], funding_rate=0.0006)
        status, reason, data = eval_funding_cost("xyz:SILVER", ctx)
        # Short + positive rate = receiving — pass
        assert status == "pass"
        assert "tailwind" in reason or "Receiving" in reason

    def test_skip_when_no_funding_rate(self):
        ctx = _base_ctx(funding_rate=None)
        status, _, _ = eval_funding_cost("xyz:SILVER", ctx)
        assert status == "skip"

    def test_skip_when_no_position(self):
        ctx = _base_ctx(positions=[])
        status, _, _ = eval_funding_cost("xyz:SILVER", ctx)
        assert status == "skip"


# ── weekend_leverage ──────────────────────────────────────────

class TestWeekendLeverage:
    def test_pass_when_not_friday(self):
        ctx = _base_ctx(is_friday_brisbane=False)
        status, reason, _data = eval_weekend_leverage("xyz:SILVER", ctx)
        assert status == "pass"
        assert "N/A" in reason

    def test_fail_on_friday_over_cap(self):
        ctx = _base_ctx(is_friday_brisbane=True)  # 25x > 2x cap
        status, reason, data = eval_weekend_leverage("xyz:SILVER", ctx)
        assert status == "fail"
        assert "EXCEEDS" in reason

    def test_pass_on_friday_under_cap(self):
        pos = dict(SILVER_LONG, leverage="2")
        ctx = _base_ctx(positions=[pos], is_friday_brisbane=True)
        status, _, _ = eval_weekend_leverage("xyz:SILVER", ctx)
        assert status == "pass"


# ── sweep_risk ────────────────────────────────────────────────

class TestSweepRisk:
    def test_pass_when_score_0(self):
        ctx = _base_ctx(sweep_result={"score": 0, "flags": [], "reasoning": "clean"})
        status, _, _ = eval_sweep_risk("xyz:SILVER", ctx)
        assert status == "pass"

    def test_warn_when_score_1(self):
        ctx = _base_ctx(sweep_result={"score": 1, "flags": ["zone near"], "reasoning": "building"})
        status, _, _ = eval_sweep_risk("xyz:SILVER", ctx)
        assert status == "warn"

    def test_fail_when_score_2(self):
        ctx = _base_ctx(sweep_result={"score": 2, "flags": ["zone", "funding"], "reasoning": "elevated"})
        status, _, _ = eval_sweep_risk("xyz:SILVER", ctx)
        assert status == "fail"

    def test_fail_when_score_3(self):
        ctx = _base_ctx(sweep_result={"score": 3, "flags": ["a", "b", "c"], "reasoning": "imminent"})
        status, _, _ = eval_sweep_risk("xyz:SILVER", ctx)
        assert status == "fail"

    def test_skip_when_no_result(self):
        ctx = _base_ctx(sweep_result=None)
        status, _, _ = eval_sweep_risk("xyz:SILVER", ctx)
        assert status == "skip"


# ── overnight_fills ───────────────────────────────────────────

class TestOvernightFills:
    def test_pass_when_no_fills(self):
        ctx = _base_ctx(filled_orders=[])
        status, reason, data = eval_overnight_fills("xyz:SILVER", ctx)
        assert status == "pass"
        assert "No fills" in reason

    def test_pass_and_reports_fills(self):
        fills = [{"coin": "xyz:SILVER", "side": "buy", "size": 10}]
        ctx = _base_ctx(filled_orders=fills)
        status, reason, data = eval_overnight_fills("xyz:SILVER", ctx)
        assert status == "pass"
        assert "1 fills" in reason
        assert data is not None


# ── cascade_events ────────────────────────────────────────────

class TestCascadeEvents:
    def test_pass_when_no_cascades(self):
        ctx = _base_ctx(cascades=[])
        status, _, _ = eval_cascade_events("xyz:SILVER", ctx)
        assert status == "pass"

    def test_warn_when_cascade_present(self):
        cascade = {
            "instrument": "xyz:SILVER",
            "notional_usd": 5_000_000.0,
            "ts": 1700000000.0,
        }
        ctx = _base_ctx(cascades=[cascade])
        status, reason, data = eval_cascade_events("xyz:SILVER", ctx)
        assert status == "warn"
        assert "cascade" in reason.lower()
        assert data["count"] == 1
