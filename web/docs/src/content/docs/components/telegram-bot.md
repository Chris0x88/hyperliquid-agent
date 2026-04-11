---
title: Telegram Bot
description: Complete command reference and architecture for the Telegram dashboard — slash commands are deterministic code, free text routes to the AI agent.
---

## Architecture

The Telegram bot (`cli/telegram_bot.py`) is a long-lived polling process that serves as the primary user interface.

- **Poll interval:** 2 seconds
- **Single-instance:** PID file + pgrep scan; kills any existing process on startup
- **Command dispatch:** `HANDLERS` dict maps `/command` strings to `cmd_*` functions
- **Callback routing:** Inline keyboard callbacks via `model:`, `approve:`, `reject:`, `mn:` prefixes
- **AI routing:** Any message not matching a slash command delegates to `cli/telegram_agent.py`

---

## The Slash vs AI Boundary

This rule is absolute:

- **Slash commands are fixed code.** A `/command` is deterministic — pure Python, no AI calls, no AI-seeded text. The output of a slash command never depends on AI or AI-influenced content.
- **Commands that use AI MUST end in `ai`.** Examples: `/briefai`, `/brutalreviewai`, `/oilbotreviewai`, `/lessonauthorai`. No exceptions.
- **Free-text messages = AI path.** Anything the user types that does NOT start with `/` is routed to the AI agent. That is where AI lives.

---

## Complete Command Reference

### Quick Data

| Command | Aliases | Description |
|---------|---------|-------------|
| `/status` | | Account overview: equity, positions, margin |
| `/price <coin>` | | Current price for a market |
| `/orders` | | Open orders list |
| `/pnl` | | Profit & loss summary |
| `/position <coin>` | `/pos` | Position detail for a specific market |
| `/market <coin>` | `/m` | Full technical signal engine: multi-timeframe confluence, RSI divergence, exhaustion detection, volume flow |
| `/watchlist` | `/w` | Current watchlist markets |
| `/powerlaw` | | Bitcoin power-law model overlay |

### Charts

| Command | Aliases | Description |
|---------|---------|-------------|
| `/chart <coin> <hours>` | | Price chart for any market with configurable timeframe |
| `/chartoil` | | Brent oil chart (dynamic shortcut) |
| `/chartbtc` | | Bitcoin chart (dynamic shortcut) |
| `/chartgold` | | Gold chart (dynamic shortcut) |
| `/chartwti` | | WTI crude chart (dynamic shortcut) |

### Trade Actions

All trade actions require inline-keyboard confirmation before execution.

| Command | Aliases | Description | Requires Approval |
|---------|---------|-------------|:-:|
| `/close <coin>` | | Market close position | Yes |
| `/sl <coin> <price>` | | Set stop-loss trigger | Yes |
| `/tp <coin> <price>` | | Set take-profit trigger | Yes |

### Briefs

| Command | Aliases | Description |
|---------|---------|-------------|
| `/brief` | `/b` | Mechanical PDF brief (no AI) |
| `/briefai` | `/bai` | AI-enhanced PDF brief with commentary |

### Thesis & Conviction

| Command | Aliases | Description |
|---------|---------|-------------|
| `/thesis` | | Current thesis files with conviction levels |
| `/signals` | `/sig` | Technical signal summary across watchlist |
| `/readiness` | | Pre-trade readiness checklist |
| `/activate` | | Activate execution for a market |

### Authority

| Command | Aliases | Description |
|---------|---------|-------------|
| `/delegate <coin>` | | Delegate trade authority to the agent for a market |
| `/reclaim <coin>` | | Reclaim authority from the agent |
| `/authority` | `/auth` | Show current authority assignments |

### News & Supply

| Command | Aliases | Description |
|---------|---------|-------------|
| `/news` | | Latest news headlines |
| `/catalysts` | | Upcoming catalyst events |
| `/supply` | | Oil supply data |
| `/disruptions` | | Active supply disruptions |
| `/disrupt <args>` | | Log a new supply disruption |
| `/disrupt-update <id> <field=val>` | | Update a disruption record |

### Oil Bot-Pattern

| Command | Aliases | Description |
|---------|---------|-------------|
| `/oilbot` | | Oil Bot-Pattern system status |
| `/oilbotjournal [N]` | | Recent oil bot journal entries |
| `/oilbotreviewai [N]` | | AI review of oil bot journal entries |
| `/heatmap [coin]` | | Signal heatmap |
| `/botpatterns [coin] [N]` | | Detected bot patterns |

