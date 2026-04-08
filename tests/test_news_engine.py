from datetime import datetime, timezone
from pathlib import Path

from modules.news_engine import Headline, Catalyst, parse_feed, dedupe_headlines

FIXTURES = Path(__file__).parent / "fixtures" / "news"


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


def test_parse_atom_feed_well_formed():
    xml = (FIXTURES / "reuters_atom_sample.xml").read_text()
    entries = parse_feed(xml, source="reuters_energy")
    assert len(entries) == 2
    titles = [e.title for e in entries]
    assert "Drone strike hits Volgograd refinery, 200kbpd offline" in titles
    assert "Trump sets 8 PM deadline for Iran nuclear deal" in titles
    # All entries should have timezone-aware published_at
    for e in entries:
        assert e.published_at.tzinfo is not None
        assert e.source == "reuters_energy"
        assert e.id  # sha256 non-empty


def test_parse_rss20_well_formed():
    xml = (FIXTURES / "oilprice_rss20_sample.xml").read_text()
    entries = parse_feed(xml, source="oilprice_main")
    assert len(entries) == 2
    titles = [e.title for e in entries]
    assert "Houthi missiles strike VLCC in Red Sea, vessel ablaze" in titles
    assert "OPEC+ agrees production cut of 1M bpd" in titles


def test_parse_malformed_feed_returns_empty():
    xml = (FIXTURES / "malformed.xml").read_text()
    entries = parse_feed(xml, source="broken_feed")
    assert entries == []


def test_dedupe_same_headline_twice():
    xml = (FIXTURES / "reuters_atom_sample.xml").read_text()
    first = parse_feed(xml, source="reuters_energy")
    second = parse_feed(xml, source="reuters_energy")
    deduped = dedupe_headlines(first + second)
    assert len(deduped) == len(first)  # second pass added nothing new


def test_dedupe_different_sources_kept_separate():
    xml_a = (FIXTURES / "reuters_atom_sample.xml").read_text()
    xml_b = (FIXTURES / "oilprice_rss20_sample.xml").read_text()
    a = parse_feed(xml_a, source="reuters_energy")
    b = parse_feed(xml_b, source="oilprice_main")
    deduped = dedupe_headlines(a + b)
    assert len(deduped) == len(a) + len(b)  # different sources → different IDs
