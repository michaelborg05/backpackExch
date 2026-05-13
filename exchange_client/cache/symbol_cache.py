import threading
from typing import Dict, List
from utils.logging import log_manager


class SymbolCache:
    """
    Thread-safe in-memory cache for active symbols.

    Two separate concerns:
      _monitored: flat list of all enabled symbols from monitored_symbols table.
                  Drives price fetching — includes symbols not yet assigned to any profile.
      _by_profile: {profile_name: [symbol, ...]} from symbol_configs.
                   Drives per-profile signal generation.
    """

    def __init__(self):
        self.logger = log_manager.get_logger("SymbolCache")
        self._monitored: List[str] = []
        self._by_profile: Dict[str, List[str]] = {}
        self._lock = threading.RLock()

    def refresh(self, db) -> None:
        """Reload both symbol lists from the database."""
        from db.models import SymbolConfig

        # Price-fetch list: all enabled monitored symbols
        try:
            from db.models import MonitoredSymbol
            monitored_rows = (
                db.query(MonitoredSymbol.symbol)
                .filter(MonitoredSymbol.enabled == True)
                .order_by(MonitoredSymbol.symbol)
                .all()
            )
            new_monitored = [r.symbol for r in monitored_rows]
        except Exception:
            # Migration hasn't run yet — fall back to symbol_configs
            new_monitored = []

        # Per-profile signal list: enabled symbol_configs only
        profile_rows = (
            db.query(SymbolConfig.profile_name, SymbolConfig.symbol)
            .filter(SymbolConfig.enabled == True)
            .all()
        )
        new_by_profile: Dict[str, List[str]] = {}
        for profile_name, symbol in profile_rows:
            new_by_profile.setdefault(profile_name, []).append(symbol)

        # Fall back if monitored_symbols table wasn't available
        if not new_monitored:
            seen: set = set()
            for syms in new_by_profile.values():
                for s in syms:
                    if s not in seen:
                        new_monitored.append(s)
                        seen.add(s)

        with self._lock:
            self._monitored = new_monitored
            self._by_profile = new_by_profile

        self.logger.debug(
            f"SymbolCache refreshed: {len(new_monitored)} monitored symbol(s), "
            f"{sum(len(v) for v in new_by_profile.values())} profile-symbol mapping(s)"
        )

    def get_symbols_for_profile(self, profile_name: str) -> List[str]:
        """Return active symbols for a single profile (from symbol_configs)."""
        with self._lock:
            return list(self._by_profile.get(profile_name, []))

    def get_all_symbols(self) -> List[str]:
        """Return all enabled monitored symbols (drives price fetching)."""
        with self._lock:
            return list(self._monitored)


_symbol_cache: SymbolCache = SymbolCache()


def get_symbol_cache() -> SymbolCache:
    return _symbol_cache
