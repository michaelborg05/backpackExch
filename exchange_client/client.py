import urllib.request
import urllib.error
import json
from typing import Dict, Optional, Any
from utils.config import Config
from utils.logging import log_manager

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
    
