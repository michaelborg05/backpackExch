import os
from typing import Optional
from dotenv import load_dotenv

class Config:
    """Centralized configuration management"""
    load_dotenv()
    def __init__(self):
        self.api_key = os.getenv('BACKPACK_API_KEY')
        self.secret = os.getenv('SECRET')
        self.debug_mode = os.getenv('DEBUG_MODE', 'False').lower() == 'true'
        self.log_level = os.getenv('LOG_LEVEL', 'INFO').upper()    
        self.log_location = os.getenv('LOG_LOCATION', 'app.log')
        self.monitor_delay_interval = self.get_int_env('MONITORLOOP_DELAY_INTERVAL')
        if self.log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
            raise ValueError(f"Invalid LOG_LEVEL: {self.log_level}")
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_group_id = self.get_int_env('CHAT_GROUP_ID')
        self.webhook_secret = os.getenv("WEBHOOK_SECRET", "")
        self.port = int(os.getenv("PORT", "8000"))
        self.api_master_key = os.getenv("API_MASTER_KEY", "")
        self.api_readonly_key = os.getenv("API_READONLY_KEY", "")
        self.api_trading_key = os.getenv("API_TRADING_KEY", "")
        # Security settings
        self.enable_api_key_auth: bool = os.getenv("ENABLE_API_KEY_AUTH", "true").lower() == 'true'
        self.enable_rate_limiting: bool = os.getenv("ENABLE_RATE_LIMITING", "true").lower() == 'true'
        self.telegram_enabled: bool = os.getenv("TELEGRAM_ENABLED", "false").lower() == 'true'
        self.database_url: str = self._get_required("DATABASE_URL")
        self.telegram_webhook_url: str = os.getenv("TELEGRAM_WEBHOOK_URL", "")  
    def _get_required(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Required environment variable {key} is not set")
        return value
    
    def get_int_env(self, var_name: str) -> int | None:
        value = os.getenv(var_name)
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None