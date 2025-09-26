import time
import urllib.request
import urllib.error
import json
from typing import Dict, Optional, Any
from config import Config
from models.backpack_ticker import BackpackTicker
from utils.logging import log_manager
from api.endpoints import APIEndpoints
from utils import data_converter
from models.backpack_balance import BalanceReader

config = Config()
client_logger = log_manager.get_logger("client")

def api_request(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """
    Generic API request function
    
    Args:
        url: API endpoint URL
        headers: Optional HTTP headers
        timeout: Request timeout in seconds
        
    Returns:
        JSON response data or None if failed
    """
    try:
        if headers is None:
            headers = {"User-Agent": "Backpack trader/1.0"}
        
        if config.debug_mode == True:
            client_logger.info(f"DEBUG: Making request to {url}")

        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            # Read response bytes once to avoid consuming the stream twice
            resp_bytes = response.read()

            if config.debug_mode:
                # Try to decode as text, fall back to repr of bytes
                try:
                    resp_text = resp_bytes.decode('utf-8')
                except Exception:
                    resp_text = repr(resp_bytes)

                # Keep a short, single-line preview for logs/console
                client_logger.info(f"DEBUG: Response body: {resp_text}")

            if response.status == 200:
                try:
                    return json.loads(resp_bytes.decode('utf-8'))
                except json.JSONDecodeError:
                    client_logger.error("Failed to decode JSON from response")
                    return None
            else:
                #print(f"API request failed with status: {response.status}")
                client_logger.error("API request failed with status: {response.status}")
                return None
                
    except urllib.error.HTTPError as e:
        # HTTPError contains the response body which we should decode safely
        body = None
        try:
            body = e.read().decode('utf-8')
        except Exception:
            try:
                body = repr(e.read())
            except Exception:
                body = '<unable to read body>'

        print(f"HTTP Error: {e.code} - {e.reason}")
        client_logger.error(f"HTTP Error: {e.code} - {e.reason}")
        client_logger.error(f"HTTP Error body: {body}")
        return None
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error in API request: {e}")
        return None
    
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

def get_prices(ticker:str):
    url = APIEndpoints.backpack_ticker(ticker,"1d")
    ticker = check_ticker(url)
    
    if ticker:
        client_logger.info("API call completed successfully")
    else:
        client_logger.error("API call failed")
    print(f"Summary: {ticker.formatted_summary()}")



def get_balances() -> Optional[BalanceReader]:
    url = APIEndpoints.backpack_balances()
    headers=data_converter.build_authorisation_header(
        api_key=config.api_key,
        secret=config.secret,
        query_params={},
        body=None,
        instruction="balanceQuery",
        window=60000
    )

    balances = api_request(url, headers)
    
    if balances:
        client_logger.info("API call for balances completed successfully")
        return BalanceReader(balances)
        #active_assets = balancelist.get_non_zero_balances()
        #print(balancelist.summary())
    else:
        client_logger.error("API call for balances failed")