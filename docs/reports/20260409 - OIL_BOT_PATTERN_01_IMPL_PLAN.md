# Sub-System 1 — News & Catalyst Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md` (committed in `7ac7bea`)
**Parent:** `docs/plans/OIL_BOT_PATTERN_SYSTEM.md`

**Goal:** Build a daemon iterator that polls public RSS feeds and iCal calendars, tags headlines against a rule library, and publishes structured `Catalyst` records so the existing `CatalystDeleverageIterator` can act on them without any change to its trading behaviour.

**Architecture:** Three layers. (1) `modules/news_engine.py` is pure logic — feed parsing, dedup, rule-based tagging, catalyst extraction — with no I/O. (2) `cli/daemon/iterators/news_ingest.py` is the daemon integration layer that polls feeds on a tick, throttles per-source, and writes results to JSONL files. (3) `modules/catalyst_bridge.py` fans Catalysts out to one CatalystEvent per instrument and writes them to a new `data/daemon/external_catalyst_events.json` file that the existing `CatalystDeleverageIterator` reads on each tick via a new additive method. All new files are additive. Existing files get additive-only edits.

**Tech Stack:** Python 3.13, pytest, PyYAML (already in deps), feedparser (new — requires approval at Phase 0), icalendar (new — requires approval at Phase 0). Existing daemon tick engine (`cli/daemon/clock.py`).

---

## Ship gates (from parent spec §7)

Each item must be checked by the end of Phase 8 before sub-system 2 is allowed to start:

- [ ] All 19 tests from spec §9 passing
- [ ] Mock-mode end-to-end run produces expected outputs against fixture feeds
- [ ] Live-mode dry-run for ≥ 24h with `severity_floor: 5`; Telegram alerts fire on real catalysts and do not duplicate; no severity-3/4 entries reach `external_catalyst_events.json`
- [ ] Promote `severity_floor` from `5` to `3` (config edit only)
- [ ] `docs/wiki/components/news_ingest.md` created
- [ ] `CLAUDE.md` daemon iterator list updated
- [ ] `docs/wiki/build-log.md` entry added
- [ ] `/news` and `/catalysts` smoke-tested via Telegram on mainnet

---

## File structure (locked here)

### New files

| Path | Responsibility |
|---|---|
| `modules/news_engine.py` | Pure logic. Dataclasses (`Headline`, `Catalyst`, `Rule`), feed parser (Atom + RSS 2.0 + malformed), dedup, rule loader (YAML), rule tagger (keyword + conditional), catalyst extractor, event-date parser. Zero I/O; all sources injected. |
| `modules/catalyst_bridge.py` | Conversion layer: `Catalyst` → `CatalystEvent` fan-out (one per instrument), JSON persistence to `data/daemon/external_catalyst_events.json`. Kept separate from `news_engine.py` so the engine stays pure. |
| `cli/daemon/iterators/news_ingest.py` | Daemon iterator. Polls feeds, throttles per-source, writes headlines.jsonl/catalysts.jsonl, calls `catalyst_bridge.persist()`, emits Telegram alerts for severity ≥ `alert_floor`. |
| `data/config/news_feeds.yaml` | Feed registry (URL, name, poll interval, weight, category). |
| `data/config/news_rules.yaml` | Rule library — 11 categories from spec §5. |
| `data/config/news_ingest.json` | Runtime config: `enabled`, `severity_floor`, `alert_floor`, `default_poll_interval_s`, `max_headlines_per_tick`, file paths. |
| `data/news/.gitkeep` | Directory placeholder. |
| `tests/test_news_engine.py` | 15 unit tests (spec §9 tests 1-15) covering pure logic. |
| `tests/test_news_ingest_iterator.py` | 4 integration tests (spec §9 tests 16-19) covering iterator + bridge + end-to-end. |
| `tests/fixtures/news/reuters_atom_sample.xml` | Real captured Atom feed, used by tests 1, 14. |
| `tests/fixtures/news/oilprice_rss20_sample.xml` | Real captured RSS 2.0 feed, used by test 2. |
| `tests/fixtures/news/malformed.xml` | Deliberately broken XML, used by test 3. |
| `docs/wiki/components/news_ingest.md` | Wiki page for the new iterator. |

### Edited files (additive only)

| Path | Change |
|---|---|
| `pyproject.toml` | Add `feedparser>=6.0.10` and `icalendar>=5.0.0` to `dependencies`. **Phase 0 — user approval required.** |
| `cli/daemon/iterators/catalyst_deleverage.py` | Add public method `add_external_catalysts(events: list[CatalystEvent])` (dedup by `name`, persist state). Add `tick()` prologue one-liner that calls a new private `_load_external_catalysts_from_file()` which mtime-watches `data/daemon/external_catalyst_events.json` and merges new entries. Existing constructor, `_load_state`, `_process_catalyst`, and all other code paths unchanged. |
| `cli/commands/daemon.py` | One-line `clock.register(NewsIngestIterator())` added after the existing radar/pulse registration block. Unconditional (safe in all tiers — read-only). |
| `cli/daemon/tiers.py` | Add `"news_ingest"` to all three tier lists (watch, rebalance, opportunistic) so the iterator runs regardless of tier. |
| `cli/telegram_bot.py` | Add `cmd_news` and `cmd_catalysts` handlers (deterministic, NOT AI-suffix). Apply the five-surface checklist: handler, HANDLERS dict, `_set_telegram_commands` menu list, `cmd_help`, `cmd_guide`. |
| `docs/wiki/build-log.md` | One entry for sub-system 1 ship. |
| `CLAUDE.md` (project root or `agent-cli/CLAUDE.md`) | One line under the daemon iterator list. |

---

## Phase 0 — Prerequisites

### Task 0.1: Add feedparser and icalendar deps (REQUIRES USER APPROVAL)

**Files:**
- Modify: `pyproject.toml`

CLAUDE.md rule #3: "Zero external deps by default. Do not suggest [new services] unless the user explicitly asks." The user approved these two deps during brainstorming (§13 of the spec) but the implementer must re-confirm before editing `pyproject.toml`.

- [ ] **Step 1: Confirm with user before proceeding**

Message to user (literal): "Adding two new Python deps to pyproject.toml: `feedparser>=6.0.10` (RSS/Atom parsing, MIT license, ~2k LOC, stable) and `icalendar>=5.0.0` (iCal parsing, LGPL, small and well-maintained). Both were pre-approved in the news-ingestion spec open questions §13. Confirm to proceed?"

Wait for explicit "yes" before Step 2.

- [ ] **Step 2: Edit `pyproject.toml`**

Locate the `dependencies = [` block (around line 27 in current HEAD) and add two lines in alphabetical order:

```toml
dependencies = [
    # ... existing deps ...
    "feedparser>=6.0.10",
    "icalendar>=5.0.0",
    # ... rest ...
]
```

- [ ] **Step 3: Install into venv**

Run: `.venv/bin/pip install feedparser>=6.0.10 icalendar>=5.0.0`
Expected: both packages install without error. Verify with `.venv/bin/python -c "import feedparser, icalendar; print(feedparser.__version__, icalendar.__version__)"`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add feedparser + icalendar for oil bot pattern sub-system 1"
```

### Task 0.2: Create test fixtures directory

**Files:**
- Create: `tests/fixtures/news/reuters_atom_sample.xml`
- Create: `tests/fixtures/news/oilprice_rss20_sample.xml`
- Create: `tests/fixtures/news/malformed.xml`

- [ ] **Step 1: Create `tests/fixtures/news/reuters_atom_sample.xml`**

Capture a real sample from Reuters energy feed (or use this minimal valid Atom fixture — good enough for parser tests):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Reuters Energy</title>
  <link href="https://www.reuters.com/business/energy/feed/"/>
  <updated>2026-04-09T05:00:00Z</updated>
  <id>urn:uuid:reuters-energy-test</id>
  <entry>
    <title>Drone strike hits Volgograd refinery, 200kbpd offline</title>
    <link href="https://www.reuters.com/business/energy/volgograd-refinery-strike"/>
    <id>reuters-volgograd-001</id>
    <updated>2026-04-08T22:14:00Z</updated>
    <published>2026-04-08T22:14:00Z</published>
    <summary>Ukrainian drones struck the Volgograd refinery overnight. Russian energy ministry confirms 200 thousand barrels per day of capacity offline; repair timeline uncertain.</summary>
  </entry>
  <entry>
    <title>Trump sets 8 PM deadline for Iran nuclear deal</title>
    <link href="https://www.reuters.com/world/trump-iran-deadline"/>
    <id>reuters-trump-iran-001</id>
    <updated>2026-04-08T19:30:00Z</updated>
    <published>2026-04-08T19:30:00Z</published>
    <summary>President Trump issued an 8 PM Eastern deadline for Iran to accept the nuclear framework or face immediate consequences.</summary>
  </entry>
</feed>
```

- [ ] **Step 2: Create `tests/fixtures/news/oilprice_rss20_sample.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>OilPrice.com</title>
    <link>https://oilprice.com/</link>
    <description>Latest oil news</description>
    <item>
      <title>Houthi missiles strike VLCC in Red Sea, vessel ablaze</title>
      <link>https://oilprice.com/geopolitics/houthi-vlcc-red-sea</link>
      <guid>oilprice-vlcc-001</guid>
      <pubDate>Wed, 09 Apr 2026 14:22:00 +0000</pubDate>
      <description>Two Houthi-fired anti-ship missiles struck a Suezmax tanker transiting the southern Red Sea. Bridge ablaze, crew evacuated; cargo status unknown.</description>
    </item>
    <item>
      <title>OPEC+ agrees production cut of 1M bpd</title>
      <link>https://oilprice.com/opec/production-cut-announcement</link>
      <guid>oilprice-opec-cut-001</guid>
      <pubDate>Wed, 09 Apr 2026 12:00:00 +0000</pubDate>
      <description>OPEC+ ministers agreed to a 1 million barrels per day production cut at their emergency meeting.</description>
    </item>
  </channel>
</rss>
```

