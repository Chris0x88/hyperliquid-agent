"""
Local memory system — inspired by LosslessClaw (Martian-Engineering).

Philosophy:
- NEVER lose data. SQLite stores every event, observation, and learning.
- Hierarchical summaries: old data compressed but still queryable.
- Temporal accuracy: events tagged with exact timestamps — "when did X happen?"
  is always answerable without relying on recency bias.
- Market-aware: context is always filtered to what's relevant.

Tables:
  events     — geopolitical events, trades, signals, operational notes
  learnings  — lessons (topic-tagged) that persist across conversations
  summaries  — AI-generated compressions of old event clusters (lossless: link to source IDs)
"""
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

_DB_PATH = "data/memory/memory.db"


def _conn(db_path: str = _DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    _init(con)
    return con


def _init(con: sqlite3.Connection):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_ms INTEGER NOT NULL,
            market      TEXT,
            event_type  TEXT NOT NULL,
            title       TEXT NOT NULL,
            detail      TEXT,
            tags        TEXT,
            source      TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_market ON events(market);
        CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp_ms);

        CREATE TABLE IF NOT EXISTS learnings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_ms INTEGER NOT NULL,
            topic       TEXT NOT NULL,
            title       TEXT NOT NULL,
            lesson      TEXT NOT NULL,
            confidence  TEXT,
            source      TEXT,
            market      TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_learnings_topic ON learnings(topic);
        CREATE INDEX IF NOT EXISTS idx_learnings_market ON learnings(market);

        CREATE TABLE IF NOT EXISTS summaries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            market       TEXT,
            summary_type TEXT NOT NULL,
            content      TEXT NOT NULL,
            generated_at INTEGER NOT NULL,
            covers_from  INTEGER,
            covers_to    INTEGER,
            source_ids   TEXT
        );

        CREATE TABLE IF NOT EXISTS observations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at      INTEGER NOT NULL,
            valid_from      INTEGER NOT NULL,
            valid_until     INTEGER,
            superseded_by   INTEGER,
            market          TEXT NOT NULL,
            category        TEXT NOT NULL,
            priority        INTEGER NOT NULL DEFAULT 2,
            title           TEXT NOT NULL,
            body            TEXT,
            tags            TEXT DEFAULT '[]',
            source          TEXT NOT NULL DEFAULT 'programmatic'
        );
        CREATE INDEX IF NOT EXISTS idx_obs_active ON observations(market, category) WHERE valid_until IS NULL;
        CREATE INDEX IF NOT EXISTS idx_obs_market_time ON observations(market, created_at);

        CREATE TABLE IF NOT EXISTS action_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_ms    INTEGER NOT NULL,
            market          TEXT NOT NULL,
            action_type     TEXT NOT NULL,
            detail          TEXT,
            reasoning       TEXT,
            source          TEXT NOT NULL DEFAULT 'programmatic',
            outcome         TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_action_market_time ON action_log(market, timestamp_ms);

        CREATE TABLE IF NOT EXISTS execution_traces (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_ms    INTEGER NOT NULL,
            process         TEXT NOT NULL,
            duration_ms     INTEGER,
            success         INTEGER NOT NULL,
            stdout          TEXT,
            stderr          TEXT,
            actions_taken   TEXT,
            errors          TEXT
        );

        -- Account snapshots: queryable historical record of account state.
        -- Dual-written from cli/daemon/iterators/account_collector.py alongside
        -- the JSON files in data/snapshots/. JSON files remain the canonical
        -- source for "latest snapshot"; this table enables time-range queries
        -- and analytical access to history (equity over time, drawdown
        -- timeline, position count history, etc.).
        CREATE TABLE IF NOT EXISTS account_snapshots (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_ms      INTEGER NOT NULL,
            snapshot_filename TEXT,
            equity_total      REAL NOT NULL DEFAULT 0,
            equity_native     REAL NOT NULL DEFAULT 0,
            equity_xyz        REAL NOT NULL DEFAULT 0,
            spot_usdc         REAL NOT NULL DEFAULT 0,
            high_water_mark   REAL NOT NULL DEFAULT 0,
            drawdown_pct      REAL NOT NULL DEFAULT 0,
            has_positions     INTEGER NOT NULL DEFAULT 0,
            position_count    INTEGER NOT NULL DEFAULT 0,
            positions_json    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_account_snapshots_ts
            ON account_snapshots(timestamp_ms);

        -- ------------------------------------------------------------------
        -- Trade lessons: verbatim post-mortems authored by the agent after
        -- every closed position. Append-only (body_full and summary are
        -- frozen at insert time; only reviewed_by_chris and tags may change).
        -- Indexed with FTS5 for BM25-ranked recall at decision time.
        -- See modules/lesson_engine.py for the pure-computation layer.
        -- ------------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS lessons (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at          TEXT NOT NULL,
            trade_closed_at     TEXT NOT NULL,
            market              TEXT NOT NULL,
            direction           TEXT NOT NULL CHECK (direction IN ('long','short','flat')),
            signal_source       TEXT NOT NULL,
            lesson_type         TEXT NOT NULL,
            outcome             TEXT NOT NULL CHECK (outcome IN ('win','loss','breakeven','scratched')),
            pnl_usd             REAL NOT NULL,
            roe_pct             REAL NOT NULL,
            holding_ms          INTEGER NOT NULL,
            conviction_at_open  REAL,
            journal_entry_id    TEXT,
            thesis_snapshot_path TEXT,
            summary             TEXT NOT NULL,
            body_full           TEXT NOT NULL,
            tags                TEXT NOT NULL DEFAULT '[]',
            reviewed_by_chris   INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_lessons_market_dir ON lessons(market, direction);
        CREATE INDEX IF NOT EXISTS idx_lessons_signal     ON lessons(signal_source);
        CREATE INDEX IF NOT EXISTS idx_lessons_type       ON lessons(lesson_type);
        CREATE INDEX IF NOT EXISTS idx_lessons_closed     ON lessons(trade_closed_at);

        -- FTS5 virtual table — indexes summary, body_full, and tags for
        -- BM25-ranked search. content='lessons' ties it to the base table;
        -- we maintain it manually via explicit sync triggers below so the
        -- base table can have CHECK constraints without FTS5 complaining.
        CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(
            summary, body_full, tags,
            content='lessons',
            content_rowid='id',
            tokenize='porter unicode61'
        );

        -- Keep lessons_fts in sync with lessons on insert. We do NOT create
        -- update/delete triggers because the append-only trigger below blocks
        -- body_full/summary updates, and deletes are not part of the design.
        CREATE TRIGGER IF NOT EXISTS lessons_ai AFTER INSERT ON lessons BEGIN
            INSERT INTO lessons_fts(rowid, summary, body_full, tags)
            VALUES (new.id, new.summary, new.body_full, new.tags);
        END;

        -- Append-only trigger: body_full, summary, pnl_usd, roe_pct, outcome,
        -- and the identity columns are frozen at insert. Updates are only
        -- allowed for reviewed_by_chris and tags (for curation).
        CREATE TRIGGER IF NOT EXISTS lessons_append_only
            BEFORE UPDATE OF
                body_full, summary, pnl_usd, roe_pct, holding_ms,
                outcome, market, direction, signal_source, lesson_type,
                trade_closed_at, created_at, journal_entry_id,
                thesis_snapshot_path, conviction_at_open
            ON lessons
        BEGIN
            SELECT RAISE(ABORT, 'lessons table is append-only on content columns');
        END;

        -- When tags are updated (via curation), keep FTS5 in sync.
        CREATE TRIGGER IF NOT EXISTS lessons_tags_au AFTER UPDATE OF tags ON lessons BEGIN
            INSERT INTO lessons_fts(lessons_fts, rowid, summary, body_full, tags)
            VALUES ('delete', old.id, old.summary, old.body_full, old.tags);
            INSERT INTO lessons_fts(rowid, summary, body_full, tags)
            VALUES (new.id, new.summary, new.body_full, new.tags);
        END;
    """)
    con.commit()


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def log_event(
    title: str,
    event_type: str = "observation",
    market: Optional[str] = None,
    detail: Optional[str] = None,
    tags: Optional[list] = None,
    source: Optional[str] = None,
    timestamp_ms: Optional[int] = None,
    db_path: str = _DB_PATH,
) -> int:
    """
    Log a geopolitical event, trade event, or observation to the timeline.

    event_type examples: geopolitical, trade, signal, operational, market_data
    """
    ts = timestamp_ms or int(time.time() * 1000)
    tags_str = json.dumps(tags) if tags else None
    with _conn(db_path) as con:
        cur = con.execute(
            "INSERT INTO events (timestamp_ms, market, event_type, title, detail, tags, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, market, event_type, title, detail, tags_str, source),
        )
        return cur.lastrowid


def log_account_snapshot(
    snapshot: dict,
    snapshot_filename: Optional[str] = None,
    db_path: str = _DB_PATH,
) -> int:
    """Append an account snapshot row from the daemon's account_collector.

    Dual-write: this is called from account_collector.py AFTER the JSON file
    has been written successfully. Failure here must NOT break the daemon —
    callers should wrap in try/except.

    Args:
        snapshot: the dict produced by AccountCollectorIterator._build_snapshot()
        snapshot_filename: optional filename of the matching JSON on disk
        db_path: SQLite path

    Returns:
        Inserted row id.
    """
    ts = int(snapshot.get("timestamp", int(time.time() * 1000)))
    equity_total = float(snapshot.get("total_equity", snapshot.get("account_value", 0) or 0))
    equity_xyz = float(snapshot.get("xyz_account_value", 0) or 0)
    spot_usdc = float(snapshot.get("spot_usdc", 0) or 0)
    # Native equity = total - xyz - spot. account_value got overwritten with
    # total_equity earlier in _build_snapshot, so derive native by subtraction.
    equity_native = max(0.0, equity_total - equity_xyz - spot_usdc)
    hwm = float(snapshot.get("high_water_mark", 0) or 0)
    drawdown_pct = float(snapshot.get("drawdown_pct", 0) or 0)

    # Position summary
    native_positions = snapshot.get("positions_native", []) or []
    xyz_positions = snapshot.get("positions_xyz", []) or []
    # Filter to non-zero positions; xyz wraps each in {"position": {...}}
    nonzero = []
    for p in native_positions:
        if isinstance(p, dict) and float(p.get("szi", 0)) != 0:
            nonzero.append(p)
    for wrap in xyz_positions:
        if isinstance(wrap, dict):
            inner = wrap.get("position", wrap)
            if isinstance(inner, dict) and float(inner.get("szi", 0)) != 0:
                nonzero.append(inner)
    has_positions = 1 if nonzero else 0
    position_count = len(nonzero)
    positions_json_blob = json.dumps(nonzero) if nonzero else None

    with _conn(db_path) as con:
        cur = con.execute(
            """
            INSERT INTO account_snapshots (
                timestamp_ms, snapshot_filename, equity_total, equity_native,
                equity_xyz, spot_usdc, high_water_mark, drawdown_pct,
                has_positions, position_count, positions_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts, snapshot_filename, equity_total, equity_native,
                equity_xyz, spot_usdc, hwm, drawdown_pct,
                has_positions, position_count, positions_json_blob,
            ),
        )
        return cur.lastrowid


def get_account_snapshots(
    days: int = 7,
    limit: Optional[int] = None,
    db_path: str = _DB_PATH,
) -> list[dict]:
    """Return account snapshots from the last N days, newest first."""
    cutoff = int((time.time() - days * 86400) * 1000)
    con = _conn(db_path)
    query = (
        "SELECT * FROM account_snapshots WHERE timestamp_ms >= ? "
        "ORDER BY timestamp_ms DESC"
    )
    params: list = [cutoff]
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    rows = con.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def log_learning(
    title: str,
    lesson: str,
    topic: str = "general",
    confidence: str = "medium",
    market: Optional[str] = None,
    source: Optional[str] = None,
    db_path: str = _DB_PATH,
) -> int:
    """
    Log a structured learning, indexed by topic for later retrieval.

    topic examples: geopolitical, venue_economics, risk_management, execution, operational
    """
    ts = int(time.time() * 1000)
    with _conn(db_path) as con:
        cur = con.execute(
            "INSERT INTO learnings (timestamp_ms, topic, title, lesson, confidence, source, market) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, topic, title, lesson, confidence, source, market),
        )
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_timeline(
    market: Optional[str] = None,
    days: int = 60,
    event_types: Optional[list] = None,
    db_path: str = _DB_PATH,
) -> list[dict]:
    """Return chronological event list for temporal grounding."""
    cutoff = int((time.time() - days * 86400) * 1000)
    con = _conn(db_path)
    query = "SELECT * FROM events WHERE timestamp_ms >= ?"
    params: list = [cutoff]
    if market:
        query += " AND (market = ? OR market IS NULL)"
        params.append(market)
    if event_types:
        placeholders = ",".join("?" * len(event_types))
        query += f" AND event_type IN ({placeholders})"
        params.extend(event_types)
    query += " ORDER BY timestamp_ms ASC"
    rows = con.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_learnings(
    topic: Optional[str] = None,
    market: Optional[str] = None,
    days: int = 365,
    db_path: str = _DB_PATH,
) -> list[dict]:
    """Return learnings filtered by topic and/or market."""
    cutoff = int((time.time() - days * 86400) * 1000)
    con = _conn(db_path)
    query = "SELECT * FROM learnings WHERE timestamp_ms >= ?"
    params: list = [cutoff]
    if topic:
        query += " AND topic = ?"
        params.append(topic)
    if market:
        query += " AND (market = ? OR market IS NULL)"
        params.append(market)
    query += " ORDER BY timestamp_ms DESC"
    rows = con.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def search(
    query_text: str,
    market: Optional[str] = None,
    days: int = 90,
    db_path: str = _DB_PATH,
) -> dict:
    """Full-text search across events and learnings."""
    cutoff = int((time.time() - days * 86400) * 1000)
    q = f"%{query_text.lower()}%"
    con = _conn(db_path)

    event_q = "SELECT * FROM events WHERE timestamp_ms >= ? AND (LOWER(title) LIKE ? OR LOWER(detail) LIKE ?)"
    ev_params: list = [cutoff, q, q]
    if market:
        event_q += " AND (market = ? OR market IS NULL)"
        ev_params.append(market)
    event_q += " ORDER BY timestamp_ms DESC LIMIT 20"

    learn_q = "SELECT * FROM learnings WHERE timestamp_ms >= ? AND (LOWER(title) LIKE ? OR LOWER(lesson) LIKE ?)"
    le_params: list = [cutoff, q, q]
    if market:
        learn_q += " AND (market = ? OR market IS NULL)"
        le_params.append(market)
    learn_q += " ORDER BY timestamp_ms DESC LIMIT 10"

    return {
        "events": [dict(r) for r in con.execute(event_q, ev_params).fetchall()],
        "learnings": [dict(r) for r in con.execute(learn_q, le_params).fetchall()],
    }


def get_market_context(
    market: str,
    days: int = 30,
    db_path: str = _DB_PATH,
) -> str:
    """
    Return a compact memory context string for a given market.
    Used by scheduled_check to prime the AI with accumulated knowledge.
    """
    timeline = get_timeline(market=market, days=days, db_path=db_path)
    learnings = get_learnings(market=market, days=365, db_path=db_path)

    if not timeline and not learnings:
        return ""

    lines = []

    if timeline:
        lines.append(f"## Event Timeline ({market}, last {days}d)")
        for ev in timeline:
            ts = datetime.fromtimestamp(ev["timestamp_ms"] / 1000, tz=timezone.utc)
            date_str = ts.strftime("%Y-%m-%d")
            detail = f" — {ev['detail']}" if ev.get("detail") else ""
            lines.append(f"- [{date_str}] [{ev['event_type']}] {ev['title']}{detail}")

    if learnings:
        lines.append(f"\n## Accumulated Learnings ({market})")
        for lrn in learnings[:10]:  # cap at 10 most recent
            ts = datetime.fromtimestamp(lrn["timestamp_ms"] / 1000, tz=timezone.utc)
            lines.append(
                f"- [{ts.strftime('%Y-%m-%d')}] [{lrn['topic']}] "
                f"**{lrn['title']}**: {lrn['lesson']}"
            )

    return "\n".join(lines)


def format_timeline_for_prompt(market: str, days: int = 60, db_path: str = _DB_PATH) -> str:
    """Compact timeline string suitable for injection into a prompt."""
    events = get_timeline(market=market, days=days, db_path=db_path)
    if not events:
        return f"No events logged for {market} in the last {days} days."
    lines = [f"MEMORY TIMELINE — {market} (last {days}d):"]
    for ev in events:
        ts = datetime.fromtimestamp(ev["timestamp_ms"] / 1000, tz=timezone.utc)
        lines.append(f"  {ts.strftime('%Y-%m-%d')} | {ev['event_type']:15s} | {ev['title']}")
        if ev.get("detail"):
            lines.append(f"    {ev['detail'][:120]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trade lesson helpers
# ---------------------------------------------------------------------------
#
# The `lessons` table stores verbatim trade post-mortems authored by the
# agent after every closed position. See modules/lesson_engine.py for the
# pure-computation layer (Lesson dataclass, prompt builder, response parser).
# The table is append-only on content columns — only `reviewed_by_chris` and
# `tags` may change after insert.
#
# These helpers intentionally take `dict` inputs/outputs instead of the
# Lesson dataclass to keep common/memory.py free of a circular dependency
# with modules/. Callers in modules/ and cli/daemon/ convert via
# Lesson.to_dict() / Lesson.from_dict().

def log_lesson(lesson: dict, db_path: str = _DB_PATH) -> int:
    """Insert a lesson row. Returns the assigned id.

    `lesson` must contain all NOT NULL columns. `tags` may be a list (it will
    be JSON-encoded) or a JSON string. Raises sqlite3.IntegrityError on CHECK
    constraint violations (e.g. invalid direction or outcome).
    """
    tags = lesson.get("tags", [])
    if isinstance(tags, (list, tuple)):
        tags_str = json.dumps(list(tags))
    elif isinstance(tags, str):
        tags_str = tags if tags else "[]"
    else:
        tags_str = "[]"

    with _conn(db_path) as con:
        cur = con.execute(
            """
            INSERT INTO lessons (
                created_at, trade_closed_at, market, direction, signal_source,
                lesson_type, outcome, pnl_usd, roe_pct, holding_ms,
                conviction_at_open, journal_entry_id, thesis_snapshot_path,
                summary, body_full, tags, reviewed_by_chris
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lesson["created_at"],
                lesson["trade_closed_at"],
                lesson["market"],
                lesson["direction"],
                lesson["signal_source"],
                lesson["lesson_type"],
                lesson["outcome"],
                float(lesson["pnl_usd"]),
                float(lesson["roe_pct"]),
                int(lesson["holding_ms"]),
                lesson.get("conviction_at_open"),
                lesson.get("journal_entry_id"),
                lesson.get("thesis_snapshot_path"),
                lesson["summary"],
                lesson["body_full"],
                tags_str,
                int(lesson.get("reviewed_by_chris", 0)),
            ),
        )
        return int(cur.lastrowid)


def get_lesson(lesson_id: int, db_path: str = _DB_PATH) -> Optional[dict]:
    """Return a single lesson row as a dict, or None if not found."""
    with _conn(db_path) as con:
        row = con.execute(
            "SELECT * FROM lessons WHERE id = ?", (lesson_id,)
        ).fetchone()
        return dict(row) if row else None


def search_lessons(
    query: str = "",
    market: Optional[str] = None,
    direction: Optional[str] = None,
    signal_source: Optional[str] = None,
    lesson_type: Optional[str] = None,
    outcome: Optional[str] = None,
    include_rejected: bool = False,
    limit: int = 5,
    db_path: str = _DB_PATH,
) -> list[dict]:
    """BM25-ranked lesson search.

    If `query` is empty, falls back to recency ordering (trade_closed_at DESC)
    — useful for prompt injection when there's no specific query to rank by.
    Otherwise uses FTS5 MATCH over summary/body_full/tags and ranks by BM25.

    Rejected lessons (reviewed_by_chris = -1) are excluded by default so they
    don't influence the agent's prompt. Pass include_rejected=True to get them
    back (e.g. for anti-pattern search from Telegram).

    Returns dicts with the full lesson row plus a `bm25_score` key for MATCH
    results (None for recency fallback).
    """
    with _conn(db_path) as con:
        params: list = []
        where_parts: list[str] = []

        query_stripped = (query or "").strip()
        if query_stripped:
            # FTS5 path. Use the matchinfo()-backed bm25() function.
            sql = (
                "SELECT lessons.*, bm25(lessons_fts) AS bm25_score "
                "FROM lessons_fts "
                "JOIN lessons ON lessons.id = lessons_fts.rowid "
                "WHERE lessons_fts MATCH ?"
            )
            params.append(_fts5_escape_query(query_stripped))
        else:
            # Recency path.
            sql = "SELECT lessons.*, NULL AS bm25_score FROM lessons WHERE 1=1"

        if market is not None:
            where_parts.append("lessons.market = ?")
            params.append(market)
        if direction is not None:
            where_parts.append("lessons.direction = ?")
            params.append(direction)
        if signal_source is not None:
            where_parts.append("lessons.signal_source = ?")
            params.append(signal_source)
        if lesson_type is not None:
            where_parts.append("lessons.lesson_type = ?")
            params.append(lesson_type)
        if outcome is not None:
            where_parts.append("lessons.outcome = ?")
            params.append(outcome)
        if not include_rejected:
            where_parts.append("lessons.reviewed_by_chris >= 0")

        if where_parts:
            sql += " AND " + " AND ".join(where_parts)

        # BM25 is negative in SQLite's bm25() — lower = more relevant. Order
        # ascending for MATCH, descending for recency fallback.
        if query_stripped:
            sql += " ORDER BY bm25_score ASC"
        else:
            sql += " ORDER BY lessons.trade_closed_at DESC"

        sql += " LIMIT ?"
        params.append(int(limit))

        rows = con.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def set_lesson_review(
    lesson_id: int,
    status: int,
    db_path: str = _DB_PATH,
) -> bool:
    """Set reviewed_by_chris for a lesson. status must be -1, 0, or 1.

    Returns True if a row was updated, False if the id was not found.
    Note: the append-only trigger does NOT block updates to reviewed_by_chris
    (it only covers content columns).
    """
    if status not in (-1, 0, 1):
        raise ValueError(f"status must be -1, 0, or 1, got {status!r}")
    with _conn(db_path) as con:
        cur = con.execute(
            "UPDATE lessons SET reviewed_by_chris = ? WHERE id = ?",
            (status, lesson_id),
        )
        return cur.rowcount > 0


def _fts5_escape_query(query: str) -> str:
    """Escape an FTS5 MATCH query so user input can't inject FTS operators.

    FTS5 interprets characters like `"`, `*`, `(`, `)`, `:`, `AND`, `OR`, `NOT`
    as query operators. For retrieval from user/agent text we want a simple
    keyword search: wrap each word in double quotes (which FTS5 treats as a
    phrase) and join with implicit AND (space). Double-quotes inside a word
    are doubled per FTS5 quoting rules.
    """
    words = [w for w in re.split(r"\s+", query.strip()) if w]
    quoted = []
    for w in words:
        escaped = w.replace('"', '""')
        quoted.append(f'"{escaped}"')
    return " ".join(quoted) if quoted else '""'
