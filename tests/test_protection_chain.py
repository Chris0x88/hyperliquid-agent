"""Tests for the composable ProtectionChain in parent/risk_manager.py.

Covers each protection independently, chain composition, position-awareness,
lock expiration, edge cases, and custom thresholds.
"""
from __future__ import annotations

import time

import pytest

from parent.risk_manager import (
    DailyLossProtection,
    MaxDrawdownProtection,
    ProtectionChain,
    ProtectionReturn,
    RiskGate,
    RuinProtection,
    StoplossGuardProtection,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _base_kwargs(**overrides) -> dict:
    """Sensible defaults for protection check() calls."""
    defaults = dict(
        equity=1000.0,
        hwm=1000.0,
        drawdown_pct=0.0,
        has_positions=True,
        consecutive_losses=0,
        daily_pnl=0.0,
    )
    defaults.update(overrides)
    return defaults


# ═══════════════════════════════════════════════════════════════════════
# MaxDrawdownProtection
# ═══════════════════════════════════════════════════════════════════════

class TestMaxDrawdownProtection:
    def setup_method(self):
        self.prot = MaxDrawdownProtection(warn_pct=15.0, halt_pct=25.0)

    def test_no_trigger_below_warn(self):
        result = self.prot.check(**_base_kwargs(drawdown_pct=14.9))
        assert result.lock is False
        assert result.gate == RiskGate.OPEN

    def test_warn_at_exactly_15_pct(self):
        result = self.prot.check(**_base_kwargs(drawdown_pct=15.0))
        assert result.lock is True
        assert result.gate == RiskGate.COOLDOWN
        assert "15" in result.reason

    def test_warn_between_15_and_25(self):
        result = self.prot.check(**_base_kwargs(drawdown_pct=20.0))
        assert result.lock is True
        assert result.gate == RiskGate.COOLDOWN

    def test_halt_at_exactly_25_pct(self):
        result = self.prot.check(**_base_kwargs(drawdown_pct=25.0))
        assert result.lock is True
        assert result.gate == RiskGate.CLOSED

    def test_halt_above_25_pct(self):
        result = self.prot.check(**_base_kwargs(drawdown_pct=35.0))
        assert result.lock is True
        assert result.gate == RiskGate.CLOSED

    def test_no_trigger_when_flat(self):
        """MaxDrawdown must NOT fire when there are no open positions."""
        result = self.prot.check(**_base_kwargs(drawdown_pct=30.0, has_positions=False))
        assert result.lock is False
        assert result.gate == RiskGate.OPEN

    def test_no_trigger_at_zero_drawdown(self):
        result = self.prot.check(**_base_kwargs(drawdown_pct=0.0))
        assert result.lock is False


# ═══════════════════════════════════════════════════════════════════════
# StoplossGuardProtection
# ═══════════════════════════════════════════════════════════════════════

class TestStoplossGuardProtection:
    def setup_method(self):
        self.prot = StoplossGuardProtection(max_consecutive=3)

    def test_no_trigger_below_threshold(self):
        result = self.prot.check(**_base_kwargs(consecutive_losses=2))
        assert result.lock is False

    def test_triggers_at_threshold(self):
        result = self.prot.check(**_base_kwargs(consecutive_losses=3))
        assert result.lock is True
        assert result.gate == RiskGate.COOLDOWN
        assert "3" in result.reason

    def test_triggers_above_threshold(self):
        result = self.prot.check(**_base_kwargs(consecutive_losses=10))
        assert result.lock is True
        assert result.gate == RiskGate.COOLDOWN

    def test_lock_expiry_set_to_30_min(self):
        before = time.time()
        result = self.prot.check(**_base_kwargs(consecutive_losses=3))
        after = time.time()
        # lock_until should be ~30 minutes from now
        assert result.lock_until >= before + 1800
        assert result.lock_until <= after + 1800 + 1  # 1s tolerance

    def test_no_lock_when_losses_zero(self):
        result = self.prot.check(**_base_kwargs(consecutive_losses=0))
        assert result.lock is False
        assert result.lock_until == 0.0


# ═══════════════════════════════════════════════════════════════════════
# DailyLossProtection
# ═══════════════════════════════════════════════════════════════════════

class TestDailyLossProtection:
    def setup_method(self):
        self.prot = DailyLossProtection(max_daily_loss_pct=5.0)

    def test_no_trigger_on_profit(self):
        result = self.prot.check(**_base_kwargs(hwm=1000.0, daily_pnl=50.0))
        assert result.lock is False

    def test_no_trigger_below_limit(self):
        result = self.prot.check(**_base_kwargs(hwm=1000.0, daily_pnl=-49.0))
        assert result.lock is False

    def test_triggers_at_exactly_5_pct(self):
        result = self.prot.check(**_base_kwargs(hwm=1000.0, daily_pnl=-50.0))
        assert result.lock is True
        assert result.gate == RiskGate.CLOSED

    def test_triggers_above_5_pct(self):
        result = self.prot.check(**_base_kwargs(hwm=1000.0, daily_pnl=-100.0))
        assert result.lock is True
        assert result.gate == RiskGate.CLOSED
        assert "10.0" in result.reason  # 10% loss reported

    def test_zero_hwm_edge_case(self):
        """Zero HWM must not divide by zero — protection should pass silently."""
        result = self.prot.check(**_base_kwargs(hwm=0.0, daily_pnl=-100.0))
        assert result.lock is False
        assert result.gate == RiskGate.OPEN

    def test_positive_hwm_zero_pnl(self):
        result = self.prot.check(**_base_kwargs(hwm=500.0, daily_pnl=0.0))
        assert result.lock is False


# ═══════════════════════════════════════════════════════════════════════
# RuinProtection
# ═══════════════════════════════════════════════════════════════════════

class TestRuinProtection:
    def setup_method(self):
        self.prot = RuinProtection(ruin_pct=40.0)

    def test_no_trigger_below_ruin(self):
        result = self.prot.check(**_base_kwargs(drawdown_pct=39.9, has_positions=True))
        assert result.lock is False

    def test_triggers_at_exactly_40_pct(self):
        result = self.prot.check(**_base_kwargs(drawdown_pct=40.0, has_positions=True))
        assert result.lock is True
        assert result.gate == RiskGate.CLOSED
        assert "RUIN" in result.reason

    def test_triggers_above_40_pct(self):
        result = self.prot.check(**_base_kwargs(drawdown_pct=75.0, has_positions=True))
        assert result.lock is True
        assert result.gate == RiskGate.CLOSED

    def test_no_trigger_when_flat(self):
        """Ruin protection only fires when positions are open."""
        result = self.prot.check(**_base_kwargs(drawdown_pct=50.0, has_positions=False))
        assert result.lock is False

    def test_no_trigger_at_zero_drawdown(self):
        result = self.prot.check(**_base_kwargs(drawdown_pct=0.0, has_positions=True))
        assert result.lock is False


# ═══════════════════════════════════════════════════════════════════════
# ProtectionChain composition
# ═══════════════════════════════════════════════════════════════════════

class TestProtectionChainComposition:
    def test_empty_chain_returns_open(self):
        chain = ProtectionChain(protections=[])
        gate, triggered = chain.check_all(**_base_kwargs())
        assert gate == RiskGate.OPEN
        assert triggered == []

    def test_no_triggers_returns_open(self):
        chain = ProtectionChain()
        gate, triggered = chain.check_all(**_base_kwargs(
            drawdown_pct=0.0, consecutive_losses=0, daily_pnl=0.0
        ))
        assert gate == RiskGate.OPEN
        assert triggered == []

    def test_single_cooldown_returns_cooldown(self):
        chain = ProtectionChain(protections=[StoplossGuardProtection(max_consecutive=3)])
        gate, triggered = chain.check_all(**_base_kwargs(consecutive_losses=3))
        assert gate == RiskGate.COOLDOWN
        assert len(triggered) == 1

    def test_single_closed_returns_closed(self):
        chain = ProtectionChain(protections=[RuinProtection(ruin_pct=40.0)])
        gate, triggered = chain.check_all(**_base_kwargs(drawdown_pct=50.0, has_positions=True))
        assert gate == RiskGate.CLOSED
        assert len(triggered) == 1

    def test_worst_gate_wins_closed_beats_cooldown(self):
        """COOLDOWN + CLOSED → chain returns CLOSED."""
        chain = ProtectionChain(protections=[
            StoplossGuardProtection(max_consecutive=3),   # → COOLDOWN
            RuinProtection(ruin_pct=40.0),                 # → CLOSED
        ])
        gate, triggered = chain.check_all(**_base_kwargs(
            drawdown_pct=50.0, has_positions=True, consecutive_losses=5
        ))
        assert gate == RiskGate.CLOSED
        assert len(triggered) == 2

    def test_multiple_cooldowns_stay_cooldown(self):
        chain = ProtectionChain(protections=[
            MaxDrawdownProtection(warn_pct=15.0, halt_pct=25.0),
            StoplossGuardProtection(max_consecutive=3),
        ])
        gate, triggered = chain.check_all(**_base_kwargs(
            drawdown_pct=20.0, has_positions=True, consecutive_losses=5
        ))
        assert gate == RiskGate.COOLDOWN
        assert len(triggered) == 2

    def test_all_four_protections_triggered(self):
        """All 4 fire simultaneously → CLOSED with 4 reasons."""
        chain = ProtectionChain()  # default: all 4 protections
        gate, triggered = chain.check_all(**_base_kwargs(
            drawdown_pct=45.0,     # MaxDrawdown CLOSED + RuinProtection CLOSED
            has_positions=True,
            consecutive_losses=5,  # StoplossGuard COOLDOWN
            hwm=1000.0,
            daily_pnl=-100.0,      # DailyLoss CLOSED (10%)
        ))
        assert gate == RiskGate.CLOSED
        assert len(triggered) == 4

    def test_reasons_collected_from_all_triggers(self):
        chain = ProtectionChain(protections=[
            StoplossGuardProtection(max_consecutive=2),
            DailyLossProtection(max_daily_loss_pct=5.0),
        ])
        gate, triggered = chain.check_all(**_base_kwargs(
            consecutive_losses=3,
            hwm=1000.0,
            daily_pnl=-60.0,
        ))
        reasons = [r.reason for r in triggered]
        assert any("losses" in r for r in reasons)
        assert any("Daily loss" in r for r in reasons)

    def test_faulty_protection_does_not_crash_chain(self):
        """A protection that raises must be silently skipped."""
        class BrokenProtection(MaxDrawdownProtection):
            name = "broken"
            def check(self, **kwargs):
                raise RuntimeError("simulated failure")

        chain = ProtectionChain(protections=[
            BrokenProtection(),
            StoplossGuardProtection(max_consecutive=3),
        ])
        gate, triggered = chain.check_all(**_base_kwargs(consecutive_losses=5))
        # Chain should still process the healthy protection
        assert gate == RiskGate.COOLDOWN
        assert len(triggered) == 1

    def test_open_result_not_collected(self):
        """Non-triggering protections must not appear in triggered list."""
        chain = ProtectionChain(protections=[
            MaxDrawdownProtection(warn_pct=15.0, halt_pct=25.0),
        ])
        gate, triggered = chain.check_all(**_base_kwargs(drawdown_pct=5.0, has_positions=True))
        assert gate == RiskGate.OPEN
        assert triggered == []


# ═══════════════════════════════════════════════════════════════════════
# Position-awareness
# ═══════════════════════════════════════════════════════════════════════

class TestPositionAwareness:
    def test_max_drawdown_silent_when_flat(self):
        chain = ProtectionChain(protections=[MaxDrawdownProtection(warn_pct=10.0, halt_pct=20.0)])
        gate, triggered = chain.check_all(**_base_kwargs(drawdown_pct=99.0, has_positions=False))
        assert gate == RiskGate.OPEN
        assert triggered == []

    def test_ruin_silent_when_flat(self):
        chain = ProtectionChain(protections=[RuinProtection(ruin_pct=40.0)])
        gate, triggered = chain.check_all(**_base_kwargs(drawdown_pct=99.0, has_positions=False))
        assert gate == RiskGate.OPEN
        assert triggered == []

    def test_stoploss_guard_fires_regardless_of_positions(self):
        """StoplossGuard tracks consecutive losses independent of position state."""
        chain = ProtectionChain(protections=[StoplossGuardProtection(max_consecutive=3)])
        gate, triggered = chain.check_all(**_base_kwargs(consecutive_losses=5, has_positions=False))
        assert gate == RiskGate.COOLDOWN

    def test_daily_loss_fires_regardless_of_positions(self):
        chain = ProtectionChain(protections=[DailyLossProtection(max_daily_loss_pct=5.0)])
        gate, triggered = chain.check_all(**_base_kwargs(
            hwm=1000.0, daily_pnl=-100.0, has_positions=False
        ))
        assert gate == RiskGate.CLOSED


# ═══════════════════════════════════════════════════════════════════════
# Custom thresholds
# ═══════════════════════════════════════════════════════════════════════

class TestCustomThresholds:
    def test_custom_max_drawdown_thresholds(self):
        chain = ProtectionChain(protections=[MaxDrawdownProtection(warn_pct=5.0, halt_pct=10.0)])
        # Below custom warn — OPEN
        gate, _ = chain.check_all(**_base_kwargs(drawdown_pct=4.9, has_positions=True))
        assert gate == RiskGate.OPEN
        # At custom warn — COOLDOWN
        gate, _ = chain.check_all(**_base_kwargs(drawdown_pct=5.0, has_positions=True))
        assert gate == RiskGate.COOLDOWN
        # At custom halt — CLOSED
        gate, _ = chain.check_all(**_base_kwargs(drawdown_pct=10.0, has_positions=True))
        assert gate == RiskGate.CLOSED

    def test_custom_stoploss_guard_threshold(self):
        chain = ProtectionChain(protections=[StoplossGuardProtection(max_consecutive=1)])
        gate, _ = chain.check_all(**_base_kwargs(consecutive_losses=1))
        assert gate == RiskGate.COOLDOWN

    def test_custom_daily_loss_threshold(self):
        chain = ProtectionChain(protections=[DailyLossProtection(max_daily_loss_pct=2.0)])
        gate, _ = chain.check_all(**_base_kwargs(hwm=1000.0, daily_pnl=-20.0))
        assert gate == RiskGate.CLOSED

    def test_custom_ruin_pct(self):
        chain = ProtectionChain(protections=[RuinProtection(ruin_pct=20.0)])
        gate, _ = chain.check_all(**_base_kwargs(drawdown_pct=20.0, has_positions=True))
        assert gate == RiskGate.CLOSED
        gate, _ = chain.check_all(**_base_kwargs(drawdown_pct=19.9, has_positions=True))
        assert gate == RiskGate.OPEN

    def test_mixed_custom_chain(self):
        """Custom multi-protection chain with tight thresholds all firing."""
        chain = ProtectionChain(protections=[
            MaxDrawdownProtection(warn_pct=5.0, halt_pct=10.0),
            StoplossGuardProtection(max_consecutive=1),
            DailyLossProtection(max_daily_loss_pct=1.0),
            RuinProtection(ruin_pct=15.0),
        ])
        gate, triggered = chain.check_all(**_base_kwargs(
            drawdown_pct=16.0,
            has_positions=True,
            consecutive_losses=2,
            hwm=1000.0,
            daily_pnl=-20.0,
        ))
        assert gate == RiskGate.CLOSED
        assert len(triggered) == 4
