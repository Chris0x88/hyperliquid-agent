# HyperLiquid Agent — Daemon Layer & Simplification

**Date:** 2026-03-29
**Status:** Review
**Scope:** New daemon/monitoring layer, strategy visibility system, API wallet onboarding, dead code removal

---

## 1. Problem

The agent-cli inherited 22 strategies and APEX multi-slot orchestration from Nunchi. A regular person sees this complexity and closes the tab. The product needs to be approachable: clone, configure your API wallet, run a daemon that monitors and rebalances.

**Goals:**
- Tiered daemon (watch → rebalance → opportunistic) so beginners aren't overwhelmed
- Multi-strategy roster — easy to add/remove/pause live strategies
- All daemon logic is deterministic — OpenClaw is "just a human that runs programs"
- API wallet security baked into onboarding as the primary path
- Keep all 22 strategies available but surface only a curated few

**Non-goals:**
- HFT or sub-second execution
- Rewriting existing pure-logic modules (guard, radar, pulse, reflect)
- Removing strategy files — they stay for power users via `hl run`

---

## 2. Architecture: Hummingbot-style Clock Loop

### 2.1 Core Pattern

A `Clock` ticks at a configurable interval. Each tick calls registered `Iterator` objects in dependency order. Inspired by Hummingbot's `TimeIterator` pattern but drastically simplified — no Cython, no event bus, just a protocol and a loop.

```
Clock (configurable interval, default 60s)
  → ConnectorIterator   (refresh balances, positions, prices from HL)
  → RiskIterator        (risk gate checks — wraps parent/risk_manager.py)
  → GuardIterator       (trailing stops per active position — wraps modules/trailing_stop.py)
  → RebalancerIterator  (per-strategy — runs any BaseStrategy.on_tick())
  → RadarIterator       (opportunity scan — wraps modules/radar_engine.py, own schedule)
  → PulseIterator       (momentum detection — wraps modules/pulse_engine.py, own schedule)
  → JournalIterator     (log state snapshot, PnL, write to store — wraps modules/reflect_engine.py)
  ─── post-iterator phase ───
  → ExecutionPhase      (drain order_queue, submit to HL, record fills)
```

### 2.2 Iterator Protocol

```python
class Iterator(Protocol):
    name: str

    def tick(self, ctx: TickContext) -> None:
        """Called every clock cycle. Read/write shared TickContext."""
        ...

    def on_start(self, ctx: TickContext) -> None:
        """Called once when iterator is registered.

        Raises RuntimeError on failure. ConnectorIterator failure is fatal
        (daemon refuses to start). Other iterator failures are non-fatal
        (iterator skipped, alert raised, daemon continues without it).
        """
        ...

    def on_stop(self) -> None:
        """Called when iterator is deregistered or daemon stops."""
        ...
```

### 2.3 TickContext — Shared Data Bag

`ConnectorIterator` populates the context first. Downstream iterators consume and append.

```python
@dataclass
class TickContext:
    # Populated by ConnectorIterator
    timestamp: int                          # unix ms
    balances: dict[str, Decimal]            # token → balance
    positions: list[Position]               # current positions
    prices: dict[str, Decimal]              # instrument → mid price
    candles: dict[str, list]                # instrument → candle history (see 2.3.1)
    all_markets: list[dict]                 # all HL perps metadata

    # Populated by downstream iterators
    order_queue: list[OrderIntent]          # orders to execute in post-iterator phase
    alerts: list[Alert]                     # notifications for OpenClaw / logging
    risk_gate: RiskGate                     # OPEN / COOLDOWN / CLOSED

    # Strategy roster state
    active_strategies: dict[str, StrategySlot]  # name → slot with strategy instance + config


@dataclass
class OrderIntent:
    """Adapter between StrategyDecision and the execution phase.

    RebalancerIterator converts StrategyDecision (from BaseStrategy.on_tick())
    into OrderIntent. This decouples strategy output from execution details.
    """
    strategy_name: str              # which roster slot generated this
    instrument: str                 # e.g., "BTC-PERP"
    action: str                     # "buy" | "sell" | "close" | "noop"
    size: Decimal                   # base asset quantity
    price: Decimal | None           # None = market order
    reduce_only: bool = False
    meta: dict = field(default_factory=dict)  # pass-through from StrategyDecision


@dataclass
class Alert:
    """Notification for logging and OpenClaw consumption."""
    severity: str                   # "info" | "warning" | "critical"
    source: str                     # iterator name that raised it
    message: str
    timestamp: int                  # unix ms
    data: dict = field(default_factory=dict)  # structured payload
```

