---
title: Tiers & Promotion
description: The WATCH/REBALANCE/OPPORTUNISTIC ladder — what each tier can do and how to promote safely.
---

## Tier Overview

| Tier | Permissions | Default | Trade placement |
|------|-------------|---------|----------------|
| **WATCH** | Observe + alert only. Zero writes to exchange. | Yes | Only heartbeat (SL/TP placer) + user manually |
| **REBALANCE** | WATCH + ATR-based stop placement + delegated rebalancing | No | Heartbeat + exchange_protection + delegated execution_engine |
| **OPPORTUNISTIC** | REBALANCE + autonomous opportunity hunting | No | Everything REBALANCE does + autonomous entries on delegated assets |

Tier promotion raises the **capability** of the daemon. Each individual asset still needs explicit `agent` delegation for that capability to be exercised on it.

---

## WATCH Tier (Current Production)

WATCH provides full situational awareness with zero risk of unauthorized order placement.

**What runs:**
- Account state monitoring and snapshots
- Liquidation cushion alerts
- Funding rate tracking
- Protection audit (verifies SL/TP exist — does NOT place them)
- Brent rollover calendar alerts
- Pulse and radar signal scanners (read-only)
- Auto-research (REFLECT loop)

**What does NOT run:**
- Exchange order placement of any kind (that's the separate heartbeat process)
- Entry/exit orders
- Position resizing

**Note:** The heartbeat process handles actual SL/TP placement. It runs every 2 minutes via launchd, independent of the daemon tier.

---

## REBALANCE Tier

Adds active position management to WATCH:

- `exchange_protection` iterator — places missing stops as exchange orders
- `execution_engine` — rebalances positions toward thesis targets (delegated assets only)
- `profit_lock` — trailing profit protection
- `guard` — drawdown protection enforcement

Requires per-asset `agent` delegation in `data/authority.json`.

---

## OPPORTUNISTIC Tier

Adds autonomous signal-driven entries to REBALANCE:

- Full APEX conviction engine (entry signals, not just rebalancing)
- `radar` and `pulse` scanners fire live signals (not just read-only)

Requires per-asset `agent` delegation AND explicit enablement.

---

## Promotion Checklist

Before promoting from WATCH to REBALANCE:

- [ ] Run `/readiness` — all checks green
- [ ] All open positions have SL/TP (`/orders` shows trigger orders)
- [ ] Thesis files are fresh (updated within 72h)
- [ ] Authority set correctly for target assets
- [ ] Test suite passes (`pytest tests/ -x -q`)
- [ ] You understand what the execution_engine will do (review thesis convictions)

```bash
python -m cli.main daemon promote --tier rebalance
```

---

## Per-Asset Authority

```bash
# Delegate an asset to agent control
python -m cli.main authority set BRENTOIL agent

# Reclaim manual control
python -m cli.main authority set BRENTOIL manual

# Disable watching entirely
python -m cli.main authority set BRENTOIL off

# View current state
python -m cli.main authority list
```

Or via Telegram: `/delegate BRENTOIL`, `/reclaim BRENTOIL`, `/authority`

---

## Rollback

To drop back to WATCH at any time:

```bash
python -m cli.main daemon demote --tier watch
```

The daemon always restarts in the configured default tier. If in doubt, restart it — it defaults to WATCH.

---

## The `/activate` Command

The `/activate` Telegram command walks you through the tier promotion flow interactively, checking readiness gates at each step. Use it instead of the CLI if you're not sure.

See the [Activation Runbook](https://github.com/Chris0x88/hyperliquid-agent/blob/main/agent-cli/docs/wiki/operations/sub_system_5_activation.md) for the detailed walkthrough.
