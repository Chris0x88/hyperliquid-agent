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

from daemon.context import TickContext
from daemon.iterators.account_collector import AccountCollectorIterator


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


# ---------------------------------------------------------------------------
# Followup 2 (2026-04-09): ctx.prices → snapshot["prices"] for chat history
# market_context enrichment.
# ---------------------------------------------------------------------------
#
# The chat-history correlation pipeline (cli/telegram_agent.py:_log_chat ->
# _build_market_context_snapshot) was already forward-compatible: if the
# account snapshot dict has a `prices` key, it will pick it up. Followup 2
# is the producer side — the account_collector iterator copies ctx.prices
# (which ConnectorIterator populates) into the snapshot dict. Stringified
# Decimals so the snapshot stays JSON-serializable.


class TestSnapshotPricesEnrichment:
    def test_ctx_prices_populate_snapshot_prices_field(self, tmp_path):
        """When ctx.prices is non-empty, snapshot['prices'] mirrors it as
        string values keyed by symbol."""
        from decimal import Decimal

        adapter = _FakeAdapter(
            native_positions=[],
            perp_value=0.0,
            spot_usdc=100.0,
        )
        it = AccountCollectorIterator(adapter=adapter, snapshot_dir=str(tmp_path))

        ctx = TickContext()
        ctx.prices["BTC"] = Decimal("94250.50")
        ctx.prices["xyz:BRENTOIL"] = Decimal("78.41")

        snap = it._build_snapshot(ctx)
        assert snap is not None
        assert "prices" in snap
        assert snap["prices"]["BTC"] == "94250.50"
        assert snap["prices"]["xyz:BRENTOIL"] == "78.41"

    def test_empty_ctx_prices_omits_snapshot_prices(self, tmp_path):
        """No prices on ctx → no `prices` key on the snapshot. Downstream
        consumers test for the key's presence so this matters."""
        adapter = _FakeAdapter(
            native_positions=[],
            perp_value=0.0,
            spot_usdc=100.0,
        )
        it = AccountCollectorIterator(adapter=adapter, snapshot_dir=str(tmp_path))

        ctx = TickContext()  # ctx.prices is an empty dict by default
        snap = it._build_snapshot(ctx)
        assert snap is not None
        # Empty ctx.prices means no prices field on snapshot
        assert "prices" not in snap or snap["prices"] == {}

    def test_snapshot_remains_json_serializable_with_prices(self, tmp_path):
        """Decimals get stringified so json.dumps doesn't crash on the
        snapshot. This is the critical contract — snapshot files must be
        loadable by every downstream reader (chat history enrichment,
        agent tools, brutal review)."""
        import json
        from decimal import Decimal

        adapter = _FakeAdapter(
            native_positions=[],
            perp_value=0.0,
            spot_usdc=100.0,
        )
        it = AccountCollectorIterator(adapter=adapter, snapshot_dir=str(tmp_path))

        ctx = TickContext()
        ctx.prices["BTC"] = Decimal("94250.50")
        ctx.prices["GOLD"] = Decimal("2105.75")

        snap = it._build_snapshot(ctx)
        # Round-trip through JSON to prove serializability
        serialized = json.dumps(snap)
        loaded = json.loads(serialized)
        assert loaded["prices"]["BTC"] == "94250.50"
        assert loaded["prices"]["GOLD"] == "2105.75"


# ---------------------------------------------------------------------------
# Snapshot rotation: 30-day expiry + daily throttle
# ---------------------------------------------------------------------------

import time as _time
from pathlib import Path as _Path


def _make_snapshot(directory: _Path, name: str, age_days: float) -> _Path:
    """Write a minimal JSON snapshot file with an mtime set to ``age_days`` ago."""
    fp = directory / name
    fp.write_text('{"test": true}')
    # Back-date mtime to simulate the file being ``age_days`` old.
    ts = _time.time() - age_days * 86400
    import os
    os.utime(fp, (ts, ts))
    return fp


