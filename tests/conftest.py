"""Shared fixtures for the agent-cli test suite."""
from __future__ import annotations

import time
import tempfile

import pytest

from common.models import MarketSnapshot
from sdk.strategy_sdk.base import StrategyContext


@pytest.fixture(autouse=True)
def _disable_gate_chain_for_tests():
    """Disable the execute_tool gate chain for all tests that don't need it.

    Tests in test_tool_gates.py exercise the gates directly and don't call
    execute_tool, so they are unaffected.  All other tests that call
    execute_tool() directly get a pass-through (chain=None) so the rate
    limiter doesn't accumulate across the test suite.

    Restore the sentinel (None → lazy-build) after each test so a later
    test that explicitly sets the chain sees a clean slate.
    """
    try:
        import agent.tools as tools_mod
        original = tools_mod._gate_chain
        tools_mod.set_gate_chain(None)  # None → gate code returns immediately (no-op)
        # Override _get_gate_chain to return None (bypass lazy build too)
        original_get = tools_mod._get_gate_chain

        def _no_gate_chain():
            return None

        tools_mod._get_gate_chain = _no_gate_chain
        yield
        tools_mod._get_gate_chain = original_get
        tools_mod._gate_chain = original
    except ImportError:
        yield


@pytest.fixture
def snapshot():
    return MarketSnapshot(
        instrument="ETH-PERP",
        mid_price=2500.0,
        bid=2499.5,
        ask=2500.5,
        spread_bps=4.0,
        timestamp_ms=int(time.time() * 1000),
    )


@pytest.fixture
def context():
    return StrategyContext(round_number=1)


@pytest.fixture
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d
