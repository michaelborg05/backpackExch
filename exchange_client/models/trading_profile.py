from dataclasses import dataclass
from pydantic import BaseModel, Field
from typing import Optional
from decimal import Decimal

class TradingProfile(BaseModel):
    name: str
    api_key: str
    secret: str    
    
    # Position management settings (as percentages)
    take_profit_pct: Optional[Decimal] = Field(None, description="Take profit percentage (e.g., 5.0 for 5%)")
    stop_loss_pct: Optional[Decimal] = Field(None, description="Stop loss percentage (e.g., 2.0 for 2%)")
    trailing_stop_pct: Optional[Decimal] = Field(None, description="Trailing stop percentage (e.g., 1.5 for 1.5%)")
    use_trailing_stop: bool = False
    
    # Risk management
    max_risk_pct: Decimal = Field(Decimal("0.25"), description="Max risk per trade as % of portfolio")
    default_order_size_pct: Decimal = Field(Decimal("5"), description="Default order size as % of portfolio")
    max_position_size: Optional[Decimal] = None
