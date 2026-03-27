"""Backtest engine — replay cached candle data through any BaseStrategy.

Simulates order fills, tracks equity curve, and computes performance
metrics. Uses the exact same on_tick() code path as live trading for
maximum fidelity.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from common.models import MarketSnapshot
from modules.candle_cache import CandleCache

log = logging.getLogger("backtest")


@dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""

    coin: str = "BTC"
    instrument: str = ""  # auto-derived: BTC -> BTC-PERP
    interval: str = "1h"
    start_ms: int = 0  # 0 = use all available data
    end_ms: int = 0
    days: int = 90  # used if start_ms/end_ms not set

    initial_capital: float = 10_000.0
    fee_bps: float = 3.5  # HL taker fee
    slippage_bps: float = 1.0
    max_leverage: float = 10.0

    def __post_init__(self):
        if not self.instrument:
            self.instrument = f"{self.coin.upper()}-PERP"
        if self.start_ms == 0 and self.end_ms == 0 and self.days > 0:
            self.end_ms = int(time.time() * 1000)
            self.start_ms = self.end_ms - (self.days * 86_400_000)


@dataclass
class BacktestTrade:
    """A simulated trade fill."""

    timestamp_ms: int
    side: str  # "long" or "short"
    action: str  # "open" or "close"
    price: float
    size: float
    fee: float
    pnl: float = 0.0
    equity_after: float = 0.0


@dataclass
class BacktestResult:
    """Complete results from a backtest run."""

    config: BacktestConfig
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[Tuple[int, float]] = field(default_factory=list)

    # Performance metrics (computed after run)
    net_pnl: float = 0.0
    net_pnl_pct: float = 0.0
    win_rate: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    avg_trade_pnl: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    candles_processed: int = 0

    def compute_metrics(self):
        """Calculate performance metrics from trades and equity curve."""
        closed = [t for t in self.trades if t.action == "close"]
        self.total_trades = len(closed)

        if not closed:
            return

        pnls = [t.pnl for t in closed]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        self.net_pnl = sum(pnls)
        self.net_pnl_pct = (self.net_pnl / self.config.initial_capital) * 100
        self.win_rate = len(wins) / len(pnls) * 100 if pnls else 0
        self.avg_trade_pnl = self.net_pnl / len(pnls) if pnls else 0
        self.best_trade = max(pnls) if pnls else 0
        self.worst_trade = min(pnls) if pnls else 0
        self.profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")

        # Max drawdown from equity curve
        if self.equity_curve:
            peak = self.equity_curve[0][1]
            max_dd = 0.0
            for _, eq in self.equity_curve:
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100 if peak > 0 else 0
                if dd > max_dd:
                    max_dd = dd
            self.max_drawdown_pct = max_dd

        # Annualized Sharpe ratio
        if len(pnls) >= 2:
            import numpy as np
            returns = np.array(pnls) / self.config.initial_capital
            if np.std(returns) > 0:
                # Annualize based on interval
                periods_per_year = {"1h": 8760, "4h": 2190, "1d": 365, "15m": 35040}.get(
                    self.config.interval, 8760
                )
                self.sharpe_ratio = float(
                    np.mean(returns) / np.std(returns) * math.sqrt(periods_per_year)
                )


class BacktestEngine:
    """Replay cached candle data through any BaseStrategy.

    Usage:
        cache = CandleCache()
        config = BacktestConfig(coin="BTC", interval="1h", days=90)
        engine = BacktestEngine(cache, config)
        result = engine.run(my_strategy)
        result.compute_metrics()
    """

    def __init__(self, cache: CandleCache, config: BacktestConfig):
        self.cache = cache
        self.config = config
        self._equity = config.initial_capital
        self._position: Optional[Dict[str, Any]] = None  # {side, entry_price, size}
        self._trades: List[BacktestTrade] = []
        self._equity_curve: List[Tuple[int, float]] = []

    def run(self, strategy) -> BacktestResult:
        """Run the backtest. strategy must have on_tick(snapshot, context) method."""
        candles = self.cache.get_candles(
            self.config.coin,
            self.config.interval,
            self.config.start_ms,
            self.config.end_ms,
        )

        if not candles:
            log.warning("No candles found for %s %s in range", self.config.coin, self.config.interval)
            return BacktestResult(config=self.config)

        log.info(
            "Starting backtest: %s %s, %d candles, $%.0f capital",
            self.config.coin, self.config.interval, len(candles), self.config.initial_capital,
        )

        for i, candle in enumerate(candles):
            snapshot = self._candle_to_snapshot(candle)
            context = self._build_context(candle, i, len(candles))

            try:
                decisions = strategy.on_tick(snapshot, context)
                if decisions:
                    for decision in decisions:
                        self._process_decision(decision, candle)
            except Exception as exc:
                log.debug("Strategy error at candle %d: %s", i, exc)

            # Track equity (mark-to-market)
            mtm_equity = self._mark_to_market(float(candle["c"]))
            self._equity_curve.append((int(candle["t"]), mtm_equity))

        # Close any open position at the end
        if self._position:
            self._close_position(float(candles[-1]["c"]), int(candles[-1]["t"]))

        result = BacktestResult(
            config=self.config,
            trades=self._trades,
            equity_curve=self._equity_curve,
            candles_processed=len(candles),
        )
        result.compute_metrics()
        return result

    def _candle_to_snapshot(self, candle: Dict) -> MarketSnapshot:
        """Convert a candle dict to a MarketSnapshot."""
        close = float(candle["c"])
        high = float(candle["h"])
        low = float(candle["l"])
        volume = float(candle["v"])

        # Synthetic bid/ask from candle range
        spread = max(high - low, close * 0.0001)
        return MarketSnapshot(
            instrument=self.config.instrument,
            mid_price=close,
            bid=close - spread * 0.01,
            ask=close + spread * 0.01,
            spread_bps=(spread / close * 10000) if close > 0 else 0,
            timestamp_ms=int(candle["t"]),
            volume_24h=volume,
            funding_rate=0.0,
            open_interest=0.0,
        )

    def _build_context(self, candle: Dict, index: int, total: int):
        """Build a strategy context for the current candle."""
        from sdk.strategy_sdk.base import StrategyContext

        unrealized = 0.0
        if self._position:
            price = float(candle["c"])
            entry = self._position["entry_price"]
            size = self._position["size"]
            if self._position["side"] == "long":
                unrealized = (price - entry) * size
            else:
                unrealized = (entry - price) * size

        # position_qty: positive = long, negative = short, 0 = flat
        pos_qty = 0.0
        pos_notional = 0.0
        if self._position:
            size = self._position["size"]
            price = float(candle["c"])
            pos_qty = size if self._position["side"] == "long" else -size
            pos_notional = abs(size * price)

        snapshot = self._candle_to_snapshot(candle)

        return StrategyContext(
            snapshot=snapshot,
            position_qty=pos_qty,
            position_notional=pos_notional,
            unrealized_pnl=unrealized,
            realized_pnl=sum(t.pnl for t in self._trades if t.action == "close"),
            round_number=index,
            meta={
                "backtest": True,
                "candle_index": index,
                "candles_total": total,
                "account_value": self._equity + unrealized,
                "drawdown_pct": 0.0,
            },
        )

    def _process_decision(self, decision, candle: Dict):
        """Process a StrategyDecision: simulate fills."""
        action = getattr(decision, "action", "")
        if action != "place_order":
            return

        side = getattr(decision, "side", "long")
        size = getattr(decision, "size", 0.0)
        price = float(candle["c"])
        ts = int(candle["t"])

        if size <= 0:
            return

        # Apply slippage
        slip = price * (self.config.slippage_bps / 10000)
        fill_price = price + slip if side == "long" else price - slip

        # Fee
        fee = fill_price * size * (self.config.fee_bps / 10000)

        if self._position:
            # Close existing position if opposite side
            if self._position["side"] != side:
                self._close_position(fill_price, ts)
                # Open new position
                self._open_position(side, fill_price, size, fee, ts)
            else:
                # Add to position (average up/down)
                old_size = self._position["size"]
                old_entry = self._position["entry_price"]
                new_size = old_size + size
                self._position["entry_price"] = (old_entry * old_size + fill_price * size) / new_size
                self._position["size"] = new_size
                self._equity -= fee
        else:
            self._open_position(side, fill_price, size, fee, ts)

    def _open_position(self, side: str, price: float, size: float, fee: float, ts: int):
        """Open a new position."""
        # Check leverage
        notional = price * size
        max_notional = self._equity * self.config.max_leverage
        if notional > max_notional:
            size = max_notional / price
            notional = max_notional

        self._position = {"side": side, "entry_price": price, "size": size}
        self._equity -= fee

        self._trades.append(BacktestTrade(
            timestamp_ms=ts, side=side, action="open",
            price=price, size=size, fee=fee, equity_after=self._equity,
        ))

    def _close_position(self, price: float, ts: int):
        """Close the current position and realize PnL."""
        if not self._position:
            return

        entry = self._position["entry_price"]
        size = self._position["size"]
        side = self._position["side"]

        if side == "long":
            pnl = (price - entry) * size
        else:
            pnl = (entry - price) * size

        fee = price * size * (self.config.fee_bps / 10000)
        pnl -= fee
        self._equity += pnl

        self._trades.append(BacktestTrade(
            timestamp_ms=ts, side=side, action="close",
            price=price, size=size, fee=fee, pnl=pnl, equity_after=self._equity,
        ))

        self._position = None

    def _mark_to_market(self, current_price: float) -> float:
        """Current equity including unrealized PnL."""
        if not self._position:
            return self._equity

        entry = self._position["entry_price"]
        size = self._position["size"]
        if self._position["side"] == "long":
            unrealized = (current_price - entry) * size
        else:
            unrealized = (entry - current_price) * size

        return self._equity + unrealized
