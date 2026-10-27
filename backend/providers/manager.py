"""
ChainSentinel - Transaction Provider Manager
Coordinates synthetic demo data and real-time blockchain ingestion.
Provides hot-switching and engine update notification callbacks.
"""

import os
from typing import Any, Callable, Dict, List, Optional

try:
    from backend.providers.base import BaseTransactionProvider
    from backend.providers.synthetic import SyntheticTransactionProvider
    from backend.providers.live import LiveBlockchainProvider
except (ImportError, ModuleNotFoundError):
    from providers.base import BaseTransactionProvider
    from providers.synthetic import SyntheticTransactionProvider
    from providers.live import LiveBlockchainProvider


class ProviderManager:
    """Singleton manager controlling active data mode (DEMO vs LIVE) and transaction feeds."""

    MODE_DEMO = "DEMO"
    MODE_LIVE = "LIVE"

    def __init__(self):
        initial_mode = os.getenv("CHAINSENTINEL_DATA_MODE", self.MODE_DEMO).upper()
        self._mode = self.MODE_LIVE if initial_mode == self.MODE_LIVE else self.MODE_DEMO
        self._synthetic = SyntheticTransactionProvider()
        self._live = LiveBlockchainProvider()
        self._update_listeners: List[Callable[[], None]] = []

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def synthetic_provider(self) -> SyntheticTransactionProvider:
        return self._synthetic

    @property
    def live_provider(self) -> LiveBlockchainProvider:
        return self._live

    def register_listener(self, callback: Callable[[], None]) -> None:
        """Registers a callback hook invoked when transaction dataset changes or mode switches."""
        if callback not in self._update_listeners:
            self._update_listeners.append(callback)

    def _notify_listeners(self) -> None:
        for cb in self._update_listeners:
            try:
                cb()
            except Exception as err:
                print(f"[ProviderManager] Listener notification error: {err}")

    def get_active_provider(self) -> BaseTransactionProvider:
        """Returns the currently active transaction provider instance."""
        if self._mode == self.MODE_LIVE:
            return self._live
        return self._synthetic

    def get_transactions(self) -> List[Dict[str, Any]]:
        """Returns transactions from the active provider."""
        txs = self.get_active_provider().get_transactions()
        # Fallback safeguard: if LIVE mode has 0 transactions yet, return synthetic to avoid empty crash
        if self._mode == self.MODE_LIVE and not txs:
            return self._synthetic.get_transactions()
        return txs

    def switch_mode(self, new_mode: str) -> Dict[str, Any]:
        """Switches the active provider between DEMO and LIVE."""
        target = new_mode.upper().strip()
        if target not in (self.MODE_DEMO, self.MODE_LIVE):
            raise ValueError(f"Invalid mode '{new_mode}'. Expected 'DEMO' or 'LIVE'.")

        if self._mode != target:
            self._mode = target
            self._notify_listeners()

        return self.get_status()

    def ingest_live_transactions(self, raw_txs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Ingests raw transactions into the live provider and refreshes analytical models."""
        added = self._live.ingest_batch(raw_txs)
        if self._mode == self.MODE_LIVE and added:
            self._notify_listeners()

        return {
            "ingested_count": len(added),
            "total_live_transactions": len(self._live.get_transactions()),
            "active_mode": self._mode,
        }

    def fetch_live_block(self, max_txs: int = 25) -> Dict[str, Any]:
        """Polls public RPC for latest block and normalizes transactions into the live feed."""
        added = self._live.fetch_latest_block_transactions(max_txs=max_txs)
        if self._mode == self.MODE_LIVE and added:
            self._notify_listeners()

        return {
            "fetched_count": len(added),
            "total_live_transactions": len(self._live.get_transactions()),
            "last_error": self._live.get_status().get("last_error"),
            "active_mode": self._mode,
        }

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status of both providers and active mode configuration."""
        active_provider = self.get_active_provider()
        return {
            "active_mode": self._mode,
            "is_live_active": self._mode == self.MODE_LIVE,
            "active_provider_name": active_provider.name,
            "synthetic_status": self._synthetic.get_status(),
            "live_status": self._live.get_status(),
            "active_transaction_count": len(self.get_transactions()),
            "live_supported": True,
        }


# Global singleton instance
PROVIDER_MANAGER = ProviderManager()
