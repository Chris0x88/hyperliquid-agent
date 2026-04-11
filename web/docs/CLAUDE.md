# web/docs/ — Astro Starlight Documentation Site

## Running the Docs

```bash
# From agent-cli/web/docs/
bun run serve        # Build + serve on http://127.0.0.1:4321/
```

That's it. One command. `bun run serve` calls `astro build` then `bun serve.ts`.

## CRITICAL: DO NOT use `astro dev` or `astro preview`

**Astro's dev server and preview server are broken for this site.** They use
client-side SPA routing that serves the index page shell for every URL — sidebar
navigation doesn't work, links appear dead, and every route shows the homepage.
The built static HTML files are correct; it's the Astro dev/preview server that
fails to serve them properly.

**Always use `bun run serve`** which:
1. Runs `astro build` to generate static HTML in `dist/`
2. Serves `dist/` with `serve.ts` (a simple Bun static file server)

If you need to iterate on content, kill the server, edit files, run `bun run serve`
again. The build takes ~2 seconds.

## Content Structure

All doc pages live in `src/content/docs/` as Markdown with YAML frontmatter:

```
src/content/docs/
├── index.mdx                          # Landing page (hero layout)
├── getting-started/                   # Setup, overview, quick start
├── architecture/                      # System design, data flow, tiers
├── components/                        # Daemon, telegram, agent, conviction, etc.
├── trading/                           # Markets, oil knowledge, sizing, portfolio
└── operations/                        # Runbook, security, tier operations
```

Sidebar is auto-generated from directories in `astro.config.mjs`.

## Adding a New Page

1. Create `src/content/docs/<section>/<slug>.md`
2. Add YAML frontmatter: `title` and `description`
3. Run `bun run serve` — it auto-appears in the sidebar

## Editing Existing Pages

- Content source of truth is the wiki at `agent-cli/docs/wiki/`
- Doc pages should be accurate reflections of the wiki + codebase
- When the codebase changes, update the relevant doc page
- Never reference files that don't exist — verify paths against the actual `data/` directory

## Tech Stack

- **Astro Starlight** v0.38+ — static site generator with built-in search (Pagefind)
- **Bun** — runtime, package manager, and static server
- Build output: `dist/` (static HTML, CSS, JS)
- Port: 4321 (local only)

## Common Pitfalls (Learned the Hard Way)

1. **`astro dev` / `astro preview`** — DO NOT USE. See above.
2. **Stale `.astro/` cache** — If build acts weird, `rm -rf .astro dist` and rebuild.
3. **Frontmatter errors** — Missing `title` in frontmatter causes silent build failures.
4. **`trailingSlash: 'always'`** is set in astro.config.mjs — all URLs end with `/`.
