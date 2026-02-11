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
 
    # Market Regime Filter
    use_market_regime_filter: bool = False  
    
    # NEW: Trend Filter Configuration (Higher Timeframe)
    use_trend_filter: bool = False
    trend_timeframe: str = "1h"  # Which timeframe to check trend on
    trend_indicators: Optional[List[Dict[str, Any]]] = None  # List of indicator configs
    min_indicators_required: int = Field(default=2, ge=1)  # Minimum that must be bullish
    
    # NEW: Entry Filter Configuration (Execution Timeframe)
    use_entry_filter: bool = False
    entry_timeframe: str = "15m"  # Which timeframe to check entry on
    entry_indicators: Optional[List[Dict[str, Any]]] = None  # List of entry indicator configs
    min_entry_indicators_required: int = Field(default=2, ge=1)  # Minimum entry indicators required

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

    # Position sizing
    default_order_size_usdc: float = 100.0      # Default order size in USDC (fixed amount)
    max_position_size_pct: float = 10.0         # Max position as % of portfolio (e.g., 10% = 10.0)
    
    # Risk management
    max_open_positions: int = 5                  # Max concurrent positions
    max_portfolio_exposure_pct: float = 80.0     # Max % of portfolio in positions

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
    
    def get_entry_config_summary(self) -> str:
        """Get human-readable summary of entry filter config"""
        if not self.use_entry_filter:
            return "Entry filter: DISABLED"
        
        if not self.entry_indicators:
            return f"Entry filter: ENABLED on {self.entry_timeframe} (no indicators configured)"
        
        indicator_names = [ind.get("type", "unknown") for ind in self.entry_indicators]
        return (
            f"Entry filter: ENABLED on {self.entry_timeframe} - "
            f"Require {self.min_entry_indicators_required}/{len(self.entry_indicators)} "
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
    
 