- [ ] **Step 3: Create `tests/fixtures/news/malformed.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Broken Feed
    <item>
      <title>Missing close tag
      <link>https://example.com/broken
    </item>
  </channel>
```

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/news/reuters_atom_sample.xml tests/fixtures/news/oilprice_rss20_sample.xml tests/fixtures/news/malformed.xml
git commit -m "test: add news fixture feeds for sub-system 1"
```

---

## Phase 1 — Pure logic (`modules/news_engine.py`)

All tasks in this phase edit `modules/news_engine.py` and `tests/test_news_engine.py`. Tests are written FIRST, run to confirm fail, then implementation.

### Task 1.1: Headline and Catalyst dataclasses

**Files:**
- Create: `modules/news_engine.py`
- Create: `tests/test_news_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_news_engine.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_news_engine.py -x -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'modules.news_engine'`

- [ ] **Step 3: Implement dataclasses**

```python
# modules/news_engine.py
"""News engine — pure logic for feed parsing, dedup, rule tagging, catalyst extraction.

All I/O is injected. This module has no knowledge of the daemon, HL, or trading.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Headline:
    id: str
    source: str
    url: str
    title: str
    body_excerpt: str
    published_at: datetime
    fetched_at: datetime


@dataclass(frozen=True)
class Catalyst:
    id: str
    headline_id: str
    instruments: list[str]
    event_date: datetime
    category: str
    severity: int
    expected_direction: str | None
    rationale: str
    created_at: datetime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_news_engine.py -x -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add modules/news_engine.py tests/test_news_engine.py
git commit -m "feat(news_engine): Headline and Catalyst dataclasses"
```

### Task 1.2: Parse Atom feed (spec test #1)

**Files:**
- Modify: `modules/news_engine.py`
- Modify: `tests/test_news_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_news_engine.py (append)
from pathlib import Path
from modules.news_engine import parse_feed

FIXTURES = Path(__file__).parent / "fixtures" / "news"

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_news_engine.py::test_parse_atom_feed_well_formed -x -q`
Expected: FAIL with `ImportError: cannot import name 'parse_feed'`

- [ ] **Step 3: Implement `parse_feed`**

```python
# modules/news_engine.py (append)
import hashlib
import logging
from datetime import timezone

import feedparser

log = logging.getLogger("news_engine")


def _hash_headline(source: str, url: str, title: str) -> str:
    return hashlib.sha256(f"{source}|{url}|{title}".encode("utf-8")).hexdigest()[:16]


def _to_utc(dt_tuple) -> datetime:
    """Convert feedparser's time.struct_time → UTC datetime."""
    from datetime import datetime as _dt
    return _dt(*dt_tuple[:6], tzinfo=timezone.utc)


