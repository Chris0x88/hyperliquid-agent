"""Tests for the conviction engine — pure sizing, modulation, and safety functions."""
import pytest
from datetime import datetime, timezone

from trading.conviction_engine import (
    conviction_to_target_pct,
    compute_target_notional,
    modulate_dip_add_pct,
    modulate_spike_take_pct,
    is_near_roll_window,
    check_oil_direction_guard,
    can_execute_add,
)
from trading.heartbeat_config import ConvictionBands


@pytest.fixture
def bands():
    return ConvictionBands()


# ── conviction_to_target_pct ─────────────────────────────────────────────────

class TestConvictionToTargetPct:
    def test_below_defensive_returns_zero(self, bands):
        assert conviction_to_target_pct(0.0, bands) == 0.0
        assert conviction_to_target_pct(0.2, bands) == 0.0
        assert conviction_to_target_pct(0.29, bands) == 0.0

    def test_small_band_boundaries(self, bands):
        # At 0.3 (bottom of small): should be 5%
        assert abs(conviction_to_target_pct(0.3, bands) - 0.05) < 0.001
        # At 0.5 (top of small): should be 10%
        assert abs(conviction_to_target_pct(0.5, bands) - 0.10) < 0.001

    def test_small_band_midpoint(self, bands):
        # At 0.4 (midpoint of small): should be ~7.5%
        result = conviction_to_target_pct(0.4, bands)
        assert 0.07 < result < 0.08

    def test_medium_band(self, bands):
        # At 0.6 (midpoint of medium): ~15%
        result = conviction_to_target_pct(0.6, bands)
        assert 0.14 < result < 0.16

    def test_large_band(self, bands):
        # At 0.8 (midpoint of large): ~27.5%
        result = conviction_to_target_pct(0.8, bands)
        assert 0.25 < result < 0.30

    def test_max_band(self, bands):
        # At 0.95 (midpoint of max): ~42.5%
        result = conviction_to_target_pct(0.95, bands)
        assert 0.40 < result < 0.46

    def test_above_one_returns_top(self, bands):
        result = conviction_to_target_pct(1.1, bands)
        assert abs(result - 0.50) < 0.001

    def test_monotonically_increasing(self, bands):
        prev = 0.0
        for c in [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            curr = conviction_to_target_pct(c, bands)
            assert curr >= prev, f"Not monotonic at {c}: {curr} < {prev}"
            prev = curr


class TestComputeTargetNotional:
    def test_basic(self, bands):
        result = compute_target_notional(0.8, 600.0, bands)
        # At 0.8 conviction, target ~27.5% of $600 = ~$165
        assert 150 < result < 180

    def test_zero_conviction(self, bands):
        assert compute_target_notional(0.0, 600.0, bands) == 0.0


# ── modulate_dip_add_pct ─────────────────────────────────────────────────────

class TestModulateDipAddPct:
    def test_below_defensive_returns_zero(self):
        assert modulate_dip_add_pct(10.0, 0.2) == 0.0

    def test_at_half_conviction(self):
        # At 0.5, returns 50% of base
        assert abs(modulate_dip_add_pct(10.0, 0.5) - 5.0) < 0.001

    def test_at_high_conviction(self):
        # At 0.95, returns 95% of base
        assert abs(modulate_dip_add_pct(10.0, 0.95) - 9.5) < 0.001


# ── modulate_spike_take_pct ──────────────────────────────────────────────────

class TestModulateSpikeTakePct:
    def test_low_conviction_doubles(self):
        # At 0.3, take 2x base
        assert abs(modulate_spike_take_pct(15.0, 0.3) - 30.0) < 0.001

    def test_high_conviction_halves(self):
        # At 0.9+, take 0.5x base
        assert abs(modulate_spike_take_pct(15.0, 0.9) - 7.5) < 0.001
        assert abs(modulate_spike_take_pct(15.0, 1.0) - 7.5) < 0.001

    def test_midpoint(self):
        # At 0.6 (midpoint of 0.3-0.9), multiplier = 2.0 - 0.5*1.5 = 1.25
        result = modulate_spike_take_pct(15.0, 0.6)
        assert 18.0 < result < 19.5

    def test_inverse_to_conviction(self):
        """Lower conviction = bigger take (more aggressive profit-taking)."""
        low = modulate_spike_take_pct(15.0, 0.4)
        high = modulate_spike_take_pct(15.0, 0.8)
        assert low > high


# ── is_near_roll_window ──────────────────────────────────────────────────────

class TestIsNearRollWindow:
    def test_first_of_month_is_outside(self):
        # 1st = 1 business day (if weekday)
        dt = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)  # Wednesday
        assert not is_near_roll_window(dt)

    def test_mid_month_in_window(self):
        # April 7, 2026 is a Tuesday. ~5th business day
        dt = datetime(2026, 4, 7, 12, 0, tzinfo=timezone.utc)
        assert is_near_roll_window(dt)

    def test_late_month_outside(self):
        # April 20, 2026 = well past 12th business day
        dt = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
        assert not is_near_roll_window(dt)


