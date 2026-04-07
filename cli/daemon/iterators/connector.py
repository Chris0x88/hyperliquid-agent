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
        #
        # BUG-FIX 2026-04-08: the original code read
        # ``account_state["marginSummary"]["accountValue"]`` which is the
        # raw HL clearinghouseState shape, but ``DirectHLProxy.get_account_state``
        # (the production adapter) flattens that into a top-level
        # ``account_value`` key — there is no ``marginSummary`` key in the
        # returned dict. The lookup silently returned ``"0"`` and
        # ``ctx.balances["USDC"]`` was always ``Decimal("0")``, which made
        # ``execution_engine._process_market`` bail at the
        # ``account_equity <= 0`` early-return *before* the H2 authority
        # gate ever fired. This branch supports both shapes (DirectHLProxy
        # flat keys preferred, raw HL nested fallback) so the H2 gate is
        # actually reachable.
        try:
            account_state = self._adapter.get_account_state()
            if account_state:
                equity = account_state.get("account_value")
                if equity is None:
                    # Fall back to raw HL clearinghouseState shape
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

        # Fetch positions (native HL perps)
        #
        # BUG-FIX 2026-04-08: the original branch only called
        # ``self._adapter.get_positions()``, which does not exist on
        # ``DirectHLProxy`` (the production adapter). The hasattr check
        # silently fell through, so ``ctx.positions`` never included any
        # native HL positions — every downstream iterator that reads
        # ``ctx.positions`` (exchange_protection, guard, liquidation_monitor,
        # protection_audit, apex_advisor, catalyst_deleverage, autoresearch)
        # saw zero native positions regardless of what was on the exchange.
        # The fallback path below uses ``get_account_state()["positions"]``
        # (raw HL ``assetPositions`` list) and builds proper ``Position``
        # objects so the H1-H4 authority gates actually have something to
        # gate on.
        try:
            if hasattr(self._adapter, 'get_positions'):
                ctx.positions = self._adapter.get_positions()
            elif hasattr(self._adapter, 'get_account_state'):
                from parent.position_tracker import Position
                from decimal import Decimal as _D
                state = self._adapter.get_account_state()
                native_positions = state.get("positions", []) or []
                built: list[Position] = []
                for ap in native_positions:
                    p = ap.get("position", ap) if isinstance(ap, dict) else {}
                    coin = p.get("coin", "")
                    szi = float(p.get("szi", 0))
                    if not coin or szi == 0:
                        continue
                    built.append(Position(
                        instrument=coin,
                        net_qty=_D(str(szi)),
                        avg_entry_price=_D(str(p.get("entryPx", 0))),
                        liquidation_price=_D(str(p.get("liquidationPx") or 0)),
                        leverage=_D(str((p.get("leverage") or {}).get("value", 1))),
                    ))
                ctx.positions = built
        except Exception as e:
            log.warning("Failed to fetch native positions: %s", e)

        # Merge xyz dex positions (BRENTOIL and other commodity perps)
        try:
            if hasattr(self._adapter, 'get_xyz_state'):
                xyz = self._adapter.get_xyz_state()
                if xyz:
                    from parent.position_tracker import Position
                    from decimal import Decimal as _D
                    for ap in xyz.get("assetPositions", []):
                        p = ap.get("position", ap)
                        coin = p.get("coin", "")
                        szi = float(p.get("szi", 0))
                        if szi == 0:
                            continue
                        # coin is already "xyz:BRENTOIL" from API — don't double-prefix
                        inst = coin if coin.startswith("xyz:") else f"xyz:{coin}"
                        entry_px = float(p.get("entryPx", 0))
                        liq_px = float(p.get("liquidationPx") or 0)
                        leverage_val = float((p.get("leverage") or {}).get("value", 1))

                        # Find or create position entry in ctx.positions
                        existing = next((x for x in ctx.positions if x.instrument == inst), None)
                        if existing is None:
                            existing = Position(instrument=inst)
                            ctx.positions.append(existing)

                        existing.net_qty = _D(str(szi))
                        existing.avg_entry_price = _D(str(entry_px))
                        existing.liquidation_price = _D(str(liq_px))
                        existing.leverage = _D(str(leverage_val))

                    log.debug("Merged %d xyz positions into ctx.positions",
                              len([ap for ap in xyz.get("assetPositions", [])
                                   if float(ap.get("position", ap).get("szi", 0)) != 0]))
        except Exception as e:
            log.warning("Failed to merge xyz positions: %s", e)

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
