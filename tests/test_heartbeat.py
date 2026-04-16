"""Tests for common.heartbeat — core heartbeat decision logic."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from trading.heartbeat_config import (
    EscalationConfig,
    HeartbeatConfig,
    ProfitRules,
    SpikeConfig,
)
from trading.heartbeat import (
    check_drawdown,
    check_funding_rate,
    check_liq_distance,
    compute_stop_price,
    detect_spike_or_dip,
    fetch_with_retry,
    is_oil_market_open,
    resolve_escalation,
    should_add_on_dip,
    should_take_profit,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg(**overrides) -> HeartbeatConfig:
    """Build a HeartbeatConfig with optional escalation overrides."""
    esc_kw = {k: v for k, v in overrides.items() if hasattr(EscalationConfig, k)}
    return HeartbeatConfig(escalation=EscalationConfig(**esc_kw))


ET = ZoneInfo("America/New_York")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. compute_stop_price
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeStopPrice:

    def test_compute_stop_price_long(self):
        """Long stop = entry - multiplier * atr."""
        stop = compute_stop_price(entry=100.0, side="long", atr=2.0, multiplier=3.0)
        assert stop == pytest.approx(94.0)

    def test_compute_stop_price_short(self):
        """Short stop = entry + multiplier * atr."""
        stop = compute_stop_price(entry=100.0, side="short", atr=2.0, multiplier=3.0)
        assert stop == pytest.approx(106.0)

    def test_compute_stop_price_respects_min_distance(self):
        """Stop should not be within min_distance_pct of current_price."""
        # Long: ATR stop would be 94, but current_price is 95 and min_distance=3%
        # 3% below 95 = 92.15, which is further away — stop should be pushed to 92.15
        stop = compute_stop_price(
            entry=100.0, side="long", atr=2.0, multiplier=3.0,
            current_price=95.0, min_distance_pct=3.0,
        )
        # ATR stop = 94.0, min_distance stop = 95 * (1 - 0.03) = 92.15
        # For longs, "most conservative" = lowest stop that satisfies all constraints
        # min_distance means stop must be <= 92.15
        assert stop == pytest.approx(92.15)

    def test_compute_stop_price_respects_liq_buffer(self):
        """Liq buffer is a floor for longs; ATR stop already above floor => no change."""
        # Long: ATR stop = 94, liq_price=90, buffer=3% => floor = 90*1.03 = 92.7
        # ATR stop 94 > floor 92.7 => stop stays at 94
        stop = compute_stop_price(
            entry=100.0, side="long", atr=2.0, multiplier=3.0,
            liq_price=90.0, liq_buffer_pct=3.0,
        )
        assert stop == pytest.approx(94.0)

    def test_compute_stop_price_liq_buffer_overrides_atr(self):
        """When ATR stop is below liq buffer, liq buffer wins."""
        # Long: ATR stop = 100 - 3*5 = 85, liq_price=88, buffer=3% => 88*1.03=90.64
        # Liq buffer stop (90.64) is higher — safest for longs
        stop = compute_stop_price(
            entry=100.0, side="long", atr=5.0, multiplier=3.0,
            liq_price=88.0, liq_buffer_pct=3.0,
        )
        assert stop == pytest.approx(88.0 * 1.03)

    def test_compute_stop_price_short_liq_buffer(self):
        """Short: stop must not be above liq * (1 - buffer%)."""
        # Short: ATR stop = 100 + 3*5 = 115, liq=112, buffer=3% => 112*0.97=108.64
        # Liq buffer stop (108.64) is lower — safest for shorts
        stop = compute_stop_price(
            entry=100.0, side="short", atr=5.0, multiplier=3.0,
            liq_price=112.0, liq_buffer_pct=3.0,
        )
        assert stop == pytest.approx(112.0 * 0.97)

    def test_compute_stop_price_short_min_distance(self):
        """Short: stop must be at least min_distance_pct above current price."""
        # Short ATR stop = 100 + 3*2 = 106, current=105, min_dist=3%
        # 3% above 105 = 108.15 — must push stop up
        stop = compute_stop_price(
            entry=100.0, side="short", atr=2.0, multiplier=3.0,
            current_price=105.0, min_distance_pct=3.0,
        )
        assert stop == pytest.approx(105.0 * 1.03)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. check_liq_distance
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckLiqDistance:

    def test_check_liq_distance_l0(self):
        cfg = _cfg(liq_L1_alert_pct=10, liq_L2_deleverage_pct=8, liq_L3_emergency_pct=5)
        assert check_liq_distance(15.0, cfg) == "L0"

    def test_check_liq_distance_l1(self):
        cfg = _cfg(liq_L1_alert_pct=10, liq_L2_deleverage_pct=8, liq_L3_emergency_pct=5)
        assert check_liq_distance(9.0, cfg) == "L1"

    def test_check_liq_distance_l2(self):
        cfg = _cfg(liq_L1_alert_pct=10, liq_L2_deleverage_pct=8, liq_L3_emergency_pct=5)
        assert check_liq_distance(6.0, cfg) == "L2"

    def test_check_liq_distance_l3(self):
        cfg = _cfg(liq_L1_alert_pct=10, liq_L2_deleverage_pct=8, liq_L3_emergency_pct=5)
        assert check_liq_distance(4.0, cfg) == "L3"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. check_drawdown
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckDrawdown:

    def test_check_drawdown_l0(self):
        cfg = _cfg(drawdown_L1_pct=5, drawdown_L2_pct=8, drawdown_L3_pct=12)
        # 2% drawdown => L0
        assert check_drawdown(current_equity=980, session_peak=1000, config=cfg) == "L0"

    def test_check_drawdown_l1(self):
        cfg = _cfg(drawdown_L1_pct=5, drawdown_L2_pct=8, drawdown_L3_pct=12)
        # 6% drawdown => L1
        assert check_drawdown(current_equity=940, session_peak=1000, config=cfg) == "L1"

    def test_check_drawdown_l2(self):
        cfg = _cfg(drawdown_L1_pct=5, drawdown_L2_pct=8, drawdown_L3_pct=12)
        # 10% drawdown => L2
        assert check_drawdown(current_equity=900, session_peak=1000, config=cfg) == "L2"

    def test_check_drawdown_l3(self):
        cfg = _cfg(drawdown_L1_pct=5, drawdown_L2_pct=8, drawdown_L3_pct=12)
        # 15% drawdown => L3
        assert check_drawdown(current_equity=850, session_peak=1000, config=cfg) == "L3"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. detect_spike_or_dip
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectSpikeOrDip:

    def test_detect_spike_long(self):
        """Long position, price goes up 5% => spike."""
        result = detect_spike_or_dip(
            current_price=105, last_price=100, side="long",
            spike_threshold_pct=3.0, dip_threshold_pct=2.0,
        )
        assert result["type"] == "spike"
        assert result["pct"] == pytest.approx(5.0)

    def test_detect_dip_long(self):
        """Long position, price goes down 3% => dip."""
        result = detect_spike_or_dip(
            current_price=97, last_price=100, side="long",
            spike_threshold_pct=3.0, dip_threshold_pct=2.0,
        )
        assert result["type"] == "dip"
        assert result["pct"] == pytest.approx(3.0)

    def test_detect_spike_short(self):
        """Short position, price goes down 4% => spike (favorable)."""
        result = detect_spike_or_dip(
            current_price=96, last_price=100, side="short",
            spike_threshold_pct=3.0, dip_threshold_pct=2.0,
        )
        assert result["type"] == "spike"
        assert result["pct"] == pytest.approx(4.0)

    def test_detect_no_movement(self):
        """Small movement => none."""
        result = detect_spike_or_dip(
            current_price=100.5, last_price=100, side="long",
            spike_threshold_pct=3.0, dip_threshold_pct=2.0,
        )
        assert result["type"] == "none"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. should_take_profit
# ═══════════════════════════════════════════════════════════════════════════════

class TestShouldTakeProfit:

    def _rules(self) -> ProfitRules:
        return ProfitRules(
            quick_profit_pct=5.0,
            quick_profit_window_min=30,
            quick_profit_take_pct=25,
            extended_profit_pct=10.0,
            extended_profit_window_min=120,
            extended_profit_take_pct=25,
        )

    def test_should_take_profit_quick(self):
        """Quick profit: high pnl within short window."""
        result = should_take_profit(
            upnl_pct=6.0, position_age_min=20, rules=self._rules(),
        )
        assert result["take"] is True
        assert result["take_pct"] == 25
        assert "quick" in result["reason"].lower()

    def test_should_take_profit_extended(self):
        """Extended profit: very high pnl within longer window."""
        result = should_take_profit(
            upnl_pct=12.0, position_age_min=90, rules=self._rules(),
        )
        assert result["take"] is True
        assert result["take_pct"] == 25
        assert "extended" in result["reason"].lower()

    def test_should_take_profit_too_slow(self):
        """Position is profitable but outside all time windows."""
        result = should_take_profit(
            upnl_pct=6.0, position_age_min=150, rules=self._rules(),
        )
        assert result["take"] is False

    def test_should_take_profit_too_small_position(self):
        """Would leave fewer than min_size contracts."""
        result = should_take_profit(
            upnl_pct=6.0, position_age_min=20, rules=self._rules(),
            current_size=3, min_size=2,
        )
        # 25% of 3 = 0.75 contracts taken, leaving 2.25 — that's fine
        # But if current_size=2, 25% of 2 = 0.5, leaving 1.5 < 2
        result2 = should_take_profit(
            upnl_pct=6.0, position_age_min=20, rules=self._rules(),
            current_size=2, min_size=2,
        )
        assert result2["take"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 6. should_add_on_dip
# ═══════════════════════════════════════════════════════════════════════════════

class TestShouldAddOnDip:

    def _spike_cfg(self) -> SpikeConfig:
        return SpikeConfig(
            dip_add_min_liq_pct=12,
            dip_add_max_drawdown_pct=3,
            dip_add_cooldown_min=120,
        )

    def test_should_add_on_dip_allowed(self):
        now = int(time.time() * 1000)
        last_add = now - (121 * 60 * 1000)  # 121 min ago
        assert should_add_on_dip(
            liq_distance_pct=15.0, daily_drawdown_pct=1.0,
            last_add_ms=last_add, now_ms=now, config=self._spike_cfg(),
        ) is True

    def test_should_add_on_dip_blocked_low_liq(self):
        now = int(time.time() * 1000)
        last_add = now - (121 * 60 * 1000)
        assert should_add_on_dip(
            liq_distance_pct=10.0, daily_drawdown_pct=1.0,
            last_add_ms=last_add, now_ms=now, config=self._spike_cfg(),
        ) is False

    def test_should_add_on_dip_blocked_drawdown(self):
        now = int(time.time() * 1000)
        last_add = now - (121 * 60 * 1000)
        assert should_add_on_dip(
            liq_distance_pct=15.0, daily_drawdown_pct=5.0,
            last_add_ms=last_add, now_ms=now, config=self._spike_cfg(),
        ) is False

    def test_should_add_on_dip_blocked_cooldown(self):
        now = int(time.time() * 1000)
        last_add = now - (60 * 60 * 1000)  # Only 60 min ago
        assert should_add_on_dip(
            liq_distance_pct=15.0, daily_drawdown_pct=1.0,
            last_add_ms=last_add, now_ms=now, config=self._spike_cfg(),
        ) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 7. check_funding_rate
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckFundingRate:

    def test_check_funding_rate_normal(self):
        result = check_funding_rate(
            current_rate=0.0005,
            recent_rates=[0.0005, 0.0003, 0.0004],
            position_notional=10000,
        )
        assert result["alert"] is False

    def test_check_funding_rate_high_consecutive(self):
        """Three consecutive rates > 0.001 triggers alert."""
        result = check_funding_rate(
            current_rate=0.0015,
            recent_rates=[0.0012, 0.0011, 0.0015],
            position_notional=10000,
        )
        assert result["alert"] is True
        assert "$" in result["message"]

    def test_check_funding_rate_cumulative(self):
        """Cumulative funding > 1% triggers alert."""
        result = check_funding_rate(
            current_rate=0.0005,
            recent_rates=[0.0005, 0.0003, 0.0004],
            position_notional=10000,
            cumulative_pct=1.5,
        )
        assert result["alert"] is True
        assert "cumulative" in result["message"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 8. is_oil_market_open
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsOilMarketOpen:

    def test_is_oil_market_open_weekday(self):
        """Tuesday 10am ET => open."""
        dt = datetime(2026, 3, 31, 14, 0, tzinfo=timezone.utc)  # Tue 10am ET
        assert is_oil_market_open(dt) is True

    def test_is_oil_market_closed_saturday(self):
        """Saturday => closed."""
        dt = datetime(2026, 3, 28, 14, 0, tzinfo=timezone.utc)  # Sat
        assert is_oil_market_open(dt) is False

    def test_is_oil_market_closed_friday_late(self):
        """Friday 6pm ET => closed (after 5pm cutoff)."""
        # Friday March 27, 2026, 22:00 UTC = 6pm ET
        dt = datetime(2026, 3, 27, 22, 0, tzinfo=timezone.utc)
        assert is_oil_market_open(dt) is False

    def test_is_oil_market_open_sunday_evening(self):
        """Sunday 7pm ET => open (after 6pm open)."""
        # Sunday March 29, 2026, 23:00 UTC = 7pm ET
        dt = datetime(2026, 3, 29, 23, 0, tzinfo=timezone.utc)
        assert is_oil_market_open(dt) is True

    def test_is_oil_market_closed_sunday_morning(self):
        """Sunday 10am ET => closed (before 6pm open)."""
        dt = datetime(2026, 3, 29, 14, 0, tzinfo=timezone.utc)  # Sun 10am ET
        assert is_oil_market_open(dt) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 9. resolve_escalation
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolveEscalation:

    def test_resolve_escalation_highest_wins(self):
        assert resolve_escalation(["L0", "L1", "L2", "L0"]) == "L2"

    def test_resolve_escalation_all_l0(self):
        assert resolve_escalation(["L0", "L0", "L0"]) == "L0"

    def test_resolve_escalation_l3(self):
        assert resolve_escalation(["L0", "L3", "L1"]) == "L3"

    def test_resolve_escalation_empty(self):
        assert resolve_escalation([]) == "L0"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. fetch_with_retry
# ═══════════════════════════════════════════════════════════════════════════════

class TestFetchWithRetry:

    def test_fetch_with_retry_success_first(self):
        result = fetch_with_retry(lambda: 42, retries=3, delay_ms=0)
        assert result == 42

    def test_fetch_with_retry_success_after_failures(self):
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("fail")
            return "ok"

        result = fetch_with_retry(flaky, retries=3, delay_ms=0)
        assert result == "ok"
        assert call_count["n"] == 3

    def test_fetch_with_retry_all_fail(self):
        def always_fail():
            raise ConnectionError("boom")

        result = fetch_with_retry(always_fail, retries=3, delay_ms=0)
        assert result is None


class TestAccountRiskAdjustedEscalation:
    """Escalation should be downgraded when position is small vs account."""

    def test_large_position_keeps_escalation(self):
        """$200 margin on $600 account (33%) — keep L3."""
        from trading.heartbeat import account_risk_adjusted_escalation
        assert account_risk_adjusted_escalation("L3", margin_used=200, account_equity=600) == "L3"

    def test_small_position_downgrades_l3(self):
        """$50 margin on $600 account (8%) — downgrade L3 to L1."""
        from trading.heartbeat import account_risk_adjusted_escalation
        assert account_risk_adjusted_escalation("L3", margin_used=50, account_equity=600) == "L1"

    def test_small_position_downgrades_l2(self):
        """$50 margin on $600 account (8%) — downgrade L2 to L1."""
        from trading.heartbeat import account_risk_adjusted_escalation
        assert account_risk_adjusted_escalation("L2", margin_used=50, account_equity=600) == "L1"

    def test_small_position_downgrades_l1(self):
        """$50 margin on $600 account (8%) — downgrade L1 to L0."""
        from trading.heartbeat import account_risk_adjusted_escalation
        assert account_risk_adjusted_escalation("L1", margin_used=50, account_equity=600) == "L0"

    def test_l0_stays_l0(self):
        """L0 can't go lower."""
        from trading.heartbeat import account_risk_adjusted_escalation
        assert account_risk_adjusted_escalation("L0", margin_used=50, account_equity=600) == "L0"

    def test_borderline_keeps_escalation(self):
        """$90 margin on $600 account (15%) — exactly at threshold, keep level."""
        from trading.heartbeat import account_risk_adjusted_escalation
        assert account_risk_adjusted_escalation("L3", margin_used=90, account_equity=600) == "L3"

    def test_zero_equity_keeps_escalation(self):
        """Zero equity — can't calculate risk, keep raw level."""
        from trading.heartbeat import account_risk_adjusted_escalation
        assert account_risk_adjusted_escalation("L3", margin_used=50, account_equity=0) == "L3"
