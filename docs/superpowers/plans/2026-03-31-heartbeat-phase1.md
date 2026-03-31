# Heartbeat Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single Python script that runs every 2 minutes via launchd, audits all open HyperLiquid positions (oil + BTC), adds missing stops, takes profit on spikes, detects stop-hunts, monitors liquidation distance, and reports everything to Telegram.

**Architecture:** One heartbeat process (`run_heartbeat.py`) reads HL API state, applies rules from config files, takes protective actions via HL Exchange API, and sends alerts via Telegram Bot API. Stateless between runs except for `working_state.json` (previous prices, session peak, ATR cache, escalation state). No AI dependency. No daemon dependency.

**Tech Stack:** Python 3.13, hyperliquid-python-sdk, requests (Telegram), SQLite (memory.db), pytest

**Spec:** `docs/superpowers/specs/2026-03-31-memory-system-design.md`

---

## File Structure

```
agent-cli/
├── common/
│   ├── memory.py              # MODIFY — add 3 new tables to _init()
│   ├── heartbeat.py           # CREATE — core heartbeat logic (position audit, escalation, spike/dip)
│   ├── heartbeat_config.py    # CREATE — config loading with hardcoded defaults
│   └── memory_telegram.py     # CREATE — direct Telegram Bot API wrapper
├── cli/
│   ├── main.py                # MODIFY — register `hl heartbeat` command
│   ├── mcp_server.py          # MODIFY — add memory_health() tool
│   └── commands/
│       └── heartbeat_cmd.py   # CREATE — `hl heartbeat run/status/health` CLI
├── scripts/
│   └── run_heartbeat.py       # CREATE — launchd entry point with PID enforcement
├── plists/
│   └── com.hyperliquid.heartbeat.plist  # CREATE — launchd plist
├── data/
│   ├── config/
│   │   ├── profit_rules.json      # CREATE — per-market profit-taking rules
│   │   ├── escalation_config.json # CREATE — escalation thresholds
│   │   └── market_config.json     # CREATE — canonical ID → API mapping
│   └── memory/
│       ├── pids/                   # Created at runtime
│       └── logs/                   # Created at runtime
└── tests/
    ├── test_heartbeat.py          # CREATE — unit tests for heartbeat logic
    ├── test_heartbeat_config.py   # CREATE — config loading tests
    └── test_memory_telegram.py    # CREATE — Telegram wrapper tests
```

---

### Task 1: Telegram Reporter

**Files:**
- Create: `common/memory_telegram.py`
- Test: `tests/test_memory_telegram.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_memory_telegram.py
"""Tests for direct Telegram Bot API wrapper."""
import json
from unittest.mock import patch, MagicMock
from common.memory_telegram import send_telegram, format_position_summary


def test_send_telegram_success():
    """send_telegram posts correct JSON to Telegram API."""
    with patch("common.memory_telegram.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        result = send_telegram("Test message", bot_token="FAKE", chat_id="123")
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert body["chat_id"] == "123"
        assert body["text"] == "Test message"
        assert body["parse_mode"] == "Markdown"


def test_send_telegram_failure_returns_false():
    """send_telegram returns False on HTTP error, doesn't raise."""
    with patch("common.memory_telegram.requests.post") as mock_post:
        mock_post.side_effect = Exception("Connection refused")
        result = send_telegram("Test", bot_token="FAKE", chat_id="123")
        assert result is False


def test_send_telegram_long_message_splits():
    """Messages over 4096 chars are split into multiple sends."""
    long_msg = "x" * 5000
    with patch("common.memory_telegram.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        result = send_telegram(long_msg, bot_token="FAKE", chat_id="123")
        assert result is True
        assert mock_post.call_count == 2


def test_format_position_summary():
    """format_position_summary produces readable markdown."""
    positions = {
        "xyz:BRENTOIL": {"size": 20, "side": "long", "entry": 107.65, "mark": 108.10, "upnl": 8500, "leverage": 10, "liq_distance_pct": 7.7},
    }
    text = format_position_summary(positions)
    assert "BRENTOIL" in text
    assert "20" in text
    assert "107.65" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/test_memory_telegram.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'common.memory_telegram'`

- [ ] **Step 3: Implement Telegram wrapper**

```python
# common/memory_telegram.py
"""Direct Telegram Bot API wrapper. No AI dependency."""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

log = logging.getLogger("heartbeat.telegram")

TELEGRAM_MAX_LENGTH = 4096


def send_telegram(
    message: str,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> bool:
    """Send a message via Telegram Bot API.

    Returns True on success, False on failure. Never raises.
    """
    bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "5219304680")

    if not bot_token:
        log.warning("TELEGRAM_BOT_TOKEN not set, skipping send")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        # Split long messages
        chunks = _split_message(message, TELEGRAM_MAX_LENGTH)
        for chunk in chunks:
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                timeout=10,
            )
            if resp.status_code != 200:
                log.warning("Telegram API error %s: %s", resp.status_code, resp.text[:200])
                return False
        return True
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
        return False


def _split_message(text: str, max_len: int) -> list[str]:
    """Split text into chunks at newline boundaries."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find last newline before limit
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def format_position_summary(positions: dict) -> str:
    """Format positions dict into Telegram-friendly markdown."""
    if not positions:
        return "No open positions."
    lines = ["*Open Positions:*"]
    for market, pos in positions.items():
        side = pos.get("side", "?").upper()
        size = pos.get("size", 0)
        entry = pos.get("entry", 0)
        mark = pos.get("mark", 0)
        upnl = pos.get("upnl", 0)
        leverage = pos.get("leverage", 1)
        liq_dist = pos.get("liq_distance_pct", 0)
        pnl_sign = "+" if upnl >= 0 else ""
        lines.append(
            f"*{market}*: {size} {side} @ `{entry:.2f}`"
            f" | mark `{mark:.2f}` | PnL {pnl_sign}`{upnl:.0f}`"
            f" | {leverage}x | liq {liq_dist:.1f}%"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/test_memory_telegram.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add common/memory_telegram.py tests/test_memory_telegram.py
git commit -m "feat: add direct Telegram Bot API wrapper for heartbeat alerts"
```

---

