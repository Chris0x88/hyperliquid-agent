"""CalendarContext — multi-resolution temporal awareness for trading decisions.

Layers (from fastest to slowest cadence):
  1. Session (intraday)  — which market session is active, volume profile
  2. Daily               — key times: Asia open, EU open, US open, settlements
  3. Weekly              — weekday volume norms, weekend risk, market open/close
  4. Monthly/Quarterly   — OPEC, Fed, earnings, option expiries, contract rolls
  5. Annual/Seasonal     — Easter, Christmas, CNY, summer doldrums, tax season
  6. 4-Year Political    — election cycles, administration policy shifts
  7. 4-Year Halving      — BTC halving season map (your original research)
  8. Credit Cycle        — where we are in the long-wave credit cycle

CalendarContext.get_current() returns a compact summary (~200-300 tokens)
of what matters RIGHT NOW — no need to load massive files into context.

File layout: data/calendar/*.json (private, not pushed to GitHub)
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("calendar")

CALENDAR_DIR = "data/calendar"


# ---------------------------------------------------------------------------
# Time utilities
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_et() -> datetime:
    """Current time in US Eastern (approximate: UTC-5 EST, UTC-4 EDT)."""
    # Rough EDT check: March second Sunday to November first Sunday
    utc = _now_utc()
    month = utc.month
    if 3 < month < 11:
        offset = -4
    elif month == 3:
        # Second Sunday of March
        second_sun = 14 - (datetime(utc.year, 3, 1).weekday() + 1) % 7
        offset = -4 if utc.day >= second_sun else -5
    elif month == 11:
        first_sun = 7 - (datetime(utc.year, 11, 1).weekday() + 1) % 7
        offset = -5 if utc.day >= first_sun else -4
    else:
        offset = -5
    return utc + timedelta(hours=offset)


def _now_aest() -> datetime:
    """Current time in AEST (UTC+10) / AEDT (UTC+11)."""
    utc = _now_utc()
    # Rough AEDT: first Sunday in October to first Sunday in April
    month = utc.month
    if 4 < month < 10:
        offset = 10
    elif month == 4:
        first_sun = 7 - (datetime(utc.year, 4, 1).weekday() + 1) % 7
        offset = 10 if utc.day >= first_sun else 11
    elif month == 10:
        first_sun = 7 - (datetime(utc.year, 10, 1).weekday() + 1) % 7
        offset = 11 if utc.day >= first_sun else 10
    else:
        offset = 11 if month < 4 else 10
    return utc + timedelta(hours=offset)


# ---------------------------------------------------------------------------
# Session identification
# ---------------------------------------------------------------------------

@dataclass
class SessionInfo:
    """Which trading session is currently active."""
    name: str                    # "asia", "europe", "us", "overnight", "weekend"
    phase: str                   # "pre_open", "open", "peak", "close", "after_hours"
    volume_profile: str          # "thin", "normal", "heavy"
    hours_to_next_major: float   # hours until next major session event
    next_event: str              # description of next event
    weekend: bool = False
    user_likely_state: str = ""  # "sleeping", "waking", "active", "winding_down"


def _get_session(et: datetime, aest: datetime) -> SessionInfo:
    """Determine current session from ET and AEST times."""
    weekday_et = et.weekday()  # 0=Mon
    hour_et = et.hour + et.minute / 60
    hour_aest = aest.hour + aest.minute / 60

    # Weekend check (HL perps trade Sun 6PM ET - Fri 5PM ET)
    if weekday_et == 5 or (weekday_et == 4 and hour_et >= 17):
        return SessionInfo(
            name="weekend", phase="closed", volume_profile="thin",
            hours_to_next_major=_hours_until_sunday_open(et),
            next_event="Market opens Sunday 6PM ET",
            weekend=True,
            user_likely_state=_user_state(aest),
        )
    if weekday_et == 6 and hour_et < 18:
        return SessionInfo(
            name="weekend", phase="closed", volume_profile="thin",
            hours_to_next_major=18 - hour_et,
            next_event="Market opens Sunday 6PM ET",
            weekend=True,
            user_likely_state=_user_state(aest),
        )

    # Session windows (ET-based)
    if 18 <= hour_et or hour_et < 3:
        # Asia session (6PM-3AM ET = 8AM-1PM AEST next day roughly)
        name = "asia"
        if hour_et >= 18 and hour_et < 20:
            phase = "pre_open"
        elif hour_et >= 20 or hour_et < 1:
            phase = "open"
        else:
            phase = "close"
        volume = "normal" if 21 <= hour_et or hour_et < 2 else "thin"
        hours_next = (3 - hour_et) % 24
        next_ev = "EU pre-market 3AM ET"
    elif 3 <= hour_et < 8:
        # Europe session (3AM-8AM ET = London open)
        name = "europe"
        if hour_et < 4:
            phase = "pre_open"
        elif hour_et < 7:
            phase = "open"
        else:
            phase = "close"
        volume = "normal" if 4 <= hour_et < 7 else "thin"
        hours_next = 9.5 - hour_et
        next_ev = "US pre-market 8AM ET"
    elif 8 <= hour_et < 9.5:
        # US pre-market
        name = "us"
        phase = "pre_open"
        volume = "normal"
        hours_next = 9.5 - hour_et
        next_ev = "US market open 9:30AM ET"
    elif 9.5 <= hour_et < 12:
        # US morning — heaviest volume
        name = "us"
        phase = "peak"
        volume = "heavy"
        hours_next = 16 - hour_et
        next_ev = "US close 4PM ET"
    elif 12 <= hour_et < 16:
        # US afternoon
        name = "us"
        phase = "open"
        volume = "normal" if hour_et < 15 else "heavy"  # close cross heavy
        hours_next = 16 - hour_et
        next_ev = "US close 4PM ET"
    elif 16 <= hour_et < 18:
        # US after-hours
        name = "us"
        phase = "after_hours"
        volume = "thin"
        hours_next = 18 - hour_et
        next_ev = "Asia session 6PM ET"
    else:
        name = "overnight"
        phase = "open"
        volume = "thin"
        hours_next = 4
        next_ev = "Next session"

    return SessionInfo(
        name=name, phase=phase, volume_profile=volume,
        hours_to_next_major=max(hours_next, 0.1),
        next_event=next_ev,
        user_likely_state=_user_state(aest),
    )


def _user_state(aest: datetime) -> str:
    """Estimate user state based on AEST time (Perth-based petroleum engineer)."""
    h = aest.hour
    if h < 6:
        return "sleeping"
    elif h < 8:
        return "waking"
    elif h < 12:
        return "active_morning"
    elif h < 17:
        return "active_afternoon"
    elif h < 21:
        return "winding_down"
    elif h < 23:
        return "late_evening"
    else:
        return "sleeping"


def _hours_until_sunday_open(et: datetime) -> float:
    """Hours until Sunday 6PM ET from current ET time."""
    wd = et.weekday()
    if wd == 5:  # Saturday
        return (24 - et.hour - et.minute / 60) + 18
    elif wd == 4:  # Friday evening
        return (24 - et.hour - et.minute / 60) + 24 + 18
    elif wd == 6:  # Sunday
        if et.hour < 18:
            return 18 - et.hour - et.minute / 60
        return 0
    return 0


# ---------------------------------------------------------------------------
# Event calendar (loaded from JSON files)
# ---------------------------------------------------------------------------

def _load_json(filename: str) -> Any:
    """Load a calendar JSON file, returning empty dict/list on failure."""
    path = os.path.join(CALENDAR_DIR, filename)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        log.warning("Failed to load %s: %s", path, e)
        return {}


def _upcoming_events(events: List[Dict], hours_ahead: float = 48) -> List[Dict]:
    """Filter events to those occurring within hours_ahead from now."""
    now_ts = time.time()
    cutoff = now_ts + hours_ahead * 3600
    result = []
    for ev in events:
        ev_date = ev.get("date", "")
        ev_time = ev.get("time", "00:00")
        try:
            dt = datetime.strptime(f"{ev_date} {ev_time}", "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=timezone.utc)
            ev_ts = dt.timestamp()
            if now_ts <= ev_ts <= cutoff:
                hours_away = (ev_ts - now_ts) / 3600
                ev_copy = dict(ev)
                ev_copy["hours_away"] = round(hours_away, 1)
                result.append(ev_copy)
        except Exception:
            continue
    return sorted(result, key=lambda x: x.get("hours_away", 999))


# ---------------------------------------------------------------------------
# Cycle positioning
# ---------------------------------------------------------------------------

@dataclass
class CyclePosition:
    """Where we are in a multi-year cycle."""
    name: str              # "btc_halving", "credit", "political"
    phase: str             # e.g. "expansion", "euphoria", "contraction"
    phase_pct: float       # 0.0-1.0 how far through current phase
    description: str       # one-line context
    implication: str       # what this means for trading


def _get_cycle_positions() -> List[CyclePosition]:
    """Load cycle data from JSON files and compute current position."""
    cycles = []

    # BTC halving cycle
    halving = _load_json("4yr_halving.json")
    if halving and halving.get("phases"):
        now = _now_utc()
        for phase in halving["phases"]:
            start = datetime.strptime(phase["start"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end = datetime.strptime(phase["end"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if start <= now <= end:
                total = (end - start).total_seconds()
                elapsed = (now - start).total_seconds()
                pct = elapsed / total if total > 0 else 0
                cycles.append(CyclePosition(
                    name="btc_halving",
                    phase=phase["name"],
                    phase_pct=round(pct, 2),
                    description=phase.get("description", ""),
                    implication=phase.get("implication", ""),
                ))
                break

    # Credit cycle
    credit = _load_json("credit_cycle.json")
    if credit and credit.get("current_phase"):
        cycles.append(CyclePosition(
            name="credit_cycle",
            phase=credit["current_phase"],
            phase_pct=float(credit.get("phase_pct", 0.5)),
            description=credit.get("description", ""),
            implication=credit.get("implication", ""),
        ))

    # Political cycle
    political = _load_json("4yr_political.json")
    if political and political.get("current_phase"):
        cycles.append(CyclePosition(
            name="political_cycle",
            phase=political["current_phase"],
            phase_pct=float(political.get("phase_pct", 0.5)),
            description=political.get("description", ""),
            implication=political.get("implication", ""),
        ))

    return cycles


# ---------------------------------------------------------------------------
# Weekday context
# ---------------------------------------------------------------------------

def _weekday_context(et: datetime) -> Dict[str, Any]:
    """Weekday-specific norms from weekly template."""
    weekly = _load_json("weekly_template.json")
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_name = day_names[et.weekday()]

    if weekly and day_name in weekly:
        return weekly[day_name]
    return {"volume_norm": "normal", "notes": ""}


# ---------------------------------------------------------------------------
# Main API: CalendarContext.get_current()
# ---------------------------------------------------------------------------

@dataclass
class CalendarContext:
    """Compact temporal context for the current moment. ~200-300 tokens."""
    timestamp_utc: str
    timestamp_et: str
    timestamp_aest: str

    # Session layer
    session: SessionInfo

    # Weekday context
    weekday: str
    weekday_context: Dict[str, Any]

    # Upcoming events (next 48h)
    events_next_48h: List[Dict]

    # Cycle positions
    cycles: List[CyclePosition]

    # Seasonal context
    seasonal_notes: str

    def to_prompt(self) -> str:
        """Compact text representation for injection into AI prompt (~200-300 tokens)."""
        lines = []
        lines.append(f"TIME: {self.timestamp_utc} UTC | {self.timestamp_et} ET | {self.timestamp_aest} AEST")
        lines.append(f"SESSION: {self.session.name}/{self.session.phase} | volume={self.session.volume_profile} | user={self.session.user_likely_state}")

        if self.session.weekend:
            lines.append(f"WEEKEND: market thin/closed | next open: {self.session.next_event} ({self.session.hours_to_next_major:.1f}h)")
        else:
            lines.append(f"NEXT: {self.session.next_event} in {self.session.hours_to_next_major:.1f}h")

        wd_ctx = self.weekday_context
        if wd_ctx.get("notes"):
            lines.append(f"DAY: {self.weekday} — {wd_ctx['notes']}")

        if self.events_next_48h:
            lines.append("EVENTS (48h):")
            for ev in self.events_next_48h[:5]:  # max 5 events
                lines.append(f"  {ev.get('hours_away', '?')}h: {ev.get('name', '')} [{ev.get('impact', 'medium')}]")

        if self.cycles:
            lines.append("CYCLES:")
            for c in self.cycles:
                lines.append(f"  {c.name}: {c.phase} ({c.phase_pct:.0%}) — {c.implication}")

        if self.seasonal_notes:
            lines.append(f"SEASONAL: {self.seasonal_notes}")

        return "\n".join(lines)

    def to_dict(self) -> Dict:
        return {
            "timestamp_utc": self.timestamp_utc,
            "timestamp_et": self.timestamp_et,
            "timestamp_aest": self.timestamp_aest,
            "session": {
                "name": self.session.name,
                "phase": self.session.phase,
                "volume_profile": self.session.volume_profile,
                "hours_to_next_major": self.session.hours_to_next_major,
                "next_event": self.session.next_event,
                "weekend": self.session.weekend,
                "user_likely_state": self.session.user_likely_state,
            },
            "weekday": self.weekday,
            "events_next_48h": self.events_next_48h,
            "cycles": [{"name": c.name, "phase": c.phase, "pct": c.phase_pct,
                         "description": c.description, "implication": c.implication}
                        for c in self.cycles],
            "seasonal_notes": self.seasonal_notes,
        }

    @classmethod
    def get_current(cls, calendar_dir: str = CALENDAR_DIR) -> "CalendarContext":
        """Build the current calendar context. This is the main API."""
        global CALENDAR_DIR
        old_dir = CALENDAR_DIR
        CALENDAR_DIR = calendar_dir

        try:
            utc = _now_utc()
            et = _now_et()
            aest = _now_aest()

            session = _get_session(et, aest)

            # Load quarterly + annual events
            quarterly_events = _load_json("quarterly.json")
            annual_events = _load_json("annual.json")
            all_events = []
            if isinstance(quarterly_events, dict):
                all_events.extend(quarterly_events.get("events", []))
            elif isinstance(quarterly_events, list):
                all_events.extend(quarterly_events)
            if isinstance(annual_events, dict):
                all_events.extend(annual_events.get("events", []))
            elif isinstance(annual_events, list):
                all_events.extend(annual_events)

            upcoming = _upcoming_events(all_events, hours_ahead=48)

            cycles = _get_cycle_positions()
            wd_ctx = _weekday_context(et)

            # Seasonal notes
            seasonal = _load_json("annual.json")
            seasonal_notes = ""
            if isinstance(seasonal, dict):
                seasonal_notes = seasonal.get("current_seasonal_note", "")

            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

            return cls(
                timestamp_utc=utc.strftime("%Y-%m-%d %H:%M UTC"),
                timestamp_et=et.strftime("%Y-%m-%d %H:%M ET"),
                timestamp_aest=aest.strftime("%Y-%m-%d %H:%M AEST"),
                session=session,
                weekday=day_names[et.weekday()],
                weekday_context=wd_ctx,
                events_next_48h=upcoming,
                cycles=cycles,
                seasonal_notes=seasonal_notes,
            )
        finally:
            CALENDAR_DIR = old_dir
