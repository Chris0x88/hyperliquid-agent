"""Regression test for the connector.py native-position fallback.

BUG-FIX 2026-04-08: ``connector.tick`` previously only populated
``ctx.positions`` via ``self._adapter.get_positions()``. ``DirectHLProxy``
(the production adapter) does not expose that method, so the hasattr check
silently fell through and native HL perp positions were invisible to every
downstream iterator (exchange_protection, guard, liquidation_monitor,
protection_audit, apex_advisor, catalyst_deleverage, autoresearch).

These tests lock in the fallback path that builds ``Position`` objects from
``get_account_state()["positions"]`` — the raw HL ``assetPositions`` list —
and confirm the H1-H4 authority gates downstream actually see a non-empty
input in production.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from cli.daemon.context import TickContext
from cli.daemon.iterators.connector import ConnectorIterator


class _FakeDirectAdapter:
    """Shape-matches ``DirectHLProxy`` for the parts connector.tick touches."""

    def __init__(self, native_positions: List[Dict[str, Any]],
                 xyz_state: Dict[str, Any] | None = None):
        self._native_positions = native_positions
        self._xyz_state = xyz_state or {}

    # connector.tick probes this first
    def get_account_state(self) -> Dict[str, Any]:
        return {
            "account_value": 500.0,
            "total_margin": 10.0,
            "withdrawable": 480.0,
            "positions": self._native_positions,
            "spot_balances": [],
        }

    # connector.tick merges xyz afterward via this call
    def get_xyz_state(self) -> Dict[str, Any]:
        return self._xyz_state

    # connector.tick calls get_snapshot per roster instrument — not relevant
    # for the positions path, but we stub it so the call does not blow up.
    def get_snapshot(self, instrument: str):
        class _S:
            mid_price = 100.0
        return _S()

    def get_all_markets(self):
        return []


def _raw_hl_position(coin: str, szi: float, entry: float,
                     liq: float | None = None, lev: int = 3) -> Dict[str, Any]:
    """Produce an assetPositions entry in the exact shape HL returns."""
    return {
        "type": "oneWay",
        "position": {
            "coin": coin,
            "szi": str(szi),
            "entryPx": str(entry),
            "positionValue": str(abs(szi) * entry),
            "unrealizedPnl": "0.0",
            "returnOnEquity": "0.0",
            "liquidationPx": None if liq is None else str(liq),
            "marginUsed": str(abs(szi) * entry / lev),
            "maxLeverage": 40,
            "leverage": {"type": "cross", "value": lev},
            "cumFunding": {"allTime": "0.0", "sinceOpen": "0.0", "sinceChange": "0.0"},
        },
    }


class TestConnectorNativePositions:

    def test_single_long_native_position_is_built(self):
        """The fallback builds one Position object from a single raw HL entry."""
        adapter = _FakeDirectAdapter(
            native_positions=[_raw_hl_position("BTC", 0.00015, 67858.0, lev=3)],
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        assert len(ctx.positions) == 1
        pos = ctx.positions[0]
        assert pos.instrument == "BTC"
        assert pos.net_qty == Decimal("0.00015")
        assert pos.avg_entry_price == Decimal("67858.0")
        assert pos.leverage == Decimal("3")

    def test_short_native_position_preserves_sign(self):
        adapter = _FakeDirectAdapter(
            native_positions=[_raw_hl_position("ETH", -2.5, 3200.0, liq=3900.0, lev=5)],
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        assert len(ctx.positions) == 1
        pos = ctx.positions[0]
        assert pos.instrument == "ETH"
        assert pos.net_qty == Decimal("-2.5")  # short preserved
        assert pos.liquidation_price == Decimal("3900.0")

    def test_zero_qty_position_is_skipped(self):
        """HL returns closed positions with szi=0 — the fallback drops them."""
        adapter = _FakeDirectAdapter(
            native_positions=[
                _raw_hl_position("BTC", 0.0, 67000.0),
                _raw_hl_position("ETH", 1.5, 3200.0),
            ],
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        assert len(ctx.positions) == 1
        assert ctx.positions[0].instrument == "ETH"

    def test_empty_native_positions_yields_empty_list(self):
        adapter = _FakeDirectAdapter(native_positions=[])
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        assert ctx.positions == []

    def test_liquidation_price_null_is_zero(self):
        """Unified-account positions have liquidationPx=None; coerce to 0."""
        adapter = _FakeDirectAdapter(
            native_positions=[_raw_hl_position("BTC", 0.001, 68000.0, liq=None)],
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        assert len(ctx.positions) == 1
        assert ctx.positions[0].liquidation_price == Decimal("0")

    def test_native_and_xyz_positions_both_populated(self):
        """Fix does not break the existing xyz merge path."""
        adapter = _FakeDirectAdapter(
            native_positions=[_raw_hl_position("BTC", 0.0002, 68000.0)],
            xyz_state={
                "assetPositions": [{
                    "position": {
                        "coin": "xyz:BRENTOIL",
                        "szi": "0.5",
                        "entryPx": "85.0",
                        "liquidationPx": "75.0",
                        "leverage": {"value": 2},
                    }
                }],
                "marginSummary": {"accountValue": "50"},
            },
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        instruments = {p.instrument for p in ctx.positions}
        assert "BTC" in instruments
        assert "xyz:BRENTOIL" in instruments
        assert len(ctx.positions) == 2

    def test_adapter_without_get_account_state_leaves_positions_untouched(self):
        """Guards against future adapters that expose neither method."""
        class _MinimalAdapter:
            def get_snapshot(self, instrument: str):
                class _S:
                    mid_price = 100.0
                return _S()
            def get_all_markets(self):
                return []

        it = ConnectorIterator(adapter=_MinimalAdapter())
        ctx = TickContext()
        # Pre-populate to prove the fallback does not clobber it
        from parent.position_tracker import Position
        ctx.positions = [Position(instrument="PRESET", net_qty=Decimal("1"))]
        it.tick(ctx)

        # With neither get_positions nor get_account_state, ctx.positions
        # should be left as-is (the try/except must not clear it)
        assert len(ctx.positions) == 1
        assert ctx.positions[0].instrument == "PRESET"

    def test_get_positions_path_still_works_when_adapter_provides_it(self):
        """Backward-compat: if a future adapter provides get_positions(), use it."""
        from parent.position_tracker import Position

        class _LegacyAdapter:
            def get_positions(self):
                return [Position(instrument="LEGACY", net_qty=Decimal("2.5"))]
            def get_snapshot(self, instrument: str):
                class _S:
                    mid_price = 100.0
                return _S()
            def get_all_markets(self):
                return []

        it = ConnectorIterator(adapter=_LegacyAdapter())
        ctx = TickContext()
        it.tick(ctx)

        assert len(ctx.positions) == 1
        assert ctx.positions[0].instrument == "LEGACY"
        assert ctx.positions[0].net_qty == Decimal("2.5")


class TestConnectorBalancesUSDC:
    """Regression tests for bug #3 — account_state shape mismatch.

    BUG-FIX 2026-04-08: connector.tick read
    ``account_state["marginSummary"]["accountValue"]`` (raw HL shape) but
    DirectHLProxy returns a flattened dict with ``account_value`` at the
    top level. The lookup silently returned "0" and execution_engine
    bailed at the ``account_equity <= 0`` early-return *before* the H2
    authority gate fired.
    """

    def test_directhlproxy_flat_shape_populates_usdc_balance(self):
        """DirectHLProxy's flat ``account_value`` key is read correctly."""
        adapter = _FakeDirectAdapter(native_positions=[])
        # _FakeDirectAdapter.get_account_state returns {"account_value": 500.0, ...}
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        assert ctx.balances["USDC"] == Decimal("500.0")

    def test_raw_hl_shape_fallback_still_works(self):
        """If a future adapter returns the raw HL shape, the fallback reads it."""

        class _RawHLAdapter:
            def get_account_state(self):
                return {
                    "marginSummary": {"accountValue": "1234.56"},
                    "positions": [],
                }
            def get_snapshot(self, instrument):
                class _S:
                    mid_price = 100.0
                return _S()
            def get_all_markets(self):
                return []

        it = ConnectorIterator(adapter=_RawHLAdapter())
        ctx = TickContext()
        it.tick(ctx)

        assert ctx.balances["USDC"] == Decimal("1234.56")

    def test_missing_both_shapes_yields_zero(self):
        """If neither shape is present, ctx.balances['USDC'] becomes 0."""

        class _EmptyAdapter:
            def get_account_state(self):
                return {"positions": []}
            def get_snapshot(self, instrument):
                class _S:
                    mid_price = 100.0
                return _S()
            def get_all_markets(self):
                return []

        it = ConnectorIterator(adapter=_EmptyAdapter())
        ctx = TickContext()
        it.tick(ctx)

        assert ctx.balances["USDC"] == Decimal("0")
