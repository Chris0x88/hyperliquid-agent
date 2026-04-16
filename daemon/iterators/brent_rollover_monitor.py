"""BrentRolloverMonitorIterator — Brent crude futures contract rollover alerts.

Reads a user-maintained calendar file at
``data/calendar/brent_rollover.json`` and alerts when the front-month
Brent contract is approaching its last trading day or first notice day.
This is the C7 piece from the 2026-04-07 connections audit.

Why this matters: HyperLiquid's xyz:BRENTOIL is a perpetual contract that
tracks the physical Brent benchmark. The benchmark itself is built from
ICE Brent futures, and around contract roll the underlying basis can move
sharply. A trader holding xyz:BRENTOIL through a roll can see the perp
mark do unexpected things even with no fundamental news. Knowing the roll
dates lets you size down or close ahead of the event.

Calendar file format::

    {
        "brent_futures": [
            {"contract": "BZK6", "delivery_month": "2026-05",
             "last_trading": "2026-04-13", "first_notice": "2026-04-30"},
            {"contract": "BZM6", "delivery_month": "2026-06",
             "last_trading": "2026-05-14", "first_notice": "2026-05-29"}
        ]
    }

Dates are ISO YYYY-MM-DD. Either ``last_trading`` or ``first_notice`` is
required per entry; both is fine.

Alert tiers (per contract, per threshold, only fired once):
  - 7 days out  → info     ("BZK6 last trading in 7 days")
  - 3 days out  → warning  ("BZK6 last trading in 3 days")
  - 1 day out   → critical ("BZK6 last trading TOMORROW")
  - past date   → info     ("BZK6 has rolled — now back month")

The iterator is safe in WATCH tier because it never queues orders or
touches the exchange. It only reads its config file and emits alerts.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from daemon.context import Alert, TickContext

log = logging.getLogger("daemon.brent_rollover_monitor")

# Throttle: check at most once per hour. Roll dates don't change minute-to-minute.
CHECK_INTERVAL_S = 3600

# Default config path — relative to project root, daemon cwd.
# data/calendar/ is the home for human-maintained reference calendars
# (annual.json, quarterly.json, etc.). This file joins them.
#
# The file itself is gitignored / hook-blocked because it lives under data/.
# When the file does NOT exist, the iterator falls back to DEFAULT_CALENDAR
# below so it works out-of-the-box. The user can override by creating the
# file at the path; it will be reloaded automatically (mtime watch).
DEFAULT_CONFIG_PATH = "data/calendar/brent_rollover.json"

# Built-in seed calendar used when DEFAULT_CONFIG_PATH does not exist.
# These are user-editable seeds — please verify against the official
# ICE Brent calendar before relying on them.
# https://www.theice.com/products/219/Brent-Crude-Futures
#
# Contract codes: F=Jan G=Feb H=Mar J=Apr K=May M=Jun
#                 N=Jul Q=Aug U=Sep V=Oct X=Nov Z=Dec
# Year is the last digit of the year. BZK6 = Brent May 2026.
DEFAULT_CALENDAR: List[dict] = [
    {"contract": "BZK6", "delivery_month": "2026-05", "last_trading": "2026-04-13"},
    {"contract": "BZM6", "delivery_month": "2026-06", "last_trading": "2026-05-14"},
    {"contract": "BZN6", "delivery_month": "2026-07", "last_trading": "2026-06-15"},
    {"contract": "BZQ6", "delivery_month": "2026-08", "last_trading": "2026-07-15"},
]

# Threshold tiers (days out, severity, label) — listed STRICTEST FIRST so the
# matching loop fires the most-urgent appropriate band rather than the loosest.
THRESHOLDS: List[Tuple[int, str, str]] = [
    (0, "critical", "TODAY"),
    (1, "critical", "TOMORROW"),
    (3, "warning", "in 3 days"),
    (7, "info", "in 7 days"),
]


class BrentRolloverMonitorIterator:
    """Watches the Brent futures roll calendar and alerts before each roll."""

    name = "brent_rollover_monitor"

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH) -> None:
        self._config_path = Path(config_path)
        self._last_check: float = 0.0
        # Track which (contract, event, threshold_days) tuples we've already alerted on
        # so we don't spam every cycle.
        self._fired: Set[Tuple[str, str, int]] = set()
        self._calendar: List[dict] = []
        self._loaded_at: float = 0.0

    def on_start(self, ctx: TickContext) -> None:
        self._reload_calendar()
        log.info(
            "BrentRolloverMonitor started  config=%s  contracts=%d  interval=%ds",
            self._config_path,
            len(self._calendar),
            CHECK_INTERVAL_S,
        )

    def on_stop(self) -> None:
        pass

    def tick(self, ctx: TickContext) -> None:
        now = time.monotonic()
        if now - self._last_check < CHECK_INTERVAL_S:
            return
        self._last_check = now

        # Reload calendar if file mtime changed (lets the user edit live)
        self._maybe_reload()

        if not self._calendar:
            return  # nothing to monitor — silent

        today = datetime.now(timezone.utc).date()

        for entry in self._calendar:
            contract = entry.get("contract", "?")
            self._check_event(ctx, today, contract, "last_trading", entry.get("last_trading"))
            self._check_event(ctx, today, contract, "first_notice", entry.get("first_notice"))

    # ── Internals ───────────────────────────────────────────────────

    def _maybe_reload(self) -> None:
        if not self._config_path.exists():
            self._calendar = []
            return
        try:
            mtime = self._config_path.stat().st_mtime
        except OSError:
            return
        if mtime > self._loaded_at:
            self._reload_calendar()

    def _reload_calendar(self) -> None:
        if not self._config_path.exists():
            # Fall back to the built-in seed calendar so the iterator works
            # out-of-the-box without requiring the user to ship a config file.
            self._calendar = list(DEFAULT_CALENDAR)
            self._loaded_at = 0.0
            self._fired.clear()
            log.info(
                "BrentRolloverMonitor: %s not found, using built-in seed (%d contracts)",
                self._config_path, len(self._calendar),
            )
            return
        try:
            data = json.loads(self._config_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            log.warning(
                "BrentRolloverMonitor: failed to load %s: %s",
                self._config_path, e,
            )
            self._calendar = []
            return
        entries = data.get("brent_futures", [])
        if not isinstance(entries, list):
            log.warning(
                "BrentRolloverMonitor: 'brent_futures' is not a list in %s",
                self._config_path,
            )
            self._calendar = []
            return
        self._calendar = entries
        try:
            self._loaded_at = self._config_path.stat().st_mtime
        except OSError:
            self._loaded_at = time.time()
        # Reset fired alerts on reload — config may have new dates
        self._fired.clear()
        log.info(
            "BrentRolloverMonitor: reloaded %d contract(s) from %s",
            len(self._calendar), self._config_path,
        )

    def _check_event(
        self,
        ctx: TickContext,
        today: date,
        contract: str,
        event_name: str,
        date_str: Optional[str],
    ) -> None:
        if not date_str:
            return
        try:
            event_date = date.fromisoformat(date_str)
        except (TypeError, ValueError):
            log.debug(
                "BrentRolloverMonitor: invalid date %s for %s.%s",
                date_str, contract, event_name,
            )
            return

        days_out = (event_date - today).days

        # Past event — fire a single 'rolled' info alert if we haven't yet
        if days_out < 0:
            key = (contract, event_name, -1)
            if key not in self._fired:
                self._fired.add(key)
                self._emit(
                    ctx,
                    severity="info",
                    msg=(
                        f"Brent {contract} {event_name.replace('_', ' ')} "
                        f"was {abs(days_out)} day(s) ago — contract is now back-month"
                    ),
                    contract=contract,
                    event=event_name,
                    days_out=days_out,
                )
            return

        # Find the smallest threshold this event has crossed but not yet fired
        for threshold_days, severity, label in THRESHOLDS:
            if days_out > threshold_days:
                continue  # haven't crossed yet
            key = (contract, event_name, threshold_days)
            if key in self._fired:
                continue  # already alerted at this tier
            self._fired.add(key)
            event_label = event_name.replace("_", " ")
            msg = f"Brent {contract} {event_label} {label}"
            if days_out != threshold_days:
                msg += f" (actual: {days_out}d out)"
            self._emit(
                ctx,
                severity=severity,
                msg=msg,
                contract=contract,
                event=event_name,
                days_out=days_out,
            )
            return  # one alert per event per tick

    def _emit(
        self,
        ctx: TickContext,
        severity: str,
        msg: str,
        contract: str,
        event: str,
        days_out: int,
    ) -> None:
        ctx.alerts.append(Alert(
            severity=severity,
            source=self.name,
            message=msg,
            data={
                "contract": contract,
                "event": event,
                "days_out": days_out,
            },
        ))
        log.info("[%s] %s", severity, msg)
