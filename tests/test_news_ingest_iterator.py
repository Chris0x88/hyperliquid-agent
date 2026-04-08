import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from cli.daemon.iterators.news_ingest import NewsIngestIterator


def test_iterator_has_name():
    it = NewsIngestIterator()
    assert it.name == "news_ingest"


def test_kill_switch_enabled_false_noop():
    with tempfile.TemporaryDirectory() as d:
        config_path = Path(d) / "news_ingest.json"
        config_path.write_text(json.dumps({
            "enabled": False,
            "severity_floor": 5,
            "alert_floor": 4,
            "default_poll_interval_s": 60,
            "max_headlines_per_tick": 50,
            "headlines_jsonl": f"{d}/headlines.jsonl",
            "catalysts_jsonl": f"{d}/catalysts.jsonl",
            "external_catalyst_events_json": f"{d}/external_catalyst_events.json",
        }))
        it = NewsIngestIterator(config_path=str(config_path))
        ctx = MagicMock()
        ctx.timestamp = 1755000000
        ctx.alerts = []
        it.on_start(ctx)
        it.tick(ctx)

        # No files should have been written
        assert not Path(f"{d}/headlines.jsonl").exists()
        assert not Path(f"{d}/catalysts.jsonl").exists()
        assert not Path(f"{d}/external_catalyst_events.json").exists()