### Task 2: Config Loading

**Files:**
- Create: `common/heartbeat_config.py`
- Create: `data/config/profit_rules.json`
- Create: `data/config/escalation_config.json`
- Create: `data/config/market_config.json`
- Test: `tests/test_heartbeat_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_heartbeat_config.py
"""Tests for heartbeat config loading with hardcoded defaults."""
import json
import tempfile
import os
from pathlib import Path
from common.heartbeat_config import HeartbeatConfig, load_config


def test_load_config_defaults_when_no_files():
    """Config loads with sensible defaults when no config files exist."""
    cfg = load_config(config_dir="/tmp/nonexistent_hb_config_dir")
    assert cfg.escalation.liq_L1_alert_pct == 10
    assert cfg.escalation.liq_L2_deleverage_pct == 8
    assert cfg.escalation.liq_L3_emergency_pct == 5
    assert cfg.escalation.drawdown_L1_pct == 5
    assert cfg.escalation.drawdown_L2_pct == 8
    assert cfg.escalation.drawdown_L3_pct == 12


def test_load_config_from_files():
    """Config loads from JSON files and overrides defaults."""
    with tempfile.TemporaryDirectory() as d:
        esc = {"liq_distance": {"L1_alert_pct": 15}}
        Path(d, "escalation_config.json").write_text(json.dumps(esc))
        cfg = load_config(config_dir=d)
        assert cfg.escalation.liq_L1_alert_pct == 15
        # Other fields still have defaults
        assert cfg.escalation.liq_L2_deleverage_pct == 8


def test_market_config_defaults():
    """Market config has correct API mappings for known markets."""
    cfg = load_config(config_dir="/tmp/nonexistent_hb_config_dir")
    oil = cfg.get_market("xyz:BRENTOIL")
    assert oil.hl_coin == "BRENTOIL"
    assert oil.dex == "xyz"
    btc = cfg.get_market("BTC-PERP")
    assert btc.hl_coin == "BTC"
    assert btc.dex is None


def test_profit_rules_defaults():
    """Profit rules have sensible defaults per market."""
    cfg = load_config(config_dir="/tmp/nonexistent_hb_config_dir")
    oil_rules = cfg.get_profit_rules("xyz:BRENTOIL")
    assert oil_rules.quick_profit_pct == 5.0
    assert oil_rules.quick_profit_take_pct == 25


def test_atr_config():
    """ATR config uses 4h candles, 14-period, 1h cache."""
    cfg = load_config(config_dir="/tmp/nonexistent_hb_config_dir")
    assert cfg.atr_interval == "4h"
    assert cfg.atr_period == 14
    assert cfg.atr_cache_seconds == 3600
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/test_heartbeat_config.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement config module**

```python
# common/heartbeat_config.py
"""Heartbeat configuration with hardcoded defaults and optional JSON overrides."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("heartbeat.config")


@dataclass
class EscalationConfig:
    liq_L1_alert_pct: float = 10
    liq_L2_deleverage_pct: float = 8
    liq_L2_deleverage_amount: float = 1  # reduce leverage by this many x
    liq_L3_emergency_pct: float = 5
    liq_L3_target_leverage: float = 3
    liq_L2_cooldown_min: int = 30
    liq_L3_cooldown_min: int = 60
    drawdown_L1_pct: float = 5
    drawdown_L2_pct: float = 8
    drawdown_L2_cut_size_pct: float = 25
    drawdown_L3_pct: float = 12
    drawdown_L3_cut_size_pct: float = 50


@dataclass
class ProfitRules:
    quick_profit_pct: float = 5.0
    quick_profit_window_min: int = 30
    quick_profit_take_pct: float = 25
    extended_profit_pct: float = 10.0
    extended_profit_window_min: int = 120
    extended_profit_take_pct: float = 25


@dataclass
class SpikeConfig:
    spike_profit_threshold_pct: float = 3.0
    spike_window_min: int = 10
    spike_take_pct: float = 15
    dip_threshold_pct: float = 2.0
    dip_add_pct: float = 10  # % of current position to add
    dip_add_min_liq_pct: float = 12  # min liq distance to allow add
    dip_add_max_drawdown_pct: float = 3
    dip_add_cooldown_min: int = 120  # max one add per 2h


@dataclass
class MarketMapping:
    canonical_id: str
    hl_coin: str
    dex: Optional[str] = None
    wallet_address: Optional[str] = None


@dataclass
class HeartbeatConfig:
    escalation: EscalationConfig = field(default_factory=EscalationConfig)
    profit_rules: dict[str, ProfitRules] = field(default_factory=dict)
    spike_config: SpikeConfig = field(default_factory=SpikeConfig)
    markets: dict[str, MarketMapping] = field(default_factory=dict)
    atr_interval: str = "4h"
    atr_period: int = 14
    atr_cache_seconds: int = 3600

    def get_market(self, canonical_id: str) -> MarketMapping:
        return self.markets.get(canonical_id, MarketMapping(canonical_id, canonical_id.split(":")[-1] if ":" in canonical_id else canonical_id))

    def get_profit_rules(self, canonical_id: str) -> ProfitRules:
        return self.profit_rules.get(canonical_id, ProfitRules())


_DEFAULT_MARKETS = {
    "xyz:BRENTOIL": MarketMapping("xyz:BRENTOIL", "BRENTOIL", dex="xyz"),
    "BTC-PERP": MarketMapping("BTC-PERP", "BTC", dex=None),
}

_DEFAULT_PROFIT_RULES = {
    "xyz:BRENTOIL": ProfitRules(quick_profit_pct=5.0, quick_profit_window_min=30, quick_profit_take_pct=25, extended_profit_pct=10.0, extended_profit_window_min=120, extended_profit_take_pct=25),
    "BTC-PERP": ProfitRules(quick_profit_pct=8.0, quick_profit_window_min=60, quick_profit_take_pct=20, extended_profit_pct=15.0, extended_profit_window_min=240, extended_profit_take_pct=25),
}


def load_config(config_dir: Optional[str] = None) -> HeartbeatConfig:
    """Load config from JSON files, falling back to hardcoded defaults."""
    if config_dir is None:
        config_dir = str(Path(__file__).resolve().parent.parent / "data" / "config")

    cfg = HeartbeatConfig(
        markets=dict(_DEFAULT_MARKETS),
        profit_rules=dict(_DEFAULT_PROFIT_RULES),
    )

    config_path = Path(config_dir)

    # Escalation overrides
    esc_file = config_path / "escalation_config.json"
    if esc_file.exists():
        try:
            data = json.loads(esc_file.read_text())
            ld = data.get("liq_distance", {})
            dd = data.get("drawdown", {})
            for k, v in ld.items():
                attr = f"liq_{k}" if not k.startswith("liq_") else k
                if hasattr(cfg.escalation, attr):
                    setattr(cfg.escalation, attr, v)
            for k, v in dd.items():
                attr = f"drawdown_{k}" if not k.startswith("drawdown_") else k
                if hasattr(cfg.escalation, attr):
                    setattr(cfg.escalation, attr, v)
        except Exception as e:
            log.warning("Failed to load escalation config: %s", e)

    # Profit rules overrides
    profit_file = config_path / "profit_rules.json"
    if profit_file.exists():
        try:
            data = json.loads(profit_file.read_text())
            for market, rules in data.items():
                cfg.profit_rules[market] = ProfitRules(**rules)
        except Exception as e:
            log.warning("Failed to load profit rules: %s", e)

    # Market config overrides
    market_file = config_path / "market_config.json"
    if market_file.exists():
        try:
            data = json.loads(market_file.read_text())
            for market, mapping in data.items():
                cfg.markets[market] = MarketMapping(**mapping)
        except Exception as e:
            log.warning("Failed to load market config: %s", e)

    return cfg
```

- [ ] **Step 4: Create default config JSON files**

```bash
mkdir -p /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/config
```

Write `data/config/market_config.json`:
```json
{
    "xyz:BRENTOIL": {
        "canonical_id": "xyz:BRENTOIL",
        "hl_coin": "BRENTOIL",
        "dex": "xyz"
    },
    "BTC-PERP": {
        "canonical_id": "BTC-PERP",
        "hl_coin": "BTC",
        "dex": null
    }
}
```

Write `data/config/escalation_config.json` and `data/config/profit_rules.json` matching the spec defaults.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/test_heartbeat_config.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add common/heartbeat_config.py tests/test_heartbeat_config.py data/config/
git commit -m "feat: add heartbeat config loading with hardcoded defaults + JSON overrides"
```

---

### Task 3: Memory Schema Extension

**Files:**
- Modify: `common/memory.py` — add 3 new tables to `_init()`
- Test: `tests/test_heartbeat.py` (first batch — schema only)

- [ ] **Step 1: Write failing test**

```python
# tests/test_heartbeat.py (initial — schema test only, more added in later tasks)
"""Tests for heartbeat system."""
import sqlite3
import tempfile
import os
from common.memory import _conn


def test_new_tables_created():
    """Memory DB creates observations, action_log, execution_traces tables."""
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "test.db")
        con = _conn(db_path)
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "observations" in tables
        assert "action_log" in tables
        assert "execution_traces" in tables
        # Old tables still exist
        assert "events" in tables
        assert "learnings" in tables
        con.close()


def test_observations_insert_and_query():
    """Can insert and query observations with temporal validity."""
    import time
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "test.db")
        con = _conn(db_path)
        now = int(time.time() * 1000)
        con.execute(
            "INSERT INTO observations (created_at, valid_from, market, category, priority, title, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, now, "xyz:BRENTOIL", "metric", 1, "test obs", "programmatic"),
        )
        con.commit()
        rows = con.execute("SELECT * FROM observations WHERE market = ?", ("xyz:BRENTOIL",)).fetchall()
        assert len(rows) == 1
        assert rows[0]["title"] == "test obs"
        assert rows[0]["valid_until"] is None  # still active
        con.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/test_heartbeat.py::test_new_tables_created -v`
Expected: FAIL — `observations` table doesn't exist

- [ ] **Step 3: Add new tables to `_init()` in `common/memory.py`**

Add after the existing `CREATE TABLE IF NOT EXISTS summaries` block, before the `con.commit()`:

```sql
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/test_heartbeat.py -v`
Expected: 2 passed

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/ -x --timeout=30 -q 2>&1 | tail -20`
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add common/memory.py tests/test_heartbeat.py
git commit -m "feat: add observations, action_log, execution_traces tables to memory DB"
```

---

### Task 4: Working State + ATR Cache

**Files:**
- Create: `common/heartbeat_state.py` — working state read/write + ATR computation
- Test: `tests/test_heartbeat_state.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_heartbeat_state.py
"""Tests for heartbeat working state and ATR computation."""
import json
import tempfile
import time
import os
from pathlib import Path
from common.heartbeat_state import (
    WorkingState, load_working_state, save_working_state, compute_atr,
)


def test_save_and_load_working_state():
    """Working state round-trips through JSON."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "working_state.json")
        state = WorkingState(last_updated_ms=1000, session_peak_equity=50000)
        save_working_state(state, path)
        loaded = load_working_state(path)
        assert loaded.last_updated_ms == 1000
        assert loaded.session_peak_equity == 50000


