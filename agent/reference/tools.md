# Your Tools — Reference

This is the on-demand detail for every tool you can call. Use it when the always-loaded prompt doesn't give you enough to act safely. The list of names is also discoverable live via `introspect_self()`.

## How tools work in your runtime

- **READ tools** auto-execute. No approval needed. Use them freely to gather information.
- **WRITE tools** require user approval via inline keyboard before they actually run. The user sees a prompt and clicks Approve / Reject. You will not get a result back until they decide.
- A tool result of `"No result provided"` is a compaction-boundary artifact, NOT a real failure. Do not retry the same call. Verify the actual state with a read tool (e.g. `get_orders`, `account_summary`) before assuming anything.
- Tool results are capped at ~12000 characters; very large outputs are truncated.

## Trading & market data (READ)

### `market_brief(market)`
Compact market brief: price, technicals, position, thesis, and memory for one market. Best first call when forming a view on a single instrument. Markets use names like `xyz:BRENTOIL`, `BTC`, `xyz:GOLD`. The `xyz:` prefix is required for commodity perps on the xyz clearinghouse.

### `account_summary()`
Total equity across native HL + xyz dex + spot. Open positions across all venues with size, entry, uPnL, leverage, liquidation price. Use this when the user asks "what's my account doing" or before sizing a trade.

### `live_price(coin)`
Single mid price for a market. Cheap, use it for spot checks. For depth/spread, use `market_brief`.

### `analyze_market(market)`
Multi-timeframe technical analysis: 1h/4h/1d trend, RSI, BB, OBV, signal verdict. Returns a structured signal block. Use after `market_brief` when you want to dig into the chart.

### `get_orders()`
Open orders across all venues — limit orders, stop-losses, take-profits. Use this to verify whether a `place_trade` / `set_sl` / `set_tp` actually landed (read-back verification — see workflows.md).

### `get_signals()`
Strategy signal queue: any pending entry/exit signals from the daemon's strategy iterators. Distinct from `analyze_market` which is your own ad-hoc analysis.

### `check_funding(coin)`
Funding rate, open interest, annualised funding cost. Critical for hold-cost calculation on perps, especially when planning multi-day positions.

### `trade_journal(limit)`
Recent realised trades with PnL, entry/exit, duration. Use this for retrospective analysis ("how did the last 5 oil trades go?").

### `get_errors(limit)`
Recent agent errors from the diagnostics log. Use this when something feels off — a tool may have been silently failing.

### `get_feedback(limit)`
Recent user feedback submitted via `/feedback`. Use this when the user references prior feedback or you want to know what they've been complaining about.

## Trading actions (WRITE — need approval)

### `place_trade(coin, side, size)`
IOC market order. Crosses the spread to guarantee a fill. After approval and execution, the return string includes the actual fill price and oid. **You should always read back with `get_orders` and `account_summary` after placing a trade to confirm exposure changed as intended.**

- `coin`: market identifier, e.g. `"BTC"`, `"xyz:BRENTOIL"`, `"xyz:SP500"`
- `side`: `"buy"` (long) or `"sell"` (short)
- `size`: number of contracts/coins (not USD)

### `close_position(coin, side, size)`
Exit an open position. The `side` here is the *closing* side (opposite of position direction). For a long, pass `side="sell"`. For a short, pass `side="buy"`.

### `set_sl(coin, side, size, trigger_px)` / `set_tp(coin, side, size, trigger_px)`
Place exchange-side stop-loss / take-profit trigger orders. Every position MUST have both SL and TP on the exchange — this is a hard rule (see rules.md). After approval, read back with `get_orders` to confirm the trigger landed.

### `update_thesis(market, direction, conviction, summary)`
Write or update the thesis JSON for a market. Conviction is 0.0-1.0. Direction is `"long"`, `"short"`, or `"flat"`. Summary is your written reasoning. The thesis drives execution sizing — be deliberate.

## Codebase tools (READ)

### `read_file(path)`
Read a file relative to project root. Use this when investigating an error, looking up a config, or verifying behaviour.

### `search_code(pattern, path)`
Grep across the codebase. Pattern is a regex. Use for finding callers of a function, checking which iterator does what, etc.

### `list_files(pattern)`
Glob a directory. Useful when you don't know exact filenames.

### `edit_file(path, old_str, new_str)` (WRITE)
Edit-in-place by exact string replacement. `old_str` must be unique in the file. Creates a `.bak` backup automatically. Use for small, targeted edits — not for large rewrites.

