# Security & Key Management

## API Wallets vs Main Key

Never use your main private key. HyperLiquid provides API wallets (agent wallets) for programmatic trading.

| | Main Key | API Wallet |
|-|----------|-----------|
| Can trade | Yes | Yes |
| Can withdraw | Yes | **No** |
| Revocable | No | Yes -- deregister from web UI instantly |
| Nonce isolation | Shared with web UI | Separate tracker |
| If leaked | Full account drain | Can only trade (no withdrawals) |

### Creating an API Wallet

1. Log in at app.hyperliquid.xyz
2. Portfolio > API Wallets > Generate
3. Name it (e.g., "agent-bot")
4. Copy the private key immediately (shown once)
5. Import: `hl keys import --backend ows`

## Key Storage Backends

Keys are resolved in priority order until one succeeds:

| Backend | Security | Platform | Notes |
|---------|----------|----------|-------|
| **OWS Vault** | AES-256-GCM, mlock'd memory, Rust core | All | Primary. `pip install open-wallet-standard` |
| **macOS Keychain** | System-level encryption | macOS | Auto-detected. Fast fallback. |
| **Encrypted Keystore** | geth-compatible scrypt KDF | All | Requires `HL_KEYSTORE_PASSWORD` |
| **Railway Env** | Platform-managed | Railway | Set via dashboard only |
| **Flat File** | Plaintext, 0600 perms | All | Dev only. Logs warning on every retrieval. |

**Dual-write requirement:** ALL key storage MUST write to both OWS and Keychain (on macOS) for redundancy. See `common/credentials.py` for the `OWSBackend` + `store_key_secure()` pattern.

## OWS Vault Architecture

Each repo gets independent OWS wallets sharing `~/.ows/wallets/`:

- **agent-cli:** wallet prefix `hl-agent`, keychain service `agent-cli`
- **SpaceLord:** wallet prefix `spacelord`, keychain service `spacelord`

OWS auto-derives addresses for all chains from a single secp256k1 key. Requires Python 3.13 (no 3.14 wheels yet).

## CLI Commands

```bash
hl keys import --backend keychain    # Import to Keychain (recommended macOS)
hl keys import --backend keystore    # Import to encrypted keystore
hl keys import --backend ows         # Import to OWS vault
hl keys list                         # Show all addresses (never shows keys)
hl keys migrate --from file --to keychain  # Migrate between backends
```

## Key Rotation

1. Generate a new API wallet on app.hyperliquid.xyz
2. Import the new key: `hl keys import --backend ows`
3. Deregister the old API wallet from the web UI

Never reuse an API wallet address after deregistration -- nonce state is pruned, which could allow replay of previously signed actions.

## If Compromised

1. Immediately deregister the API wallet at app.hyperliquid.xyz
2. Close any open positions from the web UI
3. Generate a fresh API wallet and import it
4. Funds are safe -- API wallets cannot withdraw

## What This Tool Never Does

- Never stores your main private key (unless you explicitly give it -- don't)
- Never makes withdrawal API calls
- Never transmits keys over the network
- Never logs key material
- Never phones home or sends telemetry
