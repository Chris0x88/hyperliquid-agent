# TOOLS.md — Environment-Specific Configuration

## Research File Locations

All trading research lives in this repo:

```
/Users/cdi/Developer/HyperLiquid_Bot/agent-cli/
├── data/research/
│   ├── FRAMEWORK.md          ← Trading rules, information hierarchy
│   ├── OPERATIONS.md         ← Roles, risk thresholds, reporting
│   ├── markets/
│   │   ├── xyz_brentoil/
│   │   │   ├── README.md     ← Oil thesis (THE key document)
│   │   │   ├── trades.jsonl  ← Trade history
│   │   │   ├── signals.jsonl ← Latest signals + position state
│   │   │   ├── notes/        ← Dated research (facility damage, troops, etc)
│   │   │   └── charts/       ← Generated chart images
│   │   └── btc/
│   │       ├── README.md     ← BTC Power Law thesis
│   │       └── signals.jsonl
│   └── strategy_versions/
│       ├── ACTIVE.md         ← Current active strategy
│       └── v001-*.md         ← Version history
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
- Margin: Isolated ONLY (no cross for xyz perps)
- Max leverage: 20x
- OI cap: $750M
- Trading hours: Sun 6PM ET - Fri 5PM ET

## Separate Systems (Claude Code handles these)

- Trade execution via HyperLiquid SDK
- Risk monitor (polls every 30s)
- Telegram commands bot (@Hyperliquid0x88_bot)
- Daily PDF reports (7AM/7PM AEST)
- Hourly position monitoring + opportunity hunting

## Web Research

Use browser/web_fetch for current news. When researching:
- Cross-reference 2+ sources (wartime data unreliable)
- oilprice.com for rig counts and industry news
- EIA.gov for weekly petroleum reports
- ICE for forward curve data
