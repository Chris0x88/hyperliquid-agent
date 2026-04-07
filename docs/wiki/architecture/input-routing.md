# Input Routing — Slash Commands vs Buttons vs Natural Language

> Status: living doc. Last touched 2026-04-07. Owner: telegram bot.
> Source of truth for how a single user message becomes a tool call,
> a button tap, or an AI turn. If this disagrees with `cli/telegram_bot.py`,
> the code wins and this gets fixed.

## Why this exists

Telegram is a single text input box, but the bot has THREE behaviourally
distinct paths behind it. They look the same to the user typing, and they
are very different inside the program. Today's `/brief` bug (a stale bot
process couldn't dispatch `/brief`, so the message fell through to the AI
chat path and produced a hallucinated approval flow with a "disgusting
format") was a direct consequence of this boundary not being drawn
anywhere. So: it's drawn now.

## The three paths

```
                            ┌──────────────────────────────┐
                            │   Telegram inbound update    │
                            └──────────────┬───────────────┘
                                           │
                       ┌───────────────────┼───────────────────┐
                       │                   │                   │
                  callback_query?       message              other
                       │                   │
                       ▼                   ▼
              ┌────────────────┐    ┌────────────────┐
              │ BUTTON path    │    │ TEXT path      │
              │ (callback id)  │    │ (msg.text)     │
              └────────┬───────┘    └────────┬───────┘
                       │                     │
                       ▼                     │
        ┌──────────────────────┐             │
        │ _handle_menu_callback│             │
        │  • mn:* → menu       │             │
        │  • model:* → model   │             │
        │  • approve:*/        │             │
        │    reject:* → tool   │             │
        │    approval         │              │
        └──────────────────────┘             │
                                             ▼
                                  ┌──────────────────────┐
                                  │ pending input?       │  yes
                                  │ (e.g. SL prompt)     │ ───────────┐
                                  └──────────┬───────────┘            │
                                             │ no                     ▼
                                             ▼              ┌─────────────────┐
                                  ┌──────────────────────┐  │ resume the       │
                                  │ starts with "/"?     │  │ pending dialog   │
                                  └──────────┬───────────┘  │ (SL/TP/close…)  │
                                             │              └─────────────────┘
                            ┌────────────────┼────────────────┐
                            │ yes                              │ no
                            ▼                                  ▼
                ┌───────────────────────┐         ┌───────────────────────┐
                │ SLASH path            │         │ NATURAL LANGUAGE path │
                │ HANDLERS dict lookup  │         │ → telegram_agent      │
                │ first token only      │         │ → agent_runtime       │
                │                       │         │ → Anthropic/OpenRouter│
                │ FIXED CODE only.      │         │ AI lives here. Tools, │
                │ NO AI calls.          │         │ memory, streaming,    │
                │ AI variants must end  │         │ approval keyboards.   │
                │ in `ai` (e.g.         │         │                       │
                │ /briefai).            │         │                       │
                └──────────┬────────────┘         └──────────┬────────────┘
                           │                                 │
                           ▼                                 ▼
                ┌──────────────────────┐         ┌────────────────────────┐
                │ cmd_<name>(token,    │         │ tool calls → READ      │
                │   chat_id, args)     │         │   auto-execute / WRITE │
                │ Direct tg_send /     │         │   → inline approve     │
                │ sendDocument.        │         │   buttons ◄────────────┤
                │ No model in the loop.│         │ Streamed model output  │
                └──────────────────────┘         │ → tg_send (markdown)   │
                                                 └────────────────────────┘
```

## Path 1 — BUTTON (callback_query)

**Trigger:** user taps an inline keyboard button. Telegram sends a
`callback_query` update, NOT a `message`.

**Dispatcher:** `_handle_menu_callback()` in `cli/telegram_bot.py`. Routes
by callback `data` prefix:
- `mn:*` — interactive menu navigation (the `/menu` terminal)
- `model:*` — model picker callbacks from `/models`
- `approve:*` / `reject:*` — tool-approval responses for WRITE tools queued
  by the agent (close, sl, tp, etc.). The pending action is stored in
  `agent_tools` pending-action store and executed only after `approve:*` is
  received.

**Properties:**
- Always fixed code. The button payload is structured data, never free text.
- The user CANNOT approve a write tool by typing the word "approve" in
  the text box. That's a NATURAL LANGUAGE message and the agent will
  hallucinate at it. **This is a UX papercut today** — see "Known
  papercuts" below.

## Path 2 — Pending input (in-flight dialog)

**Trigger:** user previously tapped a button that opened a multi-step
dialog (`/sl`, `/tp`, `/close`, `/addmarket`, etc.) and the bot is waiting
for the user to type a value.

**Dispatcher:** `_handle_pending_input()`. Checked BEFORE slash and BEFORE
NL routing. Returns `True` if it consumed the message; if it returns
`False`, the message falls through to the slash/NL check.

**Properties:**
- Fixed code, deterministic.
- Pending state lives in a per-chat dict in memory. A bot restart drops it
  — restarting mid-dialog will look like the bot "forgot" the prompt and
  the next message will fall through to NL.

## Path 3 — SLASH (fixed code)

**Trigger:** message starts with `/`.

**Dispatcher:** look up the first whitespace-separated token in the
`HANDLERS` dict. If found, call `cmd_<name>(token, chat_id, args)`. If
not found, **fall through to the NATURAL LANGUAGE path** (this is the bug
we hit today — a stale bot didn't have `/brief` registered, so the
message went to the AI).

