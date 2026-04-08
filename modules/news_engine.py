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
