"""Middleware — wraps daemon iterators and heartbeat sub-functions with consistent
timing, error capture, and timeout budgets.

Inspired by DeerFlow 2.0's 11-layer middleware chain, simplified to what matters
for a trading daemon: timing, errors, and circuit-breaker awareness.
"""
from __future__ import annotations

import logging
import signal
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("middleware")


@dataclass
class MiddlewareResult:
    """Result of a middleware-wrapped function call."""
    name: str
    status: str          # "ok", "timeout", "error"
    elapsed_s: float
    error: Optional[str] = None
    result: Any = None


class TimeoutError(Exception):
    """Raised when a function exceeds its time budget."""
    pass


@contextmanager
def _timeout_context(seconds: int):
    """Context manager that raises TimeoutError after `seconds`.

    Uses signal.SIGALRM on the main thread, falls back to no-op
    on non-main threads or non-Unix systems.
    """
    if seconds <= 0:
        yield
        return

    # signal.alarm only works on main thread
    try:
        is_main = threading.current_thread() is threading.main_thread()
    except Exception:
        is_main = False

    if not is_main or not hasattr(signal, "SIGALRM"):
        yield  # no timeout enforcement on non-main threads
        return

    def _handler(signum, frame):
        raise TimeoutError(f"Exceeded {seconds}s budget")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def run_with_middleware(
    name: str,
    fn: Callable,
    *args,
    timeout_s: int = 10,
    telemetry: Optional[Any] = None,
    **kwargs,
) -> MiddlewareResult:
    """Execute a function with timing, error capture, and optional timeout.

    Args:
        name: Human-readable identifier for logging.
        fn: The function to execute.
        *args: Positional arguments passed to fn.
        timeout_s: Maximum seconds before timeout (0 = no limit).
        telemetry: Optional TelemetryRecorder to log metrics to.
        **kwargs: Keyword arguments passed to fn.

    Returns:
        MiddlewareResult with status, timing, and any error.
    """
    start = time.monotonic()
    try:
        with _timeout_context(timeout_s):
            result = fn(*args, **kwargs)
        elapsed = time.monotonic() - start
        log.debug("[done] %s (%.2fs)", name, elapsed)
        if telemetry:
            telemetry.record(name, elapsed, "ok")
        return MiddlewareResult(name=name, status="ok", elapsed_s=elapsed, result=result)

    except TimeoutError:
        elapsed = time.monotonic() - start
        log.warning("[timeout] %s after %.1fs (budget=%ds)", name, elapsed, timeout_s)
        if telemetry:
            telemetry.record(name, elapsed, "timeout")
        return MiddlewareResult(name=name, status="timeout", elapsed_s=elapsed,
                                error=f"Exceeded {timeout_s}s budget")

    except Exception as e:
        elapsed = time.monotonic() - start
        log.error("[error] %s: %s (%.2fs)", name, e, elapsed)
        if telemetry:
            telemetry.record(name, elapsed, "error", str(e))
        return MiddlewareResult(name=name, status="error", elapsed_s=elapsed,
                                error=str(e))
