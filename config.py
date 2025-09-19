import os
from typing import Optional
from dotenv import load_dotenv

class Config:
    """Centralized configuration management"""
    load_dotenv()
    def __init__(self):
        self.api_key = os.getenv('BACKPACK_API_KEY')
        self.debug_mode = os.getenv('DEBUG_MODE', 'False').lower() == 'true'
        self.log_level = os.getenv('LOG_LEVEL', 'INFO').upper()    
        self.log_location = os.getenv('LOG_LOCATION', 'app.log')
        
        if self.log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            raise ValueError(f"Invalid LOG_LEVEL: {self.log_level}")
        
    def _get_required(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Required environment variable {key} is not set")
        return value