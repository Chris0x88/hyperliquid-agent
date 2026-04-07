"""Tests for account_snapshots dual-write into memory.db (audit H4)."""
import json
import os
import sqlite3
import tempfile
import time

import pytest

from common.memory import log_account_snapshot, get_account_snapshots, _init


def _now_ms() -> int:
    return int(time.time() * 1000)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


def _connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    _init(con)
    return con


class TestSchema:
    def test_table_created_on_first_write(self, tmp_db):
        snap = {
            "timestamp": _now_ms(),
            "total_equity": 1000.0,
            "high_water_mark": 1100.0,
            "drawdown_pct": 9.09,
        }
        rid = log_account_snapshot(snap, snapshot_filename="t.json", db_path=tmp_db)
        assert rid > 0
        # Verify table exists with the index
        con = sqlite3.connect(tmp_db)
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_account_snapshots_ts'"
        )
        assert cur.fetchone() is not None


class TestWriteFlatSnapshot:
    def test_basic_equity_fields(self, tmp_db):
        snap = {
            "timestamp": _now_ms(),
            "total_equity": 5000.0,
            "xyz_account_value": 1500.0,
            "spot_usdc": 200.0,
            "high_water_mark": 5500.0,
            "drawdown_pct": 9.09,
        }
        rid = log_account_snapshot(snap, snapshot_filename="x.json", db_path=tmp_db)
        rows = get_account_snapshots(days=30, db_path=tmp_db)
        assert len(rows) == 1
        r = rows[0]
        assert r["id"] == rid
        assert r["snapshot_filename"] == "x.json"
        assert r["equity_total"] == 5000.0
        assert r["equity_xyz"] == 1500.0
        assert r["spot_usdc"] == 200.0
        # native = total - xyz - spot = 5000 - 1500 - 200 = 3300
        assert r["equity_native"] == 3300.0
        assert r["high_water_mark"] == 5500.0
        assert r["drawdown_pct"] == pytest.approx(9.09)
        assert r["has_positions"] == 0
        assert r["position_count"] == 0
        assert r["positions_json"] is None

    def test_native_clamped_at_zero(self, tmp_db):
        # Edge case: xyz + spot > total (shouldn't happen but defensive)
        snap = {
            "timestamp": _now_ms(),
            "total_equity": 100.0,
            "xyz_account_value": 200.0,
            "spot_usdc": 50.0,
        }
        log_account_snapshot(snap, db_path=tmp_db)
        rows = get_account_snapshots(days=30, db_path=tmp_db)
        assert rows[0]["equity_native"] == 0.0

    def test_missing_timestamp_uses_now(self, tmp_db):
        snap = {"total_equity": 100.0}  # no timestamp
        rid = log_account_snapshot(snap, db_path=tmp_db)
        rows = get_account_snapshots(days=1, db_path=tmp_db)
        assert len(rows) == 1
        # Should be a recent timestamp (within last 5 seconds)
        import time
        now_ms = int(time.time() * 1000)
        assert (now_ms - rows[0]["timestamp_ms"]) < 5000


class TestPositionExtraction:
    def test_native_positions_counted(self, tmp_db):
        snap = {
            "timestamp": _now_ms(),
            "total_equity": 1000.0,
            "positions_native": [
                {"coin": "BTC", "szi": "0.5", "entryPx": "60000"},
                {"coin": "ETH", "szi": "0", "entryPx": "3000"},  # closed — szi=0
                {"coin": "SOL", "szi": "10", "entryPx": "150"},
            ],
        }
        log_account_snapshot(snap, db_path=tmp_db)
        rows = get_account_snapshots(days=30, db_path=tmp_db)
        r = rows[0]
        assert r["has_positions"] == 1
        assert r["position_count"] == 2  # BTC + SOL, ETH excluded
        positions = json.loads(r["positions_json"])
        coins = {p["coin"] for p in positions}
        assert coins == {"BTC", "SOL"}

    def test_xyz_positions_unwrapped(self, tmp_db):
        # xyz positions are wrapped in {"position": {...}}
        snap = {
            "timestamp": _now_ms(),
            "total_equity": 1000.0,
            "positions_xyz": [
                {"position": {"coin": "xyz:BRENTOIL", "szi": "100"}},
                {"position": {"coin": "xyz:GOLD", "szi": "0"}},  # excluded
            ],
        }
        log_account_snapshot(snap, db_path=tmp_db)
        rows = get_account_snapshots(days=30, db_path=tmp_db)
        r = rows[0]
        assert r["position_count"] == 1
        positions = json.loads(r["positions_json"])
        assert positions[0]["coin"] == "xyz:BRENTOIL"

    def test_mixed_native_and_xyz(self, tmp_db):
        snap = {
            "timestamp": _now_ms(),
            "total_equity": 1000.0,
            "positions_native": [
                {"coin": "BTC", "szi": "0.5"},
            ],
            "positions_xyz": [
                {"position": {"coin": "xyz:BRENTOIL", "szi": "10"}},
            ],
        }
        log_account_snapshot(snap, db_path=tmp_db)
        rows = get_account_snapshots(days=30, db_path=tmp_db)
        assert rows[0]["position_count"] == 2

    def test_no_positions(self, tmp_db):
        snap = {"timestamp": _now_ms(), "total_equity": 1000.0}
        log_account_snapshot(snap, db_path=tmp_db)
        rows = get_account_snapshots(days=30, db_path=tmp_db)
        assert rows[0]["has_positions"] == 0
        assert rows[0]["position_count"] == 0


