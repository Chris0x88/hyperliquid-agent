#!/usr/bin/env python3
"""
Power Law Rebalancer Bot — Hyperliquid Integration
===================================================

All Hedera / SpaceLord / HCS / HBAR references removed.
Uses HLPowerLawAdapter for price, portfolio, and execution.

Core logic:
  1. Get HL account state + BTC-PERP position
  2. Run heartbeat model → target allocation %
  3. Compare target to current (leverage-normalised) allocation
  4. If deviation > threshold → rebalance via BTC-PERP order
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from plugins.power_law.config import PowerLawConfig, get_power_law_config
from plugins.power_law.adapter import HLPowerLawAdapter, PortfolioState

log = logging.getLogger("power_law.bot")

# State persistence path (within agent-cli data dir)
STATE_FILE = Path("data/power_law/state.json")


class PowerLawBot:
    """
    Rebalancer bot that uses the Bitcoin Heartbeat Model to determine
    optimal BTC-PERP leverage and rebalances via Hyperliquid orders.

    Designed to be called once per tick by PowerLawBTCStrategy.on_tick().
    The tick interval should be set to config.interval_seconds (default 3600).
    """

    def __init__(self, proxy, config: Optional[PowerLawConfig] = None):
        """
        Args:
            proxy:  DirectHLProxy or DirectMockProxy (already connected).
            config: Bot configuration. If None, loads from env.
        """
        self.config = config or get_power_law_config()
        self.adapter = HLPowerLawAdapter(proxy, max_leverage=self.config.max_leverage)

        self.last_check: Optional[datetime] = None
        self.last_rebalance: Optional[datetime] = None
        self.trades_executed: int = 0
        self._activity_log: list = []
        self._max_log_entries: int = 25

        # Cached values for status queries
        self._last_signal: dict = {}
        self._last_portfolio: dict = {}

        # Debounce: skip re-logging identical simulated trades
        self._last_simulated_direction: Optional[str] = None
        self._last_simulated_usd: float = 0.0

        self._load_state()

        log.info("=" * 50)
        log.info("Power Law Rebalancer Bot initialised")
        log.info("  Model:      %s", self.config.model)
        log.info("  Instrument: %s", self.config.instrument)
        log.info("  Max lev:    %sx", self.config.max_leverage)
        log.info("  Threshold:  %s%%", self.config.threshold_percent)
        log.info("  Interval:   %ss", self.config.interval_seconds)
        log.info("  Simulate:   %s", self.config.simulate)
        log.info("=" * 50)

    # ------------------------------------------------------------------
    # Signal
    # ------------------------------------------------------------------

    def get_signal(self) -> Optional[dict]:
        """
        Get today's heartbeat model signal.

        Returns dict with allocation_pct, floor, ceiling, model_price,
        position_in_band_pct, valuation, stance, tagline, etc.
        """
        try:
            from plugins.power_law.heartbeat_model import get_daily_signal

            btc_price = self.adapter.get_btc_price()
            if btc_price <= 0:
                log.error("[PowerLaw] Cannot get BTC price for signal")
                return None

            return get_daily_signal(datetime.now(), btc_price)

        except Exception as e:
            log.error("[PowerLaw] Signal error: %s", e, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Main rebalance loop
    # ------------------------------------------------------------------

    def check_and_rebalance(self) -> dict:
        """
        Main iteration: fetch state → get signal → rebalance if needed.

        Returns dict with result details (success, traded, signal, etc.).
        Always saves state at the end.
        """
        self.last_check = datetime.now()
        log.info("-" * 40)
        log.info("Checking portfolio...")

        try:
            state: Optional[PortfolioState] = self.adapter.get_portfolio_state()
            if not state:
                log.error("  Failed to get portfolio state")
                return {"success": False, "error": "Could not fetch portfolio"}

            # Cache for status display
            self._last_portfolio = {
                "btc_position": state.btc_position,
                "usdc_balance": state.usdc_balance,
                "total_value_usd": state.total_value_usd,
                "btc_percent": state.btc_percent,
                "btc_price_usd": state.btc_price_usd,
            }

            log.info(
                "  Portfolio: $%.2f | BTC pos: %.6f | Effective alloc: %.1f%%",
                state.total_value_usd, state.btc_position, state.btc_percent,
            )

            # Minimum portfolio check
            if state.total_value_usd < self.config.min_portfolio_usd:
                reason = (
                    f"Portfolio ${state.total_value_usd:.2f} below minimum "
                    f"${self.config.min_portfolio_usd:.2f}"
                )
                log.warning("  %s", reason)
                return {
                    "success": False,
                    "error": reason,
                    "needs_funding": True,
                    "total_usd": state.total_value_usd,
                    "min_required": self.config.min_portfolio_usd,
                }

            signal = self.get_signal()
            if not signal:
                return {"success": False, "error": "Could not fetch power law signal"}

            self._last_signal = signal

            log.info("  Model price:   $%s", f"{signal['model_price']:,.2f}")
            log.info(
                "  Target alloc:  %.1f%% BTC | Current: %.1f%% BTC",
                signal["allocation_pct"], state.btc_percent,
            )
            log.info("  Stance: %s — %s", signal["stance"], signal["tagline"])

            target_btc_pct = signal["allocation_pct"]
            deviation = state.btc_percent - target_btc_pct
            log.info(
                "  Deviation: %.1f%% (threshold: %.1f%%)",
                abs(deviation), self.config.threshold_percent,
            )

            # Within threshold — no trade
            if abs(deviation) < self.config.threshold_percent:
                reason = f"Deviation {abs(deviation):.1f}% < {self.config.threshold_percent}%"
                log.info("  No trade needed: %s", reason)
                self._log("skip", reason)
                return {
                    "success": True,
                    "reason": reason,
                    "traded": False,
                    "signal": signal,
                    "current_btc_pct": state.btc_percent,
                    "target_btc_pct": target_btc_pct,
                }

            # Calculate trade size in USD notional
            direction = "buy_btc" if deviation < 0 else "sell_btc"

            # Target notional for BTC leg = target_pct / 100 * max_leverage * account_value
            target_notional = (target_btc_pct / 100) * state.max_leverage * state.total_value_usd
            current_notional = max(0.0, state.btc_position) * state.btc_price_usd
            trade_usd = abs(target_notional - current_notional)

            if trade_usd < self.config.min_trade_usd:
                reason = f"Trade too small (${trade_usd:.2f} < ${self.config.min_trade_usd:.2f})"
                log.info("  %s", reason)
                self._log("skip", reason)
                return {"success": True, "reason": reason, "traded": False}

            # Simulated debounce
            if self.config.simulate and self._last_simulated_direction == direction:
                if self._last_simulated_usd > 0:
                    drift = abs(trade_usd - self._last_simulated_usd) / self._last_simulated_usd
                    if drift < 0.05:
                        reason = f"Simulated {direction} ${trade_usd:.2f} unchanged (<5% drift)"
                        log.info("  %s", reason)
                        return {"success": True, "reason": reason, "traded": False}

            log.info("  Rebalancing: %s $%.2f", direction, trade_usd)

            result = self.adapter.execute_rebalance(
                direction=direction,
                amount_usd=trade_usd,
                btc_price=state.btc_price_usd,
                simulate=self.config.simulate,
            )

            if result.get("success"):
                if self.config.simulate:
                    self._last_simulated_direction = direction
                    self._last_simulated_usd = trade_usd
                else:
                    self._last_simulated_direction = None

                self.trades_executed += 1
                self.last_rebalance = datetime.now()
                sim_tag = " (SIMULATED)" if result.get("simulated") else ""
                log.info("  Rebalance executed%s", sim_tag)

                self._log(
                    "trade",
                    f"{direction} ${trade_usd:.2f}{sim_tag}",
                    {
                        "direction": direction,
                        "amount_usd": trade_usd,
                        "simulated": result.get("simulated", False),
                        "fill_price": result.get("fill_price"),
                    },
                )
            else:
                log.error("  Rebalance failed: %s", result.get("error"))
                self._log("error", f"Trade failed: {result.get('error')}")

            result.update({
                "signal": signal,
                "current_btc_pct": state.btc_percent,
                "target_btc_pct": target_btc_pct,
                "deviation": deviation,
                "traded": result.get("success", False),
            })
            return result

        finally:
            self._save_state()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return comprehensive bot status (non-blocking, uses cached values)."""
        return {
            "running": True,
            "simulate": self.config.simulate,
            "model": self.config.model,
            "instrument": self.config.instrument,
            "max_leverage": self.config.max_leverage,
            "threshold": self.config.threshold_percent,
            "interval_seconds": self.config.interval_seconds,
            "trades_executed": self.trades_executed,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_rebalance": self.last_rebalance.isoformat() if self.last_rebalance else None,
            "signal": self._last_signal,
            "portfolio": self._last_portfolio,
            "activity_log": self._activity_log[-10:],
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load persisted state from file."""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE) as f:
                    data = json.load(f)
                self.trades_executed = data.get("trades_executed", 0)
                self._activity_log = data.get("activity_log", [])
                self._last_portfolio = data.get("last_portfolio", {})
                self._last_signal = data.get("last_signal", {})
                if data.get("last_rebalance"):
                    self.last_rebalance = datetime.fromisoformat(data["last_rebalance"])
        except Exception:
            pass  # Fresh start if state is missing or corrupt

    def _save_state(self) -> None:
        """Persist state to disk for restart continuity."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(
                    {
                        "trades_executed": self.trades_executed,
                        "last_rebalance": (
                            self.last_rebalance.isoformat() if self.last_rebalance else None
                        ),
                        "activity_log": self._activity_log[-self._max_log_entries:],
                        "last_portfolio": self._last_portfolio,
                        "last_signal": self._last_signal,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            log.warning("[PowerLaw] Could not save state: %s", e)

    def _log(self, activity_type: str, message: str, data: Optional[dict] = None) -> None:
        """Append an activity log entry."""
        entry: dict = {
            "timestamp": datetime.now().isoformat(),
            "type": activity_type,
            "message": message,
        }
        if data:
            entry["data"] = data
        self._activity_log.append(entry)
        if len(self._activity_log) > self._max_log_entries:
            self._activity_log = self._activity_log[-self._max_log_entries:]
