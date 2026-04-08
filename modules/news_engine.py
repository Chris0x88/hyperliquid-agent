"""News engine — pure logic for feed parsing, dedup, rule tagging, catalyst extraction.

All I/O is injected. This module has no knowledge of the daemon, HL, or trading.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser
import yaml
from icalendar import Calendar

log = logging.getLogger("news_engine")


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

    # "tomorrow" anywhere in the text, with a "N AM/PM" token either before or after it.
    # The plan's original regex required "tomorrow" to come first, but real headlines
    # put the phrase either way around ("tomorrow at 8 PM" or "8 PM deadline tomorrow").
    if "tomorrow" in text:
        m = re.search(r"(\d{1,2})\s*(am|pm)", text)
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
