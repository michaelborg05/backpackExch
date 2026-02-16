# cache/settings_cache.py
"""
Settings cache with automatic refresh capability.
Provides fast access to settings without hitting the database on every read.
Periodically refreshes from database to pick up changes without restart.
"""
import threading
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from db.utils import get_db_session
from db.crud_settings import get_all_settings, get_settings_for_profile
from utils.logging import log_manager


class SettingsCache:
    """
    Thread-safe cache for application settings.
    
    Features:
    - Loads all settings on initialization
    - Periodically refreshes from database
    - Profile-specific settings override global settings
    - Type conversion helpers (int, float, bool)
    - Thread-safe access
    """
    
    def __init__(self, refresh_interval: int = 900):
        """
        Initialize settings cache
        
        Args:
            refresh_interval: How often to refresh from database (seconds)
        """
        self.logger = log_manager.get_logger("SettingsCache")
        self.refresh_interval = refresh_interval
        
        # Cache structure: {profile_name: {setting_name: value}}
        self._cache: Dict[str, Dict[str, str]] = {}
        self._lock = threading.RLock()
        
        # Refresh control
        self._refresh_thread: Optional[threading.Thread] = None
        self._stop_refresh = threading.Event()
        self._last_refresh: Optional[datetime] = None
        
        # Initial load
        self.refresh()
        
        # Start auto-refresh thread
        self._start_refresh_thread()
    
    def _start_refresh_thread(self):
        """Start background thread for periodic refresh"""
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            self.logger.warning("Refresh thread already running")
            return
        
        self._stop_refresh.clear()
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            daemon=True,
            name="SettingsCacheRefresh"
        )
        self._refresh_thread.start()
        self.logger.info(f"Started settings cache refresh thread (interval: {self.refresh_interval}s)")
    
    def _refresh_loop(self):
        """Background loop for periodic refresh"""
        while not self._stop_refresh.is_set():
            try:
                time.sleep(self.refresh_interval)
                if not self._stop_refresh.is_set():
                    self.refresh()
            except Exception as e:
                self.logger.error(f"Error in refresh loop: {e}", exc_info=True)
    
    def refresh(self):
        """
        Refresh cache from database.
        Loads all settings and organizes by profile.
        """
        try:
            with get_db_session() as db:
                all_settings = get_all_settings(db)
            
            with self._lock:
                # Clear existing cache
                self._cache.clear()
                
                # Organize by profile
                for setting in all_settings:
                    profile = setting.profile_name
                    if profile not in self._cache:
                        self._cache[profile] = {}
                    
                    self._cache[profile][setting.setting_name] = setting.value
                
                self._last_refresh = datetime.now(timezone.utc)
                
                # Count settings
                global_count = len(self._cache.get('0', {}))
                profile_count = sum(len(settings) for profile, settings in self._cache.items() if profile != '0')
                
                self.logger.debug(
                    f"Settings cache refreshed: {global_count} global, "
                    f"{profile_count} profile-specific settings"
                )
        
        except Exception as e:
            self.logger.error(f"Failed to refresh settings cache: {e}", exc_info=True)
    
    def get(
        self,
        setting_name: str,
        profile_name: Optional[str] = None,
        default: Any = None
    ) -> Optional[str]:
        """
        Get a setting value.
        
        If profile_name is provided, checks profile-specific settings first,
        then falls back to global settings.
        
        Args:
            setting_name: Name of the setting
            profile_name: Optional profile name (checks global if None)
            default: Default value if setting not found
        
        Returns:
            Setting value as string, or default if not found
        """
        with self._lock:
            # If profile specified, check profile-specific first
            if profile_name:
                profile_settings = self._cache.get(profile_name, {})
                if setting_name in profile_settings:
                    return profile_settings[setting_name]
            
            # Fall back to global settings
            global_settings = self._cache.get('0', {})
            return global_settings.get(setting_name, default)
    
    def get_int(
        self,
        setting_name: str,
        profile_name: Optional[str] = None,
        default: int = 0
    ) -> int:
        """Get setting as integer"""
        value = self.get(setting_name, profile_name)
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            self.logger.warning(
                f"Failed to parse '{setting_name}' as int: '{value}', using default: {default}"
            )
            return default
    
    def get_float(
        self,
        setting_name: str,
        profile_name: Optional[str] = None,
        default: float = 0.0
    ) -> float:
        """Get setting as float"""
        value = self.get(setting_name, profile_name)
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            self.logger.warning(
                f"Failed to parse '{setting_name}' as float: '{value}', using default: {default}"
            )
            return default
    
    def get_bool(
        self,
        setting_name: str,
        profile_name: Optional[str] = None,
        default: bool = False
    ) -> bool:
        """Get setting as boolean"""
        value = self.get(setting_name, profile_name)
        if value is None:
            return default
        return str(value).lower() in ('true', '1', 'yes', 'on')
    
    def get_all_for_profile(self, profile_name: str) -> Dict[str, str]:
        """
        Get all settings applicable to a profile (global + profile-specific)
        
        Args:
            profile_name: Profile name
        
        Returns:
            Dictionary of setting_name -> value
        """
        with self._lock:
            # Start with global settings
            result = dict(self._cache.get('0', {}))
            
            # Override with profile-specific
            profile_settings = self._cache.get(profile_name, {})
            result.update(profile_settings)
            
            return result
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            return {
                "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
                "refresh_interval_seconds": self.refresh_interval,
                "profiles_cached": len(self._cache),
                "global_settings_count": len(self._cache.get('0', {})),
                "total_settings": sum(len(settings) for settings in self._cache.values()),
                "is_refreshing": self._refresh_thread.is_alive() if self._refresh_thread else False
            }
    
    def stop(self):
        """Stop the refresh thread"""
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._stop_refresh.set()
            self._refresh_thread.join(timeout=5)
            self.logger.info("Settings cache refresh thread stopped")
    
    def __del__(self):
        """Cleanup on deletion"""
        self.stop()


# Global instance
_settings_cache: Optional[SettingsCache] = None
_cache_lock = threading.Lock()


def initialize_settings_cache(refresh_interval: int = 60) -> SettingsCache:
    """
    Initialize the global settings cache instance.
    Should be called once during application startup.
    
    Args:
        refresh_interval: How often to refresh from database (seconds)
    
    Returns:
        SettingsCache instance
    """
    global _settings_cache
    
    with _cache_lock:
        if _settings_cache is None:
            _settings_cache = SettingsCache(refresh_interval=refresh_interval)
        return _settings_cache


def get_settings_cache() -> Optional[SettingsCache]:
    """
    Get the global settings cache instance.
    Returns None if not initialized.
    
    Returns:
        SettingsCache instance or None
    """
    return _settings_cache


def shutdown_settings_cache():
    """Shutdown the settings cache (cleanup)"""
    global _settings_cache
    
    with _cache_lock:
        if _settings_cache:
            _settings_cache.stop()
            _settings_cache = None