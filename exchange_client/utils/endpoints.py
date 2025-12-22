from utils.data_converters import get_utc_timestamp_seconds
"""API endpoints"""

class APIEndpoints:
    """Centralized API endpoint definitions"""
    BACKPACK_BASE  = "https://api.backpack.exchange"
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"
    

    @classmethod
    def backpack_ticker(cls, ticker: str = "SOL_USDC", interval: str = "1d") -> str:
        """backpack price endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/ticker?symbol={ticker}&interval={interval}"
    
    @classmethod
    def backpack_balances(cls) -> str:
        """Backpack balances endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/capital"


    def backpack_depth(cls, ticker: str = "SOL_USDC") -> str:
        """backpack depth endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/depth?symbol={ticker}"

    def backpack_klines(cls, ticker: str = "SOL_USDC", interval: str = "4h",startTime: str = None) -> str:
        """backpack klines endpoint"""
        if startTime is None:
            startTime = get_utc_timestamp_seconds() - 86400  # 24 hours ago
        return f"{cls.BACKPACK_BASE}/api/v1/klines?symbol={ticker}&interval={interval}&startTime={startTime}"

    @classmethod
    def backpack_ExecuteOrder(cls) -> str:
        """Backpack Execute Order endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/order"

    @classmethod
    def backpack_GetOpenOrders(cls) -> str:
        """Backpack Execute Order endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/orders"