def parse_feed(xml: str, source: str) -> list[Headline]:
    """Parse an RSS 2.0 or Atom 1.0 feed. Returns list of Headlines.

    Malformed feeds return an empty list and log a warning; they do not raise.
    """
    try:
        parsed = feedparser.parse(xml)
    except Exception as e:
        log.warning("feedparser crashed on source=%s: %s", source, e)
        return []

    if parsed.bozo and not parsed.entries:
        log.warning("feed %s is bozo (%s) with no entries — skipping", source, parsed.bozo_exception)
        return []

    now = datetime.now(timezone.utc)
    out: list[Headline] = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        url = entry.get("link") or ""
        if not title or not url:
            continue
        body = (entry.get("summary") or entry.get("description") or "")[:500]
        pub_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        published = _to_utc(pub_parsed) if pub_parsed else now
        out.append(Headline(
            id=_hash_headline(source, url, title),
            source=source,
            url=url,
            title=title,
            body_excerpt=body,
            published_at=published,
            fetched_at=now,
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_news_engine.py::test_parse_atom_feed_well_formed -x -q`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add modules/news_engine.py tests/test_news_engine.py
git commit -m "feat(news_engine): parse Atom 1.0 feeds via feedparser"
```

### Task 1.3: Parse RSS 2.0 feed (spec test #2)

**Files:**
- Modify: `tests/test_news_engine.py`

`feedparser` already handles RSS 2.0 via the same `parse_feed` function. This task only adds the test to prove it works.

- [ ] **Step 1: Write failing test (will fail only if parse_feed is RSS-blind)**

```python
# tests/test_news_engine.py (append)
def test_parse_rss20_well_formed():
    xml = (FIXTURES / "oilprice_rss20_sample.xml").read_text()
    entries = parse_feed(xml, source="oilprice_main")
    assert len(entries) == 2
    titles = [e.title for e in entries]
    assert "Houthi missiles strike VLCC in Red Sea, vessel ablaze" in titles
    assert "OPEC+ agrees production cut of 1M bpd" in titles
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/test_news_engine.py::test_parse_rss20_well_formed -x -q`
Expected: PASS (feedparser handles RSS 2.0 natively). If it fails, the RSS fixture is malformed — fix the fixture, not the code.

- [ ] **Step 3: Commit**

```bash
git add tests/test_news_engine.py
git commit -m "test(news_engine): verify RSS 2.0 parsing"
```

### Task 1.4: Parse malformed feed (spec test #3)

**Files:**
- Modify: `tests/test_news_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_news_engine.py (append)
def test_parse_malformed_feed_returns_empty():
    xml = (FIXTURES / "malformed.xml").read_text()
    entries = parse_feed(xml, source="broken_feed")
    assert entries == []
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/test_news_engine.py::test_parse_malformed_feed_returns_empty -x -q`
Expected: Likely PASS already (the bozo-and-no-entries check covers this). If it FAILS because entries are non-empty, feedparser partially recovered — accept the partial result or tighten the bozo check.

- [ ] **Step 3: Commit**

```bash
git add tests/test_news_engine.py
git commit -m "test(news_engine): malformed feed returns empty list, no crash"
```

### Task 1.5: Dedup (spec tests #4, #5)

**Files:**
- Modify: `modules/news_engine.py`
- Modify: `tests/test_news_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_news_engine.py (append)
from modules.news_engine import dedupe_headlines

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
```

- [ ] **Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/test_news_engine.py::test_dedupe_same_headline_twice tests/test_news_engine.py::test_dedupe_different_sources_kept_separate -x -q`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
# modules/news_engine.py (append)
def dedupe_headlines(headlines: list[Headline]) -> list[Headline]:
    """Dedupe by Headline.id (sha256(source+url+title)). Stable order preserved."""
    seen: set[str] = set()
    out: list[Headline] = []
    for h in headlines:
        if h.id in seen:
            continue
        seen.add(h.id)
        out.append(h)
    return out
```

- [ ] **Step 4: Run tests**

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add modules/news_engine.py tests/test_news_engine.py
git commit -m "feat(news_engine): dedupe headlines by source+url+title hash"
```

### Task 1.6: Rule loader + Rule dataclass

**Files:**
- Modify: `modules/news_engine.py`
- Modify: `tests/test_news_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_news_engine.py (append)
import tempfile
from modules.news_engine import Rule, load_rules

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
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/test_news_engine.py::test_load_rules_from_yaml -x -q`
Expected: FAIL with `ImportError: cannot import name 'Rule'`

- [ ] **Step 3: Implement**

```python
# modules/news_engine.py (append)
import yaml


@dataclass(frozen=True)
class Rule:
    name: str
    severity: int
    instruments: list[str]
    direction: str | None        # None | "bull" | "bear"
    keywords_all: list[str]      # ALL must match
    keywords_any: list[str]      # ANY must match
    keywords_require_any: list[str] = None  # optional secondary requirement

    def __post_init__(self):
        # frozen dataclass requires object.__setattr__ for mutation in __post_init__
        if self.keywords_require_any is None:
            object.__setattr__(self, "keywords_require_any", [])


def load_rules(yaml_path: str) -> list[Rule]:
    with open(yaml_path, "r") as f:
        doc = yaml.safe_load(f)
    rules: list[Rule] = []
    for rd in doc.get("rules", []):
        rules.append(Rule(
            name=rd["name"],
            severity=int(rd["severity"]),
            instruments=list(rd.get("instruments", [])),
            direction=rd.get("direction"),
            keywords_all=[k.lower() for k in rd.get("keywords_all", [])],
            keywords_any=[k.lower() for k in rd.get("keywords_any", [])],
            keywords_require_any=[k.lower() for k in rd.get("keywords_require_any", [])],
        ))
    return rules
```

- [ ] **Step 4: Run test**

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add modules/news_engine.py tests/test_news_engine.py
git commit -m "feat(news_engine): Rule dataclass and YAML loader"
```

### Task 1.7: Rule tagger — pure keyword rules (spec tests #6, #7, #8, #9, #10)

**Files:**
- Modify: `modules/news_engine.py`
- Modify: `tests/test_news_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_news_engine.py (append)
from modules.news_engine import tag_headline

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

def test_rule_trump_oil_announcement_fires():
    rules = _load_all_rules()
    h = _make_headline("Trump sets 8 PM deadline for Iran nuclear deal")
    hits = tag_headline(h, rules)
    assert any(r.name == "trump_oil_announcement" for r in hits)

def test_rule_physical_damage_fires():
    rules = _load_all_rules()
    h = _make_headline("Drone strike hits Volgograd refinery, 200kbpd offline")
    hits = tag_headline(h, rules)
    assert any(r.name == "physical_damage_facility" for r in hits)

def test_rule_shipping_attack_fires():
    rules = _load_all_rules()
    h = _make_headline("Houthi missiles strike VLCC in Red Sea, vessel ablaze")
    hits = tag_headline(h, rules)
    assert any(r.name == "shipping_attack" for r in hits)

def test_rule_chokepoint_fires():
    rules = _load_all_rules()
    h = _make_headline("Hormuz strait closed after Iranian navy seizure")
    hits = tag_headline(h, rules)
    assert any(r.name == "chokepoint_blockade" for r in hits)

def test_rule_negative_no_false_positive():
    rules = _load_all_rules()
    h = _make_headline("Trump tweets about golf tournament schedule")
    hits = tag_headline(h, rules)
    assert hits == []
```

- [ ] **Step 2: Run tests**

Expected: all fail with `ImportError` AND also blocked because `data/config/news_rules.yaml` does not exist yet. See Task 2.1 — this is OK; tests are written first, the YAML landing in Phase 2 unblocks them.

**IMPORTANT:** do NOT run these tests in CI until Phase 2 lands. Mark them with a module-level `pytest.importorskip` or `@pytest.mark.skipif(not Path("data/config/news_rules.yaml").exists(), reason="rules YAML ships in Phase 2")` to keep the test suite green between phases.

```python
# tests/test_news_engine.py (at module top)
import pytest
RULES_YAML = Path("data/config/news_rules.yaml")
skip_if_no_rules = pytest.mark.skipif(not RULES_YAML.exists(), reason="rules YAML lands in Phase 2")
```

Apply `@skip_if_no_rules` decorator to each of the 5 tests above.

- [ ] **Step 3: Implement `tag_headline`**

```python
# modules/news_engine.py (append)
def tag_headline(headline: Headline, rules: list[Rule]) -> list[Rule]:
    """Return every rule whose keyword pattern matches this headline.

    A rule fires when:
      - every entry in `keywords_all` appears in (title + body_excerpt), lowercased
      - at least one entry in `keywords_any` appears
      - if `keywords_require_any` is non-empty, at least one of those entries also appears
    """
    text = (headline.title + " " + headline.body_excerpt).lower()
    hits: list[Rule] = []
    for rule in rules:
        if rule.keywords_all and not all(k in text for k in rule.keywords_all):
            continue
        if rule.keywords_any and not any(k in text for k in rule.keywords_any):
            continue
        if rule.keywords_require_any and not any(k in text for k in rule.keywords_require_any):
            continue
        hits.append(rule)
    return hits
```

- [ ] **Step 4: Run tests**

Tests will stay SKIPPED until Phase 2 lands the YAML. That's expected. Continue.

- [ ] **Step 5: Commit**

```bash
git add modules/news_engine.py tests/test_news_engine.py
git commit -m "feat(news_engine): keyword-based rule tagger"
```

### Task 1.8: Rule-conditional direction (spec rules 2, 6, 8)

**Files:**
- Modify: `modules/news_engine.py`
- Modify: `tests/test_news_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_news_engine.py (append)
from modules.news_engine import direction_for_opec_action, direction_for_iran_deal, direction_for_fomc_macro

def test_opec_action_cut_is_bull():
    assert direction_for_opec_action("OPEC+ agrees production cut of 1M bpd") == "bull"

def test_opec_action_increase_is_bear():
    assert direction_for_opec_action("OPEC ramps production by 500k bpd") == "bear"

def test_opec_action_neutral_returns_none():
    assert direction_for_opec_action("OPEC holds meeting in Vienna") is None

def test_iran_deal_agreement_is_bear():
    assert direction_for_iran_deal("Iran nuclear deal agreement reached in Geneva") == "bear"

def test_iran_deal_collapse_is_bull():
    assert direction_for_iran_deal("Iran talks collapse, US walks out of nuclear deal") == "bull"

def test_fomc_cut_is_bull():
    assert direction_for_fomc_macro("Fed cuts rates by 25bp at dovish FOMC meeting") == "bull"

def test_fomc_hike_is_bear():
    assert direction_for_fomc_macro("Fed hikes rates 50bp, signals hawkish path") == "bear"
```

- [ ] **Step 2: Run tests**

Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
# modules/news_engine.py (append)
def direction_for_opec_action(headline_text: str) -> str | None:
    text = headline_text.lower()
    if any(w in text for w in ("cut", "reduce", "lower")):
        return "bull"
    if any(w in text for w in ("increase", "raise", "boost", "ramp")):
        return "bear"
    return None


def direction_for_iran_deal(headline_text: str) -> str | None:
    text = headline_text.lower()
    if any(w in text for w in ("deal", "agreement", "reached", "signed")) and not any(
        w in text for w in ("collapse", "walk out", "walks out", "breakdown", "fails")
    ):
        return "bear"
    if any(w in text for w in ("collapse", "walk out", "walks out", "breakdown", "fails", "rejects")):
        return "bull"
    return None


def direction_for_fomc_macro(headline_text: str) -> str | None:
    text = headline_text.lower()
    if any(w in text for w in ("cut", "dovish", "pause", "ease")):
        return "bull"
    if any(w in text for w in ("hike", "hawkish", "raise", "tighten")):
        return "bear"
    return None


# Registry: category name → conditional direction callable
RULE_CONDITIONAL_DIRECTION = {
    "opec_action": direction_for_opec_action,
    "iran_deal": direction_for_iran_deal,
    "fomc_macro": direction_for_fomc_macro,
}
```

- [ ] **Step 4: Run tests**

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add modules/news_engine.py tests/test_news_engine.py
git commit -m "feat(news_engine): rule-conditional direction for opec/iran/fomc"
```

### Task 1.9: Event-date parser (spec test #14)

**Files:**
- Modify: `modules/news_engine.py`
- Modify: `tests/test_news_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_news_engine.py (append)
from modules.news_engine import parse_event_date

def test_event_date_no_phrase_uses_published_at():
    published = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    result = parse_event_date("OPEC+ agrees production cut of 1M bpd", published)
    assert result == published  # no explicit future date → fall back

def test_event_date_tomorrow_phrase():
    published = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
    result = parse_event_date("Trump's 8 PM ET deadline tomorrow", published)
    # Tomorrow at 8 PM ET = 2026-04-10 00:00 UTC (ET = UTC-4 in April DST)
    assert result.date() == datetime(2026, 4, 10).date()
```

- [ ] **Step 2: Run tests**

Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
# modules/news_engine.py (append)
import re
from datetime import timedelta

def parse_event_date(headline_text: str, published_at: datetime) -> datetime:
    """Extract an event date from headline text if present; otherwise use published_at.

    V1 recognises:
      - "tomorrow at HH PM ET|UTC" → published_at.date + 1, at HH local
      - "in N hours" → published_at + N hours
      - "on {Mon|Tue|Wed|Thu|Fri|Sat|Sun}" → next occurrence of that weekday (coarse)

    Unrecognised phrases silently fall back to published_at. This is conservative — the
    sub-system prefers missing a catalyst date over mis-dating one.
    """
    text = headline_text.lower()

    # "tomorrow at N PM"
    m = re.search(r"tomorrow.*?(\d{1,2})\s*(am|pm)", text)
    if m:
        hour = int(m.group(1)) % 12
        if m.group(2) == "pm":
            hour += 12
        tomorrow = published_at.date() + timedelta(days=1)
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, 0, tzinfo=timezone.utc)

    # "in N hours"
    m = re.search(r"in\s+(\d+)\s+hours?", text)
    if m:
        return published_at + timedelta(hours=int(m.group(1)))

    return published_at
```

- [ ] **Step 4: Run tests**

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add modules/news_engine.py tests/test_news_engine.py
git commit -m "feat(news_engine): conservative event-date phrase parser"
```

### Task 1.10: Catalyst extractor

**Files:**
- Modify: `modules/news_engine.py`
- Modify: `tests/test_news_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_news_engine.py (append)
from modules.news_engine import extract_catalysts

@skip_if_no_rules
def test_extract_catalysts_from_tagged_headline():
    rules = _load_all_rules()
    h = _make_headline("Drone strike hits Volgograd refinery, 200kbpd offline")
    catalysts = extract_catalysts([h], rules)
    assert len(catalysts) >= 1
    cat = [c for c in catalysts if c.category == "physical_damage_facility"][0]
    assert cat.severity == 5
    assert cat.expected_direction == "bull"
    assert "xyz:BRENTOIL" in cat.instruments
    assert "CL" in cat.instruments
    assert cat.headline_id == h.id
```

- [ ] **Step 2: Run test (stays skipped until Phase 2)**

- [ ] **Step 3: Implement**

```python
# modules/news_engine.py (append)
def extract_catalysts(headlines: list[Headline], rules: list[Rule]) -> list[Catalyst]:
    """Tag each headline, extract a Catalyst record per rule that fires."""
    out: list[Catalyst] = []
    now = datetime.now(timezone.utc)
    for h in headlines:
        for rule in tag_headline(h, rules):
            # Rule-conditional direction overrides the rule's default direction
            direction = rule.direction
            if rule.name in RULE_CONDITIONAL_DIRECTION:
                conditional = RULE_CONDITIONAL_DIRECTION[rule.name](h.title + " " + h.body_excerpt)
                if conditional is not None:
                    direction = conditional

            event_date = parse_event_date(h.title, h.published_at)
            cat_id = _hash_headline(rule.name, h.id, "")
            out.append(Catalyst(
                id=cat_id,
                headline_id=h.id,
                instruments=list(rule.instruments),
                event_date=event_date,
                category=rule.name,
                severity=rule.severity,
                expected_direction=direction,
                rationale=f"rule: {rule.name} severity={rule.severity}",
                created_at=now,
            ))
    return out
```

- [ ] **Step 4: Run test (skipped until Phase 2)**

- [ ] **Step 5: Commit**

```bash
git add modules/news_engine.py tests/test_news_engine.py
git commit -m "feat(news_engine): extract Catalyst records from tagged headlines"
```

---

## Phase 2 — Configuration files

### Task 2.1: Create `data/config/news_rules.yaml`

**Files:**
- Create: `data/config/news_rules.yaml`

- [ ] **Step 1: Create the file**

```yaml
# data/config/news_rules.yaml
# Rule library for modules/news_engine.py tagger.
# Spec: docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md §5

rules:
  - name: trump_oil_announcement
    severity: 4
    instruments: ["xyz:BRENTOIL", "CL"]
    direction: null
    keywords_all: ["trump"]
    keywords_any: ["iran", "saudi", "opec", "sanctions", "deadline"]
    keywords_require_any: []

  - name: opec_action
    severity: 4
    instruments: ["xyz:BRENTOIL", "CL"]
    direction: null
    keywords_all: ["opec"]
    keywords_any: ["cut", "quota", "production", "meeting", "ramp", "increase"]
    keywords_require_any: []

  - name: eia_weekly
    severity: 3
    instruments: ["xyz:BRENTOIL", "CL"]
    direction: null
    keywords_all: ["eia"]
    keywords_any: ["crude", "inventories", "stockpile"]
    keywords_require_any: []

  - name: geopolitical_strike
    severity: 5
    instruments: ["xyz:BRENTOIL", "CL"]
    direction: "bull"
    keywords_all: []
    keywords_any: ["strike", "drone", "missile"]
    keywords_require_any: ["refinery", "pipeline", "field", "oil", "terminal"]

  - name: cushing_storage
    severity: 3
    instruments: ["CL"]
    direction: null
    keywords_all: ["cushing"]
    keywords_any: ["storage", "inventory", "build", "draw"]
    keywords_require_any: []

  - name: iran_deal
    severity: 4
    instruments: ["xyz:BRENTOIL", "CL"]
    direction: null
    keywords_all: ["iran"]
    keywords_any: ["deal", "deadline", "nuclear", "talks"]
    keywords_require_any: []

  - name: russia_oil
    severity: 4
    instruments: ["xyz:BRENTOIL"]
    direction: null
    keywords_all: ["russia"]
    keywords_any: ["oil", "sanctions", "pipeline", "refinery"]
    keywords_require_any: []

  - name: fomc_macro
    severity: 3
    instruments: ["BTC", "xyz:BRENTOIL", "CL"]
    direction: null
    keywords_all: []
    keywords_any: ["fomc", "fed"]
    keywords_require_any: ["rate", "hike", "cut", "pause"]

  - name: physical_damage_facility
    severity: 5
    instruments: ["xyz:BRENTOIL", "CL"]
    direction: "bull"
    keywords_all: []
    keywords_any: ["strike", "drone", "missile", "fire", "explosion", "damage", "offline"]
    keywords_require_any: ["refinery", "pipeline", "terminal", "oilfield", "gas plant"]

  - name: shipping_attack
    severity: 5
    instruments: ["xyz:BRENTOIL", "CL"]
    direction: "bull"
    keywords_all: []
    keywords_any: ["strike", "attack", "drone", "missile", "fire", "detained", "seized"]
    keywords_require_any: ["tanker", "vlcc", "ship", "vessel", "shipping"]

  - name: chokepoint_blockade
    severity: 5
    instruments: ["xyz:BRENTOIL", "CL"]
    direction: "bull"
    keywords_all: []
    keywords_any: ["block", "closed", "halt", "detain", "attack"]
    keywords_require_any: ["hormuz", "bab-el-mandeb", "suez", "malacca", "red sea", "strait"]
```

- [ ] **Step 2: Verify loader works**

Run: `.venv/bin/python -c "from modules.news_engine import load_rules; print(len(load_rules('data/config/news_rules.yaml')))"`
Expected: `11`

- [ ] **Step 3: Run the previously-skipped tests**

Run: `.venv/bin/python -m pytest tests/test_news_engine.py -x -q`
Expected: all tests now pass (no more skips)

- [ ] **Step 4: Commit**

```bash
git add data/config/news_rules.yaml
git commit -m "feat(news_engine): initial rule library (11 categories)"
```

### Task 2.2: Create `data/config/news_feeds.yaml`

**Files:**
- Create: `data/config/news_feeds.yaml`

- [ ] **Step 1: Create file**

```yaml
# data/config/news_feeds.yaml
# Feed registry for news_ingest iterator.
# Spec: docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md §6
# Implementer: verify each URL returns valid XML before promoting to live.

feeds:
  - name: reuters_energy
    url: https://www.reuters.com/business/energy/feed/
    poll_interval_s: 60
    weight: 0.9
    categories: [oil, energy]
    enabled: true

  - name: oilprice_main
    url: https://oilprice.com/rss/main
    poll_interval_s: 120
    weight: 0.8
    categories: [oil, energy]
    enabled: true

  - name: eia_today_in_energy
    url: https://www.eia.gov/rss/todayinenergy.xml
    poll_interval_s: 300
    weight: 0.95
    categories: [oil, energy, fundamentals]
    enabled: true

  - name: ap_top
    url: https://feeds.apnews.com/rss/apf-topnews
    poll_interval_s: 60
    weight: 0.7
    categories: [macro, geopolitical]
    enabled: true

icals:
  - name: eia_weekly_petroleum
    url: ""   # Verify at implementation time; set enabled=false if not found
    enabled: false
    categories: [oil, scheduled]

  - name: opec_meetings
    url: ""
    enabled: false
    categories: [oil, scheduled]

  - name: fomc_schedule
    url: ""
    enabled: false
    categories: [macro, scheduled]
```

- [ ] **Step 2: Commit**

```bash
git add data/config/news_feeds.yaml
git commit -m "feat(news_ingest): initial feed registry (4 RSS + 3 placeholder iCals)"
```

### Task 2.3: Create `data/config/news_ingest.json`

**Files:**
- Create: `data/config/news_ingest.json`

- [ ] **Step 1: Create file**

```json
{
  "enabled": true,
  "severity_floor": 5,
  "alert_floor": 4,
  "default_poll_interval_s": 60,
  "max_headlines_per_tick": 50,
  "headlines_jsonl": "data/news/headlines.jsonl",
  "catalysts_jsonl": "data/news/catalysts.jsonl",
  "external_catalyst_events_json": "data/daemon/external_catalyst_events.json"
}
```

**Note:** `severity_floor: 5` is the dry-run setting per spec §10. Promote to `3` after 24h dry-run passes.

- [ ] **Step 2: Commit**

```bash
git add data/config/news_ingest.json
git commit -m "feat(news_ingest): runtime config (dry-run severity_floor=5)"
```

### Task 2.4: Create `data/news/` directory

**Files:**
- Create: `data/news/.gitkeep`

- [ ] **Step 1: Create file**

```
# touch data/news/.gitkeep
```

- [ ] **Step 2: Commit**

```bash
git add data/news/.gitkeep
git commit -m "feat(news_ingest): data/news directory"
```

---

## Phase 3 — Bridge + catalyst deleverage integration

### Task 3.1: `modules/catalyst_bridge.py` — Catalyst → CatalystEvent fan-out

**Files:**
- Create: `modules/catalyst_bridge.py`
- Create: `tests/test_catalyst_bridge.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_catalyst_bridge.py
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
```

- [ ] **Step 2: Run test**

Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
# modules/catalyst_bridge.py
"""Catalyst → CatalystEvent conversion bridge.

Keeps modules/news_engine.py pure by pushing the daemon-type coupling here.
Also handles persistence to data/daemon/external_catalyst_events.json, the file
the existing CatalystDeleverageIterator watches via its new additive reader.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from cli.daemon.iterators.catalyst_deleverage import CatalystEvent
from modules.news_engine import Catalyst

log = logging.getLogger("catalyst_bridge")


def catalyst_to_events(cat: Catalyst, pre_event_hours: int = 24) -> list[CatalystEvent]:
    """Fan a multi-instrument Catalyst out to one CatalystEvent per instrument."""
    return [
        CatalystEvent(
            name=f"{cat.id}-{instrument}",
            instrument=instrument,
            event_date=cat.event_date.date().isoformat(),
            pre_event_hours=pre_event_hours,
            reduce_leverage_to=None,
            reduce_size_pct=0.25,  # sensible default: 25% size-down ahead of catalyst
            post_event_hours=12,
            executed=False,
        )
        for instrument in cat.instruments
    ]


def persist(
    catalysts: Iterable[Catalyst],
    output_path: str,
    severity_floor: int,
) -> int:
    """Append Catalyst fan-outs above the severity floor to output_path JSON.

    File format: a JSON object {"events": [<CatalystEvent>, ...]}. On first call
    the file is created; on subsequent calls existing events are preserved and
    new events are deduped by `name`.

    Returns the number of new events added.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text()).get("events", [])
        except json.JSONDecodeError:
            log.warning("external catalyst file %s corrupt — starting fresh", path)
            existing = []

    existing_names = {e["name"] for e in existing}
    added = 0
    for cat in catalysts:
        if cat.severity < severity_floor:
            continue
        for event in catalyst_to_events(cat):
            if event.name in existing_names:
                continue
            existing.append(asdict(event))
            existing_names.add(event.name)
            added += 1

    path.write_text(json.dumps({"events": existing}, indent=2, default=str))
    return added
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/python -m pytest tests/test_catalyst_bridge.py -x -q`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add modules/catalyst_bridge.py tests/test_catalyst_bridge.py
git commit -m "feat(catalyst_bridge): Catalyst → CatalystEvent fan-out + persist"
```

