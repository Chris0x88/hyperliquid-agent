# Phase 4: Self-Improving System

> **Status: Future**
> **Depends on: Phase 3 complete (REFLECT wired)**

## Goal

The system learns from outcomes and improves with less human direction. Chris sets the thesis, the system handles everything else and gets better at it over time.

## Components

### 1. REFLECT adapter auto-tunes parameters
- `ReflectAdapter.adapt()` suggests parameter changes based on metrics
- `DirectionalHysteresis` prevents oscillation (require 2 consecutive same-direction)
- `ConvergenceTracker` gates changes (only apply if overall performance improving)
- Guardrails: radar_score [120-280], pulse_confidence [40-95], daily_loss_limit [$50-$5000]

### 2. Playbook-informed filtering
- If a (instrument, signal_source) combo has <40% win rate over 20+ trades, stop taking those entries
- If a combo has >70% win rate, increase conviction multiplier for those signals
- This is emergent strategy — the system discovers what works

### 3. Catalyst deleverage calendar
- Wire `CatalystDeleverage` iterator with event calendar
- Known events: Trump deadlines, OPEC meetings, contract rolls, NFP, CPI
- 6h before event: alert Chris
- 1h before event: auto-reduce leverage by configured %
- Calendar stored in `data/calendar/` (already built)

### 4. System health monitoring
- Track: daemon uptime, API latency, thesis freshness, alert delivery
- Weekly health score: 0-100
- Alert if score drops below 80
- Monthly trend: "System health improving/degrading"

### 5. Claude Code session efficiency
- Per-package CLAUDE.md files scope each session
- `docs/plans/MASTER_PLAN.md` provides session start context
- Phase-specific plans track progress across sessions
- Each session updates plans with what was done

## Success Metric

Chris opens his phone Sunday morning and sees:
```
[Weekly Report Card]
Portfolio: +2.3% this week ($654 → $669)
Trades: 8 total, 62% WR, net +$15
Best: BRENTOIL long +$12 (radar entry, held 4h)
Worst: BTC short -$5 (pulse entry, stopped out 20min)
Playbook: radar entries 71% WR (keep), pulse shorts 33% WR (flagged)
System: 99.2% uptime, 0 blind periods, thesis avg age 4.2h
Auto-adjustments: radar_threshold 180→170 (approved by convergence)
Recommendation: Consider dropping BTC pulse shorts (3 consecutive losses)
```

## Verification

- Playbook has 20+ entries per instrument with meaningful win rates
- Convergence tracker shows positive trend over 4+ weeks
- Catalyst deleverage fires correctly before known events
- System health score stays above 80 for consecutive weeks
