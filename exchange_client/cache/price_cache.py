import threading
from typing import Optional, Dict
from datetime import datetime, timedelta
from decimal import Decimal
from utils.logging import log_manager


class PriceCache:
    """
    Thread-safe in-memory cache for asset prices
    Stores latest price data retrieved by monitoring service
    """
    
    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize price cache
        
        Args:
            ttl_seconds: Time-to-live for cached data in seconds (default 5 min)
        """
        self.logger = log_manager.get_logger("PriceCache")
        self._cache: Dict[str, Decimal] = {}  # {symbol: price}
        self._lock = threading.RLock()
        self._last_update: Dict[str, datetime] = {}  # {symbol: timestamp}
        self.ttl_seconds = ttl_seconds
    
    def update_price(self, symbol: str, price: str):
        """
        Update price for a single symbol
        
        Args:
            symbol: Symbol (e.g., "SOL_USDC")
            price: Price as string
        """
        with self._lock:
            try:
                self._cache[symbol] = Decimal(price)
                self._last_update[symbol] = datetime.now()
                self.logger.debug(f"Updated price for {symbol}: {price}")
            except Exception as e:
                self.logger.error(f"Error updating price for {symbol}: {e}")
    
    def update_prices(self, prices: Dict[str, str]):
        """
        Update multiple prices at once
        
        Args:
            prices: Dict of {symbol: price}
        """
        with self._lock:
            for symbol, price in prices.items():
                self.update_price(symbol, price)
    
    def get_price(self, symbol: str) -> Optional[Decimal]:
        """
        Get price for a symbol
        
        Args:
            symbol: Symbol (e.g., "SOL_USDC")
            
        Returns:
            Price as Decimal, or None if not found or stale
        """
        with self._lock:
            if symbol not in self._cache:
                self.logger.warning(f"Symbol {symbol} not found in cache")
                return None
            
            # Check if price is stale
            if not self._is_valid(symbol):
                self.logger.warning(f"Price for {symbol} is stale")
                return None
            
            return self._cache[symbol]
    
    def get_all_prices(self) -> Dict[str, Decimal]:
        """Get all prices from cache"""
        with self._lock:
            # Return only non-stale prices
            return {
                symbol: price
                for symbol, price in self._cache.items()
                if self._is_valid(symbol)
            }
    
    def _is_valid(self, symbol: str) -> bool:
        """Check if price is valid (not stale)"""
        if symbol not in self._last_update:
            return False
        
        age = (datetime.now() - self._last_update[symbol]).total_seconds()
        return age <= self.ttl_seconds
    
    def get_cache_info(self) -> Dict:
        """Get cache metadata"""
        with self._lock:
            return {
                "symbol_count": len(self._cache),
                "valid_count": len([s for s in self._cache if self._is_valid(s)]),
                "ttl_seconds": self.ttl_seconds
            }
    
    def clear(self):
        """Clear the cache"""
        with self._lock:
            self._cache.clear()
            self._last_update.clear()
            self.logger.info("Price cache cleared")


# Global instance
_price_cache = PriceCache()


def get_price_cache() -> PriceCache:
    """Get the global price cache instance"""
    return _price_cache
