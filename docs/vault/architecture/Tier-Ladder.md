---
kind: architecture
tags:
  - architecture
  - tier-ladder
  - autonomy
---

# Tier Ladder

The daemon runs at one of three tiers at any given time. Each tier
activates a different subset of iterators. **This is the system-wide
autonomy dial.** On top of the tier filter, each subsystem has its own
kill switch AND each asset has its own per-asset authority (see
[[Authority-Model]]).

**Source of truth**: [`cli/daemon/tiers.py`](../../../cli/daemon/tiers.py)

## The three tiers

| Tier | What the bot can do | When Chris uses it |
|---|---|---|
| **`WATCH`** (current production) | Read-only iterators only — monitoring, alerts, auto-watchlist, lesson corpus reads, heatmap + supply ledger maintenance, entry critique on new positions (read-only grading) | Default production posture. Reports + alerts only. **No autonomous trade placement.** |
| **`REBALANCE`** | All of WATCH + `execution_engine`, `rebalancer`, `oil_botpattern`, `oil_botpattern_tune`, `oil_botpattern_reflect`, `catalyst_deleverage`, `exchange_protection`, `guard` | When Chris wants the bot to execute — either via conviction-driven thesis execution or via the oil_botpattern tactical strategy (both dual kill switches required) |
| **`OPPORTUNISTIC`** | Same as REBALANCE plus `radar` | Highest autonomy. Reserved for when Chris has explicitly delegated broad authority. |

## What each tier activates

The full iterator lists live in `cli/daemon/tiers.py`. Every iterator in
the vault has a `tiers:` frontmatter field auto-populated by the vault
generator. Browse [[iterators/_index]] to see which iterators live in
which tiers.

### WATCH (read-only, current production)

Iterators that run in WATCH are **always safe** — they read, they alert,
they write to append-only logs, they never place orders and never
modify positions. The tier is the default production posture because
losing nothing is more valuable than winning occasionally.

Typical WATCH tier includes (check `tiers.py` for the live list):
- `account_collector` (equity + positions snapshot)
- `liquidation_monitor` (cushion alerts)
- `news_ingest` (catalyst pipeline — sub-system 1)
- `supply_ledger` (disruption ledger — sub-system 2)
- `heatmap` (liquidity zones + cascades — sub-system 3)
- `bot_classifier` (bot-pattern classifier — sub-system 4)
- `thesis_engine` (reads thesis files, no execution in WATCH)
- `lesson_author` (writes candidate files from closed trades)
- `entry_critic` (grades new positions, posts critique alerts)
- `action_queue` (fires user-action nudges on schedule)
- `memory_backup` (hourly SQLite snapshot of memory.db)
- `autoresearch` (reflect engine)
- `memory_consolidation` (dream cycle)
- `journal` (position-close journaling)
- `telegram` (alert forwarder)

### REBALANCE (execution allowed on delegated assets)

REBALANCE adds the execution-capable iterators. **Even in REBALANCE,
the bot only acts on assets Chris has explicitly delegated via
`/delegate` per the [[Authority-Model]].** The tier unlocks *capability*;
the authority model gates *scope*.

Additions beyond WATCH:
- `execution_engine` (conviction-driven dip-adds + trims)
- `rebalancer` (vault BTC rebalancing)
- `exchange_protection` (mandatory SL+TP enforcement on exchange)
- `guard` (pre-execution risk gate)
- `profit_lock` (realised profit locking)
- `catalyst_deleverage` (reduce size on bullish catalyst, deleverage on bearish for longs)
- `oil_botpattern` (sub-system 5 — **the only place oil shorting is legal**, dual kill switches)
- `oil_botpattern_tune` (L1 bounded auto-tune — sub-system 6)
- `oil_botpattern_reflect` (L2 weekly reflect proposals — sub-system 6)

### OPPORTUNISTIC (add radar + future aggressive strategies)

Adds `radar` (opportunity scanner) on top of REBALANCE. Reserved for
future strategies that Chris explicitly authorizes.

## Promotion path

Promotion is **explicit and reversible**:

```
WATCH  →  REBALANCE  →  OPPORTUNISTIC
  (manual tier flag change in daemon config)
```

Per CLAUDE.md: "Every risky subsystem ships with `enabled: false` by
default." Promoting the tier does NOT automatically enable every
subsystem — each subsystem still has its own `data/config/<name>.json`
kill switch. Both the tier AND the kill switch must be `true` for a
subsystem to actually run.

**Example — enabling oil_botpattern shorts**:

1. Promote tier to REBALANCE (activates the iterator)
2. Flip `data/config/oil_botpattern.json:enabled = true`
3. Flip `data/config/oil_botpattern.json:short_legs_enabled = true`
4. `/delegate BRENTOIL` or `/delegate CL` (authority model)

All four must be true. Any one of them being false blocks execution.

## Registration contract (the memory_backup bug lesson)

Every iterator must be registered in **both**:

1. `cli/daemon/tiers.py` — tier membership (determines which tiers activate it)
2. `cli/commands/daemon.py:daemon_start()` — `clock.register(<ClassName>())` (determines whether it runs at all)

**Missing the second step is a silent bug.** The `memory_backup`
iterator was listed in tiers.py but not registered in daemon_start()
for 12+ hours after ship — the hourly backups were not actually
running in production. Caught by a parallel agent audit, fixed in
commit `4a58095`, documented in the vault's auto-generated iterator
pages as a `⚠️ REGISTRATION GAP` warning when detected.

See [[iterators/memory_backup]] for the full post-mortem.

## See also

- [[Overview]] — system architecture narrative
- [[Authority-Model]] — per-asset delegation on top of tiers
- [[Data-Discipline]] — P10 read-path bounds
- [[iterators/_index]] — full list of iterators with tier membership
