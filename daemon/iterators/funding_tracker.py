"""FundingTrackerIterator -- tracks cumulative funding costs for open positions.

HyperLiquid perpetual futures charge/receive funding hourly.  For leveraged
positions this is a significant hidden cost that erodes PnL.  This iterator
estimates each payment on a throttled schedule and persists a running tally
to ``data/daemon/funding_tracker.jsonl``.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from daemon.context import Alert, TickContext

log = logging.getLogger("daemon.funding_tracker")

# HL funding is hourly.  The rate from MarketSnapshot is annualised.
_HOURS_PER_YEAR = 8760


class FundingTrackerIterator:
    name = "funding_tracker"

    def __init__(
        self,
        adapter: Any = None,
        alert_threshold_usd: float = 50.0,
        check_interval_s: int = 300,
        data_dir: str = "data/daemon",
    ):
        self._adapter = adapter
        self._alert_threshold_usd = alert_threshold_usd
        self._check_interval_s = check_interval_s
        self._data_dir = Path(data_dir)
        self._jsonl_path = self._data_dir / "funding_tracker.jsonl"

        # Per-instrument cumulative tracker
        # instrument -> {cumulative_usd, last_rate, last_check_ts, payments}
        self._trackers: Dict[str, Dict[str, Any]] = {}

        # Throttle
        self._last_check_ts: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self, ctx: TickContext) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._load_cumulative()
        log.info(
            "FundingTrackerIterator started  instruments=%d  threshold=$%.2f",
            len(self._trackers),
            self._alert_threshold_usd,
        )

    def on_stop(self) -> None:
        log.info("FundingTrackerIterator stopped")

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self, ctx: TickContext) -> None:
        now = ctx.timestamp or int(time.time())

        # Throttle: only run every check_interval_s
        if now - self._last_check_ts < self._check_interval_s:
            return

        if not ctx.positions:
            self._last_check_ts = now
            return

        # Fetch funding rates for instruments with open positions
        rates = self._fetch_rates(ctx)

        for pos in ctx.positions:
            inst = pos.instrument
            net_qty = float(pos.net_qty)
            if net_qty == 0.0:
                continue

            rate = rates.get(inst)
            if rate is None:
                continue

            price = float(ctx.prices.get(inst, 0))
            if price == 0.0:
                continue

            tracker = self._trackers.setdefault(inst, {
                "cumulative_usd": 0.0,
                "last_rate": 0.0,
                "last_check_ts": 0,
                "payments": 0,
            })

            elapsed_s = now - tracker["last_check_ts"] if tracker["last_check_ts"] else 0
            if elapsed_s <= 0:
                # First observation -- record state but don't charge
                tracker["last_rate"] = rate
                tracker["last_check_ts"] = now
                continue

            elapsed_hours = elapsed_s / 3600.0
            notional = abs(net_qty) * price
            hourly_rate = rate / _HOURS_PER_YEAR

            # For longs (net_qty > 0): positive rate = paying, negative = earning
            # For shorts (net_qty < 0): opposite
            if net_qty > 0:
                payment_usd = notional * hourly_rate * elapsed_hours
            else:
                payment_usd = -notional * hourly_rate * elapsed_hours

            tracker["cumulative_usd"] += payment_usd
            tracker["last_rate"] = rate
            tracker["last_check_ts"] = now
            tracker["payments"] += 1

            # Persist to JSONL
            self._append_jsonl({
                "timestamp": now,
                "instrument": inst,
                "rate": rate,
                "payment_usd": round(payment_usd, 6),
                "cumulative_usd": round(tracker["cumulative_usd"], 6),
            })

            # Alert if cumulative exceeds threshold (paid, not earned)
            if tracker["cumulative_usd"] > self._alert_threshold_usd:
                ctx.alerts.append(Alert(
                    severity="warning",
                    source=self.name,
                    message=(
                        f"Cumulative funding paid on {inst}: "
                        f"${tracker['cumulative_usd']:.2f} "
                        f"(threshold ${self._alert_threshold_usd:.2f})"
                    ),
                    data={
                        "instrument": inst,
                        "cumulative_usd": tracker["cumulative_usd"],
                        "last_rate": rate,
                    },
                ))

        self._last_check_ts = now

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> Dict[str, Any]:
        """Return aggregated funding summary across all tracked instruments."""
        total_paid = 0.0
        total_earned = 0.0
        per_instrument: Dict[str, Dict[str, Any]] = {}

        for inst, t in self._trackers.items():
            cum = t["cumulative_usd"]
            if cum > 0:
                total_paid += cum
            else:
                total_earned += abs(cum)
            per_instrument[inst] = {
                "cumulative_usd": round(cum, 6),
                "last_rate": t["last_rate"],
                "payments": t["payments"],
            }

        return {
            "total_paid_usd": round(total_paid, 6),
            "total_earned_usd": round(total_earned, 6),
            "net_funding_usd": round(total_earned - total_paid, 6),
            "instruments": per_instrument,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_rates(self, ctx: TickContext) -> Dict[str, float]:
        """Get funding rates -- try adapter snapshot, fall back to ctx attrs."""
        rates: Dict[str, float] = {}

        # Check if ctx has a funding_rates dict injected by another iterator
        ctx_rates = getattr(ctx, "funding_rates", None)
        if isinstance(ctx_rates, dict):
            rates.update(ctx_rates)

        # Fill gaps via adapter.get_snapshot()
        if self._adapter is not None:
            for pos in ctx.positions:
                inst = pos.instrument
                if inst in rates:
                    continue
                try:
                    snapshot = self._adapter.get_snapshot(inst)
                    if snapshot and snapshot.funding_rate is not None:
                        rates[inst] = float(snapshot.funding_rate)
                except Exception as e:
                    log.debug("Failed to fetch funding rate for %s: %s", inst, e)

        return rates

    def _append_jsonl(self, record: Dict[str, Any]) -> None:
        try:
            with open(self._jsonl_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as e:
            log.warning("Failed to write funding record: %s", e)

    def _load_cumulative(self) -> None:
        """Rebuild cumulative state from existing JSONL on startup."""
        if not self._jsonl_path.exists():
            return

        try:
            with open(self._jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    inst = rec.get("instrument")
                    if not inst:
                        continue

                    # Overwrite with latest cumulative from file
                    self._trackers[inst] = {
                        "cumulative_usd": rec.get("cumulative_usd", 0.0),
                        "last_rate": rec.get("rate", 0.0),
                        "last_check_ts": rec.get("timestamp", 0),
                        "payments": self._trackers.get(inst, {}).get("payments", 0) + 1,
                    }
        except OSError as e:
            log.warning("Failed to load funding history: %s", e)
