---
kind: adr
last_regenerated: 2026-04-09 16:36
adr_file: docs/wiki/decisions/011-two-app-architecture-research-sibling.md
tags:
  - adr
  - decision
---
# ADR-011: Two-App Architecture — Research Sibling with Nautilus Catalog

**Source**: [`docs/wiki/decisions/011-two-app-architecture-research-sibling.md`](../../docs/wiki/decisions/011-two-app-architecture-research-sibling.md)

## Preview

```
# ADR-011: Two-App Architecture — Research Sibling with Nautilus Catalog

**Date:** 2026-04-07
**Status:** Proposed (planning only — no code yet)
**Supersedes:** Aspects of MASTER_PLAN.md Phase 3 sequencing
**Related:** ADR-002 (conviction engine), ADR-009 (embedded agent runtime)

## Context

### What we have today

The trading bot (`agent-cli/`) is a mature, running system: WATCH-tier daemon, Telegram bot, embedded AI agent runtime, conviction engine, on-exchange stops, vault rebalancer, comprehensive test suite (`pytest -x -q`). Architecturally it serves three roles in one process tree: portfolio copilot, research agent, and risk manager.

Storage today is fragmented across six formats:

```

## Human notes

<!-- HUMAN:BEGIN -->
<!-- HUMAN:END -->
