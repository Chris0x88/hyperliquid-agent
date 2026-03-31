"""Tests for heartbeat memory schema extension."""
import sqlite3
import tempfile
import time
import os
from common.memory import _conn


def test_new_tables_created():
    """Memory DB creates observations, action_log, execution_traces tables."""
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "test.db")
        con = _conn(db_path)
        tables = [row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "observations" in tables
        assert "action_log" in tables
        assert "execution_traces" in tables
        assert "events" in tables  # old tables still exist
        assert "learnings" in tables
        con.close()


def test_observations_insert_and_query():
    """Can insert and query observations with temporal validity."""
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "test.db")
        con = _conn(db_path)
        now = int(time.time() * 1000)
        con.execute(
            "INSERT INTO observations (created_at, valid_from, market, category, priority, title, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, now, "xyz:BRENTOIL", "metric", 1, "test obs", "programmatic"),
        )
        con.commit()
        rows = con.execute("SELECT * FROM observations WHERE market = ?", ("xyz:BRENTOIL",)).fetchall()
        assert len(rows) == 1
        assert rows[0]["title"] == "test obs"
        assert rows[0]["valid_until"] is None
        con.close()


def test_action_log_insert():
    """Can insert action_log entries."""
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "test.db")
        con = _conn(db_path)
        now = int(time.time() * 1000)
        con.execute(
            "INSERT INTO action_log (timestamp_ms, market, action_type, reasoning, source) VALUES (?, ?, ?, ?, ?)",
            (now, "xyz:BRENTOIL", "stop_placed", "ATR-based stop", "programmatic"),
        )
        con.commit()
        rows = con.execute("SELECT * FROM action_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["action_type"] == "stop_placed"
        con.close()


def test_execution_traces_insert():
    """Can insert execution trace entries."""
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "test.db")
        con = _conn(db_path)
        now = int(time.time() * 1000)
        con.execute(
            "INSERT INTO execution_traces (timestamp_ms, process, duration_ms, success, stdout) VALUES (?, ?, ?, ?, ?)",
            (now, "heartbeat", 1500, 1, "all checks passed"),
        )
        con.commit()
        rows = con.execute("SELECT * FROM execution_traces").fetchall()
        assert len(rows) == 1
        assert rows[0]["process"] == "heartbeat"
        assert rows[0]["success"] == 1
        con.close()
