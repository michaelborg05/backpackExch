# services/balance_cache.py
import threading
from typing import Optional, Dict
from datetime import datetime, timedelta
from decimal import Decimal
from utils.logging import log_manager


class BalanceCache:
    """
    Thread-safe in-memory cache for account balances
    Stores latest balance data retrieved by monitoring service
    """
    
    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize balance cache
        
        Args:
            ttl_seconds: Time-to-live for cached data in seconds (default 5 min)
        """
        self.logger = log_manager.get_logger("BalanceCache")
        self._cache: Dict[str, Dict[str, Dict]] = {}  # {profile_name: {asset: balance_info}}
        self._lock = threading.Lock()
        self._last_update: Dict[str, datetime] = {}  # {profile_name: last_update_time}
        self.ttl_seconds = ttl_seconds

    def update_profile_balances(self, profile_name: str, balances: Dict[str, Dict]):
        """Update balances for a specific profile"""
        with self._lock:
            self._cache[profile_name] = balances
            self._last_update[profile_name] = datetime.utcnow()
    
    def get_profile_balances(self, profile_name: str) -> Optional[Dict[str, Dict]]:
        """Get balances for a specific profile"""
        with self._lock:
            return self._cache.get(profile_name)

    def get_profile_asset_balance(self, profile_name: str, asset: str) -> Optional[Dict]:
        """Get balance for a specific asset in a profile"""
        with self._lock:
            profile_balances = self._cache.get(profile_name)
            if profile_balances:
                return profile_balances.get(asset)
            return None
                    
    def update(self, balances: Dict[str, Dict]):
        """Update balances for default profile (backwards compatibility)"""
        self.update_profile_balances("default", balances)
    
    def get_all_profiles(self) -> Dict[str, Dict[str, Dict]]:
        """Get balances for all profiles"""
        with self._lock:
            return self._cache.copy()
    
    def get_cache_info(self) -> dict:
        """Get cache information for all profiles"""
        with self._lock:
            return {
                "profiles": list(self._cache.keys()),
                "last_updates": {
                    profile: update_time.isoformat() 
                    for profile, update_time in self._last_update.items()
                },
                "asset_counts": {
                    profile: len(balances) 
                    for profile, balances in self._cache.items()
                }
            }
    
    def clear_profile(self, profile_name: str):
        """Clear cache for a specific profile"""
        with self._lock:
            self._cache.pop(profile_name, None)
            self._last_update.pop(profile_name, None)


# Singleton pattern
_balance_cache = None

def get_balance_cache() -> BalanceCache:
    """Get the balance cache instance"""
    global _balance_cache
    if _balance_cache is None:
        _balance_cache = BalanceCache()
    return _balance_cache
