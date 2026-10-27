"""
ChainSentinel - Phase 10 Transaction Providers Test Suite
Verifies synthetic provider, live blockchain provider, normalization contracts,
manager mode switching, real-time ingestion, and REST endpoints.
"""

import pytest
from starlette.testclient import TestClient

from backend.main import app
from backend.providers import (
    BaseTransactionProvider,
    SyntheticTransactionProvider,
    LiveBlockchainProvider,
    ProviderManager,
    PROVIDER_MANAGER,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def ensure_demo_mode_after_test():
    """Ensure every test leaves the system in DEMO mode."""
    yield
    PROVIDER_MANAGER.switch_mode("DEMO")


class TestSyntheticProvider:
    """Verifies synthetic transaction provider contract."""

    def test_synthetic_provider_basic_contract(self):
        prov = SyntheticTransactionProvider()
        assert prov.mode == "DEMO"
        assert "Synthetic" in prov.name
        status = prov.get_status()
        assert status["mode"] == "DEMO"
        assert status["total_transactions"] == 70
        assert status["healthy"] is True

    def test_synthetic_provider_transactions(self):
        prov = SyntheticTransactionProvider()
        txs = prov.get_transactions()
        assert len(txs) == 70
        first = txs[0]
        assert "tx_id" in first
        assert "from_wallet" in first
        assert "to_wallet" in first
        assert "amount" in first
        assert isinstance(first["amount"], float)

    def test_synthetic_normalization(self):
        prov = SyntheticTransactionProvider()
        raw = {
            "tx_id": "0xTEST01",
            "from_wallet": "0xAAA",
            "to_wallet": "0xBBB",
            "amount": 12.5,
            "timestamp": "2026-10-08T12:00:00Z",
        }
        normalized = prov.normalize_transaction(raw)
        assert normalized["tx_id"] == "0xTEST01"
        assert normalized["amount"] == 12.5
        assert normalized["status"] == "SUCCESS"


class TestLiveBlockchainProvider:
    """Verifies live blockchain provider and normalization contracts."""

    def test_live_provider_basic_contract(self):
        prov = LiveBlockchainProvider()
        assert prov.mode == "LIVE"
        assert prov.get_transactions() == []
        status = prov.get_status()
        assert status["mode"] == "LIVE"
        assert status["total_transactions"] == 0
        assert status["is_live"] is True

    def test_normalize_raw_ethereum_rpc_format(self):
        prov = LiveBlockchainProvider()
        raw_rpc_tx = {
            "hash": "0x9876543210abcdef9876543210abcdef9876543210abcdef9876543210abcdef",
            "from": "0x1111111111111111111111111111111111111111",
            "to": "0x2222222222222222222222222222222222222222",
            "value": "0xde0b6b3a7640000",  # 1 ETH in hex Wei (1000000000000000000)
            "gas": "0x5208",  # 21000
            "gasPrice": "0x4a817c800",  # 20 Gwei
            "block_timestamp": "2026-10-08T15:30:00Z",
        }
        normalized = prov.normalize_transaction(raw_rpc_tx)
        assert normalized["tx_id"] == raw_rpc_tx["hash"]
        assert normalized["from_wallet"] == raw_rpc_tx["from"].lower()
        assert normalized["to_wallet"] == raw_rpc_tx["to"].lower()
        assert normalized["amount"] == 1.0
        assert normalized["category_label"] == "live_transfer"
        assert normalized["status"] == "SUCCESS"

    def test_ingest_and_deduplicate(self):
        prov = LiveBlockchainProvider()
        tx1 = {
            "tx_id": "0xLIVE_1",
            "from_wallet": "0xSENDER1",
            "to_wallet": "0xRECV1",
            "amount": 5.0,
            "timestamp": "2026-10-08T12:00:00Z",
        }
        res1 = prov.ingest_transaction(tx1)
        assert res1["tx_id"] == "0xLIVE_1"
        assert len(prov.get_transactions()) == 1

        # Duplicate ingestion
        res2 = prov.ingest_transaction(tx1)
        assert len(prov.get_transactions()) == 1

        # Batch ingestion
        batch = [
            {"tx_id": "0xLIVE_2", "from_wallet": "0xA", "to_wallet": "0xB", "amount": 2.5},
            {"tx_id": "0xLIVE_3", "from_wallet": "0xB", "to_wallet": "0xC", "amount": 2.4},
        ]
        added = prov.ingest_batch(batch)
        assert len(added) == 2
        assert len(prov.get_transactions()) == 3

        # Clear
        prov.clear_live_transactions()
        assert len(prov.get_transactions()) == 0


class TestProviderManager:
    """Verifies manager mode switching and listener triggers."""

    def test_manager_mode_switching(self):
        mgr = ProviderManager()
        assert mgr.mode == "DEMO"
        status = mgr.get_status()
        assert status["active_mode"] == "DEMO"
        assert status["is_live_active"] is False

        # Switch to LIVE
        status_live = mgr.switch_mode("LIVE")
        assert mgr.mode == "LIVE"
        assert status_live["active_mode"] == "LIVE"

        # Switch back to DEMO
        status_demo = mgr.switch_mode("DEMO")
        assert mgr.mode == "DEMO"
        assert status_demo["active_mode"] == "DEMO"

    def test_manager_invalid_mode_raises(self):
        mgr = ProviderManager()
        with pytest.raises(ValueError):
            mgr.switch_mode("UNSUPPORTED_MODE")

    def test_manager_listener_callback(self):
        mgr = ProviderManager()
        called = []

        def callback():
            called.append(True)

        mgr.register_listener(callback)
        mgr.switch_mode("LIVE")
        assert len(called) == 1
        mgr.switch_mode("DEMO")
        assert len(called) == 2


class TestProviderEndpoints:
    """Verifies REST endpoints for provider status, mode switching, and ingestion."""

    def test_get_provider_status(self, client):
        resp = client.get("/api/provider/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_mode"] == "DEMO"
        assert "synthetic_status" in data
        assert "live_status" in data
        assert data["live_supported"] is True

    def test_switch_provider_mode_endpoint(self, client):
        # Switch to LIVE
        resp = client.post("/api/provider/mode", json={"mode": "LIVE"})
        assert resp.status_code == 200
        assert resp.json()["active_mode"] == "LIVE"

        # Health endpoint reflects active mode
        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["data_mode"] == "LIVE"

        # Switch back to DEMO
        resp_back = client.post("/api/provider/mode", json={"mode": "DEMO"})
        assert resp_back.status_code == 200
        assert resp_back.json()["active_mode"] == "DEMO"

    def test_switch_provider_mode_invalid(self, client):
        resp = client.post("/api/provider/mode", json={"mode": "INVALID"})
        assert resp.status_code == 400

    def test_ingest_live_transactions_endpoint(self, client):
        payload = {
            "transactions": [
                {
                    "tx_id": "0xINGEST_01",
                    "from_wallet": "0x0001",
                    "to_wallet": "0x0002",
                    "amount": 15.0,
                    "timestamp": "2026-10-08T16:00:00Z",
                },
                {
                    "tx_id": "0xINGEST_02",
                    "from_wallet": "0x0002",
                    "to_wallet": "0x0003",
                    "amount": 14.5,
                    "timestamp": "2026-10-08T16:01:00Z",
                },
            ]
        }
        resp = client.post("/api/provider/ingest", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ingested_count"] >= 0

    def test_fetch_live_block_endpoint(self, client):
        resp = client.post("/api/provider/fetch-live", json={"max_txs": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert "fetched_count" in data
        assert "total_live_transactions" in data
