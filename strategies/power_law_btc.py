"""
Power Law BTC Strategy — Hyperliquid BTC-PERP
==============================================

Wraps the Power Law Heartbeat Model bot as a BaseStrategy so it can be
launched with:

    hl run power_law_btc -i BTC-PERP --tick 3600

How it works
------------
The heartbeat model outputs an allocation % (0–100 %) for each day
based on where BTC price sits relative to its power-law floor and cycle
ceiling.  We map that to a target leverage on BTC-PERP:

    target_leverage = (allocation_pct / 100) × max_leverage

on_tick() is called every `tick` seconds (set to 3600 for hourly).
The strategy delegates to PowerLawBot.check_and_rebalance() and converts
the result into zero StrategyDecisions (orders are placed directly by the
bot via DirectHLProxy, not through the engine's order queue).

Env vars
--------
  POWER_LAW_MAX_LEVERAGE     default 40
  POWER_LAW_THRESHOLD_PERCENT default 15
  POWER_LAW_INTERVAL_SECONDS  default 3600
  POWER_LAW_MIN_TRADE_USD     default 10
  POWER_LAW_MIN_PORTFOLIO_USD default 100
  POWER_LAW_SIMULATE          default true  (set false for live)
"""
from __future__ import annotations

import logging
from typing import List, Optional

from sdk.strategy_sdk.base import BaseStrategy, StrategyContext
from common.models import MarketSnapshot, StrategyDecision

log = logging.getLogger("strategy.power_law_btc")


class PowerLawBTCStrategy(BaseStrategy):
    """
    Bitcoin Heartbeat Model rebalancer for Hyperliquid BTC-PERP.

    Tick interval should be set to 3600 (1 hour) to match the model's
    daily/hourly rebalance cadence:

        hl run power_law_btc --tick 3600
    """

    def __init__(
        self,
        max_leverage: float = 40.0,
        threshold_percent: float = 15.0,
        simulate: bool = True,
        **kwargs,
    ):
        super().__init__(strategy_id="power_law_btc")
        self._max_leverage = max_leverage
        self._threshold_percent = threshold_percent
        self._simulate = simulate
        self._bot = None          # lazy-init on first tick (needs proxy)
        self._proxy = None        # set by on_tick via context.meta
        self._tick_count = 0

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    def on_tick(
        self,
        snapshot: MarketSnapshot,
        context: Optional[StrategyContext] = None,
    ) -> List[StrategyDecision]:
        """
        Called every tick by the engine.

        Initialises the PowerLawBot on the first call (needs the proxy
        from context.meta), then delegates to check_and_rebalance().
        Returns an empty list — all orders are placed inside the bot.
        """
        self._tick_count += 1

        # Grab proxy from context on first tick
        if self._bot is None:
            proxy = self._get_proxy(context)
            if proxy is None:
                log.error("[PowerLawBTC] No proxy available — cannot initialise bot")
                return []
            self._init_bot(proxy)

        if self._bot is None:
            return []

        try:
            result = self._bot.check_and_rebalance()
            if result.get("traded"):
                sim = " (simulated)" if result.get("simulated") else ""
                log.info(
                    "[PowerLawBTC] Rebalanced%s — %s $%.2f | target: %.1f%% | current: %.1f%%",
                    sim,
                    result.get("direction", ""),
                    result.get("amount_usd", 0),
                    result.get("target_btc_pct", 0),
                    result.get("current_btc_pct", 0),
                )
            elif result.get("reason"):
                log.debug("[PowerLawBTC] No trade: %s", result["reason"])
        except Exception as e:
            log.error("[PowerLawBTC] check_and_rebalance error: %s", e, exc_info=True)

        # Orders are placed directly inside the bot — return empty list
        return []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_proxy(self, context: Optional[StrategyContext]):
        """Extract DirectHLProxy from context.meta, or fall back to env."""
        if context and context.meta:
            proxy = context.meta.get("proxy") or context.meta.get("hl_proxy")
            if proxy is not None:
                return proxy

        # Fall back: build our own proxy from env (standalone mode)
        try:
            import os
            from common.account_resolver import resolve_private_key, resolve_vault_wallet
            from exchange.hl_proxy import HLProxy
            from cli.hl_adapter import DirectHLProxy, DirectMockProxy

            if os.environ.get("HL_MOCK", "false").lower() == "true":
                log.info("[PowerLawBTC] Using mock proxy")
                return DirectMockProxy()

            key = resolve_private_key(required=True)
            testnet = os.environ.get("HL_TESTNET", "true").lower() != "false"
            vault_address = resolve_vault_wallet(required=False)
            hl = HLProxy(private_key=key, testnet=testnet, vault_address=vault_address or None)
            return DirectHLProxy(hl)
        except Exception as e:
            log.error("[PowerLawBTC] Could not build proxy: %s", e)
            return None

    def _init_bot(self, proxy) -> None:
        """Initialise PowerLawBot with the resolved proxy."""
        try:
            from plugins.power_law.bot import PowerLawBot
            from plugins.power_law.config import PowerLawConfig

            cfg = PowerLawConfig(
                max_leverage=self._max_leverage,
                threshold_percent=self._threshold_percent,
                simulate=self._simulate,
            )
            self._bot = PowerLawBot(proxy=proxy, config=cfg)
            log.info(
                "[PowerLawBTC] Bot ready — max_leverage=%.0fx simulate=%s threshold=%.0f%%",
                cfg.max_leverage, cfg.simulate, cfg.threshold_percent,
            )
        except Exception as e:
            log.error("[PowerLawBTC] Failed to init bot: %s", e, exc_info=True)
            self._bot = None

    def get_status(self) -> dict:
        """Return bot status (used by hl status command)."""
        if self._bot:
            return self._bot.get_status()
        return {"running": False, "ticks": self._tick_count}