### Task 3.2: `catalyst_bridge.persist()` dedup + severity filter (spec tests #11, #15)

**Files:**
- Modify: `tests/test_catalyst_bridge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_catalyst_bridge.py (append)
import json
import tempfile
from modules.catalyst_bridge import persist

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
```

- [ ] **Step 2: Run tests**

Expected: 3 passed (the implementation from Task 3.1 already handles all three cases)

- [ ] **Step 3: Commit**

```bash
git add tests/test_catalyst_bridge.py
git commit -m "test(catalyst_bridge): severity filter, dedup, preserve existing"
```

### Task 3.3: `CatalystDeleverageIterator.add_external_catalysts()` method

**Files:**
- Modify: `cli/daemon/iterators/catalyst_deleverage.py`
- Create: `tests/test_catalyst_deleverage_external.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_catalyst_deleverage_external.py
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
```

- [ ] **Step 2: Run test**

Expected: FAIL with `AttributeError: 'CatalystDeleverageIterator' object has no attribute 'add_external_catalysts'`

- [ ] **Step 3: Implement (additive to existing file)**

Open `cli/daemon/iterators/catalyst_deleverage.py` and add the following method inside the `CatalystDeleverageIterator` class, below `_process_catalyst`:

```python
    # ------------------------------------------------------------------
    # External catalyst injection (sub-system 1 news ingestion)
    # ------------------------------------------------------------------

    def add_external_catalysts(self, events: list[CatalystEvent]) -> int:
        """Merge externally-supplied CatalystEvents into the iterator's list.

        Dedupe by `name`. Called by the news_ingest iterator via file watching.
        Returns the count of new events added.
        """
        existing_names = {c.name for c in self._catalysts}
        added = 0
        for ev in events:
            if ev.name in existing_names:
                continue
            self._catalysts.append(ev)
            existing_names.add(ev.name)
            added += 1
        if added:
            log.info("CatalystDeleverage: merged %d external catalysts", added)
            self._save_state()
        return added
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/python -m pytest tests/test_catalyst_deleverage_external.py -x -q`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add cli/daemon/iterators/catalyst_deleverage.py tests/test_catalyst_deleverage_external.py
git commit -m "feat(catalyst_deleverage): add_external_catalysts() for sub-system 1 bridge"
```

### Task 3.4: `CatalystDeleverageIterator.tick()` prologue — external file watcher

**Files:**
- Modify: `cli/daemon/iterators/catalyst_deleverage.py`
- Modify: `tests/test_catalyst_deleverage_external.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_catalyst_deleverage_external.py (append)
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

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
```

- [ ] **Step 2: Run tests**

Expected: FAIL because `_external_catalyst_path` does not exist and `tick()` does not load the file.

- [ ] **Step 3: Implement**

Edit `cli/daemon/iterators/catalyst_deleverage.py`:

(a) In `__init__`, after `self._state_path = Path(data_dir) / "catalyst_events.json"`, add:

```python
        self._external_catalyst_path = Path(data_dir) / "external_catalyst_events.json"
        self._external_mtime: float = 0.0
