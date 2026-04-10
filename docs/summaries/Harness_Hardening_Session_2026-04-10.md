# Session Summary: Hardening the Autonomous Trading Harness
**Date:** 2026-04-10
**Objective:** Transition from "Prompt-Heavy Reasoning" to "Harness-First Determinism" to eliminate LLM hallucinations in trading decisions.

## 1. The Core Problem: "Old Agentic" Instability
Historically, the agent relied on a 17-step "Oil Short Consideration" checklist inside `AGENT.md`. This forced the LLM to perform complex financial logic, math, and cross-reference check-offs in its head.
- **Consequence:** During model fallbacks or high-pressure cycles, the LLM would ignore its own checklist and provide irrational advice (e.g., "buy high, sell low").
- **Solution:** Move the "brains" of the evaluation out of the prompt and into a deterministic Python harness.

---

## 2. Key Architectural Changes

### A. Deterministic Trade Evaluator (`cli/trade_evaluator.py`)
We created a dedicated Python module that encodes all trading logic gates as hard code. It checks:
- **Kill Switches:** `short_legs_enabled` and other config flags.
- **Drawdown Brakes:** Daily/Weekly/Monthly loss limits from `oil_botpattern_state.json`.
- **Bot Patterns:** Validates pattern classification and confidence (e.g., must be `bot_driven_overextension` with >0.7 confidence).
- **Macro Catalysts:** Scans `catalysts.jsonl` for high-severity events in the next 24 hours.
- **Calendar Alerts:** Scans all calendar JSON files for rollovers (WTI/Brent) and macro deadlines (CPI, OPEC).

### B. Context Injection Pipeline (`cli/telegram_agent.py`)
The results from the `trade_evaluator` are now injected directly into the `LIVE CONTEXT` of every message.
- **[SYSTEM EVALUATION]:** Tells the model exactly if a setup is a `GO` or `NO_GO` before it even starts thinking.
- **[CALENDAR ALERTS]:** Surfaces imminent rollovers (e.g., "BRENT ROLL BZK6 last trading in 2d").
- **Outcome:** The LLM is effectively "straight-jacketed" by the system's deterministic truth. It acts as a UI/Interpreter rather than a decision-maker.

---

## 3. Toolset Expansion & Hardening

### A. New Rich Data Tools
We added three new tools to `agent_tools.py` to bridge the gap between "collected data" and "agent awareness":
1.  **`get_calendar`**: Surfaces upcoming macro/rollover events from JSON files.
2.  **`get_research`**: Allows the agent to read your deep-research notes (e.g., the 5-day phased WTI roll analysis) using a fuzzy-search "query" mechanism.
3.  **`get_technicals`**: Provides pre-computed RSI, Bollinger Bands, and ATR derived directly from `CandleCache`, removing the need for the LLM to process raw candle arrays.

### B. Semantic Triage Router
Modified `handle_ai_message` to use a lightweight `llm_triage` call. This classifies the user message (TRADING, OPERATIONS, CODING, CHAT) and restricts the toolset provided to the model.

### C. Multi-Model Orchestration (Haiku Steering)
We formalized a "Model Tiering" strategy within the harness to optimize for cost, latency, and rate limits:
- **Haiku (Triage):** Used for the initial intent classification (`llm_triage`). Its high speed and low cost make it ideal for this frequent, single-turn classification task.
- **Haiku (Tool Iterations):** During the tool-calling loop, if the active model is Sonnet or Opus, the harness **overrides** subsequent calls to use Haiku. Haiku is highly competent at reading file contents and searching code; using it for these intermediate steps preserves expensive Sonnet/Opus tokens for the final synthesis.
- **Sonnet/Opus (Final Response):** Reserved for the final turn of the conversation to synthesize all tool results into a high-quality human response.

---

## 4. UX & Reliability Fixes

### A. Continuous Typing Indicator
Added a `TypingIndicator` daemon thread that sends a "Typing..." action to Telegram every 4 seconds until the AI response is delivered.
- **Why:** Telegram clears the typing status after 5 seconds. Since direct Anthropic SDK calls are non-streaming and can take 15-30s during tool loops, the bot previously looked "dead."

### B. Indentation & Syntax Hardening
Fixed a critical syntax error in `telegram_agent.py` where a mismatched `try/except` block caused an immediate crash upon receiving messages. The file was validated against the Python compiler before final deployment.

---

## 5. Summary of Files Modified
| File | Change Type | Purpose |
| :--- | :--- | :--- |
| `agent/AGENT.md` | [MODIFY] | Removed checklists; redirected model to trust `[SYSTEM EVALUATION]`. |
| `cli/trade_evaluator.py` | [NEW] | The new deterministic "Brain" of the trading system. |
| `cli/agent_tools.py` | [MODIFY] | Added `get_calendar`, `get_research`, `get_technicals`. |
| `cli/telegram_agent.py` | [MODIFY] | Added Typing Indicator, Semantic Triage, and Context Injection. |
| `cli/agent_runtime.py` | [MODIFY] | Updated context assembly logic. |

---

## 6. Verification
All changes were verified via:
1.  **Compilation Check:** Using `py_compile` on all modified files.
2.  **Direct Testing:** A `scratch.py` test script confirmed that `build_system_evaluations()` successfully catches the WTI roll and CPI data.
3.  **Bot Restart:** The telegram daemon was restarted and is currently processing messages with the new harness and typing indicator.

> [!IMPORTANT]
> The bot is now "Harness-First." If it gives advice that seems off, check the `[SYSTEM EVALUATION]` in the logs. The LLM is now strictly bound by the Python code's decisions.