### 2.3.1 Candle Data Requirements

ConnectorIterator needs to know which instruments and timeframes to fetch. Each `StrategySlot` declares its data requirements:

```python
@dataclass
class DataRequirements:
    instruments: list[str]          # e.g., ["BTC-PERP"]
    candle_intervals: list[str]     # e.g., ["1h", "4h"]
    candle_lookback_ms: int         # how far back (default 24h)
```

ConnectorIterator unions all active slots' requirements and fetches once. Strategies that don't need candles declare empty requirements (default).

### 2.4 Tiers

Tiers control which iterators are registered. Users upgrade/downgrade at runtime.

| Tier | Iterators | Description |
|------|-----------|-------------|
| `watch` | Connector, Risk, Journal | Monitor positions, PnL, risk. Alert on thresholds. No trading. |
| `rebalance` | + Guard, Rebalancer(s) | Auto-execute rebalance trades. Guard existing positions. |
| `opportunistic` | + Radar, Pulse | Scan for opportunities, surface to OpenClaw or auto-act within strict limits. |

**Tier constraints for `opportunistic`:**
- Capital limits per opportunity (configurable, default 5% of account)
- Position size limits (configurable)
- Leverage limits (configurable, default 3x)
- All entries are deterministic signal-based — no LLM decisions in the daemon
- OpenClaw can override/approve but daemon doesn't wait for approval

### 2.5 Execution Phase

After all iterators have ticked, the Clock drains `ctx.order_queue` and submits orders to HL:

1. Filter: skip orders if `ctx.risk_gate` is CLOSED; skip new entries if COOLDOWN
2. Submit each `OrderIntent` via the HL adapter (`adapters/hl_adapter.py` → `HLVenueAdapter`)
3. On fill: update `PositionTracker.apply_fill()`, log to trade journal
4. On failure: log error, increment circuit breaker counter for the originating strategy
5. After all orders processed: persist state

This is **not** a separate iterator — it's a hardcoded post-tick phase in the Clock itself. Orders never execute mid-tick; iterators only queue intents.

### 2.6 IPC: Runtime Control

Runtime commands (`hl daemon tier`, `hl daemon add`, `hl daemon pause`, `hl daemon stop`) communicate with the running daemon via a **control file**:

- Path: `data/daemon/control.json`
- The daemon checks this file at the **start of each tick** (before ConnectorIterator)
- CLI commands write a JSON command to the file; daemon reads and clears it
- If daemon is not running, commands modify persisted state directly (applied on next start)

```python
# Example control commands
{"action": "set_tier", "tier": "rebalance"}
{"action": "add_strategy", "name": "trend_follower", "instrument": "ETH-PERP", "tick_interval": 60}
{"action": "remove_strategy", "name": "trend_follower"}
{"action": "pause_strategy", "name": "power_law_btc"}
{"action": "resume_strategy", "name": "power_law_btc"}
{"action": "shutdown"}
```

**PID file:** `data/daemon/daemon.pid` — written on start, removed on clean shutdown. `hl daemon stop` reads PID and sends SIGTERM, then waits up to 30s. `hl daemon status` checks if PID is alive.

