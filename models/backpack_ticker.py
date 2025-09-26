"""
Data models for price information
"""
from dataclasses import dataclass
from typing import Optional
from utils import data_converter
import time


@dataclass
class BackpackTicker:
    symbol: str
    high: Optional[float] = None
    first_price: Optional[float] = None
    last_price: Optional[float] = None
    low: Optional[float] = None
    price_change: Optional[float] = None
    price_change_percent: Optional[float] = None
    timestamp: Optional[int] = None
    trades: Optional[int] = None
    volume: Optional[float] = None

    def is_valid(self) -> bool:
        return self.current_price is not None
    
    def __post_init__(self):
        """Validation after initialization"""
        if self.timestamp is None:
            self.timestamp = int(time.time())
        
    def is_valid(self) -> bool:
        """Check if essential price data is available"""
        return self.last_price is not None
    
    def price_change(self) -> Optional[float]:
        """Calculate absolute price change from first to current"""
        if self.last_price and self.first_price:
            return self.last_price - self.first_price
        return None
    
    def formatted_summary(self) -> str:
        if not self.is_valid():
            return "No price data available"
        
        results = f"{self.symbol} Price Summary ({data_converter.timestamp_to_readable(self.timestamp)}):\n" 
        results +=     f"  Current Price: {data_converter.convert_to_price(self.last_price)}\n"
        if self.first_price is not None:
            results += f"    First Price: {data_converter.convert_to_price(self.first_price)}\n"
        if self.high is not None:
            results += f"           High: {data_converter.convert_to_price(self.high)}\n" 
        if self.low is not None:                       
            results += f"            Low: {data_converter.convert_to_price((self.low))}\n"
        if self.price_change is not None:
            results += f"   Price Change: {data_converter.convert_to_price(self.price_change)} " 
        price_change_percent_float = data_converter.convert_to_percent(self.price_change_percent)
        if price_change_percent_float is not None:
            sign = "+" if price_change_percent_float >= 0 else ""
            results += f" ({sign}{price_change_percent_float:.2f}%)\n"
        if self.trades is not None:
            results += f"         Trades: {self.trades}\n" 
        if self.volume is not None:
            results += f"         Volume: {data_converter.convert_volume(self.volume, self.first_price)}\n" 
        
        return results
    