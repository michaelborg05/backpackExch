from dataclasses import dataclass
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from decimal import Decimal
from utils.constants import StrategyType, TradingType

class TradingProfile(BaseModel):
    id: int
    name: str
    display_name: str
    api_key: str
    secret: str

    account_id: Optional[int] = Field(None, description="Exchange account ID (for shared-account profiles)")
    exchange_type: str = Field("backpack", description="Exchange identifier: 'backpack' or 'bullet'")
    wallet_address: Optional[str] = Field(None, description="Main wallet address for read operations (Bullet only). api_key holds the delegate address used for signing writes.")

    trading_type: TradingType = Field(TradingType.RULES_LIVE, description="Type of trading (e.g., 'rules_live, ai_live, shadow')")
    strategy_type: StrategyType = Field(StrategyType.TREND_FOLLOWING, description="Type of strategy (e.g., 'trend_following', 'mean_reversion')")
    market_type: str = Field("SPOT", description="Market type: 'SPOT' or 'PERP'")
    direction: str = Field("LONG", description="Trade direction for this profile: 'LONG' or 'SHORT'")

    # Position management settings (as percentages)
    take_profit_pct: Optional[Decimal] = Field(None, description="Take profit percentage (e.g., 5.0 for 5%)")
    stop_loss_pct: Optional[Decimal] = Field(None, description="Stop loss percentage (e.g., 2.0 for 2%)")
    arm_trailing_stop_pct: Optional[Decimal] = Field(None, description="Arm trailing stop percentage (e.g., 1.0 for 1%)")
    trailing_stop_pct: Optional[Decimal] = Field(None, description="Trailing stop percentage (e.g., 1.5 for 1.5%)")
    use_trailing_stop: bool = False
    
    # Risk management
    max_risk_pct: Decimal = Field(Decimal("0.25"), description="Max risk per trade as % of portfolio")
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
    signal_cooldown_seconds: Optional[int] = 900    # Wait 5min between signals for same symbol
    min_signal_confidence: float = 75.0             # Only trade signals >= 75% confidence
    min_volume_ratio: float = 1.5                   # Require 50% above average volume

    # position exit logic 
    use_trend_invalidation_exit: Optional[bool] = False
    trend_invalidation_indicators: Optional[str] = "entry"  # trend or entry
    min_position_age_for_trend_check: Optional[int] = 120  # minutes
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
                
        return summary
    
 
class ProfileCreateRequest(BaseModel):
    name: str
    display_name: str
    account_id:   int            # Required — links to ExchangeAccount

    # Strategy
    trading_type: Optional[str] = "rules_live"
    strategy_type: Optional[str] = "trend_following"

    # Risk
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    arm_trailing_stop_pct: Optional[float] = None
    use_trailing_stop: Optional[bool] = False

    # Sizing
    default_order_size_usdc: Optional[float] = 100.0
    max_position_size_pct: Optional[float] = 40.0
    max_open_positions: Optional[int] = 5
    max_portfolio_exposure_pct: Optional[float] = 80.0

    # Signal generation
    signal_timeframe: Optional[str] = "15"
    signal_cooldown_seconds: Optional[int] = 900
    min_signal_confidence: Optional[float] = 72.0
    min_volume_ratio: Optional[float] = 1.0

    # Timeframes
    trend_timeframe: Optional[str] = "60"
    entry_timeframe: Optional[str] = "15"

    # Filter toggles
    use_market_regime_filter: Optional[bool] = False
    use_trend_filter: Optional[bool] = False
    use_entry_filter: Optional[bool] = False
    use_atr_filter: Optional[bool] = False

    # Indicator thresholds
    min_indicators_required: Optional[int] = 2
    min_entry_indicators_required: Optional[int] = 2

    # Exit logic
    use_trend_invalidation_exit: Optional[bool] = False
    trend_invalidation_indicators: Optional[str] = "entry"
    min_position_age_for_trend_check: Optional[int] = 120
    max_position_hours: Optional[int] = None

    # Market & direction
    market_type: Optional[str] = "SPOT"
    direction: Optional[str] = "LONG"  # "LONG" or "SHORT"

    # Active flag
    is_active: Optional[bool] = True


class ProfileUpdateRequest(BaseModel):
    """Partial update — only non-None fields are applied."""
    display_name: Optional[str] = None

    trading_type: Optional[str] = None
    strategy_type: Optional[str] = None
    market_type: Optional[str] = None
    direction: Optional[str] = None  # "LONG" or "SHORT"

    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    arm_trailing_stop_pct: Optional[float] = None
    use_trailing_stop: Optional[bool] = None

    default_order_size_usdc: Optional[float] = None
    max_position_size_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    max_portfolio_exposure_pct: Optional[float] = None

    signal_timeframe: Optional[str] = None
    signal_cooldown_seconds: Optional[int] = None
    min_signal_confidence: Optional[float] = None
    min_volume_ratio: Optional[float] = None

    trend_timeframe: Optional[str] = None
    entry_timeframe: Optional[str] = None

    use_market_regime_filter: Optional[bool] = None
    use_trend_filter: Optional[bool] = None
    use_entry_filter: Optional[bool] = None
    use_atr_filter: Optional[bool] = None

    min_indicators_required: Optional[int] = None
    min_entry_indicators_required: Optional[int] = None

    use_trend_invalidation_exit: Optional[bool] = None
    trend_invalidation_indicators: Optional[str] = None
    min_position_age_for_trend_check: Optional[int] = None
    max_position_hours: Optional[int] = None

    is_active: Optional[bool] = None


class ProfileCredentialsRequest(BaseModel):
    raw_api_key: str
    raw_secret: str


class CircuitBreakerUpdateRequest(BaseModel):
    max_daily_profit_pct: Optional[float] = None
    max_daily_loss_pct: Optional[float] = None
    profit_lock_hours: Optional[int] = None
    loss_lock_hours: Optional[int] = None
    is_active: Optional[bool] = None

