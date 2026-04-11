from utils.data_converters import get_utc_timestamp_seconds
"""API endpoints — per-exchange classes with a factory function.

Usage:
    from utils.endpoints import get_endpoints
    ep = get_endpoints("backpack")
    url = ep.ticker("SOL_USDC")

Backward compat:
    from utils.endpoints import APIEndpoints   # still works, points at BackpackEndpoints
"""


class BackpackEndpoints:
    """Backpack Exchange endpoint definitions."""
    BASE = "https://api.backpack.exchange"

    @classmethod
    def ticker(cls, symbol: str = "SOL_USDC", interval: str = "1d") -> str:
        return f"{cls.BASE}/api/v1/ticker?symbol={symbol}&interval={interval}"

    @classmethod
    def balances(cls) -> str:
        return f"{cls.BASE}/api/v1/capital"

    @classmethod
    def depth(cls, symbol: str = "SOL_USDC", limit: str = None) -> str:
        url = f"{cls.BASE}/api/v1/depth?symbol={symbol}"
        if limit:
            url += f"&limit={limit}"
        return url

    @classmethod
    def klines(cls, symbol: str = "SOL_USDC", interval: str = "4h", start_time: int = None) -> str:
        if start_time is None:
            start_time = get_utc_timestamp_seconds() - 86400
        return f"{cls.BASE}/api/v1/klines?symbol={symbol}&interval={interval}&startTime={start_time}"

    @classmethod
    def execute_order(cls) -> str:
        return f"{cls.BASE}/api/v1/order"

    @classmethod
    def open_orders(cls, market_type: str = "SPOT", symbol: str = None) -> str:
        if symbol is not None:
            return f"{cls.BASE}/api/v1/orders?marketType={market_type}&symbol={symbol}"
        return f"{cls.BASE}/api/v1/orders?marketType={market_type}"

    @classmethod
    def order_history(cls, symbol: str = None, order_id: str = None) -> str:
        if symbol is None and order_id is None:
            return f"{cls.BASE}/wapi/v1/history/orders"
        elif symbol is not None and order_id is not None:
            return f"{cls.BASE}/wapi/v1/history/orders?symbol={symbol}&orderId={order_id}"
        elif symbol is not None:
            return f"{cls.BASE}/wapi/v1/history/orders?symbol={symbol}"
        else:
            return f"{cls.BASE}/wapi/v1/history/orders?orderId={order_id}"

    @classmethod
    def single_order(cls, symbol: str, order_id: str) -> str:
        return f"{cls.BASE}/api/v1/order?orderId={order_id}&symbol={symbol}"

    @classmethod
    def cancel_order(cls) -> str:
        return f"{cls.BASE}/api/v1/order"

    @classmethod
    def market_info(cls, symbol: str = "SOL_USDC") -> str:
        return f"{cls.BASE}/api/v1/market?symbol={symbol}"

    @classmethod
    def markets(cls) -> str:
        return f"{cls.BASE}/api/v1/markets"

    @classmethod
    def convert_dust(cls) -> str:
        return f"{cls.BASE}/api/v1/account/convertDust"

    # ── Legacy aliases (old callers used backpack_* names) ──────────────────
    @classmethod
    def backpack_ticker(cls, ticker: str = "SOL_USDC", interval: str = "1d") -> str:
        return cls.ticker(ticker, interval)

    @classmethod
    def backpack_balances(cls) -> str:
        return cls.balances()

    @classmethod
    def backpack_depth(cls, ticker: str = "SOL_USDC", limit: str = None) -> str:
        return cls.depth(ticker, limit)

    @classmethod
    def backpack_klines(cls, ticker: str = "SOL_USDC", interval: str = "4h", startTime: int = None) -> str:
        return cls.klines(ticker, interval, startTime)

    @classmethod
    def backpack_ExecuteOrder(cls) -> str:
        return cls.execute_order()

    @classmethod
    def backpack_GetOpenOrders(cls, marketType: str = "SPOT", symbol: str = None) -> str:
        return cls.open_orders(marketType, symbol)

    @classmethod
    def backpack_GetOrderHistory(cls, symbol: str = None, order_id: str = None) -> str:
        return cls.order_history(symbol, order_id)

    @classmethod
    def backpack_GetSingleOrder(cls, symbol: str, order_id: str) -> str:
        return cls.single_order(symbol, order_id)

    @classmethod
    def backpack_CancelOrder(cls) -> str:
        return cls.cancel_order()

    @classmethod
    def backpack_MarketInfo(cls, symbol: str = "SOL_USDC") -> str:
        return cls.market_info(symbol)

    @classmethod
    def backpack_Markets(cls) -> str:
        return cls.markets()

    @classmethod
    def backpack_convert_dust(cls) -> str:
        return cls.convert_dust()


