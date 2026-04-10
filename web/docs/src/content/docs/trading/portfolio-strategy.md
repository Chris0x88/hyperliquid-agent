---
title: Portfolio Strategy
description: How BTC Power Law, oil theses, and metals positions fit together as a portfolio.
---

## Account Structure

Two separate accounts on HyperLiquid:

| Account | Markets | Strategy | Automation |
|---------|---------|----------|------------|
| **Main account** | BRENTOIL, GOLD, SILVER | Thesis-driven, human-in-loop | Heartbeat enforces SL/TP |
| **Vault** | BTC | Power Law rebalancing | Automated hourly |

---

## BTC Power Law (Vault)

The vault runs an automated rebalancing strategy based on BTC's long-term power law price trend:

- **Target allocation:** Calculated from power law regression
- **Rebalance cadence:** Hourly check, trade if >5% off target
- **Direction:** Long only (buy below power law, reduce above)
- **Script:** `scripts/run_vault_rebalancer.py` via launchd

The BTC strategy is fully automated and does not require thesis files. It runs independently of the main account.

---

## Oil Strategy (Main Account)

The oil position is thesis-driven with human judgment driving entries:

1. **Write thesis:** Create/update `data/thesis/BRENTOIL.json` with current view
2. **Set conviction:** 0.0–1.0 based on strength of evidence
3. **AI executes:** With agent authority, execution engine sizes to conviction
4. **Heartbeat enforces:** SL/TP placed and maintained automatically

The AI agent is the risk manager — it challenges the thesis, monitors invalidation conditions, and enforces position discipline. The human provides the supply chain insight.

---

## GOLD and SILVER (Main Account)

Both are thesis-driven long-bias positions serving as portfolio diversifiers:

- **GOLD:** Chaos hedge, USD debasement, central bank buying thesis
- **SILVER:** Capital builder, structural undervaluation vs gold, industrial demand

Currently both have stale theses (not updated since early April 2026) and the conviction engine has auto-clamped leverage. These should be refreshed or formally parked.

---

## Portfolio Risk Rules

| Rule | Value |
|------|-------|
| Max single-market exposure | 20% equity (at max conviction) |
| Account halt trigger | 25% drawdown |
| Account liquidation trigger | 40% drawdown |
| Weekend leverage | Max 50% of normal |
| Minimum liquidation cushion | 15% (alert), 10% (critical) |

---

## Capital Allocation Philosophy

Stay fully allocated — do not sit in cash when there's a thesis. The system is designed for:

- **Conviction 0.8+:** Size aggressively when the edge is clear
- **Conviction 0.5–0.8:** Standard position, let it run
- **Conviction < 0.5:** Minimal size or flat

Do not reduce to cash because of uncertainty. Reduce leverage instead. The oil long-only rule means uncertainty = smaller size, not exit.
