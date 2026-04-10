---
kind: adr
last_regenerated: 2026-04-09 16:36
adr_file: docs/wiki/decisions/004-menu-system.md
tags:
  - adr
  - decision
---
# ADR-004: Interactive Button Menu (v3.2)

**Source**: [`docs/wiki/decisions/004-menu-system.md`](../../docs/wiki/decisions/004-menu-system.md)

## Preview

```
# ADR-004: Interactive Button Menu (v3.2)

**Date:** 2026-04-04
**Status:** Accepted

## Context
The Telegram bot had 31 slash commands, but discoverability was poor. Users had to remember command names and arguments. Chat flooding from sequential command outputs made conversations hard to follow.

## Decision
Add an interactive button menu system. `/menu` or `/start` opens a button grid that adapts to current positions. Callbacks use the `mn:` prefix, routed by `_handle_menu_callback()`. Navigation edits messages in-place instead of sending new ones. The menu tree: position buttons (with close/SL/TP/chart/technicals), orders, PnL, watchlist (coin grid to market detail), and tools (status/health/diag/models/authority/memory). Every button has a slash command fallback.

## Consequences
- Discoverability solved: users navigate by tapping instead of memorizing commands.
- In-place message editing eliminates chat flooding during exploration.
- The `mn:` callback prefix cleanly separates menu routing from approval and model-selection callbacks.
```

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
