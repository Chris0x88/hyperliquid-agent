"""Tests for common/position_risk.py — position-aware dip-add gating."""
import time
import pytest

from common.position_risk import (
    DipAddDecision,
    DipAddGateConfig,
    DipAddGateResult,
    PositionSnapshot,
    evaluate_dip_add_gate,
)


def _make_healthy_position(**overrides) -> PositionSnapshot:
    """A baseline healthy BRENTOIL long — all gates should pass."""
    defaults = dict(
        symbol="BRENTOIL",
        side="long",
        position_qty=10.0,
        position_notional=700.0,     # ~$700 notional
        entry_price=70.0,
        current_price=72.0,          # +2.8% upnl
        liquidation_price=55.0,      # 23.6% below current — very safe
        account_equity=2000.0,       # 35% of equity — comfortably below 60% max
        margin_used=140.0,
        num_adds_this_session=1,
        last_add_timestamp=time.time() - 400,  # 400s ago, past cooldown
        daily_drawdown_pct=1.0,
        cumulative_funding_pct=0.1,
    )
    defaults.update(overrides)
    return PositionSnapshot(**defaults)


class TestPositionSnapshot:
    def test_liq_distance_pct(self):
        p = _make_healthy_position(current_price=100.0, liquidation_price=80.0)
        assert p.liq_distance_pct == pytest.approx(20.0)

    def test_liq_distance_no_liq(self):
        p = _make_healthy_position(liquidation_price=0.0)
        assert p.liq_distance_pct == 100.0  # unknown liq — assume safe

    def test_upnl_long_positive(self):
        p = _make_healthy_position(entry_price=70.0, current_price=77.0)
        assert p.upnl_pct == pytest.approx(10.0)

    def test_upnl_long_negative(self):
        p = _make_healthy_position(entry_price=80.0, current_price=72.0)
        assert p.upnl_pct == pytest.approx(-10.0)

    def test_position_pct_of_equity(self):
        p = _make_healthy_position(position_notional=500.0, account_equity=1000.0)
        assert p.position_as_pct_of_equity == pytest.approx(50.0)


