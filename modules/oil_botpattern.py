"""Oil Bot-Pattern Strategy Engine — pure logic.

Spec: docs/plans/OIL_BOT_PATTERN_05_STRATEGY_ENGINE.md

Sub-system 5 of the Oil Bot-Pattern Strategy. The only place in the
codebase where shorting BRENTOIL/CL is legal, gated by a chain of
hard checks. Conviction-sized (Druckenmiller-style) with drawdown
circuit breakers. Funding-cost exit for longs (no time cap).

This file is pure computation — no I/O, no orders, no HTTP. The
iterator in cli/daemon/iterators/oil_botpattern.py wires it up.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CLASSIFICATIONS_SHORT_ELIGIBLE = ("bot_driven_overextension",)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GateResult:
    """Result of a single gate check."""
    name: str
    passed: bool
    reason: str


@dataclass(frozen=True)
class SizingDecision:
    """Output of the conviction-sizing ladder."""
    edge: float
    rung: int  # index into sizing_ladder; -1 if below floor
    base_pct: float
    leverage: float
    sizing_multiplier: float
    target_notional_usd: float
    target_size: float  # instrument units (base_pct × leverage × multiplier × equity / price)


@dataclass(frozen=True)
class Decision:
    """A single per-tick strategy decision for one instrument.

    Written to decision_journal_jsonl regardless of whether action is
    taken. Provides the audit trail for sub-system 6 self-tuning.
    """
    id: str
    instrument: str
    decided_at: datetime
    direction: str            # "long" | "short" | "flat"
    action: str               # "open" | "hold" | "close" | "skip"
    edge: float
    classification: str       # from sub-system 4
    classifier_confidence: float
    thesis_conviction: float
    recent_outcome_bias: float
    sizing: dict              # serialized SizingDecision
    gate_results: list[dict]  # serialized list[GateResult]
    notes: str = ""


@dataclass
class StrategyState:
    """Per-instrument tactical state. Mutable; written atomically each tick."""
    open_positions: dict[str, dict] = field(default_factory=dict)
    # instrument -> {"side": "long"|"short", "entry_ts": iso,
    #                "entry_price": float, "size": float, "leverage": float,
    #                "cumulative_funding_usd": float,
    #                "realised_pnl_today_usd": float}

    daily_realised_pnl_usd: float = 0.0
    weekly_realised_pnl_usd: float = 0.0
    monthly_realised_pnl_usd: float = 0.0
    daily_window_start: str = ""   # iso
    weekly_window_start: str = ""  # iso
    monthly_window_start: str = ""  # iso

    daily_brake_tripped_at: str | None = None
    weekly_brake_tripped_at: str | None = None
    monthly_brake_tripped_at: str | None = None
    brake_cleared_at: str | None = None  # Chris flips this manually

    enabled_since: str | None = None  # for 1h grace period


# ---------------------------------------------------------------------------
# JSONL I/O for decisions
# ---------------------------------------------------------------------------

def _decision_to_dict(d: Decision) -> dict:
    out = asdict(d)
    out["decided_at"] = d.decided_at.isoformat()
    return out


def _decision_from_dict(raw: dict) -> Decision:
    return Decision(
        id=raw["id"],
        instrument=raw["instrument"],
        decided_at=datetime.fromisoformat(raw["decided_at"]),
        direction=raw["direction"],
        action=raw["action"],
        edge=float(raw["edge"]),
        classification=raw["classification"],
        classifier_confidence=float(raw["classifier_confidence"]),
        thesis_conviction=float(raw["thesis_conviction"]),
        recent_outcome_bias=float(raw["recent_outcome_bias"]),
        sizing=dict(raw.get("sizing", {})),
        gate_results=list(raw.get("gate_results", [])),
        notes=raw.get("notes", ""),
    )


def append_decision(jsonl_path: str, d: Decision) -> None:
    p = Path(jsonl_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(_decision_to_dict(d)) + "\n")


def read_decisions(jsonl_path: str) -> list[Decision]:
    p = Path(jsonl_path)
    if not p.exists():
        return []
    out: list[Decision] = []
    with p.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(_decision_from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# State I/O (atomic)
# ---------------------------------------------------------------------------

def _state_to_dict(s: StrategyState) -> dict:
    return {
        "open_positions": s.open_positions,
        "daily_realised_pnl_usd": s.daily_realised_pnl_usd,
        "weekly_realised_pnl_usd": s.weekly_realised_pnl_usd,
        "monthly_realised_pnl_usd": s.monthly_realised_pnl_usd,
        "daily_window_start": s.daily_window_start,
        "weekly_window_start": s.weekly_window_start,
        "monthly_window_start": s.monthly_window_start,
        "daily_brake_tripped_at": s.daily_brake_tripped_at,
        "weekly_brake_tripped_at": s.weekly_brake_tripped_at,
        "monthly_brake_tripped_at": s.monthly_brake_tripped_at,
        "brake_cleared_at": s.brake_cleared_at,
        "enabled_since": s.enabled_since,
    }


def _state_from_dict(raw: dict) -> StrategyState:
    return StrategyState(
        open_positions=dict(raw.get("open_positions", {})),
        daily_realised_pnl_usd=float(raw.get("daily_realised_pnl_usd", 0.0)),
        weekly_realised_pnl_usd=float(raw.get("weekly_realised_pnl_usd", 0.0)),
        monthly_realised_pnl_usd=float(raw.get("monthly_realised_pnl_usd", 0.0)),
        daily_window_start=raw.get("daily_window_start", "") or "",
        weekly_window_start=raw.get("weekly_window_start", "") or "",
        monthly_window_start=raw.get("monthly_window_start", "") or "",
        daily_brake_tripped_at=raw.get("daily_brake_tripped_at"),
        weekly_brake_tripped_at=raw.get("weekly_brake_tripped_at"),
        monthly_brake_tripped_at=raw.get("monthly_brake_tripped_at"),
        brake_cleared_at=raw.get("brake_cleared_at"),
        enabled_since=raw.get("enabled_since"),
    )


def read_state(path: str) -> StrategyState:
    p = Path(path)
    if not p.exists():
        return StrategyState()
    try:
        return _state_from_dict(json.loads(p.read_text()))
    except (OSError, json.JSONDecodeError):
        return StrategyState()


def write_state_atomic(path: str, state: StrategyState) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(_state_to_dict(state), indent=2, sort_keys=True))
    os.replace(tmp, p)


# ---------------------------------------------------------------------------
# Edge computation (conviction sizing input)
# ---------------------------------------------------------------------------

def compute_edge(
    classifier_confidence: float,
    thesis_conviction: float,
    thesis_direction_matches: bool,
    recent_outcome_bias: float = 0.0,
) -> float:
    """Blend classifier + thesis + recent outcome bias into a single edge.

    - classifier_confidence is sub-system 4's output (0..1)
    - thesis_conviction is the long-horizon thesis score (0..1); zeroed
      when direction doesn't match
    - recent_outcome_bias is a small additive adjustment from last N
      closed trades (-0.05..+0.05)
    """
    thesis_contribution = thesis_conviction if thesis_direction_matches else 0.0
    edge = max(classifier_confidence, thesis_contribution) + recent_outcome_bias
    return max(0.0, min(1.0, edge))


def compute_recent_outcome_bias(recent_trades: list[dict], min_trades: int = 3) -> float:
    """Small additive edge adjustment from last 5 closed oil_botpattern trades.

    win rate > 0.6 → +0.05
    win rate < 0.4 → −0.05
    otherwise → 0
    Requires at least `min_trades` data points.
    """
    if len(recent_trades) < min_trades:
        return 0.0
    wins = sum(1 for t in recent_trades if float(t.get("realised_pnl_usd", 0)) > 0)
    win_rate = wins / len(recent_trades)
    if win_rate > 0.6:
        return 0.05
    if win_rate < 0.4:
        return -0.05
    return 0.0


# ---------------------------------------------------------------------------
# Sizing ladder
# ---------------------------------------------------------------------------

def size_from_edge(
    edge: float,
    sizing_ladder: list[dict],
    sizing_multiplier: float,
    equity_usd: float,
    price: float,
) -> SizingDecision:
    """Walk the sizing ladder to translate edge → notional + leverage.

    Returns a SizingDecision with rung=-1 if edge is below the floor
    (no trade). `sizing_ladder` must be sorted ascending by min_edge.
    """
    if equity_usd <= 0 or price <= 0:
        return SizingDecision(edge=edge, rung=-1, base_pct=0.0, leverage=0.0,
                              sizing_multiplier=sizing_multiplier,
                              target_notional_usd=0.0, target_size=0.0)

    matched_rung = -1
    base_pct = 0.0
    leverage = 0.0
    for i, rung in enumerate(sizing_ladder):
        if edge >= float(rung.get("min_edge", 0)):
            matched_rung = i
            base_pct = float(rung.get("base_pct", 0))
            leverage = float(rung.get("leverage", 0))

    if matched_rung < 0:
        return SizingDecision(edge=edge, rung=-1, base_pct=0.0, leverage=0.0,
                              sizing_multiplier=sizing_multiplier,
                              target_notional_usd=0.0, target_size=0.0)

    target_notional = equity_usd * base_pct * sizing_multiplier * leverage
    target_size = target_notional / price if price > 0 else 0.0
    return SizingDecision(
        edge=edge, rung=matched_rung, base_pct=base_pct, leverage=leverage,
        sizing_multiplier=sizing_multiplier,
        target_notional_usd=target_notional, target_size=target_size,
    )


# ---------------------------------------------------------------------------
# Gate chain
# ---------------------------------------------------------------------------

def gate_classification_ok(
    direction: str,
    latest_pattern: dict | None,
    long_min_edge: float,
    short_min_edge: float,
) -> GateResult:
    """Latest BotPattern must exist and match direction with sufficient confidence.

    Longs need classification != 'unclear' and edge ≥ long_min_edge.
    Shorts need classification == 'bot_driven_overextension' and edge ≥
    short_min_edge.
    """
    if latest_pattern is None:
        return GateResult("classification", False, "no BotPattern record for instrument")
    cls = latest_pattern.get("classification", "unclear")
    conf = float(latest_pattern.get("confidence", 0.0))
    pat_dir = latest_pattern.get("direction", "flat")

    if direction == "long":
        if cls == "unclear":
            return GateResult("classification", False, "classification unclear")
        if pat_dir != "up":
            return GateResult("classification", False, f"pattern direction {pat_dir} ≠ long")
        if conf < long_min_edge:
            return GateResult("classification", False, f"conf {conf:.2f} < {long_min_edge}")
        return GateResult("classification", True, f"{cls} up conf={conf:.2f}")

    if direction == "short":
        if cls not in CLASSIFICATIONS_SHORT_ELIGIBLE:
            return GateResult("classification", False,
                              f"only {CLASSIFICATIONS_SHORT_ELIGIBLE} eligible, got {cls}")
        if pat_dir != "down":
            return GateResult("classification", False, f"pattern direction {pat_dir} ≠ short")
        if conf < short_min_edge:
            return GateResult("classification", False, f"conf {conf:.2f} < {short_min_edge}")
        return GateResult("classification", True, f"{cls} down conf={conf:.2f}")

    return GateResult("classification", False, f"unknown direction {direction}")


def gate_no_blocking_catalyst(
    catalysts_next_24h: list[dict],
    severity_floor: int,
    direction: str,
) -> GateResult:
    """Short-leg-only gate: no pending high-sev catalyst that would fight a short.

    Bullish catalyst (direction=up OR neutral/empty) with sev ≥ floor
    pending in the next 24h blocks opening a short.
    """
    blocking = []
    for c in catalysts_next_24h:
        try:
            sev = int(c.get("severity", 0))
        except (TypeError, ValueError):
            continue
        if sev < severity_floor:
            continue
        cat_dir = (c.get("direction") or "").lower()
        # Treat missing/neutral as potentially-bullish for safety
        if direction == "short" and cat_dir in ("", "up", "neutral"):
            blocking.append(c)
    if blocking:
        top = blocking[0]
        return GateResult("no_blocking_catalyst", False,
                          f"blocked by sev{top.get('severity')} "
                          f"{top.get('category', '?')} in next 24h")
    return GateResult("no_blocking_catalyst", True, "no blocking catalyst in next 24h")


def gate_no_fresh_supply_upgrade(
    supply_state: dict | None,
    freshness_hours: int,
    direction: str,
    detected_at: datetime,
) -> GateResult:
    """Short-leg-only gate: no fresh supply disruption upgrade.

    A recent (≤freshness_hours) supply state with active disruptions is
    a bullish-on-oil signal; opening a short against it is fighting the
    fundamental.
    """
    if direction != "short":
        return GateResult("no_fresh_supply_upgrade", True, "n/a for longs")
    if not supply_state:
        return GateResult("no_fresh_supply_upgrade", True, "no supply state (not blocking)")
    try:
        computed_at = datetime.fromisoformat(supply_state.get("computed_at", ""))
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return GateResult("no_fresh_supply_upgrade", True, "unparseable supply timestamp")
    age = detected_at - computed_at
    if age > timedelta(hours=freshness_hours):
        return GateResult("no_fresh_supply_upgrade", True,
                          f"supply state stale ({age.total_seconds()/3600:.1f}h old)")
    active = int(supply_state.get("active_disruption_count", 0))
    if active == 0:
        return GateResult("no_fresh_supply_upgrade", True, "no active disruptions")
    return GateResult("no_fresh_supply_upgrade", False,
                      f"fresh supply state with {active} active disruptions — short blocked")


def gate_short_grace_period(
    state: StrategyState,
    grace_period_s: int,
    now: datetime,
) -> GateResult:
    """Short-leg-only gate: require 1h since `enabled` was flipped on."""
    if not state.enabled_since:
        return GateResult("short_grace_period", False, "enabled_since not set")
    try:
        since = datetime.fromisoformat(state.enabled_since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return GateResult("short_grace_period", False, "unparseable enabled_since")
    elapsed = (now - since).total_seconds()
    if elapsed < grace_period_s:
        return GateResult("short_grace_period", False,
                          f"grace period: {elapsed:.0f}s / {grace_period_s}s elapsed")
    return GateResult("short_grace_period", True,
                      f"grace period cleared ({elapsed:.0f}s ≥ {grace_period_s}s)")


def gate_short_daily_loss_cap(
    state: StrategyState,
    equity_usd: float,
    daily_loss_cap_pct: float,
) -> GateResult:
    """Short-leg-only gate: daily realised loss on short layer ≤ cap."""
    if equity_usd <= 0:
        return GateResult("short_daily_loss_cap", False, "equity ≤ 0")
    # This is realised PnL across the entire strategy; conservatively use
    # total daily realised as the short-layer proxy (short_daily is a
    # subset and we don't track it separately in v1).
    loss_pct = -state.daily_realised_pnl_usd / equity_usd * 100.0 if state.daily_realised_pnl_usd < 0 else 0.0
    if loss_pct >= daily_loss_cap_pct:
        return GateResult("short_daily_loss_cap", False,
                          f"daily loss {loss_pct:.2f}% ≥ cap {daily_loss_cap_pct}%")
    return GateResult("short_daily_loss_cap", True,
                      f"daily loss {loss_pct:.2f}% < cap {daily_loss_cap_pct}%")


def gate_thesis_conflict(
    direction: str,
    thesis_state: dict | None,
    instrument: str,
    last_conflict_at: datetime | None,
    now: datetime,
    conflict_lockout_hours: int = 24,
) -> GateResult:
    """Lock out the bot-pattern direction when it conflicts with the thesis.

    Same direction: stacks (pass).
    Opposite direction: thesis wins, bot-pattern locked for 24h.
    No thesis: pass.
    """
    if not thesis_state:
        return GateResult("thesis_conflict", True, "no thesis (pass)")
    thesis_dir = (thesis_state.get("direction") or "flat").lower()
    if thesis_dir in ("flat", "neutral", ""):
        return GateResult("thesis_conflict", True, "thesis flat")
    if direction == thesis_dir:
        return GateResult("thesis_conflict", True, f"same direction as thesis ({thesis_dir})")
    # Opposite direction — check lockout
    if last_conflict_at is not None:
        elapsed = now - last_conflict_at
        if elapsed < timedelta(hours=conflict_lockout_hours):
            return GateResult("thesis_conflict", False,
                              f"thesis conflict lockout: {elapsed.total_seconds()/3600:.1f}h / {conflict_lockout_hours}h")
    return GateResult("thesis_conflict", False,
                      f"opposite to thesis ({thesis_dir}) — thesis wins, 24h lockout")


# ---------------------------------------------------------------------------
# Drawdown brakes
# ---------------------------------------------------------------------------

def check_drawdown_brakes(
    state: StrategyState,
    equity_usd: float,
    daily_cap_pct: float,
    weekly_cap_pct: float,
    monthly_cap_pct: float,
) -> tuple[bool, str]:
    """Evaluate all three brake levels. Returns (blocked, reason)."""
    if equity_usd <= 0:
        return (True, "equity ≤ 0")

    if state.monthly_brake_tripped_at and not state.brake_cleared_at:
        return (True, f"monthly brake tripped at {state.monthly_brake_tripped_at}")
    if state.weekly_brake_tripped_at and not state.brake_cleared_at:
        return (True, f"weekly brake tripped at {state.weekly_brake_tripped_at}")

    if state.daily_realised_pnl_usd < 0:
        daily_loss_pct = -state.daily_realised_pnl_usd / equity_usd * 100.0
        if daily_loss_pct >= daily_cap_pct:
            return (True, f"daily brake: {daily_loss_pct:.2f}% ≥ {daily_cap_pct}%")

    if state.weekly_realised_pnl_usd < 0:
        weekly_loss_pct = -state.weekly_realised_pnl_usd / equity_usd * 100.0
        if weekly_loss_pct >= weekly_cap_pct:
            return (True, f"weekly brake: {weekly_loss_pct:.2f}% ≥ {weekly_cap_pct}%")

    if state.monthly_realised_pnl_usd < 0:
        monthly_loss_pct = -state.monthly_realised_pnl_usd / equity_usd * 100.0
        if monthly_loss_pct >= monthly_cap_pct:
            return (True, f"monthly brake: {monthly_loss_pct:.2f}% ≥ {monthly_cap_pct}%")

    return (False, "brakes clear")


def maybe_reset_daily_window(state: StrategyState, now: datetime) -> bool:
    """Reset daily PnL accumulator and daily brake at UTC rollover."""
    today = now.strftime("%Y-%m-%d")
    if state.daily_window_start == today:
        return False
    state.daily_window_start = today
    state.daily_realised_pnl_usd = 0.0
    state.daily_brake_tripped_at = None
    return True


def maybe_reset_weekly_window(state: StrategyState, now: datetime) -> bool:
    """Reset weekly PnL accumulator at ISO week start (Monday UTC)."""
    iso_year, iso_week, _ = now.isocalendar()
    week_key = f"{iso_year}-W{iso_week:02d}"
    if state.weekly_window_start == week_key:
        return False
    state.weekly_window_start = week_key
    state.weekly_realised_pnl_usd = 0.0
    # Weekly brake does NOT auto-reset — requires manual clear
    return True


def maybe_reset_monthly_window(state: StrategyState, now: datetime) -> bool:
    month_key = now.strftime("%Y-%m")
    if state.monthly_window_start == month_key:
        return False
    state.monthly_window_start = month_key
    state.monthly_realised_pnl_usd = 0.0
    # Monthly brake does NOT auto-reset — requires manual clear
    return True


# ---------------------------------------------------------------------------
# Funding-cost exit (longs only)
# ---------------------------------------------------------------------------

def should_exit_on_funding(
    cumulative_funding_usd: float,
    position_notional_usd: float,
    warn_pct: float,
    exit_pct: float,
) -> tuple[str, str]:
    """Return (action, reason): action ∈ {'hold', 'warn', 'exit'}."""
    if position_notional_usd <= 0:
        return ("hold", "no position notional")
    pct_paid = cumulative_funding_usd / position_notional_usd * 100.0
    if pct_paid >= exit_pct:
        return ("exit", f"funding {pct_paid:.2f}% ≥ exit {exit_pct}%")
    if pct_paid >= warn_pct:
        return ("warn", f"funding {pct_paid:.2f}% ≥ warn {warn_pct}%")
    return ("hold", f"funding {pct_paid:.2f}% < warn {warn_pct}%")


# ---------------------------------------------------------------------------
# Hold cap (shorts only)
# ---------------------------------------------------------------------------

def short_should_force_close(
    entry_ts: str,
    now: datetime,
    max_hold_hours: int,
) -> tuple[bool, str]:
    """Return (should_close, reason) for the 24h short hard cap."""
    try:
        entry = datetime.fromisoformat(entry_ts)
        if entry.tzinfo is None:
            entry = entry.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return (True, "unparseable entry_ts — force close for safety")
    elapsed = (now - entry).total_seconds() / 3600.0
    if elapsed >= max_hold_hours:
        return (True, f"hold cap: {elapsed:.1f}h ≥ {max_hold_hours}h")
    return (False, f"hold {elapsed:.1f}h < {max_hold_hours}h")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_decision_id(instrument: str, decided_at: datetime) -> str:
    return f"{instrument}_{decided_at.isoformat()}"


def gate_results_to_dicts(results: list[GateResult]) -> list[dict]:
    return [{"name": r.name, "passed": r.passed, "reason": r.reason} for r in results]


def sizing_to_dict(s: SizingDecision) -> dict:
    return asdict(s)
