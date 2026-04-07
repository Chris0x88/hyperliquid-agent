# Daemon Tiers — WATCH / REBALANCE / OPPORTUNISTIC

> Status: living doc. Last touched 2026-04-07. Owner: trading bot.
> Source of truth for the tick loop tiers, what runs in each, and how to
> promote between them. If this document and `cli/daemon/tiers.py` ever
> disagree, the code wins and this file gets fixed.

## TL;DR

The daemon runs a Hummingbot-style tick loop. Every tick, a sequence of
**iterators** is executed in order against a shared **TickContext**. Which
iterators run depends on the active **tier**. There are three tiers, each
strictly more privileged than the last:

| Tier | Permissions | Default? | Who places trades? |
|------|-------------|----------|--------------------|
| **WATCH** | Observe + alert only. ZERO writes to the exchange. | ✅ Yes | Only the user (manual) and the heartbeat process (SL placer). |
| **REBALANCE** | WATCH + ATR-based stop placement + delegated-asset rebalancing. | No | Heartbeat + `exchange_protection` iterator + delegated execution_engine. |
| **OPPORTUNISTIC** | REBALANCE + autonomous opportunity hunting via APEX/conviction engine. | No | Everything REBALANCE does + autonomous entries on delegated assets. |

Promotion is **always opt-in** and **per-asset** through `common/authority.py`
delegation. There is no global "go live" switch — promoting a tier raises
the *capability* of the daemon, but each individual asset still has to be
explicitly delegated for that capability to be exercised on it.

## Mental model

Think of the tiers as a **layered safety envelope**:

```
                ┌──────────────────────────────────┐
                │       OPPORTUNISTIC              │   ← can OPEN positions
                │  ┌────────────────────────────┐  │
                │  │      REBALANCE             │  │   ← can ADJUST positions
                │  │  ┌──────────────────────┐  │  │
                │  │  │       WATCH          │  │  │   ← can only OBSERVE
                │  │  └──────────────────────┘  │  │
                │  └────────────────────────────┘  │
                └──────────────────────────────────┘
```

Each outer ring inherits everything from the inner ring and adds new
write-capable iterators on top. You can never "downgrade" mid-tick — the
tier is decided at daemon startup (or via tier-change command) and applies
for the whole session until restarted.

## WATCH tier (current production state)

**Purpose:** Build full situational awareness with zero risk of the daemon
moving size. This is where the bot lives today and where it should stay
until you're ready to trust it with execution.

**Iterators (run in order each tick):**

| # | Iterator | What it does | Writes? |
|---|----------|--------------|---------|
| 1 | `connector` | Fetches positions, prices, orders, account state. Populates `ctx.positions`, `ctx.prices`, `ctx.orders`, `ctx.account`. | ❌ |
| 2 | `liquidation_monitor` | Computes per-position cushion = `(mark − liq) / mark`. Tiered alerts: ≥20% safe, 10–20% warning, <10% critical (re-alerts every 10 ticks while critical). | ❌ alerts only |
| 3 | `funding_tracker` | Polls funding payments from `userFunding` API, persists to `data/daemon/funding_tracker.jsonl`, alerts on outliers. | ❌ |
| 4 | `protection_audit` | Read-only verifier — for every open position, confirms a stop trigger order exists, on the right side, within 0.5%–50% of mark. Alerts: `no_stop` (CRITICAL), `wrong_side` (CRITICAL), `too_close` (WARNING), `too_far` (WARNING), `recovery` (INFO). Does NOT call `place_trigger_order`. | ❌ |
| 5 | `brent_rollover_monitor` | Reads `data/calendar/brent_rollover.json` (or baked-in `DEFAULT_CALENDAR` fallback). Alerts at 7d, 3d, 1d, day-of for each upcoming Brent contract roll. | ❌ |
| 6 | `pulse` | Multi-signal scanner. Populates `ctx.pulse_signals`. | ❌ |
| 7 | `radar` | Conviction-engine opportunity scanner. Populates `ctx.radar_opportunities`. | ❌ |
| 8 | `risk` | Consolidated protection-chain alert with calendar tags appended (e.g. `[WEEKEND, EVENT<24H:FOMC]`). | ❌ |
| 9 | `apex_advisor` | Dry-run APEX engine — proposes up to 3 candidate slot moves per cycle. Logs as advisory only. **Never queues an `OrderIntent`.** | ❌ |
| 10 | `autoresearch` | REFLECT loop — research-and-record on positions and watchlist. | ❌ writes to memory.db |
| 11 | `account_collector` | Persists daily snapshot to `data/snapshots/` and dual-writes to `account_snapshots` table in `memory.db`. | ❌ filesystem only |
| ... | (other observer iterators) | See `cli/daemon/tiers.py` for the authoritative list. | |

**The two things WATCH does NOT do:**
1. Place stop-loss or take-profit orders. (That's the **heartbeat process**'s job — a separate launchd-managed Python script that runs every 2 minutes and respects `common/authority.py`.)
2. Place entry or exit orders. (That requires REBALANCE or OPPORTUNISTIC + an `agent` delegation on the asset.)

**Who actually places stops in WATCH mode?** The heartbeat process. It is
**not** a daemon iterator. It runs separately, computes ATR-based stops via
`compute_stop_price()`, and respects per-asset authority. The
`protection_audit` iterator inside the daemon only **verifies** the
heartbeat's work — it never writes.

**This is why C1 was rewritten as `protection_audit`** instead of adding
`exchange_protection` to WATCH. Two writers (heartbeat + exchange_protection)
on the same stop slot would race and thrash. The audit pattern lets the
daemon catch heartbeat failures without becoming a second writer.

