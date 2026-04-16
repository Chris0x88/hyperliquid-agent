# Morning Brief — Standing Template

**Trigger:** Chris says "morning brief" / "brief me" / "/brief" / "what's the state" at session start.

**Output:** A structured situational report Chris can act on in 60 seconds.

**Owner:** Claude Code (this session). Not the in-app Telegram agent.

---

## What I run, in order

### 1. Account state — what you have, what's open
- Read `data/daemon/state.json` for last daemon tick
- Read native + xyz clearinghouse equity via `scripts/scheduled_check.py` output, or directly with the same fetcher pattern in `cli/telegram_agent.py:_fetch_account_state_for_harness`
- Show: total equity, native vs xyz vs spot, every open position with size/entry/uPnL/leverage/liq distance, every working order
- Flag anything where liquidation distance < 15% as a red item

### 2. Δ vs last session
- Compare current equity against the last brief (stored in `data/brief/last_brief_state.json`)
- Compute realised + unrealised PnL since last brief
- Flag any position that opened or closed without a brief in between

### 3. Overnight catalysts
- Check `data/daemon/catalyst_events.json` if present
- Web search via `WebSearch` tool for: "{date} oil news", "{date} FOMC", "{date} OPEC", "{date} geopolitical Hormuz"
- Filter to material moves only — not noise

### 4. Oil-specific intel
- Check the active BRENTOIL/CL thesis: `data/thesis/xyz_brentoil_state.json`
- Read funding via the in-app `check_funding` pattern (tools.py)
- Calendar: WTI rollover dates, EIA inventories (Wed 10:30am ET = Thu 1:30am AEST), OPEC meetings, Hormuz status
- Spread / backwardation read if available

### 5. Thesis review
- For every market with an active thesis (`data/thesis/*.json`):
  - Direction, conviction, age, last evaluation
  - Is the thesis being confirmed or invalidated by current price action?
  - Any thesis older than 7 days needs explicit refresh-or-retire decision

### 6. The "today's plays" call
- 0-3 concrete recommendations max — not a wishlist
- For each: market, side, size guidance (% of equity), trigger condition, stop placement, take-profit target, kill criteria
- If nothing is set up, say "no plays today, hold"

### 7. Save state for next brief
- Write current equity + position snapshot to `data/brief/last_brief_state.json`
- Append a one-line note to `data/strategies/brief_log.md`

---

## Output format Chris sees

```
═══════════════════════════════════════
MORNING BRIEF — {date} {time AEST}
═══════════════════════════════════════

📊 ACCOUNT
  Equity: $XXX (Δ +$YY since {last_brief_time})
  Native: $XX | xyz: $XX | Spot: $XX
  Open: N positions

📍 POSITIONS
  • {coin} {SIDE} {size} @ {entry} | uPnL ±$X | {Lx} | liq dist {Y}%
    SL ✓ TP ✓     [or ❌ MISSING — fix immediately]

⚠️ RISK FLAGS
  - {item} — {action}
  (or "none — within tolerance")

🌍 OVERNIGHT
  - {catalyst 1}
  - {catalyst 2}

🛢️ OIL INTEL
  Front month: {price} | spread: {value} | backwardation: {state}
  Funding: {rate}/h ({annualised}%)
  Next event: {EIA / OPEC / rollover} in {hours}
  Thesis: {direction} {conviction} — {still valid? / needs refresh}

📋 THESIS REVIEW
  • BRENTOIL — {state}
  • BTC — {state}
  • {others}

🎯 TODAY'S PLAYS (max 3)
  1. {market}: {action} — trigger {condition}, stop {price}, target {price}
     Why: {one-line thesis}
  2. ...
  (or "no plays — hold and reassess at next brief")

❓ DECISIONS NEEDED FROM YOU
  - {explicit ask 1}
  - {explicit ask 2}
═══════════════════════════════════════
```

---

## How Chris invokes it

Three ways, all equivalent:

1. **Type "morning brief"** in this chat — I run the full template
2. **Type "/brief"** — same thing, shorter
3. **Type "quick brief"** — abbreviated version, skips sections 4-5, just sections 1-3 + 6

I do NOT run this without being asked. Chris's day, Chris's call.

## What I do NOT do in a brief

- Place trades (he places them after the brief, manually or via the in-app bot)
- Modify thesis files (I propose changes; he approves)
- Long historical analysis (separate request — "do a deep dive on X")
- Speculation about catalysts beyond ~24 hours
- Filling in numbers I don't have. If a data source is unavailable, I say "DATA MISSING: {what} — fetch from {where} or skip"

## Maintenance

- The template lives here. Edits go here.
- The state file `data/brief/last_brief_state.json` is private to the brief — don't reuse for other purposes
- If a section is consistently empty for >5 briefs, drop it from the template
- If a section is consistently the same value, that's a sign to automate it via the daemon, not to keep reporting it
