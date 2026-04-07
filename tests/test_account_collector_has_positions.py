"""Regression test for the account_collector.py native position unwrap.

BUG-FIX 2026-04-08: the ``has_positions`` re-check in
``AccountCollectorIterator.tick`` previously passed the raw
``positions_native`` list straight through without unwrapping the outer
``{"type": "oneWay", "position": {...}}`` envelope that HL's
``clearinghouseState`` endpoint returns. As a result, ``p.get("szi", 0)``
always read 0 for native positions and ``has_positions`` collapsed to
False on every tick — triggering spurious ``Flat (no positions) —
resetting HWM`` log lines and resetting the high-water-mark to current
equity even while real native positions were open, which in turn masked
drawdown tracking.

These tests exercise ``_collect_and_inject`` end-to-end with a fake
adapter returning HL-shaped native positions, asserting that the
unwrap works and the HWM is preserved.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from cli.daemon.context import TickContext
from cli.daemon.iterators.account_collector import AccountCollectorIterator


class _FakeAdapter:
    """Shape-matches ``DirectHLProxy.get_account_state`` + ``get_xyz_state``."""

    def __init__(self, native_positions: List[Dict[str, Any]],
                 xyz_positions: List[Dict[str, Any]] | None = None,
                 perp_value: float = 10.0,
                 spot_usdc: float = 500.0):
        self._native_positions = native_positions
        self._xyz_positions = xyz_positions or []
        self._perp_value = perp_value
        self._spot_usdc = spot_usdc

    def get_account_state(self) -> Dict[str, Any]:
        return {
            "account_value": self._perp_value,
            "total_margin": 5.0,
            "withdrawable": self._spot_usdc,
            "spot_usdc": self._spot_usdc,
            "positions": self._native_positions,
            "spot_balances": [{"coin": "USDC", "total": str(self._spot_usdc)}],
        }

    def get_xyz_state(self) -> Dict[str, Any]:
        return {
            "assetPositions": self._xyz_positions,
            "marginSummary": {"accountValue": "0"},
        }


def _raw_hl_position(coin: str, szi: float, entry: float = 67000.0) -> Dict[str, Any]:
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
            "liquidationPx": None,
            "marginUsed": str(abs(szi) * entry / 3),
            "maxLeverage": 40,
            "leverage": {"type": "cross", "value": 3},
        },
    }


class TestHasPositionsUnwrap:

    def test_native_wrapped_position_is_recognized(self, tmp_path, caplog):
        """Raw HL-wrapped native position must count as 'has_positions=True'."""
        adapter = _FakeAdapter(
            native_positions=[_raw_hl_position("BTC", 0.00015, 67858.0)],
            perp_value=2.04,
            spot_usdc=424.58,
        )
        it = AccountCollectorIterator(adapter=adapter, snapshot_dir=str(tmp_path))
        it._high_water_mark = 500.0  # higher than total equity (426.62)

        ctx = TickContext()
        with caplog.at_level(logging.INFO, logger="daemon.account_collector"):
            it._collect_and_inject(ctx)

        # If the unwrap bug were still present, has_positions would be False
        # and the "Flat (no positions) — resetting HWM" line would fire,
        # pulling HWM from 500.0 down to ~426.62. The fix keeps HWM intact.
        assert "Flat (no positions)" not in caplog.text, \
            "has_positions re-check collapsed to False on wrapped native position"
        assert it._high_water_mark == 500.0, \
            f"HWM should not reset when a native position is open; got {it._high_water_mark}"

    def test_native_zero_szi_still_flat(self, tmp_path, caplog):
        """HL returns closed positions as wrapped entries with szi=0 — still flat."""
        adapter = _FakeAdapter(
            native_positions=[_raw_hl_position("BTC", 0.0, 67000.0)],
            perp_value=0.0,
            spot_usdc=500.0,
        )
        it = AccountCollectorIterator(adapter=adapter, snapshot_dir=str(tmp_path))
        it._high_water_mark = 600.0  # higher than equity so reset can trigger

        ctx = TickContext()
        with caplog.at_level(logging.INFO, logger="daemon.account_collector"):
            it._collect_and_inject(ctx)

        # With szi=0, has_positions should be False → HWM reset to current equity
        assert it._high_water_mark == 500.0, \
            "HWM should reset when all native positions have szi=0"

    def test_native_wrapped_plus_xyz_wrapped_both_counted(self, tmp_path, caplog):
        """Both native and xyz (each wrapped) must be unwrapped consistently."""
        adapter = _FakeAdapter(
            native_positions=[_raw_hl_position("ETH", 1.0, 3200.0)],
            xyz_positions=[{
                "position": {
                    "coin": "xyz:BRENTOIL",
                    "szi": "0.5",
                    "entryPx": "85.0",
                    "liquidationPx": "75.0",
                    "leverage": {"value": 2},
                }
            }],
            perp_value=100.0,
            spot_usdc=300.0,
        )
        it = AccountCollectorIterator(adapter=adapter, snapshot_dir=str(tmp_path))
        it._high_water_mark = 500.0

        ctx = TickContext()
        with caplog.at_level(logging.INFO, logger="daemon.account_collector"):
            it._collect_and_inject(ctx)

        assert "Flat (no positions)" not in caplog.text
        assert it._high_water_mark == 500.0

    def test_empty_snapshot_resets_hwm(self, tmp_path, caplog):
        """With no positions anywhere, HWM auto-resets to current equity."""
        adapter = _FakeAdapter(
            native_positions=[],
            xyz_positions=[],
            perp_value=0.0,
            spot_usdc=500.0,
        )
        it = AccountCollectorIterator(adapter=adapter, snapshot_dir=str(tmp_path))
        it._high_water_mark = 600.0

        ctx = TickContext()
        with caplog.at_level(logging.INFO, logger="daemon.account_collector"):
            it._collect_and_inject(ctx)

        # Flat → reset HWM to current equity
        assert it._high_water_mark == 500.0
        assert "Flat (no positions)" in caplog.text
