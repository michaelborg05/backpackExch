import time
from datetime import datetime, timezone
from typing import Dict, Union, Any, Optional
import base64
import urllib.parse
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import math

def get_utc_timestamp_seconds() -> int:
    """Get current UTC timestamp in seconds"""
    return int(time.time())

def get_utc_timestamp_milliseconds() -> int:
    """Get current UTC timestamp in milliseconds"""
    return int(time.time() * 1000)

def timestamp_to_readable(timestamp: Union[int, float], tz=timezone.utc) -> str:
    """Convert timestamp to readable format"""
    if timestamp > 1e10:  # Milliseconds
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S %Z')

def get_random_delay(min_seconds: int = 30, max_seconds: int = 180) -> int:
    """Get random delay for API calls"""
    import random
    return random.randint(min_seconds, max_seconds)

def convert_to_float(val: Any) -> Optional[float]:
    """Validate and convert to float"""
    if val is None:
        return None
    
    try:
        float_value = float(val)
        return float_value
    except (ValueError, TypeError):
        raise ValueError(f"Invalid float format: {val}")

def convert_to_percent(val: Any) -> Optional[float]:
    """Validate and convert to percent"""
    if val is None:
        return None
    
    try:
        float_value = float(val) * 100
        return float_value
    except (ValueError, TypeError):
        raise ValueError(f"Invalid float format: {val}")

def convert_to_price(val: Any) -> Optional[str]:
    """Validate and convert to price string"""
    if val is None:
        return None
    
    try:
        float_value = convert_to_float(val)
        
        return f"${float_value:.2f}"
    except (ValueError, TypeError):
        raise ValueError(f"Invalid float format: {val}")

def convert_volume(val: Any, token_price: Any) -> Optional[str]:
    """convert volume """
    if val is None:
        return None
    
    try:
        float_value = convert_to_float(val)
        token_value = convert_to_float(token_price)
        volume = float_value * token_value if float_value and token_value else None        
        return f"${volume:.2f}"
    except (ValueError, TypeError):
        raise ValueError(f"Invalid float format: {val}")
    

def string_to_base64(s: str, encoding: str = 'utf-8') -> str:
    if not isinstance(s, str):
        raise TypeError(f"Expected str for `s`, got {type(s)!r}")

    b = s.encode(encoding)
    encoded = base64.b64encode(b).decode('ascii')
    return encoded

def base64_to_string(b64: str, encoding: str = 'utf-8') -> str:
    if not isinstance(b64, str):
        raise TypeError(f"Expected str for `b64`, got {type(b64)!r}")

    try:
        raw = base64.b64decode(b64)
    except (base64.binascii.Error, ValueError) as e:
        raise ValueError(f"Invalid base64 input: {e}") from e

    return raw.decode(encoding)


def ed25519_sign_base64(secret_b64: str, message: str, encoding: str = 'utf-8') -> str:
    """Sign a message using an ED25519 private key provided as a base64 string.

    The function accepts a base64-encoded secret. The secret may be:
    - raw 32-byte seed (most common), or
    - 64-byte private key (seed+pub), or
    - a PEM/DER private key that was base64-encoded (detected by '-----BEGIN').

    Returns the signature as a base64-encoded string.
    """
    if not isinstance(secret_b64, str):
        raise TypeError(f"Expected base64 secret string, got {type(secret_b64)!r}")

    try:
        secret_bytes = base64.b64decode(secret_b64)
    except Exception as e:
        raise ValueError("Invalid base64 secret") from e

    private_key = None
    # If the decoded bytes look like a PEM/DER blob containing a private key, try to load
    try:
        if b'-----BEGIN' in secret_bytes:
            # treat as PEM/DER
            private_key = serialization.load_pem_private_key(secret_bytes, password=None)
        else:
            # Treat as raw seed/private bytes. Ed25519 private seed is 32 bytes.
            if len(secret_bytes) >= 32:
                seed = secret_bytes[:32]
                private_key = Ed25519PrivateKey.from_private_bytes(seed)
            else:
                raise ValueError("Secret must be at least 32 bytes when base64-decoded")
    except Exception as e:
        raise ValueError(f"Failed to construct Ed25519 private key: {e}") from e

    sig = private_key.sign(message.encode(encoding))
    return base64.b64encode(sig).decode('ascii')

def build_query_string(params: dict) -> str:
    if not isinstance(params, dict):
        raise TypeError(f"Expected dict for `params`, got {type(params)!r}")
    
    # Sort keys alphabetically and build query string
    query_parts = []
    for key in sorted(params.keys()):
        if params[key] is not None:  # Skip None values
            encoded_key = urllib.parse.quote_plus(str(key))
            encoded_value = urllib.parse.quote_plus(str(params[key]))
            query_parts.append(f"{encoded_key}={encoded_value}")
    
    return "&".join(query_parts)

def build_authorisation_header(api_key: str, secret: str,  query_params: Dict[str, Any], body: Optional[Dict[str, Any]], instruction: str, window: int = 5000) -> str:
    timestamp = get_utc_timestamp_milliseconds().__str__()
    query_string =""
    if isinstance(query_params, dict) is True and len(query_params) > 0:
        query_string = build_query_string(query_params)
    else:
        if isinstance(body, dict) is True and len(body) > 0:
            query_string = build_query_string(body)
    
    if query_string:
        query_string = "&" + query_string
    message = f"instruction={instruction}{query_string}&timestamp={timestamp}&window={window.__str__()}"
    # Sign with ED25519 using the base64-encoded secret key
    signature = ed25519_sign_base64(secret, message)

    headers = {"User-Agent": "Python-Script/1.0"}
    headers["X-TIMESTAMP"] =  timestamp
    headers["X-WINDOW"] = window.__str__()
    headers["X-API-KEY"] = api_key
    # signature is already base64-encoded
    headers["X-SIGNATURE"] = signature

    return headers

def round_down(value, decimals):
    try:
        factor = 10**decimals
        return math.floor(value * factor) / factor
    except Exception as e:
        raise ValueError(f"Error rounding down: {e}")