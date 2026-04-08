from datetime import datetime, timezone
from modules.news_engine import Catalyst
from modules.catalyst_bridge import catalyst_to_events


def test_catalyst_with_two_instruments_fans_out():
    c = Catalyst(
        id="cat1",
        headline_id="h1",
        instruments=["xyz:BRENTOIL", "CL"],
        event_date=datetime(2026, 4, 10, 20, 0, tzinfo=timezone.utc),
        category="trump_oil_announcement",
        severity=4,
        expected_direction=None,
        rationale="rule: trump_oil_announcement",
        created_at=datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc),
    )
    events = catalyst_to_events(c)
    assert len(events) == 2
    instruments = [e.instrument for e in events]
    assert "xyz:BRENTOIL" in instruments
    assert "CL" in instruments
    for e in events:
        assert e.event_date == "2026-04-10"
        assert e.name.startswith("cat1-")
        assert e.pre_event_hours == 24
        assert e.executed is False
