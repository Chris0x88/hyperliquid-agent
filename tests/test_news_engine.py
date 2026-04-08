from datetime import datetime, timezone
from modules.news_engine import Headline, Catalyst


def test_headline_dataclass_constructs():
    h = Headline(
        id="abc123",
        source="reuters_energy",
        url="https://reuters.com/a",
        title="Drone strike hits refinery",
        body_excerpt="...",
        published_at=datetime(2026, 4, 8, 22, 14, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 4, 9, 5, 0, tzinfo=timezone.utc),
    )
    assert h.source == "reuters_energy"
    assert h.published_at.tzinfo is not None


def test_catalyst_dataclass_constructs():
    c = Catalyst(
        id="cat1",
        headline_id="abc123",
        instruments=["xyz:BRENTOIL", "CL"],
        event_date=datetime(2026, 4, 8, 22, 14, tzinfo=timezone.utc),
        category="physical_damage_facility",
        severity=5,
        expected_direction="bull",
        rationale="rule: physical_damage_facility matched [drone, strike, refinery]",
        created_at=datetime(2026, 4, 9, 5, 0, tzinfo=timezone.utc),
    )
    assert c.severity == 5
    assert "CL" in c.instruments
