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

    @classmethod
    def backpack_depth(cls, ticker: str = "SOL_USDC") -> str:
        """backpack depth endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/depth?symbol={ticker}"
    
    @classmethod
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
    def backpack_GetOpenOrders(cls, marketType: str = "SPOT") -> str:
        """Backpack Open Orders endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/orders?marketType={marketType}"

    @classmethod
    def backpack_GetOrderHistory(cls, symbol: str = None, order_id: str = None) -> str:
        """Backpack Order History endpoint"""
        if symbol is None and order_id is None:
            return f"{cls.BACKPACK_BASE}/wapi/v1/history/orders"
        elif symbol is not None and order_id is not None:
            return f"{cls.BACKPACK_BASE}/wapi/v1/history/orders?symbol={symbol}&orderId={order_id}"
        elif symbol is not None:
            return f"{cls.BACKPACK_BASE}/wapi/v1/history/orders?symbol={symbol}"
        else:
            return f"{cls.BACKPACK_BASE}/wapi/v1/history/orders?orderId={order_id}"


    @classmethod
    def backpack_GetSingleOrder(cls, symbol: str, order_id: str) -> str:
        """Backpack Single Order endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/order?orderId={order_id}&symbol={symbol}"

    @classmethod
    def backpack_MarketInfo(cls, symbol: str = "SOL_USDC") -> str:
        """Backpack Market Info endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/market?symbol={symbol}"

    @classmethod
    def backpack_Markets(cls) -> str:
        """Backpack Markets endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/markets"

    @classmethod
    def backpack_convert_dust(cls) -> str:
        """Backpack Convert Dust endpoint"""
        return f"{cls.BACKPACK_BASE}/api/v1/account/convertDust"