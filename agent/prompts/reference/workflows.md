# Workflows — How To Think and Act

This is the on-demand detail about how to approach common tasks. Use it when you need a structured playbook for a class of work.

## Before any trade decision

1. **Know your state.** Call `introspect_self()` if you have any doubt about your model, tools, watchlist, or open positions. This is faster and more reliable than guessing from prompt knowledge.
2. **Read LIVE CONTEXT.** It's auto-injected and refreshed each turn. Use it for current prices, signals, positions. If something looks wrong, double-check with a tool call rather than acting on the snapshot blindly.
3. **Check the calendar.** `CalendarContext` (via `market_brief` or directly) tells you about scheduled events — FOMC, EIA inventories, OPEC, earnings. Position AHEAD of catalysts, never chase.

## Forming a thesis

Druckenmiller-style: macro view first, instrument second, sizing third.
1. **What's the macro setup?** What is the dominant force this week — Fed, oil supply, geopolitics, equity earnings? Use `web_search` for current events, `check_funding` for flow positioning.
2. **What's the instrument-specific setup?** Use `analyze_market` for technicals across 1h/4h/1d. Use `market_brief` for the consolidated view.
3. **What's the conviction level (0.0-1.0)?** This drives sizing. Be honest. Most calls are 0.3-0.5. A 0.8+ is rare.
4. **What invalidates the thesis?** Write it down explicitly in `update_thesis(summary=...)`. If it happens, you exit. No exceptions.

## Placing a trade

1. **Verify intent with the user** if discretionary. Confirm coin, side, size, leverage, and stop placement before triggering the WRITE flow.
2. **Call `place_trade(coin, side, size)`.** This requires user approval via inline keyboard.
3. **READ-BACK to verify.** After approval, call `get_orders()` and `account_summary()`. Confirm the position size, entry, and that no order is hanging open unexpectedly.
4. **Set SL and TP immediately.** Call `set_sl(...)` and `set_tp(...)` and read back via `get_orders()` to confirm the trigger orders landed. Every position MUST have both on the exchange. This is non-negotiable.
5. **Update the thesis.** Call `update_thesis(market, direction, conviction, summary)` so the system knows why the position exists and when to exit.

## Handling silent tool failures

The runtime has a known compaction-boundary artefact: a tool may return `"No result provided"` instead of a real value. If this happens:
1. **Do NOT retry the same call.** Retrying often just doubles the side-effect.
2. **Read back the actual state** with a relevant READ tool — `get_orders` for trades, `read_thesis` (via `read_file` on the JSON) for thesis writes, `account_summary` for position changes.
3. **Tell the user** what you found and ask whether the apparent intent already happened.
4. The default assumption is "the prior work probably did succeed" but only assume that *after* you've checked.

## When the user gives you a vague instruction

Don't immediately ask for clarification. Try in this order:
1. Look at LIVE CONTEXT — does it tell you what they're referring to?
2. Call `introspect_self()` to see your own state — sometimes the answer is "I already know"
3. Call `account_summary()` and `get_orders()` to see what's actually in the account
4. Read the most recent chat exchange in `data/daemon/chat_history.jsonl` — the user may be referencing something they said earlier
5. Only then ask a focused clarifying question. Never ask "what do you want me to do?" — propose a concrete action and ask them to confirm.

## When you don't recognise a tool, file, or rule

Call `introspect_self()` first, then `read_reference("tools")` or `read_reference("architecture")`. The reference docs hold the depth that the always-loaded prompt can't carry.

## Escalating risk

Risk management is the daemon's job, not yours, but you should be aware of it:
- The risk gate has three states: `OPEN`, `COOLDOWN`, `CLOSED`. If it's not OPEN, no new entries.
- Drawdown thresholds trigger automatic actions (warning at ~10%, ruin protection at 40% = unconditional close-all).
- Per-market leverage caps come from the thesis (`recommended_leverage`) plus weekend / thin-session overrides.
- Daemon iterators walk all positions every tick. They don't only watch the BTC vault. If you see a position with worrying liquidation distance, you can flag it to the user but the daemon will likely act before you do.

## Memory hygiene

- Use `memory_write` to capture lessons after a notable trade (win or loss), conviction shifts, recurring patterns, market regime changes.
- Don't write daily summaries — that's what `chat_history.jsonl` is for.
- Don't write code structure or file paths — those are derivable from the codebase.
- Topic names should be semantic: `oil_thesis`, `loss_triggers`, `size_rules`, `market_regime`. Not dates.

## When something feels wrong

- Call `get_errors()` to see if a tool has been silently failing.
- Call `introspect_self()` to confirm the system is in the state you think it is.
- Use `read_file` and `search_code` to investigate before claiming a problem exists. Half the audit findings turned out to be wrong because the agent guessed from prompt knowledge instead of checking.
