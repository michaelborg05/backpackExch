# services/atr_cache.py
import threading
from typing import Optional, Dict, List
from datetime import datetime
from decimal import Decimal
from collections import deque
from utils.logging import log_manager


class ATRData:
    """ATR and SMA data for a symbol/timeframe"""
    
    def __init__(
        self,
        symbol: str,
        timeframe: str,
        atr: Decimal,
        atr_sma: Decimal,
        atr_period: int = 14,
        sma_period: int = 50
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.atr = atr
        self.atr_sma = atr_sma
        self.atr_period = atr_period
        self.sma_period = sma_period
        self.timestamp = datetime.now()
    
    def is_volatile(self, threshold: float = 1.05) -> bool:
        """Check if ATR > ATR_SMA * threshold"""
        if self.atr_sma == 0:
            return False
        return self.atr > (self.atr_sma * Decimal(str(threshold)))
    
    def get_ratio(self) -> Optional[Decimal]:
        """Get ATR/ATR_SMA ratio"""
        if self.atr_sma == 0:
            return None
        return self.atr / self.atr_sma
    
    def to_dict(self) -> dict:
        ratio = self.get_ratio()
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "atr": str(self.atr),
            "atr_sma": str(self.atr_sma),
            "atr_period": self.atr_period,
            "sma_period": self.sma_period,
            "ratio": str(ratio) if ratio else None,
            "is_volatile": self.is_volatile(),
            "timestamp": self.timestamp.isoformat()
        }


class ATRCache:
    """
    Thread-safe cache for ATR data
    Stores ATR values calculated from exchange candle data
    """
    
    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize ATR cache
        
        Args:
            ttl_seconds: Time-to-live for cached data (default 5 min)
        """
        self.logger = log_manager.get_logger("ATRCache")
        self._cache: Dict[str, ATRData] = {}  # key: "SYMBOL_TIMEFRAME"
        self._lock = threading.RLock()
        self._history_counts: Dict[str, int] = {}  # Track how many ATR values we have
        self.ttl_seconds = ttl_seconds
    
    def update(self, atr_data: ATRData, history_count: Optional[int] = None):
        """
        Update ATR data for a symbol/timeframe
        
        Args:
            atr_data: ATR data object
            history_count: Number of ATR values in history (for tracking SMA readiness)
        """
        with self._lock:
            key = f"{atr_data.symbol}_{atr_data.timeframe}"
            self._cache[key] = atr_data
            
            if history_count is not None:
                self._history_counts[key] = history_count
            
            # Check if SMA is fully ready
            sma_status = "READY"
            if history_count and history_count < atr_data.sma_period:
                sma_status = f"BUILDING ({history_count}/{atr_data.sma_period})"
            
            self.logger.debug(
                f"Updated ATR for {atr_data.symbol} ({atr_data.timeframe}): "
                f"ATR={atr_data.atr:.6f}, SMA={atr_data.atr_sma:.6f} [{sma_status}], "
                f"Ratio={atr_data.get_ratio():.2f}, "
                f"Volatile={atr_data.is_volatile()}"
            )
    
    def get(self, symbol: str, timeframe: str) -> Optional[ATRData]:
        """Get ATR data for a symbol/timeframe"""
        with self._lock:
            key = f"{symbol}_{timeframe}"
            
            if key not in self._cache:
                return None
            
            atr_data = self._cache[key]
            
            # Check if stale
            age = (datetime.now() - atr_data.timestamp).total_seconds()
            if age > self.ttl_seconds:
                self.logger.warning(
                    f"ATR data for {symbol} ({timeframe}) is stale "
                    f"({age:.0f}s old)"
                )
                return None
            
            return atr_data
    
    def is_volatile(
        self, 
        symbol: str, 
        timeframe: str, 
        threshold: float = 1.05
    ) -> tuple[bool, Optional[str]]:
        """
        Check if market is currently volatile
        
        Returns:
            (is_volatile, reason) tuple
        """
        atr_data = self.get(symbol, timeframe)
        
        if atr_data is None:
            return False, f"No ATR data for {symbol} ({timeframe})"
        
        is_vol = atr_data.is_volatile(threshold)
        ratio = atr_data.get_ratio()
        
        if is_vol:
            return True, f"High volatility: ATR/SMA = {ratio:.2f} (threshold: {threshold})"
        else:
            return False, f"Normal volatility: ATR/SMA = {ratio:.2f} (threshold: {threshold})"
    
    def get_all(self) -> Dict[str, ATRData]:
        """Get all ATR data from cache"""
        with self._lock:
            return self._cache.copy()
    
    def get_cache_info(self) -> dict:
        """Get cache metadata"""
        with self._lock:
            return {
                "entries": len(self._cache),
                "ttl_seconds": self.ttl_seconds,
                "data": {
                    key: data.to_dict() 
                    for key, data in self._cache.items()
                }
            }
    
    def clear(self):
        """Clear the cache"""
        with self._lock:
            self._cache.clear()
            self.logger.info("ATR cache cleared")


# Global instance
_atr_cache = None


def get_atr_cache() -> ATRCache:
    """Get or create global ATR cache"""
    global _atr_cache
    if _atr_cache is None:
        _atr_cache = ATRCache()
    return _atr_cache