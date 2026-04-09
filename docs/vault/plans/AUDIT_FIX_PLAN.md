---
kind: plan
last_regenerated: 2026-04-09 14:08
plan_file: docs/plans/AUDIT_FIX_PLAN.md
status: unknown
tags:
  - plan
---
# Plan: AUDIT_FIX_PLAN

**Source**: [`docs/plans/AUDIT_FIX_PLAN.md`](../../docs/plans/AUDIT_FIX_PLAN.md)

**Status (detected)**: unknown

## Preview

```
# Audit Fix Plan — 2026-04-07

**Source:** Self-audit performed by the embedded agent (full text in `data/daemon/chat_history.jsonl` lines 218-219, partially in `data/feedback.jsonl` 2026-04-07T03:25 entries).

**Constraint:** The embedded agent runtime is **load-bearing and must keep working**. No changes to `cli/agent_runtime.py`, `agent/AGENT.md`, `agent/SOUL.md`, or auth profiles without explicit per-change sign-off. `cli/telegram_agent.py` may be edited but only at the specific call sites listed below — the rest is frozen.

**Out of scope:** Audit item #1 (auth) is already fixed in commits since the audit ran. Audit items #11/12/13 (daily report, conflict calendar, conviction ladder) are explicitly parked.

## Status (updated 2026-04-07 hardening session)

| Fix | Status | Notes |
|---|---|---|
| F1 self-knowledge | shipped | commit `7fab372` |
| F2 auto-watchlist | shipped | commit `66141de` |
| F3 model selection (dream/compaction) | shipped + revised | commits `0b06e68`, `dcb089b` (Haiku-via-SDK to stop bot wedge) |
| F4 context_harness verification | verified, no fix needed | `_fetch_account_state_for_harness` correctly iterates `for dex in ['', 'xyz']`. F2 closes the SP500 symptom. Vault BTC gap noted separately. |
| F5 LIVE CONTEXT staleness | shipped | commit `66141de` |
| F6 liquidation cushion alerts | shipped | new `liquidation_monitor` iterator in all 3 tiers, alert-only. Closes the early-warning gap above the existing exchange_protection ruin SLs. |
| F7 tool execution verification | shipped | commits `ae921be`, `3365777` |
| F8 model logging | shipped | commit `66141de` |
| F9 chat history resume | re-scoped | bot was already stateless across restarts (loads from disk every message). Added startup diagnostic log line for operator visibility. |
| audit #5 web_search | shipped | commit `ef602a2` |

---

## Root cause analysis

The audit was performed by the agent on itself. What it found is largely *"I don't know what I am"*. Cutting documentation to save tokens removed the agent's self-knowledge. Three audit items collapse into a single root cause, and two more collapse into a second:

**Root cause A — Agent self-knowledge gap:**
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
