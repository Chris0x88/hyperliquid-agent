---
title: Tier State Machine
description: WATCH, REBALANCE, and OPPORTUNISTIC — what each tier can do and how to promote safely.
---

## The Tier Ladder

The daemon operates in one of three tiers that control how much autonomous action it can take:

| Tier | What it does | Trade placement |
|------|-------------|----------------|
| **WATCH** | All monitoring iterators active | None — advisory only |
| **REBALANCE** | Adds rebalancing toward thesis targets | Per-asset `agent` authority required |
| **OPPORTUNISTIC** | Full signal-driven trading | Per-asset `agent` authority required |

**Default: WATCH.** The system ships in WATCH and stays there until you explicitly promote.

---

## What WATCH Does

In WATCH tier, the daemon runs all these iterators every tick:

- Account state fetch and logging
- Mandatory SL/TP enforcement (PLACES orders to fix missing stops)
- Liquidation cushion monitoring and alerts
- Heartbeat Telegram messages
- Conviction state calculation
- Trade journal entries
- REFLECT evaluation loop
- Entry critic grading of new positions

WATCH tier can place orders — but only defensive ones (adding missing stops). It cannot enter new positions or resize existing ones.

---

## Promoting Tiers

Before promoting, complete the readiness checklist:

```bash
/readiness
```

This shows:
- Whether all open positions have SL/TP
- Whether thesis files are fresh (not stale)
- Whether authority is set correctly
- Whether the daemon health is green

Then promote via:

```bash
python -m cli.main daemon promote --tier rebalance
```

Or via the Telegram `/activate` command if you've set up the activation workflow.

---

## Per-Asset Authority

Tier promotion alone is not sufficient for autonomous trading. Each asset also needs its authority set to `agent`:

```bash
python -m cli.main authority set BRENTOIL agent
```

Without `agent` authority, the system treats that asset as `manual` regardless of tier.

---

## Rollback

To drop back to WATCH at any time:

```bash
python -m cli.main daemon demote --tier watch
```

Or restart the daemon — it always starts in the configured default tier.

---

## Kill Switches

Individual subsystems have separate kill switches independent of tier:

| Subsystem | Config file | What it controls |
|-----------|------------|-----------------|
| Oil Bot-Pattern | `data/config/oil_botpattern.json` | Pattern-based entry signals |
| News ingestion | `data/config/news_ingest.json` | RSS/iCal catalyst ingestion |
| Thesis updater | `data/config/thesis_updater.json` | Haiku-powered conviction adjustment |
| Lab engine | `data/config/lab.json` | Strategy development pipeline |
| Conviction bands | Inside thesis JSON | Per-market conviction scaling |

All kill switches default to **off** (disabled). Flip them manually when you're ready.

See [Tiers & Promotion Operations](/operations/tiers/) for the full promotion/rollback checklist.
