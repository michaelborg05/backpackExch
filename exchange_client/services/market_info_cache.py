# services/market_info_cache.py
import threading
from typing import Optional, Dict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from utils.logging import log_manager


def _safe_decimal(value: any, default: str = "0") -> Decimal:
    """
    Safely convert value to Decimal, handling NULL, None, and invalid values
    
    Args:
        value: Value to convert (could be string, number, None, or "NULL")
        default: Default value if conversion fails
        
    Returns:
        Decimal value
    """
    if value is None or value == "NULL" or value == "null" or value == "":
        return Decimal(default)
    
    try:
        return Decimal(str(value))
    except (ValueError, InvalidOperation):
        return Decimal(default)
    
class MarketInfo:
    """Market trading rules and filters"""
    def __init__(self, data: dict):
        self.symbol = data.get("symbol")
        self.base_symbol = data.get("baseSymbol")
        self.quote_symbol = data.get("quoteSymbol")
        self.market_type = data.get("marketType")
        
        # Extract filters
        filters = data.get("filters", {})
        
        # Quantity filters
        qty_filter = filters.get("quantity", {})
        self.min_quantity = _safe_decimal(qty_filter.get("minQuantity", "0"))
        self.max_quantity = _safe_decimal(qty_filter.get("maxQuantity", "0"))
        self.step_size = _safe_decimal(qty_filter.get("stepSize", "0"))
        
        # Price filters
        price_filter = filters.get("price", {})
        self.min_price = _safe_decimal(price_filter.get("minPrice", "0"))
        self.max_price = _safe_decimal(price_filter.get("maxPrice", "0"))
        self.tick_size = _safe_decimal(price_filter.get("tickSize", "0"))
        
        self.order_book_state = data.get("orderBookState")
        self.visible = data.get("visible", True)
    

    def validate_quantity(self, quantity: Decimal) -> tuple[bool, Optional[str]]:
        """
        Validate if quantity meets market requirements
        
        Returns:
            (is_valid, error_message)
        """
        if quantity < self.min_quantity:
            return False, f"Qty {quantity} below min {self.min_quantity}"
        
        if self.max_quantity > 0 and quantity > self.max_quantity:
            return False, f"Qty {quantity} exceeds max {self.max_quantity}"
        
        # Check step size compliance
        if self.step_size > 0:
            remainder = quantity % self.step_size
            if remainder != 0:
                return False, f"Qty {quantity} does not comply with step size {self.step_size}"
        
        return True, None
    
    def validate_price(self, price: Decimal) -> tuple[bool, Optional[str]]:
        """
        Validate if price meets market requirements
        
        Returns:
            (is_valid, error_message)
        """
        if price < self.min_price:
            return False, f"Price {price} below min {self.min_price}"
        
        if self.max_price > 0 and price > self.max_price:
            return False, f"Price {price} exceeds max {self.max_price}"
        
        # Check tick size compliance
        if self.tick_size > 0:
            remainder = price % self.tick_size
            if remainder != 0:
                return False, f"Price {price} does not comply with tick size {self.tick_size}"
        
        return True, None
    
    def round_quantity(self, quantity: Decimal) -> Decimal:
        """Round quantity to comply with step size"""
        if self.step_size <= 0:
            return quantity
        
        # Round down to nearest step size
        return (quantity // self.step_size) * self.step_size

    def round_price(self, price: Decimal) -> Decimal:
        """Round price to comply with tick size"""
        if self.tick_size <= 0:
            return price
        
        # Round to nearest tick size
        return (price // self.tick_size) * self.tick_size
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "symbol": self.symbol,
            "base_symbol": self.base_symbol,
            "quote_symbol": self.quote_symbol,
            "market_type": self.market_type,
            "min_quantity": str(self.min_quantity),
            "max_quantity": str(self.max_quantity),
            "step_size": str(self.step_size),
            "min_price": str(self.min_price),
            "max_price": str(self.max_price),
            "tick_size": str(self.tick_size),
            "order_book_state": self.order_book_state,
            "visible": self.visible
        }


class MarketInfoCache:
    """
    Thread-safe cache for market trading rules
    Stores market info like step size, min quantity, tick size, etc.
    """
    
    def __init__(self):
        self.logger = log_manager.get_logger("MarketInfoCache")
        self._cache: Dict[str, MarketInfo] = {}
        self._lock = threading.RLock()
        self._last_update: Optional[datetime] = None
    
    def update_market(self, market_data: dict):
        """
        Update market info for a single symbol
        
        Args:
            market_data: Market data from API
        """
        with self._lock:
            try:
                market_info = MarketInfo(market_data)
                self._cache[market_info.symbol] = market_info
                self._last_update = datetime.now()
                self.logger.debug(f"Updated market info for {market_info.symbol}")
            except Exception as e:
                self.logger.error(f"Error updating market info: {e}")
    
    def update_markets(self, markets_data: list):
        """
        Update multiple markets at once
        
        Args:
            markets_data: List of market data from API
        """
        with self._lock:
            for market_data in markets_data:
                self.update_market(market_data)
    
    def get_market_info(self, symbol: str) -> Optional[MarketInfo]:
        """
        Get market info for a symbol
        
        Args:
            symbol: Trading pair symbol (e.g., "SOL_USDC")
            
        Returns:
            MarketInfo object or None if not found
        """
        with self._lock:
            if symbol not in self._cache:
                self.logger.warning(f"Market info for {symbol} not found in cache")
                return None
            return self._cache[symbol]
    
    def get_all_markets(self) -> Dict[str, MarketInfo]:
        """Get all market info from cache"""
        with self._lock:
            return self._cache.copy()
    
    def get_cache_info(self) -> dict:
        """Get cache metadata"""
        with self._lock:
            return {
                "market_count": len(self._cache),
                "last_update": self._last_update.isoformat() if self._last_update else None,
                "markets": list(self._cache.keys())
            }
    
    def clear(self):
        """Clear the cache"""
        with self._lock:
            self._cache.clear()
            self._last_update = None
            self.logger.info("Market info cache cleared")


# Global instance
_market_info_cache = MarketInfoCache()


def get_market_info_cache() -> MarketInfoCache:
    """Get the global market info cache instance"""
    return _market_info_cache



