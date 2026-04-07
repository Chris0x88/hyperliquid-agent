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
