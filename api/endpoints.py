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

