---
kind: adr
last_regenerated: 2026-04-09 16:05
adr_file: docs/wiki/decisions/013-parallel-equity-field.md
tags:
  - adr
  - decision
---
# ADR-013: Parallel `ctx.total_equity` Field for Alert Reporting

**Source**: [`docs/wiki/decisions/013-parallel-equity-field.md`](../../docs/wiki/decisions/013-parallel-equity-field.md)

## Preview

```
# ADR-013: Parallel `ctx.total_equity` Field for Alert Reporting

**Date:** 2026-04-08
**Status:** Accepted
**Supersedes:** None
**Related:** Build log entry 2026-04-08 (Alert Numbers + Format Postmortem),
ADR-007 (Renderer ABC), `cli/daemon/CLAUDE.md` total_equity definition

## Context

The 2026-04-08 morning Telegram alerts reported equity numbers that did not
match what `/status` showed Chris in the same chat. The status command
(`telegram_bot.py:316 _get_account_values`) sums **native + xyz + spot USDC**
— this is the documented total per `cli/daemon/CLAUDE.md`. But the daemon's
alert path read `ctx.balances["USDC"]`, which has always been native-only
```

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
