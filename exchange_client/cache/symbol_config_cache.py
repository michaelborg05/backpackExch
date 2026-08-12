"""In-memory cache of per-symbol order sizing (`symbol_configs`).

Position sizing reads a symbol's config on every signal that reaches the
sizing stage, one query per (profile, symbol) — which made this one of the
most-called statements in the database despite the table being small, static
config that changes only when someone edits the Symbols page.

The whole table is loaded in a single query and served from memory. Writes go
through `upsert_symbol_config`, which invalidates; the TTL is a backstop for
writes this process cannot see (the `db/manage.py` CLI runs separately), and
bounds how long a stale order size could survive. Order size decides how much
capital goes into a trade, so the TTL is deliberately short rather than absent.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple

from utils.logging import log_manager


@dataclass(frozen=True)
class CachedSymbolConfig:
    """Immutable snapshot of one symbol_configs row.

    Deliberately not the ORM object: those expire on commit and detach when
    their session closes, so a cached one would start issuing lazy reloads —
    exactly the queries this cache exists to remove.
    """
    profile_name: str
    symbol: str
    order_size_usdc: Optional[Decimal]
    max_position_size_pct: Optional[Decimal]


class SymbolConfigCache:
    """Enabled symbol configs, keyed by (profile_name, symbol)."""

    def __init__(self, ttl_seconds: int = 300):
        self.logger = log_manager.get_logger("SymbolConfigCache")
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[Tuple[str, str], CachedSymbolConfig] = {}
        self._loaded_at: float = 0.0
        self._lock = threading.RLock()

    # -- reads -------------------------------------------------------------

    def get(self, profile_name: str, symbol: str) -> Optional[CachedSymbolConfig]:
        """Config for one (profile, symbol), or None if there isn't an enabled one.

        A missing key is a real answer, not a cache miss — the table is loaded
        whole, so "absent" means no enabled row exists. That matters: symbols
        with no config are the common case on the sizing path, and re-querying
        each one is what made this hot.
        """
        self._refresh_if_stale()
        with self._lock:
            return self._cache.get((profile_name, symbol))

    def is_loaded(self) -> bool:
        with self._lock:
            return self._loaded_at > 0.0

    # -- loading -----------------------------------------------------------

    def _refresh_if_stale(self) -> None:
        with self._lock:
            fresh = (time.time() - self._loaded_at) < self.ttl_seconds
            if self._loaded_at > 0.0 and fresh:
                return
        self.refresh()

    def refresh(self) -> None:
        """Reload every enabled row in one query.

        A failure leaves the previous contents in place: serving a slightly
        stale order size beats refusing to size any trade because the DB
        blipped. The stamp is only advanced on success, so the next read
        retries.
        """
        # Imported here so db.crud can invalidate this cache without a cycle.
        from db.models import SymbolConfig
        from db.utils import get_db_session

        try:
            with get_db_session() as db:
                rows = (
                    db.query(SymbolConfig)
                    .filter(SymbolConfig.enabled == True)  # noqa: E712 — SQL, not Python
                    .all()
                )
                loaded = {
                    (r.profile_name, r.symbol): CachedSymbolConfig(
                        profile_name=r.profile_name,
                        symbol=r.symbol,
                        order_size_usdc=r.order_size_usdc,
                        max_position_size_pct=r.max_position_size_pct,
                    )
                    for r in rows
                }
        except Exception as e:  # noqa: BLE001 — must never break position sizing
            self.logger.error(f"SymbolConfigCache refresh failed, keeping previous: {e}")
            return

        with self._lock:
            self._cache = loaded
            self._loaded_at = time.time()
        self.logger.debug(f"SymbolConfigCache loaded {len(loaded)} enabled config(s)")

    def invalidate(self) -> None:
        """Force the next read to reload. Call after any write to symbol_configs."""
        with self._lock:
            self._loaded_at = 0.0


_symbol_config_cache: Optional[SymbolConfigCache] = None
_init_lock = threading.Lock()


def get_symbol_config_cache() -> SymbolConfigCache:
    global _symbol_config_cache
    if _symbol_config_cache is None:
        with _init_lock:
            if _symbol_config_cache is None:
                _symbol_config_cache = SymbolConfigCache()
    return _symbol_config_cache
