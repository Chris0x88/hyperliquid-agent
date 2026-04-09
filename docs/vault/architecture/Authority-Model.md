---
kind: architecture
tags:
  - architecture
  - authority
  - delegation
---

# Authority Model

**Per-asset, parameterized, reversible.** The bot is NOT always
supervised — authority is a dial Chris sets per asset. This is the
single biggest correction from the 2026-04-09 morning NORTH_STAR
rewrite (which wrongly asserted "always human in the loop" and was
caught by Chris the same day).

**Source of truth**: [`common/authority.py`](../../../common/authority.py) — 150 lines.
State file: `data/authority.json`.

## The three authority levels

| Level | What the bot can do | Default? |
|---|---|---|
| **`agent`** | Bot manages entries, exits, sizing, dip-adds, profit-takes. User gets reports. Bot acts on conviction engine + thesis. | No |
| **`manual`** | User trades. Bot is safety-net only — ensures SL/TP exist, alerts on dangerous leverage. **Never enters or exits.** | ✅ **Default for any unregistered asset** |
| **`off`** | Not watched at all. No alerts, no stops, nothing. | No |

The default is `manual` — safe. Unregistered assets get `manual`
automatically. Promoting to `agent` requires an explicit
`/delegate <ASSET>` Telegram command.

## How it's used

```python
from common.authority import get_authority, is_agent_managed

# Check whether the bot has authority to trade BRENTOIL
if is_agent_managed("BRENTOIL"):
    # execute_trade(...)
    ...

# Display in /status, /position, etc.
auth = get_authority("BRENTOIL")
icon = {"agent": "🤖", "manual": "👤", "off": "⬛"}[auth]
```

Every iterator that places trades checks authority before acting. The
existing execution path in `execution_engine` already respects this.
The entry critic iterator surfaces the authority icon in its critique
output so Chris sees at a glance which assets are bot-managed.

## The Telegram surface

| Command | Effect |
|---|---|
| `/delegate BRENTOIL` | Set authority to `agent` — bot manages entries, exits, sizing |
| `/reclaim BRENTOIL` | Set authority back to `manual` — you control, bot is safety net |
| `/authority` | Display the current authority state for all assets + positions |
| `/auth` | Alias for `/authority` |

All four are deterministic (no AI). Source:
[`cli/telegram_bot.py`](../../../cli/telegram_bot.py) around lines 1000-1049.

## Authority × Tier × Kill Switch = Effective Autonomy

The bot can only act on an asset when **all three** conditions are met:

```
  Asset authority == "agent"
    AND
  Daemon tier ∈ {REBALANCE, OPPORTUNISTIC}
    AND
  Relevant subsystem kill switch == true (per data/config/<name>.json)
```

Missing any one of the three → the bot is read-only on that asset.

Example: you delegate BRENTOIL (`/delegate BRENTOIL`), but the daemon
is in WATCH tier → the bot tracks BRENTOIL but cannot place trades.
Promote to REBALANCE and the conviction engine starts executing.
Additionally enable `oil_botpattern.enabled = true` + `short_legs_enabled
= true` and the tactical short leg is allowed. Any one of those
switches set to `false` disables the corresponding capability.

## Why it's per-asset, not global

Because Chris's confidence in delegating varies by market. He might
want the bot to execute his BTC thesis autonomously (high conviction,
simple execution) while keeping BRENTOIL manual because the physical
supply edge requires his own judgment. The per-asset model lets him
ship BTC autonomy without forcing oil autonomy.

The pattern also lets Chris experiment — delegate a market for a
week, observe the bot's decisions, reclaim if something feels off.
Reversible at any moment via `/reclaim`.

## Audit trail

Every authority change is logged to `data/authority.json` with a
timestamp. The file is JSON and append-style — the `changed_at` field
on each asset row records the last change, and the original row is
overwritten with the new level + new timestamp. The log is visible
via `/authority` any time.

## What this corrects

Per NORTH_STAR P6 ("delegated autonomy, not constant supervision"):
the bot is not always supervised. The authority model is what makes
that statement safe — Chris chooses the *scope* of delegation, the
bot operates autonomously within that scope, and the scope is
reversible at any moment.

Per NORTH_STAR P5 sub-rule (the meta-lesson from the morning rewrite):
"A feature that came up in passing... is NOT pre-validated." I (Claude)
rewrote NORTH_STAR in the morning and asserted a P6 that contradicted
this file. Chris caught it the same day. The authority model existed,
had been built, had been committed, had been registered in the Telegram
HANDLERS dict — and my morning rewrite skipped reading it. **Don't
skip reading common/authority.py ever again.**

## See also

- [[Tier-Ladder]] — daemon-wide tier on top of per-asset authority
- [[Overview]] — system architecture
- [[commands/delegate]] — `/delegate` command
- [[commands/reclaim]] — `/reclaim` command
- [[commands/authority]] — `/authority` command
- [[plans/NORTH_STAR]] — P6 "delegated autonomy, not constant supervision"