class TestSnapshotRotation:
    """Tests for _expire_old_snapshots — 30d deletion, 7d thinning, hwm.json preservation."""

    def test_files_older_than_30_days_are_deleted(self, tmp_path):
        """Any snapshot over 30 days old must be removed."""
        old = _make_snapshot(tmp_path, "20250101_120000.json", age_days=35)
        recent = _make_snapshot(tmp_path, "20260101_120000.json", age_days=2)

        it = AccountCollectorIterator(adapter=None, snapshot_dir=str(tmp_path))
        it._expire_old_snapshots()

        assert not old.exists(), "35-day-old snapshot should be deleted"
        assert recent.exists(), "2-day-old snapshot should be kept"

    def test_hwm_json_is_never_deleted(self, tmp_path):
        """hwm.json must survive rotation regardless of its mtime."""
        # Create hwm.json and back-date it heavily
        hwm = tmp_path / "hwm.json"
        hwm.write_text('{"hwm": 1000}')
        import os
        ts = _time.time() - 90 * 86400   # 90 days old
        os.utime(hwm, (ts, ts))

        it = AccountCollectorIterator(adapter=None, snapshot_dir=str(tmp_path))
        it._expire_old_snapshots()

        assert hwm.exists(), "hwm.json must never be deleted by rotation"

    def test_within_7_days_all_kept(self, tmp_path):
        """Files ≤7 days old are all kept, even multiple per day."""
        f1 = _make_snapshot(tmp_path, "20260415_080000.json", age_days=1)
        f2 = _make_snapshot(tmp_path, "20260415_120000.json", age_days=1)
        f3 = _make_snapshot(tmp_path, "20260415_160000.json", age_days=1)

        it = AccountCollectorIterator(adapter=None, snapshot_dir=str(tmp_path))
        it._expire_old_snapshots()

        assert f1.exists() and f2.exists() and f3.exists(), \
            "All files ≤7 days old should be preserved"

    def test_between_7_and_30_days_only_last_per_day_kept(self, tmp_path):
        """For files 7–30 days old, only the last (lexicographically latest) per day is kept."""
        day = "20260301"
        early = _make_snapshot(tmp_path, f"{day}_080000.json", age_days=20)
        mid   = _make_snapshot(tmp_path, f"{day}_120000.json", age_days=20)
        last  = _make_snapshot(tmp_path, f"{day}_200000.json", age_days=20)

        it = AccountCollectorIterator(adapter=None, snapshot_dir=str(tmp_path))
        it._expire_old_snapshots()

        assert not early.exists(), "Earlier snapshot in 7-30d range should be deleted"
        assert not mid.exists(),   "Middle snapshot in 7-30d range should be deleted"
        assert last.exists(),      "Latest snapshot in 7-30d range must be kept"

    def test_daily_throttle_prevents_repeated_runs(self, tmp_path, monkeypatch):
        """_expire_old_snapshots should only be called when ROTATE_INTERVAL_S has elapsed."""
        # Plant an old file that rotation would delete
        old = _make_snapshot(tmp_path, "20250101_000000.json", age_days=40)

        adapter = _FakeAdapter(
            native_positions=[],
            perp_value=0.0,
            spot_usdc=100.0,
        )
        it = AccountCollectorIterator(adapter=adapter, snapshot_dir=str(tmp_path))

        # Force _last_rotate to "just now" — rotation should be skipped this tick
        import daemon.iterators.account_collector as _mod
        it._last_rotate = _time.monotonic()  # already rotated

        ctx = TickContext()
        it._collect_and_inject(ctx)

        # Old file should still be present because the throttle prevented rotation
        assert old.exists(), "Old snapshot should NOT be deleted when throttle is active"

    def test_daily_throttle_fires_when_interval_elapsed(self, tmp_path):
        """When last rotation was >24h ago (or never), rotation runs and deletes old files."""
        old = _make_snapshot(tmp_path, "20250101_000000.json", age_days=40)

        adapter = _FakeAdapter(
            native_positions=[],
            perp_value=0.0,
            spot_usdc=100.0,
        )
        it = AccountCollectorIterator(adapter=adapter, snapshot_dir=str(tmp_path))
        # _last_rotate=0 means "never run" → interval elapsed → rotation fires
        assert it._last_rotate == 0.0

        ctx = TickContext()
        it._collect_and_inject(ctx)

        assert not old.exists(), "40-day-old snapshot should be deleted after rotation fires"

    def test_rotation_logs_deleted_count_and_bytes(self, tmp_path, caplog):
        """Rotation must log the count and size of deleted files."""
        import logging
        _make_snapshot(tmp_path, "20250101_120000.json", age_days=35)

        it = AccountCollectorIterator(adapter=None, snapshot_dir=str(tmp_path))
        with caplog.at_level(logging.INFO, logger="daemon.account_collector"):
            it._expire_old_snapshots()

        assert "deleted" in caplog.text.lower(), "Rotation should log deleted file count"
        assert "KB" in caplog.text, "Rotation should log bytes freed in KB"
