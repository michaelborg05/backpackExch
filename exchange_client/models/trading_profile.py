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