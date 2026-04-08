import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
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


def _write_config(d, enabled=True, severity_floor=5):
    p = Path(d) / "news_ingest.json"
    p.write_text(json.dumps({
        "enabled": enabled,
        "severity_floor": severity_floor,
        "alert_floor": 4,
        "default_poll_interval_s": 60,
        "max_headlines_per_tick": 50,
        "headlines_jsonl": f"{d}/headlines.jsonl",
        "catalysts_jsonl": f"{d}/catalysts.jsonl",
        "external_catalyst_events_json": f"{d}/external_catalyst_events.json",
    }))
    return p


def _write_single_feed(d, fixture_name):
    p = Path(d) / "news_feeds.yaml"
    p.write_text(f"""
feeds:
  - name: test_feed
    url: https://example.com/feed
    poll_interval_s: 60
    weight: 1.0
    categories: [test]
    enabled: true
icals: []
""")
    return p, Path(__file__).parent / "fixtures" / "news" / fixture_name


def test_iterator_handles_failing_feed_without_crashing(tmp_path):
    cfg = _write_config(str(tmp_path))
    feeds, _ = _write_single_feed(str(tmp_path), "reuters_atom_sample.xml")
    it = NewsIngestIterator(
        config_path=str(cfg),
        feeds_path=str(feeds),
        rules_path="data/config/news_rules.yaml",
    )
    ctx = MagicMock()
    ctx.timestamp = int(time.time())
    ctx.alerts = []
    it.on_start(ctx)

    # Patch requests.get to raise
    with patch("cli.daemon.iterators.news_ingest.requests.get", side_effect=RuntimeError("boom")):
        it.tick(ctx)  # must not raise

    # No headlines written because fetch failed
    assert not Path(f"{tmp_path}/headlines.jsonl").exists()


def test_iterator_throttles_per_feed(tmp_path):
    cfg = _write_config(str(tmp_path))
    feeds, fixture = _write_single_feed(str(tmp_path), "reuters_atom_sample.xml")
    xml = fixture.read_text()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = xml

    it = NewsIngestIterator(
        config_path=str(cfg),
        feeds_path=str(feeds),
        rules_path="data/config/news_rules.yaml",
    )
    ctx = MagicMock()
    ctx.timestamp = int(time.time())
    ctx.alerts = []
    it.on_start(ctx)

    with patch("cli.daemon.iterators.news_ingest.requests.get", return_value=mock_response) as m:
        it.tick(ctx)
        it.tick(ctx)  # second tick within throttle window
        assert m.call_count == 1  # throttled to one poll
