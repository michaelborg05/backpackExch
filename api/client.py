import urllib.request
import urllib.error
import json
from typing import Dict, Optional, Any
from config import Config

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
    config = Config()

    try:
        if headers is None:
            headers = {"User-Agent": "Backpack trader/1.0"}
        
        req = urllib.request.Request(url, headers=headers)
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if config.debug_mode == True:
                print(f"DEBUG: Response: {response}")
            if response.status == 200:
                return json.loads(response.read().decode('utf-8'))
            else:
                print(f"API request failed with status: {response.status}")
                return None
                
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
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
    
def check_price(endpoint: str, api_key: Optional[str] = None ) -> Optional[float]:
    """
    Get current Solana price from API
    
    Args:
        api_endpoint: API endpoint URL
        api_key: Optional API key
        
    Returns:
        Current SOL price or None if failed
    """
    headers = {"User-Agent": "Python-Script/1.0"}
    if api_key:
        headers["Authorization"] = f"{api_key}"
    
    #response = requests.get(url, headers=headers, timeout=10)
    price_response = api_request(endpoint, headers)
    if not price_response:
        print("Failed to get data from API")
        return False    
    
    print(f"Response data: {price_response.get('firstPrice','firstPrice not found')}")
    
    return True
    
    