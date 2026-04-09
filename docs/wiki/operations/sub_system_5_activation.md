# Sub-System 5 Activation Runbook

**Audience:** Chris (solo operator).
**Goal:** Go from "sub-system 5 ships with kill switches OFF on mainnet
WATCH" to "real oil_botpattern trades flowing with full harness feedback",
without lighting money on fire at 3am.

The activation path has four rungs:

```
WATCH, enabled=false          ← starting state (today)
        │
        ▼
WATCH, decisions_only=true    ← shadow: iterator runs, no real orders,
        │                       paper positions + Telegram notices
        │
        ▼
REBALANCE, decisions_only=true ← shadow with full tier active,
        │                        all harness + guard iterators running
        │
        ▼
REBALANCE, decisions_only=false ← LIVE: real orders, kept small
        │                         via sizing_multiplier
        │
        ▼
REBALANCE, decisions_only=false + sizing_multiplier=1.0 ← full size
```

You can stop at any rung for as long as you want. The next rung is only
eligible after you've watched the current rung for long enough to be
confident in what you're seeing.

---

## Rung 0 — Starting state (today)

**Where you are:**
- `data/config/oil_botpattern.json` → `enabled: false`
- `decisions_only: false` (default)
- Daemon running in WATCH tier on mainnet
- Sub-system 5 is fully inert — iterator's first line returns on the
  kill switch check

**Gate to rung 1:** Run `/readiness`. It checks:

| Check | Expected state | Why |
|---|---|---|
| Sub-system 5 config | 🟢 master kill switch OFF | Can't promote what isn't wired |
| Catalyst feed | 🟢 fresh <12h | Gate chain needs catalysts |
| Supply ledger | 🟢 fresh <24h | Short-leg gate reads this |
| Liquidity heatmap | 🟢 fresh <6h | #3 must be producing zones |
| Bot classifier | 🟢 active <24h | #4 is the sole entry trigger |
| BRENTOIL thesis | 🟢 fresh <72h OR file absent (🟡) | Thesis lockout logic needs it |
| Risk caps | 🟢 populated for BRENTOIL + CL | Sizing fails closed without these |
| Drawdown brakes | 🟢 clean | No unresolved tripped brakes |

If overall is **🟢 GO**: you may proceed to rung 1.
If overall is **🟡 PROCEED WITH CAUTION**: fix the yellow flags or
decide explicitly to accept them before proceeding.
If **🔴 DO NOT ACTIVATE**: resolve the red flags first. Do not promote.

---

## Rung 1 — Shadow mode in WATCH

**What you do:**
1. Edit `data/config/oil_botpattern.json`:
   ```json
   "enabled": true,
   "decisions_only": true,
   "short_legs_enabled": false
   ```
   Leave all other fields as-shipped. In particular, leave `short_legs_enabled`
   off — shorts are the riskier leg and should prove themselves in
   shadow LAST, not FIRST.
2. Tail the daemon log or watch Telegram. Within one tick of the
   sub-system 5 interval (default 60s), the iterator will re-read
   config and engage.
3. The iterator now runs the full gate chain on every BRENTOIL/CL
   classifier output. On passing gates + positive sizing, it:
   - Writes to the decision journal at `data/strategy/oil_botpattern_journal.jsonl`
   - Opens a paper position tracked in
     `data/strategy/oil_botpattern_shadow_positions.json`
   - Emits a `🟡 SHADOW OPEN ...` Telegram alert with entry, size,
     leverage, notional, stop, take-profit, edge, and running balance
   - **Never** queues an OrderIntent — no exchange contact

**What you should see:**
- Telegram notices on every open: `🟡 SHADOW OPEN LONG BRENTOIL @ ...`
- Telegram notices on every close (SL, TP, or mode change):
  - `🟢 SHADOW TP ...` for winning closes (info severity)
  - `🔴 SHADOW SL ...` for losing closes (warning severity)
  - Each close includes realised PnL, ROE, hold time, updated balance,
    running win rate
- The `/sim` command shows balance, open positions with mark price,
  and recent trades on demand

**Interpret the data:**
- Are the entries going where your gut would have taken them? If the
  iterator is opening things you would never have traded, the gates are
  mis-calibrated — do not promote.
