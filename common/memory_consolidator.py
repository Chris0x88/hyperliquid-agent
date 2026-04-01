"""Memory consolidator — inspired by Claude Code's "dream" system.

Compresses old events and observations into bounded summaries so the AI
gets accumulated knowledge without unbounded context growth.

Philosophy:
- NEVER delete source rows (events, learnings stay forever in SQLite)
- Summaries LINK to source IDs (lossless reference)
- Old events get compressed: 50 events → 1 summary paragraph
- Summaries have a market + time range, so context builder can pick the right ones
- Consolidation runs periodically (not every tick) — triggered by context builder or cron

Inspired by Claude Code's autoDream:
  Phase 1 - Orient: check what's already summarized
  Phase 2 - Gather: find unsummarized events older than threshold
  Phase 3 - Consolidate: compress event clusters into summaries
  Phase 4 - Prune: keep summary index bounded per market

Unlike Claude Code (which uses an LLM for summarization), we use pure code
to compress events — no AI dependency for the consolidation itself. The AI
reads the summaries, it doesn't write them. This is the key difference:
trading memory must be deterministic and auditable.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("memory_consolidator")

_DB_PATH = "data/memory/memory.db"

# Consolidation thresholds
MIN_EVENTS_TO_CONSOLIDATE = 10     # need at least 10 events to make a summary
EVENT_AGE_THRESHOLD_DAYS = 7       # only consolidate events older than 7 days
MAX_SUMMARIES_PER_MARKET = 50      # prune oldest summaries beyond this
MAX_SUMMARY_CHARS = 500            # each summary is max 500 chars
CONSOLIDATION_WINDOW_DAYS = 7      # group events into weekly windows


@dataclass
class ConsolidationStats:
    """Report from one consolidation run."""
    events_scanned: int = 0
    events_consolidated: int = 0
    summaries_created: int = 0
    summaries_pruned: int = 0
    markets_touched: List[str] = field(default_factory=list)
    duration_ms: int = 0


def consolidate(db_path: str = _DB_PATH) -> ConsolidationStats:
    """Run one consolidation pass.

    1. Find events older than threshold that aren't already covered by a summary
    2. Group by market + weekly window
    3. Compress each group into a summary row
    4. Prune excess summaries per market

    Returns stats about what was done.
    """
    start = time.monotonic()
    stats = ConsolidationStats()

    con = _get_conn(db_path)

    # Phase 1: Orient — find what's already summarized
    existing_ranges = _get_existing_summary_ranges(con)

    # Phase 2: Gather — find unsummarized old events
    cutoff_ms = int((time.time() - EVENT_AGE_THRESHOLD_DAYS * 86400) * 1000)
    old_events = con.execute(
        "SELECT id, timestamp_ms, market, event_type, title, detail, tags "
        "FROM events WHERE timestamp_ms < ? ORDER BY timestamp_ms",
        (cutoff_ms,),
    ).fetchall()

    stats.events_scanned = len(old_events)

    if not old_events:
        stats.duration_ms = int((time.monotonic() - start) * 1000)
        return stats

    # Group by market + weekly window
    groups = _group_events(old_events, existing_ranges)

    # Phase 3: Consolidate — compress each group
    for (market, window_start, window_end), events in groups.items():
        if len(events) < MIN_EVENTS_TO_CONSOLIDATE:
            continue

        summary_text = _compress_events(events, market)
        source_ids = json.dumps([e["id"] for e in events])

        con.execute(
            "INSERT INTO summaries (market, summary_type, content, generated_at, "
            "covers_from, covers_to, source_ids) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (market, "weekly_consolidation", summary_text,
             int(time.time() * 1000), window_start, window_end, source_ids),
        )
        con.commit()

        stats.events_consolidated += len(events)
        stats.summaries_created += 1
        if market and market not in stats.markets_touched:
            stats.markets_touched.append(market)

        log.info(
            "Consolidated %d events for %s (%s to %s) → %d chars",
            len(events), market or "global",
            _ms_to_date(window_start), _ms_to_date(window_end),
            len(summary_text),
        )

    # Phase 4: Prune — keep bounded summaries per market
    stats.summaries_pruned = _prune_old_summaries(con)

    # Also consolidate learnings.md if it's too large
    _trim_learnings_file()

    stats.duration_ms = int((time.monotonic() - start) * 1000)
    log.info(
        "Consolidation complete: %d events → %d summaries (%d pruned) in %dms",
        stats.events_consolidated, stats.summaries_created,
        stats.summaries_pruned, stats.duration_ms,
    )
    return stats


def get_consolidated_context(
    market: str,
    days: int = 90,
    max_chars: int = 3000,
    db_path: str = _DB_PATH,
) -> str:
    """Get memory context using summaries for old data + raw events for recent.

    This is the key function the context harness calls. It returns a bounded
    string that covers both recent detail and historical summaries.

    Strategy:
    - Recent events (< 7 days): include raw (full detail, most relevant)
    - Older: use summaries (compressed, still covers the period)
    - Learnings: always include (they're already compressed wisdom)
    """
    con = _get_conn(db_path)
    lines = []
    char_count = 0

    # 1. Recent events (raw, full detail)
    recent_cutoff = int((time.time() - 7 * 86400) * 1000)
    recent_events = con.execute(
        "SELECT timestamp_ms, event_type, title, detail FROM events "
        "WHERE timestamp_ms >= ? AND (market = ? OR market IS NULL) "
        "ORDER BY timestamp_ms DESC LIMIT 30",
        (recent_cutoff, market),
    ).fetchall()

    if recent_events:
        lines.append(f"RECENT ({market}, last 7d):")
        for ev in reversed(list(recent_events)):
            date = _ms_to_date(ev["timestamp_ms"])
            line = f"  {date} [{ev['event_type']}] {ev['title']}"
            if ev["detail"]:
                line += f" — {ev['detail'][:100]}"
            if char_count + len(line) > max_chars * 0.6:
                break
            lines.append(line)
            char_count += len(line)

    # 2. Historical summaries (compressed)
    historical_cutoff = int((time.time() - days * 86400) * 1000)
    summaries = con.execute(
        "SELECT content, covers_from, covers_to FROM summaries "
        "WHERE (market = ? OR market IS NULL) AND covers_from >= ? "
        "ORDER BY covers_from DESC LIMIT 10",
        (market, historical_cutoff),
    ).fetchall()

    if summaries:
        lines.append(f"HISTORY ({market}, summarized):")
        for s in reversed(list(summaries)):
            date_range = f"{_ms_to_date(s['covers_from'])}→{_ms_to_date(s['covers_to'])}"
            line = f"  [{date_range}] {s['content']}"
            if char_count + len(line) > max_chars * 0.85:
                break
            lines.append(line)
            char_count += len(line)

    # 3. Learnings (always include — they're compressed wisdom)
    learnings = con.execute(
        "SELECT title, lesson, topic FROM learnings "
        "WHERE (market = ? OR market IS NULL) "
        "ORDER BY timestamp_ms DESC LIMIT 8",
        (market,),
    ).fetchall()

    if learnings:
        lines.append(f"LEARNINGS ({market}):")
        for lrn in learnings:
            line = f"  [{lrn['topic']}] {lrn['title']}: {lrn['lesson'][:120]}"
            if char_count + len(line) > max_chars:
                break
            lines.append(line)
            char_count += len(line)

    return "\n".join(lines)


def get_active_observations(
    market: str,
    max_items: int = 10,
    db_path: str = _DB_PATH,
) -> List[Dict]:
    """Get currently valid observations for a market, sorted by priority."""
    con = _get_conn(db_path)
    now_ms = int(time.time() * 1000)

    rows = con.execute(
        "SELECT priority, category, title, body FROM observations "
        "WHERE market = ? AND valid_until IS NULL OR valid_until > ? "
        "ORDER BY priority ASC, created_at DESC LIMIT ?",
        (market, now_ms, max_items),
    ).fetchall()

    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _get_conn(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _get_existing_summary_ranges(
    con: sqlite3.Connection,
) -> Dict[str, List[Tuple[int, int]]]:
    """Get (covers_from, covers_to) ranges per market for existing summaries."""
    rows = con.execute(
        "SELECT market, covers_from, covers_to FROM summaries "
        "WHERE covers_from IS NOT NULL AND covers_to IS NOT NULL"
    ).fetchall()

    result: Dict[str, List[Tuple[int, int]]] = {}
    for r in rows:
        mk = r["market"] or "__global__"
        if mk not in result:
            result[mk] = []
        result[mk].append((r["covers_from"], r["covers_to"]))
    return result


def _is_already_summarized(
    event_ts: int,
    market: str,
    existing_ranges: Dict[str, List[Tuple[int, int]]],
) -> bool:
    """Check if an event's timestamp falls within an existing summary range."""
    mk = market or "__global__"
    for (start, end) in existing_ranges.get(mk, []):
        if start <= event_ts <= end:
            return True
    return False


def _group_events(
    events: list,
    existing_ranges: Dict[str, List[Tuple[int, int]]],
) -> Dict[Tuple[str, int, int], List[Dict]]:
    """Group events by market + weekly window, excluding already-summarized."""
    window_ms = CONSOLIDATION_WINDOW_DAYS * 86_400_000
    groups: Dict[Tuple[str, int, int], List[Dict]] = {}

    for row in events:
        ev = dict(row)
        market = ev.get("market") or "__global__"

        if _is_already_summarized(ev["timestamp_ms"], market, existing_ranges):
            continue

        # Compute weekly window
        window_start = (ev["timestamp_ms"] // window_ms) * window_ms
        window_end = window_start + window_ms

        key = (market, window_start, window_end)
        if key not in groups:
            groups[key] = []
        groups[key].append(ev)

    return groups


def _compress_events(events: List[Dict], market: str) -> str:
    """Compress a group of events into a summary paragraph.

    Pure code — no LLM. Extracts key facts deterministically:
    - Event type distribution
    - Key titles (most unique/important)
    - Date range
    - Tag frequency
    """
    if not events:
        return ""

    # Date range
    dates = sorted(ev["timestamp_ms"] for ev in events)
    date_from = _ms_to_date(dates[0])
    date_to = _ms_to_date(dates[-1])

    # Event type counts
    type_counts: Dict[str, int] = {}
    for ev in events:
        et = ev.get("event_type", "unknown")
        type_counts[et] = type_counts.get(et, 0) + 1

    type_summary = ", ".join(f"{c}x {t}" for t, c in sorted(type_counts.items(), key=lambda x: -x[1]))

    # Top titles (deduplicated, most frequent type first)
    title_set: set = set()
    key_titles = []
    for ev in sorted(events, key=lambda e: -type_counts.get(e.get("event_type", ""), 0)):
        t = ev.get("title", "")
        if t and t not in title_set:
            title_set.add(t)
            key_titles.append(t)
        if len(key_titles) >= 5:
            break

    # Tag frequency
    all_tags: Dict[str, int] = {}
    for ev in events:
        tags_raw = ev.get("tags")
        if tags_raw:
            try:
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
                for tag in tags:
                    all_tags[tag] = all_tags.get(tag, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

    top_tags = sorted(all_tags.items(), key=lambda x: -x[1])[:5]
    tags_str = ", ".join(f"{t}({c})" for t, c in top_tags) if top_tags else "none"

    # Compose summary
    parts = [
        f"{date_from}→{date_to}: {len(events)} events ({type_summary}).",
        f"Key: {'; '.join(key_titles[:3])}.",
    ]
    if top_tags:
        parts.append(f"Tags: {tags_str}.")

    summary = " ".join(parts)

    # Enforce max chars
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS - 3] + "..."

    return summary


def _prune_old_summaries(con: sqlite3.Connection) -> int:
    """Keep at most MAX_SUMMARIES_PER_MARKET per market. Delete oldest."""
    pruned = 0

    markets = con.execute("SELECT DISTINCT market FROM summaries").fetchall()
    for row in markets:
        market = row["market"]
        count = con.execute(
            "SELECT COUNT(*) FROM summaries WHERE market = ? OR (market IS NULL AND ? IS NULL)",
            (market, market),
        ).fetchone()[0]

        if count > MAX_SUMMARIES_PER_MARKET:
            excess = count - MAX_SUMMARIES_PER_MARKET
            con.execute(
                "DELETE FROM summaries WHERE id IN ("
                "  SELECT id FROM summaries WHERE market = ? OR (market IS NULL AND ? IS NULL) "
                "  ORDER BY covers_from ASC LIMIT ?"
                ")",
                (market, market, excess),
            )
            con.commit()
            pruned += excess
            log.info("Pruned %d old summaries for %s", excess, market or "global")

    return pruned


def _trim_learnings_file(max_bytes: int = 25_000) -> None:
    """Keep learnings.md under max_bytes, trimming oldest entries.

    Inspired by Claude Code's MEMORY.md 200-line / 25KB cap.
    """
    path = "data/research/learnings.md"
    if not os.path.exists(path):
        return

    try:
        content = open(path).read()
        if len(content) <= max_bytes:
            return

        # Keep header (first 3 lines) + most recent entries
        lines = content.split("\n")
        header = lines[:3]

        # Find entry boundaries (## headers)
        entries = []
        current: List[str] = []
        for line in lines[3:]:
            if line.startswith("## ") and current:
                entries.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            entries.append("\n".join(current))

        # Keep most recent entries that fit
        kept = []
        budget = max_bytes - len("\n".join(header)) - 100
        for entry in reversed(entries):
            if budget - len(entry) < 0:
                break
            kept.insert(0, entry)
            budget -= len(entry)

        trimmed = "\n".join(header) + "\n" + "\n".join(kept)

        # Atomic write
        tmp_path = path + ".tmp"
        with open(tmp_path, "w") as f:
            f.write(trimmed)
        os.rename(tmp_path, path)

        log.info(
            "Trimmed learnings.md: %d → %d bytes (%d → %d entries)",
            len(content), len(trimmed), len(entries), len(kept),
        )
    except Exception as e:
        log.warning("Failed to trim learnings.md: %s", e)


def _ms_to_date(ms: int) -> str:
    """Convert millisecond timestamp to compact date string."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
