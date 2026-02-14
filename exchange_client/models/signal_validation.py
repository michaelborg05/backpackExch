# models/signal_validation.py
"""
Structured signal validation model for AI-parseable and human-readable signal analysis.

This replaces the list-of-strings approach with a structured JSON model that preserves
all validation details while being easy for AI and humans to understand.
"""

from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from utils.constants import StrategyType, MarketRegime, TrendState, OrderType
from enum import Enum
import json

@dataclass
class IndicatorResult:
    """
    Result of a single indicator check.
    
    Attributes:
        type: Indicator type (e.g., "rsi_threshold", "ema_slope")
        is_bullish: Whether the indicator passed (True) or failed (False)
        config: Configuration parameters from the profile YAML
        values: Actual values measured (e.g., RSI level, slope percentage)
        message: Human-readable summary
    """
    type: str
    is_bullish: bool
    config: Dict[str, Any]
    values: Dict[str, Any]
    message: str
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class ValidationGroup:
    """
    Group of related indicator checks (e.g., trend validation, entry validation).
    
    Attributes:
        enabled: Whether this validation group is active
        timeframe: Timeframe these indicators operate on
        passed: Whether the overall group passed validation
        indicators_passed: Number of indicators that passed
        indicators_total: Total number of indicators checked
        summary: Brief human-readable summary
        indicators: List of individual indicator results
    """
    enabled: bool
    timeframe: Optional[str] = None
    passed: bool = False
    indicators_passed: int = 0
    indicators_total: int = 0
    summary: str = ""
    indicators: List[IndicatorResult] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary with nested indicator results"""
        return {
            "enabled": self.enabled,
            "timeframe": self.timeframe,
            "passed": self.passed,
            "indicators_passed": self.indicators_passed,
            "indicators_total": self.indicators_total,
            "summary": self.summary,
            "indicators": [ind.to_dict() for ind in self.indicators]
        }


@dataclass
class MarketContext:
    """
    Market context information (regime, volume, volatility).
    """
    regime: Dict[str, Any] = field(default_factory=dict)
    volume: Dict[str, Any] = field(default_factory=dict)
    volatility: Dict[str, Any] = field(default_factory=dict)
    atr: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SignalValidationResult:
    """
    Complete validation result for a trading signal.
    
    This structure provides:
    - Machine-parseable data for AI analysis
    - Human-readable summaries for logs/Telegram
    - Complete audit trail of all checks
    - Configuration tracking for post-analysis
    """
    # Metadata
    timestamp: float
    symbol: str
    order_type: OrderType
    signal_timeframe: str
    strategy_type: str
    score: float
    score_components: int
    
    # Market context
    market_context: MarketContext
    
    # Validation groups
    trend_validation: ValidationGroup
    entry_validation: ValidationGroup
    
    # Additional checks
    additional_checks: List[IndicatorResult] = field(default_factory=list)
    
    # Summary
    overall_passed: bool = True
    human_readable: str = ""
    
    def to_dict(self) -> dict:
        """Convert entire validation result to dictionary"""
        return {
            "metadata": {
                "timestamp": self.timestamp,
                "symbol": self.symbol,
                "signal_timeframe": self.signal_timeframe,
                "order_type": self.order_type,
                "strategy_type": self.strategy_type,
                "score": self.score,
                "score_components": self.score_components
            },
            "market_context": self.market_context.to_dict(),
            "trend_validation": self.trend_validation.to_dict(),
            "entry_validation": self.entry_validation.to_dict(),
            "additional_checks": [check.to_dict() for check in self.additional_checks],
            "summary": {
                "overall_passed": self.overall_passed,
                "human_readable": self.human_readable
            }
        }
    
    def to_json(self, indent: Optional[int] = None) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'SignalValidationResult':
        """Reconstruct from dictionary"""
        metadata = data.get("metadata", {})
        market_ctx = MarketContext(**data.get("market_context", {}))
        
        # Reconstruct trend validation
        trend_data = data.get("trend_validation", {})
        trend_indicators = [
            IndicatorResult(**ind) 
            for ind in trend_data.get("indicators", [])
        ]
        trend_validation = ValidationGroup(
            enabled=trend_data.get("enabled", False),
            timeframe=trend_data.get("timeframe"),
            passed=trend_data.get("passed", False),
            indicators_passed=trend_data.get("indicators_passed", 0),
            indicators_total=trend_data.get("indicators_total", 0),
            summary=trend_data.get("summary", ""),
            indicators=trend_indicators
        )
        
        # Reconstruct entry validation
        entry_data = data.get("entry_validation", {})
        entry_indicators = [
            IndicatorResult(**ind) 
            for ind in entry_data.get("indicators", [])
        ]
        entry_validation = ValidationGroup(
            enabled=entry_data.get("enabled", False),
            timeframe=entry_data.get("timeframe"),
            passed=entry_data.get("passed", False),
            indicators_passed=entry_data.get("indicators_passed", 0),
            indicators_total=entry_data.get("indicators_total", 0),
            summary=entry_data.get("summary", ""),
            indicators=entry_indicators
        )
        
        # Reconstruct additional checks
        additional_checks = [
            IndicatorResult(**check) 
            for check in data.get("additional_checks", [])
        ]
        
        summary = data.get("summary", {})
        
        return cls(
            timestamp=metadata.get("timestamp", 0),
            symbol=metadata.get("symbol", ""),
            signal_timeframe=metadata.get("signal_timeframe", ""),
            strategy_type=metadata.get("strategy_type", ""),
            order_type=metadata.get("order_type", ""),
            score=metadata.get("score", 0),
            score_components=metadata.get("score_components", 0),
            market_context=market_ctx,
            trend_validation=trend_validation,
            entry_validation=entry_validation,
            additional_checks=additional_checks,
            overall_passed=summary.get("overall_passed", True),
            human_readable=summary.get("human_readable", "")
        )
    
    def get_telegram_summary(self) -> str:
        """
        Get concise summary for Telegram notifications.
        Can be more detailed than human_readable.
        """
        lines = []
        
        # Header
        lines.append(f"🎯 {self.symbol} | {self.strategy_type}")
        lines.append(f"Score: {self.score:.1f}% | TF: {self.signal_timeframe}")
        
        # Trend
        if self.trend_validation.enabled:
            icon = "✅" if self.trend_validation.passed else "❌"
            lines.append(f"{icon} Trend ({self.trend_validation.timeframe}): {self.trend_validation.summary}")
        
        # Entry
        if self.entry_validation.enabled:
            icon = "✅" if self.entry_validation.passed else "❌"
            lines.append(f"{icon} Entry ({self.entry_validation.timeframe}): {self.entry_validation.summary}")
        
        # Volume
        vol_data = self.market_context.volume
        if vol_data.get("is_sufficient"):
            lines.append(f"✅ Vol: {vol_data.get('ratio', 0):.1f}x")
        else:
            lines.append(f"⚠️ Vol: {vol_data.get('ratio', 0):.1f}x")
        
        return "\n".join(lines)
    
    def get_failed_indicators(self) -> List[str]:
        """
        Get list of failed indicator names for quick analysis.
        Useful for debugging or filtering.
        """
        failed = []
        
        for ind in self.trend_validation.indicators:
            if not ind.is_bullish:
                failed.append(f"Trend:{ind.type}")
        
        for ind in self.entry_validation.indicators:
            if not ind.is_bullish:
                failed.append(f"Entry:{ind.type}")
        
        for ind in self.additional_checks:
            if not ind.is_bullish:
                failed.append(f"Check:{ind.type}")
        
        return failed


# Helper functions for integration

def parse_indicator_details(
    indicator_type: str,
    is_bullish: bool,
    message: str,
    config: Dict[str, Any],
    trend_data: Any
) -> IndicatorResult:
    """
    Parse indicator result into structured format.
    
    Args:
        indicator_type: Type of indicator (e.g., "rsi_threshold")
        is_bullish: Whether indicator passed
        message: Human-readable message from trend_cache
        config: Configuration from YAML profile
        trend_data: TrendData object with actual values
        
    Returns:
        IndicatorResult with structured data
    """
    values = {}
    
    # Extract values based on indicator type
    if indicator_type == "rsi_threshold":
        values = {
            "rsi": float(trend_data.rsi) if trend_data else None,
            "threshold": config.get("min_value"),
            "momentum": None  # Would need to calculate if available
        }
    
    elif indicator_type == "ema_slope":
        # Extract slope from message if available
        ema = config.get("ema", 20)
        values = {
            "ema": ema,
            "slope_pct": None,  # Parse from message or calculate
            "direction": config.get("direction")
        }
    
    elif indicator_type == "price_vs_ema":
        ema = config.get("ema", 20)
        ema_value = getattr(trend_data, f'ema{ema}', None) if trend_data else None
        price = trend_data.price if trend_data else None
        
        if ema_value and price:
            gap_pct = ((price - ema_value) / ema_value) * 100
        else:
            gap_pct = None
        
        values = {
            "ema": ema,
            "price": price,
            "ema_value": float(ema_value) if ema_value else None,
            "gap_pct": gap_pct
        }
    
    elif indicator_type == "price_vs_vwap":
        price = trend_data.price if trend_data else None
        vwap = trend_data.vwap if trend_data else None
        
        if price and vwap:
            gap_pct = ((price - vwap) / vwap) * 100
        else:
            gap_pct = None
        
        values = {
            "price": price,
            "vwap": float(vwap) if vwap else None,
            "gap_pct": gap_pct
        }
    
    elif indicator_type == "ema_cross":
        fast = config.get("fast", 20)
        slow = config.get("slow", 50)
        
        fast_ema = getattr(trend_data, f'ema{fast}', None) if trend_data else None
        slow_ema = getattr(trend_data, f'ema{slow}', None) if trend_data else None
        
        values = {
            "fast_ema": fast,
            "slow_ema": slow,
            "fast_value": float(fast_ema) if fast_ema else None,
            "slow_value": float(slow_ema) if slow_ema else None
        }
    
    # Add more indicator types as needed
    
    return IndicatorResult(
        type=indicator_type,
        is_bullish=is_bullish,
        config=config,
        values=values,
        message=message
    )


def build_validation_result_from_trend_cache(
    symbol: str,
    timeframe: str,
    strategy_type: str,
    order_type: OrderType,
    trend_validation_enabled: bool,
    trend_timeframe: Optional[str],
    trend_indicators_config: Optional[List[Dict]],
    trend_min_required: int,
    entry_validation_enabled: bool,
    entry_timeframe: Optional[str],
    entry_indicators_config: Optional[List[Dict]],
    entry_min_required: int,
    volume_ratio: float,
    volume_required: float,
    score: float,
    trend_cache_instance: Any
) -> SignalValidationResult:
    """
    Build a SignalValidationResult from trend_cache responses.
    
    This is a bridge function that converts your current trend_cache.is_bullish()
    responses into the structured format.
    
    Args:
        symbol: Trading symbol
        timeframe: Signal generation timeframe
        strategy_type: "trend_following" or "mean_reversion"
        trend_validation_enabled: Whether trend filter is enabled
        trend_timeframe: Timeframe for trend checks (e.g., "60")
        trend_indicators_config: List of trend indicator configs from YAML
        trend_min_required: Minimum passing trend indicators
        entry_validation_enabled: Whether entry filter is enabled
        entry_timeframe: Timeframe for entry checks (e.g., "15")
        entry_indicators_config: List of entry indicator configs from YAML
        entry_min_required: Minimum passing entry indicators
        volume_ratio: Current volume ratio
        volume_required: Required volume ratio
        score: Confidence score
        trend_cache_instance: Instance of TrendCache
        
    Returns:
        SignalValidationResult with complete structured data
    """
    import time
    
    # Get trend data for values
    trend_data = trend_cache_instance.get(symbol, timeframe)
    
    # Market context
    market_context = MarketContext(
        regime={
            "type": "unknown",  # Would need regime filter data
            "confidence": 0.0
        },
        volume={
            "is_sufficient": volume_ratio >= volume_required,
            "ratio": volume_ratio,
            "required_ratio": volume_required,
            "message": f"{volume_ratio:.1f}x average ({volume_required}x required)"
        },
        volatility={
            "atr_ratio": None,
            "is_acceptable": True
        }
    )
    
    # Trend validation
    trend_validation = ValidationGroup(enabled=trend_validation_enabled)
    if trend_validation_enabled and trend_indicators_config:
        is_bullish, reason = trend_cache_instance.is_bullish(
            symbol=symbol,
            timeframe=trend_timeframe,
            indicators_config=trend_indicators_config,
            min_indicators_required=trend_min_required
        )
        
        # Parse the detailed results from _validate_timeframe_indicators
        indicators_list = []
        for indicator_config in trend_indicators_config:
            ind_type = indicator_config.get("type")
            params = indicator_config.get("params", {})
            
            # Get trend data for this timeframe
            tf_trend_data = trend_cache_instance.get(symbol, trend_timeframe)
            
            # For now, we mark based on overall result
            # In a more detailed integration, you'd call the validator for each
            indicators_list.append(
                parse_indicator_details(
                    indicator_type=ind_type,
                    is_bullish=is_bullish,  # Simplified - would need individual results
                    message="",  # Would extract from reason
                    config=params,
                    trend_data=tf_trend_data
                )
            )
        
        trend_validation.timeframe = trend_timeframe
        trend_validation.passed = is_bullish
        trend_validation.indicators = indicators_list
        trend_validation.indicators_total = len(indicators_list)
        trend_validation.indicators_passed = sum(1 for ind in indicators_list if ind.is_bullish)
        trend_validation.summary = reason
    
    # Entry validation
    entry_validation = ValidationGroup(enabled=entry_validation_enabled)
    if entry_validation_enabled and entry_indicators_config:
        is_bullish, reason = trend_cache_instance.is_bullish(
            symbol=symbol,
            timeframe=entry_timeframe,
            indicators_config=entry_indicators_config,
            min_indicators_required=entry_min_required
        )
        
        indicators_list = []
        for indicator_config in entry_indicators_config:
            ind_type = indicator_config.get("type")
            params = indicator_config.get("params", {})
            
            tf_trend_data = trend_cache_instance.get(symbol, entry_timeframe)
            
            indicators_list.append(
                parse_indicator_details(
                    indicator_type=ind_type,
                    is_bullish=is_bullish,
                    message="",
                    config=params,
                    trend_data=tf_trend_data
                )
            )
        
        entry_validation.timeframe = entry_timeframe
        entry_validation.passed = is_bullish
        entry_validation.indicators = indicators_list
        entry_validation.indicators_total = len(indicators_list)
        entry_validation.indicators_passed = sum(1 for ind in indicators_list if ind.is_bullish)
        entry_validation.summary = reason
    
    # Build result
    result = SignalValidationResult(
        timestamp=time.time(),
        symbol=symbol,
        signal_timeframe=timeframe,
        strategy_type=strategy_type,
        order_type=order_type,
        score=score,
        score_components=3,  # Adjust based on actual components
        market_context=market_context,
        trend_validation=trend_validation,
        entry_validation=entry_validation
    )
    
    # Generate human readable summary
    parts = []
    if trend_validation.enabled:
        icon = "✅" if trend_validation.passed else "❌"
        parts.append(f"{icon} Trend ({trend_validation.timeframe}m): {trend_validation.summary}")
    if entry_validation.enabled:
        icon = "✅" if entry_validation.passed else "❌"
        parts.append(f"{icon} Entry ({entry_validation.timeframe}m): {entry_validation.summary}")
    
    vol_icon = "✅" if market_context.volume["is_sufficient"] else "⚠️"
    parts.append(f"{vol_icon} Volume: {volume_ratio:.1f}x")
    parts.append(f"Score: {score:.1f}%")
    
    result.human_readable = " | ".join(parts)
    
    return result


# Example usage
if __name__ == "__main__":
    # Example of creating a result manually
    result = SignalValidationResult(
        timestamp=1707738600.0,
        symbol="SOL_USDC",
        signal_timeframe="15m",
        strategy_type="trend_following",
        order_type=OrderType.BUY,
        score=100.0,
        score_components=3,
        market_context=MarketContext(
            regime={"type": "bullish", "confidence": 0.85},
            volume={
                "is_sufficient": True,
                "ratio": 1.9,
                "required_ratio": 1.1,
                "message": "1.9x average (1.1x required)"
            },
            volatility={"atr_ratio": 1.05, "is_acceptable": True}
        ),
        trend_validation=ValidationGroup(
            enabled=True,
            timeframe="60m",
            passed=True,
            indicators_passed=3,
            indicators_total=3,
            summary="3/3 bullish",
            indicators=[
                IndicatorResult(
                    type="ema_slope",
                    is_bullish=True,
                    config={"ema": 20, "direction": "rising", "min_slope_pct": 0.02},
                    values={"slope_pct": 0.061, "direction": "rising"},
                    message="rising +0.061%"
                ),
                IndicatorResult(
                    type="rsi_threshold",
                    is_bullish=True,
                    config={"period": 14, "min_value": 52, "use_momentum": True},
                    values={"rsi": 52.9, "momentum": 1.6, "threshold": 52},
                    message="52.9 > 52 - increasing momentum +1.6"
                ),
                IndicatorResult(
                    type="price_vs_vwap",
                    is_bullish=True,
                    config={},
                    values={"price": 1968.25, "vwap": 1964.17, "gap_pct": 0.21},
                    message="1968.25 vs 1964.17"
                )
            ]
        ),
        entry_validation=ValidationGroup(
            enabled=True,
            timeframe="15m",
            passed=True,
            indicators_passed=5,
            indicators_total=5,
            summary="5/5 bullish",
            indicators=[
                IndicatorResult(
                    type="price_vs_ema",
                    is_bullish=True,
                    config={"ema": 20, "min_gap_pct": 0.0, "max_gap_pct": 1.5},
                    values={"price": 1968.25, "ema_value": 1966.99, "gap_pct": 0.06},
                    message="+0.06% gap - min +0.00%/max +1.50%"
                )
                # ... more indicators
            ]
        )
    )
    
    # Convert to JSON
    print("JSON Output:")
    print(result.to_json(indent=2))
    
    # Get Telegram summary
    print("\nTelegram Summary:")
    print(result.get_telegram_summary())
    
    # Store in database
    json_for_db = result.to_json()
    print(f"\nJSON for DB (length: {len(json_for_db)} chars)")