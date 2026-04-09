# Multi-Market Expansion Plan

> **Goal**: decouple the trading core from oil-shaped assumptions so any
> HyperLiquid market can be promoted from "tracked" to "thesis-driven" via
> configuration, not code edits.
>
> **Status**: Proposed. Wedge 1 ready to start after the current Oil Bot
> Pattern System sub-system 6 completes.

---

## Why this is needed

The codebase is currently shaped around oil + BTC because that's where Chris's
edge began. Specifically, these assumptions are baked in:

| Assumption | Where it lives | Generalisation challenge |
|---|---|---|
| `LONG or NEUTRAL only on oil` | `common/conviction_engine.py:check_oil_direction_guard()` + CLAUDE.md rule #4 | Other markets have different direction bias |
| Approved markets list `BTC, BRENTOIL, CL, GOLD, SILVER` | CLAUDE.md rule #2; risk_caps.json; thesis directory naming | Hardcoded list is the choke point |
| `xyz:` prefix handling | Recurring footgun across the codebase | Already partly generalised via `_coin_matches()` |
| BRENTOIL roll buffer | `conviction_engine.is_near_roll_window()` (3rd–12th business day) | Roll calendars differ per instrument family |
| Catalyst severity rules | `data/config/news_rules.yaml` regex patterns are oil-flavoured | Each market needs its own catalyst dictionary |
| Supply ledger | `modules/supply_ledger.py` is shaped around physical oil disruptions | Different markets need different signal types |
| oil_botpattern subsystem | The whole subsystem is named, scoped, and gated for oil | Generalises to "any market with cascade-prone bot patterns" |
| Heatmap defaults | `data/config/heatmap.json` defaults to `["BRENTOIL"]` | Easy fix — already configurable |
| Tier system + auto-watchlist | Auto-watchlist tracks any open position but doesn't promote it to thesis-driven | This is the hook the expansion plugs into |

The fact that auto-watchlist already tracks any position is the architectural
crack to expand through: the system *can* see other markets, it just can't
*decide* on them.

---

## Design principles

1. **No new abstractions until they earn their keep.** Three similar configs
   beat a premature abstraction. Generalise when sub-system 5 (which already
   takes BRENTOIL + CL) wants to add a third instrument.
2. **Configuration over code.** Adding a new tradeable market should be a
   YAML edit + a new thesis JSON, not a code change.
3. **Per-market metadata, not global rules.** "Long-only oil" becomes
   `direction_bias: "long_only"` on a per-instrument config.
4. **Backwards-compatible.** Existing oil thesis files and the oil_botpattern
   subsystem continue to work unchanged. The plan is additive.
5. **Test every promotion.** A new market is treated like a new strategy:
   it goes through WATCH → REBALANCE → OPPORTUNISTIC tiers with its own
   smoke tests at each step.

---

## The wedges

This plan is split into independently shippable wedges. Each wedge is a
PR-sized unit of work with its own tests and build-log entry. Ship them in
order; each builds on the previous.

### Wedge 1 — Per-market direction bias config

**What ships:**
- New file `data/config/markets.yaml` with per-instrument metadata:
  ```yaml
  markets:
    BTC:
      direction_bias: "neutral"     # long, short, or neutral allowed
      asset_class: "crypto"
      thesis_required: true
      max_leverage: 25
    BRENTOIL:
      direction_bias: "long_only"   # the existing rule, now configurable
      asset_class: "commodity"
      sub_class: "energy"
      thesis_required: true
      max_leverage: 10
      roll_calendar: "monthly_3rd_to_12th"
      exception_subsystems: ["oil_botpattern"]   # the only place shorting is legal
    GOLD:
      direction_bias: "neutral"
      asset_class: "commodity"
      sub_class: "precious_metals"
      thesis_required: true
      max_leverage: 10
    # ... etc
  ```
- New module `common/markets.py` with a `MarketRegistry` class that loads
  markets.yaml, handles xyz: prefix normalization, and exposes:
  - `get_direction_bias(symbol) -> Literal["long_only", "short_only", "neutral"]`
  - `is_direction_allowed(symbol, direction, subsystem=None) -> bool`
  - `get_max_leverage(symbol) -> int`
  - `is_thesis_required(symbol) -> bool`
- `common/conviction_engine.py:check_oil_direction_guard()` becomes
  `check_direction_guard(symbol, direction, subsystem)` and delegates to
  `MarketRegistry.is_direction_allowed()`.
- The hardcoded oil-only-long check is removed from conviction_engine and
  moved into the registry's BRENTOIL row. Behavior is **identical** at
  ship time — no rule change.

**Tests:**
- `tests/test_market_registry.py` — load, lookup, prefix handling, direction
  bias, leverage caps, subsystem exception handling.
- `tests/test_conviction_engine.py` — existing oil-direction tests unchanged
  but now flow through the registry.

**Backwards compatibility:** The CLAUDE.md rule "LONG or NEUTRAL only on
oil — except inside `oil_botpattern`" continues to be enforced, just via
configuration instead of a hardcoded function. No behavior change.

**Definition of done**:
- All existing tests pass with no behavior change.
- Adding a hypothetical SOL or HYPE market is a markets.yaml edit only.
- CLAUDE.md gets a new note pointing future sessions at markets.yaml.

---

### Wedge 2 — Thesis JSON schema generalisation

**What ships:**
- Schema migration for `data/thesis/*_state.json` to include:
  - `asset_class` field
  - `direction_bias_override` (rare — for cases where the market default
    needs a per-thesis override)
  - `instrument_metadata_version` (so future schema changes are detectable)
- Migration script `scripts/migrate_thesis_v2.py` (additive, idempotent,
  no destructive overwrite — adds missing fields, preserves existing).
