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
    """Atomically write WorkingState to JSON (write .tmp then rename)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = str(p) + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(asdict(state), f, indent=2)
    os.replace(tmp_path, str(p))


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