def test_load_working_state_missing_file():
    """Returns fresh default state when file doesn't exist."""
    state = load_working_state("/tmp/nonexistent_ws.json")
    assert state.last_updated_ms == 0
    assert state.session_peak_equity == 0
    assert state.escalation_level == "L0"


def test_save_working_state_atomic():
    """Save writes to .tmp then renames (no partial writes)."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "working_state.json")
        state = WorkingState(last_updated_ms=1000)
        save_working_state(state, path)
        # File exists and is valid JSON
        data = json.loads(Path(path).read_text())
        assert data["last_updated_ms"] == 1000
        # No .tmp file left behind
        assert not os.path.exists(path + ".tmp")


def test_compute_atr_from_candles():
    """ATR computed correctly from OHLC candles."""
    candles = [
        {"h": "110", "l": "100", "c": "105"},  # TR = 10
        {"h": "112", "l": "102", "c": "108"},  # TR = max(10, |112-105|, |102-105|) = 10
        {"h": "115", "l": "104", "c": "110"},  # TR = max(11, |115-108|, |104-108|) = 11
    ]
    atr = compute_atr(candles, period=3)
    assert atr > 0
    assert isinstance(atr, float)


def test_compute_atr_empty_candles():
    """ATR returns None for insufficient data."""
    atr = compute_atr([], period=14)
    assert atr is None


def test_session_peak_resets_daily():
    """Session peak resets when date changes."""
    state = WorkingState(
        last_updated_ms=1000,
        session_peak_equity=80000,
        session_peak_reset_date="2026-03-30",
    )
    # Simulate new day
    state.maybe_reset_peak("2026-03-31", current_equity=75000)
    assert state.session_peak_equity == 75000
    assert state.session_peak_reset_date == "2026-03-31"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/test_heartbeat_state.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement working state module**

```python
# common/heartbeat_state.py
"""Working state persistence and ATR computation for heartbeat."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("heartbeat.state")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = str(PROJECT_ROOT / "data" / "memory" / "working_state.json")


