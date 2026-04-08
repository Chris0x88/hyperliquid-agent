# Guardian Angel — Phase Status

**Source spec:** `docs/superpowers/specs/2026-04-09-guardian-angel-design.md`
**Implementation plan:** `docs/superpowers/plans/2026-04-09-guardian-angel.md`
**ADR:** `docs/wiki/decisions/014-guardian-system.md`

## Status

| Phase | Task | Status | Notes |
|---|---|---|---|
| 1 | Task 1 — Package scaffold | shipped | |
| 1 | Task 2 — Cartographer imports | shipped | |
| 1 | Task 3 — Cartographer Telegram | shipped | |
| 1 | Task 4 — Cartographer iterators + inventory | shipped | |
| 1 | Task 5 — SessionStart hook (read-only) | shipped | |
| 1 | Task 6 — Guide stub + /guide | shipped | |
| 2 | Task 7 — Drift orphans + parallel tracks | shipped | |
| 2 | Task 8 — Drift Telegram + plan mismatches + report | shipped | |
| 3 | Task 9 — Gate skeleton + PreToolUse hook | shipped | no rules active yet |
| 3 | Task 10 — Gate rule telegram-completeness | shipped | |
| 3 | Task 11 — Gate rules parallel-track + recent-delete | shipped | |
| 3 | Task 12 — Gate rule stale-adr-guard | shipped | |
| 4 | Task 13 — Friction log reader + patterns | shipped | |
| 4 | Task 14 — Friction report | shipped | |
| 5 | Task 15 — sweep.py orchestrator | shipped | |
| 5 | Task 16 — SessionStart hook sub-agent dispatch | shipped | |
| 5 | Task 17 — /guardian slash command | shipped | |
| 6 | Task 18 — Guide finalize | shipped | |
| 6 | Task 19 — ADR-014 + wiki + cross-links | shipped | |

Commit hashes are in git log (search for `guardian`).

## Kill status

All kill switches default to ENABLED. See `guardian/guide.md` for the full table.

## Open questions (from spec §12)

- **Q1 (surface style):** Claude surfaces findings naturally in its first response (default chosen).
- **Q2 (sweep inputs):** Cartographer uses both snapshot diff and `git log --since` for drift context.
- **Q3 (slash commands):** `/guide` + `/guardian` shipped; no other commands planned.

## Kill switches ops

To silence Guardian entirely for one session: `GUARDIAN_ENABLED=0 claude`
To disable a single gate rule: e.g., `GUARDIAN_RULE_PARALLEL_TRACK=0`
To reset Guardian state: `rm -rf agent-cli/guardian/state/*` (next sweep rebuilds)
