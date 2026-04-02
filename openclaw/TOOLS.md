# TOOLS.md — Environment-Specific Configuration

## MCP Tools (Primary Interface)

Your MCP connection `hl-trading` provides these tools. **Use these instead of reading files directly when possible.**

### Essential Tools
| Tool | Purpose | When to Use |
|------|---------|-------------|
| `market_context` | Pre-assembled market brief | FIRST call for any trading question |
| `account` | Live balances + positions | Position sizing, equity checks |
| `status` | Quick position view | Simple "where are we?" questions |
| `analyze` | Technicals (EMA, RSI) | Technical analysis questions |

### Research & Memory
| Tool | Purpose | When to Use |
|------|---------|-------------|
| `agent_memory` | Learnings, observations | "What did we learn?" questions |
| `trade_journal` | Trade history with reasoning | Performance review, trade analysis |
| `get_candles` | Historical OHLCV | Chart analysis, backtesting context |
| `cache_stats` | What data is cached | Before requesting candles |

### Actions
| Tool | Purpose | When to Use |
|------|---------|-------------|
| `trade` | Place orders | Executing trades |
| `update_thesis` | Write conviction update | After market analysis — persist your view so the heartbeat can act on it |
| `live_price` | Quick current prices | Fast price check without full market_context overhead |
| `log_bug` | Report a bug | Something's broken |
| `log_feedback` | Record feedback | User shares improvement ideas |

### System
| Tool | Purpose | When to Use |
|------|---------|-------------|
| `diagnostic_report` | Debug failures | Tools not working, empty responses |
| `daemon_status` | Daemon health | Check if daemon is running |

## Research File Locations (Fallback)

If MCP tools are unavailable, read these files directly:

```
data/research/
├── FRAMEWORK.md          ← Trading rules, information hierarchy
├── OPERATIONS.md         ← Roles, risk thresholds, reporting
├── markets/
│   ├── xyz_brentoil/
│   │   ├── README.md     ← Oil thesis (THE key document)
│   │   ├── signals.jsonl ← Latest signals + position state
│   │   └── notes/        ← Dated research notes
│   └── btc/
│       ├── README.md     ← BTC Power Law thesis
│       └── signals.jsonl
└── strategy_versions/
    └── ACTIVE.md         ← Current active strategy
```

## Accounts

| Account | Address | Role |
|---------|---------|------|
| Main | 0x80B5801ce295C4D469F4C0C2e7E17bd84dF0F205 | Trading (oil + spot) |
| Vault | 0x9da9a9aef5a968277b5ea66c6a0df7add49d98da | BTC Power Law |

Account is UNIFIED mode — don't double count spot + perps margin.

## Key Market Details

- BRENTOIL contract: xyz:BRENTOIL (HIP-3, trade.xyz)
- Tracks: ICE Brent June 2026 (BZM6), rolling Jul 7-13
- Oracle: Pyth Network. Funding: hourly. Margin: isolated only.
- Max leverage: 20x. OI cap: $750M.
- Trading hours: Sun 6PM ET - Fri 5PM ET.

## Separate Systems

- **Commands Bot** (separate DM bot): Handles /status, /chart, /market, /position, /pnl, /bug, /feedback
- **Claude Code**: Handles code changes, research updates, scheduled thesis evaluation
- **Daemon**: Autonomous execution, risk management, position monitoring

## Web Research

Use browser/web_fetch for current news. When researching:
- Cross-reference 2+ sources (wartime data unreliable)
- oilprice.com for rig counts and industry news
- EIA.gov for weekly petroleum reports
- ICE for forward curve data
