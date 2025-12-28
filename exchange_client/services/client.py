import urllib.request
import urllib.error
import json
from typing import Dict, Optional, Any
from utils.config import Config
from utils.logging import log_manager
import socket
from utils.constants import HttpMethod
from utils.exceptions import ExchangeAPIError

config = Config()
client_logger = log_manager.get_logger("client")


def api_request(
    url: str, 
    headers: Optional[Dict[str, str]] = None, 
    body: Optional[Dict[str, Any]] = None,
    timeout: int = 10, 
    requestType: str = HttpMethod.GET
) -> Optional[Dict[str, Any]]:
    """
    Generic API request function
    
    Args:
        url: API endpoint URL
        headers: Optional HTTP headers
        body: Optional request body (will be JSON encoded)
        timeout: Request timeout in seconds
        requestType: HTTP method (GET, POST, DELETE, etc.)
        
    Returns:
        JSON response data or None if failed
    """
    try:
        # Set default headers
        if headers is None:
            headers = {"User-Agent": "Backpack trader/1.0"}
        
        # Prepare request body
        data = None
        if body is not None:
            # Add content-type header if body is present
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
            
            # Encode body as JSON bytes
            data = json.dumps(body).encode('utf-8')
            
            if config.debug_mode:
                client_logger.debug(f"DEBUG: Request body: {json.dumps(body, indent=2)}")
        
        if config.debug_mode:
            client_logger.debug(f"DEBUG: {requestType.value} request to {url}")
            client_logger.debug(f"DEBUG: Headers: {headers}")

        # Create request with optional body
        req = urllib.request.Request(
            url, 
            data=data,  # Add body data
            headers=headers, 
            method=requestType.value
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            # Read response bytes once
            resp_bytes = response.read()

            if config.debug_mode:
                try:
                    resp_text = resp_bytes.decode('utf-8')
                    # Pretty print JSON if possible
                    try:
                        parsed = json.loads(resp_text)
                        resp_text = json.dumps(parsed, indent=2)
                    except:
                        pass
                    client_logger.debug(f"DEBUG: Response ({response.status}): {resp_text}")
                except Exception:
                    client_logger.debug(f"DEBUG: Response ({response.status}): {repr(resp_bytes)}")

            # Check for successful status codes (200-299)
            if 200 <= response.status < 300:
                # Handle empty responses
                if not resp_bytes:
                    return {}
                
                try:
                    return json.loads(resp_bytes.decode('utf-8'))
                except json.JSONDecodeError as e:
                    client_logger.error(f"Failed to decode JSON from response: {e}")
                    client_logger.error(f"Response text: {resp_bytes.decode('utf-8', errors='replace')}")
                    return None
            else:
                error_msg = f"API request failed with status: {response.status}"
            try:
                error_data = json.loads(resp_bytes.decode('utf-8'))
                error_msg = f"{error_msg} - {error_data}"
            except:
                pass
            
            client_logger.error(error_msg)
            raise ExchangeAPIError(error_msg, status_code=response.status)
                
    except urllib.error.HTTPError as e:
        body_text = _read_error_body(e)
        error_msg = f"HTTP {e.code} Error: {body_text or e.reason}"
        client_logger.error(error_msg)
        raise ExchangeAPIError(error_msg, status_code=e.code)
        
    except urllib.error.URLError as e:
        client_logger.error(f"URL Error: {e.reason}")
        raise ExchangeAPIError(f"Connection error: {e.reason}")
        
    except socket.timeout:
        client_logger.error(f"Request timeout after {timeout} seconds")
        raise ExchangeAPIError(f"Request timeout after {timeout} seconds")
        
    except Exception as e:
        client_logger.error(f"Unexpected error: {type(e).__name__}: {e}")
        raise ExchangeAPIError(f"Unexpected error: {str(e)}")

def _read_error_body(error: urllib.error.HTTPError) -> Optional[str]:
    """Helper to read error body"""
    try:
        body_bytes = error.read()
        body_text = body_bytes.decode('utf-8')
        try:
            error_json = json.loads(body_text)
            return json.dumps(error_json, indent=2)
        except:
            return body_text
    except:
        return None