@dataclass
class WorkingState:
    last_updated_ms: int = 0
    session_peak_equity: float = 0
    session_peak_reset_date: str = ""
    positions: dict = field(default_factory=dict)
    escalation_level: str = "L0"
    last_l2_ms: Optional[int] = None
    last_l3_ms: Optional[int] = None
    last_ai_checkin_ms: Optional[int] = None
    heartbeat_consecutive_failures: int = 0
    atr_cache: dict = field(default_factory=dict)
    last_prices: dict = field(default_factory=dict)  # for spike/dip detection
    last_add_ms: dict = field(default_factory=dict)  # cooldown tracking per market

    def maybe_reset_peak(self, today_str: str, current_equity: float):
        """Reset session peak if date changed."""
        if self.session_peak_reset_date != today_str:
            self.session_peak_equity = current_equity
            self.session_peak_reset_date = today_str
        elif current_equity > self.session_peak_equity:
            self.session_peak_equity = current_equity


def load_working_state(path: str = DEFAULT_STATE_PATH) -> WorkingState:
    """Load working state from JSON. Returns default if missing/corrupt."""
    try:
        data = json.loads(Path(path).read_text())
        return WorkingState(**{k: v for k, v in data.items() if k in WorkingState.__dataclass_fields__})
    except (FileNotFoundError, json.JSONDecodeError, TypeError) as e:
        log.debug("Working state not found or corrupt (%s), using defaults", e)
        return WorkingState()


def save_working_state(state: WorkingState, path: str = DEFAULT_STATE_PATH):
    """Save working state atomically (write .tmp then rename)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path + ".tmp"
    try:
        Path(tmp_path).write_text(json.dumps(asdict(state), indent=2, default=str))
        os.rename(tmp_path, path)
    except Exception as e:
        log.error("Failed to save working state: %s", e)
        # Clean up tmp file if rename failed
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def compute_atr(candles: list[dict], period: int = 14) -> Optional[float]:
    """Compute Average True Range from OHLC candle dicts.

    Candle format: {"h": "110", "l": "100", "c": "105", ...}
    Returns None if insufficient data.
    """
    if len(candles) < 2:
        return None

    true_ranges = []
    for i in range(1, len(candles)):
        high = float(candles[i]["h"])
        low = float(candles[i]["l"])
        prev_close = float(candles[i - 1]["c"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        # Use what we have
        return sum(true_ranges) / len(true_ranges) if true_ranges else None

    # Simple moving average of last `period` TRs
    return sum(true_ranges[-period:]) / period
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/test_heartbeat_state.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add common/heartbeat_state.py tests/test_heartbeat_state.py
git commit -m "feat: add heartbeat working state persistence and ATR computation"
```

---

### Task 5: Core Heartbeat Logic — Position Auditor

**Files:**
- Create: `common/heartbeat.py` — the main heartbeat runner
- Test: `tests/test_heartbeat.py` (extend with auditor tests)

This is the largest task. The heartbeat reads positions, checks stops, monitors liq distance, handles escalation, detects spikes/dips, and reports to Telegram.

- [ ] **Step 1: Write failing tests for position auditor**

Add to `tests/test_heartbeat.py`:

```python
"""Tests for core heartbeat logic."""
from unittest.mock import MagicMock, patch
from common.heartbeat import (
    audit_position, check_stop_exists, compute_stop_price,
    check_liq_distance, check_drawdown, detect_spike_or_dip,
)
from common.heartbeat_config import HeartbeatConfig, load_config
from common.heartbeat_state import WorkingState


def _mock_position(size=20, side="long", entry=107.65, mark=108.10, leverage=10, liq_price=99.36):
    return {
        "size": size, "side": side, "entry": entry, "mark": mark,
        "leverage": leverage, "liq_price": liq_price,
        "liq_distance_pct": round((mark - liq_price) / mark * 100, 1) if side == "long" else round((liq_price - mark) / mark * 100, 1),
    }


def test_compute_stop_price_long():
    """Stop placed 3x ATR below entry for longs."""
    stop = compute_stop_price(entry=107.65, side="long", atr=1.85, multiplier=3.0)
    expected = 107.65 - (3.0 * 1.85)  # 102.10
    assert abs(stop - expected) < 0.01


def test_compute_stop_price_respects_min_distance():
    """Stop never placed within 2% of current price."""
    stop = compute_stop_price(entry=107.65, side="long", atr=0.5, multiplier=3.0, current_price=107.50, min_distance_pct=2.0)
    min_stop = 107.50 * 0.98  # 105.35
    assert stop <= min_stop


def test_compute_stop_price_respects_liq_buffer():
    """Stop never placed tighter than liq price + 3%."""
    stop = compute_stop_price(entry=107.65, side="long", atr=5.0, multiplier=3.0, liq_price=100.0, liq_buffer_pct=3.0)
    min_stop = 100.0 * 1.03  # 103.0
    assert stop >= min_stop


def test_check_liq_distance_l0():
    """No escalation when liq distance is healthy."""
    level = check_liq_distance(liq_distance_pct=15.0, config=load_config(config_dir="/tmp/nonexistent"))
    assert level == "L0"


def test_check_liq_distance_l1():
    """L1 alert when liq distance < 10%."""
    level = check_liq_distance(liq_distance_pct=9.5, config=load_config(config_dir="/tmp/nonexistent"))
    assert level == "L1"


def test_check_liq_distance_l2():
    """L2 deleverage when liq distance < 8%."""
    level = check_liq_distance(liq_distance_pct=7.5, config=load_config(config_dir="/tmp/nonexistent"))
    assert level == "L2"


def test_check_liq_distance_l3():
    """L3 emergency when liq distance < 5%."""
    level = check_liq_distance(liq_distance_pct=4.8, config=load_config(config_dir="/tmp/nonexistent"))
    assert level == "L3"


def test_check_drawdown():
    """Drawdown computed from session peak."""
    level = check_drawdown(current_equity=47500, session_peak=50000, config=load_config(config_dir="/tmp/nonexistent"))
    assert level == "L1"  # 5% drawdown = L1


def test_detect_spike_long():
    """Spike detected when price moves >3% in favor of long position."""
    result = detect_spike_or_dip(
        current_price=111.0, last_price=107.0, side="long",
        spike_threshold_pct=3.0, dip_threshold_pct=2.0,
    )
    assert result["type"] == "spike"
    assert result["pct"] > 3.0


def test_detect_dip_long():
    """Dip detected when price drops >2% against long position."""
    result = detect_spike_or_dip(
        current_price=104.8, last_price=107.0, side="long",
        spike_threshold_pct=3.0, dip_threshold_pct=2.0,
    )
    assert result["type"] == "dip"


def test_detect_no_movement():
    """No detection on small price moves."""
    result = detect_spike_or_dip(
        current_price=107.5, last_price=107.0, side="long",
        spike_threshold_pct=3.0, dip_threshold_pct=2.0,
    )
    assert result["type"] == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/test_heartbeat.py -v -k "not test_new_tables and not test_observations"`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement core heartbeat logic**

Create `common/heartbeat.py` with the following functions:
- `compute_stop_price(entry, side, atr, multiplier, current_price, min_distance_pct, liq_price, liq_buffer_pct)` → float
- `check_liq_distance(liq_distance_pct, config)` → str (L0/L1/L2/L3)
- `check_drawdown(current_equity, session_peak, config)` → str (L0/L1/L2/L3)
- `detect_spike_or_dip(current_price, last_price, side, spike_threshold_pct, dip_threshold_pct)` → dict
- `audit_position(market, position, state, config, proxy)` → list of actions taken
- `run_heartbeat(config, proxy, state_path)` → the main entry point

**Implementation note:** `run_heartbeat()` is the top-level function called by `scripts/run_heartbeat.py`. It: loads state → fetches positions → for each position runs audit → saves state → returns summary. Each sub-function is pure (testable without mocks) except `audit_position` which calls the proxy for order placement.

The full implementation is ~300 lines. The developer should implement each function to pass the tests above, following the spec rules exactly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m pytest tests/test_heartbeat.py -v`
Expected: all tests pass (schema tests from Task 3 + new auditor tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add common/heartbeat.py tests/test_heartbeat.py
git commit -m "feat: add core heartbeat position auditor with stops, escalation, spike/dip detection"
```

---

### Task 6: Heartbeat Runner Script + PID Enforcement

**Files:**
- Create: `scripts/run_heartbeat.py`
- Create: `plists/com.hyperliquid.heartbeat.plist`

- [ ] **Step 1: Create the runner script**

```python
#!/usr/bin/env python3
"""Heartbeat runner — launchd entry point with PID enforcement.

