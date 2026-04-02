# Phase 3: Wire REFLECT Meta-Evaluation

> **Status: Planned**
> **Depends on: Phase 2 complete (daemon running)**
> **Estimated: 1 session**

## Goal

The system evaluates itself. Every trade is journaled, every week is reviewed, performance is tracked over time, and Chris gets a clear "is this working?" signal.

## What's Already Built (just needs wiring)

| Module | Location | What it does |
|--------|----------|-------------|
| ReflectEngine | `modules/reflect_engine.py` | FIFO round-trip analysis, win rate, PnL, FDR, streaks |
| ReflectReporter | `modules/reflect_reporter.py` | Markdown reports + distilled summaries |
| ConvergenceTracker | `modules/reflect_convergence.py` | Detects if adjustments are helping or oscillating |
| ReflectAdapter | `modules/reflect_adapter.py` | Suggests config parameter fixes with guardrails |
| JournalEngine | `modules/journal_engine.py` | Trade quality assessment, nightly review |
| JournalGuard | `modules/journal_guard.py` | Journal persistence (JSONL I/O) |
| MemoryEngine | `modules/memory_engine.py` | Playbook (what works per instrument/signal) |
| MemoryGuard | `modules/memory_guard.py` | Memory persistence (JSONL + JSON) |
| AutoResearch iterator | `cli/daemon/iterators/autoresearch.py` | 30-min evaluation loop (daemon) |

## Wiring Plan

### 1. AutoResearch iterator → REFLECT engine
**File:** `cli/daemon/iterators/autoresearch.py`

The autoresearch iterator already runs every 30 minutes in the daemon. Wire it to:
- Load recent trades from `data/research/trades/`
- Call `ReflectEngine.compute()` with trade records
- Log `ReflectMetrics` to memory via `MemoryGuard.log_event()`
- If `ConvergenceTracker.is_converging()` is false for 2+ cycles → alert

### 2. Journal entries on position close
**File:** `cli/daemon/iterators/execution_engine.py` or `guard.py`

When a position is closed (by guard, profit_lock, or manual):
- Create `JournalEntry` via `JournalEngine.create_entry()`
- Persist via `JournalGuard.log_entry()`
- Update `MemoryEngine` playbook with outcome

### 3. Nightly review
**File:** New function in autoresearch or separate iterator

After market close (5PM ET Friday, or daily at midnight AEST):
- Call `JournalEngine.compute_nightly_review()` with today's trades vs 7-day rolling
- Log key findings to memory
- Send brief to Telegram: "Today: 3 trades, 67% WR, +$45 | 7d avg: 55% WR, +$23/day"

### 4. Weekly REFLECT summary to Telegram
**File:** Autoresearch iterator or daemon telegram iterator

Every Sunday:
- Run full REFLECT on past 7 days of trades
- Generate distilled summary via `ReflectReporter.distill()`
- Send to Telegram

### 5. Playbook accumulation
**File:** `modules/memory_engine.py` (already built)

After each position close:
- Update playbook entry for (instrument, signal_source)
- Track: trade_count, win_count, total_pnl, avg_roe

Over time, the playbook answers: "Are BRENTOIL radar entries profitable? Are BTC pulse entries worth taking?"

## Success Metric

After Phase 3, Chris gets:
```
[Weekly] 12 trades, 58% WR, net +$234
Signal quality: 3 good, 7 fair, 2 poor
Playbook: BRENTOIL radar 71% WR, BTC pulse 45% WR
System: 0 failures, daemon uptime 99.8%
Convergence: improving (3 consecutive positive cycles)
```

## Verification

```bash
# 1. Generate a REFLECT report from existing trade data
hl reflect run

# 2. Check journal has entries
cat data/apex/journal.jsonl | wc -l

# 3. Check playbook accumulates
cat data/apex/memory/playbook.json

# 4. Verify weekly summary fires (test with --max-ticks)
```
