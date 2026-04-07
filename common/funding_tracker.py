"""Funding Tracker — tracks cumulative funding cost per position over time.

On HyperLiquid, funding is settled HOURLY (rate calculated on 8-hour basis).
This tracker records each hourly funding payment so the agent can answer:
"This BRENTOIL position has cost $14.30 in funding over 12 days."

This feeds into thesis re-evaluation — if cumulative funding drag exceeds
the expected alpha, the position might not be worth holding.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("funding_tracker")

DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "state"


@dataclass
class FundingRecord:
    """A single funding payment record."""
    timestamp: float
    funding_rate: float       # Hourly rate (e.g. 0.000125 = 0.0125%)
    position_notional: float  # Position size in USD at time of payment
    cost_usd: float           # Actual cost: notional × rate (negative = received)


@dataclass
class PositionFunding:
    """Cumulative funding state for a single position/symbol."""
    symbol: str
    total_paid_usd: float = 0.0       # Positive = we paid, negative = received
    total_received_usd: float = 0.0    # Convenience: abs of payments received
    hours_tracked: int = 0
    first_record_ts: float = 0.0
    last_record_ts: float = 0.0
    avg_hourly_cost_usd: float = 0.0
    annualized_cost_pct: float = 0.0   # Annual cost as % of avg notional

    # Rolling window for recent trend
    recent_records: List[FundingRecord] = field(default_factory=list)
    _max_recent: int = 72              # Keep last 72 hours (3 days)

    def record(self, funding_rate: float, position_notional: float,
               timestamp: Optional[float] = None) -> FundingRecord:
        """Record a single hourly funding payment.

        Args:
            funding_rate: The hourly funding rate (e.g. 0.000125).
            position_notional: Current position notional in USD.
            timestamp: Epoch time (defaults to now).

        Returns:
            The created FundingRecord.
        """
        ts = timestamp or time.time()
        cost = position_notional * funding_rate

        rec = FundingRecord(
            timestamp=ts,
            funding_rate=funding_rate,
            position_notional=position_notional,
            cost_usd=round(cost, 6),
        )

        self.total_paid_usd += cost
        if cost < 0:
            self.total_received_usd += abs(cost)
        self.hours_tracked += 1

        if self.first_record_ts == 0:
            self.first_record_ts = ts
        self.last_record_ts = ts

        self.avg_hourly_cost_usd = self.total_paid_usd / self.hours_tracked

        # Annualized cost as % of average notional
        if position_notional > 0 and self.hours_tracked > 0:
            avg_notional = position_notional  # simplified; could track avg over time
            annual_cost = self.avg_hourly_cost_usd * 24 * 365
            self.annualized_cost_pct = (annual_cost / avg_notional) * 100

        # Maintain rolling window
        self.recent_records.append(rec)
        if len(self.recent_records) > self._max_recent:
            self.recent_records = self.recent_records[-self._max_recent:]

        return rec

    @property
    def days_tracked(self) -> float:
        if self.hours_tracked == 0:
            return 0.0
        return self.hours_tracked / 24.0

    @property
    def net_cost_usd(self) -> float:
        """Net funding cost (positive = we paid, negative = we earned)."""
        return round(self.total_paid_usd, 2)

    @property
    def recent_trend(self) -> str:
        """Simple trend indicator from last 24 records."""
        if len(self.recent_records) < 3:
            return "insufficient_data"
        last_3 = self.recent_records[-3:]
        avg_recent = sum(r.cost_usd for r in last_3) / 3
        if avg_recent > 0.01:
            return "paying"
        elif avg_recent < -0.01:
            return "earning"
        return "neutral"

    def summary(self) -> str:
        """Human-readable summary for the AI copilot (dumb head friendly)."""
        direction = "paid" if self.total_paid_usd > 0 else "earned"
        amt = abs(self.total_paid_usd)
        return (
            f"{self.symbol}: ${amt:.2f} {direction} over "
            f"{self.days_tracked:.1f} days ({self.annualized_cost_pct:.1f}% ann.) "
            f"[{self.recent_trend}]"
        )


class FundingTracker:
    """Manages funding tracking across all positions.

    Persists state to `state/funding.json` for crash recovery.

    Usage:
        tracker = FundingTracker()
        tracker.record("BRENTOIL", funding_rate=0.000125, position_notional=500)
        tracker.record("BTC", funding_rate=-0.00005, position_notional=1000)
        print(tracker.summary())  # Human-readable for AI copilot
    """

    def __init__(self, state_dir: Optional[Path] = None):
        self.state_dir = Path(state_dir) if state_dir else DEFAULT_STATE_DIR
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.filepath = self.state_dir / "funding.json"
        self._positions: Dict[str, PositionFunding] = {}
        self._load()

    def record(self, symbol: str, funding_rate: float,
               position_notional: float,
               timestamp: Optional[float] = None) -> FundingRecord:
        """Record an hourly funding payment for a symbol."""
        if symbol not in self._positions:
            self._positions[symbol] = PositionFunding(symbol=symbol)
        rec = self._positions[symbol].record(funding_rate, position_notional, timestamp)
        self._save()
        return rec

    def get(self, symbol: str) -> Optional[PositionFunding]:
        """Get funding state for a symbol."""
        return self._positions.get(symbol)

    def summary(self) -> str:
        """Human-readable summary of all positions' funding."""
        if not self._positions:
            return "No funding data tracked yet."
        lines = [pos.summary() for pos in self._positions.values()]
        return "\n".join(lines)

    def clear(self, symbol: str) -> None:
        """Clear funding history for a symbol (e.g. when position closed)."""
        self._positions.pop(symbol, None)
        self._save()

    def _save(self) -> None:
        """Persist funding state to disk.

        H8 hardening: also writes a best-effort ``{filepath}.bak`` copy in the
        same directory so a single corrupt or deleted primary file is
        recoverable. Funding history is not regenerable from the exchange
        (HyperLiquid does not expose cumulative-paid funding by position).
        Closes the SPOF flagged in the data-stores.md verification ledger.
        """
        data = {}
        for sym, pf in self._positions.items():
            d = {
                "symbol": pf.symbol,
                "total_paid_usd": round(pf.total_paid_usd, 6),
                "total_received_usd": round(pf.total_received_usd, 6),
                "hours_tracked": pf.hours_tracked,
                "first_record_ts": pf.first_record_ts,
                "last_record_ts": pf.last_record_ts,
                "avg_hourly_cost_usd": round(pf.avg_hourly_cost_usd, 6),
                "annualized_cost_pct": round(pf.annualized_cost_pct, 2),
            }
            data[sym] = d

        serialized = json.dumps(data, indent=2)

        # Primary write — atomic via .tmp + rename (existing behavior)
        tmp = self.filepath.with_suffix(".tmp")
        try:
            with open(tmp, "w") as f:
                f.write(serialized)
            os.replace(tmp, self.filepath)
        except Exception as e:
            log.warning("Failed to save funding state: %s", e)
            return

        # H8 — best-effort .bak dual-write in the same directory
        try:
            from pathlib import Path as _Path
            bak_path = _Path(str(self.filepath) + ".bak")
            bak_tmp = _Path(str(self.filepath) + ".bak.tmp")
            with open(bak_tmp, "w") as f:
                f.write(serialized)
            os.replace(bak_tmp, bak_path)
        except Exception as e:
            log.warning("Funding state backup write failed: %s", e)

    def _load(self) -> None:
        """Load funding state from disk."""
        if not self.filepath.exists():
            return
        try:
            with open(self.filepath) as f:
                data = json.load(f)
            for sym, d in data.items():
                pf = PositionFunding(symbol=d.get("symbol", sym))
                pf.total_paid_usd = d.get("total_paid_usd", 0)
                pf.total_received_usd = d.get("total_received_usd", 0)
                pf.hours_tracked = d.get("hours_tracked", 0)
                pf.first_record_ts = d.get("first_record_ts", 0)
                pf.last_record_ts = d.get("last_record_ts", 0)
                pf.avg_hourly_cost_usd = d.get("avg_hourly_cost_usd", 0)
                pf.annualized_cost_pct = d.get("annualized_cost_pct", 0)
                self._positions[sym] = pf
        except Exception as e:
            log.warning("Failed to load funding state: %s", e)
