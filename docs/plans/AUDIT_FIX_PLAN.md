# Audit Fix Plan — 2026-04-07

**Source:** Self-audit performed by the embedded agent (full text in `data/daemon/chat_history.jsonl` lines 218-219, partially in `data/feedback.jsonl` 2026-04-07T03:25 entries).

**Constraint:** The embedded agent runtime is **load-bearing and must keep working**. No changes to `cli/agent_runtime.py`, `agent/AGENT.md`, `agent/SOUL.md`, or auth profiles without explicit per-change sign-off. `cli/telegram_agent.py` may be edited but only at the specific call sites listed below — the rest is frozen.

**Out of scope:** Audit item #1 (auth) is already fixed in commits since the audit ran. Audit items #11/12/13 (daily report, conflict calendar, conviction ladder) are explicitly parked.

## Status (updated 2026-04-07 hardening session)

| Fix | Status | Notes |
|---|---|---|
| F1 self-knowledge | shipped | commit `7fab372` |
| F2 auto-watchlist | shipped | commit `66141de` |
| F3 model selection (dream/compaction) | shipped + revised | commits `0b06e68`, `dcb089b` (Haiku-via-SDK to stop bot wedge) |
| F4 context_harness verification | verified, no fix needed | `_fetch_account_state_for_harness` correctly iterates `for dex in ['', 'xyz']`. F2 closes the SP500 symptom. Vault BTC gap noted separately. |
| F5 LIVE CONTEXT staleness | shipped | commit `66141de` |
| F6 liquidation cushion alerts | shipped | new `liquidation_monitor` iterator in all 3 tiers, alert-only. Closes the early-warning gap above the existing exchange_protection ruin SLs. |
| F7 tool execution verification | shipped | commits `ae921be`, `3365777` |
| F8 model logging | shipped | commit `66141de` |
| F9 chat history resume | re-scoped | bot was already stateless across restarts (loads from disk every message). Added startup diagnostic log line for operator visibility. |
| audit #5 web_search | shipped | commit `ef602a2` |

---

## Root cause analysis

The audit was performed by the agent on itself. What it found is largely *"I don't know what I am"*. Cutting documentation to save tokens removed the agent's self-knowledge. Three audit items collapse into a single root cause, and two more collapse into a second:

**Root cause A — Agent self-knowledge gap:**
- #4 Memory minimal (agent has no persistent self-knowledge)
- #6 Approved markets (agent doesn't know current state)
- #8 Silent tool failures (agent doesn't know which tools exist or how to verify)
- The audit's overall framing — agent had to guess its own architecture from reading code

**Root cause B — Legacy systems ignore `/models` selection:**
- #4 Memory minimal (dream consolidation is what writes memory, and it's hardcoded to Haiku/OpenRouter)
- #5 Web search broken / OpenRouter 402

---

## Threads

### Thread 1 — Agent self-knowledge (audit #4, #6, #8)

