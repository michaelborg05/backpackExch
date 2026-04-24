from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict
from utils.constants import TradeReason

class SignalStrength(Enum):
    """Signal confidence levels"""
    WEAK = 1        # 0-75% confidence
    MEDIUM = 2    # 75-85% confidence
    STRONG = 3      # 85-100% confidence

@dataclass
class TradingSignal:
    """Represents a trading signal"""
    symbol: str
    action: str  # "BUY", "SELL", "HOLD"
    strength: SignalStrength
    source: TradeReason
    confidence: float  # 0-100
    reasons: List[str]  # Why this signal was generated
    indicators: Dict[str, any]  # Raw indicator values
    timestamp: float
    timeframe: str
    trend_timeframe: str
    regime_confidence: str
    # Optional fields with defaults must come last
    signal_snapshot: Optional[Dict] = None  # Flat indicator snapshot stored in trades DB
    position_size_scalar: float = 1.0       # BB position scalar (1.0 = full size)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "strength": self.strength.name,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "indicators": self.indicators,
            "timestamp": self.timestamp,
            "timeframe": self.timeframe,
            "trend_timeframe": self.trend_timeframe,
            "regime_confidence": self.regime_confidence,
            "position_size_scalar": self.position_size_scalar,
        }