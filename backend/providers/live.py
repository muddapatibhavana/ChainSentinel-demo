"""
ChainSentinel - Live Blockchain Transaction Provider
Normalizes and ingests live blockchain transactions from JSON-RPC endpoints or real-time streams.
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from backend.providers.base import BaseTransactionProvider
except (ImportError, ModuleNotFoundError):
    from providers.base import BaseTransactionProvider

DEFAULT_PUBLIC_RPC_URL = "https://cloudflare-eth.com"


class LiveBlockchainProvider(BaseTransactionProvider):
    """Provides live blockchain transaction ingestion and public RPC synchronization."""

    def __init__(self, rpc_url: Optional[str] = None):
        self._rpc_url = rpc_url or os.getenv("CHAINSENTINEL_RPC_URL", DEFAULT_PUBLIC_RPC_URL)
        self._live_transactions: List[Dict[str, Any]] = []
        self._tx_id_index: set = set()
        self._last_sync_timestamp: Optional[str] = None
        self._last_error: Optional[str] = None
        self._synced_blocks_count: int = 0

    @property
    def name(self) -> str:
        return "Live Blockchain Feed (Mainnet / Ingestion)"

    @property
    def mode(self) -> str:
        return "LIVE"

    @property
    def rpc_url(self) -> str:
        return self._rpc_url

    def set_rpc_url(self, url: str) -> None:
        if url and url.strip():
            self._rpc_url = url.strip()

    def get_status(self) -> Dict[str, Any]:
        total_vol = sum(tx["amount"] for tx in self._live_transactions)
        unique_wallets = set()
        for tx in self._live_transactions:
            unique_wallets.add(tx["from_wallet"])
            unique_wallets.add(tx["to_wallet"])

        return {
            "mode": self.mode,
            "provider_name": self.name,
            "healthy": self._last_error is None,
            "rpc_url": self._rpc_url,
            "total_transactions": len(self._live_transactions),
            "total_wallets": len(unique_wallets),
            "total_volume_eth": round(total_vol, 4),
            "last_sync_timestamp": self._last_sync_timestamp,
            "last_error": self._last_error,
            "synced_blocks_count": self._synced_blocks_count,
            "is_live": True,
            "description": "Real-time normalized blockchain feed supporting public RPC block polling and direct payload ingestion.",
        }

    def get_transactions(self) -> List[Dict[str, Any]]:
        return list(self._live_transactions)

    def normalize_transaction(self, raw_tx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalizes a transaction payload into ChainSentinel schema.
        Handles both raw Ethereum JSON-RPC format and standard dictionary format.
        """
        # Case A: Raw Ethereum JSON-RPC format (keys: hash, from, to, value, gas, gasPrice)
        if "hash" in raw_tx and "from" in raw_tx:
            tx_hash = str(raw_tx["hash"])
            from_addr = str(raw_tx["from"]).lower()
            to_addr = str(raw_tx.get("to") or "0x0000000000000000000000000000000000000000").lower()

            raw_val = raw_tx.get("value", "0x0")
            if isinstance(raw_val, str) and raw_val.startswith("0x"):
                val_wei = int(raw_val, 16)
            else:
                val_wei = int(raw_val or 0)
            amount_eth = round(val_wei / 1e18, 6)

            gas_val = int(raw_tx.get("gas", "0x5208"), 16) if isinstance(raw_tx.get("gas"), str) else int(raw_tx.get("gas", 21000))
            gas_price_val = int(raw_tx.get("gasPrice", "0x4a817c800"), 16) if isinstance(raw_tx.get("gasPrice"), str) else int(raw_tx.get("gasPrice", 20000000000))
            gas_fee_eth = round((gas_val * gas_price_val) / 1e18, 6)

            block_ts = raw_tx.get("block_timestamp")
            if block_ts:
                timestamp = block_ts
            else:
                timestamp = datetime.now(timezone.utc).isoformat()

            return {
                "tx_id": tx_hash,
                "from_wallet": from_addr,
                "to_wallet": to_addr,
                "amount": amount_eth,
                "timestamp": timestamp,
                "status": "SUCCESS",
                "gas_fee": gas_fee_eth,
                "category_label": "live_transfer",
                "description": f"Live Ethereum Mainnet Transfer ({amount_eth} ETH)",
            }

        # Case B: Standard ChainSentinel payload
        tx_id = str(raw_tx.get("tx_id") or raw_tx.get("id") or f"0xLIVE{len(self._live_transactions) + 1:08x}")
        from_wallet = str(raw_tx.get("from_wallet") or raw_tx.get("from") or "0x0000000000000000000000000000000000000001")
        to_wallet = str(raw_tx.get("to_wallet") or raw_tx.get("to") or "0x0000000000000000000000000000000000000002")
        amount = float(raw_tx.get("amount") or raw_tx.get("value") or 0.0)
        timestamp = str(raw_tx.get("timestamp") or datetime.now(timezone.utc).isoformat())

        return {
            "tx_id": tx_id,
            "from_wallet": from_wallet,
            "to_wallet": to_wallet,
            "amount": round(amount, 6),
            "timestamp": timestamp,
            "status": str(raw_tx.get("status", "SUCCESS")),
            "gas_fee": float(raw_tx.get("gas_fee", 0.002)),
            "category_label": str(raw_tx.get("category_label", "live_ingested")),
            "description": str(raw_tx.get("description", "Live Ingested Blockchain Transaction")),
        }

    def ingest_transaction(self, raw_tx: Dict[str, Any]) -> Dict[str, Any]:
        """Normalizes and appends a single transaction to the live ledger."""
        normalized = self.normalize_transaction(raw_tx)
        if normalized["tx_id"] not in self._tx_id_index:
            self._tx_id_index.add(normalized["tx_id"])
            self._live_transactions.append(normalized)
            self._last_sync_timestamp = datetime.now(timezone.utc).isoformat()
        return normalized

    def ingest_batch(self, raw_txs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalizes and appends a batch of transactions to the live ledger."""
        added = []
        for raw in raw_txs:
            norm = self.normalize_transaction(raw)
            if norm["tx_id"] not in self._tx_id_index:
                self._tx_id_index.add(norm["tx_id"])
                self._live_transactions.append(norm)
                added.append(norm)

        if added:
            self._last_sync_timestamp = datetime.now(timezone.utc).isoformat()
        return added

    def clear_live_transactions(self) -> None:
        """Clears the live transactions buffer."""
        self._live_transactions.clear()
        self._tx_id_index.clear()
        self._last_error = None

    def fetch_latest_block_transactions(self, max_txs: int = 25) -> List[Dict[str, Any]]:
        """
        Polls the configured public Ethereum JSON-RPC endpoint for the latest block.
        Extracts up to `max_txs` value transfers and ingests them into the live feed.
        Fails gracefully if offline or RPC is unreachable.
        """
        rpc_payload = {
            "jsonrpc": "2.0",
            "method": "eth_getBlockByNumber",
            "params": ["latest", True],
            "id": 1,
        }

        req = urllib.request.Request(
            self._rpc_url,
            data=json.dumps(rpc_payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "ChainSentinel/0.2.0"},
        )

        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            block = data.get("result")
            if not block or "transactions" not in block:
                self._last_error = "RPC returned empty block payload."
                return []

            block_timestamp_hex = block.get("timestamp")
            if block_timestamp_hex and isinstance(block_timestamp_hex, str):
                ts_int = int(block_timestamp_hex, 16)
                block_ts_iso = datetime.fromtimestamp(ts_int, tz=timezone.utc).isoformat()
            else:
                block_ts_iso = datetime.now(timezone.utc).isoformat()

            raw_tx_list = block.get("transactions", [])
            # Filter for value transfers or non-empty transactions
            candidates = []
            for tx in raw_tx_list:
                if isinstance(tx, dict):
                    tx["block_timestamp"] = block_ts_iso
                    candidates.append(tx)
                    if len(candidates) >= max_txs:
                        break

            added = self.ingest_batch(candidates)
            self._synced_blocks_count += 1
            self._last_error = None
            return added

        except urllib.error.URLError as err:
            self._last_error = f"RPC network connection error: {err.reason}"
            return []
        except Exception as err:
            self._last_error = f"RPC extraction error: {str(err)}"
            return []
