import json
import time
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, Any
from urllib.parse import quote
from utils.config import Config
from models import BackpackTicker
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils.price_resolution import BookTop, book_top
from services.client import api_request
from cache.market_info_cache import get_market_info_cache

config = Config()
market_logger = log_manager.get_logger("MarketBuilder")

def check_ticker(endpoint: str) -> BackpackTicker:
    """
    Get current Solana price from API
    
    Args:
        api_endpoint: API endpoint URL
        api_key: Optional API key
        
    Returns:
        Current SOL price or None if failed
    """
    headers = {"User-Agent": "Python-Script/1.0"}
    
    #response = requests.get(url, headers=headers, timeout=10)
    price_response = api_request(endpoint, headers)
    if not price_response:
        print("Failed to get data from API")
        return BackpackTicker()    
    
    #print(f"Response data: {price_response.get('firstPrice','firstPrice not found')}")
    
    return BackpackTicker(
        symbol=price_response.get('symbol'),
        first_price=price_response.get('firstPrice'),  # Adjust field names
        last_price=price_response.get('lastPrice'),
        high=price_response.get('high'),
        low=price_response.get('low'),
        price_change= price_response.get('priceChange'),
        price_change_percent=price_response.get('priceChangePercent'),
        trades=price_response.get('trades'),
        volume=price_response.get('volume'),
        timestamp=int(time.time())
    )

def fetch_all_tickers(interval: str = "1d") -> Dict[str, dict]:
    """Every market's 24h ticker in one request, keyed by symbol.

    Replaces one /ticker call per monitored symbol (23 requests per loop became
    one). Returns {} on failure so the caller can fall back to the book alone.
    """
    rows = api_request(APIEndpoints.tickers(interval))
    if not rows or not isinstance(rows, list):
        market_logger.error("API call for /tickers failed or returned no rows")
        return {}
    return {row["symbol"]: row for row in rows if isinstance(row, dict) and row.get("symbol")}


BINANCE_PRICES_URL = "https://data-api.binance.vision/api/v3/ticker/price"


def _to_binance_symbol(symbol: str) -> str:
    """"RAY_USDC" -> "RAYUSDT": Binance's deep USDT book prices the same asset."""
    base, _, _ = symbol.partition("_")
    return f"{base.upper()}USDT"


def fetch_reference_prices(symbols) -> Dict[str, Decimal]:
    """Binance spot prices for *symbols* (Backpack format), keyed by Backpack symbol.

    An independent sanity check for the Backpack book, whose thin markets can
    quote a price nobody trades at (RAY_USDC: +33% on 2026-10-18, -5% on
    2026-10-20, Binance unmoved both times). Uses the public market-data host,
    which is not geo-blocked like api.binance.com.

    One request for the whole roster. Binance rejects the whole batch if any
    symbol is unknown, so that falls back to the full price list. Returns {}
    on failure — callers must treat a missing reference as "can't check",
    never as "check failed".
    """
    wanted = {_to_binance_symbol(s): s for s in symbols}
    if not wanted:
        return {}

    def _get(url):
        # api_request raises on HTTP errors (Binance's 400 for an unknown
        # symbol); this must never take the price loop down with it.
        try:
            return api_request(url, timeout=5)
        except Exception as e:
            market_logger.debug(f"Binance price request failed: {e}")
            return None

    batch = json.dumps(sorted(wanted), separators=(",", ":"))
    rows = _get(f"{BINANCE_PRICES_URL}?symbols={quote(batch)}")
    if not isinstance(rows, list):
        rows = _get(BINANCE_PRICES_URL)
    if not isinstance(rows, list):
        market_logger.warning("Binance reference prices unavailable this cycle")
        return {}

    prices = {}
    for row in rows:
        ours = wanted.get(row.get("symbol")) if isinstance(row, dict) else None
        if ours is None:
            continue
        try:
            price = Decimal(str(row["price"]))
        except (InvalidOperation, KeyError, TypeError):
            continue
        if price > 0:
            prices[ours] = price
    return prices


