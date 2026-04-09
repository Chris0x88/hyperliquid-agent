---
kind: adr
last_regenerated: 2026-04-09 14:08
adr_file: docs/wiki/decisions/005-interface-first.md
tags:
  - adr
  - decision
---
# ADR-005: Interface-First Over Daemon-First

**Source**: [`docs/wiki/decisions/005-interface-first.md`](../../docs/wiki/decisions/005-interface-first.md)

## Preview

```
# ADR-005: Interface-First Over Daemon-First

**Date:** 2026-04-02
**Status:** Accepted

## Context
v1 spent weeks building daemon infrastructure (19 iterators, REFLECT loop, 4-phase plan) before any user-facing interface existed. The result was an invisible system that silently failed for 21 hours during the 2026-04-02 oil loss. Meanwhile, the v2 interface-first rewrite produced a usable Telegram bot with rich AI context in a single day.

## Decision
Prioritize the interface layer. Build rich context injection (positions + technicals + thesis) and AI chat first, then wire daemon automation behind it. The insight: rich AI context makes even cheap/free models useful, and a visible interface exposes failures immediately.

## Consequences
- v2 was built in one morning; v1 daemon took weeks. Interface-first is dramatically faster to validate.
- Failures became visible immediately through Telegram instead of silently accumulating.
- Rich context (3500-token budget with account state, candles, thesis) turned free OpenRouter models into useful trading assistants.
```

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
