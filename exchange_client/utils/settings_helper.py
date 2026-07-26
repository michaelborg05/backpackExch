# utils/settings_helper.py
"""
Helper utilities for accessing settings throughout the codebase.
Provides convenience functions for common settings patterns.
"""
from typing import Optional, Any
from cache.settings_cache import get_settings_cache


class SettingsHelper:
    """
    Convenience class for accessing settings with sensible defaults.
    Wraps the settings cache with application-specific helpers.
    """
    
    def __init__(self, profile_name: Optional[str] = None):
        """
        Initialize settings helper
        
        Args:
            profile_name: Optional profile name for profile-specific settings
        """
        self.profile_name = profile_name
        self.cache = get_settings_cache()
    
    def _get(self, setting_name: str, default: Any = None) -> Optional[str]:
        """Internal get method"""
        if self.cache is None:
            return default
        return self.cache.get(setting_name, self.profile_name, default)
    
    def _get_int(self, setting_name: str, default: int) -> int:
        """Internal get int method"""
        if self.cache is None:
            return default
        return self.cache.get_int(setting_name, self.profile_name, default)
    
    def _get_float(self, setting_name: str, default: float) -> float:
        """Internal get float method"""
        if self.cache is None:
            return default
        return self.cache.get_float(setting_name, self.profile_name, default)
    
    def _get_bool(self, setting_name: str, default: bool) -> bool:
        """Internal get bool method"""
        if self.cache is None:
            return default
        return self.cache.get_bool(setting_name, self.profile_name, default)
    
    # Monitoring intervals
    @property
    def circuit_breaker_interval(self) -> int:
        """How often to check circuit breakers (in monitoring cycles)"""
        return self._get_int('circuit_breaker_interval', 2)
    
    @property
    def dust_conversion_interval(self) -> int:
        """How often to convert dust (in monitoring cycles)"""
        return self._get_int('dust_conversion_interval', 2880)
    
    @property
    def signal_check_interval(self) -> int:
        """How often to check for signals (in monitoring cycles)"""
        return self._get_int('signal_check_interval', 10)
    
    @property
    def signal_check_interval_debug(self) -> int:
        """How often to check for signals in debug mode (in monitoring cycles)"""
        return self._get_int('signal_check_interval_debug', 1)
    
    @property
    def trend_invalidation_interval(self) -> int:
        """How often to update trend invalidation (in monitoring cycles)"""
        return self._get_int('trend_invalidation_interval', 10)
    
    @property
    def position_validation_interval(self) -> int:
        """How often to validate positions (in monitoring cycles)"""
        return self._get_int('position_validation_interval', 10)
    
    @property
    def order_monitor_interval(self) -> int:
        """How often to monitor orders (in monitoring cycles)"""
        return self._get_int('order_monitor_interval', 1)
    
    # Position monitoring
    @property
    def trailing_stop_armed_threshold_pct(self) -> float:
        """Percentage gain to arm trailing stop"""
        return self._get_float('trailing_stop_armed_threshold_pct', 2.0)
    
    # Cache refresh intervals
    @property
    def settings_cache_refresh_interval(self) -> int:
        """How often to refresh settings cache (seconds)"""
        return self._get_int('settings_cache_refresh_interval', 60)
    
    @property
    def balance_cache_ttl(self) -> int:
        """Balance cache time-to-live (seconds)"""
        return self._get_int('balance_cache_ttl', 30)
    
    @property
    def price_cache_ttl(self) -> int:
        """Price cache time-to-live (seconds)"""
        return self._get_int('price_cache_ttl', 5)
    
    # Risk management
    @property
    def max_concurrent_positions(self) -> int:
        """Maximum concurrent positions across all profiles"""
        return self._get_int('max_concurrent_positions', 5)
    
    @property
    def max_position_value_pct(self) -> float:
        """Maximum position value as percentage of portfolio"""
        return self._get_float('max_position_value_pct', 20.0)
    
    # Notification settings
    @property
    def telegram_rate_limit_seconds(self) -> int:
        """Rate limit for telegram messages (seconds)"""
        return self._get_int('telegram_rate_limit_seconds', 2)
    
    @property
    def telegram_batch_window_seconds(self) -> int:
        """Window for batching similar telegram messages (seconds)"""
        return self._get_int('telegram_batch_window_seconds', 5)
    
    # Market data
    @property
    def kline_limit(self) -> int:
        """Number of klines to fetch for indicators"""
        return self._get_int('kline_limit', 100)
    
    @property
    def orderbook_depth(self) -> int:
        """Orderbook depth to fetch"""
        return self._get_int('orderbook_depth', 20)

    @property
    def cooldown_take_profit_mins(self) -> int:
        """cooldown in minutes after take profit for same symbol"""
        return self._get_int('cooldown_take_profit_mins', 35)
    
    @property
    def cooldown_stop_loss_mins(self) -> int:
        """cooldown in minutes after stop loss for same symbol"""
        return self._get_int('cooldown_stop_loss_mins', 35)

    @property
    def cooldown_default_mins(self) -> int:
        """cooldown in minutes for same symbol"""
        return self._get_int('cooldown_default_mins', 15)

    @property
    def mean_rever_rsi_inval_threshold(self) -> int:
        """RSI invalidation threshold for mean reversion profiles """
        return self._get_int('mean_rever_rsi_inval_threshold', 36)

    @property
    def mean_rever_rsi_lookback_candles(self) -> int:
        """rsi lookback candle amount for mean reversion profile"""
        return self._get_int('mean_rever_rsi_lookback_candles', 2)

    @property
    def alert_trend_max_age(self) -> int:
        """trend cache max age to raise an alert"""
        return self._get_int('alert_trend_max_age', 1200)

    @property
    def alert_price_max_age(self) -> int:
        """price cache max age to raise an alert"""
        return self._get_int('alert_price_max_age', 120)

    @property
    def alert_re_alert_cooldown(self) -> int:
        """cooldown in seconds before raising next alert """
        return self._get_int('alert_re_alert_cooldown', 900)
    
    @property
    def alert_startup_grace_period(self) -> int:
        """grace period in seconds before triggering health checks """
        return self._get_int('alert_startup_grace_period', 120)

    @property
    def alert_healthcheck_interval(self) -> int:
        """interval between performing health/alert checks """
        return self._get_int('alert_healthcheck_interval', 60)

    # Data retention
    @property
    def retention_trans_history_days(self) -> int:
        """Days to retain orders, positions, trades, and ai_signal_log"""
        return self._get_int('retention_trans_history_days', 90)

    @property
    def retention_trenddata_history_days(self) -> int:
        """Days to retain trend_analysis_log"""
        return self._get_int('retention_trenddata_history_days', 365)

    @property
    def retention_audit_history_days(self) -> int:
        """Days to retain circuit_breaker_events, config_audit_log, daily_balance_snapshots"""
        return self._get_int('retention_audit_history_days', 28)

    def get_custom(self, setting_name: str, default: Any = None) -> Any:
        """
        Get a custom setting not covered by properties
        
        Args:
            setting_name: Name of the setting
            default: Default value if not found
        
        Returns:
            Setting value or default
        """
        return self._get(setting_name, default)
    
    def get_custom_int(self, setting_name: str, default: int = 0) -> int:
        """Get custom setting as integer"""
        return self._get_int(setting_name, default)
    
    def get_custom_float(self, setting_name: str, default: float = 0.0) -> float:
        """Get custom setting as float"""
        return self._get_float(setting_name, default)
    
    def get_custom_bool(self, setting_name: str, default: bool = False) -> bool:
        """Get custom setting as boolean"""
        return self._get_bool(setting_name, default)


def get_settings_helper(profile_name: Optional[str] = None) -> SettingsHelper:
    """
    Get a settings helper instance
    
    Args:
        profile_name: Optional profile name for profile-specific settings
    
    Returns:
        SettingsHelper instance
    """
    return SettingsHelper(profile_name)