- Is the win rate in a believable band (30–70% over a reasonable
  sample)? Outside that range the gate set is probably wrong.
- Are losses small and wins larger on average? If not, the fixed 2%/5%
  SL/TP in shadow mode is mis-matched to the real ATR. Adjust
  `shadow_sl_pct` / `shadow_tp_pct` in config or decide to accept it
  knowing live will use ATR-based stops via `exchange_protection`.

**Stay at this rung for at least 7 days or 20 closed shadow trades,
whichever is LATER.** That sounds slow. It is deliberate.

**Rollback from rung 1:** Set `enabled: false` in config. The iterator
stops. Open shadow positions persist in their state file and will be
re-marked when the iterator runs again — they are NOT automatically
closed on disable, nor should they be (disable should be inert, not
destructive).

**Gate to rung 2:**
- `/sim` shows ≥ 20 closed shadow trades
- Win rate in a sane band
- You've manually reviewed at least 5 shadow trades and agreed with
  the decision journal's reasoning (edge, classification, gate results)
- `/readiness` still 🟢 or 🟡 with nothing freshly red
- No red Guardian drift reports

---

## Rung 2 — Shadow mode in REBALANCE

**What you do:**
1. Stop the daemon: `hl daemon stop` (or equivalent).
2. Restart in REBALANCE tier: `hl daemon start --tier rebalance --mainnet`
3. Leave `decisions_only: true` unchanged.

**What changes:**
- All REBALANCE iterators are now active: `execution_engine`,
  `exchange_protection`, `profit_lock`, `rebalancer`, the full thesis
  writer chain, the harness iterators (L1-L4).
- Sub-system 5 is still in shadow — no real orders from IT. But other
  strategies on the REBALANCE tier (the existing thesis_engine path
  for BRENTOIL positions > 24h) MAY place real orders. Those are
  existing live trading.
- The harness doesn't see shadow trades because they're written to a
  separate ledger. L1 auto-tune only tunes on real trades.

**What to watch:**
- Everything from rung 1.
- Guardian sweep output — any parallel-track drift between sub-systems.
- `/oilbot` still shows shadow state annotation (the state record has
  `shadow: true` to distinguish from real live positions).
- Other strategies' positions and orders — make sure shadow doesn't
  interact with them.

**Stay at this rung for another 7 days or 20 trades.** You're proving
that shadow behavior is stable under REBALANCE's full iterator stack,
not just WATCH's read-only stack.

**Rollback from rung 2:** `enabled: false` and/or stop the daemon and
restart in WATCH.

**Gate to rung 3:**
- Everything from the rung-1 → rung-2 gate, still true
- Shadow positions and real thesis_engine positions on BRENTOIL have
  been coexisting without anomalies
- You have a clear picture of typical shadow P&L cadence — roughly
  how many trades per day, typical hold time, typical drawdown

---

## Rung 3 — LIVE with reduced size

**What you do:**
1. Edit `data/config/risk_caps.json` to reduce sizing for oil_botpattern.
   The default `sizing_multiplier` is `1.0`. Set it to `0.25` (quarter
   size) to start real trades at 25% of the conviction ladder's
   suggested size.
2. Edit `data/config/oil_botpattern.json`:
   ```json
   "enabled": true,
   "decisions_only": false,
   "short_legs_enabled": false
   ```
   Shorts stay off at this rung — longs only, at reduced size, on
   mainnet for real.
3. The iterator next tick reads the config, sees `decisions_only=false`,
   and starts emitting real `OrderIntents` when gates pass. It also
   continues to mark any leftover shadow positions until they close on
   their paper SL/TP — shadow and real trades will briefly coexist.
4. `exchange_protection` attaches ATR-based stops + TPs to real
   positions immediately on fill. Verify with `/position`.

**What to watch:**
- First real trade: **get eyes on it immediately**. Check `/position`,
  `/orders`, `/status`, and the exchange UI. Confirm stop is attached
  and sensible.
- L1 auto-tune is still `enabled: false`. Leave it that way until at
  least 10 real closed trades have accumulated. Early-trade noise is
  NOT what you want the auto-tuner to train on.
