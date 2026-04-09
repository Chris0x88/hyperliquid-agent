---
kind: runbook
title: Drift Detection via Vault Regeneration
tags:
  - runbook
  - vault
  - drift
  - alignment
---

# Drift Detection via Vault Regeneration

**Purpose:** turn the obsidian vault into the system's primary
structural-drift detector. Every session, regenerate the vault; the
git diff under `docs/vault/` IS the drift report.

**When to run:** at the start or end of every meaningful session, as
part of the `/alignment` ritual.

**Why this exists:** Guardian is disabled (hook loop re-emitted stale
narrative). The vault generator reads the *authoritative sources*
— `cli/daemon/iterators/*.py`, `cli/daemon/tiers.py`,
`cli/telegram_bot.py`, `cli/telegram_commands/*`, `cli/agent_tools.py`,
`data/config/*.json`, `docs/plans/*`, `docs/wiki/decisions/*` — and
emits frontmatter + descriptions that can't drift from the code
because they ARE the code. Any diff between two regen runs is real
structural change.

## The drift-detection protocol

```bash
cd /Users/cdi/Developer/HyperLiquid_Bot/agent-cli
.venv/bin/python scripts/build_vault.py
git diff --stat docs/vault/
git diff docs/vault/ | less   # inspect the diff
```

### How to read the diff

1. **All frontmatter `last_regenerated:` bumps** — ignore, they're
   timestamp noise. `git diff` shows them on every run.
2. **Tier frontmatter additions or removals** (e.g.
   `tiers: [rebalance]` → `tiers: [watch, rebalance]`) — an iterator
   was moved between tiers in `tiers.py`. If that's intentional,
   commit it; if not, investigate the source change.
3. **New pages under `iterators/`, `commands/`, `tools/`,
   `configs/`** — something was added to the codebase. Check the
   source file for the new item.
4. **Deleted pages** — something was removed. Check git log for the
   removal commit.
5. **Description body changes** — the source docstring of an
   iterator/command/tool was edited. Compare to the intent of the
   edit; if it's a genuine refactor, commit; if it's a drift from
   intent, fix the source.

### When the diff is empty

Empty diff is a success state. It means the code structure has not
changed since the last regeneration. Commit nothing and move on.

### When the diff is huge

A big diff after a significant code burst (e.g. 68 commits in one
day) is expected. The right reaction is to commit it as part of an
`alignment:` commit. See the 2026-04-09 alignment burst (commit
`42eca28`) for a worked example.

## Hand-written pages the generator does NOT touch

The generator preserves these locations entirely:

- `docs/vault/Home.md`
- `docs/vault/README.md`
- `docs/vault/architecture/*.md` — hand-written cohesion /
  architecture pages. This is where you put pages that need to
  survive regeneration, like `Cohesion-Map.md` and
  `Time-Loop-Interweaving.md`.
- `docs/vault/runbooks/*.md` — including this file.
- `docs/vault/components/*.md` — wiki component pages.

You can add new hand-written pages freely under any of these
directories without risk of the next regeneration overwriting them.

## Limits of structural drift detection

The vault catches structural drift (iterator added, tier changed,
command renamed) but cannot catch:

- **Behavioural drift** — the source of a function changes in a way
  that doesn't affect its name, signature, or docstring. Unit tests
  catch this, not the vault.
- **Time-loop drift** — cadence changes in a config file. The vault
  regenerates the config page with the new cadence, but if the
  downstream consumer expects the old cadence, the vault alone
  doesn't flag the mismatch. See `architecture/Time-Loop-Interweaving.md`
  for the hand-written layer that captures these relationships.
- **Cross-process writer drift** — Telegram and daemon touch the
  same files; the vault shows both iterators but not the race. See
  `architecture/Cohesion-Map.md` for the hand-written parallel-writer
  map.

These are precisely why `VAULT_AS_AUDITOR.md` (in `docs/plans/`)
proposes a set of **health pages** that extend the auto-generator
with lightweight queries beyond structural extraction.

## Related

- `docs/plans/VAULT_AS_AUDITOR.md` — the proposal to extend the
  auto-generator with health pages (untested, kill_switches,
  stale_data, orphans, plan_ships, parallel_writers,
  cadence_interweaving).
- `docs/plans/TIMER_LOOP_AUDIT.md` — the Phase C audit that motivated
  the time-loop-interweaving layer.
- `docs/plans/COHESION_HARDENING_LIST.md` — the Phase D backlog that
  several health pages would surface automatically once implemented.
- `docs/vault/architecture/Cohesion-Map.md` — hand-written cohesion
  map of parallel writers + cross-process contracts.
- `docs/vault/architecture/Time-Loop-Interweaving.md` — hand-written
  time-loop interweaving reference.
