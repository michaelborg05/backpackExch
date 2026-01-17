import time
from typing import Dict, Optional, Any
from utils.config import Config
from models import BackpackTicker, TickerDepth, BalanceReader
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters
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

def get_depth(symbol: str) -> Optional[TickerDepth]:
    url = APIEndpoints.backpack_depth(symbol, "5")
    headers=data_converters.build_authorisation_header(
        api_key=config.api_key,
        secret=config.secret,
        query_params={},
        body=None,
        instruction="balanceQuery",
        window=60000
    )

    balances = api_request(url, headers)
    
    if balances:
        market_logger.debug("API call for balances completed successfully")
        return BalanceReader(balances)
        #active_assets = balancelist.get_non_zero_balances()
        #print(balancelist.summary())
    else:
        market_logger.error("API call for balances failed")
    return None

def get_price(symbol:str):
    url = APIEndpoints.backpack_ticker(symbol,"1d")
    ticker = check_ticker(url)
    
    if ticker:
        market_logger.debug("API call successful")
    else:
        market_logger.error("API call failed")
    print(ticker.simple_summary())
    return ticker.last_price



def get_market_info(symbol: str) -> Optional[dict]:
    """
    Get market information from API
    
    Args:
        symbol: Trading pair (e.g., "SOL_USDC")
        
    Returns:
        Market info dict or None
    """
    url = APIEndpoints.backpack_MarketInfo(symbol)
    result = api_request(url)

    if result:
        # Update cache
        cache = get_market_info_cache()
        cache.update_market(result)
    
    return result


def get_all_markets() -> Optional[list]:
    """
    Get all market information from API
    
    Returns:
        List of market info dicts or None
    """
    url = APIEndpoints.backpack_Markets()

    result = api_request(url)
    
    if result:
        # Update cache with all markets
        cache = get_market_info_cache()
        cache.update_markets(result)
    
    return result
