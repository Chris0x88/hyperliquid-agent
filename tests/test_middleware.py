"""Tests for common.middleware — timing, timeout, and error capture."""
import time
import pytest
from common.middleware import MiddlewareResult, run_with_middleware


def _fast_fn():
    return 42


def _slow_fn():
    time.sleep(0.2)
    return "done"


def _failing_fn():
    raise ValueError("boom")


class FakeTelemetry:
    """Stub to capture telemetry.record() calls."""
    def __init__(self):
        self.calls = []

    def record(self, name, elapsed, status, error=None):
        self.calls.append({"name": name, "elapsed": elapsed,
                           "status": status, "error": error})


class TestRunWithMiddleware:
    def test_successful_call(self):
        result = run_with_middleware("test_fast", _fast_fn, timeout_s=5)
        assert result.status == "ok"
        assert result.result == 42
        assert result.elapsed_s < 1.0
        assert result.error is None

    def test_error_capture(self):
        result = run_with_middleware("test_fail", _failing_fn, timeout_s=5)
        assert result.status == "error"
        assert "boom" in result.error
        assert result.result is None

    def test_timing(self):
        result = run_with_middleware("test_slow", _slow_fn, timeout_s=5)
        assert result.status == "ok"
        assert result.elapsed_s >= 0.15  # at least 150ms (sleep 200ms)
        assert result.elapsed_s < 1.0

    def test_telemetry_recording(self):
        tel = FakeTelemetry()
        result = run_with_middleware("test_tel", _fast_fn, timeout_s=5, telemetry=tel)
        assert result.status == "ok"
        assert len(tel.calls) == 1
        assert tel.calls[0]["name"] == "test_tel"
        assert tel.calls[0]["status"] == "ok"

    def test_telemetry_on_error(self):
        tel = FakeTelemetry()
        result = run_with_middleware("test_fail_tel", _failing_fn, timeout_s=5, telemetry=tel)
        assert result.status == "error"
        assert len(tel.calls) == 1
        assert tel.calls[0]["status"] == "error"
        assert "boom" in tel.calls[0]["error"]

    def test_with_args(self):
        def add(a, b):
            return a + b
        result = run_with_middleware("test_add", add, 3, 4, timeout_s=5)
        assert result.status == "ok"
        assert result.result == 7

    def test_with_kwargs(self):
        def greet(target="world"):
            return f"hello {target}"
        result = run_with_middleware("test_greet", greet, timeout_s=5, target="agent")
        assert result.status == "ok"
        assert result.result == "hello agent"

    def test_zero_timeout_no_enforcement(self):
        result = run_with_middleware("test_no_timeout", _slow_fn, timeout_s=0)
        assert result.status == "ok"
        assert result.result == "done"

    def test_result_dataclass(self):
        result = run_with_middleware("test_dc", _fast_fn, timeout_s=5)
        assert isinstance(result, MiddlewareResult)
        assert result.name == "test_dc"
