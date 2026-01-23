from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Tuple


class SignalStrength(Enum):
    """Signal confidence levels"""
    WEAK = 1        # 60-70% confidence
    MODERATE = 2    # 70-80% confidence
    STRONG = 3      # 80-90% confidence
    VERY_STRONG = 4 # 90%+ confidence


@dataclass
class TradingSignal:
    """Represents a trading signal"""
    symbol: str
    action: str  # "BUY", "SELL", "HOLD"
    strength: SignalStrength
    confidence: float  # 0-100
    reasons: List[str]  # Why this signal was generated
    indicators: Dict[str, any]  # Raw indicator values
    timestamp: float
    timeframe: str
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "strength": self.strength.name,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "indicators": self.indicators,
            "timestamp": self.timestamp,
            "timeframe": self.timeframe
        }
