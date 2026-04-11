# Learning Path: Alerts & Monitoring

How alerts flow from iterators through TickContext to Telegram. Read these files in order.

---

## 1. `cli/daemon/context.py` -- Alert dataclass (line ~59)

**Start here.** The `Alert` dataclass is the universal alert struct:

```
Alert(
    severity: str,      # "info" | "warning" | "critical"
    source: str,        # iterator name, e.g. "liquidation_monitor"
    message: str,       # human-readable text
    timestamp: int,     # unix ms (auto-filled on creation)
    data: Dict,         # optional structured payload
)
```

Alerts live on `TickContext.alerts` (line ~114) -- a simple list that any iterator can append to during its `tick()` call. The list is drained by `TelegramIterator` at the end of each tick cycle.

This is fire-and-forget: no acknowledgement, no persistence. If the Telegram iterator is disabled, alerts evaporate silently (they still appear in daemon logs).

**What you'll learn:** The alert contract -- three severities, source tagging, and the append-then-drain lifecycle.

---

## 2. Any iterator that does `ctx.alerts.append()` -- Producers

**See how alerts are created in practice.** Almost every iterator produces alerts. Scan a few examples:

- `iterators/account_collector.py` -- drawdown alerts when equity drops below high-water mark thresholds
- `iterators/risk.py` -- risk gate transition alerts (OPEN/COOLDOWN/CLOSED)
- `iterators/thesis_engine.py` -- staleness reminders when thesis files go unreviewed
- `iterators/funding_tracker.py` -- cumulative funding cost warnings
- `iterators/brent_rollover_monitor.py` -- T-7/T-3/T-1 calendar alerts before contract rolls
- `iterators/thesis_challenger.py` -- CRITICAL alert when a new catalyst matches a thesis invalidation condition

The pattern is always the same:

```python
ctx.alerts.append(Alert(
    severity="warning",
    source=self.name,
    message="Funding cost for BRENTOIL exceeds 0.5% threshold",
    data={"coin": "xyz:BRENTOIL", "cumulative_pct": 0.62},
))
```

**What you'll learn:** That alert production is distributed across all iterators -- there's no central alert manager.

---

## 3. `cli/daemon/iterators/telegram.py` -- Alert consumer (line ~74)

**The single drain for all alerts.** `TelegramIterator.tick()` walks `ctx.alerts` every tick and forwards them to Telegram with severity-aware deduplication.

Key mechanisms:

**Dedup cooldowns** (line ~84):
| Severity | Cooldown |
|----------|----------|
| `critical` | 15 min (re-alerts to keep persistent issues visible) |
| `warning` | 1 hour |
| `info` | 4 hours |

**Dedup key** (line ~91): `"{source}:{first 60 chars of message}"` hashed to MD5. Same key within the cooldown window is silently dropped.

**Escalation** (line ~98): if the same alert fires again AFTER the cooldown expires (i.e., the condition persisted for the full cooldown duration), it gets an "ACTION REQUIRED" prefix. This catches conditions that don't self-resolve.

**Source labels** (line ~111): raw iterator names like `"liquidation_monitor"` are mapped to human-friendly labels like `"Liquidation"` for Telegram display.

**Additional notifications** (lines ~129-160):
- Risk gate transitions (OPEN/COOLDOWN/CLOSED) with state-change detection
- Order execution summaries for every non-noop `OrderIntent` in the queue
- Periodic status (every 30 ticks) with equity, position count, and tier

**Rate limiting**: 2-second minimum between Telegram API calls (line ~18) to stay under Telegram's rate limits.

**What you'll learn:** The dedup model, escalation logic, and how a single iterator serves as the alert sink.

---

## 4. `cli/daemon/iterators/liquidation_monitor.py` -- Tiered alerts example

**The best example of a multi-tier alert producer.** This iterator monitors every open position's distance to liquidation and emits alerts on tier transitions.

Tiers (line ~9-12):
| Cushion | Tier | Alert |
|---------|------|-------|
| >= 6% | safe | No alert (recovery alert if transitioning FROM worse) |
| 2% - 6% | warning | Alert on transition into this tier |
| < 2% | critical | Alert on transition + repeat every 10 ticks |