### Self-Tune

| Command | Aliases | Description |
|---------|---------|-------------|
| `/selftune` | | Self-tune system status |
| `/selftuneproposals` | | Pending parameter proposals |
| `/selftuneapprove <id>` | | Approve a self-tune proposal |
| `/selftunereject <id>` | | Reject a self-tune proposal |

### Pattern Library

| Command | Aliases | Description |
|---------|---------|-------------|
| `/patterncatalog` | | Browse the pattern library |
| `/patternpromote <id>` | | Promote a pattern to production |
| `/patternreject <id>` | | Reject a pattern |

### Shadow Eval

| Command | Aliases | Description |
|---------|---------|-------------|
| `/shadoweval [id]` | | Shadow evaluation results |
| `/sim` | | Simulation status |

### Lessons

| Command | Aliases | Description |
|---------|---------|-------------|
| `/lessons [N]` | | Recent trade lessons |
| `/lesson <id>` | | View a specific lesson |
| `/lesson approve\|reject\|unreview <id>` | | Moderate a lesson |
| `/lessonsearch <query>` | | Full-text search over lesson corpus |
| `/lessonauthorai [N\|all]` | | AI-authored lessons from recent trades |

### Reviews

| Command | Aliases | Description |
|---------|---------|-------------|
| `/brutalreviewai` | | AI brutal honesty review of recent performance |
| `/critique [N\|instrument]` | | Trade critique |

### System

| Command | Aliases | Description |
|---------|---------|-------------|
| `/health` | `/h` | Daemon health, iterator status, error budget |
| `/diag` | | Full diagnostics dump |
| `/restart` | | Restart daemon |
| `/models` | `/model` | AI model routing configuration |
| `/memory` | `/mem` | Agent memory stats |
| `/chathistory` | `/ch` | Recent chat history with the AI agent |
| `/rebalancer` | | Rebalancer status |
| `/rebalance` | | Trigger rebalance |
| `/adaptlog` | | Adaptation log |
| `/nudge` | | Nudge the daemon |

### Meta

| Command | Aliases | Description |
|---------|---------|-------------|
| `/help` | | Command list by category |
| `/guide` | `/g` | User guide with usage examples |
| `/commands` | | Raw command list |
| `/menu` | | Interactive button menu |

### Feedback

| Command | Aliases | Description |
|---------|---------|-------------|
| `/bug` | | Report a bug |
| `/todo` | | View open todos |
| `/feedback` | `/fb` | Submit feedback |
| `/feedback_resolve` | `/fbr` | Resolve a feedback item |

### Watchlist Management

| Command | Aliases | Description |
|---------|---------|-------------|
| `/addmarket` | | Add a market to the watchlist |
| `/removemarket` | | Remove a market from the watchlist |

---

## Interactive Menu System

`/menu` or `/start` opens a button grid that adapts to current positions:

```
/menu
+-- [Position buttons] --> detail --> [Close] [SL] [TP] [Chart] [Technicals]
+-- [Orders] [PnL]
+-- [Watchlist] --> coin grid --> market detail
+-- [Tools] --> Status / Health / Diag / Models / Authority / Memory
```

Menu navigation edits messages in-place (no chat flooding). Every button has a slash command equivalent.

---

## Write Command Approval Flow

Commands that modify exchange state require confirmation via inline keyboard:

1. User sends `/close BRENTOIL`
2. Bot displays position details with **Confirm** / **Cancel** buttons
3. Only on **Confirm** does the bot execute the order
4. Result is reported back with fill details

This applies to `/close`, `/sl`, and `/tp`.

---

## Slash Command Checklist

When adding any new command, ALL of these surfaces must be updated:

1. `cli/telegram_bot.py` — add `def cmd_<name>(token, chat_id, args)` handler
2. `HANDLERS` dict — register BOTH the `/cmd` and bare `cmd` forms (and any aliases)
3. `_set_telegram_commands()` list — add `{"command": ..., "description": ...}` for the Telegram menu UI
4. `cmd_help()` — add one-line entry under the right section
5. `cmd_guide()` — add to the relevant section if user-facing
6. If AI-dependent, command name MUST end in `ai`
7. Tests in `tests/test_telegram_bot.py` for non-trivial behavior

Missing any surface is a bug.