# ── check_oil_direction_guard ────────────────────────────────────────────────

class TestOilDirectionGuard:
    def test_long_allowed(self):
        assert check_oil_direction_guard("long") is True

    def test_flat_allowed(self):
        assert check_oil_direction_guard("flat") is True

    def test_neutral_allowed(self):
        assert check_oil_direction_guard("neutral") is True

    def test_short_allowed(self):
        # Oil is neutral as of 2026-04-11 — both directions allowed
        assert check_oil_direction_guard("short") is True

    def test_empty_allowed(self):
        assert check_oil_direction_guard("") is True


# ── can_execute_add ──────────────────────────────────────────────────────────

class TestCanExecuteAdd:
    BASE = dict(
        thesis_exists=True,
        effective_conv=0.8,
        escalation="L0",
        is_oil=False,
        thesis_direction="long",
        is_vault_no_tactical=False,
        total_notional=100.0,
        add_notional=20.0,
        equity=600.0,
        max_notional_pct=0.50,
    )

    def test_all_clear(self):
        ok, reason = can_execute_add(**self.BASE)
        assert ok is True
        assert reason == ""

    def test_no_thesis(self):
        ok, reason = can_execute_add(**{**self.BASE, "thesis_exists": False})
        assert ok is False
        assert "no thesis" in reason

    def test_low_conviction(self):
        ok, reason = can_execute_add(**{**self.BASE, "effective_conv": 0.3})
        assert ok is False
        assert "conviction" in reason

    def test_escalation_l2(self):
        ok, reason = can_execute_add(**{**self.BASE, "escalation": "L2"})
        assert ok is False
        assert "escalation" in reason

    def test_escalation_l3(self):
        ok, reason = can_execute_add(**{**self.BASE, "escalation": "L3"})
        assert ok is False

    def test_oil_short_allowed(self):
        # Oil is neutral as of 2026-04-11 — both directions allowed
        ok, reason = can_execute_add(**{**self.BASE, "is_oil": True, "thesis_direction": "short"})
        assert ok is True

    def test_oil_long_allowed(self):
        ok, reason = can_execute_add(**{**self.BASE, "is_oil": True, "thesis_direction": "long"})
        assert ok is True

    def test_vault_no_tactical(self):
        ok, reason = can_execute_add(**{**self.BASE, "is_vault_no_tactical": True})
        assert ok is False
        assert "vault" in reason

    def test_exceeds_notional_cap(self):
        ok, reason = can_execute_add(**{**self.BASE, "total_notional": 290.0, "add_notional": 20.0})
        assert ok is False
        assert "notional" in reason

    def test_exactly_at_cap_blocked(self):
        # 300 + 1 > 600 * 0.50 = 300
        ok, reason = can_execute_add(**{**self.BASE, "total_notional": 300.0, "add_notional": 1.0})
        assert ok is False