class TestQuery:
    def test_get_recent_ordered_newest_first(self, tmp_db):
        base = _now_ms() - 3600 * 1000  # one hour ago
        for ts in [base, base + 60000, base + 120000]:
            log_account_snapshot(
                {"timestamp": ts, "total_equity": float(ts % 1000)},
                db_path=tmp_db,
            )
        rows = get_account_snapshots(days=30, db_path=tmp_db)
        timestamps = [r["timestamp_ms"] for r in rows]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_limit(self, tmp_db):
        base = _now_ms() - 3600 * 1000
        for ts in range(base, base + 10 * 60000, 60000):
            log_account_snapshot(
                {"timestamp": ts, "total_equity": 100.0},
                db_path=tmp_db,
            )
        rows = get_account_snapshots(days=30, limit=3, db_path=tmp_db)
        assert len(rows) == 3

    def test_days_filter_excludes_old(self, tmp_db):
        import time
        now_ms = int(time.time() * 1000)
        # 100 days old
        log_account_snapshot(
            {"timestamp": now_ms - 100 * 86400 * 1000, "total_equity": 1.0},
            db_path=tmp_db,
        )
        # 1 day old
        log_account_snapshot(
            {"timestamp": now_ms - 86400 * 1000, "total_equity": 2.0},
            db_path=tmp_db,
        )
        rows = get_account_snapshots(days=7, db_path=tmp_db)
        assert len(rows) == 1
        assert rows[0]["equity_total"] == 2.0


class TestRealisticAccountCollectorShape:
    """Round-trip with the exact dict shape produced by AccountCollectorIterator._build_snapshot()."""

    def test_full_snapshot_roundtrip(self, tmp_db):
        # Mirrors the keys set by account_collector._build_snapshot()
        snapshot = {
            "timestamp": _now_ms(),
            "timestamp_human": "2024-04-01 00:00:00 UTC",
            "account_value": 5500.0,           # gets overwritten with total_equity
            "total_margin": 2000.0,
            "withdrawable": 1000.0,
            "spot_usdc": 200.0,
            "positions_native": [
                {"coin": "BTC", "szi": "0.1", "entryPx": "60000"},
            ],
            "positions_xyz": [
                {"position": {"coin": "xyz:BRENTOIL", "szi": "5", "entryPx": "85"}},
            ],
            "xyz_account_value": 800.0,
            "xyz_margin_summary": {"accountValue": "800"},
            "xyz_open_orders": [],
            "total_equity": 5500.0,
            "high_water_mark": 6000.0,
            "drawdown_pct": 8.33,
        }
        rid = log_account_snapshot(
            snapshot,
            snapshot_filename="20260407_120000.json",
            db_path=tmp_db,
        )
        assert rid > 0
        rows = get_account_snapshots(days=30, db_path=tmp_db)
        assert len(rows) == 1
        r = rows[0]
        assert r["snapshot_filename"] == "20260407_120000.json"
        assert r["equity_total"] == 5500.0
        assert r["equity_xyz"] == 800.0
        assert r["spot_usdc"] == 200.0
        assert r["equity_native"] == 4500.0  # 5500 - 800 - 200
        assert r["high_water_mark"] == 6000.0
        assert r["has_positions"] == 1
        assert r["position_count"] == 2
        positions = json.loads(r["positions_json"])
        coins = {p["coin"] for p in positions}
        assert coins == {"BTC", "xyz:BRENTOIL"}
