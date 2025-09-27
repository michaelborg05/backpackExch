"""
Data models for price information
"""
from dataclasses import dataclass
from typing import Optional, List, Tuple, Any, Dict
from utils import data_converters
import time


@dataclass
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
    