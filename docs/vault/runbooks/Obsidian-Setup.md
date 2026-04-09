---
kind: runbook
tags:
  - runbook
  - vault
  - obsidian
---

# Obsidian Setup

Recommended settings for opening this vault in Obsidian and getting
the most value out of the graph view.

## Open the vault

1. Launch Obsidian
2. File → "Open folder as vault" (or "Open another vault" from the
   main menu)
3. Navigate to `agent-cli/docs/vault/` and select it
4. Click "Open"
5. Accept any "trust this vault" prompts — the vault contains only
   markdown, no code execution

## Recommended settings

### Appearance

- **Theme**: Dark or Light, your preference
- **Font size**: whatever you read comfortably
- **Enable readable line length**: ON (makes long narrative pages
  comfortable)

### Files & Links

- **Use [[Wikilinks]]**: ✅ **MUST BE ON** — the vault uses
  `[[wiki-link]]` syntax throughout. If this is off, all links break.
- **Default location for new attachments**: doesn't matter (you'll
  probably never add attachments to this vault)
- **Excluded files**: leave empty (the .obsidian/ directory is
  gitignored so it won't appear)

### Graph view (`Ctrl+G` / `Cmd+G`)

The graph view is the whole reason this vault exists. Recommended:

- **Filters** → exclude tag: `#kind/index` if you want the graph to
  focus on content pages rather than index pages
- **Groups**: create color groups based on folder:
  - `path:iterators` → green
  - `path:commands` → blue
  - `path:tools` → purple
  - `path:components` → orange
  - `path:architecture` → yellow
  - `path:plans` → gray
  - `path:adrs` → red
- **Display** → show arrows: ON (useful to see which pages link to which)
- **Forces** → adjust until clusters form naturally
  - Center force: 0.5
  - Repel force: 5
  - Link force: 1
  - Link distance: 100-200

### Suggested starting layout

- **Left sidebar**: File explorer + Graph view (in a split pane)
- **Right sidebar**: Outline + Tag pane + Backlinks
- **Main pane**: Whatever page you're reading

This gives you the graph on the left for navigation, the page you're
reading in the center, and backlinks on the right so you can see
what links INTO the current page.

## Useful keyboard shortcuts

| Shortcut | Effect |
|---|---|
| `Ctrl+P` / `Cmd+P` | Command palette — search all commands |
| `Ctrl+O` / `Cmd+O` | Quick switcher — jump to any page by name |
| `Ctrl+G` / `Cmd+G` | Open graph view |
| `Ctrl+Shift+F` / `Cmd+Shift+F` | Search all files |
| `Ctrl+Click` on a wiki-link | Open in new pane |
| `Ctrl+Shift+Click` | Open in new tab |

## Plugins (optional, not required)

The vault works with stock Obsidian. If you want to extend it:

- **Dataview** — lets you query frontmatter dynamically. Would be
  useful for live queries like "show all iterators with
  `kill_switch=true` that are registered in WATCH tier." Not required
  — the vault's static index pages already cover the common cases.
- **Mermaid** — already built into Obsidian core. The Home.md + some
  architecture pages use mermaid fenced blocks for diagrams. Should
  render automatically.
- **Git** — community plugin that auto-commits the vault on a schedule.
  **DO NOT install this on this vault** — we want regeneration diffs
  to be committed deliberately by Chris, not silently.

## What NOT to do

- **Don't enable auto-sync to iCloud / Dropbox / etc.** The vault
  is committed to git locally (not pushed). External sync would
  duplicate the work + risk conflicts.
- **Don't enable Obsidian Sync** (their paid service). Same reason.
- **Don't edit auto-generated pages** in Obsidian unless the page
  has a `<!-- HUMAN:BEGIN -->...<!-- HUMAN:END -->` region. The next
  regeneration will overwrite anything outside those markers. (Today
  the generator writes whole pages; HUMAN markers are reserved for
  a future wedge that preserves them across regeneration.)
- **Don't push the vault to a public remote**. Chris's trading
  infrastructure is private. The `.gitignore` allows the vault in
  local commits but the user's git workflow keeps it local.

## Troubleshooting

### "Can't find file" errors on wiki-links

Check that "Use [[Wikilinks]]" is ON in Settings → Files & Links. If
that's not it, the generator may have emitted a link to a page that
doesn't exist — file a note in the action_queue and I'll fix the
generator.

### Graph view is empty

- The vault has ~190 pages. If the graph is empty, Obsidian hasn't
  finished indexing yet — wait a few seconds.
- Make sure you opened the right folder (`docs/vault/`, not
  `docs/`)
- Try "Reload app without saving" from the command palette

### Pages show as broken after regeneration

Run `git status` in `agent-cli/` — the generator may have created
new files the folder isn't tracking yet. `git add docs/vault/` and
commit.

## See also

- [[Regenerate-Vault]] — how to keep the vault fresh
- [[Home]] — vault entry point
- [[README]] — vault overview
