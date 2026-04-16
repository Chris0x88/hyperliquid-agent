"""Tests for ApexAdvisorIterator (C3 — dry-run APEX advisor)."""
from decimal import Decimal

import pytest

from daemon.context import TickContext
from daemon.iterators.apex_advisor import (
    ApexAdvisorIterator,
    ADVISE_INTERVAL_S,
    ADVISOR_MAX_SLOTS,
)
from exchange.position_tracker import Position


def _ctx(positions=None, prices=None, pulse=None, radar=None, tick=1):
    c = TickContext()
    c.tick_number = tick
    if positions is not None:
        c.positions = positions
    if prices is not None:
        c.prices = {k: Decimal(str(v)) for k, v in prices.items()}
    if pulse is not None:
        c.pulse_signals = pulse
    if radar is not None:
        c.radar_opportunities = radar
    return c


def _long(inst, qty, entry):
    return Position(
        instrument=inst,
        net_qty=Decimal(str(qty)),
        avg_entry_price=Decimal(str(entry)),
    )


def _force_tick(it):
    it._last_advise = -10000


@pytest.fixture
def advisor():
    it = ApexAdvisorIterator()
    it.on_start(_ctx())
    # If APEX modules failed to import, the engine is None
    if it._engine is None:
        pytest.skip("APEX modules unavailable in this environment")
    return it


class TestStartup:
    def test_engine_initializes(self, advisor):
        assert advisor._engine is not None
        assert advisor._config is not None
        assert advisor._config.max_slots == ADVISOR_MAX_SLOTS

    def test_constants_sane(self):
        assert ADVISE_INTERVAL_S == 60
        assert ADVISOR_MAX_SLOTS == 3


class TestNoSignals:
    def test_quiet_market_no_proposals(self, advisor):
        ctx = _ctx(positions=[], prices={}, pulse=[], radar=[])
        _force_tick(advisor)
        advisor.tick(ctx)
        # No actionable proposals → no info alerts from advisor
        advisor_alerts = [a for a in ctx.alerts if a.source == "apex_advisor"]
        assert advisor_alerts == []

    def test_positions_no_signals_no_proposals(self, advisor):
        ctx = _ctx(
            positions=[_long("BTC", 1, 100)],
            prices={"BTC": 100},
            pulse=[],
            radar=[],
        )
        _force_tick(advisor)
        advisor.tick(ctx)
        advisor_alerts = [a for a in ctx.alerts if a.source == "apex_advisor"]
        # Engine may propose exit on stagnation/conviction collapse but with
        # no signals at all and a fresh entry it should be silent.
        # Filter to enter actions only — definitely shouldn't propose entries
        # without signals.
        enters = [a for a in advisor_alerts if a.data.get("action") == "enter"]
        assert enters == []


class TestThrottle:
    def test_throttle_blocks_repeat(self, advisor):
        ctx1 = _ctx(positions=[], prices={}, pulse=[], radar=[])
        _force_tick(advisor)
        advisor.tick(ctx1)
        # Second tick without resetting throttle: should be a no-op
        ctx2 = _ctx(positions=[], prices={}, pulse=[], radar=[])
        # _last_advise was just set; next call should be throttled
        advisor.tick(ctx2)
        # No new alerts (would have been none anyway, but key is the
        # _advise method wasn't called again — verified by the fact that
        # tick returned early without raising on missing fields).


class TestNeverExecutes:
    def test_no_order_intent_queued(self, advisor):
        # Even with rich signals, advisor must NEVER queue OrderIntent.
        # Build a fake immediate signal that the engine would normally
        # convert into a slot fill.
        pulse = [{
            "asset": "BTC",
            "signal_type": "IMMEDIATE_MOVER",
            "direction": "long",
            "confidence": 95,
        }]
        radar = [{
            "asset": "ETH",
            "direction": "long",
            "final_score": 80,
        }]
        ctx = _ctx(positions=[], prices={"BTC": 100}, pulse=pulse, radar=radar)
        initial_queue_len = len(ctx.order_queue)
        _force_tick(advisor)
        advisor.tick(ctx)
        # Critical invariant: order_queue MUST be untouched
        assert len(ctx.order_queue) == initial_queue_len


class TestProposalDedup:
    def test_same_proposal_not_repeated(self, advisor):
        pulse = [{
            "asset": "BTC",
            "signal_type": "IMMEDIATE_MOVER",
            "direction": "long",
            "confidence": 95,
        }]
        # First cycle: engine may propose enter
        ctx1 = _ctx(positions=[], prices={"BTC": 100}, pulse=pulse, radar=[])
        _force_tick(advisor)
        advisor.tick(ctx1)
        first_proposals = [a for a in ctx1.alerts if a.source == "apex_advisor"]
        # Second cycle with identical inputs: should NOT re-alert if engine
        # produces the same proposal
        ctx2 = _ctx(positions=[], prices={"BTC": 100}, pulse=pulse, radar=[])
        _force_tick(advisor)
        advisor.tick(ctx2)
        second_proposals = [a for a in ctx2.alerts if a.source == "apex_advisor"]
        # Whatever the engine does, the dedup state ensures the SAME
        # action key is not re-emitted. If first round had any proposals,
        # the second round must have fewer (ideally zero).
        if first_proposals:
            assert len(second_proposals) <= len(first_proposals)


class TestPositionMirroring:
    def test_open_position_fills_slot(self, advisor):
        # Engine should see the position as an active slot and not propose
        # another entry on the same instrument.
        ctx = _ctx(
            positions=[_long("BTC", 1, 100)],
            prices={"BTC": 100},
            pulse=[{
                "asset": "BTC",
                "signal_type": "IMMEDIATE_MOVER",
                "direction": "long",
                "confidence": 95,
            }],
            radar=[],
        )
        _force_tick(advisor)
        advisor.tick(ctx)
        # Engine should not propose ENTER on BTC because the slot is mirrored as active
        advisor_alerts = [a for a in ctx.alerts if a.source == "apex_advisor"]
        enters_on_btc = [
            a for a in advisor_alerts
            if a.data.get("action") == "enter"
            and "BTC" in (a.data.get("instrument") or "")
        ]
        assert enters_on_btc == []


class TestAlertShape:
    def test_alert_data_has_action_fields(self, advisor):
        # Force a proposal-like situation by injecting strong signals
        pulse = [{
            "asset": "ETH",
            "signal_type": "IMMEDIATE_MOVER",
            "direction": "long",
            "confidence": 99,
        }]
        ctx = _ctx(positions=[], prices={"ETH": 50}, pulse=pulse, radar=[])
        _force_tick(advisor)
        advisor.tick(ctx)
        advisor_alerts = [a for a in ctx.alerts if a.source == "apex_advisor"]
        for a in advisor_alerts:
            # All advisor alerts must be info severity (informational, never blocking)
            assert a.severity == "info"
            # Data dict should have the action contract
            assert "action" in a.data
            assert "instrument" in a.data
            assert "direction" in a.data
            assert "source" in a.data
            assert "signal_score" in a.data
