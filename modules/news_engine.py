"""News engine — pure logic for feed parsing, dedup, rule tagging, catalyst extraction.

All I/O is injected. This module has no knowledge of the daemon, HL, or trading.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser

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