Design patterns to study:

- **Transition detection** (line ~108): tracks `_last_tier` per instrument, only alerts when tier CHANGES (not every tick)
- **Repeat for critical** (line ~116): `_last_critical_tick` dict ensures critical alerts re-fire every N ticks even without a tier change
- **Recovery alerts** (not shown in excerpt): when a position moves from warning/critical back to safe, an info alert confirms the improvement
- **Pure alert layer** (line ~17): never places orders, never modifies state. The ruin floor lives in `exchange_protection`

**What you'll learn:** How to build a stateful, transition-based alert producer with proper dedup and escalation.

---

## 5. `cli/daemon/iterators/protection_audit.py` -- SL/TP verification alerts

**The defense-in-depth auditor.** This read-only iterator fetches existing trigger orders from the exchange and compares them against open positions.

Alert conditions (line ~11-16):
| Condition | Severity | Meaning |
|-----------|----------|---------|
| No matching stop on exchange | CRITICAL | Position is unprotected |
| Stop on wrong side of entry | CRITICAL | Stop would lock in a loss |
| No take-profit on exchange | CRITICAL | Missing TP (added per feedback) |
| Stop implausibly far from price | WARNING | Probably stale or miscalculated |
| Stop looks reasonable | (no alert) | Info log only |

Coordination model (line ~24-30):
- `heartbeat` = SL placer (writes to exchange every 2 min via launchd)
- `protection_audit` = SL verifier (reads from exchange, alerts on gaps)
- `liquidation_monitor` = cushion alerter (reads positions, alerts on proximity)

The three together form the WATCH-tier defense story.

**What you'll learn:** How alerts serve as a monitoring layer over the mechanical stop-placement system, catching failures in other components.

---

## 6. `common/telemetry.py` -- HealthWindow error budget (line ~197)

**The circuit breaker that alerts feed into.** `HealthWindow` is a sliding-window health tracker:

- Configured with `window_s` (default 900 = 15 min) and `error_budget` (default 10)
- `record(event_type)` pushes events with timestamps into a deque
- `budget_exhausted()` returns True when error count in the window exceeds the budget
- When budget is exhausted, the daemon's `clock.py` auto-downgrades (e.g., pause order execution)

The `TelemetryRecorder` class (line ~69) provides a broader per-cycle metrics layer:
- Tracks action durations, status (ok/timeout/error), API call counts
- Records stop placement success/failure, order execution counts
- Writes to `state/telemetry.json` each cycle for external monitoring

**What you'll learn:** How the error budget pattern provides automatic circuit-breaking, and how telemetry data feeds the `/health` dashboard endpoint.

---

## Alert flow diagram

```
  Iterator A                Iterator B              Iterator C
  (account_collector)       (liquidation_monitor)   (protection_audit)
       |                         |                       |
       v                         v                       v
  ctx.alerts.append(         ctx.alerts.append(     ctx.alerts.append(
    Alert("warning",           Alert("critical",      Alert("critical",
      "account_collector",       "liquidation_monitor",  "protection_audit",
      "Drawdown 5.2%")          "BRENTOIL <2%")         "BTC no SL")
  )                          )                       )
       \                         |                      /
        \________________________|____________________/
                                 |
                                 v
                    TelegramIterator.tick(ctx)
                                 |
                    ┌────────────┴─────────────┐
                    │  Dedup by severity:       │
                    │  critical = 15min cooldown │
                    │  warning  = 1hr cooldown   │
                    │  info     = 4hr cooldown   │
                    │                            │
                    │  Escalation: same alert    │
                    │  after cooldown =          │
                    │  "ACTION REQUIRED"         │
                    └────────────┬─────────────┘
                                 |
                                 v
                      Telegram Bot API
                      (rate limited: 1 msg / 2s)
                                 |
                                 v
                      User's phone
```

The alerts list is cleared implicitly each tick (TickContext is rebuilt fresh). No persistence -- if Telegram is unreachable, the alert is lost until the condition fires again on the next tick.
