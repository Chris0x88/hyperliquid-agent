# ADR-013: Parallel `ctx.total_equity` Field for Alert Reporting

**Date:** 2026-04-08
**Status:** Accepted
**Supersedes:** None
**Related:** Build log entry 2026-04-08 (Alert Numbers + Format Postmortem),
ADR-007 (Renderer ABC), `cli/daemon/CLAUDE.md` total_equity definition

## Context

The 2026-04-08 morning Telegram alerts reported equity numbers that did not
match what `/status` showed Chris in the same chat. The status command
(`telegram_bot.py:316 _get_account_values`) sums **native + xyz + spot USDC**
— this is the documented total per `cli/daemon/CLAUDE.md`. But the daemon's
alert path read `ctx.balances["USDC"]`, which has always been native-only
because `connector.py:52-59` only reads from `get_account_state()` (native HL
clearinghouse).

Two consumer classes both read `ctx.balances["USDC"]`:

| Consumer | What it does with the value | Sensitivity |
|---|---|---|
| **Alert reporting** — `iterators/telegram.py` periodic block, `iterators/journal.py` `account_equity` field | Display number to operator | Must match `/status` |
| **Sizing math** — `iterators/execution_engine.py:169` `target_notional`, `iterators/profit_lock.py:77` baseline, `iterators/autoresearch.py:211` percentage | Compute order size, profit lock thresholds, current allocation % | Already operating on native-only and not flagged |

The alert consumers were the source of the user complaint. The sizing
consumers were not flagged and have been running without observable issues
on the native-only value.

## Decision

Add a parallel field `ctx.total_equity: float` to `TickContext`. The
`ConnectorIterator` populates it on every tick by summing
`get_account_state()["account_value"]` (native) +
`get_account_state()["spot_usdc"]` (spot) + `get_xyz_state()["marginSummary"]
["accountValue"]` (xyz). All three sources are already fetched on every
tick — no extra API round-trips.

`ctx.balances["USDC"]` semantic is **unchanged** — it remains native-only.

Alert iterators (`telegram.py`, `journal.py`, eventually `account_collector.py`
once it migrates) read `ctx.total_equity` first and fall back to
`ctx.balances["USDC"]` only when total_equity is 0 (tick 0 / mock mode).

Sizing iterators continue to read `ctx.balances["USDC"]` and are not
touched by this change.

## Alternatives Considered

### 1. Change `ctx.balances["USDC"]` semantic to total

**Why rejected:** changing the semantic in place would force `execution_engine`
sizing math, `profit_lock` baseline tracking, and `autoresearch` percentage
calc to all migrate simultaneously. None of those were flagged in the user
complaint, so a sizing change would be an unintended side effect of an alert
fix. CLAUDE.md rule 2 (minimal bug fixes) explicitly prohibits scope creep
beyond the bug being fixed.

If migration of those consumers is desired in the future, it can land as its
own ADR with its own test sweep — and at that point the parallel field
becomes the deprecation signal: once everyone reads `ctx.total_equity`, the
legacy `ctx.balances["USDC"]` can be removed.

### 2. Have alert iterators query the HL API directly

**Why rejected:** every alert iterator would replicate the same three-source
fetch, with three additional API round-trips per tick. The connector
iterator already makes those calls — duplicating them would multiply API
load and create three different versions of the "what's total equity"
question.

### 3. Inject from `account_collector` instead of `connector`

**Why rejected:** `account_collector` runs on a 5-minute snapshot cadence
(`SNAPSHOT_INTERVAL_S = 300`). Between snapshots it would inject a stale
total. `connector` runs every tick, so the value is always fresh.

The `account_collector` snapshot DOES compute the same total via
`_build_snapshot()` and writes it to disk — that's how `/brief` and the AI
agent read account state. But that's a slower, snapshot-oriented path; the
in-memory `ctx.total_equity` is the per-tick path.

## Consequences

### Positive

- Alerts now report the same equity number as `/status`, eliminating the
  user-visible "wrong numbers" complaint.
- Sizing math is untouched — no risk of accidentally changing position
  sizing as a side effect of an alert fix.
- The parallel field is a clear deprecation signal for the eventual
  migration of sizing consumers (see "Future" below).
- Zero new API calls — uses data already fetched on every tick.

### Negative

- Two fields with overlapping semantics is a small ongoing maintenance
  cost. Future contributors must understand which to read for which
  purpose.
- The `ctx.balances["USDC"]` name is now misleading — it sounds like total
  USDC but is actually native-perps-only. Mitigated by the long comment
  block in `context.py` that explains the situation.

### Future

Once a separate review confirms it is safe to migrate the sizing consumers
to total equity:

1. Update `execution_engine._process_market` to read `ctx.total_equity`
   (with the same fallback to `ctx.balances["USDC"]` for tick 0)
2. Update `profit_lock.tick` baseline to read `ctx.total_equity`
3. Update `autoresearch` percentage calc to read `ctx.total_equity`
4. Add tests confirming the new sizing matches the old sizing for
   accounts with no xyz/spot exposure (regression baseline)
5. Add tests confirming the new sizing scales correctly when xyz/spot
   are present
6. Once all consumers are migrated, remove `ctx.balances["USDC"]`
   population from connector.py and write a follow-up ADR documenting
   the cleanup

This is **not** scheduled — it requires a deliberate review of whether
total equity is actually the right sizing input for accounts with mixed
native/xyz/spot exposure, including how cross-margin behaves when xyz
positions are present.

## Verification

- New field documented in `cli/daemon/context.py` with a 25-line comment
  block explaining the semantic and the fallback contract
- 5 tests in `tests/test_connector_native_positions.py::TestConnectorTotalEquity`
  covering native-only, native+spot, native+xyz+spot, missing-margin-summary,
  and no-account-state
- 4 tests in `tests/test_telegram_iterator_format.py::TestPeriodicEquityAlert`
  covering total_equity preference, fallback behaviour, markdown format,
  and off-cadence skip
- Existing 16 connector tests still pass — `ctx.balances["USDC"]`
  semantic unchanged
- Full pytest suite: 1969 passed, 0 regressions