Runs every 2 minutes. Checks positions, adds stops, monitors risk, reports to Telegram.
"""
from __future__ import annotations

import atexit
import logging
import os
import sys
import time
from pathlib import Path

# Project root resolution (scripts/ → agent-cli/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PID_DIR = PROJECT_ROOT / "data" / "memory" / "pids"
PID_FILE = PID_DIR / "heartbeat.pid"
LOG_DIR = PROJECT_ROOT / "data" / "memory" / "logs"
LOG_FILE = LOG_DIR / "heartbeat.log"
MAX_LOG_SIZE = 1_000_000  # 1MB


def _check_pid() -> bool:
    """Return True if another instance is running."""
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)  # Check if alive
        return True  # Process is running
    except (ProcessLookupError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it


def _write_pid():
    PID_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def _cleanup_pid():
    PID_FILE.unlink(missing_ok=True)


def _setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Rotate if too large
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_SIZE:
        old = LOG_FILE.with_suffix(".log.old")
        LOG_FILE.rename(old)
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Also log to stderr (captured by launchd)
    logging.getLogger().addHandler(logging.StreamHandler())


def main():
    if _check_pid():
        return  # Another instance running, exit silently

    _write_pid()
    atexit.register(_cleanup_pid)
    _setup_logging()

    log = logging.getLogger("heartbeat.runner")
    start = time.time()

    try:
        from common.heartbeat_config import load_config
        from common.heartbeat_state import load_working_state, save_working_state
        from common.heartbeat import run_heartbeat

        config = load_config()
        result = run_heartbeat(config)

        elapsed = int((time.time() - start) * 1000)
        log.info("Heartbeat completed in %dms: %s", elapsed, result.get("summary", "ok"))

    except Exception as e:
        log.error("Heartbeat failed: %s", e, exc_info=True)
        # Try to send Telegram alert about the failure
        try:
            from common.memory_telegram import send_telegram
            send_telegram(f"🔴 Heartbeat crashed: {e}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create the launchd plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.hyperliquid.heartbeat</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/python3</string>
        <string>/Users/cdi/Developer/HyperLiquid_Bot/agent-cli/scripts/run_heartbeat.py</string>
    </array>
    <key>StartInterval</key>
    <integer>120</integer>
    <key>WorkingDirectory</key>
    <string>/Users/cdi/Developer/HyperLiquid_Bot/agent-cli</string>
    <key>StandardOutPath</key>
    <string>/Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/memory/logs/heartbeat_launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/memory/logs/heartbeat_launchd_err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>/Users/cdi/Developer/HyperLiquid_Bot/agent-cli</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
```

- [ ] **Step 3: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add scripts/run_heartbeat.py plists/com.hyperliquid.heartbeat.plist
git commit -m "feat: add heartbeat runner script with PID enforcement and launchd plist"
```

---

### Task 7: CLI Commands

**Files:**
- Create: `cli/commands/heartbeat_cmd.py`
- Modify: `cli/main.py` — register heartbeat subcommand

- [ ] **Step 1: Create CLI commands**

```python
# cli/commands/heartbeat_cmd.py
"""hl heartbeat — position auditor and risk monitor commands."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