**Rules (from CLAUDE.md "Slash Commands vs AI"):**
1. Slash commands MUST be deterministic. No AI calls. No AI-seeded text.
   No thesis-file content that injects narrative.
2. If a command's output is even partially AI-influenced, the command
   name MUST end in `ai`. The convention is enforced by code review and
   by the checklist in CLAUDE.md.
3. Aliases for the same handler are explicit dict entries; both `/cmd`
   and bare `cmd` forms are registered so the dispatcher matches when
   Telegram strips the slash on group mentions.

**Examples on either side of the line:**

| Command | Path | Notes |
|---------|------|-------|
| `/status` | SLASH | Pure HL API + formatting |
| `/position` | SLASH | Pure HL API + risk formula |
| `/market oil` | SLASH | Pure technicals + funding + OI |
| `/brief` | SLASH | Mechanical PDF — fixed code only |
| `/briefai` | SLASH (ai-suffixed) | Same as `/brief` plus thesis + catalysts (AI-seeded content) |
| `/chartoil 72` | SLASH | matplotlib render of HL candles |
| `/sl <coin> <price>` | SLASH → BUTTON | Slash queues a confirm button; the actual write goes through approval |
| `/models` | SLASH | Just opens the model picker keyboard |

## Path 4 — NATURAL LANGUAGE (AI agent)

**Trigger:** any text message that:
- isn't a callback query (Path 1)
- isn't pending dialog input (Path 2)
- doesn't match a HANDLERS entry (Path 3 miss)

**Dispatcher:** `telegram_agent.handle_message()` →
`agent_runtime.run_turn()` → Anthropic/OpenRouter API call with the agent
system prompt and the 25 agent tools.

**Properties:**
- AI lives ONLY here.
- Has access to all 25 agent tools. READ tools auto-execute (account_summary,
  check_funding, market_brief, web_search, etc.). WRITE tools (close,
  sl, tp) queue an inline approve/reject keyboard — that drops the user
  back into Path 1 to confirm.
- Streamed model output is sent as Telegram messages with Markdown
  formatting. If the model produces malformed markdown the message looks
  ugly — that's the "disgusting format" we saw today when `/brief` wrongly
  fell into this path.
- Memory + chat history are loaded fresh per turn from
  `data/daemon/chat_history.jsonl` and `data/agent_memory/`.

## How today's `/brief` bug fits this picture

1. User typed `/brief`.
2. Bot was running stale code from 16:03 — its HANDLERS dict did NOT yet
   contain `/brief` (that handler shipped at 19:25).
3. Path 3 missed → fell through to Path 4.
4. The agent received "/brief" as natural language. With no system
   instruction explaining what `/brief` means, the model improvised: it
   produced a freeform "should I generate a brief? approve?" response.
5. User saw a fake approval prompt (the model hallucinating Path 1) and
   ugly markdown (the model's formatting, not a PDF).

The bug was a **process gap** (bot wasn't restarted after the new
handler shipped), not a code bug. The fix is just to restart, and the
preventative is the Telegram command checklist in CLAUDE.md plus this
diagram.

## Known papercuts (architecture-mapping session input)

These are NOT bugs but they ARE seams the architecture map should pin
down so we can decide whether to clean them up:

1. **Typing "Approve" in text never works.** Tool approval is always Path
   1 (callback_query). If the user types the word, it falls into Path 4
   and the agent hallucinates at it. Options: have the agent recognise
   "approve"/"reject"/"yes"/"no" as approval verbs and forward to the
   pending-action store; OR send a hint message reminding the user to tap
   the button; OR add explicit `/approve` and `/reject` slash commands as
   aliases. Pick one.

2. **Pending dialogs die on bot restart.** If the bot restarts mid-`/sl`
   prompt, the in-memory pending state is lost. The next typed message
   falls through to NL. Options: persist pending dialogs to disk; or
   shorten the time window so a stale prompt is harmless; or just
   document it.

3. **Slash dispatch is silent on miss.** A typo like `/breif` falls
   through to Path 4 with no warning. The agent will try to interpret
   it. Options: add a "did you mean…?" handler that catches `/<unknown>`
   tokens and suggests close matches before forwarding to NL.

4. **Fixed code vs AI suffix is a convention, not enforced.** Nothing in
   the code stops a future `cmd_foo` from importing the agent runtime
   and calling Anthropic. The rule lives in CLAUDE.md and code review.
   Options: lint rule, or move all slash command modules into a
   `cli/commands/slash/` package that has no imports from `cli.telegram_agent`
   or `cli.agent_runtime`.

5. **Three different writers can place trigger orders.** Heartbeat (in
   WATCH), exchange_protection (in REBALANCE), execution_engine
   (delegated). The tier doc explains the rules; the architecture map
   should diagram who owns which slot under each tier. (See
   `docs/wiki/operations/tiers.md`.)

## Where this is implemented

| Concern | File |
|---------|------|
| Update polling + path classification | `cli/telegram_bot.py` `run()` and `_process_update()` |
| Button dispatcher | `cli/telegram_bot.py` `_handle_menu_callback()` |
| Pending dialog dispatcher | `cli/telegram_bot.py` `_handle_pending_input()` |
| Slash HANDLERS dict | `cli/telegram_bot.py` near line 2915 |
| AI agent entry | `cli/telegram_agent.py` |
| Agent runtime (tools, streaming, compaction) | `cli/agent_runtime.py` |
| Tool definitions + approval store | `cli/agent_tools.py` |
| Slash/AI convention rule | `CLAUDE.md` "Slash Commands vs AI" |
| Telegram command checklist | `CLAUDE.md` "Slash Commands vs AI" item 3 |
