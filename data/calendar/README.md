# Calendar Data (Private)

This directory contains private trading calendar data used by the CalendarContext system.

**These files are NOT pushed to GitHub** (data/ is in .gitignore).

## Files

- `weekly_template.json` — Session hours, volume norms by weekday, user schedule
- `quarterly.json` — OPEC, Fed, earnings, contract rolls, option expiries
- `annual.json` — Holidays, seasonal patterns for oil and BTC
- `4yr_halving.json` — BTC halving cycle phases and current position
- `4yr_political.json` — US political cycle, administration policy analysis
- `credit_cycle.json` — Long-wave credit cycle, fiscal dominance regime analysis

## Public Template

See `templates/calendar/` in the repo root for anonymized placeholder versions
that can be used as starting points.

## How It Works

`common/calendar.py` → `CalendarContext.get_current()` returns a compact ~200-300 token
summary of what matters RIGHT NOW: session, volume profile, upcoming events, cycle positions.
Injected into the scheduled task every 5 minutes.
