from typing import Dict, Optional, Tuple
import time
from utils.logging import log_manager
from models.webhook import TrendData

class TrendCache:
    """Cache for trend data received from TradingView"""
    
    def __init__(self, max_age: int = 600):  # 10 min max age
        self.logger = log_manager.get_logger("TrendCache")
        self.max_age = max_age
        self._cache: Dict[str, TrendData] = {}
        # Store RSI history for momentum calculation
        self._rsi_history: Dict[str, list] = {}  # key: symbol_timeframe, value: [(timestamp, rsi), ...]
    
    
    def update(self, trend_data: TrendData):
        """Update trend data for a symbol/timeframe"""
        key = f"{trend_data.symbol}_{trend_data.timeframe}"
        trend_data.timestamp = time.time()
        self._cache[key] = trend_data
        
        # Update RSI history for momentum tracking
        if key not in self._rsi_history:
            self._rsi_history[key] = []
        
        # Add current RSI to history
        self._rsi_history[key].append((trend_data.timestamp, trend_data.rsi))
        
        # Keep only last 5 entries (enough for momentum calculation)
        if len(self._rsi_history[key]) > 5:
            self._rsi_history[key] = self._rsi_history[key][-5:]
  
        if trend_data.price < 1:
            self.logger.info(
                f"Updated trend: {trend_data.symbol} ({trend_data.timeframe}) - "
                f"EMA: {trend_data.ema20:.5f}/{trend_data.ema50:.5f}, "
                f"RSI: {trend_data.rsi:.1f}, "
                f"Price: ${trend_data.price:.5f}, VWAP: ${trend_data.vwap:.5f}"
            )
        else:
            self.logger.info(
                f"Updated trend: {trend_data.symbol} ({trend_data.timeframe}) - "
                f"EMA: {trend_data.ema20:.2f}/{trend_data.ema50:.2f}, "
                f"RSI: {trend_data.rsi:.1f}, "
                f"Price: ${trend_data.price:.2f}, VWAP: ${trend_data.vwap:.2f}"
            )
    
    def get(self, symbol: str, timeframe: str) -> Optional[TrendData]:
        """Get cached trend data if still valid"""
        key = f"{symbol}_{timeframe}"
        
        if key not in self._cache:
            self.logger.debug(f"No trend data for {symbol} ({timeframe})")
            return None
        
        trend = self._cache[key]
        age = time.time() - (trend.timestamp or 0)
        
        if age > self.max_age:
            self.logger.warning(
                f"Trend data for {symbol} ({timeframe}) is stale ({age:.0f}s old)"
            )
            return None
        
        return trend

    def _get_rsi_momentum(self, symbol: str, timeframe: str) -> Tuple[Optional[float], Optional[str]]:
        """
        Calculate RSI momentum (rate of change)
        
        Returns:
            (momentum_value, direction_description)
            - momentum_value: positive = increasing, negative = decreasing
            - direction: "increasing", "decreasing", or "flat"
        """
        key = f"{symbol}_{timeframe}"
        
        if key not in self._rsi_history or len(self._rsi_history[key]) < 2:
            return None, None
        
        history = self._rsi_history[key]
        
        # Compare current RSI to previous 2-3 readings
        current_rsi = history[-1][1]
        
        # Calculate average of previous 2 RSI values
        if len(history) >= 3:
            prev_avg = (history[-2][1] + history[-3][1]) / 2
        else:
            prev_avg = history[-2][1]
        
        # Calculate momentum
        momentum = current_rsi - prev_avg
        
        # Determine direction
        if momentum > 0.5:  # RSI increasing by more than 0.5 points
            direction = "increasing"
        elif momentum < -0.5:  # RSI decreasing by more than 0.5 points
            direction = "decreasing"
        else:
            direction = "flat"
        
        return momentum, direction
    
    def is_bullish(
        self, 
        symbol: str, 
        timeframe: str,
        indicators_config: list = None,
        min_indicators_required: int = 2
    ) -> tuple[bool, Optional[str]]:
        """
        Check if trend is bullish based on configurable indicators
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe to check
            indicators_config: List of indicator configs from profile
            min_indicators_required: Minimum number that must be bullish
        
        Returns:
            (is_bullish, reason) tuple
        """
        trend = self.get(symbol, timeframe)
        
        if trend is None:
            return False, f"No trend data available for {symbol} ({timeframe})"
        
        # Default to all 3 indicators if not specified
        if indicators_config is None:
            indicators_config = [
                {"type": "ema_alignment", "params": {"fast": 20, "slow": 50}},
                {"type": "rsi_threshold", "params": {"period": 14, "min_value": 50}},
                {"type": "price_vs_vwap", "params": {}}
            ]
        
        # Evaluate each configured indicator
        results = []
        for indicator in indicators_config:
            indicator_type = indicator.get("type")
            params = indicator.get("params", {})
            
            if indicator_type == "ema_alignment":
                is_bullish = trend.ema20 > trend.ema50
                msg = f"EMA{params.get('fast', 20)}/{params.get('slow', 50)}: {'✓' if is_bullish else '✗'} ({trend.ema20:.2f} vs {trend.ema50:.2f})"
                results.append((is_bullish, msg))
                
            elif indicator_type == "rsi_threshold":
                # Get RSI momentum
                rsi_momentum, rsi_direction = self._get_rsi_momentum(symbol, timeframe)
                
                # Enhanced RSI logic with momentum
                min_rsi = params.get("min_value", 50)
                use_momentum = params.get("use_momentum", True)
                early_threshold = params.get("early_threshold", 40)  # Default 40 for early entries
                
                if use_momentum and rsi_momentum is not None:
                    # Bullish conditions:
                    # 1. RSI > min_value (traditional - strong)
                    # 2. RSI > early_threshold AND increasing (catching early momentum)
                    is_bullish = (
                        trend.rsi > min_rsi or 
                        (trend.rsi > early_threshold and rsi_direction == "increasing")
                    )
                    
                    # Build descriptive message
                    if trend.rsi > min_rsi:
                        msg = f"RSI: ✓ ({trend.rsi:.1f} > {min_rsi}) - direction {rsi_direction} momentum {rsi_momentum:+.1f}"
                    elif trend.rsi > early_threshold and rsi_direction == "increasing":
                        msg = f"RSI: ✓ ({trend.rsi:.1f} {rsi_direction}, momentum: {rsi_momentum:+.1f})"
                    else:
                        msg = f"RSI: ✗ ({trend.rsi:.1f}, {rsi_direction or 'no momentum'})"
                else:
                    # Fallback to traditional RSI > threshold
                    is_bullish = trend.rsi > min_rsi
                    msg = f"RSI: {'✓' if is_bullish else '✗'} ({trend.rsi:.1f} vs {min_rsi})"
                
                results.append((is_bullish, msg))
                
            elif indicator_type == "price_vs_vwap":
                is_bullish = trend.price > trend.vwap
                msg = f"Price vs VWAP: {'✓' if is_bullish else '✗'} ({trend.price:.2f} vs {trend.vwap:.2f})"
                results.append((is_bullish, msg))
        
        # Count bullish indicators
        bullish_count = sum(1 for is_bullish, _ in results if is_bullish)
        total_count = len(results)
        
        # Build detailed reason
        details = ", ".join(msg for _, msg in results)
        
        if bullish_count >= min_indicators_required:
            return True, f"{bullish_count}/{total_count} bullish ({details})"
        else:
            return False, f"Only {bullish_count}/{total_count} bullish, need {min_indicators_required} ({details})"
    
    def get_cache_info(self) -> dict:
        """Get cache status"""
        return {
            "symbols_cached": len(self._cache),
            "entries": [
                {
                    "key": key,
                    "age_seconds": time.time() - (data.timestamp or 0),
                    "is_bullish": data.is_bullish()
                }
                for key, data in self._cache.items()
            ]
        }


# Global instance
_trend_cache = None

def get_trend_cache() -> TrendCache:
    """Get or create global trend cache"""
    global _trend_cache
    if _trend_cache is None:
        _trend_cache = TrendCache()
    return _trend_cache
