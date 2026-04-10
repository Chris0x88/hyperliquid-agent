---
title: Installation
description: Set up HyperLiquid Bot from scratch — Python 3.13, virtual environment, key management, and launchd configuration.
---

import { Aside, Steps } from '@astrojs/starlight/components';

## Prerequisites

- **macOS** (launchd-based daemon management; Linux support is partial)
- **Python 3.13** (`python3.13 --version`)
- **A HyperLiquid account** with an API wallet (NOT your main private key)
- **A Telegram bot** — create one via [@BotFather](https://t.me/BotFather)
- **OpenRouter API key** (optional, for AI agent features)

<Aside type="caution" title="Never use your main private key">
Use an API wallet. HyperLiquid API wallets can trade but **cannot withdraw funds**. If your key is compromised, you can revoke it instantly and attackers cannot steal your balance.
</Aside>

---

## Step-by-Step Setup

<Steps>

1. **Clone and install**

   ```bash
   git clone https://github.com/Chris0x88/hyperliquid-agent.git
   cd hyperliquid-agent/agent-cli
   python3.13 -m venv .venv && source .venv/bin/activate
   pip install -e .
   ```

2. **Create an API wallet on HyperLiquid**

   1. Log in at [app.hyperliquid.xyz](https://app.hyperliquid.xyz/)
   2. Go to **Portfolio → API Wallets → Generate**
   3. Name it (e.g., `agent-bot`) and copy the private key immediately
   4. Import it into the encrypted keystore:

   ```bash
   python -m cli.main keys import
   ```

   The key is stored in both the Open Wallet Standard (AES-256-GCM) vault and macOS Keychain — dual-write for resilience.

3. **Configure environment**

   ```bash
   cp .env.example .env
   ```

   Open `.env` and fill in:

   | Variable | Description |
   |----------|-------------|
   | `TELEGRAM_BOT_TOKEN` | From @BotFather |
   | `TELEGRAM_CHAT_ID` | Your chat ID (from @userinfobot) |
   | `OPENROUTER_API_KEY` | Optional — needed for AI agent features |
   | `HL_WALLET_ADDRESS` | Your HyperLiquid vault/main address |

4. **Start the daemon in Watch mode**

   ```bash
   # Monitors only — no trading. Always start here.
   python -m cli.main daemon start --tier watch
   ```

   WATCH tier runs all monitoring iterators but gates any autonomous trade placement. Verify it's working before promoting tiers.

5. **Launch the Telegram bot**

   ```bash
   python -m cli.telegram_bot
   ```

   Send `/portfolio` to your bot in Telegram. You should see your current positions.

6. **(Optional) Set up launchd for automatic start**

   Copy the provided plist files to run the daemon and bot as background services:

   ```bash
   cp launchd/com.hyperliquid.daemon.plist ~/Library/LaunchAgents/
   cp launchd/com.hyperliquid.telegram.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.hyperliquid.daemon.plist
   launchctl load ~/Library/LaunchAgents/com.hyperliquid.telegram.plist
   ```

</Steps>

---

## Verifying the Install

Run the test suite to confirm everything is wired correctly:

```bash
cd agent-cli
.venv/bin/python -m pytest tests/ -x -q
```

All tests should pass. If you see failures, check that your `.env` has the required variables.

---

## Directory Layout

```
agent-cli/
├── .venv/                  # Python virtual environment
├── cli/
│   ├── telegram_bot.py     # Telegram dashboard
│   ├── agent_runtime.py    # Embedded Claude agent
│   └── daemon/             # Tick-based daemon engine
├── common/                 # Shared libraries
├── parent/                 # Exchange proxy + risk manager
├── modules/                # REFLECT, GUARD, RADAR, etc.
├── data/
│   ├── thesis/             # Your thesis JSON files
│   ├── memory/             # memory.db + backups
│   └── config/             # markets.yaml, kill switches
├── agent/
│   ├── AGENT.md            # Agent system prompt
│   └── SOUL.md             # Agent personality + trading rules
└── .env                    # Your secrets (never commit this)
```

---

## Key Management

All key storage dual-writes to two locations for resilience:

1. **OWS vault** — `data/keys/` encrypted with AES-256-GCM
2. **macOS Keychain** — accessible via `python -m cli.main keys list`

To rotate a key:

```bash
python -m cli.main keys import  # adds new key
python -m cli.main keys remove <old-key-name>
```
