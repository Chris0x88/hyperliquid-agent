# HyperLiquid Bot — Obsidian Vault

This directory is an **Obsidian vault** — a navigable, visualisable map
of the entire codebase. Every major thing (iterators, commands, agent
tools, configs, plans, ADRs) gets a page. Everything is cross-linked
via `[[wiki-links]]` so Obsidian's graph view shows real relationships.

## Quick start

1. **Install Obsidian** (if you haven't): https://obsidian.md — free,
   local, no account needed.
2. **Open this folder as a vault**:
   - Launch Obsidian
   - Click "Open folder as vault"
   - Navigate to `agent-cli/docs/vault/` and select it
   - Click "Open"
3. **Open the graph view**: press `Ctrl+G` (or `Cmd+G` on Mac), or
   click the graph icon in the left sidebar.
4. **Start at the home page**: open [[Home]] from the file tree on the left.

## What's in here

| Folder | What it contains | Auto-gen? |
|---|---|---|
| (root) | [[Home]], [[README]] | hand-written |
| `architecture/` | Overview, package map, tier ladder, authority model, data flow | hand-written |
| `components/` | Deep dives on subsystems (lesson layer, entry critic, etc.) | mostly hand-written |
| `iterators/` | One page per daemon iterator | ✅ auto-gen from `cli/daemon/iterators/*.py` |
| `commands/` | One page per Telegram command | ✅ auto-gen from `cli/telegram_bot.py` + `cli/telegram_commands/*.py` |
| `tools/` | One page per agent tool | ✅ auto-gen from `cli/agent_tools.py` `TOOL_DEFS` |
| `data-stores/` | One page per config file + key data stores | ✅ auto-gen from `data/config/*` |
| `plans/` | Pointer pages for each plan in `docs/plans/` | ✅ auto-gen |
| `adrs/` | Pointer pages for each ADR in `docs/wiki/decisions/` | ✅ auto-gen |
| `runbooks/` | How-tos: regenerate the vault, set up Obsidian, restore memory.db | hand-written |

## How this stays fresh

Run the generator after any significant change to the codebase:

```
cd agent-cli && python scripts/build_vault.py
```

It's **idempotent** — running it twice produces the same output. It
**only touches auto-generated files**; anything you hand-edit in
`Home.md`, `architecture/*.md`, or `runbooks/*.md` is preserved. Inside
auto-generated pages, `<!-- HUMAN:BEGIN -->...<!-- HUMAN:END -->`
regions are reserved for future hand-augmentation (v1 generator writes
the whole file; v2 will preserve these regions across regenerations).

See [[Regenerate-Vault]] for the full regeneration runbook.

## Git policy

- The vault is **checked into git** (per Chris's 2026-04-09 instruction)
- The vault is **NOT pushed** — it lives on Chris's local machine only
- `.obsidian/` (Obsidian's per-user view settings) is **gitignored**;
  your graph view preferences are personal
- Regeneration diffs ARE committed — they're the audit trail of how the
  codebase changed

## The philosophy

Per NORTH_STAR P2: **reality first, docs second**. The vault is
auto-generated from code precisely so the structural map can't drift
from the actual codebase. When iterators are added, commands are
extracted, tools are clamped per P10, ADRs are written — re-run the
generator and the vault updates. No hand-maintenance of structural
facts.

Narrative content (how the lesson layer works, why we picked
NautilusTrader in ADR-011, what the dumb-bot philosophy means) lives
in hand-written pages and in `docs/wiki/`. The vault *links to* those,
it doesn't duplicate them.

## What this vault is NOT

- Not a replacement for `docs/wiki/` (that's where narrative prose
  lives: ADRs, build-log, component deep-dives)
- Not a replacement for `docs/plans/` (that's where active/parked/
  archived plans live)
- Not a runtime artefact — no code reads from the vault
- Not Obsidian-specific in content — it's all markdown files with
  `[[wiki-link]]` syntax, works in any markdown reader, but Obsidian
  gives you the graph visualisation the user specifically wanted

## Start here

→ [[Home]] — entry point with table of contents and architecture diagram
→ [[Regenerate-Vault]] — how to keep the vault fresh
