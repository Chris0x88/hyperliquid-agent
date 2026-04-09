---
kind: runbook
tags:
  - runbook
  - vault
  - maintenance
---

# Regenerate the Obsidian Vault

## When to run

- After adding or removing an iterator
- After splitting Telegram commands into a new submodule (monolith wedges)
- After adding/modifying agent tools (`TOOL_DEFS` in `cli/agent_tools.py`)
- After adding/changing config files in `data/config/`
- After authoring or archiving a plan in `docs/plans/`
- After writing a new ADR in `docs/wiki/decisions/`
- As a weekly sanity check (check the diff — drift is visible in git)

## How to run

```
cd agent-cli
python scripts/build_vault.py
```

That's it. The script:
- Is **idempotent** — running it twice produces the same output
- **Only touches auto-generated files** (iterators, commands, tools,
  data-stores, plans, adrs folders)
- **Preserves hand-written files** — Home.md, README.md, everything in
  architecture/, components/, runbooks/ — these are never regenerated
- Prints a summary of pages generated per category

Expected output:

```
Building Obsidian vault at /Users/cdi/Developer/HyperLiquid_Bot/agent-cli/docs/vault
  iterators:    36 pages
  commands:     68 pages
  tools:        27 pages
  config files: 22 pages
  plans:        20 pages
  adrs:         14 pages

Total auto-generated: 187 pages (plus 6 index pages).
```

Exact counts vary as the codebase grows.

## What the generator reads

| Source | Output |
|---|---|
| `cli/daemon/iterators/*.py` | `iterators/<name>.md` — one page per iterator class with docstring, kill switch, tier membership, daemon registration status |
| `cli/daemon/tiers.py` | Cross-reference for "which tiers does iterator X belong to" |
| `cli/commands/daemon.py` | Cross-reference for "is iterator X actually registered in daemon_start()" |
| `cli/telegram_bot.py` + `cli/telegram_commands/*.py` | `commands/<name>.md` — one page per `cmd_*` function with docstring, submodule, AI-dependency flag |
| `cli/agent_tools.py` `TOOL_DEFS` | `tools/<name>.md` — one page per tool with description + parameters schema |
| `data/config/*.json` + `*.yaml` | `data-stores/config-<name>.md` — one page per config file with current contents + kill-switch detection |
| `docs/plans/*.md` | `plans/<name>.md` — pointer pages with status detection |
| `docs/wiki/decisions/*.md` | `adrs/<name>.md` — pointer pages |

## Troubleshooting

### "No such file or directory" errors

The script assumes you're running it from `agent-cli/`. Use the full
invocation `cd agent-cli && python scripts/build_vault.py`.

### A page wasn't regenerated

The generator uses `write_if_changed()` — it only touches a file when
the new content differs from the existing content. If nothing changed
in the source, no file is written. This is normal and keeps commit
churn minimal.

### Tools page count is 0

The generator parses `TOOL_DEFS` as an `ast.AnnAssign` (for
`TOOL_DEFS: List[dict] = [...]`). If someone renames `TOOL_DEFS` or
wraps it in a function, the parser won't find it. Check
`cli/agent_tools.py` for a top-level `TOOL_DEFS` declaration.

### Generated pages look wrong after the generator runs

Delete the affected subfolder and regenerate fresh:

```
rm -rf docs/vault/iterators
python scripts/build_vault.py
```

Hand-written files are safe — only auto-gen folders get fully
repopulated.

## Commit policy

Per Chris's 2026-04-09 instruction: the vault **is committed to git**
but **is NOT pushed**. Run the generator, git-add the resulting diff,
commit locally. Don't `git push`.

Regeneration diffs are **valuable** — they're the audit trail of how
the codebase changed. Don't squash or discard them.

## The future: Guardian drift detection

A future Guardian wedge will check the `last_regenerated:` frontmatter
timestamp on index pages and flag the vault as stale if it's older
than 7 days. Not shipped yet — for now it's on Chris's action_queue
as a weekly regeneration nudge.

## See also

- [[Obsidian-Setup]] — recommended Obsidian view settings
- [[Home]] — vault entry point
- `scripts/build_vault.py` — the generator source code
