"""Tests for ProtectionAuditIterator (C1' — read-only stop verification)."""
from decimal import Decimal
from unittest.mock import patch

import pytest

from cli.daemon.context import TickContext
from cli.daemon.iterators.protection_audit import (
    ProtectionAuditIterator,
    _coin_matches,
    MIN_STOP_DISTANCE_PCT,
    MAX_STOP_DISTANCE_PCT,
)
from parent.position_tracker import Position


def _ctx(positions=None, prices=None, tick=1):
    c = TickContext()
    c.tick_number = tick
    if positions:
        c.positions = positions
    if prices:
        c.prices = {k: Decimal(str(v)) for k, v in prices.items()}
    return c


def _long(inst, qty, entry, lev=10):
    return Position(
        instrument=inst,
        net_qty=Decimal(str(qty)),
        avg_entry_price=Decimal(str(entry)),
        leverage=Decimal(str(lev)),
    )


def _short(inst, qty, entry, lev=10):
    return Position(
        instrument=inst,
        net_qty=Decimal(str(-abs(qty))),
        avg_entry_price=Decimal(str(entry)),
        leverage=Decimal(str(lev)),
    )


def _stop(coin, trigger_px, tpsl="sl"):
    """Build a fake trigger order dict mirroring HL frontendOpenOrders shape."""
    return {
        "coin": coin,
        "triggerPx": str(trigger_px),
        "tpsl": tpsl,
        "isTrigger": True,
        "orderType": "Stop Market",
    }


def _tp(coin, trigger_px):
    return {
        "coin": coin,
        "triggerPx": str(trigger_px),
        "tpsl": "tp",
        "isTrigger": True,
        "orderType": "Take Profit Market",
    }


@pytest.fixture
def iterator():
    it = ProtectionAuditIterator()
    # Force a check on every tick by zeroing throttle
    it._last_check = -10000
    return it


def _patch_fetch(it, triggers):
    """Patch the iterator's _fetch_all_triggers to return a fixed list."""
    it._fetch_all_triggers = lambda: triggers
    # Also prevent throttle from blocking
    it._last_check = -10000


class TestCoinMatches:
    def test_exact_match(self):
        assert _coin_matches("BTC", "BTC")
        assert _coin_matches("xyz:BRENTOIL", "xyz:BRENTOIL")

    def test_xyz_prefix_handled(self):
        assert _coin_matches("xyz:BRENTOIL", "BRENTOIL")
        assert _coin_matches("BRENTOIL", "xyz:BRENTOIL")

    def test_no_false_match(self):
        assert not _coin_matches("BTC", "ETH")
        assert not _coin_matches("xyz:GOLD", "xyz:SILVER")


class TestNoPositions:
    def test_skip_when_no_positions(self, iterator):
        _patch_fetch(iterator, [])
        ctx = _ctx(positions=[], prices={})
        iterator.tick(ctx)
        assert ctx.alerts == []

    def test_state_cleared_when_positions_close(self, iterator):
        # Initial: position with no stop
        _patch_fetch(iterator, [])
        ctx1 = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx1)
        assert "BTC" in iterator._last_state
        # Position closes
        iterator._last_check = -10000  # reset throttle
        ctx2 = _ctx(positions=[], prices={})
        iterator.tick(ctx2)
        assert iterator._last_state == {}


class TestNoStop:
    def test_critical_alert_when_position_unguarded(self, iterator):
        _patch_fetch(iterator, [])  # no triggers at all
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        a = ctx.alerts[0]
        assert a.severity == "critical"
        assert "UNGUARDED" in a.message
        assert "BTC" in a.message
        assert "LONG" in a.message
        assert a.data["state"] == "no_stop"

    def test_no_repeat_alert_within_no_stop_state(self, iterator):
        _patch_fetch(iterator, [])
        ctx1 = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx1)
        assert len(ctx1.alerts) == 1
        # Same situation next tick — no repeat
        iterator._last_check = -10000
        ctx2 = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx2)
        assert ctx2.alerts == []

    def test_takes_profit_only_still_counts_as_unguarded(self, iterator):
        # TP exists, but no SL — still UNGUARDED (no_stop > no_tp priority)
        _patch_fetch(iterator, [_tp("BTC", 120)])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "critical"
        assert "UNGUARDED" in ctx.alerts[0].message


