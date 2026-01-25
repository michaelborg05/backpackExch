from dataclasses import dataclass
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from decimal import Decimal

class TradingProfile(BaseModel):
    name: str
    api_key: str
    secret: str    
    
    # Position management settings (as percentages)
    take_profit_pct: Optional[Decimal] = Field(None, description="Take profit percentage (e.g., 5.0 for 5%)")
    stop_loss_pct: Optional[Decimal] = Field(None, description="Stop loss percentage (e.g., 2.0 for 2%)")
    arm_trailing_stop_pct: Optional[Decimal] = Field(None, description="Arm trailing stop percentage (e.g., 1.0 for 1%)")
    trailing_stop_pct: Optional[Decimal] = Field(None, description="Trailing stop percentage (e.g., 1.5 for 1.5%)")
    use_trailing_stop: bool = False
    
    # Risk management
    max_risk_pct: Decimal = Field(Decimal("0.25"), description="Max risk per trade as % of portfolio")
    default_order_size_pct: Decimal = Field(Decimal("5"), description="Default order size as % of portfolio")
    max_position_size: Optional[Decimal] = None
 
    # NEW: Trend Filter Configuration
    use_trend_filter: bool = False
    trend_timeframe: str = "1h"  # Which timeframe to check trend on
    trend_indicators: Optional[List[Dict[str, Any]]] = None  # List of indicator configs
    min_indicators_required: int = Field(default=2, ge=1)  # Minimum that must be bullish

    # ATR Filters
    use_atr_filter: bool = False
    atr_timeframe: str = "15m"
    atr_threshold: float = 1.05
    atr_filter_mode: str = "require_high"

    enable_signal_generation: bool = False          # Enable automated signal generation
    signal_timeframe: str = "15m"                   # Timeframe for entry signals
    signal_cooldown_seconds: Optional[int] = 300    # Wait 5min between signals for same symbol
    min_signal_confidence: float = 75.0             # Only trade signals >= 75% confidence
    min_volume_ratio: float = 1.5                   # Require 50% above average volume

    # position exit logic 
    use_trend_invalidation_exit: Optional[bool] = False
    min_position_age_for_trend_check: Optional[int] = 2  # hours
    max_position_hours: Optional[int] = 18  # Force exit if stuck

    class Config:
        json_encoders = {
            Decimal: lambda v: float(v)
        }
    
    def get_trend_config_summary(self) -> str:
        """Get human-readable summary of trend filter config"""
        if not self.use_trend_filter:
            return "Trend filter: DISABLED"
        
        if not self.trend_indicators:
            return f"Trend filter: ENABLED on {self.trend_timeframe} (default indicators)"
        
        indicator_names = [ind.get("type", "unknown") for ind in self.trend_indicators]
        return (
            f"Trend filter: ENABLED on {self.trend_timeframe} - "
            f"Require {self.min_indicators_required}/{len(self.trend_indicators)} "
            f"({', '.join(indicator_names)})"
        )    

    def get_atr_config_summary(self) -> str:
        """Get human-readable ATR config summary"""
        if not self.use_atr_filter:
            return "ATR filter: disabled"
        
        summary = (
            f"ATR filter: {self.atr_timeframe}, "
            f"threshold={self.atr_threshold}, "
            f"mode={self.atr_filter_mode}"
        )
        
        if self.atr_max_threshold:
            summary += f", max={self.atr_max_threshold}"
        
        return summary
    
 
    def validate_filters(self, alert, balance_cache, market_info_cache, trend_cache, atr_cache) -> tuple[bool, Optional[str]]:
        """
        Validate all filters for a trade
        
        Returns:
            (is_valid, error_message) tuple
        """
        # Only validate for BUY orders
        if alert.action.lower() != "buy":
            return True, None
        
        # Check trend filter
        if self.use_trend_filter:
            is_bullish, reason = trend_cache.is_bullish(
                symbol=alert.symbol,
                timeframe=self.trend_timeframe,
                indicators_config=self.trend_indicators,
                min_indicators_required=self.min_indicators_required
            )
            
            if not is_bullish:
                return False, f"Trend filter: {reason}"
        
        # Check ATR filter
        if self.use_atr_filter:
            is_volatile, reason = atr_cache.is_volatile(
                symbol=alert.symbol,
                timeframe=self.atr_timeframe,
                threshold=self.atr_threshold
            )
            
            if self.atr_filter_mode == "require_high" and not is_volatile:
                return False, f"ATR too low: {reason}"
            
            elif self.atr_filter_mode == "require_low" and is_volatile:
                return False, f"ATR too high: {reason}"
            
            # Check max threshold if set
            if self.atr_max_threshold:
                atr_data = atr_cache.get(alert.symbol, self.atr_timeframe)
                if atr_data and atr_data.get_ratio() > self.atr_max_threshold:
                    return False, f"ATR exceeds maximum: {atr_data.get_ratio():.2f} > {self.atr_max_threshold}"
        
        return True, None    