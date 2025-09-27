import time
import urllib.request
import urllib.error
import json
from typing import Dict, Optional, Any
from utils.config import Config
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters

config = Config()
trader_logger = log_manager.get_logger("trader")

def trader(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """
        Generic API request function
        
        Args:
            url: API endpoint URL
            headers: Optional HTTP headers
            timeout: Request timeout in seconds
            
        Returns:
            JSON response data or None if failed
        """