class BulletEndpoints:
    """Bullet Exchange endpoint definitions (perpetuals DEX, Binance FAPI-compatible).

    Authentication for reads:  pass ?address=<wallet_address> as a query param — no headers.
    Authentication for writes: POST /tx/submit with a Borsh-serialised, Ed25519-signed tx.

    Symbol format: "SOL-USD", "BTC-USD" (NOT "SOL_USDC").
    All markets are perpetual futures.
    """
    BASE = "https://tradingapi.mainnet.bullet.xyz"
    TESTNET = "https://tradingapi.testnet.bullet.xyz"

    @classmethod
    def ticker(cls, symbol: str = None) -> str:
        """Current mark price(s). Returns a list when symbol is omitted."""
        if symbol:
            return f"{cls.BASE}/fapi/v1/ticker/price?symbol={symbol}"
        return f"{cls.BASE}/fapi/v1/ticker/price"

    @classmethod
    def ticker_24hr(cls, symbol: str = None) -> str:
        """24-hour rolling statistics."""
        if symbol:
            return f"{cls.BASE}/fapi/v1/ticker/24hr?symbol={symbol}"
        return f"{cls.BASE}/fapi/v1/ticker/24hr"

    @classmethod
    def depth(cls, symbol: str = "SOL-USD", limit: int = 20) -> str:
        return f"{cls.BASE}/fapi/v1/depth?symbol={symbol}&limit={limit}"

    @classmethod
    def exchange_info(cls) -> str:
        """All symbols, filters, fee tiers — replaces Backpack /markets."""
        return f"{cls.BASE}/fapi/v1/exchangeInfo"

    @classmethod
    def funding_rate(cls, symbol: str = None) -> str:
        if symbol:
            return f"{cls.BASE}/fapi/v1/fundingRate?symbol={symbol}"
        return f"{cls.BASE}/fapi/v1/fundingRate"

    @classmethod
    def open_interest(cls) -> str:
        return f"{cls.BASE}/fapi/v1/openInterest"

    @classmethod
    def balance(cls, address: str) -> str:
        """Account USDC collateral balance. No auth headers — address IS the auth."""
        return f"{cls.BASE}/fapi/v3/balance?address={address}"

    @classmethod
    def account(cls, address: str) -> str:
        """Full account state: positions, unrealised PnL, margin info."""
        return f"{cls.BASE}/fapi/v3/account?address={address}"

    @classmethod
    def open_orders(cls, symbol: str, address: str) -> str:
        return f"{cls.BASE}/fapi/v1/openOrders?symbol={symbol}&address={address}"

    @classmethod
    def single_order(cls, symbol: str, address: str, order_id: str = None, client_order_id: str = None) -> str:
        url = f"{cls.BASE}/fapi/v1/openOrder?symbol={symbol}&address={address}"
        if order_id:
            url += f"&orderId={order_id}"
        if client_order_id:
            url += f"&clientOrderId={client_order_id}"
        return url

    @classmethod
    def order_history(cls, address: str, symbol: str = None, order_id: str = None,
                      start_time: int = None, end_time: int = None, limit: int = None) -> str:
        url = f"{cls.BASE}/fapi/v1/allOrders?address={address}"
        if symbol:
            url += f"&symbol={symbol}"
        if order_id:
            url += f"&orderId={order_id}"
        if start_time:
            url += f"&startTime={start_time}"
        if end_time:
            url += f"&endTime={end_time}"
        if limit:
            url += f"&limit={limit}"
        return url

    @classmethod
    def user_trades(cls, address: str, symbol: str = None) -> str:
        url = f"{cls.BASE}/fapi/v1/userTrades?address={address}"
        if symbol:
            url += f"&symbol={symbol}"
        return url

    @classmethod
    def submit_tx(cls) -> str:
        """Submit a Borsh-serialised, Ed25519-signed transaction (place/cancel order)."""
        return f"{cls.BASE}/tx/submit"

    @classmethod
    def rollup_schema(cls) -> str:
        """Transaction schema — useful for inspecting NewOrderArgs field layout."""
        return f"{cls.BASE}/rollup/schema"

    @classmethod
    def rollup_constants(cls) -> str:
        return f"{cls.BASE}/rollup/constants"

    @classmethod
    def leverage_bracket(cls, symbol: str = None) -> str:
        if symbol:
            return f"{cls.BASE}/fapi/v1/leverageBracket?symbol={symbol}"
        return f"{cls.BASE}/fapi/v1/leverageBracket"

    @classmethod
    def commission_rate(cls, address: str, symbol: str) -> str:
        return f"{cls.BASE}/fapi/v1/commissionRate?address={address}&symbol={symbol}"

    @classmethod
    def ping(cls) -> str:
        return f"{cls.BASE}/fapi/v1/ping"

    @classmethod
    def server_time(cls) -> str:
        return f"{cls.BASE}/fapi/v1/time"

    # Klines intentionally omitted — Bullet has no candle endpoint.
    # Use CoinGecko or derive from trades for ATR calculations.
    @classmethod
    def coingecko_ohlc(cls, coin_id: str = "solana", days: int = 1) -> str:
        """Fallback OHLC data from CoinGecko for ATR when klines unavailable."""
        return f"{cls.COINGECKO_BASE}/coins/{coin_id}/ohlc?vs_currency=usd&days={days}"


# ── Backward-compatibility alias ─────────────────────────────────────────────
# All existing callers that do `from utils.endpoints import APIEndpoints` continue
# to work without any changes. New code should use get_endpoints() or the class directly.
APIEndpoints = BackpackEndpoints


# ── Factory ──────────────────────────────────────────────────────────────────
_REGISTRY = {
    "backpack": BackpackEndpoints,
    "bullet": BulletEndpoints,
}


def get_endpoints(exchange_type: str):
    """Return the endpoint class for the given exchange type.

    Args:
        exchange_type: "backpack" or "bullet"

    Returns:
        BackpackEndpoints or BulletEndpoints (the class itself, not an instance)

    Raises:
        ValueError: if exchange_type is unknown
    """
    cls = _REGISTRY.get(exchange_type)
    if cls is None:
        raise ValueError(
            f"Unknown exchange type: {exchange_type!r}. "
            f"Valid options: {list(_REGISTRY.keys())}"
        )
    return cls
