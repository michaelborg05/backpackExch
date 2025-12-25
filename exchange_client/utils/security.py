# utils/security.py
import secrets
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, Security, Header, Depends
from fastapi.security import APIKeyHeader
from utils.config import Config
from utils.logging import log_manager

config = Config()
security_logger = log_manager.get_logger("Security")

# API Key header scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

class APIKeyManager:
    """Manages API key authentication"""
    
    def __init__(self):
        # In production, store these in a database
        # For now, use environment variables
        self.valid_keys = self._load_api_keys()
        
    def _load_api_keys(self) -> dict:
        """
        Load valid API keys from config
        Format: {api_key: {name, permissions, rate_limit}}
        """
        keys = {}
        
        # Master key (full access)
        if hasattr(config, 'api_master_key') and config.api_master_key:
            keys[config.api_master_key] = {
                "name": "master",
                "permissions": ["read", "trade", "admin"],
                "rate_limit": None
            }
        
        # Read-only key (monitoring, prices, balances)
        if hasattr(config, 'api_readonly_key') and config.api_readonly_key:
            keys[config.api_readonly_key] = {
                "name": "readonly",
                "permissions": ["read"],
                "rate_limit": 100  # requests per minute
            }
        
        # Trading key (can execute trades)
        if hasattr(config, 'api_trading_key') and config.api_trading_key:
            keys[config.api_trading_key] = {
                "name": "trading",
                "permissions": ["read", "trade"],
                "rate_limit": 50
            }
        
        # Webhook key (for TradingView)
        if hasattr(config, 'webhook_secret') and config.webhook_secret:
            keys[config.webhook_secret] = {
                "name": "webhook",
                "permissions": ["webhook"],
                "rate_limit": 20
            }
        
        return keys
    
    def verify_key(self, api_key: str) -> dict:
        """Verify API key and return permissions"""
        if not api_key:
            raise HTTPException(status_code=401, detail="API key required")
        
        key_info = self.valid_keys.get(api_key)
        if not key_info:
            security_logger.warning(f"Invalid API key attempted: {api_key[:8]}...")
            raise HTTPException(status_code=401, detail="Invalid API key")
        
        security_logger.debug(f"Authenticated: {key_info['name']}")
        return key_info
    
    def check_permission(self, key_info: dict, required_permission: str):
        """Check if API key has required permission"""
        if required_permission not in key_info["permissions"]:
            security_logger.warning(
                f"Permission denied: {key_info['name']} tried to access {required_permission}"
            )
            raise HTTPException(
                status_code=403, 
                detail=f"Insufficient permissions. Required: {required_permission}"
            )


# Global instance
api_key_manager = APIKeyManager()


# Dependency functions for FastAPI
async def verify_api_key(api_key: str = Security(api_key_header)) -> dict:
    """Verify API key dependency"""
    return api_key_manager.verify_key(api_key)


async def require_read_permission(key_info: dict = Depends(verify_api_key)) -> dict:
    """Require read permission"""
    api_key_manager.check_permission(key_info, "read")
    return key_info


async def require_trade_permission(key_info: dict = Depends(verify_api_key)) -> dict:
    """Require trade permission"""
    api_key_manager.check_permission(key_info, "trade")
    return key_info


async def require_admin_permission(key_info: dict = Depends(verify_api_key)) -> dict:
    """Require admin permission"""
    api_key_manager.check_permission(key_info, "admin")
    return key_info


async def require_webhook_permission(key_info: dict = Depends(verify_api_key)) -> dict:
    """Require webhook permission"""
    api_key_manager.check_permission(key_info, "webhook")
    return key_info


# Optional: Request signing for extra security
def verify_request_signature(
    body: str,
    signature: str,
    secret: str,
    timestamp: Optional[str] = None,
    max_age_seconds: int = 300
) -> bool:
    """
    Verify HMAC signature of request
    
    Args:
        body: Request body as string
        signature: HMAC signature from header
        secret: Shared secret
        timestamp: Request timestamp (optional, for replay protection)
        max_age_seconds: Max age of request in seconds
    
    Returns:
        True if signature is valid
    """
    # Check timestamp (replay attack protection)
    if timestamp:
        try:
            request_time = datetime.fromisoformat(timestamp)
            age = (datetime.now(datetime.timezone.utc) - request_time).total_seconds()
            if age > max_age_seconds:
                security_logger.warning(f"Request too old: {age}s")
                return False
        except:
            security_logger.warning("Invalid timestamp format")
            return False
    
    # Compute expected signature
    message = body
    if timestamp:
        message = f"{timestamp}.{body}"
    
    expected = hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Compare signatures (constant-time comparison)
    return hmac.compare_digest(signature, expected)


# Rate limiting (simple in-memory implementation)
from collections import defaultdict
from threading import Lock

class RateLimiter:
    """Simple in-memory rate limiter"""
    
    def __init__(self):
        self.requests = defaultdict(list)
        self.lock = Lock()
    
    def is_allowed(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        """
        Check if request is allowed under rate limit
        
        Args:
            key: Identifier (e.g., API key or IP)
            limit: Max requests per window
            window_seconds: Time window in seconds
        
        Returns:
            True if request is allowed
        """
        with self.lock:
            now = datetime.utcnow()
            cutoff = now - timedelta(seconds=window_seconds)
            
            # Remove old requests
            self.requests[key] = [
                req_time for req_time in self.requests[key]
                if req_time > cutoff
            ]
            
            # Check limit
            if len(self.requests[key]) >= limit:
                return False
            
            # Add current request
            self.requests[key].append(now)
            return True


rate_limiter = RateLimiter()


async def check_rate_limit(key_info: dict = Depends(verify_api_key)):
    """Check rate limit for API key"""
    limit = key_info.get("rate_limit")
    
    if limit is None:
        return key_info  # No rate limit
    
    api_key_name = key_info["name"]
    
    if not rate_limiter.is_allowed(api_key_name, limit):
        security_logger.warning(f"Rate limit exceeded: {api_key_name}")
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {limit} requests per minute."
        )
    
    return key_info


