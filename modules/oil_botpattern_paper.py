"""Oil Bot-Pattern Paper Trader — pure logic.

Spec: docs/wiki/operations/sub_system_5_activation.md

A lightweight simulator that tracks shadow (paper) positions + PnL + a
running account balance for sub-system 5 when it runs in `decisions_only`
mode. The intent: let sub-system 5 run on mainnet in WATCH/REBALANCE
with its kill switch open but NO real orders emitted, so Chris can see
what it would have done — including fills, stops, take-profits, and
running account balance — before committing real capital.

The paper trader:
- Opens a ShadowPosition when sub-system 5's gates pass
- Monitors open positions against live prices each tick
- Closes positions on SL, TP, or manual intervention
- Tracks a running ShadowBalance per seed capital
- Emits Telegram alerts on every open / close / stop with PnL + balance

Zero I/O in this module — the iterator owns persistence.

Paper trades are written to their own ledger
(`oil_botpattern_shadow_trades.jsonl`) NOT to the main `journal.jsonl`.
This is deliberate: L1 auto-tune reads the main journal and should not
be influenced by paper trades. Shadow mode is purely for human review
ahead of going live — the harness only tunes on real trades.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ShadowPosition:
    """An open paper position. Mutable — its cumulative_unrealized_pnl
    field is updated on each mark-to-market tick."""
    instrument: str
    side: str              # "long" | "short"
    entry_ts: str          # ISO 8601 UTC
    entry_price: float
    size: float
    leverage: float
    notional_usd: float
    stop_price: float
    tp_price: float
    edge: float
    rung: int
    unrealized_pnl_usd: float = 0.0
    last_mark_ts: str | None = None
    last_mark_price: float | None = None


@dataclass(frozen=True)
class ShadowTrade:
    """A closed paper trade. Append-only to the shadow ledger."""
    instrument: str
    side: str
    entry_ts: str
    entry_price: float
    exit_ts: str
    exit_price: float
    size: float
    leverage: float
    notional_usd: float
    exit_reason: str       # "tp_hit" | "sl_hit" | "manual" | "mode_change"
    realised_pnl_usd: float
    roe_pct: float
    edge: float
    rung: int
    hold_hours: float


@dataclass
class ShadowBalance:
    """Running paper account balance. Updated on every close."""
    seed_balance_usd: float
    current_balance_usd: float
    realised_pnl_usd: float = 0.0
    closed_trades: int = 0
    wins: int = 0
    losses: int = 0
    last_updated_at: str | None = None

    @property
    def win_rate(self) -> float:
        if self.closed_trades == 0:
            return 0.0
        return self.wins / self.closed_trades

    @property
    def pnl_pct(self) -> float:
        if self.seed_balance_usd <= 0:
            return 0.0
        return (self.realised_pnl_usd / self.seed_balance_usd) * 100.0


# ---------------------------------------------------------------------------
# Stop + TP price computation
# ---------------------------------------------------------------------------

def compute_stop_price(entry_price: float, side: str, sl_pct: float) -> float:
    """Compute a fixed-percent stop-loss price.

    For longs: entry * (1 - sl_pct/100).
    For shorts: entry * (1 + sl_pct/100).
    sl_pct is a positive number (e.g. 2.0 means 2%).
    """
    if entry_price <= 0 or sl_pct <= 0:
        return entry_price
    if side == "long":
        return entry_price * (1.0 - sl_pct / 100.0)
    if side == "short":
        return entry_price * (1.0 + sl_pct / 100.0)
    return entry_price


def compute_tp_price(entry_price: float, side: str, tp_pct: float) -> float:
    """Compute a fixed-percent take-profit price."""
    if entry_price <= 0 or tp_pct <= 0:
        return entry_price
    if side == "long":
        return entry_price * (1.0 + tp_pct / 100.0)
    if side == "short":
        return entry_price * (1.0 - tp_pct / 100.0)
    return entry_price


# ---------------------------------------------------------------------------
# PnL math
# ---------------------------------------------------------------------------

def unrealized_pnl(position: ShadowPosition, current_price: float) -> float:
    """Compute unrealized PnL at a given mark price.

    Long PnL: size * (current - entry)
    Short PnL: size * (entry - current)

    `size` is always expressed as a positive quantity in the base asset;
    `side` determines direction.
    """
    if current_price <= 0 or position.size <= 0:
        return 0.0
    if position.side == "long":
        return position.size * (current_price - position.entry_price)
    if position.side == "short":
        return position.size * (position.entry_price - current_price)
    return 0.0


def realised_pnl(position: ShadowPosition, exit_price: float) -> float:
    """Compute realised PnL when a position closes at exit_price."""
    return unrealized_pnl(position, exit_price)


def roe_pct_on_margin(pnl_usd: float, notional_usd: float, leverage: float) -> float:
    """Return on margin: PnL / (notional / leverage) * 100.

    This is the leveraged return a real trader would see on their posted
    margin, not the unlevered move. Matches how the live thesis engine
    reports ROE.
    """
    if notional_usd <= 0 or leverage <= 0:
        return 0.0
    margin = notional_usd / leverage
    if margin <= 0:
        return 0.0
    return (pnl_usd / margin) * 100.0


# ---------------------------------------------------------------------------
# Exit checking
# ---------------------------------------------------------------------------

def check_exit(
    position: ShadowPosition,
    current_price: float,
) -> tuple[str | None, float]:
    """Determine whether a position should close at the current mark price.

    Returns (exit_reason, exit_price) or (None, 0.0) if no exit.

    For longs: stop hit if current <= stop_price; tp hit if current >= tp_price.
    For shorts: stop hit if current >= stop_price; tp hit if current <= tp_price.

    If both would hit on the same tick (impossible in reality but possible
    with coarse per-tick price sampling), stop wins — conservative exit.
    """
    if current_price <= 0:
        return (None, 0.0)
    if position.side == "long":
        if position.stop_price > 0 and current_price <= position.stop_price:
            return ("sl_hit", position.stop_price)
        if position.tp_price > 0 and current_price >= position.tp_price:
            return ("tp_hit", position.tp_price)
        return (None, 0.0)
    if position.side == "short":
        if position.stop_price > 0 and current_price >= position.stop_price:
            return ("sl_hit", position.stop_price)
        if position.tp_price > 0 and current_price <= position.tp_price:
            return ("tp_hit", position.tp_price)
        return (None, 0.0)
    return (None, 0.0)


# ---------------------------------------------------------------------------
# Position factory
# ---------------------------------------------------------------------------

def open_shadow_position(
    instrument: str,
    side: str,
    entry_price: float,
    size: float,
    leverage: float,
    sl_pct: float,
    tp_pct: float,
    edge: float,
    rung: int,
    now: datetime,
) -> ShadowPosition:
    """Construct a new ShadowPosition with computed SL/TP prices."""
    notional = size * entry_price
    return ShadowPosition(
        instrument=instrument,
        side=side,
        entry_ts=now.isoformat(),
        entry_price=entry_price,
        size=size,
        leverage=leverage,
        notional_usd=notional,
        stop_price=compute_stop_price(entry_price, side, sl_pct),
        tp_price=compute_tp_price(entry_price, side, tp_pct),
        edge=edge,
        rung=rung,
    )


def close_shadow_position(
    position: ShadowPosition,
    exit_price: float,
    exit_reason: str,
    now: datetime,
) -> ShadowTrade:
    """Convert an open ShadowPosition into a closed ShadowTrade."""
    pnl = realised_pnl(position, exit_price)
    roe = roe_pct_on_margin(pnl, position.notional_usd, position.leverage)
    try:
        entry_dt = datetime.fromisoformat(position.entry_ts)
        if entry_dt.tzinfo is None:
            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        hold_hours = max(0.0, (now - entry_dt).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        hold_hours = 0.0
    return ShadowTrade(
        instrument=position.instrument,
        side=position.side,
        entry_ts=position.entry_ts,
        entry_price=position.entry_price,
        exit_ts=now.isoformat(),
        exit_price=exit_price,
        size=position.size,
        leverage=position.leverage,
        notional_usd=position.notional_usd,
        exit_reason=exit_reason,
        realised_pnl_usd=pnl,
        roe_pct=roe,
        edge=position.edge,
        rung=position.rung,
        hold_hours=hold_hours,
    )


# ---------------------------------------------------------------------------
# Balance updates
# ---------------------------------------------------------------------------

def update_balance_on_close(
    balance: ShadowBalance,
    trade: ShadowTrade,
    now: datetime,
) -> ShadowBalance:
    """Return a new ShadowBalance reflecting the closed trade.

    Does NOT mutate the input — shadow balance transitions are audit-
    worthy, and a new object makes atomic persistence easier.
    """
    new_pnl = balance.realised_pnl_usd + trade.realised_pnl_usd
    new_current = balance.seed_balance_usd + new_pnl
    new_wins = balance.wins + (1 if trade.realised_pnl_usd > 0 else 0)
    new_losses = balance.losses + (1 if trade.realised_pnl_usd < 0 else 0)
    return ShadowBalance(
        seed_balance_usd=balance.seed_balance_usd,
        current_balance_usd=new_current,
        realised_pnl_usd=new_pnl,
        closed_trades=balance.closed_trades + 1,
        wins=new_wins,
        losses=new_losses,
        last_updated_at=now.isoformat(),
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def position_to_dict(p: ShadowPosition) -> dict:
    return asdict(p)


def position_from_dict(d: dict) -> ShadowPosition:
    return ShadowPosition(
        instrument=str(d.get("instrument", "")),
        side=str(d.get("side", "long")),
        entry_ts=str(d.get("entry_ts", "")),
        entry_price=float(d.get("entry_price", 0.0) or 0.0),
        size=float(d.get("size", 0.0) or 0.0),
        leverage=float(d.get("leverage", 0.0) or 0.0),
        notional_usd=float(d.get("notional_usd", 0.0) or 0.0),
        stop_price=float(d.get("stop_price", 0.0) or 0.0),
        tp_price=float(d.get("tp_price", 0.0) or 0.0),
        edge=float(d.get("edge", 0.0) or 0.0),
        rung=int(d.get("rung", -1)),
        unrealized_pnl_usd=float(d.get("unrealized_pnl_usd", 0.0) or 0.0),
        last_mark_ts=d.get("last_mark_ts"),
        last_mark_price=d.get("last_mark_price"),
    )


def trade_to_dict(t: ShadowTrade) -> dict:
    return asdict(t)


def balance_to_dict(b: ShadowBalance) -> dict:
    d = asdict(b)
    d["win_rate"] = b.win_rate
    d["pnl_pct"] = b.pnl_pct
    return d


def balance_from_dict(d: dict, default_seed: float = 100_000.0) -> ShadowBalance:
    seed = float(d.get("seed_balance_usd", default_seed) or default_seed)
    current = float(d.get("current_balance_usd", seed) or seed)
    return ShadowBalance(
        seed_balance_usd=seed,
        current_balance_usd=current,
        realised_pnl_usd=float(d.get("realised_pnl_usd", 0.0) or 0.0),
        closed_trades=int(d.get("closed_trades", 0) or 0),
        wins=int(d.get("wins", 0) or 0),
        losses=int(d.get("losses", 0) or 0),
        last_updated_at=d.get("last_updated_at"),
    )


def new_balance(seed_balance_usd: float) -> ShadowBalance:
    return ShadowBalance(
        seed_balance_usd=seed_balance_usd,
        current_balance_usd=seed_balance_usd,
    )
