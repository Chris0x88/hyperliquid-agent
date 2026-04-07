"""Tests for the H2 authority gate in ExecutionEngineIterator._process_market.

Closes the LATENT-REBALANCE gap from the 2026-04-07 verification ledger:
execution_engine now refuses to size or queue orders for any market that
is not in 'agent' authority, even if a thesis file exists for it.

Production runs in WATCH tier where execution_engine does not execute,
so this is a tier-promotion gate, not an active production fix.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List
from unittest.mock import patch

import pytest

from cli.daemon.context import TickContext
from cli.daemon.iterators.execution_engine import ExecutionEngineIterator
from common.thesis import ThesisState
from parent.position_tracker import Position


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _thesis(
    market: str,
    conviction: float = 0.85,
    direction: str = "long",
    recommended_leverage: float = 10.0,
    recommended_size_pct: float = 0.20,
) -> ThesisState:
    return ThesisState(
        market=market,
        direction=direction,
        conviction=conviction,
        recommended_leverage=recommended_leverage,
        recommended_size_pct=recommended_size_pct,
    )


def _ctx_with_thesis(
    thesis_states: List[ThesisState],
    equity: float = 10_000.0,
    prices: dict | None = None,
    positions: list | None = None,
    drawdown_pct: float = 0.0,
) -> TickContext:
    c = TickContext()
    c.thesis_states = {t.market: t for t in thesis_states}
    c.balances = {"USDC": Decimal(str(equity))}
    c.prices = {k: Decimal(str(v)) for k, v in (prices or {}).items()}
    c.positions = positions or []
    c.account_drawdown_pct = drawdown_pct
    c.high_water_mark = equity
    return c


def _make_iterator() -> ExecutionEngineIterator:
    it = ExecutionEngineIterator(adapter=None)
    # Bypass the 2-minute REBALANCE_INTERVAL_S throttle
    it._last_rebalance = -1e9
    return it


# ---------------------------------------------------------------------------
# Authority gate tests
# ---------------------------------------------------------------------------


class TestExecutionEngineAuthorityGate:
    def test_agent_managed_market_gets_processed(self):
        """An agent-delegated market with conviction > 0 should produce an OrderIntent."""
        it = _make_iterator()
        ctx = _ctx_with_thesis(
            thesis_states=[_thesis("BTC", conviction=0.85)],
            equity=10_000.0,
            prices={"BTC": 100.0},
            positions=[],  # no current position → maximum delta → must rebalance
        )

        with patch(
            "cli.daemon.iterators.execution_engine.is_agent_managed",
            return_value=True,
        ):
            it.tick(ctx)

        # Conviction 0.85 → "full" band (20% size, 15x leverage)
        # 10_000 * 0.20 = $2000 target notional / $100 = 20 BTC
        # Current = 0, delta = 100% → must rebalance
        assert len(ctx.order_queue) == 1
        intent = ctx.order_queue[0]
        assert intent.instrument == "BTC"
        assert intent.action in ("buy", "sell", "close")

    def test_manual_market_is_skipped(self):
        """A market with thesis present but authority='manual' must NOT produce an order."""
        it = _make_iterator()
        ctx = _ctx_with_thesis(
            thesis_states=[_thesis("GOLD", conviction=0.85)],
            equity=10_000.0,
            prices={"GOLD": 2000.0},
            positions=[],
        )

        with patch(
            "cli.daemon.iterators.execution_engine.is_agent_managed",
            return_value=False,
        ):
            it.tick(ctx)

        assert ctx.order_queue == []

    def test_off_market_is_skipped(self):
        """Same as manual — is_agent_managed returns False for 'off' too."""
        it = _make_iterator()
        ctx = _ctx_with_thesis(
            thesis_states=[_thesis("MEME", conviction=0.85)],
            equity=10_000.0,
            prices={"MEME": 1.0},
            positions=[],
        )

        with patch(
            "cli.daemon.iterators.execution_engine.is_agent_managed",
            return_value=False,
        ):
            it.tick(ctx)

        assert ctx.order_queue == []

    def test_mixed_authority_only_agent_processed(self):
        """When some markets are delegated and others aren't, only agents get sized."""
        it = _make_iterator()
        ctx = _ctx_with_thesis(
            thesis_states=[
                _thesis("BTC", conviction=0.85),
                _thesis("GOLD", conviction=0.85),
                _thesis("xyz:BRENTOIL", conviction=0.85),
            ],
            equity=10_000.0,
            prices={"BTC": 100.0, "GOLD": 2000.0, "xyz:BRENTOIL": 80.0},
            positions=[],
        )

        # BTC and BRENTOIL delegated, GOLD is not
        def fake_is_agent_managed(asset: str) -> bool:
            return asset in ("BTC", "xyz:BRENTOIL")

        with patch(
            "cli.daemon.iterators.execution_engine.is_agent_managed",
            side_effect=fake_is_agent_managed,
        ):
            it.tick(ctx)

        queued_markets = sorted(intent.instrument for intent in ctx.order_queue)
        assert queued_markets == ["BTC", "xyz:BRENTOIL"]
        assert "GOLD" not in queued_markets

    def test_authority_gate_runs_before_conviction_band(self):
        """Authority gate is checked BEFORE any conviction or sizing math.

        Verified by: a stale thesis with low effective_conviction would normally
        skip via the 'exit' band, but for a non-delegated asset we should never
        even reach that code path. The skip log should fire instead.
        """
        it = _make_iterator()
        # conviction 0.1 → exit band normally
        ctx = _ctx_with_thesis(
            thesis_states=[_thesis("GOLD", conviction=0.1)],
            equity=10_000.0,
            prices={"GOLD": 2000.0},
            positions=[],
        )

        with patch(
            "cli.daemon.iterators.execution_engine.is_agent_managed",
            return_value=False,
        ) as mock_auth:
            it.tick(ctx)

        # Authority was checked
        mock_auth.assert_called_with("GOLD")
        # Nothing was queued (not even an exit close)
        assert ctx.order_queue == []

    def test_drawdown_ruin_gate_still_fires_globally(self):
        """The H2 gate is at _process_market scope. The unconditional ruin
        prevention at >=40% drawdown is at the tick() scope, BEFORE per-market
        processing. This must remain unaffected.
        """
        it = _make_iterator()
        ctx = _ctx_with_thesis(
            thesis_states=[_thesis("BTC", conviction=0.85)],
            equity=10_000.0,
            prices={"BTC": 100.0},
            positions=[
                Position(
                    instrument="BTC",
                    net_qty=Decimal("10"),
                    avg_entry_price=Decimal("100"),
                    leverage=Decimal("10"),
                ),
            ],
            drawdown_pct=42.0,  # Past RUIN_DRAWDOWN_PCT (40)
        )

        # Even with the asset NOT agent-managed, the global ruin gate should
        # still fire and close the position because it's structured in tick()
        # before the per-market loop.
        with patch(
            "cli.daemon.iterators.execution_engine.is_agent_managed",
            return_value=False,
        ):
            it.tick(ctx)

        # The ruin alert should be present
        ruin_alerts = [
            a for a in ctx.alerts
            if "RUIN PREVENTION" in a.message
        ]
        assert len(ruin_alerts) == 1