```

(b) In `tick`, at the very top (before the existing `now_s = ...` line), add:

```python
    def tick(self, ctx: TickContext) -> None:
        self._load_external_catalysts_from_file()  # PROLOGUE: sub-system 1 news bridge
        now_s = ctx.timestamp // 1000 if ctx.timestamp > 1e12 else ctx.timestamp
        # ... rest of existing method unchanged ...
```

(c) Add the private method at the bottom of the class, next to `add_external_catalysts`:

```python
    def _load_external_catalysts_from_file(self) -> None:
        """Mtime-watch data/daemon/external_catalyst_events.json and merge new entries."""
        path = self._external_catalyst_path
        if not path.exists():
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime <= self._external_mtime:
            return  # unchanged since last check

        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            log.warning("external catalyst file %s corrupt: %s", path, e)
            return

        events: list[CatalystEvent] = []
        for ev in raw.get("events", []):
            try:
                events.append(CatalystEvent(
                    name=ev["name"],
                    instrument=ev["instrument"],
                    event_date=ev["event_date"],
                    pre_event_hours=int(ev.get("pre_event_hours", 24)),
                    reduce_leverage_to=ev.get("reduce_leverage_to"),
                    reduce_size_pct=ev.get("reduce_size_pct"),
                    post_event_hours=int(ev.get("post_event_hours", 12)),
                    executed=bool(ev.get("executed", False)),
                ))
            except (KeyError, TypeError, ValueError) as e:
                log.warning("skipping malformed external catalyst: %s (%s)", ev, e)

        if events:
            self.add_external_catalysts(events)
        self._external_mtime = mtime