class TestWrongSideStop:
    def test_long_with_stop_above_entry(self, iterator):
        # stop above entry for long = wrong; include TP so no_tp doesn't intercept first
        _patch_fetch(iterator, [_stop("BTC", 110), _tp("BTC", 120)])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        a = ctx.alerts[0]
        assert a.severity == "critical"
        assert "WRONG-SIDE" in a.message
        assert a.data["state"] == "wrong_side"

    def test_short_with_stop_below_entry(self, iterator):
        # stop below entry for short = wrong; include TP so no_tp doesn't intercept first
        _patch_fetch(iterator, [_stop("BTC", 90), _tp("BTC", 80)])
        ctx = _ctx(positions=[_short("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "critical"
        assert "WRONG-SIDE" in ctx.alerts[0].message


class TestStopDistance:
    def test_too_close(self, iterator):
        # mark=100, stop=99.9, distance=0.1% < 0.5% min; include TP so no_tp doesn't intercept
        _patch_fetch(iterator, [_stop("BTC", 99.9), _tp("BTC", 110)])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "warning"
        assert "TOO CLOSE" in ctx.alerts[0].message
        assert ctx.alerts[0].data["state"] == "too_close"

    def test_too_far(self, iterator):
        # mark=100, stop=40, distance=60% > 50% max; include TP so no_tp doesn't intercept
        _patch_fetch(iterator, [_stop("BTC", 40), _tp("BTC", 150)])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "warning"
        assert "TOO FAR" in ctx.alerts[0].message
        assert ctx.alerts[0].data["state"] == "too_far"

    def test_reasonable_stop_no_alert(self, iterator):
        # mark=100, stop=95, distance=5% — between 0.5% and 50%; include TP
        _patch_fetch(iterator, [_stop("BTC", 95), _tp("BTC", 115)])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert ctx.alerts == []
        assert iterator._last_state["BTC"] == "ok"


class TestRecovery:
    def test_recovery_alert_from_no_stop_to_ok(self, iterator):
        # Tick 1: no stop, no TP
        _patch_fetch(iterator, [])
        ctx1 = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx1)
        assert ctx1.alerts[0].severity == "critical"
        # Tick 2: both SL and TP appear (heartbeat caught up); both needed for recovery to ok
        iterator._last_check = -10000
        _patch_fetch(iterator, [_stop("BTC", 95), _tp("BTC", 115)])
        ctx2 = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx2)
        assert len(ctx2.alerts) == 1
        assert ctx2.alerts[0].severity == "info"
        assert "RESTORED" in ctx2.alerts[0].message


class TestXyzPrefix:
    def test_xyz_position_with_xyz_stop(self, iterator):
        # Include TP — position is fully protected; tests xyz prefix matching for both
        _patch_fetch(iterator, [_stop("xyz:BRENTOIL", 80), _tp("xyz:BRENTOIL", 92)])
        ctx = _ctx(
            positions=[_long("xyz:BRENTOIL", 10, 85)],
            prices={"xyz:BRENTOIL": 85},
        )
        iterator.tick(ctx)
        assert ctx.alerts == []  # ok

    def test_xyz_position_with_unprefixed_stop(self, iterator):
        # Stop and TP triggers have unprefixed coin name (some HL responses do this)
        _patch_fetch(iterator, [_stop("BRENTOIL", 80), _tp("BRENTOIL", 92)])
        ctx = _ctx(
            positions=[_long("xyz:BRENTOIL", 10, 85)],
            prices={"xyz:BRENTOIL": 85},
        )
        iterator.tick(ctx)
        assert ctx.alerts == []  # _coin_matches handles both for SL and TP


class TestMultiplePositions:
    def test_independent_state_per_instrument(self, iterator):
        _patch_fetch(iterator, [
            _stop("BTC", 95),       # ok (with TP)
            _tp("BTC", 115),        # BTC fully protected
            _stop("ETH", 49.9),     # too close (0.2% from mark 50) (with TP)
            _tp("ETH", 55),         # ETH TP present
            # SOL: no stop, no TP → no_stop (highest priority)
        ])
        ctx = _ctx(
            positions=[
                _long("BTC", 1, 100),
                _long("ETH", 10, 50),
                _long("SOL", 5, 200),  # no stop at all → no_stop critical
            ],
            prices={"BTC": 100, "ETH": 50, "SOL": 200},
        )
        iterator.tick(ctx)
        # BTC: ok (no alert)
        # ETH: too close warning
        # SOL: no stop critical (no_stop > no_tp priority so still "UNGUARDED")
        severities = sorted(a.severity for a in ctx.alerts)
        assert severities == ["critical", "warning"]
        instruments = {a.data["instrument"] for a in ctx.alerts}
        assert instruments == {"ETH", "SOL"}


class TestUnavailableState:
    def test_fetch_returns_none_skips_cycle(self, iterator):
        iterator._fetch_all_triggers = lambda: None
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert ctx.alerts == []  # silent skip, no false alarm


# ---------------------------------------------------------------------------
# Bug #4 regression: HL frontendOpenOrders does NOT populate the ``tpsl`` field.
# Only ``orderType`` distinguishes "Stop Market" from "Take Profit Market".
# Before the fix, the fallback in _is_stop_trigger defaulted to True for any
# order with ``isTrigger=True``, so a real-world TP slipped into stops_by_coin
# and got side-checked as a stop — emitting a spurious WRONG-SIDE STOP alert.
# These tests use the EXACT shape HL returned for an xyz:SP500 TP on
# 2026-04-08 to lock in the fix.
# ---------------------------------------------------------------------------


def _hl_real_tp(coin: str, trigger_px: float, sz: float = 1.0) -> dict:
    """Trigger order in the exact shape HL frontendOpenOrders returns for a TP.

    Notice: NO ``tpsl`` field. Only ``orderType="Take Profit Market"``
    differentiates this from a stop. This is the shape that bit us on
    xyz:SP500 LONG with TP at 6773.9.
    """
    return {
        "coin": coin,
        "side": "A",
        "limitPx": str(trigger_px),
        "sz": str(sz),
        "oid": 999_999_999,
        "timestamp": 1775571936850,
        "triggerCondition": f"Price above {trigger_px}",
        "isTrigger": True,
        "triggerPx": str(trigger_px),
        "children": [],
        "isPositionTpsl": False,
        "reduceOnly": True,
        "orderType": "Take Profit Market",
        "origSz": str(sz),
        "tif": None,
        "cloid": None,
    }


def _hl_real_sl(coin: str, trigger_px: float, sz: float = 1.0) -> dict:
    """Trigger order in the exact shape HL frontendOpenOrders returns for an SL.

    Same as the TP shape but ``orderType="Stop Market"``. Notably, no ``tpsl``.
    """
    return {
        "coin": coin,
        "side": "A",
        "limitPx": str(trigger_px),
        "sz": str(sz),
        "oid": 999_999_998,
        "timestamp": 1775571933820,
        "triggerCondition": f"Price below {trigger_px}",
        "isTrigger": True,
        "triggerPx": str(trigger_px),
        "children": [],
        "isPositionTpsl": False,
        "reduceOnly": True,
        "orderType": "Stop Market",
        "origSz": str(sz),
        "tif": None,
        "cloid": None,
    }


class TestRealHLTriggerShape:
    """Bug #4 regression — HL frontendOpenOrders shape lacks the ``tpsl`` field."""

    def test_is_stop_trigger_recognises_real_hl_sl(self):
        order = _hl_real_sl("xyz:SP500", 6431.8)
        assert ProtectionAuditIterator._is_stop_trigger(order) is True

    def test_is_stop_trigger_recognises_real_hl_tp_as_not_stop(self):
        order = _hl_real_tp("xyz:SP500", 6773.9)
        assert ProtectionAuditIterator._is_stop_trigger(order) is False

    def test_is_stop_trigger_unknown_order_type_defaults_to_not_stop(self):
        """Conservative default — anything unrecognised is treated as NOT a stop."""
        order = {"coin": "X", "isTrigger": True, "triggerCondition": "weird"}
        assert ProtectionAuditIterator._is_stop_trigger(order) is False

    def test_real_hl_tp_only_position_alerts_unguarded(self, iterator):
        """A LONG with only a TP (HL real shape) should still trigger UNGUARDED.

        This was already correct but locks the behavior in: the TP must NOT
        be confused for an SL. With only a TP, the position is genuinely
        unprotected on the loss side and protection_audit should say so.
        """
        _patch_fetch(iterator, [_hl_real_tp("xyz:SP500", 6773.9, sz=0.6)])
        ctx = _ctx(
            positions=[_long("xyz:SP500", 0.6, 6564.5)],
            prices={"xyz:SP500": 6564.5},
        )
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "critical"
        assert "UNGUARDED" in ctx.alerts[0].message

    def test_real_hl_tp_above_long_entry_does_NOT_emit_wrong_side(self, iterator):
        """The exact bug Chris hit: TP at 6773.9 on a LONG @ 6564.5.

        Before the fix this fired a spurious WRONG-SIDE STOP CRITICAL alert
        because the fallback ``bool(isTrigger)`` returned True for the TP and
        the side check then flagged it as wrong-side (which it would be — IF
        it were actually a stop, which it isn't).
        """
        _patch_fetch(iterator, [_hl_real_tp("xyz:SP500", 6773.9, sz=0.6)])
        ctx = _ctx(
            positions=[_long("xyz:SP500", 0.6, 6564.5)],
            prices={"xyz:SP500": 6564.5},
        )
        iterator.tick(ctx)
        # The TP is correctly classified as NOT a stop, so the alert is
        # UNGUARDED (no SL on the position), NOT WRONG-SIDE STOP.
        assert all("WRONG-SIDE" not in a.message for a in ctx.alerts), \
            f"Real-shape TP should not produce WRONG-SIDE alert; got {[a.message for a in ctx.alerts]}"

    def test_real_hl_sl_and_tp_together_only_sl_used(self, iterator):
        """A position with BOTH a real SL and TP — only the SL feeds the side check."""
        _patch_fetch(iterator, [
            _hl_real_sl("xyz:SP500", 6431.8, sz=0.6),
            _hl_real_tp("xyz:SP500", 6773.9, sz=0.6),
        ])
        ctx = _ctx(
            positions=[_long("xyz:SP500", 0.6, 6564.5)],
            prices={"xyz:SP500": 6500.0},
        )
        iterator.tick(ctx)
        # The SL at 6431.8 is below entry 6564.5 → correct side. No alerts.
        # The TP must NOT be considered for side check.
        assert all("WRONG-SIDE" not in a.message for a in ctx.alerts), \
            f"Got unexpected alerts: {[a.message for a in ctx.alerts]}"
        # Distance from mark 6500 to stop 6431.8 = 1.05% — between 0.5% and 50%
        # → no distance alert either
        assert ctx.alerts == [], f"Expected no alerts; got {[a.message for a in ctx.alerts]}"


# ---------------------------------------------------------------------------
# FEATURE 2026-04-08: Missing TP audit — CLAUDE.md "both SL and TP" rule.
# A position with an SL but no TP must emit a CRITICAL "no_tp" alert.
# Priority: no_stop > no_tp > wrong_side > too_close > too_far > ok.
# ---------------------------------------------------------------------------

class TestNoTp:
    def test_sl_only_position_alerts_no_tp(self, iterator):
        """SL present but no TP -> CRITICAL UNPROTECTED alert with state=no_tp."""
        _patch_fetch(iterator, [_stop("BTC", 95)])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        a = ctx.alerts[0]
        assert a.severity == "critical"
        assert "UNPROTECTED" in a.message
        assert "BTC" in a.message
        assert "LONG" in a.message
        # 2026-04-08 alert reformat: phrase changed from "NO take-profit"
        # to "No exchange take-profit" — same semantic, friendlier wording.
        # data["state"] is the source of truth; the phrase check is just a
        # belt-and-braces sanity check on the human-readable message.
        assert "take-profit" in a.message
        assert a.data["state"] == "no_tp"

    def test_neither_sl_nor_tp_alerts_unguarded_not_no_tp(self, iterator):
        """No SL and no TP -> UNGUARDED (no_stop is higher priority than no_tp)."""
        _patch_fetch(iterator, [])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].data["state"] == "no_stop"
        assert "UNGUARDED" in ctx.alerts[0].message

    def test_both_sl_and_tp_present_no_alert(self, iterator):
        """SL below entry and TP above entry -> fully protected, no alert."""
        _patch_fetch(iterator, [_stop("BTC", 95), _tp("BTC", 115)])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert ctx.alerts == []
        assert iterator._last_state["BTC"] == "ok"

    def test_both_present_wrong_side_sl_fires_wrong_side(self, iterator):
        """SL wrong side + TP present -> wrong_side alert (no_tp does not fire)."""
        _patch_fetch(iterator, [_stop("BTC", 110), _tp("BTC", 120)])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].data["state"] == "wrong_side"
        assert "WRONG-SIDE" in ctx.alerts[0].message

    def test_no_tp_state_no_repeat_alert(self, iterator):
        """Same no_tp state across ticks -> alert fires once, then silent."""
        _patch_fetch(iterator, [_stop("BTC", 95)])
        ctx1 = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx1)
        assert len(ctx1.alerts) == 1
        assert ctx1.alerts[0].data["state"] == "no_tp"
        # Same state next tick — no repeat
        iterator._last_check = -10000
        ctx2 = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx2)
        assert ctx2.alerts == []

    def test_real_hl_sl_only_alerts_no_tp(self, iterator):
        """Real HL shape SL-only position -> no_tp critical fires."""
        _patch_fetch(iterator, [_hl_real_sl("BTC", 95)])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].data["state"] == "no_tp"
        assert "UNPROTECTED" in ctx.alerts[0].message

    def test_real_hl_sl_and_tp_both_present_no_alert(self, iterator):
        """Real HL shape with both SL and TP -> fully protected, no alert."""
        _patch_fetch(iterator, [
            _hl_real_sl("BTC", 95),
            _hl_real_tp("BTC", 115),
        ])
        ctx = _ctx(positions=[_long("BTC", 1, 100)], prices={"BTC": 100})
        iterator.tick(ctx)
        assert ctx.alerts == []
        assert iterator._last_state["BTC"] == "ok"

    def test_is_tp_trigger_recognises_real_hl_tp(self):
        """_is_tp_trigger correctly identifies a real HL Take Profit Market order."""
        order = _hl_real_tp("xyz:SP500", 6773.9)
        assert ProtectionAuditIterator._is_tp_trigger(order) is True

    def test_is_tp_trigger_rejects_real_hl_sl(self):
        """_is_tp_trigger returns False for a real HL Stop Market order."""
        order = _hl_real_sl("xyz:SP500", 6431.8)
        assert ProtectionAuditIterator._is_tp_trigger(order) is False

    def test_is_tp_trigger_unknown_defaults_to_false(self):
        """Conservative default — unrecognised orderType is NOT classified as TP."""
        order = {"coin": "X", "isTrigger": True, "triggerCondition": "weird"}
        assert ProtectionAuditIterator._is_tp_trigger(order) is False
