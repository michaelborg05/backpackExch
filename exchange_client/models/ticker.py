"""
Data models for price information
"""
from dataclasses import dataclass
from typing import Optional, List, Tuple, Any, Dict
from utils import data_converters
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
        RED =    '\033[31m'
        GREEN =  '\033[32m'
        RESET =  '\033[0m'
        YELLOW = '\033[33m'
        BLUE =   '\033[34m'

        if not self.is_valid():
            return "No price data available"
        
        results = f"{self.symbol} Price Summary ({data_converters.timestamp_to_readable(self.timestamp)}):\n" 
        results +=     f"  Current Price: {data_converters.convert_to_price(self.last_price)}"
        if self.high is not None:
            results += f"     High: {data_converters.convert_to_price(self.high)}\n" 
        if self.first_price is not None:
            results += f"    First Price: {data_converters.convert_to_price(self.first_price)}"
        if self.low is not None:                       
            results += f"     Low: {data_converters.convert_to_price((self.low))}\n"
        if self.price_change is not None:
            if data_converters.convert_to_float(self.price_change) >= 0:
                results += GREEN
            else:
                results += RED
            results += f"   Price Change: {data_converters.convert_to_price(self.price_change)} " 
        price_change_percent_float = data_converters.convert_to_percent(self.price_change_percent)
        if price_change_percent_float is not None:
            sign = "+" if price_change_percent_float >= 0 else ""
            results += f" ({sign}{price_change_percent_float:.2f}%)\n"
        results += RESET
        #if self.trades is not None:
        #    results += f"         Trades: {self.trades}\n" 
        #if self.volume is not None:
        #    results += f"         Volume: {data_converter.convert_volume(self.volume, self.first_price)}\n" 
        
        return results

class TickerDepth:
    """Order book depth with top 10 bids and asks
    """
    def __init__(self):
        self.bids = []  # List of (price, quantity) tuples
        self.asks = []  # List of (price, quantity) tuples      
    def add_bid(self, price: float, quantity: float):
        self.bids.append((price, quantity))
        self.bids.sort(key=lambda x: x[0], reverse=True)  # Highest price first
        if len(self.bids) > 2:  # Keep only top 10 bids
            self.bids = self.bids[:2]  
    
    def add_ask(self, price: float, quantity: float):
        self.asks.append((price, quantity))
        self.asks.sort(key=lambda x: x[0])  # Lowest price first
        if len(self.asks) > 2:
            self.asks = self.asks[:2]

    @classmethod
    def from_api_response(cls, data: Any, price_key_index: int = 0, quantity_key_index: int = 1) -> 'TickerDepth':
        """Create a TickerDepth from an API orderbook response.

        Expected common formats:
        - {'bids': [[price, qty], ...], 'asks': [[price, qty], ...]}
        - {'data': {'bids': [...], 'asks': [...]}}

        price_key_index/quantity_key_index control which index in the inner list maps to price/qty.
        """
        td = cls()
        # Navigate common wrappers
        if isinstance(data, dict) and 'data' in data and isinstance(data['data'], dict):
            data = data['data']

        bids = []
        asks = []
        if isinstance(data, dict):
            bids = data.get('bids', [])
            asks = data.get('asks', [])

        # Parse bids
        for item in bids:
            try:
                price = float(item[price_key_index])
                qty = float(item[quantity_key_index])
                td.add_bid(price, qty)
            except Exception:
                continue

        # Parse asks
        for item in asks:
            try:
                price = float(item[price_key_index])
                qty = float(item[quantity_key_index])
                td.add_ask(price, qty)
            except Exception:
                continue

        return td

    def to_dict(self) -> Dict[str, List[Tuple[float, float]]]:
        return {
            'bids': self.bids,
            'asks': self.asks,
        }

    def formatted_summary(self) -> str:
        lines = ["Top bids:"]
        for p, q in self.bids:
            lines.append(f"  {p:.6f} x {q}")
        lines.append("Top asks:")
        for p, q in self.asks:
            lines.append(f"  {p:.6f} x {q}")
        return "\n".join(lines)
    