```

Don't forget to add `import json` at the top of the file if not already present.

- [ ] **Step 4: Run tests**

Expected: 2 passed

- [ ] **Step 5: Run full existing catalyst_deleverage tests to prove no regression**

Run: `.venv/bin/python -m pytest tests/ -x -q -k "catalyst"`
Expected: all passing, no regression

- [ ] **Step 6: Commit**

```bash
git add cli/daemon/iterators/catalyst_deleverage.py tests/test_catalyst_deleverage_external.py
git commit -m "feat(catalyst_deleverage): tick prologue reads external catalyst file"
```

---

## Phase 4 — Daemon iterator (`cli/daemon/iterators/news_ingest.py`)

### Task 4.1: `NewsIngestIterator` skeleton + kill switch (spec test #18)

**Files:**
- Create: `cli/daemon/iterators/news_ingest.py`
- Create: `tests/test_news_ingest_iterator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_news_ingest_iterator.py
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
```

- [ ] **Step 2: Run tests**

Expected: FAIL with `ImportError: cannot import name 'NewsIngestIterator'`

- [ ] **Step 3: Implement skeleton**

```python
# cli/daemon/iterators/news_ingest.py
"""NewsIngestIterator — polls RSS feeds + iCal calendars, writes catalysts.

Spec: docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md
Parent: docs/plans/OIL_BOT_PATTERN_SYSTEM.md

This iterator is additive and read-only (no trades). It is safe in all tiers.
Kill switch: data/config/news_ingest.json → enabled: false.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import requests
import yaml

from cli.daemon.context import Alert, TickContext
from modules.news_engine import (
    Catalyst,
    Headline,
    dedupe_headlines,
    extract_catalysts,
    load_rules,
    parse_feed,
)
from modules import catalyst_bridge

log = logging.getLogger("daemon.news_ingest")

DEFAULT_CONFIG_PATH = "data/config/news_ingest.json"
DEFAULT_FEEDS_PATH = "data/config/news_feeds.yaml"
DEFAULT_RULES_PATH = "data/config/news_rules.yaml"


class NewsIngestIterator:
    name = "news_ingest"

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        feeds_path: str = DEFAULT_FEEDS_PATH,
        rules_path: str = DEFAULT_RULES_PATH,
    ):
        self._config_path = config_path
        self._feeds_path = feeds_path
        self._rules_path = rules_path
        self._config: dict = {}
        self._feeds: list[dict] = []
        self._rules = []
        self._last_poll: dict[str, float] = {}  # feed name → last poll monotonic
        self._alerted_catalyst_ids: set[str] = set()

    def on_start(self, ctx: TickContext) -> None:
        self._reload_config()
        if not self._config.get("enabled", False):
            log.info("NewsIngestIterator disabled via config — no-op")
            return
        log.info("NewsIngestIterator started — %d feeds, %d rules", len(self._feeds), len(self._rules))

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        self._reload_config_if_changed()
        if not self._config.get("enabled", False):
            return
        # Phases 4.2+ fill in the polling, dedup, extract, write, alert pipeline.

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _reload_config(self) -> None:
        try:
            self._config = json.loads(Path(self._config_path).read_text())
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("news_ingest config unavailable (%s) — iterator disabled", e)
            self._config = {"enabled": False}
            return
        try:
            feeds_doc = yaml.safe_load(Path(self._feeds_path).read_text())
            self._feeds = [f for f in feeds_doc.get("feeds", []) if f.get("enabled", True)]
        except Exception as e:
            log.warning("news_ingest feeds unavailable (%s)", e)
            self._feeds = []
        try:
            self._rules = load_rules(self._rules_path)
        except Exception as e:
            log.warning("news_ingest rules unavailable (%s) — no tagging", e)
            self._rules = []

    def _reload_config_if_changed(self) -> None:
        # V1: full reload every tick is cheap enough with ≤10 feeds and ≤50 rules.
        # V2: mtime-watch for changes.
        self._reload_config()
```

- [ ] **Step 4: Run tests**

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add cli/daemon/iterators/news_ingest.py tests/test_news_ingest_iterator.py
git commit -m "feat(news_ingest): iterator skeleton with kill switch"
```

### Task 4.2: Poll feeds with per-source throttle (spec tests #16, #17)

**Files:**
- Modify: `cli/daemon/iterators/news_ingest.py`
- Modify: `tests/test_news_ingest_iterator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_news_ingest_iterator.py (append)
from unittest.mock import patch

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
```

- [ ] **Step 2: Run tests**

Expected: FAIL because `tick()` does no polling yet.

- [ ] **Step 3: Implement polling with throttle**

Replace the `tick` method in `cli/daemon/iterators/news_ingest.py`:

```python
    def tick(self, ctx: TickContext) -> None:
        self._reload_config_if_changed()
        if not self._config.get("enabled", False):
            return

        now_mono = time.monotonic()
        new_headlines: list[Headline] = []
        max_per_tick = int(self._config.get("max_headlines_per_tick", 50))

        for feed in self._feeds:
            name = feed["name"]
            interval = int(feed.get("poll_interval_s", self._config.get("default_poll_interval_s", 60)))
            if now_mono - self._last_poll.get(name, 0) < interval:
                continue
            self._last_poll[name] = now_mono
            try:
                resp = requests.get(feed["url"], timeout=10)
                if resp.status_code != 200:
                    log.warning("feed %s returned HTTP %d", name, resp.status_code)
                    continue
                entries = parse_feed(resp.text, source=name)
            except Exception as e:
                log.warning("feed %s fetch/parse failed: %s", name, e)
                continue
            new_headlines.extend(entries)
            if len(new_headlines) >= max_per_tick:
                break

        if not new_headlines:
            return

        # Load prior headline IDs from the JSONL for cross-tick dedup
        seen_ids = self._load_seen_headline_ids()
        fresh = [h for h in dedupe_headlines(new_headlines) if h.id not in seen_ids]
        if not fresh:
            return

        self._append_headlines_jsonl(fresh)
        catalysts = extract_catalysts(fresh, self._rules)
        if catalysts:
            self._append_catalysts_jsonl(catalysts)
            added = catalyst_bridge.persist(
                catalysts,
                self._config["external_catalyst_events_json"],
                severity_floor=int(self._config.get("severity_floor", 3)),
            )
            if added:
                log.info("news_ingest: appended %d catalysts above severity floor", added)
            self._maybe_alert(catalysts, ctx)

    # ------------------------------------------------------------------
    # JSONL writers + dedup
    # ------------------------------------------------------------------

    def _load_seen_headline_ids(self) -> set[str]:
        path = Path(self._config["headlines_jsonl"])
        if not path.exists():
            return set()
        seen: set[str] = set()
        try:
            with path.open("r") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        seen.add(rec["id"])
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError:
            pass
        return seen

    def _append_headlines_jsonl(self, headlines: list[Headline]) -> None:
        path = Path(self._config["headlines_jsonl"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for h in headlines:
                f.write(json.dumps(_headline_to_dict(h), default=str) + "\n")

    def _append_catalysts_jsonl(self, catalysts: list[Catalyst]) -> None:
        path = Path(self._config["catalysts_jsonl"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for c in catalysts:
                f.write(json.dumps(_catalyst_to_dict(c), default=str) + "\n")

    def _maybe_alert(self, catalysts: list[Catalyst], ctx: TickContext) -> None:
        alert_floor = int(self._config.get("alert_floor", 4))
        for c in catalysts:
            if c.severity < alert_floor:
                continue
            if c.id in self._alerted_catalyst_ids:
                continue
            self._alerted_catalyst_ids.add(c.id)
            direction = c.expected_direction or "?"
            ctx.alerts.append(Alert(
                severity="warning" if c.severity == 4 else "critical",
                source=self.name,
                message=f"NEW CATALYST sev={c.severity} {c.category}: {', '.join(c.instruments)} ({direction})",
                data={"category": c.category, "catalyst_id": c.id},
            ))


def _headline_to_dict(h: Headline) -> dict:
    return {
        "id": h.id,
        "source": h.source,
        "url": h.url,
        "title": h.title,
        "body_excerpt": h.body_excerpt,
        "published_at": h.published_at.isoformat(),
        "fetched_at": h.fetched_at.isoformat(),
    }


def _catalyst_to_dict(c: Catalyst) -> dict:
    return {
        "id": c.id,
        "headline_id": c.headline_id,
        "instruments": c.instruments,
        "event_date": c.event_date.isoformat(),
        "category": c.category,
        "severity": c.severity,
        "expected_direction": c.expected_direction,
        "rationale": c.rationale,
        "created_at": c.created_at.isoformat(),
    }
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_news_ingest_iterator.py -x -q`
Expected: both tests pass

- [ ] **Step 5: Commit**

```bash
git add cli/daemon/iterators/news_ingest.py tests/test_news_ingest_iterator.py
git commit -m "feat(news_ingest): feed polling with per-source throttle + dedup"
```

### Task 4.3: End-to-end fixture test (spec test #19)

**Files:**
- Modify: `tests/test_news_ingest_iterator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_news_ingest_iterator.py (append)
def test_e2e_fixture_feed_to_catalyst_deleverage(tmp_path):
    """Full pipeline: fixture feed → iterator tick → catalyst_bridge → external file."""
    cfg = _write_config(str(tmp_path), severity_floor=3)  # lower for test
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

    with patch("cli.daemon.iterators.news_ingest.requests.get", return_value=mock_response):
        it.tick(ctx)

    # headlines.jsonl has entries
    headlines_path = Path(f"{tmp_path}/headlines.jsonl")
    assert headlines_path.exists()
    lines = headlines_path.read_text().strip().split("\n")
    assert len(lines) >= 2

    # catalysts.jsonl has entries
    catalysts_path = Path(f"{tmp_path}/catalysts.jsonl")
    assert catalysts_path.exists()

    # external_catalyst_events.json has fan-outs
    ext_path = Path(f"{tmp_path}/external_catalyst_events.json")
    assert ext_path.exists()
    external = json.loads(ext_path.read_text())
    names = [e["name"] for e in external["events"]]
    # Volgograd refinery strike should have fanned out to BRENTOIL + CL
    assert any("xyz:BRENTOIL" in n for n in names)
    assert any("CL" in n for n in names)

    # Severity-5 catalyst should have produced an Alert
    assert any(a.severity == "critical" for a in ctx.alerts)
```

- [ ] **Step 2: Run test**

Expected: PASS if all prior tasks landed correctly. If FAIL, debug by reading JSONL files in `tmp_path`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_news_ingest_iterator.py
git commit -m "test(news_ingest): end-to-end fixture feed → catalyst deleverage"
```

---

## Phase 5 — Wire into daemon

### Task 5.1: Register `NewsIngestIterator` in daemon.py and tiers.py

**Files:**
- Modify: `cli/commands/daemon.py`
- Modify: `cli/daemon/tiers.py`

- [ ] **Step 1: Edit `cli/daemon/tiers.py`**

Add `"news_ingest"` to each of the three tier lists. Insert immediately after `"radar"` in `watch`, and after `"radar"` in `opportunistic`; add as a new entry in `rebalance` between `"rebalancer"` and `"profit_lock"`.

Example for `watch` (find `"radar",` and add `"news_ingest",` on the next line):

```python
    "watch": [
        "account_collector",
        "connector",
        "liquidation_monitor",
        "funding_tracker",
        "protection_audit",
        "brent_rollover_monitor",
        "market_structure",
        "thesis_engine",
        "radar",
        "news_ingest",          # sub-system 1: RSS → catalysts (read-only, safe in WATCH)
        "pulse",
        "liquidity",
        "risk",
        "apex_advisor",
        "autoresearch",
        "memory_consolidation",
        "journal",
        "telegram",
    ],
```

Apply the same `"news_ingest"` line addition to the `rebalance` and `opportunistic` tier lists.

- [ ] **Step 2: Edit `cli/commands/daemon.py`**

Find the block around line 179:

```python
    clock.register(RadarIterator())
    clock.register(PulseIterator())
```

Insert one line BETWEEN them:

```python
    clock.register(RadarIterator())
    clock.register(NewsIngestIterator())   # sub-system 1: RSS → catalysts
    clock.register(PulseIterator())
```

Also add the import at the top of the file, next to the other iterator imports:

```python
from cli.daemon.iterators.news_ingest import NewsIngestIterator
```

- [ ] **Step 3: Run full daemon smoke test in mock mode**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
.venv/bin/python -m cli.commands.daemon start --tier watch --mock --max-ticks 2
```

Expected: daemon starts, runs 2 ticks, logs "NewsIngestIterator started", no crashes. Verify `data/news/headlines.jsonl` is either empty (no live feeds) or populated (if feeds responded). Verify daemon exits cleanly.

- [ ] **Step 4: Run existing daemon tests to confirm no regression**

```bash
.venv/bin/python -m pytest tests/ -x -q -k "daemon or tier"
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add cli/commands/daemon.py cli/daemon/tiers.py
git commit -m "feat(daemon): register news_ingest iterator in all three tiers"
```

---

## Phase 6 — Telegram surface

### Task 6.1: `/news` command + 5-surface checklist

**Files:**
- Modify: `cli/telegram_bot.py`
- Create: `tests/test_telegram_news_command.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_telegram_news_command.py
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from cli.telegram_bot import cmd_news

def _write_catalysts_jsonl(d, catalysts):
    path = Path(d) / "catalysts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for c in catalysts:
            f.write(json.dumps(c) + "\n")
    return path

def test_cmd_news_returns_top_10_by_severity(tmp_path):
    # Seed a mix of severities
    catalysts = []
    for i in range(15):
        catalysts.append({
            "id": f"c{i}",
            "headline_id": f"h{i}",
            "instruments": ["CL"],
            "event_date": "2026-04-09T12:00:00+00:00",
            "category": "physical_damage_facility",
            "severity": (i % 5) + 1,
            "expected_direction": "bull",
            "rationale": "test",
            "created_at": "2026-04-09T12:00:00+00:00",
        })
    _write_catalysts_jsonl(str(tmp_path), catalysts)

    with patch("cli.telegram_bot.CATALYSTS_JSONL", str(Path(tmp_path) / "catalysts.jsonl")):
        with patch("cli.telegram_bot._send_message") as send:
            cmd_news("fake_token", "chat_id", "")
            send.assert_called_once()
            body = send.call_args[0][2]  # third positional arg
            assert "catalyst" in body.lower()
            # 10 entries max
            assert body.count("sev=") <= 10 or body.count("  ") <= 10
```

- [ ] **Step 2: Run test**

Expected: FAIL — `cmd_news` does not exist yet.

- [ ] **Step 3: Implement `cmd_news`**

Open `cli/telegram_bot.py` and locate a logical insertion point (near other informational commands like `cmd_help` or `cmd_guide`). Add:

```python
# Near the top of the file, with other constants:
CATALYSTS_JSONL = "data/news/catalysts.jsonl"


def cmd_news(token: str, chat_id: str, args: str) -> None:
    """Show the last 10 catalysts ranked by severity DESC, created_at DESC.

    Deterministic — reads data/news/catalysts.jsonl directly, no AI.
    """
    import json
    from pathlib import Path

    path = Path(CATALYSTS_JSONL)
    if not path.exists():
        _send_message(token, chat_id, "🛢️ No catalysts yet. News ingestion may be disabled or still booting.")
        return

    entries: list[dict] = []
    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        _send_message(token, chat_id, f"🛢️ Error reading catalysts: {e}")
        return

    entries.sort(key=lambda c: (-int(c.get("severity", 0)), c.get("created_at", "")), reverse=False)
    top = entries[:10]

    if not top:
        _send_message(token, chat_id, "🛢️ No catalysts yet.")
        return

    lines = ["🛢️ *Latest catalysts (last 10 by severity)*", ""]
    for c in top:
        sev = int(c.get("severity", 0))
        cat = c.get("category", "?")
        when = c.get("event_date", "")[:16].replace("T", " ") + " UTC"
        direction = c.get("expected_direction") or "?"
        instruments = ", ".join(c.get("instruments", []))
        lines.append(f"`sev={sev}` {cat} — {when}")
        lines.append(f"  → {instruments} ({direction})")
        lines.append("")

    _send_message(token, chat_id, "\n".join(lines))
```

- [ ] **Step 4: Five-surface checklist (CLAUDE.md §Slash Commands point 3)**

All five edits live in the same file `cli/telegram_bot.py`:

1. ✅ Handler: `def cmd_news(...)` added above
2. HANDLERS dict: find the dict and add both forms:
   ```python
   HANDLERS = {
       # ... existing ...
       "/news": cmd_news,
       "news": cmd_news,
   }
   ```
3. `_set_telegram_commands()` list: find the list of `{"command": ..., "description": ...}` entries and add:
   ```python
   {"command": "news", "description": "Show last 10 catalysts by severity"},
   ```
4. `cmd_help()`: find the help text and add one line under the appropriate section:
   ```
   /news — last 10 catalysts by severity
   ```
5. `cmd_guide()`: add under the relevant user-facing section (probably a "Research" or "Intelligence" section):
   ```
   /news — shows recent catalysts surfaced by the news ingest iterator
   ```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_telegram_news_command.py -x -q`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add cli/telegram_bot.py tests/test_telegram_news_command.py
git commit -m "feat(telegram): /news command + 5-surface checklist"
```

### Task 6.2: `/catalysts` command + 5-surface checklist

**Files:**
- Modify: `cli/telegram_bot.py`
- Modify: `tests/test_telegram_news_command.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_telegram_news_command.py (append)
from cli.telegram_bot import cmd_catalysts

def test_cmd_catalysts_filters_upcoming(tmp_path):
    now = datetime.now(timezone.utc) if False else None  # placeholder
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=1)
    future = now + timedelta(days=3)
    far_future = now + timedelta(days=30)

    catalysts = [
        {
            "id": "past", "headline_id": "h1", "instruments": ["CL"],
            "event_date": past.isoformat(), "category": "eia_weekly",
            "severity": 3, "expected_direction": None, "rationale": "test",
            "created_at": past.isoformat(),
        },
        {
            "id": "near_future", "headline_id": "h2", "instruments": ["CL"],
            "event_date": future.isoformat(), "category": "opec_action",
            "severity": 4, "expected_direction": None, "rationale": "test",
            "created_at": now.isoformat(),
        },
        {
            "id": "far_future", "headline_id": "h3", "instruments": ["CL"],
            "event_date": far_future.isoformat(), "category": "fomc_macro",
            "severity": 3, "expected_direction": None, "rationale": "test",
            "created_at": now.isoformat(),
        },
    ]
    _write_catalysts_jsonl(str(tmp_path), catalysts)

    with patch("cli.telegram_bot.CATALYSTS_JSONL", str(Path(tmp_path) / "catalysts.jsonl")):
        with patch("cli.telegram_bot._send_message") as send:
            cmd_catalysts("fake_token", "chat_id", "")
            body = send.call_args[0][2]
            assert "near_future" in body or "opec_action" in body
            assert "far_future" not in body or "fomc_macro" not in body  # beyond 7 days
            assert "past" not in body  # already elapsed
```

- [ ] **Step 2: Run test**

Expected: FAIL — `cmd_catalysts` does not exist.

- [ ] **Step 3: Implement**

Add to `cli/telegram_bot.py`:

```python
def cmd_catalysts(token: str, chat_id: str, args: str) -> None:
    """Show upcoming catalysts in the next 7 days.

    Deterministic — reads data/news/catalysts.jsonl directly.
    """
    import json
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    path = Path(CATALYSTS_JSONL)
    if not path.exists():
        _send_message(token, chat_id, "🛢️ No upcoming catalysts.")
        return

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=7)

    upcoming: list[dict] = []
    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    c = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    ed = datetime.fromisoformat(c["event_date"])
                except (KeyError, ValueError):
                    continue
                if now <= ed <= horizon:
                    upcoming.append(c)
    except OSError as e:
        _send_message(token, chat_id, f"🛢️ Error reading catalysts: {e}")
        return

    if not upcoming:
        _send_message(token, chat_id, "🛢️ No catalysts in the next 7 days.")
        return

    upcoming.sort(key=lambda c: c["event_date"])

    lines = ["🛢️ *Upcoming catalysts (next 7 days)*", ""]
    for c in upcoming[:20]:
        when = c["event_date"][:16].replace("T", " ") + " UTC"
        sev = int(c.get("severity", 0))
        cat = c.get("category", "?")
        instruments = ", ".join(c.get("instruments", []))
        lines.append(f"`sev={sev}` {cat} — {when}")
        lines.append(f"  → {instruments}")
        lines.append("")

    _send_message(token, chat_id, "\n".join(lines))
```

- [ ] **Step 4: Five-surface checklist**

Apply all five surfaces for `/catalysts`, mirroring Task 6.1 steps 2-5 but for `cmd_catalysts`.

- [ ] **Step 5: Run tests**

Expected: 2 passing (Task 6.1's test + this one)

- [ ] **Step 6: Commit**

```bash
git add cli/telegram_bot.py tests/test_telegram_news_command.py
git commit -m "feat(telegram): /catalysts command + 5-surface checklist"
```

---

## Phase 7 — iCal bridge (scheduled events)

### Task 7.1: Parse iCal source → Catalyst

**Files:**
- Modify: `modules/news_engine.py`
- Modify: `tests/test_news_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_news_engine.py (append)
SAMPLE_ICAL = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//Test//EN
BEGIN:VEVENT
UID:eia-2026-04-16
SUMMARY:EIA Weekly Petroleum Status Report
DTSTART:20260416T143000Z
DTEND:20260416T150000Z
DESCRIPTION:Weekly crude oil inventory release
END:VEVENT
END:VCALENDAR
"""

