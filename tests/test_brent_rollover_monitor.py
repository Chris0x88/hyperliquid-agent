"""Tests for BrentRolloverMonitorIterator (C7 — futures roll alerts)."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from cli.daemon.context import TickContext
from cli.daemon.iterators.brent_rollover_monitor import (
    BrentRolloverMonitorIterator,
    THRESHOLDS,
    CHECK_INTERVAL_S,
)


def _today():
    return datetime.now(timezone.utc).date()


def _date_str(days_offset: int) -> str:
    return (_today() + timedelta(days=days_offset)).isoformat()


@pytest.fixture
def tmp_calendar():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


def _write(path, contracts):
    with open(path, "w") as f:
        json.dump({"brent_futures": contracts}, f)


def _ctx():
    return TickContext()


def _force_tick(it):
    """Bypass the throttle so tick() actually runs."""
    it._last_check = -10000


class TestEmpty:
    def test_no_config_file_uses_seed_calendar(self, tmp_calendar):
        # When the config file doesn't exist, the iterator falls back to
        # DEFAULT_CALENDAR so it works out-of-the-box. The seed dates are
        # in 2026 and may or may not generate alerts depending on the
        # current real date — we only assert that the calendar loaded.
        os.unlink(tmp_calendar)
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        assert len(it._calendar) > 0  # seed loaded
        # Whether it alerts depends on real-world date vs seed dates.
        # This test only confirms the seed path works without crashing.
        ctx = _ctx()
        _force_tick(it)
        it.tick(ctx)  # must not raise

    def test_empty_calendar_silent(self, tmp_calendar):
        _write(tmp_calendar, [])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        ctx = _ctx()
        _force_tick(it)
        it.tick(ctx)
        assert ctx.alerts == []

    def test_malformed_json_silent_warning(self, tmp_calendar):
        with open(tmp_calendar, "w") as f:
            f.write("not valid json {")
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        ctx = _ctx()
        _force_tick(it)
        it.tick(ctx)
        assert ctx.alerts == []  # logged as warning, no alert spam


class TestThresholds:
    def test_far_future_no_alert(self, tmp_calendar):
        _write(tmp_calendar, [
            {"contract": "BZK6", "last_trading": _date_str(30)},
        ])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        ctx = _ctx()
        _force_tick(it)
        it.tick(ctx)
        assert ctx.alerts == []

    def test_seven_days_out_info(self, tmp_calendar):
        _write(tmp_calendar, [
            {"contract": "BZK6", "last_trading": _date_str(7)},
        ])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        ctx = _ctx()
        _force_tick(it)
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        a = ctx.alerts[0]
        assert a.severity == "info"
        assert "BZK6" in a.message
        assert a.data["days_out"] == 7

    def test_three_days_out_warning(self, tmp_calendar):
        _write(tmp_calendar, [
            {"contract": "BZM6", "last_trading": _date_str(3)},
        ])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        ctx = _ctx()
        _force_tick(it)
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "warning"

    def test_one_day_out_critical(self, tmp_calendar):
        _write(tmp_calendar, [
            {"contract": "BZN6", "last_trading": _date_str(1)},
        ])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        ctx = _ctx()
        _force_tick(it)
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "critical"
        assert "TOMORROW" in ctx.alerts[0].message

    def test_today_critical(self, tmp_calendar):
        _write(tmp_calendar, [
            {"contract": "BZQ6", "last_trading": _date_str(0)},
        ])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        ctx = _ctx()
        _force_tick(it)
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "critical"
        assert "TODAY" in ctx.alerts[0].message

    def test_past_event_info_rolled(self, tmp_calendar):
        _write(tmp_calendar, [
            {"contract": "BZJ6", "last_trading": _date_str(-3)},
        ])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        ctx = _ctx()
        _force_tick(it)
        it.tick(ctx)
        assert len(ctx.alerts) == 1
        assert ctx.alerts[0].severity == "info"
        assert "back-month" in ctx.alerts[0].message


class TestNoSpam:
    def test_same_threshold_only_alerts_once(self, tmp_calendar):
        _write(tmp_calendar, [
            {"contract": "BZK6", "last_trading": _date_str(7)},
        ])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        # Tick 1
        ctx1 = _ctx()
        _force_tick(it)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        # Tick 2 — same situation, no new alert
        ctx2 = _ctx()
        _force_tick(it)
        it.tick(ctx2)
        assert ctx2.alerts == []

    def test_reload_clears_fired(self, tmp_calendar):
        _write(tmp_calendar, [
            {"contract": "BZK6", "last_trading": _date_str(7)},
        ])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        ctx1 = _ctx()
        _force_tick(it)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        # Rewrite the calendar — mtime advances
        import time
        time.sleep(0.05)
        _write(tmp_calendar, [
            {"contract": "BZK6", "last_trading": _date_str(7)},
            {"contract": "BZM6", "last_trading": _date_str(3)},
        ])
        ctx2 = _ctx()
        _force_tick(it)
        it.tick(ctx2)
        # Both contracts re-alert (state cleared)
        assert len(ctx2.alerts) == 2


class TestBothEvents:
    def test_first_notice_and_last_trading_independent(self, tmp_calendar):
        _write(tmp_calendar, [
            {
                "contract": "BZM6",
                "last_trading": _date_str(7),
                "first_notice": _date_str(3),
            },
        ])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        ctx = _ctx()
        _force_tick(it)
        it.tick(ctx)
        assert len(ctx.alerts) == 2
        events = {a.data["event"] for a in ctx.alerts}
        assert events == {"last_trading", "first_notice"}


class TestThrottle:
    def test_throttle_blocks_repeat_within_interval(self, tmp_calendar):
        _write(tmp_calendar, [
            {"contract": "BZK6", "last_trading": _date_str(7)},
        ])
        it = BrentRolloverMonitorIterator(config_path=tmp_calendar)
        it.on_start(_ctx())
        # Force tick once
        ctx1 = _ctx()
        _force_tick(it)
        it.tick(ctx1)
        assert len(ctx1.alerts) == 1
        # Without bypassing throttle, second tick should NOT execute logic
        ctx2 = _ctx()
        # _last_check is now ~current monotonic
        it.tick(ctx2)
        assert ctx2.alerts == []  # throttled

    def test_throttle_constant(self):
        assert CHECK_INTERVAL_S == 3600
