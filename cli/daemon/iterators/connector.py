"""ConnectorIterator — fetches market data from HL adapter into TickContext."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from cli.daemon.context import Alert, TickContext

log = logging.getLogger("daemon.connector")


class ConnectorIterator:
    name = "connector"

    def __init__(self, adapter: Any = None):
        self._adapter = adapter

    def on_start(self, ctx: TickContext) -> None:
        if self._adapter is None:
            log.info("ConnectorIterator starting in mock mode")
            return
        # Validate connection
        try:
            self._adapter.get_snapshot("ETH-PERP")
            log.info("ConnectorIterator connected to HL")
        except Exception as e:
            raise RuntimeError(f"Cannot connect to HL: {e}") from e

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        if self._adapter is None:
            self._mock_tick(ctx)
            return

        # Fetch balances
        try:
            account_state = self._adapter.get_account_state()
            if account_state:
                equity = account_state.get("marginSummary", {}).get("accountValue", "0")
                ctx.balances["USDC"] = Decimal(str(equity))
        except Exception as e:
            log.warning("Failed to fetch account state: %s", e)

        # Fetch prices + positions for each instrument in the roster
        instruments = set()
        for slot in ctx.active_strategies.values():
            instruments.add(slot.instrument)

        for inst in instruments:
            try:
                snapshot = self._adapter.get_snapshot(inst)
                ctx.prices[inst] = Decimal(str(snapshot.mid_price))
            except Exception as e:
                log.warning("Failed to fetch snapshot for %s: %s", inst, e)

        # Fetch positions
        try:
            if hasattr(self._adapter, 'get_positions'):
                ctx.positions = self._adapter.get_positions()
        except Exception as e:
            log.warning("Failed to fetch positions: %s", e)

        # Fetch all markets (for radar/pulse)
        try:
            if hasattr(self._adapter, 'get_all_markets'):
                ctx.all_markets = self._adapter.get_all_markets()
        except Exception as e:
            log.debug("Failed to fetch all markets: %s", e)

        # Fetch candles for strategies that need them
        for slot in ctx.active_strategies.values():
            for interval in slot.data_reqs.candle_intervals:
                for inst in slot.data_reqs.instruments:
                    key = inst
                    if key not in ctx.candles:
                        ctx.candles[key] = {}
                    if interval in ctx.candles[key]:
                        continue  # already fetched
                    try:
                        candles = self._adapter.get_candles(
                            coin=inst.replace("-PERP", ""),
                            interval=interval,
                            lookback_ms=slot.data_reqs.candle_lookback_ms,
                        )
                        ctx.candles[key][interval] = candles
                    except Exception as e:
                        log.debug("Failed to fetch %s candles for %s: %s", interval, inst, e)

    def _mock_tick(self, ctx: TickContext) -> None:
        """Populate mock data for testing."""
        import random
        ctx.balances["USDC"] = Decimal("10000.00")
        for slot in ctx.active_strategies.values():
            base_price = 95000.0 if "BTC" in slot.instrument else 3500.0
            price = base_price * (1 + random.uniform(-0.001, 0.001))
            ctx.prices[slot.instrument] = Decimal(str(round(price, 2)))
