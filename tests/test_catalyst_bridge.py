import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from engines.learning.news_engine import Catalyst
from engines.data.catalyst_bridge import catalyst_to_events, persist


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


def _make_catalyst(cat_id: str, severity: int) -> Catalyst:
    return Catalyst(
        id=cat_id,
        headline_id=f"h-{cat_id}",
        instruments=["CL"],
        event_date=datetime(2026, 4, 10, tzinfo=timezone.utc),
        category="physical_damage_facility",
        severity=severity,
        expected_direction="bull",
        rationale="test",
        created_at=datetime(2026, 4, 9, tzinfo=timezone.utc),
    )


def test_persist_severity_floor_filters():
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/out.json"
        cats = [_make_catalyst("a", 2), _make_catalyst("b", 5)]
        added = persist(cats, path, severity_floor=3)
        assert added == 1  # only severity 5 made it through
        events = json.loads(open(path).read())["events"]
        assert len(events) == 1
        assert events[0]["name"] == "b-CL"


def test_persist_dedupes_on_second_call():
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/out.json"
        cat = _make_catalyst("a", 5)
        added1 = persist([cat], path, severity_floor=3)
        added2 = persist([cat], path, severity_floor=3)
        assert added1 == 1
        assert added2 == 0  # same name → not re-added
        events = json.loads(open(path).read())["events"]
        assert len(events) == 1


def test_persist_preserves_existing_events():
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/out.json"
        # seed with a handwritten CatalystEvent
        initial = {
            "events": [{
                "name": "handwritten-CL",
                "instrument": "CL",
                "event_date": "2026-04-15",
                "pre_event_hours": 24,
                "reduce_leverage_to": None,
                "reduce_size_pct": 0.3,
                "post_event_hours": 12,
                "executed": False,
            }]
        }
        Path(path).write_text(json.dumps(initial))
        persist([_make_catalyst("b", 5)], path, severity_floor=3)
        events = json.loads(open(path).read())["events"]
        names = [e["name"] for e in events]
        assert "handwritten-CL" in names
        assert "b-CL" in names
        assert len(events) == 2
