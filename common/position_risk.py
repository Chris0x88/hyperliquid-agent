"""Position risk assessment — gates dip-adds based on account reality.

The key insight: a dip-buy signal is ONLY valid if the position has room to
grow safely. If you're already max-long, over-leveraged, or your liquidation
distance is dangerously thin, adding MORE is how you get wiped out.

This module provides a single authoritative answer: "CAN I ADD?" with a
detailed explanation of *why* not (so the AI copilot can report it clearly).

Gates checked in priority order:
  1. LIQUIDATION PROXIMITY  — distance to liq < hard minimum → BLOCKED (life safety)
  2. POSITION SATURATION    — position already at/near max size → BLOCKED
  3. NOTIONAL SATURATION    — position notional >= max % of equity → BLOCKED
  4. DAILY DRAWDOWN LIMIT   — account already down too much today → BLOCKED
  5. SCALE-IN LIMIT         — already had too many adds this session → BLOCKED
  6. COOLDOWN               — added too recently → COOLDOWN
  7. FUNDING BURDEN         — cumulative funding cost eroding equity → WARN (soft gate)
  8. ALL CLEAR              → PERMITTED
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("position_risk")


class DipAddDecision(Enum):
    """The authoritative outcome of a dip-add gate check."""
    PERMITTED = "PERMITTED"          # All clear, proceed
    BLOCKED_LIQ = "BLOCKED_LIQ"     # Too close to liquidation — HARD BLOCK
    BLOCKED_SATURATED = "BLOCKED_SATURATED"  # Position already full
    BLOCKED_DRAWDOWN = "BLOCKED_DRAWDOWN"    # Account down too much today
    BLOCKED_SCALE_LIMIT = "BLOCKED_SCALE_LIMIT"  # Too many adds this session
    COOLDOWN = "COOLDOWN"            # Cooldown period not elapsed
    SOFT_WARN_FUNDING = "SOFT_WARN_FUNDING"  # Funding cost high — proceed with caution

    @property
    def is_blocked(self) -> bool:
        return self in (
            DipAddDecision.BLOCKED_LIQ,
            DipAddDecision.BLOCKED_SATURATED,
            DipAddDecision.BLOCKED_DRAWDOWN,
            DipAddDecision.BLOCKED_SCALE_LIMIT,
            DipAddDecision.COOLDOWN,
        )

    @property
    def is_hard_block(self) -> bool:
        """Life-safety blocks that cannot be overridden."""
        return self in (
            DipAddDecision.BLOCKED_LIQ,
            DipAddDecision.BLOCKED_SATURATED,
        )


@dataclass
class PositionSnapshot:
    """Current state of a single position + the account it lives in.

    All fields that the AI copilot would have after a heartbeat cycle.
    """
    # Position identity
    symbol: str
    side: str                   # "long" or "short"

    # Size
    position_qty: float         # In contracts/units
    position_notional: float    # In USD

    # Price levels
    entry_price: float
    current_price: float
    liquidation_price: float    # 0 = no liq (cross-margin or not applicable)

    # Account context
    account_equity: float       # Total account value in USD
    margin_used: float          # Margin allocated to this position

    # Activity history
    num_adds_this_session: int = 0    # How many times we've added to this pos
    last_add_timestamp: float = 0.0   # epoch seconds of last add
    daily_drawdown_pct: float = 0.0   # Account drawdown from today's peak

    # Funding
    cumulative_funding_pct: float = 0.0  # Total funding as % of position notional

    @property
    def liq_distance_pct(self) -> float:
        """Distance from current price to liquidation as a %."""
        if self.liquidation_price <= 0 or self.current_price <= 0:
            return 100.0  # No known liq — assume safe
        return abs(self.current_price - self.liquidation_price) / self.current_price * 100

    @property
    def position_as_pct_of_equity(self) -> float:
        """Position notional as a % of account equity."""
        if self.account_equity <= 0:
            return 0.0
        return self.position_notional / self.account_equity * 100

    @property
    def upnl_pct(self) -> float:
        """Unrealised PnL as a % of entry price."""
        if self.entry_price <= 0:
            return 0.0
        direction = 1 if self.side == "long" else -1
        return (self.current_price - self.entry_price) / self.entry_price * 100 * direction


@dataclass
class DipAddGateConfig:
    """Configuration for how aggressively to gate dip-adds."""
    # Hard liquidation block — never add if liq is closer than this
    min_liq_distance_pct: float = 8.0       # 8% buffer minimum (was 5%)

    # Soft liquidation warning — add cautiously between soft and hard
    warn_liq_distance_pct: float = 15.0     # Start warning below 15%

    # Position saturation — don't add if already this large
    max_position_pct_of_equity: float = 60.0  # Block above 60% of equity
    soft_position_pct_of_equity: float = 45.0 # Warn above 45%

    # Scale-in limit — max number of adds before requiring manual review
    max_adds_per_session: int = 3

    # Cooldown between adds
    min_cooldown_seconds: float = 300.0     # 5 minutes minimum

    # Daily drawdown limit
    max_daily_drawdown_pct: float = 5.0     # Block if account down 5%+ today

    # Funding burden (soft gate — still executes but logs warning)
    warn_funding_pct: float = 0.5           # Warn if funding cost > 0.5% of notional

    # If position is LOSING this much, don't average down into a knife
    max_unrealized_loss_pct: float = -8.0   # Block adding if down 8%+ on the position


@dataclass
class DipAddGateResult:
    """The full output of a dip-add gate evaluation."""
    decision: DipAddDecision
    reason: str
    details: dict = field(default_factory=dict)
    recommended_size_pct: float = 1.0  # Scale-down factor (1.0 = full size)

    @property
    def permitted(self) -> bool:
        return self.decision == DipAddDecision.PERMITTED or \
               self.decision == DipAddDecision.SOFT_WARN_FUNDING

    def short_summary(self) -> str:
        """One-line summary for the AI copilot (StepFun-friendly)."""
        return f"[{self.decision.value}] {self.reason}"

    def log_it(self, logger=None) -> None:
        lg = logger or log
        if self.decision.is_hard_block:
            lg.warning("DipAdd HARD BLOCK: %s | %s", self.decision.value, self.reason)
        elif self.decision.is_blocked:
            lg.info("DipAdd BLOCKED: %s | %s", self.decision.value, self.reason)
        else:
            lg.info("DipAdd: %s | %s", self.decision.value, self.reason)


def evaluate_dip_add_gate(
    position: PositionSnapshot,
    config: Optional[DipAddGateConfig] = None,
    now: Optional[float] = None,
) -> DipAddGateResult:
    """Evaluate whether it's safe to add to a position on a dip.

    This is the single authoritative gate. Call it BEFORE any dip-add,
    regardless of how strong the technical signal is.

    Args:
        position: Current position and account state.
        config: Gate configuration thresholds.
        now: Current time (epoch seconds). Defaults to time.time().

    Returns:
        DipAddGateResult with decision and full rationale.
    """
    cfg = config or DipAddGateConfig()
    ts = now or time.time()

    liq_pct = position.liq_distance_pct
    pos_pct = position.position_as_pct_of_equity
    upnl = position.upnl_pct
    seconds_since_add = ts - position.last_add_timestamp

    details = {
        "liq_distance_pct": round(liq_pct, 2),
        "position_pct_of_equity": round(pos_pct, 2),
        "upnl_pct": round(upnl, 2),
        "adds_this_session": position.num_adds_this_session,
        "seconds_since_add": round(seconds_since_add),
        "daily_drawdown_pct": round(position.daily_drawdown_pct, 2),
        "cumulative_funding_pct": round(position.cumulative_funding_pct, 2),
    }

    # ── GATE 1: Liquidation proximity (HARD BLOCK — life safety) ──────────────
    if liq_pct < cfg.min_liq_distance_pct:
        return DipAddGateResult(
            decision=DipAddDecision.BLOCKED_LIQ,
            reason=(
                f"Liq distance {liq_pct:.1f}% is below hard minimum {cfg.min_liq_distance_pct}%. "
                f"Adding would increase liq risk. HOLD, do not add."
            ),
            details=details,
            recommended_size_pct=0.0,
        )

    # ── GATE 2: Position saturation (HARD BLOCK) ───────────────────────────────
    if pos_pct >= cfg.max_position_pct_of_equity:
        return DipAddGateResult(
            decision=DipAddDecision.BLOCKED_SATURATED,
            reason=(
                f"Position is {pos_pct:.1f}% of equity (max={cfg.max_position_pct_of_equity}%). "
                f"Already fully committed. Cannot add more without excessive concentration risk."
            ),
            details=details,
            recommended_size_pct=0.0,
        )

    # ── GATE 3: Unrealized loss — don't average into a falling knife ──────────
    if upnl < cfg.max_unrealized_loss_pct:
        return DipAddGateResult(
            decision=DipAddDecision.BLOCKED_SATURATED,
            reason=(
                f"Position is down {upnl:.1f}% (threshold={cfg.max_unrealized_loss_pct}%). "
                f"Averaging down into a losing position increases risk of liquidation. "
                f"Thesis may be broken — wait for stabilization above entry."
            ),
            details=details,
            recommended_size_pct=0.0,
        )

    # ── GATE 4: Daily drawdown ─────────────────────────────────────────────────
    if position.daily_drawdown_pct > cfg.max_daily_drawdown_pct:
        return DipAddGateResult(
            decision=DipAddDecision.BLOCKED_DRAWDOWN,
            reason=(
                f"Account drawdown {position.daily_drawdown_pct:.1f}% exceeds daily limit "
                f"{cfg.max_daily_drawdown_pct}%. Protecting remaining capital."
            ),
            details=details,
            recommended_size_pct=0.0,
        )

    # ── GATE 5: Scale-in limit ─────────────────────────────────────────────────
    if position.num_adds_this_session >= cfg.max_adds_per_session:
        return DipAddGateResult(
            decision=DipAddDecision.BLOCKED_SCALE_LIMIT,
            reason=(
                f"Already added {position.num_adds_this_session} times this session "
                f"(max={cfg.max_adds_per_session}). Requires manual review to continue scaling."
            ),
            details=details,
            recommended_size_pct=0.0,
        )

    # ── GATE 6: Cooldown ───────────────────────────────────────────────────────
    if position.last_add_timestamp > 0 and seconds_since_add < cfg.min_cooldown_seconds:
        wait = cfg.min_cooldown_seconds - seconds_since_add
        return DipAddGateResult(
            decision=DipAddDecision.COOLDOWN,
            reason=f"Added {seconds_since_add:.0f}s ago. Wait {wait:.0f}s more before next add.",
            details=details,
            recommended_size_pct=0.0,
        )

    # ── SOFT CHECKS (warnings but permit) ─────────────────────────────────────

    # Soft gate: approaching position limit
    size_scale = 1.0
    soft_warns = []

    if pos_pct >= cfg.soft_position_pct_of_equity:
        soft_warns.append(f"position {pos_pct:.1f}% of equity approaching limit")
        size_scale *= 0.5  # half size when getting large

    # Soft gate: liq getting close (warn zone)
    if liq_pct < cfg.warn_liq_distance_pct:
        soft_warns.append(f"liq distance {liq_pct:.1f}% in warning zone (<{cfg.warn_liq_distance_pct}%)")
        size_scale *= 0.5  # reduce size as we approach danger

    # Soft gate: funding cost eating into profit
    if position.cumulative_funding_pct > cfg.warn_funding_pct:
        soft_warns.append(
            f"cumulative funding {position.cumulative_funding_pct:.2f}% of notional"
        )
        return DipAddGateResult(
            decision=DipAddDecision.SOFT_WARN_FUNDING,
            reason=(
                f"PERMITTED with caution: {'; '.join(soft_warns)}. "
                f"Funding is eroding position alpha."
            ),
            details=details,
            recommended_size_pct=size_scale,
        )

    if soft_warns:
        return DipAddGateResult(
            decision=DipAddDecision.PERMITTED,
            reason=f"PERMITTED (caution): {'; '.join(soft_warns)}",
            details=details,
            recommended_size_pct=size_scale,
        )

    # ── ALL CLEAR ──────────────────────────────────────────────────────────────
    return DipAddGateResult(
        decision=DipAddDecision.PERMITTED,
        reason=(
            f"All gates clear: liq={liq_pct:.1f}% pos={pos_pct:.1f}%eq "
            f"upnl={upnl:+.1f}% adds={position.num_adds_this_session}/{cfg.max_adds_per_session}"
        ),
        details=details,
        recommended_size_pct=1.0,
    )