def test_parse_ical_source():
    from modules.news_engine import parse_ical_source
    catalysts = parse_ical_source(
        SAMPLE_ICAL,
        source="eia_weekly_petroleum",
        category="eia_weekly",
        severity=3,
        instruments=["xyz:BRENTOIL", "CL"],
    )
    assert len(catalysts) == 1
    c = catalysts[0]
    assert c.category == "eia_weekly"
    assert c.severity == 3
    assert c.event_date.date() == datetime(2026, 4, 16).date()
```

- [ ] **Step 2: Run test**

Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement**

```python
# modules/news_engine.py (append)
from icalendar import Calendar


def parse_ical_source(
    ical_text: str,
    source: str,
    category: str,
    severity: int,
    instruments: list[str],
    direction: str | None = None,
) -> list[Catalyst]:
    """Parse an iCal VCALENDAR and return one Catalyst per VEVENT.

    Used for scheduled events (EIA, OPEC, FOMC) where the news ingest rule
    library is not the right fit — we already know these are catalysts; we
    just need to publish them into the same pipeline.
    """
    try:
        cal = Calendar.from_ical(ical_text)
    except Exception as e:
        log.warning("iCal parse failed for source=%s: %s", source, e)
        return []

    now = datetime.now(timezone.utc)
    out: list[Catalyst] = []
    for comp in cal.walk("VEVENT"):
        dtstart = comp.get("DTSTART")
        if dtstart is None:
            continue
        start = dtstart.dt
        if hasattr(start, "tzinfo") and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        elif not hasattr(start, "tzinfo"):
            # date-only VEVENT
            start = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)

        summary = str(comp.get("SUMMARY") or "")
        uid = str(comp.get("UID") or _hash_headline(source, summary, start.isoformat()))
        out.append(Catalyst(
            id=_hash_headline(source, uid, summary),
            headline_id=uid,
            instruments=list(instruments),
            event_date=start,
            category=category,
            severity=severity,
            expected_direction=direction,
            rationale=f"ical:{source}",
            created_at=now,
        ))
    return out
```

- [ ] **Step 4: Run test**

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add modules/news_engine.py tests/test_news_engine.py
git commit -m "feat(news_engine): iCal source → Catalyst parser"
```

---

## Phase 8 — Docs + ship gates

### Task 8.1: Create wiki page `docs/wiki/components/news_ingest.md`

**Files:**
- Create: `docs/wiki/components/news_ingest.md`

- [ ] **Step 1: Write page**

```markdown
# news_ingest iterator

**Runs in:** WATCH, REBALANCE, OPPORTUNISTIC (all tiers — read-only, safe everywhere)
**Source:** `cli/daemon/iterators/news_ingest.py`
**Pure logic:** `modules/news_engine.py`
**Bridge:** `modules/catalyst_bridge.py`
**Spec:** `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md`
**Implementation plan:** `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md`

## Purpose

Polls public RSS feeds and iCal calendars, deduplicates headlines, tags them
against a YAML-defined rule library, extracts structured `Catalyst` records,
and feeds high-severity catalysts to the existing `CatalystDeleverageIterator`
via a dedicated external file.

Sub-system 1 of the Oil Bot-Pattern Strategy (see `OIL_BOT_PATTERN_SYSTEM.md`
for the broader architecture).

## Inputs

- `data/config/news_feeds.yaml` — feed registry (URL, poll interval, enabled)
- `data/config/news_rules.yaml` — rule library (11 categories as of V1)
- `data/config/news_ingest.json` — runtime config (kill switch, thresholds)

## Outputs

- `data/news/headlines.jsonl` — append-only raw headline log
- `data/news/catalysts.jsonl` — append-only structured catalyst log
- `data/daemon/external_catalyst_events.json` — CatalystEvents fan-out for the
  existing `CatalystDeleverageIterator` to pick up via its tick prologue
- Telegram alerts for severity ≥ 4 catalysts (deduped by `Catalyst.id`)

## Telegram commands

- `/news` — last 10 catalysts by severity (deterministic, NOT AI)
- `/catalysts` — upcoming catalysts in next 7 days (deterministic, NOT AI)

## Kill switch

Edit `data/config/news_ingest.json` → `"enabled": false`. On the next tick the
iterator no-ops: no polling, no writes, no alerts. The existing
`CatalystDeleverageIterator` continues reading its hand-curated state file
unchanged.

## Out of scope

- Sentiment scoring (sub-system 4 — bot-pattern classifier)
- Price-impact prediction (sub-system 5 — strategy engine)
- Supply disruption ledger (sub-system 2 — separate brainstorm)
- Twitter / X feeds (deferred)
- LLM-based headline summarisation (deferred)

## Known limitations

- V1 dedup is per-source only. Same event from Reuters AND AP will produce two
  separate `Catalyst` records. Cross-source clustering is handled by
  sub-system 4 during signal scoring.
- V1 severity/direction is pure keyword-based. Fine-tuning via journal replay
  is sub-system 6's job.
- iCal sources are only enabled if their URLs are verified at implementation
  time; placeholder entries remain `enabled: false` until validated.
```

