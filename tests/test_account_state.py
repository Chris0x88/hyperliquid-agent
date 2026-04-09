from __future__ import annotations

from decimal import Decimal

from cli.daemon.context import TickContext
from cli.daemon.iterators.account_collector import AccountCollectorIterator
from common.account_state import fetch_registered_account_state


def test_fetch_registered_account_state_aggregates_main_vault_and_subs(monkeypatch):
    monkeypatch.setattr(
        "common.account_state.resolve_all_accounts",
        lambda: {
            "main": "0xmain",
            "vault": "0xvault",
            "subs": ["0xsub1"],
            "labels": {},
            "all_addresses": ["0xmain", "0xvault", "0xsub1"],
        },
    )
    monkeypatch.setattr("common.account_state.get_label", lambda addr: addr)

    def fake_fetch_wallet_state(address: str, role: str, label: str | None = None) -> dict:
        rows = {
            "0xmain": {
                "role": role,
                "label": label,
                "address": address,
                "native_equity": 100.0,
                "xyz_equity": 20.0,
                "spot_usdc": 5.0,
                "spot_balances": [{"coin": "USDC", "total": 5.0, "hold": 0.0}],
                "total_equity": 125.0,
                "positions": [{"coin": "BTC", "size": 1.0, "entry": 100.0, "upnl": 1.0, "dex": "native"}],
            },
            "0xvault": {
                "role": role,
                "label": label,
                "address": address,
                "native_equity": 50.0,
                "xyz_equity": 0.0,
                "spot_usdc": 0.0,
                "spot_balances": [],
                "total_equity": 50.0,
                "positions": [{"coin": "BTC", "size": 0.5, "entry": 90.0, "upnl": 2.0, "dex": "native"}],
            },
            "0xsub1": {
                "role": role,
                "label": label,
                "address": address,
                "native_equity": 10.0,
                "xyz_equity": 1.0,
                "spot_usdc": 2.0,
                "spot_balances": [{"coin": "USDC", "total": 2.0, "hold": 0.0}],
                "total_equity": 13.0,
                "positions": [],
            },
        }
        return rows[address]

    monkeypatch.setattr("common.account_state.fetch_wallet_state", fake_fetch_wallet_state)

    state = fetch_registered_account_state()

    assert state["account"]["total_equity"] == 188.0
    assert state["account"]["native_equity"] == 160.0
    assert state["account"]["xyz_equity"] == 21.0
    assert state["account"]["spot_usdc"] == 7.0
    assert len(state["accounts"]) == 3
    assert len(state["positions"]) == 2


class _DummyAdapter:
    def get_account_state(self):
        return {
            "account_value": 100.0,
            "spot_usdc": 5.0,
            "positions": [],
        }

    def get_xyz_state(self):
        return {
            "marginSummary": {"accountValue": 20.0},
            "assetPositions": [],
            "open_orders": [],
        }


def test_account_collector_snapshot_total_equity_does_not_double_count_spot():
    collector = AccountCollectorIterator(adapter=_DummyAdapter())
    ctx = TickContext(prices={"BTC": Decimal("100000")})

    snapshot = collector._build_snapshot(ctx)

    assert snapshot["xyz_account_value"] == 20.0
    assert snapshot["spot_usdc"] == 5.0
    assert snapshot["total_equity"] == 125.0
    assert snapshot["account_value"] == 125.0
