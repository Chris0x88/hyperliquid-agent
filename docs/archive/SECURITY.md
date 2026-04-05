# Security: API Wallets & Key Management

## Never Use Your Main Private Key

Your HyperLiquid main private key controls **everything** — trading, withdrawals, transfers. If it leaks, an attacker can drain your entire account.

HyperLiquid provides **API wallets** (also called agent wallets) specifically for programmatic trading. Always use one with this tool.

## API Wallet vs Main Key

| | Main Key | API Wallet |
|-|----------|-----------|
| Can trade | Yes | Yes |
| Can withdraw | Yes | **No** |
| Revocable | No | Yes — deregister from web UI instantly |
| Nonce isolation | Shared with web UI | Separate tracker — no conflicts |
| If leaked | **Full account drain possible** | Can only trade (no withdrawals) |
| Limits | 1 per account | 1 unnamed + 3 named per account |

## How to Create an API Wallet

1. Log in at [app.hyperliquid.xyz](https://app.hyperliquid.xyz/)
2. Go to **Portfolio → API Wallets → Generate**
3. Give it a name (e.g., "agent-bot")
4. **Copy the private key immediately** — it's only shown once
5. Import into this tool: `hl keys import --backend ows`

## Key Storage Backends

This tool stores your API wallet key locally using multiple encrypted backends:

| Backend | Security | Notes |
|---------|----------|-------|
| **OWS Vault** (primary) | AES-256-GCM, mlock'd memory, Rust core | Best option. `pip install open-wallet-standard` |
| **macOS Keychain** | System-level encryption | Auto-detected on macOS. Fast fallback. |
| **Encrypted Keystore** | geth-compatible scrypt KDF | Cross-platform. Requires `HL_KEYSTORE_PASSWORD`. |

Keys are **dual-written** to OWS + Keychain (on macOS) for redundancy.

## Key Rotation

Rotate your API wallet periodically:
1. Generate a new API wallet on app.hyperliquid.xyz
2. Import the new key: `hl keys import --backend ows`
3. Deregister the old API wallet from the web UI

**Important:** HyperLiquid strongly recommends never reusing an API wallet address after deregistration. Nonce state is pruned after deregistration, which could allow replay of previously signed actions.

## If Your Key Is Compromised

1. **Immediately** deregister the API wallet at app.hyperliquid.xyz
2. Close any open positions from the web UI
3. Generate a fresh API wallet
4. Import the new key into this tool
5. Your funds are safe — API wallets cannot withdraw

## Sub-Accounts

For separate budgets per strategy:
1. Create sub-accounts on app.hyperliquid.xyz
2. Transfer funds to the sub-account
3. Create a dedicated API wallet for the sub-account (2 named agents allowed per sub-account)
4. Import: `hl keys import --backend ows`

Sub-account volume counts toward your master account fee tier.

## What This Tool Never Does

- Never stores your main private key (unless you explicitly give it — don't)
- Never makes withdrawal API calls
- Never transmits keys over the network
- Never logs key material
- Never phones home or sends telemetry
