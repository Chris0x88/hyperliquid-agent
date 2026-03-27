"""SQLite candle cache — persistent local storage for OHLCV data.

Candles use the same dict format as HLProxy.get_candles():
  {"t": int_ms, "o": "price", "h": "price", "l": "price", "c": "price", "v": "volume"}

All string values (matching HL API), timestamps in milliseconds.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("candle_cache")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    coin       TEXT    NOT NULL,
    interval   TEXT    NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    open       TEXT    NOT NULL,
    high       TEXT    NOT NULL,
    low        TEXT    NOT NULL,
    close      TEXT    NOT NULL,
    volume     TEXT    NOT NULL,
    source     TEXT    DEFAULT 'api',
    PRIMARY KEY (coin, interval, timestamp_ms)
);
CREATE INDEX IF NOT EXISTS idx_candles_range ON candles(coin, interval, timestamp_ms);

CREATE TABLE IF NOT EXISTS fetch_log (
    coin       TEXT NOT NULL,
    interval   TEXT NOT NULL,
    start_ms   INTEGER NOT NULL,
    end_ms     INTEGER NOT NULL,
    count      INTEGER NOT NULL,
    source     TEXT DEFAULT 'api',
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY (coin, interval, start_ms)
);
"""

# Interval durations in milliseconds
INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def _normalize_coin(coin: str) -> str:
    """Normalize coin name, preserving xyz: prefix for spot tokens.

    HL API uses lowercase prefix (xyz:BRENTOIL), so we keep prefix as-is
    and only uppercase the token name.
    """
    if ":" in coin:
        prefix, name = coin.split(":", 1)
        return f"{prefix.lower()}:{name.upper()}"
    return coin.upper()


@dataclass
class CandleCache:
    """Persistent SQLite cache for OHLCV candle data."""

    db_path: str = "data/candles/candles.db"
    _conn: Optional[sqlite3.Connection] = field(default=None, repr=False)

    def __post_init__(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(_SCHEMA)
        # WAL mode for concurrent reads while daemon writes
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def store_candles(
        self, coin: str, interval: str, candles: List[Dict], source: str = "api"
    ) -> int:
        """Store candles, skipping duplicates. Returns count inserted."""
        if not candles:
            return 0

        coin = _normalize_coin(coin)
        rows = []
        for c in candles:
            rows.append((
                coin, interval, int(c["t"]),
                str(c["o"]), str(c["h"]), str(c["l"]), str(c["c"]), str(c["v"]),
                source,
            ))

        cursor = self._conn.executemany(
            "INSERT OR IGNORE INTO candles (coin, interval, timestamp_ms, open, high, low, close, volume, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        inserted = cursor.rowcount
        log.debug("Stored %d/%d candles for %s %s", inserted, len(candles), coin, interval)
        return inserted

    def get_candles(
        self, coin: str, interval: str, start_ms: int, end_ms: int
    ) -> List[Dict]:
        """Retrieve candles in the standard HL dict format, sorted by time."""
        coin = _normalize_coin(coin)
        rows = self._conn.execute(
            "SELECT timestamp_ms, open, high, low, close, volume FROM candles "
            "WHERE coin = ? AND interval = ? AND timestamp_ms >= ? AND timestamp_ms <= ? "
            "ORDER BY timestamp_ms",
            (coin, interval, start_ms, end_ms),
        ).fetchall()

        return [
            {"t": r[0], "o": r[1], "h": r[2], "l": r[3], "c": r[4], "v": r[5]}
            for r in rows
        ]

    def count(self, coin: str = "", interval: str = "") -> int:
        """Count candles, optionally filtered by coin/interval."""
        query = "SELECT COUNT(*) FROM candles WHERE 1=1"
        params: list = []
        if coin:
            query += " AND coin = ?"
            params.append(_normalize_coin(coin))
        if interval:
            query += " AND interval = ?"
            params.append(interval)
        return self._conn.execute(query, params).fetchone()[0]

    def date_range(self, coin: str, interval: str) -> Optional[Tuple[int, int]]:
        """Return (min_ts, max_ts) for a coin/interval, or None if empty."""
        coin = _normalize_coin(coin)
        row = self._conn.execute(
            "SELECT MIN(timestamp_ms), MAX(timestamp_ms) FROM candles "
            "WHERE coin = ? AND interval = ?",
            (coin, interval),
        ).fetchone()
        if row and row[0] is not None:
            return (row[0], row[1])
        return None

    def coins(self) -> List[str]:
        """Return all coins with cached data."""
        rows = self._conn.execute(
            "SELECT DISTINCT coin FROM candles ORDER BY coin"
        ).fetchall()
        return [r[0] for r in rows]

    def intervals_for(self, coin: str) -> List[str]:
        """Return all intervals with data for a coin."""
        rows = self._conn.execute(
            "SELECT DISTINCT interval FROM candles WHERE coin = ? ORDER BY interval",
            (_normalize_coin(coin),),
        ).fetchall()
        return [r[0] for r in rows]

    def log_fetch(self, coin: str, interval: str, start_ms: int, end_ms: int, count: int, source: str = "api"):
        """Record a fetch in the log for gap detection."""
        import time
        self._conn.execute(
            "INSERT OR REPLACE INTO fetch_log (coin, interval, start_ms, end_ms, count, source, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_normalize_coin(coin), interval, start_ms, end_ms, count, source, int(time.time() * 1000)),
        )
        self._conn.commit()

    def stats(self) -> Dict:
        """Summary statistics for the cache."""
        total = self._conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        coins_data = {}
        for coin in self.coins():
            coin_info = {}
            for interval in self.intervals_for(coin):
                cnt = self.count(coin, interval)
                rng = self.date_range(coin, interval)
                coin_info[interval] = {
                    "count": cnt,
                    "start": rng[0] if rng else None,
                    "end": rng[1] if rng else None,
                }
            coins_data[coin] = coin_info
        return {"total_candles": total, "coins": coins_data}

    def export_csv(self, coin: str, interval: str, path: str) -> int:
        """Export candles to CSV. Returns row count."""
        import csv
        coin = _normalize_coin(coin)
        rows = self._conn.execute(
            "SELECT timestamp_ms, open, high, low, close, volume FROM candles "
            "WHERE coin = ? AND interval = ? ORDER BY timestamp_ms",
            (coin, interval),
        ).fetchall()

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp_ms", "open", "high", "low", "close", "volume"])
            w.writerows(rows)

        return len(rows)
