"""Read-only SQLite access for memory.db and candles.db."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class SqliteReader:
    """Read-only SQLite connection with WAL mode."""

    def __init__(self, db_path: Path):
        self._path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self._path.exists():
                raise FileNotFoundError(f"Database not found: {self._path}")
            self._conn = sqlite3.connect(
                str(self._path),
                check_same_thread=False,
                timeout=5,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA query_only=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def query_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
