from __future__ import annotations

from decimal import Decimal

from daemon.context import TickContext
from daemon.iterators.account_collector import AccountCollectorIterator
from common.heartbeat import _fetch_account_state
from common.heartbeat_config import HeartbeatConfig
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


def test_heartbeat_fetch_account_state_uses_shared_equity_totals(monkeypatch):
    monkeypatch.setattr("common.heartbeat._get_main_account", lambda: "0xmain")
    monkeypatch.setattr("common.heartbeat._get_vault_address", lambda: "0xvault")
    monkeypatch.setattr("common.heartbeat._fetch_open_trigger_orders", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.heartbeat._fetch_funding_rates", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        "common.account_state.fetch_registered_account_state",
        lambda: {
            "account": {"total_equity": 200.0},
            "accounts": [
                {"role": "main", "total_equity": 120.0},
                {"role": "vault", "total_equity": 50.0},
                {"role": "sub1", "total_equity": 30.0},
            ],
            "positions": [],
            "alerts": [],
            "escalation": "L0",
        },
    )

    class _Resp:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, json=None, timeout=10):
        payload = json or {}
        if payload.get("type") == "clearinghouseState":
            return _Resp({"marginSummary": {"accountValue": 1}, "assetPositions": []})
        if payload.get("type") == "spotClearinghouseState":
            return _Resp({"balances": []})
        if payload.get("type") == "metaAndAssetCtxs":
            return _Resp([{"universe": []}, []])
        return _Resp({})

    monkeypatch.setattr("requests.post", fake_post)

    state = _fetch_account_state(HeartbeatConfig())

    assert state["equity"] == 200.0
    assert state["main_equity"] == 120.0
    assert state["vault_equity"] == 50.0
    assert state["sub_equity"] == 30.0


def test_heartbeat_fetch_account_state_includes_sub_wallet_positions(monkeypatch):
    monkeypatch.setattr("common.heartbeat._get_main_account", lambda: "0xmain")
    monkeypatch.setattr("common.heartbeat._get_vault_address", lambda: "")
    monkeypatch.setattr("common.heartbeat._get_sub_accounts", lambda: ["0xsub1"])
    monkeypatch.setattr("common.heartbeat._fetch_open_trigger_orders", lambda *args, **kwargs: [])
    monkeypatch.setattr("common.heartbeat._fetch_funding_rates", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        "common.account_state.fetch_registered_account_state",
        lambda: {
            "account": {"total_equity": 150.0},
            "accounts": [
                {"role": "main", "total_equity": 100.0},
                {"role": "sub1", "total_equity": 50.0},
            ],
            "positions": [],
            "alerts": [],
            "escalation": "L0",
        },
    )

    class _Resp:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, json=None, timeout=10):
        payload = json or {}
        user = payload.get("user")
        dex = payload.get("dex")
        if payload.get("type") == "clearinghouseState" and user == "0xmain" and not dex:
            return _Resp({"marginSummary": {"accountValue": 100}, "assetPositions": []})
        if payload.get("type") == "clearinghouseState" and user == "0xsub1" and not dex:
            return _Resp({
                "marginSummary": {"accountValue": 50},
                "assetPositions": [
                    {"position": {"coin": "ETH", "szi": "2", "entryPx": "2000", "positionValue": "4100", "unrealizedPnl": "100", "leverage": {"value": "3"}}}
                ],
            })
        if payload.get("type") == "clearinghouseState" and dex == "xyz":
            return _Resp({"marginSummary": {"accountValue": 0}, "assetPositions": []})
        if payload.get("type") == "spotClearinghouseState":
            return _Resp({"balances": []})
        if payload.get("type") == "metaAndAssetCtxs":
            return _Resp([{"universe": []}, []])
        return _Resp({})

    monkeypatch.setattr("requests.post", fake_post)

    state = _fetch_account_state(HeartbeatConfig())

    sub_pos = next(p for p in state["positions"] if p["coin"] == "ETH")
    assert sub_pos["account"] == "sub1"
    assert sub_pos["wallet_address"] == "0xsub1"
    assert state["sub_equity"] == 50.0
