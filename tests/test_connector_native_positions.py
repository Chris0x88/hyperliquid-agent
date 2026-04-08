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
                 xyz_state: Dict[str, Any] | None = None,
                 snapshot_prices: Dict[str, float] | None = None,
                 snapshot_raises: set | None = None):
        self._native_positions = native_positions
        self._xyz_state = xyz_state or {}
        # Per-instrument override: key = instrument string, value = mid_price.
        # Falls back to 100.0 for any instrument not listed.
        self._snapshot_prices = snapshot_prices or {}
        # Set of instrument strings for which get_snapshot should raise.
        self._snapshot_raises = snapshot_raises or set()

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

    # connector.tick calls get_snapshot per roster instrument and per open
    # position instrument (after the BUG-FIX 2026-04-08 position-price loop).
    def get_snapshot(self, instrument: str):
        if instrument in self._snapshot_raises:
            raise RuntimeError(f"simulated snapshot failure for {instrument}")
        price = self._snapshot_prices.get(instrument, 100.0)

        class _S:
            pass

        s = _S()
        s.mid_price = price
        return s

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


class TestConnectorTotalEquity:
    """Regression tests for BUG-FIX 2026-04-08 (equity-reporting).

    ``ctx.balances["USDC"]`` has always been native-perps-only because
    ``connector.tick`` only reads from the native HL ``get_account_state()``
    endpoint. Telegram alerts and the journal trade record were treating that
    value as "total equity" and reporting numbers that did not match
    ``/status``, which has always summed native + xyz + spot. The fix adds a
    parallel ``ctx.total_equity`` field that the connector populates with
    the same three-source sum so alerts can report the same number.

    These tests lock in:
    - native + spot is computed even when xyz is empty
    - xyz margin is added to total when get_xyz_state() returns it
    - the existing ``ctx.balances["USDC"]`` semantic is unchanged (still
      native-only) so execution_engine sizing math is not disturbed
    """

    def test_total_equity_native_only(self):
        """No xyz, no spot — total_equity equals native account_value."""
        adapter = _FakeDirectAdapter(native_positions=[])
        # _FakeDirectAdapter returns account_value=500.0, no spot
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        assert ctx.total_equity == 500.0
        # ctx.balances["USDC"] semantic UNCHANGED — still native-only
        assert ctx.balances["USDC"] == Decimal("500.0")

    def test_total_equity_native_plus_spot(self):
        """spot_usdc field on the account_state is added to total."""

        class _NativeAndSpotAdapter:
            def get_account_state(self):
                return {
                    "account_value": 500.0,
                    "spot_usdc": 75.25,
                    "positions": [],
                }
            def get_snapshot(self, instrument):
                class _S:
                    mid_price = 100.0
                return _S()
            def get_all_markets(self):
                return []

        it = ConnectorIterator(adapter=_NativeAndSpotAdapter())
        ctx = TickContext()
        it.tick(ctx)

        assert ctx.total_equity == 575.25
        # The legacy native-only field is preserved
        assert ctx.balances["USDC"] == Decimal("500.0")

    def test_total_equity_native_plus_xyz_plus_spot(self):
        """All three sources sum into total_equity. This is the prod scenario."""

        class _FullAdapter:
            def get_account_state(self):
                return {
                    "account_value": 500.0,
                    "spot_usdc": 25.0,
                    "positions": [],
                }
            def get_xyz_state(self):
                return {
                    "marginSummary": {"accountValue": "120.50"},
                    "assetPositions": [],
                }
            def get_snapshot(self, instrument):
                class _S:
                    mid_price = 100.0
                return _S()
            def get_all_markets(self):
                return []

        it = ConnectorIterator(adapter=_FullAdapter())
        ctx = TickContext()
        it.tick(ctx)

        # 500 (native) + 120.50 (xyz) + 25 (spot) = 645.50 — must match
        # what /status would report
        assert ctx.total_equity == 645.50
        # Legacy field still native-only — execution_engine sizing untouched
        assert ctx.balances["USDC"] == Decimal("500.0")

    def test_total_equity_xyz_missing_margin_summary_is_safe(self):
        """xyz state present but marginSummary absent — total = native only."""
        adapter = _FakeDirectAdapter(
            native_positions=[],
            xyz_state={"assetPositions": []},  # no marginSummary
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        # Should not crash; xyz contribution is 0
        assert ctx.total_equity == 500.0

    def test_total_equity_starts_at_zero_when_account_state_unavailable(self):
        """Adapter without get_account_state — total_equity stays at 0.

        Consumers (TelegramIterator etc.) treat 0 as 'not yet populated' and
        fall back to ``ctx.balances["USDC"]``.
        """

        class _NoAccountStateAdapter:
            def get_snapshot(self, instrument):
                class _S:
                    mid_price = 100.0
                return _S()
            def get_all_markets(self):
                return []

        it = ConnectorIterator(adapter=_NoAccountStateAdapter())
        ctx = TickContext()
        it.tick(ctx)

        assert ctx.total_equity == 0.0


class TestConnectorPositionPrices:
    """Regression tests for BUG-FIX 2026-04-08 — position-instrument price gap.

    The roster price loop only fetches prices for instruments in
    ctx.active_strategies.  If a position exists for a coin not in the roster
    (e.g. BTC when the roster uses BTC-PERP), ctx.prices[pos.instrument] was
    never populated and protection_audit / liquidation_monitor saw mark=0.0000.

    The second price loop (after the xyz merge block) closes this gap by
    fetching and storing a price for every open position instrument not already
    covered by the roster loop.
    """

    def test_position_only_instrument_gets_mark_price(self):
        """Native BTC position (not in roster) gets ctx.prices["BTC"] populated."""
        adapter = _FakeDirectAdapter(
            native_positions=[_raw_hl_position("BTC", 0.00015, 67858.0)],
            snapshot_prices={"BTC": 68500.0},
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        assert "BTC" in ctx.prices, "ctx.prices must contain the position coin key"
        assert ctx.prices["BTC"] == Decimal("68500.0")

    def test_xyz_position_gets_mark_price(self):
        """xyz:BRENTOIL position (not in roster) gets ctx.prices['xyz:BRENTOIL'] populated."""
        adapter = _FakeDirectAdapter(
            native_positions=[],
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
            },
            snapshot_prices={"xyz:BRENTOIL": 86.25},
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        assert "xyz:BRENTOIL" in ctx.prices, "ctx.prices must contain the xyz position coin key"
        assert ctx.prices["xyz:BRENTOIL"] == Decimal("86.25")

    def test_roster_covered_instrument_is_not_double_fetched(self):
        """If a position instrument is already in ctx.prices the second loop skips it.

        We simulate the roster having pre-populated ctx.prices["BTC"] = 67100,
        then give the adapter a BTC position whose snapshot would return 68000.
        The second loop must NOT overwrite the already-present price — the key
        already exists so the ``if _pos.instrument in ctx.prices: continue``
        guard fires and the adapter is NOT called a second time.

        A separate BTC-only native position (ETH) that has NO pre-existing price
        DOES get fetched, confirming the deduplication is per-key.
        """
        adapter = _FakeDirectAdapter(
            native_positions=[
                _raw_hl_position("BTC", 0.001, 67000.0),
                _raw_hl_position("ETH", 1.0, 3200.0),
            ],
            snapshot_prices={"BTC": 68000.0, "ETH": 3300.0},
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        # Pre-populate BTC as if the roster loop had already set it
        ctx.prices["BTC"] = Decimal("67100.0")
        it.tick(ctx)

        # BTC price must NOT be overwritten — the pre-existing value survives
        assert ctx.prices["BTC"] == Decimal("67100.0"), (
            "position loop must not overwrite a price already set by the roster loop"
        )
        # ETH (no pre-existing price) must be fetched by the second loop
        assert ctx.prices["ETH"] == Decimal("3300.0")

    def test_snapshot_failure_is_non_fatal(self):
        """If get_snapshot raises for one position, the loop logs and continues."""
        adapter = _FakeDirectAdapter(
            native_positions=[
                _raw_hl_position("BTC", 0.001, 67000.0),
                _raw_hl_position("ETH", 1.5, 3200.0),
            ],
            # BTC snapshot blows up; ETH snapshot returns normally
            snapshot_raises={"BTC"},
            snapshot_prices={"ETH": 3250.0},
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        # ETH must have a price even though BTC's fetch failed
        assert "ETH" in ctx.prices
        assert ctx.prices["ETH"] == Decimal("3250.0")
        # BTC must NOT be in ctx.prices (the failed fetch must not leave a zero)
        assert "BTC" not in ctx.prices

    def test_zero_qty_position_does_not_trigger_price_fetch(self):
        """Closed positions (szi=0) are dropped by the build loop and never reach
        the price loop — so no snapshot call is made for them."""
        adapter = _FakeDirectAdapter(
            native_positions=[
                _raw_hl_position("BTC", 0.0, 67000.0),   # closed — must be filtered
                _raw_hl_position("ETH", 1.0, 3200.0),    # open — must get a price
            ],
            snapshot_prices={"ETH": 3300.0},
        )
        it = ConnectorIterator(adapter=adapter)
        ctx = TickContext()
        it.tick(ctx)

        # Only the open ETH position should have propagated
        assert len(ctx.positions) == 1
        assert ctx.positions[0].instrument == "ETH"
        # ETH gets a price; BTC (closed) gets none
        assert "ETH" in ctx.prices
        assert "BTC" not in ctx.prices
