"""Tests for cli/daemon/calendar_tags helper (C4)."""
from unittest.mock import MagicMock, patch

import pytest

from daemon import calendar_tags


@pytest.fixture(autouse=True)
def reset_cache():
    calendar_tags.reset_cache()
    yield
    calendar_tags.reset_cache()


class TestEmpty:
    def test_import_failure_returns_empty(self):
        with patch.dict("sys.modules", {"common.calendar": None}):
            # Force a fresh build
            calendar_tags.reset_cache()
            result = calendar_tags.get_current_tags()
        assert result["weekend"] is False
        assert result["thin_session"] is False
        assert result["high_impact_event_24h"] is False
        assert result["session"] == "unknown"
        assert result["tags"] == []

    def test_get_current_failure_returns_empty(self):
        fake_module = MagicMock()
        fake_module.CalendarContext.get_current.side_effect = RuntimeError("boom")
        with patch.dict("sys.modules", {"common.calendar": fake_module}):
            calendar_tags.reset_cache()
            result = calendar_tags.get_current_tags()
        assert result["tags"] == []
        assert result["weekend"] is False


class TestWeekend:
    def test_weekend_session_produces_weekend_tag(self):
        fake_session = MagicMock()
        fake_session.name = "weekend"
        fake_session.weekend = True
        fake_session.volume_profile = "thin"

        fake_ctx = MagicMock()
        fake_ctx.session = fake_session
        fake_ctx.events_next_48h = []

        fake_module = MagicMock()
        fake_module.CalendarContext.get_current.return_value = fake_ctx

        with patch.dict("sys.modules", {"common.calendar": fake_module}):
            calendar_tags.reset_cache()
            result = calendar_tags.get_current_tags()

        assert result["weekend"] is True
        assert result["thin_session"] is True
        assert "WEEKEND" in result["tags"]
        assert "THIN" in result["tags"]


class TestActiveSession:
    def test_us_session_normal_volume(self):
        fake_session = MagicMock()
        fake_session.name = "us"
        fake_session.weekend = False
        fake_session.volume_profile = "normal"

        fake_ctx = MagicMock()
        fake_ctx.session = fake_session
        fake_ctx.events_next_48h = []

        fake_module = MagicMock()
        fake_module.CalendarContext.get_current.return_value = fake_ctx

        with patch.dict("sys.modules", {"common.calendar": fake_module}):
            calendar_tags.reset_cache()
            result = calendar_tags.get_current_tags()

        assert result["weekend"] is False
        assert result["thin_session"] is False
        assert result["session"] == "us"
        assert "US" in result["tags"]


class TestEvents:
    def test_high_impact_event_within_24h_tagged(self):
        fake_session = MagicMock()
        fake_session.name = "us"
        fake_session.weekend = False
        fake_session.volume_profile = "normal"

        fake_ctx = MagicMock()
        fake_ctx.session = fake_session
        fake_ctx.events_next_48h = [
            {"name": "FOMC Decision", "hours_away": 12, "impact": "high"},
        ]

        fake_module = MagicMock()
        fake_module.CalendarContext.get_current.return_value = fake_ctx

        with patch.dict("sys.modules", {"common.calendar": fake_module}):
            calendar_tags.reset_cache()
            result = calendar_tags.get_current_tags()

        assert result["high_impact_event_24h"] is True
        # Tag list should contain the event name prefix
        assert any("EVENT<24H" in t for t in result["tags"])

    def test_low_impact_event_not_tagged(self):
        fake_session = MagicMock()
        fake_session.name = "us"
        fake_session.weekend = False
        fake_session.volume_profile = "normal"

        fake_ctx = MagicMock()
        fake_ctx.session = fake_session
        fake_ctx.events_next_48h = [
            {"name": "minor data", "hours_away": 6, "impact": "low"},
        ]

        fake_module = MagicMock()
        fake_module.CalendarContext.get_current.return_value = fake_ctx

        with patch.dict("sys.modules", {"common.calendar": fake_module}):
            calendar_tags.reset_cache()
            result = calendar_tags.get_current_tags()

        assert result["high_impact_event_24h"] is False

    def test_high_impact_event_beyond_24h_not_tagged(self):
        fake_session = MagicMock()
        fake_session.name = "us"
        fake_session.weekend = False
        fake_session.volume_profile = "normal"

        fake_ctx = MagicMock()
        fake_ctx.session = fake_session
        fake_ctx.events_next_48h = [
            {"name": "FOMC", "hours_away": 36, "impact": "high"},
        ]

        fake_module = MagicMock()
        fake_module.CalendarContext.get_current.return_value = fake_ctx

        with patch.dict("sys.modules", {"common.calendar": fake_module}):
            calendar_tags.reset_cache()
            result = calendar_tags.get_current_tags()

        assert result["high_impact_event_24h"] is False


class TestCaching:
    def test_cache_avoids_repeat_calls(self):
        fake_session = MagicMock()
        fake_session.name = "us"
        fake_session.weekend = False
        fake_session.volume_profile = "normal"

        fake_ctx = MagicMock()
        fake_ctx.session = fake_session
        fake_ctx.events_next_48h = []

        fake_module = MagicMock()
        fake_module.CalendarContext.get_current.return_value = fake_ctx

        with patch.dict("sys.modules", {"common.calendar": fake_module}):
            calendar_tags.reset_cache()
            calendar_tags.get_current_tags()
            calendar_tags.get_current_tags()
            calendar_tags.get_current_tags()
            assert fake_module.CalendarContext.get_current.call_count == 1


class TestRealCalendar:
    def test_real_calendar_does_not_crash(self):
        # Just calls the real thing — must not raise.
        calendar_tags.reset_cache()
        result = calendar_tags.get_current_tags()
        assert "weekend" in result
        assert "tags" in result
        assert isinstance(result["tags"], list)