def get_depth(symbol: str, limit: str = "5") -> Optional[dict]:
    """Raw order book for *symbol*: {"bids": [[price, qty]...], "asks": [...], "timestamp"}.

    Public endpoint — no auth headers needed. Bids come back ascending, so use
    utils.price_resolution.book_top rather than indexing the lists.
    """
    depth = api_request(APIEndpoints.depth(symbol, limit))
    if not depth:
        market_logger.warning(f"API call for depth({symbol}) returned nothing")
        return None
    return depth


def fetch_book_top(symbol: str, limit: str = "5") -> Optional[BookTop]:
    """Best bid/ask/mid for *symbol*, or None when the book is missing or broken."""
    try:
        return book_top(get_depth(symbol, limit))
    except Exception as e:
        market_logger.error(f"fetch_book_top({symbol}) failed: {e}")
        return None


def get_last_trade(symbol: str) -> Optional[dict]:
    """Most recent fill for *symbol*, including its millisecond timestamp.

    /ticker has no timestamp field, so this is the only way to ask the REST API
    how old `lastPrice` actually is. Not on the monitoring hot path — the book
    already answers the freshness question — but useful for diagnostics.
    """
    trades = api_request(APIEndpoints.trades(symbol, limit=1))
    if not trades or not isinstance(trades, list):
        return None
    return trades[0] if isinstance(trades[0], dict) else None

def get_price(symbol: str, profile=None) -> Optional[float]:
    """Get the latest price for *symbol*.

    If *profile* is provided the exchange type is respected (Backpack or Bullet).
    Falls back to Backpack REST when no profile is given.
    """
    if profile:
        from api_builders.factory import get_adapter
        try:
            adapter = get_adapter(profile)
            price = adapter.get_ticker(symbol)
            if price:
                market_logger.debug(f"[{profile.exchange_type}] get_price({symbol}) = {price}")
            else:
                market_logger.error(f"[{profile.exchange_type}] get_price({symbol}) returned None")
            return price
        except Exception as e:
            market_logger.error(f"Adapter get_price({symbol}) failed: {e}")
            return None

    # Backpack fallback (no profile — legacy callers)
    url = APIEndpoints.backpack_ticker(symbol, "1d")
    ticker = check_ticker(url)
    if ticker:
        market_logger.debug("API call successful")
    else:
        market_logger.error("API call failed")
    print(ticker.simple_summary())
    return ticker.last_price if ticker else None


def get_market_info(symbol: str, profile=None) -> Optional[dict]:
    """Get market information for *symbol*.

    If *profile* is provided the exchange type is respected.
    """
    if profile:
        from api_builders.factory import get_adapter
        try:
            adapter = get_adapter(profile)
            result = adapter.get_market_info(symbol)
            if result:
                cache = get_market_info_cache()
                cache.update_market(result)
            return result
        except Exception as e:
            market_logger.error(f"Adapter get_market_info({symbol}) failed: {e}")
            return None

    # Backpack fallback
    url = APIEndpoints.backpack_MarketInfo(symbol)
    result = api_request(url)
    if result:
        cache = get_market_info_cache()
        cache.update_market(result)
    return result


def get_all_markets(profile=None) -> Optional[list]:
    """Get all available markets.

    If *profile* is provided the exchange type is respected.
    """
    if profile:
        from api_builders.factory import get_adapter
        try:
            adapter = get_adapter(profile)
            result = adapter.get_markets()
            if result:
                cache = get_market_info_cache()
                cache.update_markets(result)
            return result
        except Exception as e:
            market_logger.error(f"Adapter get_all_markets() failed: {e}")
            return None

    # Backpack fallback
    url = APIEndpoints.backpack_Markets()
    result = api_request(url)
    if result:
        cache = get_market_info_cache()
        cache.update_markets(result)
    return result
