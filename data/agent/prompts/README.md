# Agent Prompt Templates

This directory contains pi-mono-style prompt templates. Each `.md` file is a
reusable operator prompt that the bot expands on demand.

## Usage

In Telegram, type `/silvercheck` and the bot looks up `silvercheck.md`,
substitutes `{{args}}` with any text you typed after the command, then sends
the expanded body to the AI agent exactly as if you had typed it yourself.

In the Dashboard drawer, autocomplete activates when your input starts with `/`.
Type `/<name>` and the drawer shows an "expand" preview banner before sending.

## Variable substitution

Templates support `{{var}}` placeholders:

- `{{args}}` — automatically populated with the raw text after the slash command.
  Example: `/silvercheck ahead of FOMC` → `{{args}}` becomes `ahead of FOMC`.
- Any `{{other_var}}` — reserved for future named substitutions.

## Adding a new template

1. Create `<name>.md` in this directory.
2. Start the first non-blank line with a plain-text description — that line
   becomes the description shown by `/templates`.
3. Include `{{args}}` anywhere natural so operators can add context.
4. The name must match `[a-z0-9][a-z0-9_-]*` and must NOT be a built-in
   command name (status, stop, steer, etc.).

Alternatively, use the `/save <name>` command in Telegram to capture your last
message as a new template automatically.

## Starter templates

| Name | Purpose |
|------|---------|
| `silvercheck` | Silver position audit — technicals, funding, sweep risk, thesis |
| `btccheck` | BTC position audit — technicals, vault context, macro overlay |
| `portfoliosweep` | Full portfolio audit — cross-asset risk, catalysts, overnight threats |
| `exitcheck` | Per-position exit condition proposals — RSI, funding, cushion thresholds |

## Dispatch order (no regressions)

1. HANDLERS dict is checked first — all built-in commands always win.
2. If no handler matched and the message starts with `/`, this directory is checked.
3. If no template found, falls through to "unknown command" / AI routing as before.