heartbeat_app = typer.Typer(no_args_is_help=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@heartbeat_app.command("run")
def heartbeat_run(dry_run: bool = typer.Option(False, help="Print what would be done without executing")):
    """Run one heartbeat cycle (position audit + risk check + alerts)."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from common.heartbeat_config import load_config
    from common.heartbeat import run_heartbeat
    config = load_config()
    result = run_heartbeat(config, dry_run=dry_run)
    typer.echo(json.dumps(result, indent=2, default=str))


@heartbeat_app.command("status")
def heartbeat_status():
    """Show current working state (positions, escalation, last prices)."""
    from common.heartbeat_state import load_working_state
    state = load_working_state()
    typer.echo(json.dumps(state.__dict__, indent=2, default=str))


@heartbeat_app.command("health")
def heartbeat_health():
    """Check heartbeat system health (GREEN/YELLOW/RED)."""
    import time
    from common.heartbeat_state import load_working_state
    state = load_working_state()
    now_ms = int(time.time() * 1000)
    age_min = (now_ms - state.last_updated_ms) / 60_000 if state.last_updated_ms else float("inf")

    if age_min > 10:
        typer.echo(f"🔴 RED — working state is {age_min:.0f}min old (heartbeat may not be running)")
    elif state.escalation_level in ("L2", "L3"):
        typer.echo(f"🟡 YELLOW — escalation at {state.escalation_level}")
    elif age_min > 5:
        typer.echo(f"🟡 YELLOW — working state is {age_min:.0f}min old")
    else:
        typer.echo(f"🟢 GREEN — last update {age_min:.1f}min ago, escalation {state.escalation_level}")
```

- [ ] **Step 2: Register in `cli/main.py`**

Add import and registration:
```python
from cli.commands.heartbeat_cmd import heartbeat_app
app.add_typer(heartbeat_app, name="heartbeat", help="Heartbeat — position auditor and risk monitor")
```

- [ ] **Step 3: Test manually**

Run: `cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli && python -m cli.main heartbeat --help`
Expected: shows run, status, health commands

- [ ] **Step 4: Commit**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add cli/commands/heartbeat_cmd.py cli/main.py
git commit -m "feat: add hl heartbeat CLI commands (run, status, health)"
```

---

### Task 8: Integration Test — Dry Run Against Live API

**Files:**
- No new files — uses existing code

- [ ] **Step 1: Run heartbeat in dry-run mode**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
python -m cli.main heartbeat run --dry-run
```

Expected: prints JSON showing what positions were found, what stops would be placed, what alerts would be sent. No actual orders placed. No Telegram messages sent.

- [ ] **Step 2: Verify working state was created**

```bash
cat data/memory/working_state.json
```

Expected: valid JSON with positions, prices, escalation level.

- [ ] **Step 3: Check health**

```bash
python -m cli.main heartbeat health
```

Expected: GREEN or YELLOW with explanation.

- [ ] **Step 4: Run full test suite**

```bash
python -m pytest tests/ -x --timeout=30 -q 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Commit any fixes needed**

```bash
git add -u && git commit -m "fix: integration test fixes for heartbeat dry-run"
```

---

### Task 9: Install and Activate launchd

- [ ] **Step 1: Verify Python path in plist is correct**

```bash
which python3
# Should show /opt/homebrew/bin/python3 — update plist if different
```

- [ ] **Step 2: Verify TELEGRAM_BOT_TOKEN is available**

```bash
# Check if token is in environment or .env file
env | grep TELEGRAM
# If not set, the heartbeat will skip Telegram sends (safe default)
```

- [ ] **Step 3: Copy plist to LaunchAgents**

```bash
cp /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/plists/com.hyperliquid.heartbeat.plist ~/Library/LaunchAgents/
```

- [ ] **Step 4: Load the plist**

```bash
launchctl load ~/Library/LaunchAgents/com.hyperliquid.heartbeat.plist
```

- [ ] **Step 5: Verify it's running**

```bash
launchctl list | grep heartbeat
# Wait 2 minutes, then:
cat /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/data/memory/logs/heartbeat.log
```

- [ ] **Step 6: Verify Telegram receives a message**

Wait for first cycle to complete. Check Telegram chat for a status message.

- [ ] **Step 7: Commit final state**

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git add -A && git status
# Review what's being added — never add .env or keys!
git commit -m "feat: heartbeat Phase 1 complete — position auditor active"
```

---

## Summary

| Task | What | Files | Tests |
|------|------|-------|-------|
| 1 | Telegram reporter | `memory_telegram.py` | 4 |
| 2 | Config loading | `heartbeat_config.py` + 3 JSON | 5 |
| 3 | Memory schema | `memory.py` (modify) | 2 |
| 4 | Working state + ATR | `heartbeat_state.py` | 6 |
| 5 | Core heartbeat logic | `heartbeat.py` | 11 |
| 6 | Runner + PID + plist | `run_heartbeat.py` + plist | — |
| 7 | CLI commands | `heartbeat_cmd.py` + main.py | manual |
| 8 | Integration dry-run | — | manual |
| 9 | launchd activation | — | manual |

---

### Task 5A: Funding Rate Monitor (extends Task 5)

**Files:**
- Modify: `common/heartbeat.py` — add `check_funding_rate()`
- Modify: `tests/test_heartbeat.py` — add funding tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_heartbeat.py`:

```python
from common.heartbeat import check_funding_rate


def test_funding_rate_normal():
    """No alert when funding is within normal range."""
    result = check_funding_rate(current_rate=0.005, recent_rates=[0.004, 0.005, 0.003], position_notional=50000)
    assert result["alert"] is False


def test_funding_rate_high_consecutive():
    """Alert when funding >0.1% for 3 consecutive periods."""
    result = check_funding_rate(current_rate=0.12, recent_rates=[0.11, 0.13, 0.12], position_notional=50000)
    assert result["alert"] is True
    assert "drag" in result["message"].lower()


def test_funding_rate_cumulative():
    """Alert when cumulative funding drag >1% of position."""
    result = check_funding_rate(current_rate=0.05, recent_rates=[0.05] * 24, position_notional=50000, cumulative_pct=1.2)
    assert result["alert"] is True
```

- [ ] **Step 2: Implement `check_funding_rate()` in `heartbeat.py`**
- [ ] **Step 3: Run tests, verify pass**
- [ ] **Step 4: Commit**

---

### Task 5B: Oil Trading Hours (extends Task 5)

**Files:**
- Modify: `common/heartbeat.py` — add `is_oil_market_open()`
- Modify: `tests/test_heartbeat.py`

- [ ] **Step 1: Write failing tests**

```python
from common.heartbeat import is_oil_market_open
from datetime import datetime, timezone


def test_oil_market_open_weekday():
    """Oil market open during weekday business hours."""
    # Tuesday 10:00 ET = open
    dt = datetime(2026, 3, 31, 14, 0, tzinfo=timezone.utc)  # 10 AM ET
    assert is_oil_market_open(dt) is True


def test_oil_market_closed_saturday():
    """Oil market closed on Saturday."""
    dt = datetime(2026, 4, 4, 14, 0, tzinfo=timezone.utc)  # Saturday
    assert is_oil_market_open(dt) is False


def test_oil_market_closed_friday_late():
    """Oil market closes Friday 5PM ET."""
    dt = datetime(2026, 4, 3, 22, 0, tzinfo=timezone.utc)  # Friday 6PM ET = closed
    assert is_oil_market_open(dt) is False
```

- [ ] **Step 2: Implement and verify pass**
- [ ] **Step 3: Wire into `audit_position()`: skip stop placement when market closed for oil**
- [ ] **Step 4: Commit**

---

### Task 5C: Profit-Taking + Drawdown Escalation Tests (extends Task 5)

**Files:**
- Modify: `tests/test_heartbeat.py`

- [ ] **Step 1: Write tests for profit-taking**

```python
from common.heartbeat import should_take_profit


def test_quick_profit_triggers():
    """Take profit when position up >5% in <30min."""
    result = should_take_profit(upnl_pct=6.0, position_age_min=22, rules=ProfitRules())
    assert result["take"] is True
    assert result["take_pct"] == 25


def test_no_profit_if_too_slow():
    """Don't quick-profit if move took >30 minutes."""
    result = should_take_profit(upnl_pct=6.0, position_age_min=45, rules=ProfitRules())
    assert result["take"] is False  # Missed quick window, not yet at extended


def test_extended_profit_triggers():
    """Take extended profit when up >10% in <2h."""
    result = should_take_profit(upnl_pct=11.0, position_age_min=90, rules=ProfitRules())
    assert result["take"] is True
    assert result["take_pct"] == 25


def test_no_profit_on_small_position():
    """Skip profit-taking if would leave <2 contracts."""
    result = should_take_profit(upnl_pct=6.0, position_age_min=22, rules=ProfitRules(), current_size=2, min_size=2)
    assert result["take"] is False
```

- [ ] **Step 2: Write tests for drawdown L2/L3**

```python
def test_drawdown_l2():
    """L2 triggers at >8% drawdown."""
    level = check_drawdown(current_equity=46000, session_peak=50000, config=load_config(config_dir="/tmp/nonexistent"))
    assert level == "L2"  # 8% drawdown


def test_drawdown_l3():
    """L3 triggers at >12% drawdown."""
    level = check_drawdown(current_equity=43500, session_peak=50000, config=load_config(config_dir="/tmp/nonexistent"))
    assert level == "L3"  # 13% drawdown
```

- [ ] **Step 3: Write tests for spike/dip safety constraints**

```python
from common.heartbeat import should_add_on_dip


def test_dip_add_blocked_by_low_liq():
    """Don't add if liq distance <12%."""
    assert should_add_on_dip(liq_distance_pct=10, daily_drawdown_pct=1, last_add_ms=0, now_ms=999999999, config=SpikeConfig()) is False


def test_dip_add_blocked_by_drawdown():
    """Don't add if daily drawdown >3%."""
    assert should_add_on_dip(liq_distance_pct=15, daily_drawdown_pct=4, last_add_ms=0, now_ms=999999999, config=SpikeConfig()) is False


def test_dip_add_blocked_by_cooldown():
    """Don't add if last add was <2h ago."""
    now = 1000000
    last = now - (60 * 60 * 1000)  # 1h ago, need 2h
    assert should_add_on_dip(liq_distance_pct=15, daily_drawdown_pct=1, last_add_ms=last, now_ms=now, config=SpikeConfig()) is False


def test_escalation_highest_wins():
    """When multiple triggers fire, highest escalation level wins."""
    from common.heartbeat import resolve_escalation
    levels = ["L1", "L3", "L2"]
    assert resolve_escalation(levels) == "L3"
```

- [ ] **Step 4: Implement all functions, verify all pass**
- [ ] **Step 5: Commit**

---

### Task 5D: API Retry + Consecutive Failure Tracking (extends Task 5)

- [ ] **Step 1: Write tests**

```python
from common.heartbeat import fetch_with_retry


def test_fetch_with_retry_succeeds_first_try():
    """Successful API call on first attempt."""
    mock_fn = MagicMock(return_value={"ok": True})
    result = fetch_with_retry(mock_fn, retries=3)
    assert result == {"ok": True}
    assert mock_fn.call_count == 1


def test_fetch_with_retry_succeeds_after_failures():
    """Succeeds on third attempt after two failures."""
    mock_fn = MagicMock(side_effect=[Exception("timeout"), Exception("timeout"), {"ok": True}])
    result = fetch_with_retry(mock_fn, retries=3, delay_ms=0)
    assert result == {"ok": True}
    assert mock_fn.call_count == 3


def test_fetch_with_retry_all_fail():
    """Returns None after all retries exhausted."""
    mock_fn = MagicMock(side_effect=Exception("down"))
    result = fetch_with_retry(mock_fn, retries=3, delay_ms=0)
    assert result is None
    assert mock_fn.call_count == 3
```

- [ ] **Step 2: Implement, verify, commit**

---

### Task 6A: BTC Vault Monitor (new task)

**Files:**
- Modify: `common/heartbeat.py` — add `audit_btc_vault()`
- Modify: `tests/test_heartbeat.py`

- [ ] **Step 1: Write failing tests**

```python
from common.heartbeat import audit_btc_vault


def test_btc_trade_detected():
    """Detects when BTC vault position size changed."""
    last_position = {"size": 0.10, "side": "long"}
    current_position = {"size": 0.11, "side": "long", "entry": 68200, "mark": 68420}
    result = audit_btc_vault(current_position, last_position)
    assert result["trade_detected"] is True
    assert result["direction"] == "buy"
    assert result["delta"] == 0.01


def test_btc_no_trade():
    """No trade when position unchanged."""
    pos = {"size": 0.10, "side": "long"}
    result = audit_btc_vault(pos, pos)
    assert result["trade_detected"] is False


def test_btc_rebalance_stuck():
    """Flags when rebalance hasn't happened for >6h with high deviation."""
    result = audit_btc_vault(
        current_position={"size": 0.10, "side": "long"},
        last_position={"size": 0.10, "side": "long"},
        hours_since_last_rebalance=7,
        current_deviation_pct=25,
    )
    assert result["stuck"] is True


def test_btc_liq_gate_blocks_increase():
    """Block rebalance increase when liq distance <15%."""
    from common.heartbeat import btc_liq_gate
    assert btc_liq_gate(liq_distance_pct=12, direction="buy") is False
    assert btc_liq_gate(liq_distance_pct=12, direction="sell") is True  # reductions always allowed
    assert btc_liq_gate(liq_distance_pct=20, direction="buy") is True
```

- [ ] **Step 2: Implement `audit_btc_vault()` and `btc_liq_gate()`**
- [ ] **Step 3: Wire into `run_heartbeat()`: after oil audit, run BTC vault audit**
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

---

### Task 6B: 6-Hour Status Summary (new task)

**Files:**
- Modify: `common/heartbeat_state.py` — add `last_status_summary_ms` field
- Modify: `common/heartbeat.py` — add `maybe_send_status_summary()`

- [ ] **Step 1: Write failing tests**

```python
from common.heartbeat import should_send_status_summary


def test_status_summary_due():
    """Summary sent when >6h since last."""
    import time
    now = int(time.time() * 1000)
    last = now - (7 * 3600 * 1000)  # 7h ago
    assert should_send_status_summary(last_summary_ms=last, now_ms=now) is True


def test_status_summary_not_due():
    """No summary when <6h since last."""
    import time
    now = int(time.time() * 1000)
    last = now - (3 * 3600 * 1000)  # 3h ago
    assert should_send_status_summary(last_summary_ms=last, now_ms=now) is False


def test_status_summary_first_run():
    """Summary sent on first run (last=0)."""
    import time
    now = int(time.time() * 1000)
    assert should_send_status_summary(last_summary_ms=0, now_ms=now) is True
```

- [ ] **Step 2: Implement, verify, commit**

---

### Task 6C: TELEGRAM_BOT_TOKEN for launchd (fix)

The launchd environment does not inherit shell environment variables. The heartbeat needs the Telegram bot token.

- [ ] **Step 1: Update `run_heartbeat.py` to load token from file**

Add to the runner script, before the heartbeat runs:

```python
# Load Telegram bot token from .env file (launchd doesn't inherit shell env)
_env_file = PROJECT_ROOT.parent / ".claude" / "channels" / "telegram" / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            os.environ["TELEGRAM_BOT_TOKEN"] = line.split("=", 1)[1].strip().strip('"')
```

- [ ] **Step 2: Verify token path exists**

```bash
ls -la /Users/cdi/.claude/channels/telegram/.env
```

- [ ] **Step 3: Commit**

---

### Task 9 Fix: Use specific file adds, not `git add -A`

Replace Task 9 Step 7 with:

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
git status  # Review changes
git add common/heartbeat.py common/heartbeat_config.py common/heartbeat_state.py common/memory_telegram.py
git add common/memory.py cli/commands/heartbeat_cmd.py cli/main.py cli/mcp_server.py
git add scripts/run_heartbeat.py plists/com.hyperliquid.heartbeat.plist
git add data/config/ tests/test_heartbeat*.py tests/test_memory_telegram.py
git commit -m "feat: heartbeat Phase 1 complete — position auditor active"
```

---

## Updated Summary

| Task | What | Files | Tests |
|------|------|-------|-------|
| 1 | Telegram reporter | `memory_telegram.py` | 4 |
| 2 | Config loading | `heartbeat_config.py` + 3 JSON | 5 |
| 3 | Memory schema | `memory.py` (modify) | 2 |
| 4 | Working state + ATR | `heartbeat_state.py` | 6 |
| 5 | Core heartbeat (stops, escalation, spike/dip) | `heartbeat.py` | 11 |
| 5A | Funding rate monitor | `heartbeat.py` (extend) | 3 |
| 5B | Oil trading hours | `heartbeat.py` (extend) | 3 |
| 5C | Profit-taking + drawdown L2/L3 + safety constraints | `heartbeat.py` (extend) | 8 |
| 5D | API retry logic | `heartbeat.py` (extend) | 3 |
| 6 | Runner + PID + plist | `run_heartbeat.py` + plist | — |
| 6A | BTC vault monitor | `heartbeat.py` (extend) | 4 |
| 6B | 6-hour status summary | `heartbeat.py` (extend) | 3 |
| 6C | Telegram token for launchd | `run_heartbeat.py` (fix) | — |
| 7 | CLI commands | `heartbeat_cmd.py` + main.py | manual |
| 8 | Integration dry-run | — | manual |
| 9 | launchd activation | — | manual |

Total: ~16 tasks, ~52 automated tests, estimated 4-5 hours implementation time.