- `common/thesis.py` schema validation updated to require `asset_class`
  on new theses; legacy theses without it default to the markets.yaml
  asset_class for that symbol.

**Tests:**
- Round-trip serialization with new fields.
- Legacy thesis (no asset_class) loads cleanly via fallback.
- Validation rejects mismatched direction (e.g., short BRENTOIL outside the
  exception subsystem).

---

### Wedge 3 — Catalyst dictionary per asset class

**What ships:**
- `data/config/news_rules/` directory restructured per asset class:
  ```
  data/config/news_rules/
    crypto.yaml          # exchange hacks, regulatory, ETF flows, network events
    energy.yaml          # current oil rules, refined
    precious_metals.yaml # central bank, real rates, currency debasement
    equities.yaml        # earnings, Fed, macro
  ```
- `news_engine.py` loads all rule files and matches against an instrument's
  asset_class instead of a single rules file.
- News ingest iterator routes alerts by asset class so a refinery outage
  doesn't deleverage a BTC position.

**Tests:**
- Per-asset-class rule loading, isolation (crypto rules don't fire on oil),
  multi-class events (Fed announcements relevant to all classes).

---

### Wedge 4 — Auto-watchlist promotion path

**What ships:**
- New Telegram command `/promote <symbol>` (deterministic — no AI):
  1. Looks up symbol in MarketRegistry, fails if unknown
  2. Creates a stub thesis JSON with `conviction: 0.0` (clamped) so
     the daemon will track but not trade
  3. Asks Chris to fill in the thesis via `/thesis` or by editing the file
  4. Logs the promotion to build-log.md (programmatically — additive)
- Reverse: `/depromote <symbol>` archives the thesis JSON to
  `data/thesis/archive/` and removes the symbol from the active set.

**Tests:**
- Round-trip promote → depromote, validation, error handling on unknown
  symbol, idempotency.

---

### Wedge 5 — Multi-instrument oil_botpattern generalisation

**What ships:**
- Rename `cli/daemon/iterators/oil_botpattern.py` →
  `cli/daemon/iterators/cascade_pattern_strategy.py` (additive: alias the
  old name during transition so the existing config keeps working).
- Generalise `instruments` config from `["BRENTOIL", "CL"]` to any market
  with `cascade_prone: true` in markets.yaml.
- Sizing multipliers per instrument keep working but become a markets.yaml
  field.

**Tests:**
- Existing oil_botpattern tests continue to pass.
- New test: enabling cascade_pattern on a hypothetical second instrument
  with different leverage/multiplier produces correct sizing.

**This wedge is optional** — only ship if Chris wants cascade-pattern
strategies on a non-oil market. Otherwise the rename + alias is enough.

---

### Wedge 6 — CLAUDE.md + wiki + MASTER_PLAN reconciliation

**What ships:**
- CLAUDE.md updated:
  - Rule #2: "Tradeable markets are configured in `data/config/markets.yaml`,
    not hardcoded."
  - Rule #4: "Direction bias per market is in markets.yaml. The oil long-only
    rule is enforced there."
- New wiki page `docs/wiki/operations/adding-a-market.md` with the
  end-to-end checklist for promoting a new instrument.
- MASTER_PLAN.md "Tradeable thesis markets" row updated (or — if reality
  has shifted enough — archive + rewrite per MAINTAINING.md).

---

## What this plan deliberately does NOT do

- **Does not** change how Chris writes thesis JSONs day-to-day. The format
  is backwards-compatible.
- **Does not** weaken any safety rule. Long-only-oil stays exactly as
  strict, just lives in config instead of code.
- **Does not** add support for spot trading, options, or non-HL venues.
  Those are separate plans if Chris wants them.
- **Does not** add multi-account support. Single-vault, single-main-account
  remains the assumption.
- **Does not** remove the conviction-driven sizing model. Every market uses
  the same Druckenmiller ladder.
- **Does not** introduce a marketplace, signal-sharing, or anything
  user-facing beyond Chris.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Adding markets without thesis discipline → bad trades | New markets default to `conviction_clamped: 0.0` and the auto-watchlist; promotion to thesis-driven requires explicit `/promote` |
| MarketRegistry becomes a god object | Keep it pure-data: no I/O beyond loading the YAML, no business logic beyond lookup. All behavior stays in the existing engines. |
| Schema migration breaks existing thesis files | Migration is additive + idempotent. Backups are taken before any schema touch (memory_backup iterator handles memory.db; thesis files have separate H6 dual-write backup). |
| New asset classes have novel risk modes the existing iterators don't handle | New asset class = new wedge in this plan. Don't ship a new class until its risk modes are documented and the relevant iterators have asset-class-aware logic. |
| Rule drift between code, markets.yaml, and CLAUDE.md | Add a Guardian drift check that verifies CLAUDE.md rule #4 references markets.yaml and that markets.yaml has a row for every symbol mentioned in `data/thesis/`. |

---

## Definition of Done for the whole plan

- Adding a new HL market is: `markets.yaml` edit + new thesis JSON + `/promote`. Three steps. Zero code changes.
- The phrase "oil-only" appears nowhere in `common/`, `cli/`, or `parent/` source code outside of comments referencing the config file.
- A new Guardian drift rule fails if a thesis exists for a symbol not in markets.yaml, or vice versa.
- The wiki has an `adding-a-market.md` runbook with a worked example.
- 100% of existing tests pass with no behavior change.
- A successful manual end-to-end test: promote one new market (e.g., ETH), write a thesis, watch the daemon track it, place a small real trade, see the journal + lesson layer pick it up.

---

## Versioning

Same convention as MASTER_PLAN.md and NORTH_STAR.md. When wedges complete
or scope changes, archive + rewrite. Don't accumulate stale "Wedge X — TODO"
items in the body.

> Past versions: see `docs/plans/archive/`.
