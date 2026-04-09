import threading
from typing import Dict, List
from utils.logging import log_manager


class SymbolCache:
    """
    Thread-safe in-memory cache for active symbols per profile.
    Populated on startup and invalidated/refreshed when symbol configs are mutated via API.
    """

    def __init__(self):
        self.logger = log_manager.get_logger("SymbolCache")
        self._cache: Dict[str, List[str]] = {}  # {profile_name: [symbol, ...]}
        self._lock = threading.RLock()

    def refresh(self, db) -> None:
        """Reload all active symbols from the database."""
        from db.models import SymbolConfig
        rows = db.query(SymbolConfig.profile_name, SymbolConfig.symbol).filter(
            SymbolConfig.enabled == True
        ).all()

        new_cache: Dict[str, List[str]] = {}
        for profile_name, symbol in rows:
            new_cache.setdefault(profile_name, []).append(symbol)

        with self._lock:
            self._cache = new_cache

        self.logger.debug(
            f"SymbolCache refreshed: {sum(len(v) for v in new_cache.values())} "
            f"entries across {len(new_cache)} profiles"
        )

    def get_symbols_for_profile(self, profile_name: str) -> List[str]:
        """Return active symbols for a single profile."""
        with self._lock:
            return list(self._cache.get(profile_name, []))

    def get_all_symbols(self) -> List[str]:
        """Return deduplicated list of all active symbols across all profiles."""
        with self._lock:
            seen = set()
            result = []
            for symbols in self._cache.values():
                for s in symbols:
                    if s not in seen:
                        seen.add(s)
                        result.append(s)
            return result


_symbol_cache: SymbolCache = SymbolCache()


def get_symbol_cache() -> SymbolCache:
    return _symbol_cache
