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
        self._cache: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        self._last_update: Optional[datetime] = None
        self.ttl_seconds = ttl_seconds
        
    def update(self, balances: Dict[str, Dict]):
        """
        Update the entire balance cache
        
        Args:
            balances: Dict of {asset: {available, locked, staked}}
        """
        with self._lock:
            self._cache = balances.copy()
            self._last_update = datetime.now()
            self.logger.debug(f"Balance cache updated with {len(balances)} assets")
    
    def get_available_balance(self, asset: str) -> Optional[Decimal]:
        """
        Get available balance for an asset
        
        Args:
            asset: Asset symbol (e.g., "USDC", "SOL")
            
        Returns:
            Available balance as Decimal, or None if not found
        """
        with self._lock:
            if not self._is_valid():
                self.logger.warning("Balance cache is stale or empty")
                return None
                
            if asset not in self._cache:
                self.logger.warning(f"Asset {asset} not found in cache")
                return None
            
            try:
                available = self._cache[asset].get("available", "0")
                return Decimal(available)
            except Exception as e:
                self.logger.error(f"Error parsing balance for {asset}: {e}")
                return None
    
    def get_all_balances(self) -> Optional[Dict[str, Dict]]:
        """Get all balances from cache"""
        with self._lock:
            if not self._is_valid():
                return None
            return self._cache.copy()
    
    def _is_valid(self) -> bool:
        """Check if cache is valid (not stale)"""
        if not self._cache or self._last_update is None:
            return False
        
        age = (datetime.now() - self._last_update).total_seconds()
        if age > self.ttl_seconds:
            self.logger.warning(f"Cache is stale (age: {age:.1f}s, TTL: {self.ttl_seconds}s)")
            return False
        
        return True
    
    def get_cache_info(self) -> Dict:
        """Get cache metadata"""
        with self._lock:
            return {
                "asset_count": len(self._cache),
                "last_update": self._last_update.isoformat() if self._last_update else None,
                "age_seconds": (datetime.now() - self._last_update).total_seconds() if self._last_update else None,
                "is_valid": self._is_valid(),
                "ttl_seconds": self.ttl_seconds
            }
    
    def clear(self):
        """Clear the cache"""
        with self._lock:
            self._cache.clear()
            self._last_update = None
            self.logger.info("Balance cache cleared")


# Global instance (singleton pattern)
_balance_cache = BalanceCache()


def get_balance_cache() -> BalanceCache:
    """Get the global balance cache instance"""
    return _balance_cache
