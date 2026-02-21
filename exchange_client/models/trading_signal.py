from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Tuple
from models.signal_validation import SignalValidationResult

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
    confidence: float  # 0-100
    reasons: List[str]  # Why this signal was generated
    indicators: Dict[str, any]  # Raw indicator values
    timestamp: float
    timeframe: str
    trend_timeframe: str
    regime_confidence: str
    # Optional fields with defaults must come last
    validation_details: Optional[str] = None  # JSON string of SignalValidationResult
    position_size_scalar: float = 1.0          # BB position scalar (1.0 = full size)

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

    def get_validation_result(self) -> Optional[SignalValidationResult]:
        """Parse validation_details JSON back into SignalValidationResult object"""
        if self.validation_details:
            import json
            data = json.loads(self.validation_details)
            return SignalValidationResult.from_dict(data)
        return None