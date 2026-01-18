from pydantic import BaseModel, Field, validator
from typing import Optional, Literal, List
from enum import Enum

class TradingViewAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    CLOSE = "close"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    TREND_UPDATE = "trend_update"

class TradingViewAlert(BaseModel):
    """Model for TradingView webhook alert"""
    action: TradingViewAction = Field(..., description="Trading action (buy/sell/close)")
    symbol: str = Field(..., description="Trading pair (e.g., SOL_USDC)")
    price: Optional[str] = Field(None, description="Limit price (optional, market order if not provided)")
    current_price: Optional[str] = Field(None, alias="price", description="Current market price from TradingView")
    quantity: Optional[str] = Field(None, description="Order quantity")
    quote_quantity: Optional[str] = Field(None, alias="quoteQuantity", description="Quote quantity for market orders")
    profile: str | None = Field(None, description="Trading profile(s) - comma-separated for multiple profiles")
    
    # Parsed profiles (computed from profile field)
    profiles: List[str] = Field(default_factory=lambda: ["default"], description="List of profile names to execute")

    # Optional advanced parameters
    stop_loss: Optional[str] = Field(None, alias="stopLoss", description="Stop loss price")
    trailing_stop_loss: Optional[str] = Field(None, alias="trailingStopLoss", description="Trailing stop loss price")
    take_profit: Optional[str] = Field(None, alias="takeProfit", description="Take profit price")
    post_only: Optional[bool] = Field(False, alias="postOnly")
    reduce_only: Optional[bool] = Field(False, alias="reduceOnly")
    
    # TradingView specific fields
    ticker: Optional[str] = Field(None, description="TradingView ticker")
    exchange: Optional[str] = Field(None, description="Exchange name")
    interval: Optional[str] = Field(None, description="Timeframe")
    strategy: Optional[str] = Field(None, description="Strategy name")
    
    # Authentication
    secret: Optional[str] = Field(None, description="Webhook secret for authentication")
    
    class Config:
        populate_by_name = True
        use_enum_values = True
    
    @validator('profiles', pre=True, always=True)
    def parse_profiles(cls, v, values):
        """Parse profile field into list of profile names"""
        # If profiles is already set (from direct instantiation), use it
        if v and v != ["default"]:
            return v
            
        # Otherwise parse from profile field
        profile_str = values.get('profile')
        
        if not profile_str or profile_str.strip() == "":
            return ["default"]
        
        # Split by comma, strip whitespace, filter empty strings
        profiles = [p.strip() for p in profile_str.split(',') if p.strip()]
        
        # If parsing resulted in empty list, default to ["default"]
        return profiles if profiles else ["default"]
    
    @validator('symbol', pre=True)
    def normalize_symbol(cls, v, values):
        """Normalize symbol format from TradingView to exchange format"""
        # If ticker is provided, use it to construct symbol
        if 'ticker' in values and values.get('ticker'):
            ticker = values['ticker'].upper()
            # Convert TradingView format (e.g., "SOLUSD") to exchange format
            # Adjust this logic based on your exchange's format
            if ticker.endswith('USD'):
                base = ticker[:-3]
                return f"{base}_USDC"
            elif ticker.endswith('USDT'):
                base = ticker[:-4]
                return f"{base}_USDT"
        
        # Otherwise use symbol as-is, ensuring uppercase
        return v.upper() if v else v
    
    @validator('action')
    def validate_action(cls, v):
        """Ensure action is lowercase"""
        return v.lower() if isinstance(v, str) else v


class WebhookResponse(BaseModel):
    """Response model for webhook"""
    success: bool
    message: str
    results: List[dict] = Field(default_factory=list, description="Results per profile")
    details: Optional[dict] = None

class TrendData(BaseModel):
    """Trend indicator data from TradingView"""
    symbol: str
    timeframe: str  # e.g., "1h", "4h"
    ema20: float
    ema50: float
    rsi: float
    vwap: float
    price: float
    timestamp: Optional[float] = None
    volume: Optional[float] = None
    volume_sma: Optional[float] = None  # 20-period average
    volume_ratio: Optional[float] = None  # current / average

    def is_bullish(self, min_rsi: float = 50) -> bool:
        """Quick check if trend is bullish"""
        return (
            self.ema20 > self.ema50 and 
            self.rsi > min_rsi and 
            self.price > self.vwap
        )

class TrendUpdateAlert(BaseModel):
    """Alert from TradingView trend monitor"""
    action: str = Field(default="trend_update")
    secret: str
    trends: List[TrendData]  # Can send multiple symbols at once
