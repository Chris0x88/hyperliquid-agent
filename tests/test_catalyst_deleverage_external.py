import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from cli.daemon.iterators.catalyst_deleverage import CatalystDeleverageIterator, CatalystEvent


def test_add_external_catalysts_merges_and_dedupes():
    existing = [CatalystEvent(name="a", instrument="CL", event_date="2026-04-15")]
    it = CatalystDeleverageIterator(catalysts=existing)

    it.add_external_catalysts([
        CatalystEvent(name="b", instrument="CL", event_date="2026-04-16"),
        CatalystEvent(name="a", instrument="CL", event_date="2026-04-15"),  # duplicate
    ])

    names = [c.name for c in it._catalysts]
    assert "a" in names
    assert "b" in names
    assert len([n for n in names if n == "a"]) == 1  # not duplicated


def test_tick_loads_external_catalysts_from_file():
    with tempfile.TemporaryDirectory() as d:
        ext_path = Path(d) / "external_catalyst_events.json"
        ext_path.write_text(json.dumps({
            "events": [{
                "name": "news-event-1",
                "instrument": "CL",
                "event_date": "2026-04-20",
                "pre_event_hours": 24,
                "reduce_leverage_to": None,
                "reduce_size_pct": 0.25,
                "post_event_hours": 12,
                "executed": False,
            }]
        }))

        it = CatalystDeleverageIterator(data_dir=d)
        it._external_catalyst_path = ext_path  # inject for test

        # Fake TickContext
        ctx = MagicMock()
        ctx.timestamp = 1755000000
        ctx.positions = []
        ctx.alerts = []
        it._last_check = 0  # force check

        it.tick(ctx)
        assert any(c.name == "news-event-1" for c in it._catalysts)


def test_tick_missing_external_file_is_noop():
    with tempfile.TemporaryDirectory() as d:
        it = CatalystDeleverageIterator(data_dir=d)
        it._external_catalyst_path = Path(d) / "does_not_exist.json"
        ctx = MagicMock()
        ctx.timestamp = 1755000000
        ctx.positions = []
        ctx.alerts = []
        it._last_check = 0

        it.tick(ctx)  # must not raise
        assert it._catalysts == []