### `run_bash(command)` (WRITE)
Run a shell command in the project directory with a 30s timeout. Powerful but heavy — prefer the dedicated tools above when they apply.

## Knowledge tools (READ + WRITE)

### `web_search(query, max_results)`
Real web search via DuckDuckGo (ddgs package). Use for current events, oil news, geopolitical context, anything outside your training cutoff. Returns title + URL + snippet for each result.

### `memory_read(topic)`
Read agent memory. Pass `"index"` (or omit) for the index, or a topic name like `"oil_thesis"`. Returns content or a list of available topics if the requested one doesn't exist.

### `memory_write(topic, content)` (WRITE)
Save a new memory topic or overwrite an existing one. Use this to capture conviction shifts, lessons from a trade, recurring patterns. Memory survives across sessions.

### `search_lessons(query, market, direction, signal_source, lesson_type, outcome, include_rejected, limit)`
BM25-ranked search over your trade lesson corpus. Every closed position gets a verbatim post-mortem written to `data/memory/memory.db` (table `lessons` + FTS5 virtual table `lessons_fts`) — this tool is how you recall them.

**When to call this.** Before opening a new position, if you want to drill into a specific pattern: *"Have I traded BRENTOIL longs during weekend sessions before? What happened?"* The top-ranked lesson summaries are automatically injected into your prompt at decision time, but this tool lets you ask targeted questions that the prompt injection won't cover.

**How ranking works.** Non-empty `query` runs FTS5 MATCH over `summary + body_full + tags` and ranks by BM25 (lower bm25_score = more relevant). Empty query returns most-recent lessons by `trade_closed_at`. Filters stack — all filters are AND-combined.

- `query` — keyword search, optional. FTS5 operators are escaped, you can pass raw user text.
- `market` — e.g. `"xyz:BRENTOIL"`, `"BTC"`, `"xyz:GOLD"`. Exact match.
- `direction` — `"long"`, `"short"`, or `"flat"`.
- `signal_source` — `"thesis_driven"`, `"radar"`, `"pulse_signal"`, `"pulse_immediate"`, `"manual"`, or any source string that appears in the corpus.
- `lesson_type` — one of `"sizing"`, `"entry_timing"`, `"exit_quality"`, `"thesis_invalidation"`, `"funding_carry"`, `"catalyst_timing"`, `"pattern_recognition"`.
- `outcome` — `"win"`, `"loss"`, `"breakeven"`, `"scratched"`.
- `include_rejected` — default `false`. Lessons Chris rejected (`reviewed_by_chris = -1`) are hidden from ranking unless you pass `true`. Use `true` for anti-pattern queries like *"what kinds of setups did Chris tell me NOT to take?"*.
- `limit` — default 5. Keep small — each result is a summary line plus metadata.

Returns one line per hit: `#id YYYY-MM-DD market direction (signal_source, lesson_type) → outcome ROE% [review_flag]` plus the summary. Follow up with `get_lesson(id)` when you need the verbatim body.

### `get_lesson(id)`
Fetch one lesson by id and return its full verbatim body — the complete post-mortem including thesis snapshot at open time, entry reasoning, journal retrospective, autoresearch eval window, news context at open, and your structured analysis from when you wrote it. This is the "tell me everything" tool; `search_lessons` is the "find me candidates" tool.

Use this after `search_lessons` when a ranked hit looks relevant. The body includes every piece of verbatim source material that was available when you wrote the lesson — nothing is summarised away. If you only need the one-line summary, it's already in the `search_lessons` output; don't call `get_lesson` to re-fetch something you already have.

## Self-knowledge tools (READ)

### `introspect_self()`
**Call this whenever you are unsure about your own state.** Returns:
- Currently active model (e.g. `anthropic/claude-sonnet-4-6`)
- All tools you have available, with WRITE markers
- Current watchlist (the *real* approved-markets list — not what `AGENT.md` says)
- Open positions across all venues
- Thesis files with ages
- Recent memory state including last dream consolidation
- Daemon health (running / stale pid)

Prefer this over guessing from prompt knowledge. Your prompt is compressed for token cost; live state is the truth.

### `read_reference(topic)`
Read one of your detailed reference docs (`tools`, `architecture`, `workflows`, `rules`). Use when you need depth that the always-loaded prompt does not carry.
