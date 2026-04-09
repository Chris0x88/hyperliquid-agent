---
kind: plan
last_regenerated: 2026-04-09 16:36
plan_file: docs/plans/VAULT_AS_AUDITOR.md
status: proposal. No code shipped in Phase E.
tags:
  - plan
---
# Plan: VAULT_AS_AUDITOR

**Source**: [`docs/plans/VAULT_AS_AUDITOR.md`](../../docs/plans/VAULT_AS_AUDITOR.md)

**Status (detected)**: proposal. No code shipped in Phase E.

## Preview

```
# Vault-as-Auditor — Proposal

> **Phase E output** of `SYSTEM_REVIEW_HARDENING_PLAN.md` §8.
> **Status:** proposal. No code shipped in Phase E.
> **Companion pages shipped:**
> `docs/vault/runbooks/Drift-Detection.md`,
> `docs/vault/architecture/Cohesion-Map.md`,
> `docs/vault/architecture/Time-Loop-Interweaving.md`.

## Vision

The obsidian vault becomes the system's **first-class audit
surface**. The auto-generator already reads the authoritative sources
(iterators, commands, tools, tiers, configs, plans, ADRs). Every
regeneration produces a file with frontmatter + body. The **diff
between two regenerations IS the structural change surface**. No
other tool is needed — the vault already knows what changed.

The user's framing, verbatim:
> "I really do believe the obsidian vault gives eyes into how well
> linked and cohesive our app actually is. If it's a total mess, it
> will show in the vault where the key points we have to work on
> are. Especially if we consider the element of time loops in that
> process too so we track processes that interweave and not just
> waterfall code structure alone."

Phase E operationalises this in two layers:

1. **Drift-detection layer** (already working — just needs a runbook):
   regenerate + `git diff docs/vault/` = drift report.
```

## Human notes

<!-- HUMAN:BEGIN -->
_Add hand-written context here — open questions, known gaps, links to related plans, etc._
<!-- HUMAN:END -->