- Drawdown brakes: `/oilbot` shows daily / weekly / monthly P&L and
  cap proximity. If the daily brake trips, the iterator stops opening
  new positions until manually cleared — that's by design.

**Stay at this rung for at least 2 weeks or 10 closed real trades.**

**Rollback from rung 3:**
- **Soft rollback:** `decisions_only=true` puts new entries back into
  shadow but leaves existing real positions alone — they continue to
  run with `exchange_protection` managing stops. Use this when you
  want to stop opening new trades but keep existing ones.
- **Hard rollback:** `enabled=false` stops new entries AND stops the
  iterator's management of existing positions. The positions continue
  to be watched by `exchange_protection` (stops stay attached) but
  sub-system 5 takes no further action on them. Use this when you
  need the iterator fully off, not just quieted.
- **Emergency close:** use the existing `/close <instrument>` Telegram
  command. This goes through the approval flow and closes the real
  position directly.

**Gate to rung 4:**
- ≥ 10 real closed trades
- Positive or neutral net PnL (not losing money — no sense scaling up
  a losing strategy)
- L1 auto-tune has been observed in shadow for a week without runaway
  nudges (flip `oil_botpattern_tune.enabled=true` one day after rung 3
  starts)

---

## Rung 4 — LIVE at full size

**What you do:**
1. Edit `risk_caps.json`: set `sizing_multiplier` back to `1.0` (or
   whatever your target fraction is).
2. Optionally: flip `short_legs_enabled=true`. This starts a 1-hour
   grace period before any short can open — deliberate friction so
   you have time to catch mistakes.
3. Optionally: flip `oil_botpattern_reflect.enabled=true` so L2 starts
   emitting weekly proposals.

**What to watch:**
- First trade at full size: same eyes-on-it drill as rung 3.
- First SHORT trade (if shorts enabled): this is the ONLY place in the
  codebase where shorting oil is legal. Watch it carefully. The
  grace-period gate should have already forced a 1h delay.
- L1 auto-tune audit log (`data/strategy/oil_botpattern_tune_audit.jsonl`)
  starts recording nudges. Review weekly at minimum.
- L2 proposal alerts land in Telegram. Review each one with
  `/selftuneproposals` before approving.

**Rollback from rung 4:** Any of the rung-3 rollback options plus:
- Drop `sizing_multiplier` back to 0.25 to shrink risk without stopping
- Set `short_legs_enabled=false` to disable shorts only
- Drop `oil_botpattern_tune.enabled=false` to freeze auto-tuning

---

## Invariants that must hold at every rung

- Every real position has both SL and TP attached on the exchange (CLAUDE.md rule, enforced by `exchange_protection`)
- `short_legs_enabled` never goes ON until all long-side gates have
  been proven stable
- Drawdown brakes are NEVER bypassed — a tripped brake requires
  manual clear, and the clear should be logged
- `sizing_ladder` is NEVER tuned automatically — structural, owner-only
- The 2026-04-07 hardening postmortem applies: before believing
  ANY claim about system state, run the commands and read the files

---

## Commands you'll use at every rung

| Command | Purpose |
|---|---|
| `/readiness` | Preflight checklist before promoting |
| `/oilbot` | Sub-system 5 state — kill switches, positions, brakes |
| `/oilbotjournal [N]` | Decision journal — which gates fired, edge, sizing |
| `/sim` | Shadow account — balance, open paper positions, recent trades |
| `/selftune` | Harness state — L1 params, L2 pending proposals |
| `/selftuneproposals` | Pending structural proposals to review |
| `/position` | Real positions + risk + liquidation distance |
| `/status` | Portfolio overview + PnL |
| `/close <instrument>` | Emergency manual close (with approval) |

---

## What this runbook does NOT cover

- Initial account setup or funding
- Adding new markets beyond BRENTOIL / CL — use the existing
  `/addmarket` flow, and remember the `xyz:` prefix gotcha
- Responding to exchange-side incidents (API down, funding anomalies,
  liquidation events) — that's the general operations runbook
- How to debug classifier misclassifications — that's sub-system 4 wiki
- ML overlay activation — L5 is parked indefinitely
