---
title: Portfolio Strategy
description: Account structure, BTC Power Law vault, oil thesis strategy, metals positions, and portfolio-level risk rules.
---

## Account Structure

Two separate accounts on HyperLiquid, each with distinct strategies:

| Account | Markets | Strategy | Automation |
|---------|---------|----------|------------|
| **Main account** | BRENTOIL, GOLD, SILVER | Thesis-driven, conviction-sized | Daemon enforces SL/TP, conviction engine sizes positions |
| **BTC vault** | BTC | Power Law rebalancing | Fully automated via `scripts/run_vault_rebalancer.py` |

The xyz margin for BRENTOIL, GOLD, and SILVER sits inside the unified balance on the main account.

---

## BTC Power Law (Vault)

The vault runs an automated rebalancing strategy based on BTC's long-term power law price trend:

- **Target allocation:** Calculated from power law regression
- **Rebalance cadence:** Hourly check, trade if more than 5% off target
- **Direction:** Long only (buy below power law, reduce above)
- **Script:** `scripts/run_vault_rebalancer.py`

The BTC strategy is fully automated and does not require thesis files. It runs independently of the main account and its conviction engine.

---

## Oil Strategy (Main Account)

The oil position is thesis-driven with human petroleum engineering judgment driving entries:

1. **Write thesis:** Create or update `data/thesis/BRENTOIL.json` with current view
2. **Set conviction:** 0.0 to 1.0 based on strength of evidence
3. **Conviction engine sizes:** Position sized to conviction bands automatically
4. **Daemon enforces:** SL/TP placed and maintained on every tick

The AI agent is the risk manager — it challenges the thesis, monitors invalidation conditions, and enforces position discipline. The human provides the supply chain insight. The thesis should be challenged robustly, but reality wins: make money, not follow the thesis blindly.

Long or neutral only on oil. Never short (see [Oil Knowledge](/trading/oil-knowledge/) for the exception).

---

## GOLD and SILVER (Main Account)

Both are thesis-driven long-bias positions serving as portfolio diversifiers:

- **GOLD:** Chaos hedge, USD debasement, central bank buying thesis
- **SILVER:** Capital builder, structural undervaluation vs gold, industrial demand

Each requires a thesis file (`data/thesis/GOLD.json`, `data/thesis/SILVER.json`) with a conviction score. The conviction engine applies the same sizing bands as oil.

---

## Portfolio Risk Rules

| Rule | Value |
|------|-------|
| Max single-market exposure | 20% equity (at max conviction) |
| Account halt trigger | 25% drawdown — halt all new entries |
| Account liquidation trigger | 40% drawdown — close ALL positions |
| Weekend leverage | Max 50% of normal |
| Minimum liquidation cushion | 15% (alert), 10% (critical) |

---

## Capital Allocation Philosophy

Stay fully allocated — do not sit in cash when there is a thesis. The system is designed for:

- **Conviction 0.8+:** Size aggressively when the edge is clear
- **Conviction 0.5-0.8:** Standard position, let it run
- **Conviction below 0.5:** Minimal size or flat

Do not reduce to cash because of uncertainty. Reduce leverage instead. The oil long-only rule means uncertainty equals smaller size, not exit.
