# data/ Directory Structure

This directory holds all runtime data, configs, and state. Most subdirectories are auto-created by the system on first run.

## Committed (helpful for getting started)

```
data/
  config/
    market_config.json    # Markets you're trading (coin → exchange mapping)
    watchlist.json        # All available markets with aliases
    profit_rules.json     # Profit-taking rules per market
    escalation_config.json # Risk escalation thresholds (liquidation, drawdown)
    model_config.json     # AI model selection
  calendar/
    *.json                # Economic event calendars (weekly, quarterly, etc.)
    README.md             # Calendar system documentation
  research/
    FRAMEWORK.md          # Research methodology
    OPERATIONS.md         # Research operations guide
    strategy_versions/    # Strategy version history
```

## Auto-created at runtime (gitignored)

```
data/
  daemon/               # Daemon logs, PID files, chat history
  cli/                  # CLI trade logs, state DB
  snapshots/            # Portfolio snapshots (periodic)
  diagnostics/          # Tool call logs
  reports/              # Generated PDF reports
  thesis/               # Active trading theses (JSON state files)
  agent_memory/         # AI agent persistent memory
  memory/               # Session memory, heartbeat logs
  power_law/            # Power law model state
  research/
    markets/*/charts/   # Price chart screenshots
    evaluations/        # Strategy evaluation results
    trades/             # Trade records
    market_notes/       # Per-trade analysis notes
  feedback.jsonl        # User feedback (via /feedback command)
  bugs.md               # Bug reports (via /bug command)
  todos.jsonl           # Todo items (via /todo command)
```

## First Run

On first run, the system creates the directories it needs. You only need to set up:
1. `config/market_config.json` — which markets to trade (provided)
2. `config/watchlist.json` — market aliases (provided)
3. Your `.env` file (see `.env.example` in the project root)
