from datetime import datetime, timezone
from pathlib import Path

import tempfile

import pytest

from modules.news_engine import (
    Headline,
    Catalyst,
    Rule,
    parse_feed,
    dedupe_headlines,
    load_rules,
    tag_headline,
)

RULES_YAML = Path("data/config/news_rules.yaml")
skip_if_no_rules = pytest.mark.skipif(
    not RULES_YAML.exists(), reason="rules YAML lands in Phase 2"
)

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


SAMPLE_RULES_YAML = """
rules:
  - name: trump_oil_announcement
    severity: 4
    instruments: ["xyz:BRENTOIL", "CL"]
    direction: null
    keywords_all: ["trump"]
    keywords_any: ["iran", "saudi", "opec", "sanctions", "deadline"]
  - name: physical_damage_facility
    severity: 5
    instruments: ["xyz:BRENTOIL", "CL"]
    direction: "bull"
    keywords_all: []
    keywords_any: ["drone", "strike", "missile"]
    keywords_require_any: ["refinery", "pipeline", "terminal", "oilfield"]
"""


def test_load_rules_from_yaml():
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(SAMPLE_RULES_YAML)
        path = f.name
    rules = load_rules(path)
    assert len(rules) == 2
    assert rules[0].name == "trump_oil_announcement"
    assert rules[0].severity == 4
    assert rules[0].direction is None
    assert rules[1].direction == "bull"
    assert "refinery" in rules[1].keywords_require_any


def _make_headline(title: str, body: str = "") -> Headline:
    return Headline(
        id="h1",
        source="test",
        url="https://example.com/a",
        title=title,
        body_excerpt=body,
        published_at=datetime(2026, 4, 9, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 4, 9, tzinfo=timezone.utc),
    )


def _load_all_rules():
    return load_rules("data/config/news_rules.yaml")


@skip_if_no_rules
def test_rule_trump_oil_announcement_fires():
    rules = _load_all_rules()
    h = _make_headline("Trump sets 8 PM deadline for Iran nuclear deal")
    hits = tag_headline(h, rules)
    assert any(r.name == "trump_oil_announcement" for r in hits)


@skip_if_no_rules
def test_rule_physical_damage_fires():
    rules = _load_all_rules()
    h = _make_headline("Drone strike hits Volgograd refinery, 200kbpd offline")
    hits = tag_headline(h, rules)
    assert any(r.name == "physical_damage_facility" for r in hits)


@skip_if_no_rules
def test_rule_shipping_attack_fires():
    rules = _load_all_rules()
    h = _make_headline("Houthi missiles strike VLCC in Red Sea, vessel ablaze")
    hits = tag_headline(h, rules)
    assert any(r.name == "shipping_attack" for r in hits)


@skip_if_no_rules
def test_rule_chokepoint_fires():
    rules = _load_all_rules()
    h = _make_headline("Hormuz strait closed after Iranian navy seizure")
    hits = tag_headline(h, rules)
    assert any(r.name == "chokepoint_blockade" for r in hits)


@skip_if_no_rules
def test_rule_negative_no_false_positive():
    rules = _load_all_rules()
    h = _make_headline("Trump tweets about golf tournament schedule")
    hits = tag_headline(h, rules)
    assert hits == []
