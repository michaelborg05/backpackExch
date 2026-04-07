# services/balance_cache.py
import threading
from typing import Optional, Dict
from datetime import datetime, timedelta
from decimal import Decimal
from utils.logging import log_manager


class BalanceCache:
    """
    Thread-safe in-memory cache for account balances.
    Stores balances keyed by account_key (f"account_{id}" or profile_name fallback).
    Maintains a profile_name → account_key mapping so per-profile lookups still work.
    """

    def __init__(self, ttl_seconds: int = 300):
        self.logger = log_manager.get_logger("BalanceCache")
        self._cache: Dict[str, Dict[str, Dict]] = {}  # {account_key: {asset: balance_info}}
        self._profile_to_account: Dict[str, str] = {}  # profile_name → account_key
        self._lock = threading.Lock()
        self._last_update: Dict[str, datetime] = {}  # {account_key: last_update_time}
        self.ttl_seconds = ttl_seconds

    def _make_account_key(self, account_id: Optional[int], profile_name: str) -> str:
        """Compute the cache key: account-based when possible, profile-name fallback."""
        return f"account_{account_id}" if account_id else profile_name

    def update_profile_balances(self, profile_name: str, balances: Dict[str, Dict], account_id: Optional[int] = None):
        """Update balances for a profile (internally stored by account key)."""
        account_key = self._make_account_key(account_id, profile_name)
        with self._lock:
            self._cache[account_key] = balances
            self._last_update[account_key] = datetime.utcnow()
            self._profile_to_account[profile_name] = account_key

    def register_profile_account(self, profile_name: str, account_key: str):
        """Register a profile→account mapping without writing balance data.
        Used when multiple profiles share the same exchange account."""
        with self._lock:
            self._profile_to_account[profile_name] = account_key

    def get_profile_balances(self, profile_name: str) -> Optional[Dict[str, Dict]]:
        """Get balances for a specific profile (resolves to account key)."""
        with self._lock:
            account_key = self._profile_to_account.get(profile_name, profile_name)
            return self._cache.get(account_key)

    def get_account_balances(self, account_key: str) -> Optional[Dict[str, Dict]]:
        """Get balances directly by account key (e.g. 'account_1')."""
        with self._lock:
            return self._cache.get(account_key)

    def get_profile_asset_balance(self, profile_name: str, asset: str = "USDC") -> Optional[Dict]:
        """Get balance for a specific asset in a profile."""
        with self._lock:
            account_key = self._profile_to_account.get(profile_name, profile_name)
            profile_balances = self._cache.get(account_key)
            if profile_balances:
                return profile_balances.get(asset)
            return None

    def get_available_balance(self, profile_name: str, asset: str) -> Optional[Decimal]:
        """Get available balance for an asset in a specific profile."""
        self.logger.debug(f"Retrieving available balance for asset '{asset}' in profile '{profile_name}'")
        with self._lock:
            account_key = self._profile_to_account.get(profile_name, profile_name)
            profile_balances = self._cache.get(account_key)
            if profile_balances:
                available = profile_balances.get(asset, {}).get("available", "0")
                self.logger.debug(f"Available balance for '{asset}' (account {account_key}): {available}")
                return Decimal(available)
            return None

    def update(self, balances: Dict[str, Dict]):
        """Update balances for default profile (backwards compatibility)."""
        self.update_profile_balances("default", balances)

    def get_all_profiles(self) -> Dict[str, Dict[str, Dict]]:
        """Get balances keyed by account_key (no duplicate data across shared accounts)."""
        with self._lock:
            return self._cache.copy()

    def get_all_accounts(self) -> Dict[str, Dict[str, Dict]]:
        """Get balances for all unique accounts (no duplicates). Alias for get_all_profiles."""
        with self._lock:
            return self._cache.copy()

    def get_cache_info(self) -> dict:
        """Get cache information."""
        with self._lock:
            return {
                "accounts": list(self._cache.keys()),
                "profile_mappings": dict(self._profile_to_account),
                "last_updates": {
                    key: update_time.isoformat()
                    for key, update_time in self._last_update.items()
                },
                "asset_counts": {
                    key: len(balances)
                    for key, balances in self._cache.items()
                }
            }

    def clear_profile(self, profile_name: str):
        """Clear cache for a profile. Removes account entry only if no other profile maps to it."""
        with self._lock:
            account_key = self._profile_to_account.pop(profile_name, profile_name)
            # Only remove account cache if no other profile maps to the same account
            if account_key not in self._profile_to_account.values():
                self._cache.pop(account_key, None)
                self._last_update.pop(account_key, None)


# Singleton pattern
_balance_cache = None

def get_balance_cache() -> BalanceCache:
    """Get the balance cache instance."""
    global _balance_cache
    if _balance_cache is None:
        _balance_cache = BalanceCache()
    return _balance_cache