**How to know you're in WATCH:** `cli/daemon/tiers.py` `DEFAULT_TIER =
"WATCH"`, and `daemon` was started without an explicit tier flag.

## REBALANCE tier

**Purpose:** Let the daemon actively maintain protection levels and execute
already-decided rebalances on delegated assets. **Promoting to REBALANCE
means you trust the daemon to write to the exchange on your behalf for
defensive operations.**

**Adds these iterators on top of WATCH:**

| Iterator | What it does | Writes? |
|----------|--------------|---------|
| `exchange_protection` | Places ATR-based SL and thesis-driven TP triggers for any position missing them. Replaces what the heartbeat does (heartbeat should be **disabled** when running this tier to avoid the dual-writer bug). | ✅ trigger orders |
| `vault_rebalancer` | Maintains target vault allocation per `data/config/rebalancer.yaml`. Only runs when delegated. | ✅ market orders |
| `execution_engine` (defensive mode) | Executes user-approved or thesis-required position adjustments. Will close on thesis invalidation, will NOT open speculatively. | ✅ |

**Per-asset delegation still applies:** Promoting to REBALANCE does not
mean the daemon can touch every asset. Each asset is still gated by
`common/authority.py`:
- `manual` — daemon ignores it. User and heartbeat handle SL.
- `agent` — daemon manages SL/TP, can rebalance, can close on thesis invalidation.
- `off` — daemon refuses any action, even alerts.

**Promotion checklist (WATCH → REBALANCE):**
1. ✅ Run WATCH for at least 2 weeks with no `protection_audit` CRITICAL alerts that the heartbeat failed to resolve.
2. ✅ Confirm `protection_audit` matches what heartbeat produces (no `wrong_side` or `too_close` events).
3. ✅ Confirm `account_snapshots` table is populating cleanly and no drawdown excursion exceeds your comfort.
4. ✅ Stop the heartbeat launchd job (`launchctl unload com.hl-bot.heartbeat.plist`) — exchange_protection takes over.
5. ✅ Restart daemon with `--tier rebalance`.
6. ✅ Delegate ONE asset first (`/delegate BRENTOIL`). Watch for one full day.
7. ✅ Only after proving stability, delegate additional assets.

## OPPORTUNISTIC tier

**Purpose:** Full autonomous trading on delegated assets. The conviction
engine can open new positions, scale in, scale out, and hunt opportunities
from `pulse` and `radar` signals.

**Adds on top of REBALANCE:**

| Iterator | What it does | Writes? |
|----------|--------------|---------|
| `apex_engine` (live mode) | The advisor from WATCH/REBALANCE is replaced by the live engine. Slot decisions queue real `OrderIntent`s. | ✅ |
| `conviction_executor` | Reads thesis files in `data/thesis/` and sizes entries per Druckenmiller bands. | ✅ |
| `autoresearch` (write mode) | REFLECT loop is allowed to update conviction state, not just record observations. | ✅ memory.db + thesis state |

**Hard constraints that hold even at OPPORTUNISTIC:**
- LONG-or-NEUTRAL only on oil. **Never short oil**, even autonomously.
- Every position MUST have both SL and TP on exchange before sizing finishes.
- Conviction kill-switch: setting `conviction_bands.enabled = false` in config disables all autonomous entries instantly without restart.
- Per-asset authority is still respected — `manual` and `off` assets are untouched.
- Thesis-driven core markets only: BTC, BRENTOIL, GOLD, SILVER. Auto-watchlist tracks open positions in other markets but does NOT promote them to thesis-driven.

**Promotion checklist (REBALANCE → OPPORTUNISTIC):**
1. ✅ Run REBALANCE for at least 4 weeks with the daemon successfully maintaining SL/TP on at least one delegated asset, with zero override needed.
2. ✅ Confirm `apex_advisor`'s historical proposals (logged in WATCH and REBALANCE) match the trades you would have made manually. If the advisor's calls don't match your judgement, **do not promote**.
3. ✅ Confirm `data/thesis/` files exist and are current for every market you intend to delegate at this tier.
4. ✅ Confirm conviction bands kill switch is wired and tested.
5. ✅ Restart daemon with `--tier opportunistic`.
6. ✅ Delegate one asset. Watch for one full week.
7. ✅ Expand delegation only after a clean week.

## How to demote / roll back

If anything goes wrong at any tier, the rollback is **always** the same
two-step:
1. `/reclaim <ASSET>` — flip authority back to `manual` for the asset(s) of concern. The daemon will stop writing to that asset on the next tick.
2. Restart the daemon with `--tier watch`. This drops all write-capable iterators in one shot.
3. (If you stopped heartbeat earlier when promoting to REBALANCE, **restart it now**: `launchctl load ~/Library/LaunchAgents/com.hl-bot.heartbeat.plist`. Otherwise positions will be left without a stop-placer.)

## Where this is implemented in code

| Concern | File |
|---------|------|
| Tier definitions + iterator wiring | `cli/daemon/tiers.py` |
| Iterator base class + TickContext | `cli/daemon/context.py`, `cli/daemon/iterators/base.py` |
| Per-asset authority delegation | `common/authority.py` |
| WATCH-tier audit (read-only) | `cli/daemon/iterators/protection_audit.py` |
| REBALANCE write-capable protection | `cli/daemon/iterators/exchange_protection.py` |
| OPPORTUNISTIC engine | `cli/apex/engine.py`, conviction engine in `common/conviction_engine.py` |
| Heartbeat (the production SL placer in WATCH) | `common/heartbeat.py` (separate process) |

If you need a deeper architecture view, see
[`docs/wiki/components/daemon.md`](../components/daemon.md).
