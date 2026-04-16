"""Heartbeat working state — persistence and ATR computation."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("heartbeat.state")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = str(PROJECT_ROOT / "data" / "memory" / "working_state.json")


# ── WorkingState dataclass ─────────────────────────────────────────────────────

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
    last_prices: dict = field(default_factory=dict)
    last_add_ms: dict = field(default_factory=dict)
    last_status_summary_ms: int = 0
    consolidators: dict = field(default_factory=dict)  # market → consolidation state
    last_funding_hour: int = 0

    # Conviction engine tracking
    last_thesis_load_ms: int = 0
    conviction_at_last_action: dict = field(default_factory=dict)   # market → conviction
    position_target_cache: dict = field(default_factory=dict)       # market → target notional

    def maybe_reset_peak(self, today_str: str, current_equity: float) -> None:
        """Reset peak if date changed; update peak if new high."""
        if self.session_peak_reset_date != today_str:
            self.session_peak_equity = current_equity
            self.session_peak_reset_date = today_str
        elif current_equity > self.session_peak_equity:
            self.session_peak_equity = current_equity


# ── Load / Save ────────────────────────────────────────────────────────────────

def load_working_state(path: str = DEFAULT_STATE_PATH) -> WorkingState:
    """Load WorkingState from JSON, returning a fresh default if missing or corrupt."""
    try:
        with open(path) as f:
            data = json.load(f)
        return WorkingState(**{
            k: v for k, v in data.items()
            if k in WorkingState.__dataclass_fields__
        })
    except (FileNotFoundError, json.JSONDecodeError, TypeError) as exc:
        if not isinstance(exc, FileNotFoundError):
            log.warning("Corrupt working state at %s, returning default: %s", path, exc)
        return WorkingState()


def save_working_state(state: WorkingState, path: str = DEFAULT_STATE_PATH) -> None:
    """Atomically write WorkingState to JSON (write .tmp then rename).

    H7 hardening: also writes a best-effort ``{path}.bak`` copy in the same
    directory so a single corrupt or deleted primary file is recoverable.
    The backup write is atomic (.bak.tmp → rename) and wrapped in try/except
    so a backup failure cannot break the primary write. Closes the SPOF
    flagged in the data-stores.md verification ledger (no dual-write backup
    → working state loss = heartbeat escalation level lost).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(asdict(state), indent=2)

    # Primary write — atomic via .tmp + rename
    tmp_path = str(p) + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(serialized)
    os.replace(tmp_path, str(p))

    # H7 — best-effort .bak dual-write in the same directory
    try:
        bak_path = str(p) + ".bak"
        bak_tmp = str(p) + ".bak.tmp"
        with open(bak_tmp, "w") as f:
            f.write(serialized)
        os.replace(bak_tmp, bak_path)
    except Exception as e:
        log.warning("WorkingState backup write failed (%s): %s", bak_path if 'bak_path' in dir() else path, e)


# ── ATR computation ────────────────────────────────────────────────────────────

def compute_atr(candles: list[dict], period: int = 14) -> Optional[float]:
    """Compute ATR from HL API candles (string-valued h/l/c fields).

    Returns None if fewer than 2 candles are provided.
    """
    if len(candles) < 2:
        return None

    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        high = float(candles[i]["h"])
        low = float(candles[i]["l"])
        prev_close = float(candles[i - 1]["c"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if not true_ranges:
        return None

    # Simple moving average of last `period` true ranges
    window = true_ranges[-period:]
    return sum(window) / len(window)