class TestEvaluateDipAddGate:
    # ── HARD BLOCKS ──────────────────────────────────────────────────────

    def test_blocked_liq_proximity(self):
        """Liq too close → hard block."""
        p = _make_healthy_position(
            current_price=100.0,
            liquidation_price=93.0,  # only 7% away, below 8% min
        )
        result = evaluate_dip_add_gate(p)
        assert result.decision == DipAddDecision.BLOCKED_LIQ
        assert result.decision.is_hard_block
        assert result.recommended_size_pct == 0.0

    def test_blocked_position_saturation(self):
        """Position already 65% of equity → blocked."""
        p = _make_healthy_position(
            position_notional=1300.0,  # 65% of 2000 equity
            account_equity=2000.0,
        )
        result = evaluate_dip_add_gate(p)
        assert result.decision == DipAddDecision.BLOCKED_SATURATED
        assert result.decision.is_hard_block

    def test_blocked_averaging_into_loss(self):
        """Position down 10% → never average into a falling knife."""
        p = _make_healthy_position(
            entry_price=80.0,
            current_price=72.0,  # -10% from entry
        )
        result = evaluate_dip_add_gate(p)
        assert result.decision == DipAddDecision.BLOCKED_SATURATED
        assert "averaging down" in result.reason.lower()

    def test_blocked_daily_drawdown(self):
        """Account down 7% today → protect remaining capital."""
        p = _make_healthy_position(daily_drawdown_pct=7.0)
        result = evaluate_dip_add_gate(p)
        assert result.decision == DipAddDecision.BLOCKED_DRAWDOWN

    def test_blocked_scale_limit(self):
        """Already added 3 times this session → requires manual review."""
        p = _make_healthy_position(num_adds_this_session=3)
        result = evaluate_dip_add_gate(p)
        assert result.decision == DipAddDecision.BLOCKED_SCALE_LIMIT

    def test_blocked_cooldown(self):
        """Added 30s ago → cooldown not elapsed."""
        p = _make_healthy_position(
            last_add_timestamp=time.time() - 30,  # very recent
        )
        result = evaluate_dip_add_gate(p)
        assert result.decision == DipAddDecision.COOLDOWN

    # ── SOFT GATES (permitted but with caution) ───────────────────────────

    def test_soft_warn_funding(self):
        """High funding cost → permitted but flagged."""
        p = _make_healthy_position(cumulative_funding_pct=0.8)  # above 0.5% warn
        result = evaluate_dip_add_gate(p)
        assert result.decision == DipAddDecision.SOFT_WARN_FUNDING
        assert result.permitted

    def test_soft_position_size_reduces_size(self):
        """Position 50% of equity → permitted but half size."""
        p = _make_healthy_position(
            position_notional=1000.0,  # 50% of 2000
            account_equity=2000.0,
        )
        result = evaluate_dip_add_gate(p)
        assert result.permitted
        assert result.recommended_size_pct == pytest.approx(0.5)

    def test_soft_liq_warning_zone_reduces_size(self):
        """Liq in warning zone (10%) → still permitted but half size."""
        p = _make_healthy_position(
            current_price=100.0,
            liquidation_price=90.0,  # 10% away — in warn zone (<15%) but above hard block (>8%)
        )
        result = evaluate_dip_add_gate(p)
        assert result.permitted
        assert result.recommended_size_pct < 1.0

    # ── FULL CLEAR ────────────────────────────────────────────────────────

    def test_all_clear_healthy_position(self):
        """Healthy position → PERMITTED at full size."""
        result = evaluate_dip_add_gate(_make_healthy_position())
        assert result.decision == DipAddDecision.PERMITTED
        assert result.recommended_size_pct == 1.0

    def test_first_add_no_cooldown_check(self):
        """First add ever (no previous timestamp) → no cooldown block."""
        p = _make_healthy_position(last_add_timestamp=0.0)
        result = evaluate_dip_add_gate(p)
        assert result.permitted

    # ── PRIORITY ORDER ────────────────────────────────────────────────────

    def test_liq_takes_priority_over_saturation(self):
        """Liq block fires before saturation check."""
        p = _make_healthy_position(
            current_price=100.0,
            liquidation_price=93.0,   # 7% → hard liq block
            position_notional=1300.0, # also saturated
        )
        result = evaluate_dip_add_gate(p)
        assert result.decision == DipAddDecision.BLOCKED_LIQ  # liq first

    def test_saturation_fires_before_drawdown(self):
        """Saturation (position too large) fires before daily drawdown."""
        p = _make_healthy_position(
            position_notional=1300.0,  # 65% → saturated
            daily_drawdown_pct=7.0,    # also daily drawdown issue
        )
        result = evaluate_dip_add_gate(p)
        assert result.decision == DipAddDecision.BLOCKED_SATURATED

    # ── CUSTOM CONFIG ─────────────────────────────────────────────────────

    def test_custom_min_liq_distance(self):
        """Custom config with 20% min liq distance."""
        cfg = DipAddGateConfig(min_liq_distance_pct=20.0)
        p = _make_healthy_position(
            current_price=100.0,
            liquidation_price=85.0,  # 15% — fine with default, blocked with custom
        )
        result = evaluate_dip_add_gate(p, config=cfg)
        assert result.decision == DipAddDecision.BLOCKED_LIQ

    def test_custom_relaxed_scale_limit(self):
        """Custom config allows more adds."""
        cfg = DipAddGateConfig(max_adds_per_session=5)
        p = _make_healthy_position(num_adds_this_session=4)
        result = evaluate_dip_add_gate(p, config=cfg)
        assert result.permitted

    # ── RESULT PROPERTIES ─────────────────────────────────────────────────

    def test_short_summary_format(self):
        result = evaluate_dip_add_gate(_make_healthy_position())
        summary = result.short_summary()
        assert "[PERMITTED]" in summary

    def test_details_present(self):
        result = evaluate_dip_add_gate(_make_healthy_position())
        assert "liq_distance_pct" in result.details
        assert "position_pct_of_equity" in result.details
        assert "upnl_pct" in result.details

    def test_is_blocked_property(self):
        assert DipAddDecision.BLOCKED_LIQ.is_blocked
        assert DipAddDecision.BLOCKED_SATURATED.is_blocked
        assert DipAddDecision.COOLDOWN.is_blocked
        assert not DipAddDecision.PERMITTED.is_blocked
        assert not DipAddDecision.SOFT_WARN_FUNDING.is_blocked
