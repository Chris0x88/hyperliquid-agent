"""Shared account-state aggregation for commands, AI, and diagnostics.

Centralizes balance and position reads across:
- main trading wallet
- optional vault wallet
- optional sub-wallets

All callers should consume this module rather than re-implementing their own
HL API aggregation, which has historically caused equity drift and duplicated
spot accounting.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from common.account_resolver import get_label, resolve_all_accounts

HL_API = "https://api.hyperliquid.xyz/info"


def _hl_post(payload: dict) -> Any:
    try:
        resp = requests.post(HL_API, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_coin(coin: str, dex: str) -> str:
    if dex == "xyz" and coin and not coin.startswith("xyz:"):
        return f"xyz:{coin}"
    return coin


def fetch_wallet_state(address: str, role: str, label: Optional[str] = None) -> dict:
    """Fetch normalized state for a single wallet address."""
    native = _hl_post({"type": "clearinghouseState", "user": address}) or {}
    xyz = _hl_post({"type": "clearinghouseState", "user": address, "dex": "xyz"}) or {}
    spot = _hl_post({"type": "spotClearinghouseState", "user": address}) or {}

    native_equity = _as_float((native.get("marginSummary") or {}).get("accountValue"))
    xyz_equity = _as_float((xyz.get("marginSummary") or {}).get("accountValue"))
    spot_usdc = 0.0
    spot_balances: list[dict] = []
    for bal in spot.get("balances", []):
        total = _as_float(bal.get("total"))
        if total <= 0:
            continue
        coin = str(bal.get("coin", ""))
        spot_balances.append(
            {"coin": coin, "total": total, "hold": _as_float(bal.get("hold"))}
        )
        if coin == "USDC":
            spot_usdc += total

    positions: list[dict] = []
    for dex_name, state in (("native", native), ("xyz", xyz)):
        for wrapped in state.get("assetPositions", []):
            pos = wrapped.get("position", wrapped) if isinstance(wrapped, dict) else {}
            size = _as_float(pos.get("szi"))
            if size == 0:
                continue
            lev = pos.get("leverage", {})
            positions.append(
                {
                    "account_role": role,
                    "account_label": label or role.title(),
                    "address": address,
                    "dex": dex_name,
                    "coin": _normalize_coin(str(pos.get("coin", "?")), dex_name),
                    "size": size,
                    "entry": _as_float(pos.get("entryPx")),
                    "upnl": _as_float(pos.get("unrealizedPnl")),
                    "leverage": lev.get("value", "?") if isinstance(lev, dict) else lev,
                    "liq": pos.get("liquidationPx"),
                    "margin_used": _as_float(pos.get("marginUsed")),
                    "raw": pos,
                }
            )

    # EQUITY FORMULA (REVERTED 2026-04-17 — see below)
    # The pre-existing formula `native_equity + xyz_equity + spot_usdc`
    # was very close to right per the operator. Today's earlier "triple-
    # count fix" replaced it with `spot_usdc + Σ uPnL`, which:
    #   - Ignored vault wallets entirely (this account has a vault with
    #     ~$550 of operator funds + ~$27 from other participants).
    #   - Reduced reported equity from ~$580 effective → ~$21 phantom.
    #   - Cascaded into portfolio_risk_monitor calibration, dashboard
    #     widgets (drawdown showed -85% because HWM was set under the
    #     prior formula), and every iterator that uses ctx.total_equity.
    # Rolled back. Per-wallet sum is the right per-wallet value;
    # fetch_registered_account_state() then sums across wallets, which
    # gives the correct total INCLUDING vault, since each wallet row is
    # computed independently by fetch_wallet_state.
    # Future cleanup (low priority, separate change):
    #   - Vault per-participant share: subtract other-participant equity
    #     from the vault wallet total to get HIS portion only. Today it
    #     reports the FULL vault including other participants — small
    #     overstatement, no functional risk.
    #   - True unified-account double-count detection: for accounts where
    #     spot USDC is genuinely the same pool as perp margin (rare in
    #     practice for this user), document the edge case rather than
    #     silently changing the formula.
    return {
        "role": role,
        "label": label or role.title(),
        "address": address,
        "native_equity": native_equity,
        "xyz_equity": xyz_equity,
        "spot_usdc": spot_usdc,
        "spot_balances": spot_balances,
        "total_equity": native_equity + xyz_equity + spot_usdc,
        "positions": positions,
    }


def fetch_registered_account_state(
    include_vault: bool = True,
    include_subs: bool = True,
) -> dict:
    """Fetch normalized aggregate state for all configured accounts."""
    accounts_cfg = resolve_all_accounts()
    wallets: list[tuple[str, str]] = []
    if accounts_cfg.get("main"):
        wallets.append(("main", accounts_cfg["main"]))
    if include_vault and accounts_cfg.get("vault"):
        wallets.append(("vault", accounts_cfg["vault"]))
    if include_subs:
        for idx, addr in enumerate(accounts_cfg.get("subs", []) or [], start=1):
            wallets.append((f"sub{idx}", addr))

    account_rows: list[dict] = []
    all_positions: list[dict] = []
    total_equity = 0.0
    total_native = 0.0
    total_xyz = 0.0
    total_spot = 0.0

    for role, addr in wallets:
        label = get_label(addr)
        row = fetch_wallet_state(addr, role=role, label=label)
        account_rows.append(row)
        all_positions.extend(row["positions"])
        total_equity += row["total_equity"]
        total_native += row["native_equity"]
        total_xyz += row["xyz_equity"]
        total_spot += row["spot_usdc"]

    return {
        "account": {
            "total_equity": total_equity,
            "native_equity": total_native,
            "xyz_equity": total_xyz,
            "spot_usdc": total_spot,
        },
        "accounts": account_rows,
        "positions": all_positions,
        "alerts": [],
        "escalation": "L0",
    }