**F1. Restore detailed agent self-docs in token-efficient form + build `introspect_self` tool**
- **(a) Compressed reference docs:** Restore the detail that was cut, but as on-demand reference files the agent reads with `read_file` rather than always-loaded prompt content. Target files:
  - `agent/reference/tools.md` — every tool, its signature, when to use it, common failure modes
  - `agent/reference/architecture.md` — what runs where, what files mean what, how the daemon/bot/agent relate
  - `agent/reference/workflows.md` — how to think about a trade, how to verify execution, how to handle silent tool failures
  - `agent/reference/rules.md` — current approved markets, sizing rules, hard constraints (single source of truth — `AGENT.md` links here, doesn't duplicate)
- **(b) `introspect_self` tool:** New Python function tool, ~50 LOC, returns live state:
  - Currently active model (from `_get_active_model()`)
  - Tools available (introspected from `TOOL_DEFS`)
  - Approved markets (from watchlist)
  - Current open positions
  - Current thesis files and ages
  - Last memory consolidation timestamp
- `AGENT.md` gets a new section: *"When you don't know something about yourself, call `introspect_self()` first, then `read_file('agent/reference/<topic>.md')` for detail."*

**F2. Auto-watchlist on position-open**
- Daemon detects a position in a market not in `data/config/watchlist.json` → silently adds it (Chris's choice: "if I have a position it's approved").
- Implementation: existing position-monitoring iterator already reads positions; one extra check + `watchlist.json` write + log line.
- No Telegram prompt, no inline button.

---

### Thread 2 — Legacy systems must honour model selection (audit #4, #5)

**F3. Route compaction, dream, and fallback through the user's selected model**
- `cli/telegram_agent.py:625` (compaction summary): replace `model_override="anthropic/claude-haiku-4-5"` hardcode → use `_get_active_model()`. If active model is Sonnet/Opus, route via the same CLI binary path that user chat uses (`_call_via_claude_cli`).
- `cli/telegram_agent.py:729` (dream consolidation): same fix.
- `cli/telegram_agent.py:1230` (free-model fallback): the fallback chain is OpenRouter-only by design — leave the chain itself, but only enter it when the active model itself fails, not as a default path for any subsystem.
- Verification: after fix, `dream_consolidation.md` should start populating with real content within one daemon cycle, and memory will begin to grow naturally. No need to manually build memory topics — the dream loop does that once it's not silently failing.

---

### Thread 3 — LIVE CONTEXT correctness (audit #2, #9)

**F4. Verify `common/context_harness.py` reads the correct subaccount**
- Audit found LIVE CONTEXT showed `POSITIONS: none` despite an active SP500 short.
- Read `common/context_harness.py`, trace which subaccount/wallet it queries, compare against the wallet that actually held the SP500 position.
- If wrong: fix the address resolution. If right: investigate why the snapshot didn't include it (possibly a market filter excluding non-watchlist coins — would also be solved by F2).

**F5. Add timestamp + staleness check to LIVE CONTEXT**
- LIVE CONTEXT block gets a `snapshot_age_seconds` field.
- If age > 120s, prepend a `⚠️ STALE` marker so the agent knows not to cite "current price" as fact.
- Pure additive change to the snapshot builder — no change to the agent's prompt structure.

---

### Thread 4 — Execution safety (audit #7, #8)

**F6. Equities/manual-trade liquidation guards**
- The daemon risk iterator currently only fires on the BTC Power Law vault.
- Extend the iterator to walk **all** open positions (not just the vault) and apply liquidation-distance checks.
- Per-market hard leverage caps live in `data/config/risk_caps.json` (new file): `{"BTC": 25, "BRENTOIL": 10, "GOLD": 10, "SILVER": 10, "default": 15}`.
- Alert tier escalates as cushion shrinks: >20% = info, 10-20% = warning, <10% = critical.

**F7. Tool execution verification for trade-mutating tools**
- For `placetrade`, `cancel_order`, `update_thesis`: after the call, perform an explicit read-back (`get_orders` / `account_summary` / `read_thesis`) and compare against intent.
- If mismatch: surface to the agent as `verification_failed` rather than `success`.
- Removes the "assume prior work succeeded" pattern from these specific tools only (not from read-only tools where it's harmless).

---

### Thread 5 — Operational visibility (audit #3, #10)

**F8. Model selection visibility**
- `/show-model` Telegram command — returns current `_get_active_model()` result.
- Every agent turn logs which model handled it (one line at INFO).
- LIVE CONTEXT or daemon heartbeat surfaces the active model so it's never a guess.

**F9. Chat history resume across bot restarts**
- On bot startup, load the last N messages from `data/daemon/chat_history.jsonl` into the active session instead of starting empty.
- Bound by token budget (e.g. last 50 messages or last 24 hours, whichever is smaller).
- If a `[command]` message was the last one, treat it as already-handled (don't re-execute).

---

## Execution order

| # | Fix | Why this order |
|---|---|---|
| 1 | F3 (legacy → selected model) | Smallest diff, unblocks dream/memory immediately, validates the model-routing assumption before anything bigger |
| 2 | F4 (context_harness verify) | Read-only investigation; either confirms a fix is needed or rules it out |
| 3 | F6 (liquidation guards) | Highest real-money risk — must not wait |
| 4 | F1 (self-knowledge: docs + introspect_self) | Largest payoff for the audit's root cause; touches new files only, no risk to running agent |
| 5 | F7 (tool verification) | Prevents the next class of silent failures |
| 6 | F5 (LIVE CONTEXT staleness) | Small additive change |
| 7 | F2 (auto-watchlist) | Closes the SP500-style mismatch |
| 8 | F8 (model visibility) | Quick win once F3 lands |
| 9 | F9 (chat history resume) | Lowest urgency, isolated change |

Each fix gets explicit sign-off from Chris before code is written. Each fix lands as its own commit. After each commit: smoke-test the running bot/daemon (no restart unless required) before moving to the next.

---

## Verification checklist (run after all fixes)

- [ ] Send a Telegram message asking the agent "what tools do you have?" — it should call `introspect_self` and answer from live state, not from prompt-loaded knowledge.
- [ ] Wait for one dream consolidation cycle. Confirm `data/agent_memory/dream_consolidation.md` updates with real content (not a 402 error note).
- [ ] Open a trial position in a non-watchlist market on testnet. Confirm watchlist.json updates within one tick.
- [ ] Confirm LIVE CONTEXT now lists all open positions, with a timestamp and staleness flag.
- [ ] Trigger a `placetrade` on testnet with a deliberately bad parameter. Confirm verification catches it instead of reporting success.
- [ ] Confirm liquidation guard fires on a manually-opened high-leverage testnet position.
- [ ] Restart the bot. Confirm previous conversation context is restored.
- [ ] Run `/show-model` — confirm it returns Sonnet 4.6 (or whatever is active).

---

## Notes parked, not in plan

- **noduslabs.com** thinking-process recording — referenced by Chris but not in scope. Revisit only if F1 doesn't deliver enough self-knowledge.
- **Feedback file truncation** — `/feedback` clipped Chris's audit mid-text in `feedback.jsonl` though full text reached `chat_history.jsonl`. Real bug, separate from audit, parked.
- **MASTER_PLAN doc maintenance** — Phase 3 is shipped, plan is stale, hard-coded "20 tools" count violates `MAINTAINING.md`. Fix during evening alignment after this plan lands, not now.
