"""Backtest reporter — console output and chart generation."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from engines.learning.backtest_engine import BacktestResult

log = logging.getLogger("backtest_reporter")


class BacktestReporter:
    """Format and display backtest results."""

    @staticmethod
    def print_summary(result: BacktestResult) -> None:
        """Print a concise summary to console."""
        cfg = result.config
        print("")
        print(f"  {'='*56}")
        print(f"  BACKTEST RESULTS: {cfg.coin}-PERP {cfg.interval}")
        print(f"  {'='*56}")
        print(f"  Candles:      {result.candles_processed:,}")
        print(f"  Capital:      ${cfg.initial_capital:,.0f}")
        print(f"  Period:       {_ts_to_date(cfg.start_ms)} → {_ts_to_date(cfg.end_ms)}")
        print(f"  {'-'*56}")
        print(f"  Net PnL:      ${result.net_pnl:+,.2f}  ({result.net_pnl_pct:+.1f}%)")
        print(f"  Total trades: {result.total_trades}")
        print(f"  Win rate:     {result.win_rate:.1f}%")
        print(f"  Profit factor:{result.profit_factor:.2f}")
        print(f"  Sharpe ratio: {result.sharpe_ratio:.2f}")
        print(f"  Max drawdown: {result.max_drawdown_pct:.1f}%")
        print(f"  Best trade:   ${result.best_trade:+,.2f}")
        print(f"  Worst trade:  ${result.worst_trade:+,.2f}")
        print(f"  Avg trade:    ${result.avg_trade_pnl:+,.2f}")

        if result.equity_curve:
            final_eq = result.equity_curve[-1][1]
            print(f"  Final equity: ${final_eq:,.2f}")

        print(f"  {'='*56}")
        print("")

    @staticmethod
    def plot_equity(
        result: BacktestResult,
        output_path: str = "data/backtest/equity.png",
    ) -> Optional[str]:
        """Generate equity curve chart. Returns path or None if matplotlib unavailable."""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            log.warning("matplotlib not available, skipping chart")
            return None

        if not result.equity_curve:
            return None

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        timestamps = [datetime.fromtimestamp(t / 1000) for t, _ in result.equity_curve]
        equities = [e for _, e in result.equity_curve]

        # Calculate drawdown series
        peak = equities[0]
        drawdowns = []
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            drawdowns.append(-dd)

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), height_ratios=[3, 1], sharex=True)
        fig.suptitle(
            f"Backtest: {result.config.coin}-PERP {result.config.interval}  |  "
            f"PnL: ${result.net_pnl:+,.0f} ({result.net_pnl_pct:+.1f}%)  |  "
            f"Sharpe: {result.sharpe_ratio:.2f}",
            fontsize=12,
        )

        # Equity curve
        ax1.plot(timestamps, equities, linewidth=1.2, color="#2196F3")
        ax1.axhline(y=result.config.initial_capital, color="gray", linestyle="--", alpha=0.5)
        ax1.fill_between(
            timestamps, result.config.initial_capital, equities,
            where=[e >= result.config.initial_capital for e in equities],
            alpha=0.15, color="green",
        )
        ax1.fill_between(
            timestamps, result.config.initial_capital, equities,
            where=[e < result.config.initial_capital for e in equities],
            alpha=0.15, color="red",
        )
        ax1.set_ylabel("Equity ($)")
        ax1.grid(True, alpha=0.3)

        # Drawdown
        ax2.fill_between(timestamps, 0, drawdowns, alpha=0.4, color="red")
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        fig.autofmt_xdate()

        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()

        log.info("Equity chart saved to %s", output_path)
        return output_path

    @staticmethod
    def to_json(result: BacktestResult) -> str:
        """Export results as JSON."""
        return json.dumps({
            "config": {
                "coin": result.config.coin,
                "instrument": result.config.instrument,
                "interval": result.config.interval,
                "start_ms": result.config.start_ms,
                "end_ms": result.config.end_ms,
                "initial_capital": result.config.initial_capital,
                "fee_bps": result.config.fee_bps,
            },
            "metrics": {
                "net_pnl": round(result.net_pnl, 2),
                "net_pnl_pct": round(result.net_pnl_pct, 2),
                "total_trades": result.total_trades,
                "win_rate": round(result.win_rate, 2),
                "profit_factor": round(result.profit_factor, 2),
                "sharpe_ratio": round(result.sharpe_ratio, 2),
                "max_drawdown_pct": round(result.max_drawdown_pct, 2),
                "best_trade": round(result.best_trade, 2),
                "worst_trade": round(result.worst_trade, 2),
                "candles_processed": result.candles_processed,
            },
            "trades": [
                {
                    "ts": t.timestamp_ms,
                    "side": t.side,
                    "action": t.action,
                    "price": round(t.price, 2),
                    "size": round(t.size, 6),
                    "fee": round(t.fee, 4),
                    "pnl": round(t.pnl, 2),
                }
                for t in result.trades
            ],
        }, indent=2)


def _ts_to_date(ts_ms: int) -> str:
    """Convert millisecond timestamp to human-readable date."""
    if ts_ms <= 0:
        return "?"
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
