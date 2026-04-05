# Vault Rebalancer

Background daemon that manages BTC exposure in the vault account using the Power Law / Heartbeat Model strategy. Runs hourly via launchd.

## Strategy: BTC Power Law

The Heartbeat Model allocates 0-100% to BTC based on where price sits relative to the Bitcoin power law regression. On HyperLiquid this means holding BTC-PERP at 1x leverage (no leverage -- allocation IS the exposure) in the vault.

## How It Works

`scripts/run_vault_rebalancer.py` is the entry point. Each tick (default 3600s):

1. Build a `PowerLawBot` instance wired to the vault via `HLProxy(vault_address=...)`
2. Compute target BTC allocation from the power law model
3. Compare current position to target
4. If deviation exceeds the threshold (default 10%), rebalance

The bot uses `plugins/power_law/bot.py` for strategy logic and `plugins/power_law/config.py` for configuration.

## Configuration

| Parameter | Default | Source |
|-----------|---------|--------|
| `POWER_LAW_MAX_LEVERAGE` | 1 | env var |
| `POWER_LAW_THRESHOLD_PERCENT` | 10 | env var |
| `POWER_LAW_SIMULATE` | false | env var |
| `POWER_LAW_INTERVAL_SECONDS` | 3600 | env var |
| `HL_VAULT_ADDRESS` | (required) | env var |

The threshold was originally 15% (from SaucerSwap where fees were high). HL fees are ~0.035%, so lower thresholds (2-5%) may be more optimal.

## Process Management

- PID file at `data/vault_rebalancer.pid`
- Single instance enforced via PID kill (same pacman pattern as Telegram bot)
- Graceful shutdown on SIGTERM/SIGINT
- Logs to `logs/vault_rebalancer.log`

## launchd

Plist: `~/Library/LaunchAgents/com.hl-bot.vault-rebalancer.plist`

## Telegram Control

| Command | Action |
|---------|--------|
| `/rebalancer start` | Start the rebalancer daemon |
| `/rebalancer stop` | Stop the rebalancer daemon |
| `/rebalancer status` | Check if running + last rebalance |
| `/rebalance` | Force immediate rebalance |

## Funding Drag

Holding BTC-PERP incurs cumulative funding payments. This is a known cost to monitor -- the vault's funding paid should be tracked against the rebalancing gains.