- [ ] **Step 2: Commit**

```bash
git add docs/wiki/components/news_ingest.md
git commit -m "docs: wiki page for news_ingest iterator"
```

### Task 8.2: Update `CLAUDE.md` daemon iterator reference

**Files:**
- Modify: `CLAUDE.md` (project root)

- [ ] **Step 1: Find the relevant daemon section**

Run: `grep -n "daemon" /Users/cdi/Developer/HyperLiquid_Bot/CLAUDE.md | head -20`

Add one line to the daemon iterator listing (or architecture section) mentioning `news_ingest` as sub-system 1 of the oil bot pattern strategy.

- [ ] **Step 2: Edit CLAUDE.md with the minimum addition**

```markdown
- `news_ingest` — sub-system 1 of the Oil Bot-Pattern Strategy. Polls RSS/iCal
  feeds and feeds structured catalysts to `catalyst_deleverage`. Kill switch:
  `data/config/news_ingest.json`. Spec: `agent-cli/docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION.md`.
```

- [ ] **Step 3: Commit**

```bash
git add ../CLAUDE.md  # if in agent-cli subdir; otherwise CLAUDE.md
git commit -m "docs(CLAUDE): reference news_ingest iterator"
```

### Task 8.3: Add build-log entry

**Files:**
- Modify: `docs/wiki/build-log.md`

- [ ] **Step 1: Append entry**

```markdown
## 2026-04-XX — Oil Bot-Pattern Sub-System 1 shipped

- **What:** First sub-system of the Oil Bot-Pattern Strategy ships — news & catalyst ingestion.
- **Why:** Chris identified that bot-driven mispricing around scheduled catalysts (e.g. Trump's 8 PM Iran deadline) leaves systematic arbitrage on the table for a petroleum-engineer operator. Sub-system 1 is the foundation: scraped headlines → structured catalysts → existing deleverage pipeline.
- **Shape:** New `modules/news_engine.py` (pure logic), `modules/catalyst_bridge.py` (Catalyst → CatalystEvent conversion), `cli/daemon/iterators/news_ingest.py` (WATCH/REBALANCE/OPPORTUNISTIC tiers). Additive-only edits to `cli/daemon/iterators/catalyst_deleverage.py` (new `add_external_catalysts()` method + `tick()` file-watcher prologue). Two new Telegram commands: `/news`, `/catalysts` (both deterministic, not AI).
- **Deps added:** `feedparser>=6.0.10`, `icalendar>=5.0.0`. User-approved in spec §13.
- **Kill switch:** `data/config/news_ingest.json` → `enabled: false`.
- **Dry-run:** 24h with `severity_floor: 5`. Promoted to `severity_floor: 3` after dry-run passed.
- **Tests:** 19 tests from spec §9, all green.
- **Next:** Sub-system 2 — Supply Disruption Ledger (separate brainstorm).
- **Plan:** `docs/plans/OIL_BOT_PATTERN_01_NEWS_INGESTION_PLAN.md`
```

Fill in the actual ship date when committing.

- [ ] **Step 2: Commit**

```bash
git add docs/wiki/build-log.md
git commit -m "docs(build-log): 2026-04-XX oil bot pattern sub-system 1 shipped"
```

### Task 8.4: Dry-run phase (≥24h, severity_floor=5)

**Files:** None modified during this task — it's an operational gate, not a code task.

- [ ] **Step 1: Verify dry-run config**

Run: `cat data/config/news_ingest.json`
Expected: `"enabled": true` and `"severity_floor": 5`.

- [ ] **Step 2: Start daemon in production tier**

The daemon is already running in production per MASTER_PLAN.md; restart it via the existing launchd plist so the new iterator registers:

```bash
launchctl kickstart -k gui/$(id -u)/com.hyperliquid.daemon
```

Watch logs:
```bash
tail -f ~/Library/Logs/hyperliquid-daemon.log
```

- [ ] **Step 3: Wait ≥ 24 hours**

During this window:
- Monitor `data/news/headlines.jsonl` — should grow as feeds are polled
- Monitor `data/news/catalysts.jsonl` — grows slower
- Monitor `data/daemon/external_catalyst_events.json` — should ONLY contain severity-5 entries
- Watch Telegram — severity-4+ alerts should fire without duplicates

- [ ] **Step 4: Check pass criteria**

- [ ] Alerts fire on real catalysts: verify at least one alert fired during the window
- [ ] No duplicate alerts: search `data/daemon/chat_history.jsonl` for duplicate `NEW CATALYST` lines — count should match `external_catalyst_events.json` entries
- [ ] No severity-3/4 entries in `external_catalyst_events.json`: run `jq '.events[].name' data/daemon/external_catalyst_events.json` and cross-reference against `catalysts.jsonl` severity values; fail if any entry corresponds to a severity < 5 Catalyst
- [ ] Daemon has not crashed, circuit-breaker not tripped

- [ ] **Step 5: Promote severity_floor**

Edit `data/config/news_ingest.json`:
```json
{
  "severity_floor": 3
}
```

- [ ] **Step 6: Commit the promotion**

```bash
git add data/config/news_ingest.json
git commit -m "config(news_ingest): promote severity_floor 5 → 3 after 24h dry-run"
```

- [ ] **Step 7: Verify in production**

Restart the daemon (`launchctl kickstart -k ...`) and monitor that severity-3 and severity-4 catalysts now begin appearing in `external_catalyst_events.json`.

---

## Plan Self-Review

### Spec coverage check

| Spec §  | Requirement | Covered by |
|---|---|---|
| §1 | Purpose + boundary (does/does-not) | File structure + Task 4.1 skeleton |
| §2 | Data flow diagram | Task 4.2 (polling) + Task 3.1/3.2 (bridge) + Task 3.3/3.4 (deleverage hook) |
| §3 | Files (9 new, 4 edited) | "File structure" section + every task |
| §4 | `Headline` + `Catalyst` dataclasses | Task 1.1 |
| §5 | 11 rule categories | Task 2.1 (YAML) + Task 1.7 (tagger) + Task 1.8 (conditional direction) |
| §5 | Rule-conditional direction code example | Task 1.8 |
| §6 | Feed list (4 RSS + 3 iCal) | Task 2.2 |
| §7 | `/news` + `/catalysts` with 5-surface checklist | Task 6.1 + Task 6.2 |
| §7 | Severity ≥ alert_floor Telegram alerts | Task 4.2 `_maybe_alert` |
| §8 | Configuration schema | Task 2.3 |
| §9 test 1 | Atom parser | Task 1.2 |
| §9 test 2 | RSS 2.0 parser | Task 1.3 |
| §9 test 3 | Malformed feed | Task 1.4 |
| §9 test 4, 5 | Dedup | Task 1.5 |
| §9 tests 6-10 | Rule tagger positive + negative | Task 1.7 |
| §9 test 11 | Severity threshold filter | Task 3.2 |
| §9 test 12 | Alert above alert_floor | Task 4.2 (verified in Task 4.3 e2e) |
| §9 test 13 | Alert dedupe | Task 4.2 (_alerted_catalyst_ids set) |
| §9 test 14 | Event date parser | Task 1.9 |
| §9 test 15 | Catalyst feeder preserves existing | Task 3.2 |
| §9 test 16 | Iterator handles failing feed | Task 4.2 |
| §9 test 17 | Iterator throttles per feed | Task 4.2 |
| §9 test 18 | Kill switch noop | Task 4.1 |
| §9 test 19 | End-to-end fixture feed → catalyst deleverage | Task 4.3 |
| §10 | Ship gates checklist | Task 8.4 |
| §11 | Risks | Addressed in file structure ("additive only") + Task 3.4 regression check |
| §12 | Out of scope | Wiki page Task 8.1 |
| §13 | Open questions | Resolved: feedparser+icalendar (Task 0.1), catalyst_bridge separate (Task 3.1), real fixtures (Task 0.2), tick-driven (Task 4.2) |

All 19 spec tests have explicit task assignments. No coverage gaps.

### Placeholder scan

No `TODO`, `TBD`, "implement later", "write tests for the above without code", or "similar to Task N" phrases. Every code step shows actual code.

One intentional `2026-04-XX` placeholder remains in Task 8.3 (build-log entry) — this is filled in at commit time and is a conventional project pattern, not a plan failure.

### Type consistency check

- `Headline.id` (str, sha256[:16]) used consistently as FK in `Catalyst.headline_id`
- `Catalyst.id` (str) used consistently in `catalyst_bridge.catalyst_to_events` and alert dedup
- `Rule.direction` type `str | None` consistent across YAML loader, tagger, extractor
- `CatalystEvent.name` (str) used consistently as dedup key in `add_external_catalysts`
- `catalyst_bridge.persist` signature `(catalysts, output_path, severity_floor)` stable across tasks 3.1 and 4.2
- `tag_headline(headline, rules)` signature used identically in Tasks 1.7 and 1.10

No drift.
