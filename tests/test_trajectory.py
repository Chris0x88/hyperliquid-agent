"""Tests for common.trajectory — JSONL session logging."""
import json
import tempfile
from pathlib import Path

import pytest
from common.trajectory import TrajectoryEntry, TrajectoryLogger


class TestTrajectoryEntry:
    def test_to_json_minimal(self):
        entry = TrajectoryEntry(ts=1711900000.0, component="heartbeat", action="tick")
        parsed = json.loads(entry.to_json())
        assert parsed["component"] == "heartbeat"
        assert parsed["action"] == "tick"
        assert "symbol" not in parsed  # None fields excluded

    def test_to_json_full(self):
        entry = TrajectoryEntry(
            ts=1711900000.0,
            component="daemon",
            action="stop_placed",
            symbol="BRENTOIL",
            details={"price": 108.5, "side": "buy"},
            status="ok",
        )
        parsed = json.loads(entry.to_json())
        assert parsed["symbol"] == "BRENTOIL"
        assert parsed["details"]["price"] == 108.5
        assert parsed["status"] == "ok"


class TestTrajectoryLogger:
    def test_creates_file(self, tmp_path):
        with TrajectoryLogger("test", log_dir=tmp_path) as traj:
            assert traj.filepath.exists()
            assert "trajectory_" in traj.filepath.name
            assert "_test.jsonl" in traj.filepath.name

    def test_writes_entries(self, tmp_path):
        with TrajectoryLogger("heartbeat", log_dir=tmp_path) as traj:
            traj.log("tick_start")
            traj.log("stop_placed", symbol="BTC", details={"price": 95000})
            traj.log("tick_end", status="ok")

        assert traj.entry_count == 3

        # Read and parse
        lines = traj.filepath.read_text().strip().split("\n")
        assert len(lines) == 3

        first = json.loads(lines[0])
        assert first["action"] == "tick_start"
        assert first["component"] == "heartbeat"

        second = json.loads(lines[1])
        assert second["symbol"] == "BTC"
        assert second["details"]["price"] == 95000

    def test_context_manager_closes(self, tmp_path):
        with TrajectoryLogger("test", log_dir=tmp_path) as traj:
            traj.log("hello")
            filepath = traj.filepath
        # File should be closed now — we can read it
        content = filepath.read_text()
        assert "hello" in content

    def test_entry_count(self, tmp_path):
        with TrajectoryLogger("counter", log_dir=tmp_path) as traj:
            assert traj.entry_count == 0
            traj.log("a")
            traj.log("b")
            assert traj.entry_count == 2

    def test_creates_log_dir(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "dir"
        with TrajectoryLogger("auto_dir", log_dir=nested) as traj:
            traj.log("test")
        assert nested.exists()
