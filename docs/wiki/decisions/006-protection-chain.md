# ADR-006: Composable Protection Chain

**Date:** 2026-04-04
**Status:** Accepted

## Context
Risk management needed multiple independent safety checks (drawdown, consecutive losses, daily loss, ruin prevention) that could be added or removed without touching each other. Freqtrade's protection plugins and LEAN's risk management composability were proven patterns.

## Decision
Build a composable `ProtectionChain` in `parent/risk_manager.py`. Each protection is an independent class. The chain runs ALL protections, worst gate wins, all triggered reasons are collected. A 3-state `RiskGate` machine (OPEN / COOLDOWN / CLOSED) controls trading. Four protections ship by default: MaxDrawdown (warn 15%, halt 25%), StoplossGuard (3 consecutive), DailyLoss (5%), and Ruin (40% kills everything).

## Consequences
- Adding a new protection = one class + append to chain list. No existing code changes.
- Worst-gate-wins means protections cannot override each other --- the most conservative always applies.
- COOLDOWN auto-expires after 30 minutes, preventing permanent lockout from transient conditions.
- The chain is wired into the daemon via `cli/daemon/iterators/risk.py` and runs every tick.
- State persists via `to_dict()`/`from_dict()` across daemon restarts.
