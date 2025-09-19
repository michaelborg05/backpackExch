"""API endpoints"""

class APIEndpoints:
    """Centralized API endpoint definitions"""
    BACKPACK_BASE  = "https://api.backpack.exchange"
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"
    

    @classmethod
    def backpack_ticker(cls, ticker: str = "SOL_USDC") -> str:
        """backpack price endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/ticker?symbol={ticker}&interval=1d"
    
    @classmethod
    def binance_ticker(cls, symbol: str = "SOLUSDT") -> str:
        """Binance ticker endpoint"""
        return f"{cls.BINANCE_BASE}/ticker/price?symbol={symbol}"

