"""Tests for common.telemetry — behavioral metrics recording."""
import json
import time
from pathlib import Path

import pytest
from common.telemetry import TelemetryRecorder, CycleMetrics, ActionMetric


class TestTelemetryRecorder:
    def test_basic_cycle(self, tmp_path):
        tel = TelemetryRecorder("heartbeat", state_dir=tmp_path)
        tel.start_cycle()
        tel.record("check_stops", 0.3, "ok")
        tel.record("place_stop", 1.2, "ok")
        tel.end_cycle()

        # Check file was written
        data = json.loads((tmp_path / "telemetry.json").read_text())
        assert data["latest"]["component"] == "heartbeat"
        assert data["latest"]["total_actions"] == 2
        assert data["latest"]["ok"] == 2
        assert data["latest"]["errors"] == 0

    def test_error_tracking(self, tmp_path):
        tel = TelemetryRecorder("daemon", state_dir=tmp_path)
        tel.start_cycle()
        tel.record("fetch_data", 0.1, "ok")
        tel.record("process", 5.0, "error", "API timeout")
        tel.record("cleanup", 0.05, "ok")
        tel.end_cycle()

        data = json.loads((tmp_path / "telemetry.json").read_text())
        assert data["latest"]["ok"] == 2
        assert data["latest"]["errors"] == 1

    def test_api_counters(self, tmp_path):
        tel = TelemetryRecorder("heartbeat", state_dir=tmp_path)
        tel.start_cycle()
        tel.increment_api_call(success=True)
        tel.increment_api_call(success=True)
        tel.increment_api_call(success=False)
        tel.end_cycle()

        data = json.loads((tmp_path / "telemetry.json").read_text())
        assert data["latest"]["api_calls"] == 3
        assert data["latest"]["api_failures"] == 1

    def test_stop_counters(self, tmp_path):
        tel = TelemetryRecorder("heartbeat", state_dir=tmp_path)
        tel.start_cycle()
        tel.increment_stop(success=True)
        tel.increment_stop(success=True)
        tel.increment_stop(success=False)
        tel.end_cycle()

        data = json.loads((tmp_path / "telemetry.json").read_text())
        assert data["latest"]["stops_placed"] == 2
        assert data["latest"]["stops_failed"] == 1

    def test_history_accumulates(self, tmp_path):
        tel = TelemetryRecorder("daemon", state_dir=tmp_path)
        for i in range(3):
            tel.start_cycle()
            tel.record(f"action_{i}", 0.1, "ok")
            tel.end_cycle()

        data = json.loads((tmp_path / "telemetry.json").read_text())
        assert len(data["history"]) == 3

    def test_history_cap(self, tmp_path):
        tel = TelemetryRecorder("daemon", state_dir=tmp_path)
        tel._max_history = 5

        for i in range(10):
            tel.start_cycle()
            tel.record(f"action_{i}", 0.1, "ok")
            tel.end_cycle()

        data = json.loads((tmp_path / "telemetry.json").read_text())
        assert len(data["history"]) == 5

    def test_cycle_duration(self, tmp_path):
        tel = TelemetryRecorder("heartbeat", state_dir=tmp_path)
        tel.start_cycle()
        time.sleep(0.1)
        tel.record("work", 0.1, "ok")
        tel.end_cycle()

        data = json.loads((tmp_path / "telemetry.json").read_text())
        assert data["latest"]["cycle_duration_s"] >= 0.05

    def test_no_cycle_noop(self, tmp_path):
        tel = TelemetryRecorder("heartbeat", state_dir=tmp_path)
        # These should silently no-op without start_cycle
        tel.record("orphan", 0.1, "ok")
        tel.increment_api_call()
        tel.increment_stop()
        tel.increment_orders()
        tel.end_cycle()
        # No file should be written
        assert not (tmp_path / "telemetry.json").exists()

    def test_actions_in_output(self, tmp_path):
        tel = TelemetryRecorder("heartbeat", state_dir=tmp_path)
        tel.start_cycle()
        tel.record("step_a", 0.3, "ok")
        tel.record("step_b", 0.5, "error", "failed")
        tel.end_cycle()

        data = json.loads((tmp_path / "telemetry.json").read_text())
        actions = data["current_cycle_actions"]
        assert len(actions) == 2
        assert actions[0]["name"] == "step_a"
        assert actions[1]["error"] == "failed"
