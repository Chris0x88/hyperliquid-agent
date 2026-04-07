"""Calendar tags helper — surfaces session/event regime as alert tags.

This is the C4 piece from the 2026-04-07 connections audit. The
common/calendar.py CalendarContext is rich but it's only ever consumed
by the AI prompt path (scheduled_check.py) and never by the daemon.
This helper bridges the gap: it builds a tiny dict of regime tags that
daemon iterators (risk, liquidation_monitor) attach to their alerts so
the user knows what calendar context an alert fired in.

Defensive by design:
  - Never raises. Returns an empty tag set on any failure.
  - Cached for 300 seconds — calendar doesn't change minute-to-minute
    and the daemon should not call get_current() every tick.

Returns shape:
  {
    "weekend": bool,
    "thin_session": bool,
    "high_impact_event_24h": bool,
    "session": str,                  # e.g. "asia", "us", "weekend"
    "tags": List[str],               # ordered, human-readable
  }

The 'tags' list is the canonical surface for alert messages — appending
something like " [WEEKEND, THIN]" gives the operator instant context for
why an alert fired without needing a separate calendar query.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

log = logging.getLogger("daemon.calendar_tags")

# Cache duration — calendar regime is stable on minute-scale
_CACHE_TTL_S = 300

_cache: Dict[str, Any] = {"ts": 0.0, "tags": None}


def get_current_tags() -> Dict[str, Any]:
    """Return current calendar regime tags. Cached, never raises."""
    now = time.monotonic()
    if _cache["tags"] is not None and (now - _cache["ts"]) < _CACHE_TTL_S:
        return _cache["tags"]

    tags = _build_tags()
    _cache["ts"] = now
    _cache["tags"] = tags
    return tags


def _empty_tags() -> Dict[str, Any]:
    return {
        "weekend": False,
        "thin_session": False,
        "high_impact_event_24h": False,
        "session": "unknown",
        "tags": [],
    }


def _build_tags() -> Dict[str, Any]:
    try:
        from common.calendar import CalendarContext
    except Exception as e:
        log.debug("calendar_tags: import failed: %s", e)
        return _empty_tags()

    try:
        ctx = CalendarContext.get_current()
    except Exception as e:
        log.debug("calendar_tags: get_current failed: %s", e)
        return _empty_tags()

    out = _empty_tags()
    tag_list: List[str] = []

    try:
        session = ctx.session
        out["session"] = (session.name or "unknown").lower()
        if getattr(session, "weekend", False):
            out["weekend"] = True
            tag_list.append("WEEKEND")
        vol = (getattr(session, "volume_profile", "") or "").lower()
        if vol in ("thin", "very_thin", "low"):
            out["thin_session"] = True
            tag_list.append("THIN")
        if not out["weekend"] and out["session"] not in ("unknown", ""):
            tag_list.append(out["session"].upper())
    except Exception as e:
        log.debug("calendar_tags: session parse failed: %s", e)

    try:
        events = ctx.events_next_48h or []
        for ev in events:
            hours = ev.get("hours_away", 999)
            impact = (ev.get("impact", "") or "").lower()
            if hours <= 24 and impact in ("high", "critical"):
                out["high_impact_event_24h"] = True
                name = (ev.get("name", "EVENT") or "EVENT").upper()
                tag_list.append(f"EVENT<24H:{name[:20]}")
                break
    except Exception as e:
        log.debug("calendar_tags: events parse failed: %s", e)

    out["tags"] = tag_list
    return out


def reset_cache() -> None:
    """Clear the cache. Used by tests; not called from production code."""
    _cache["ts"] = 0.0
    _cache["tags"] = None