Why control file over Unix socket: simpler, no async server needed, fits the tick-based model (sub-second responsiveness isn't required), works identically on macOS and Linux.

### 2.7 Runtime Modes

Three distinct modes for the HL adapter:

| Flag | Mode | Description |
|------|------|-------------|
| `--mock` | Simulated | No network calls. Fake prices/fills. For testing. |
| (default) | Testnet | Real HL testnet API. Paper trading with real orderbook. |
| `--mainnet` | Mainnet | Real HL mainnet. Real money. |

### 2.8 Multi-Strategy Roster

The daemon maintains a **roster** of active strategies. Each strategy gets its own `RebalancerIterator` instance.

```python
@dataclass
class StrategySlot:
    name: str                    # registry key (e.g., "power_law_btc")
    strategy: BaseStrategy       # instantiated strategy object
    instrument: str              # e.g., "BTC-PERP"
    tick_interval: int           # strategy-specific tick (e.g., 3600 for hourly)
    last_tick: int               # timestamp of last execution
    paused: bool                 # temporarily stopped
    config: dict                 # strategy params override
```

The clock ticks at its own interval (e.g., 60s). Each `RebalancerIterator` checks whether enough time has passed since `last_tick` before calling `strategy.on_tick()`. This means fast-tick strategies (60s) and slow-tick strategies (3600s) coexist in the same daemon.

**Roster management CLI:**
```bash
hl daemon strategies                          # list active strategies + status
hl daemon add power_law_btc -i BTC-PERP -t 3600   # add to roster
hl daemon add trend_follower -i ETH-PERP -t 60     # add another
hl daemon remove trend_follower               # remove from roster
hl daemon pause power_law_btc                 # stop ticking without removing
hl daemon resume power_law_btc                # resume
```

Roster is persisted to `data/daemon/roster.json` and survives restarts.

---

## 3. File Structure

### 3.1 New Files

```
cli/daemon/
├── __init__.py
├── clock.py               # Clock loop, iterator registration, signal handling
├── config.py              # DaemonConfig dataclass (tier, intervals, limits)
├── context.py             # TickContext, OrderIntent, Alert dataclasses
├── state.py               # DaemonState persistence (roster, risk state, journal)
├── tiers.py               # Tier definitions, iterator sets per tier
├── roster.py              # StrategySlot, roster CRUD, persistence
├── iterators/
│   ├── __init__.py
│   ├── connector.py       # Fetch balances/positions/prices from HL adapter
│   ├── risk.py            # Wraps parent/risk_manager.py
│   ├── guard.py           # Wraps modules/trailing_stop.py per active position
│   ├── rebalancer.py      # Runs BaseStrategy.on_tick() per roster slot
│   ├── radar.py           # Wraps modules/radar_engine.py (own schedule)
│   ├── pulse.py           # Wraps modules/pulse_engine.py (own schedule)
│   └── journal.py         # State snapshots, PnL logging, reflect metrics

cli/commands/daemon.py     # CLI commands: start, stop, status, tier, add, remove, etc.

docs/SECURITY.md           # API wallet explainer, threat model
```

### 3.2 Modified Files

```
cli/main.py                    # Add daemon_app typer group
cli/strategy_registry.py       # Add visibility field to each strategy
skills/onboard/SKILL.md        # Rewrite: API wallet first, daemon-centric flow
BOOTSTRAP.md                   # Rewrite: API wallet is step 1
README.md                      # Rewrite: daemon-first, simplified onboarding
```

### 3.3 Dead Code to Remove

```
cli/multi_wallet_engine.py          # Over-engineered for daemon; single API wallet
quoting_engine/                     # Entire directory — unused in daemon mode
cli/strategy_registry.py:YEX_MARKETS  # Remove YEX_MARKETS dict only (dead, no yield perp support)
```

### 3.4 Soft Deprecations (warn + redirect)

```
cli/commands/apex.py               # hl apex run → "Use hl daemon start"
                                   # hl apex once → "Use hl daemon once"
                                   # hl apex status → "Use hl daemon status"
```

APEX commands stay functional but print deprecation warnings.

---

## 4. Daemon CLI Commands

```bash
# Lifecycle
hl daemon start [--tier watch] [--tick 60] [--mock] [--mainnet]
hl daemon stop                          # graceful shutdown via signal
hl daemon status                        # positions, PnL, risk gate, active strategies
hl daemon once                          # single tick and exit (for cron / OpenClaw)

# Tier management
hl daemon tier                          # show current tier
hl daemon tier rebalance                # upgrade to rebalance tier
hl daemon tier watch                    # downgrade to watch only

# Strategy roster
hl daemon strategies                    # list active strategies + paused/running
hl daemon add <name> [-i INSTRUMENT] [-t TICK_INTERVAL] [--params '{}']
hl daemon remove <name>
hl daemon pause <name>
hl daemon resume <name>
```

**`hl daemon start` flow:**
1. Load config (tier, roster from persisted state or defaults)
2. Resolve API wallet key from credentials backend
3. Instantiate HL adapter (testnet by default)
4. Register iterators for current tier
5. Instantiate strategy roster (one RebalancerIterator per active strategy)
6. Enter clock loop
7. Handle SIGINT/SIGTERM for graceful shutdown (close positions if configured, persist state)

**Default roster on first run:** `power_law_btc` on `BTC-PERP` with 3600s tick, `watch` tier (no actual trading until user upgrades tier).

**`hl daemon once` behavior:** Loads persisted state (same as `start`). If no state exists, uses defaults (watch tier, power_law_btc). Runs one full tick cycle, persists state, exits.

---

## 5. Strategy Visibility System

### 5.1 Registry Changes

Each strategy entry gains a `visibility` field:

```python
STRATEGY_REGISTRY = {
    "power_law_btc": {
        "path": "strategies.power_law_btc:PowerLawBTCStrategy",
        "description": "Bitcoin Power Law rebalancer — ...",
        "visibility": "featured",
        "params": {...},
    },
    "trend_follower": {
        "path": "strategies.trend_follower:TrendFollowerStrategy",
        "visibility": "standard",
        ...
    },
    "avellaneda_mm": {
        "path": "strategies.avellaneda_mm:AvellanedaStoikovMM",
        "visibility": "advanced",
        ...
    },
    ...
}
```

### 5.2 Visibility Levels

| Level | Strategies | Shown in |
|-------|-----------|----------|
| `featured` | power_law_btc | README, `hl strategies`, onboarding, daemon default |
| `standard` | brent_oil_squeeze, oil_war_regime, oil_liq_sweep, mean_reversion, trend_follower, funding_arb (6 total) | `hl strategies --all` |
| `advanced` | All 15 others (MM suite, liquidation, claude_agent, etc.) | `hl strategies --advanced` |

*Total: 22 strategies (1 featured + 6 standard + 15 advanced).*

### 5.3 CLI Behavior

```bash
hl strategies             # shows featured only (1-3 strategies)
hl strategies --all       # shows featured + standard
hl strategies --advanced  # shows everything
```

All strategies remain fully functional via `hl run <name>` regardless of visibility.

---

## 6. Onboarding: API Wallet Security Model

### 6.1 Why API Wallets

HyperLiquid API wallets (agent wallets) are purpose-built for programmatic trading:

1. **Blast radius containment** — API wallets can trade but cannot withdraw funds. A leaked API wallet key cannot drain your account.
2. **Instant revocation** — Deregister from the web UI immediately. You cannot revoke a main private key.
3. **Nonce isolation** — API wallet has its own nonce tracker. Manual web UI trading won't conflict with bot orders.
4. **Multi-bot separation** — 1 unnamed + 3 named API wallets per master account, plus 2 per sub-account.
5. **No key reuse** — HL strongly recommends never reusing API wallet addresses after deregistration (nonce replay risk after pruning).

### 6.2 Onboarding Flow

```
┌─────────────────────────────────────────────────┐
│  Step 1: Create HyperLiquid Account             │
│  → https://app.hyperliquid.xyz/                 │
│  → Sign up via email                            │
│  → Fund account (USDC on Arbitrum)              │
├─────────────────────────────────────────────────┤
│  Step 2: Create API Wallet (CRITICAL)           │
│  → Portfolio → API Wallets → Generate           │
│  → Name it (e.g., "agent-bot")                  │
│  → Copy private key — shown ONCE                │
│  → NEVER use your main wallet key               │
├─────────────────────────────────────────────────┤
│  Step 3: Import API Wallet Key                  │
│  → hl keys import --backend ows                 │
│  → Paste API wallet private key                 │
│  → Key encrypted + stored locally               │
├─────────────────────────────────────────────────┤
│  Step 4: Verify                                 │
│  → hl account                                   │
│  → hl daemon start --tier watch --mock          │
├─────────────────────────────────────────────────┤
│  Step 5: Go Live                                │
│  → hl daemon start --tier watch                 │
│  → Graduate: --tier rebalance when ready        │
│  → Graduate: --tier opportunistic when confident│
└─────────────────────────────────────────────────┘
```

### 6.3 Sub-Accounts (Advanced)

For users wanting budget isolation per strategy:
1. Create sub-account on app.hyperliquid.xyz
2. Transfer funds to sub-account
3. Create dedicated API wallet for the sub-account
4. Import: `hl keys import --backend ows` (daemon auto-detects sub-account context via `vaultAddress`)

Sub-account volume counts toward master account fee tier.

### 6.4 Documentation Deliverables

| File | Content |
|------|---------|
| `docs/SECURITY.md` | API wallet explainer, threat model, key rotation guide, what to do if key is compromised |
| `README.md` | Rewrite onboarding: API wallet setup is the first thing, daemon is the default path |
| `BOOTSTRAP.md` | Rewrite: API wallet at step 1, daemon start at step 4, `hl run` path is secondary |
| `skills/onboard/SKILL.md` | Rewrite: walk through API wallet creation, daemon tier progression |

---

## 7. Data & Analytics Layer (OpenClaw-Accessible)

The historical data system (`modules/candle_cache.py`, `modules/data_fetcher.py`, `modules/backtest_engine.py`, `modules/radar_technicals.py`) is fully built but completely hidden from agents. Currently only accessible via CLI commands (`hl data fetch`, `hl backtest run`). This section adds MCP tools so OpenClaw agents can query data programmatically.

### 7.1 New MCP Tools

Add to `cli/mcp_server.py`:

| Tool | Description | Backend Module |
|------|-------------|---------------|
| `get_candles` | Query cached OHLCV candles for a coin/interval/time range | `modules/candle_cache.py` → `CandleCache.get_candles()` |
| `fetch_data` | Fetch historical candles from HL API into cache | `modules/data_fetcher.py` → `DataFetcher.backfill()` |
| `backtest` | Run a strategy backtest against cached data, return metrics | `modules/backtest_engine.py` → `BacktestEngine.run()` |
| `analyze` | Calculate technical indicators (EMA, RSI, trend, volume ratio) | `modules/radar_technicals.py` |
| `price_at` | Point lookup: closest candle to a given timestamp | `modules/candle_cache.py` |
| `cache_stats` | What data is cached locally (coins, intervals, date ranges) | `modules/candle_cache.py` → `CandleCache.stats()` |

### 7.2 Tool Signatures

```python
@mcp.tool()
def get_candles(coin: str, interval: str = "1h", days: int = 30) -> list[dict]:
    """Get historical OHLCV candles from local cache. Fetches from HL if not cached."""

@mcp.tool()
def fetch_data(coin: str, interval: str = "1h", days: int = 90) -> dict:
    """Fetch and cache historical candles from HL API. Returns fetch stats."""

@mcp.tool()
def backtest(strategy: str, coin: str, interval: str = "1h",
             days: int = 90, capital: float = 10000) -> dict:
    """Run a backtest. Returns PnL, win rate, Sharpe, drawdown, equity curve."""

@mcp.tool()
def analyze(coin: str, interval: str = "1h", days: int = 30) -> dict:
    """Technical analysis snapshot: EMA(5,13,50), RSI(14), trend, volume ratio, patterns."""

@mcp.tool()
def price_at(coin: str, timestamp_ms: int) -> dict:
    """Get the closest candle to a timestamp. Returns OHLCV + actual timestamp."""

@mcp.tool()
def cache_stats() -> dict:
    """What historical data is cached locally. Coins, intervals, date ranges, counts."""
```

### 7.3 Auto-Fetch on Miss

`get_candles` and `analyze` auto-fetch from HL API if the requested data isn't cached. This makes the agent experience seamless — ask for data, get data, no manual fetch step needed. Rate limiting from `DataFetcher` applies.

### 7.4 Daemon Integration

The daemon's ConnectorIterator also benefits: it uses the same `CandleCache` for candle data requirements (section 2.3.1), so daemon candle fetches populate the cache that MCP tools query. One cache, two consumers.

---

## 8. Reuse Map

Existing pure-logic modules become daemon iterator backends with thin wrappers:

| Component | Backend Module | Wrapper Responsibility |
|-----------|---------------|----------------------|
| ConnectorIterator | `adapters/hl_adapter.py` (`HLVenueAdapter`) wrapping `cli/hl_adapter.py` (`DirectHLProxy`) | Populate TickContext with fresh market data. Fetches candles per DataRequirements. |
| RiskIterator | `parent/risk_manager.py` (`RiskManager`) | Call `pre_round_check()`, set `ctx.risk_gate` |
| GuardIterator | `modules/trailing_stop.py` (`TrailingStopEngine`) + `modules/guard_bridge.py` (`GuardBridge`) | Per-position `evaluate()`, sync exchange stop-losses via GuardBridge |
| RebalancerIterator | `sdk/strategy_sdk/base.py` (`BaseStrategy`) | Build `StrategyContext` from `TickContext`, call `on_tick()`, convert `StrategyDecision` → `OrderIntent`, queue to `ctx.order_queue` |
| RadarIterator | `modules/radar_engine.py` (`OpportunityRadarEngine`) | Call `scan()` on schedule, surface results as alerts |
| PulseIterator | `modules/pulse_engine.py` (`PulseEngine`) | Call `scan()` on schedule, feed signals to roster evaluation |
| JournalIterator | `modules/reflect_engine.py` (`ReflectEngine`) | Snapshot state, compute metrics, persist to store |
| ExecutionPhase | `adapters/hl_adapter.py` (`HLVenueAdapter`) | Drain `ctx.order_queue`, submit orders, record fills (see section 2.5) |

All backend modules are stateless and zero-I/O. Iterators handle persistence and context wiring.

**StrategyDecision → OrderIntent mapping** (in RebalancerIterator):
- `StrategyDecision.action` maps directly to `OrderIntent.action`
- `StrategyDecision.size` / `.price` map to `OrderIntent.size` / `.price`
- `OrderIntent.strategy_name` is set from the roster slot name
- `OrderIntent.instrument` is set from the roster slot instrument

Additional reuse:
- `parent/position_tracker.py` → central ledger inside TickContext
- `parent/store.py` (JSONLStore, StateDB) → daemon state persistence
- `common/credentials.py` → API wallet key resolution
- `modules/apex_state.py` → pattern for roster state persistence (ApexStateStore → DaemonStateStore)

---

## 9. State Persistence & Logging

### 8.1 Persistence

All daemon state lives under `data/daemon/`:

```
data/daemon/
├── daemon.pid              # PID file (removed on clean shutdown)
├── control.json            # IPC control file (see section 2.6)
├── state.json              # DaemonState: tier, risk gate, tick count, daily PnL
├── roster.json             # Strategy roster: active slots + per-slot state
├── trades.jsonl            # Trade log (append-only, same format as existing JSONLStore)
└── journal/                # JournalIterator snapshots
```

`state.py` is the single persistence layer. `roster.py` handles in-memory CRUD and delegates serialization to `state.py`.

### 8.2 Logging

Daemon follows existing logging patterns (`common/logging`). Additions:

- Log file: `data/daemon/daemon.log` (rotating, 10MB max, 3 backups)
- Structured JSON mode: `--log-json` flag for OpenClaw consumption
- Log levels: iterator lifecycle at INFO, tick summaries at INFO, order execution at INFO, errors at ERROR
- Each iterator prefixes its log messages with its `name` (e.g., `[guard]`, `[rebalancer]`)

---

## 10. Error Handling & Safety

**Circuit breaker** (reused from TradingEngine pattern):
- Track consecutive API failures per iterator
- 5 consecutive failures → iterator enters safe mode (skip ticks, alert)
- Connector failure → entire tick skipped (no stale data downstream)

**Risk gate** (reused from parent/risk_manager.py):
- OPEN → normal trading
- COOLDOWN → no new entries, exits allowed
- CLOSED → no trading at all, watch-only

**Graceful shutdown:**
- SIGINT/SIGTERM → set `_running = False`, complete current tick, persist state
- Guard stop-losses remain on exchange (crash-safe by design)
- Roster state persisted — restart resumes from last state

**Tier downgrade on error:**
- If opportunistic tier hits repeated failures → auto-downgrade to rebalance
- If rebalance hits repeated failures → auto-downgrade to watch
- User notified via alerts

---

## 11. Testing Strategy

- **Unit tests:** Each iterator tested in isolation with mock TickContext
- **Integration test:** Clock runs 3 ticks with mock adapter, verify iterator call order
- **Roster test:** Add/remove/pause strategies, verify persistence across restart
- **Tier test:** Upgrade/downgrade tiers, verify correct iterator sets
- **E2E mock:** `hl daemon start --mock --max-ticks 5` runs full daemon with simulated HL
