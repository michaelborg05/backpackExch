# cache/trend_cache.py - Smart dual-tracking version

from typing import Dict, Optional, Tuple
import time
from utils.logging import log_manager
from models.webhook import TrendData


class TrendCache:
    """
    Smart cache with dual tracking:
    1. Always refreshes cache (for volume, VWAP, price)
    2. Only tracks RSI history when indicators actually change
    """
    
    def __init__(self, max_age: int = 1200):
        self.logger = log_manager.get_logger("TrendCache")
        self.max_age = max_age
        
        # Main cache (always updated - keeps fresh timestamps)
        self._cache: Dict[str, TrendData] = {}
        
        # RSI history (only updated when RSI actually changes)
        self._rsi_history: Dict[str, list] = {}
        
        # Track statistics
        self._stats = {
            'total_updates': 0,
            'indicator_changes': 0,
            'refresh_only': 0
        }
    
    def update(self, trend_data: TrendData):
        """
        Update trend data with smart handling
        
        Always updates cache (to refresh timestamp, price, volume, VWAP)
        Only updates RSI history when indicators actually changed
        
        Args:
            trend_data: New trend data with optional indicators_changed flag
        """
        key = f"{trend_data.symbol}_{trend_data.timeframe}"
        
        # Check if Pine script told us indicators changed
        indicators_changed = getattr(trend_data, 'indicators_changed', None)
        
        # If Pine didn't tell us, check ourselves (fallback)
        if indicators_changed is None:
            old_trend = self._cache.get(key)
            indicators_changed = self._is_significant_change(old_trend, trend_data)
        
        # Update statistics
        self._stats['total_updates'] += 1
        if indicators_changed:
            self._stats['indicator_changes'] += 1
        else:
            self._stats['refresh_only'] += 1
        
        # ALWAYS update cache (refreshes timestamp and dynamic data)
        trend_data.timestamp = time.time()
        old_trend = self._cache.get(key)
        self._cache[key] = trend_data
        
        # Only update RSI history when indicators actually changed
        if indicators_changed:
            if key not in self._rsi_history:
                self._rsi_history[key] = []
            
            # Add to RSI history
            self._rsi_history[key].append((trend_data.timestamp, trend_data.rsi))
            
            # Keep last 5 significant changes
            if len(self._rsi_history[key]) > 5:
                self._rsi_history[key] = self._rsi_history[key][-5:]
            
            # Log the change
            if old_trend:
                self._log_trend_change(trend_data, old_trend)
            else:
                self._log_new_trend(trend_data)
        else:
            # Just a refresh - log at debug level
            self.logger.debug(
                f"Refresh: {trend_data.symbol} ({trend_data.timeframe}) - "
                f"Price: ${trend_data.price:.2f}, "
                f"VWAP: ${trend_data.vwap:.2f}, "
                f"Vol: {trend_data.volume_ratio:.2f}x" if trend_data.volume_ratio else "Vol: N/A"
            )
    
    def _is_significant_change(self, old_trend: Optional[TrendData], new_trend: TrendData) -> bool:
        """
        Check if indicators changed significantly
        (Fallback if Pine script doesn't provide indicators_changed flag)
        """
        if old_trend is None:
            return True
        
        EMA_THRESHOLD = 0.0001
        RSI_THRESHOLD = 0.1
        
        ema20_changed = abs(new_trend.ema20 - old_trend.ema20) > EMA_THRESHOLD
        ema50_changed = abs(new_trend.ema50 - old_trend.ema50) > EMA_THRESHOLD
        rsi_changed = abs(new_trend.rsi - old_trend.rsi) > RSI_THRESHOLD
        
        return (ema20_changed or ema50_changed or rsi_changed)
    
    def _log_new_trend(self, trend_data: TrendData):
        """Log when we first start tracking a symbol/timeframe"""
        if trend_data.price < 1:
            self.logger.info(
                f"🆕 NEW trend tracking: {trend_data.symbol} ({trend_data.timeframe}) - "
                f"EMA: {trend_data.ema20:.5f}/{trend_data.ema50:.5f}, "
                f"RSI: {trend_data.rsi:.1f}, "
                f"Price: ${trend_data.price:.5f}, VWAP: ${trend_data.vwap:.5f}"
            )
        else:
            self.logger.info(
                f"🆕 NEW trend tracking: {trend_data.symbol} ({trend_data.timeframe}) - "
                f"EMA: {trend_data.ema20:.2f}/{trend_data.ema50:.2f}, "
                f"RSI: {trend_data.rsi:.1f}, "
                f"Price: ${trend_data.price:.2f}, VWAP: ${trend_data.vwap:.2f}"
            )
    
    def _log_trend_change(self, new_trend: TrendData, old_trend: TrendData):
        """Log when trend indicators change significantly"""
        changes = []
        
        # Check what changed
        if abs(new_trend.ema20 - old_trend.ema20) > 0.0001:
            changes.append(f"EMA20: {old_trend.ema20:.4f}→{new_trend.ema20:.4f}")
        if abs(new_trend.ema50 - old_trend.ema50) > 0.0001:
            changes.append(f"EMA50: {old_trend.ema50:.4f}→{new_trend.ema50:.4f}")
        if abs(new_trend.rsi - old_trend.rsi) > 0.1:
            changes.append(f"RSI: {old_trend.rsi:.1f}→{new_trend.rsi:.1f}")
        if abs(new_trend.vwap - old_trend.vwap) > 0.0001:
            changes.append(f"VWAP: {old_trend.vwap:.4f}→{new_trend.vwap:.4f}")
        
        if changes:
            self.logger.info(
                f"✨ TREND CHANGED: {new_trend.symbol} ({new_trend.timeframe}) - "
                f"{', '.join(changes)}"
            )

    def _evaluate_rsi_with_momentum(self, trend, params, symbol, timeframe):
        """
        Evaluate RSI with momentum awareness using tiered system
        
        Tiers:
        - STRONG BULLISH: RSI > min_value (traditional)
        - MODERATE BULLISH: RSI > early_threshold AND increasing momentum
        - EMERGING BULLISH: RSI < early_threshold BUT rapid momentum surge (>2 points/change)
        - WEAK BEARISH: RSI > min_value BUT decreasing momentum (warning sign)
        - BEARISH: All other cases
        """
        rsi = trend.rsi
        min_rsi = params.get("min_value", 50)
        use_momentum = params.get("use_momentum", True)
        early_threshold = params.get("early_threshold", 40)
        
        if not use_momentum:
            # Simple threshold check
            is_bullish = rsi > min_rsi
            msg = f"RSI: {'✓' if is_bullish else '✗'} ({rsi:.1f} vs {min_rsi})"
            return is_bullish, msg
        
        # Get momentum
        rsi_momentum, rsi_direction = self._get_rsi_momentum(symbol, timeframe)
        
        if rsi_momentum is None:
            # No momentum data yet - fall back to threshold
            is_bullish = rsi > min_rsi
            msg = f"RSI: {'✓' if is_bullish else '✗'} ({rsi:.1f}, no momentum)"
            return is_bullish, msg
        
        # TIER 1: STRONG BULLISH (traditional threshold + momentum not bearish)
        if rsi > min_rsi and rsi_momentum > -1.0:  # Above threshold, not declining sharply
            msg = f"RSI: ✓ STRONG ({rsi:.1f}, {rsi_direction} {rsi_momentum:+.1f})"
            return True, msg
        
        # TIER 2: MODERATE BULLISH (early threshold + increasing)
        if rsi > early_threshold and rsi_direction == "increasing":
            msg = f"RSI: ✓ MODERATE ({rsi:.1f}, {rsi_direction} {rsi_momentum:+.1f})"
            return True, msg
        
        # TIER 3: EMERGING BULLISH (oversold but surging)
        # Catch early moves: RSI < early_threshold but strong momentum
        if rsi_momentum > 2.0:  # Rapid surge (>2 points per change)
            msg = f"RSI: ✓ EMERGING ({rsi:.1f}, surging {rsi_momentum:+.1f})"
            return True, msg
        
        # WARNING: Above threshold but weakening
        if rsi > min_rsi and rsi_momentum < -1.0:
            msg = f"RSI: ✗ WEAKENING ({rsi:.1f}, fading {rsi_momentum:+.1f})"
            return False, msg
        
        # BEARISH: All other cases
        msg = f"RSI: ✗ ({rsi:.1f}, {rsi_direction or 'flat'} {rsi_momentum:+.1f})"
        return False, msg
    
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
        
        IMPORTANT: This only uses RSI values when they ACTUALLY changed,
        so you get meaningful momentum (not artificial flatness from duplicates)
        
        Returns:
            (momentum_value, direction_description)
            - momentum_value: positive = increasing, negative = decreasing
            - direction: "increasing", "decreasing", or "flat"
        """
        key = f"{symbol}_{timeframe}"
        
        if key not in self._rsi_history or len(self._rsi_history[key]) < 2:
            return None, None
        
        history = self._rsi_history[key]
        
        # Compare current RSI to previous readings
        current_rsi = history[-1][1]
        
        # Calculate average of previous 2 RSI values (actual changes only)
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
                # Get RSI momentum (from actual changes only)
                rsi_momentum, rsi_direction = self._get_rsi_momentum(symbol, timeframe)
                
                # Enhanced RSI logic with momentum
                min_rsi = params.get("min_value", 50)
                use_momentum = params.get("use_momentum", True)
                early_threshold = params.get("early_threshold", 40)
                
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
                        msg = f"RSI: ✓ ({trend.rsi:.1f} > {min_rsi}) - {rsi_direction} momentum {rsi_momentum:+.1f}"
                    elif trend.rsi > early_threshold and rsi_direction == "increasing":
                        msg = f"RSI: ✓ ({trend.rsi:.1f} {rsi_direction}, momentum: {rsi_momentum:+.1f})"
                    else:
                        msg = f"RSI: ✗ ({trend.rsi:.1f}, {rsi_direction or 'no momentum'})"
                else:
                    is_bullish = trend.rsi > min_rsi
                    msg = f"RSI: {'✓' if is_bullish else '✗'} ({trend.rsi:.1f} vs {min_rsi})"
                
                results.append((is_bullish, msg))
                
            elif indicator_type == "price_vs_vwap":
                # Uses latest price and VWAP (refreshed every update)
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
        """Get cache status with statistics"""
        total = self._stats['total_updates']
        significant = self._stats['indicator_changes']
        refresh = self._stats['refresh_only']
        
        return {
            "symbols_cached": len(self._cache),
            "total_updates": total,
            "indicator_changes": significant,
            "refresh_only": refresh,
            "efficiency_pct": (refresh / total * 100) if total > 0 else 0,
            "entries": [
                {
                    "key": key,
                    "age_seconds": time.time() - (data.timestamp or 0),
                    "rsi": data.rsi,
                    "price": data.price,
                    "vwap": data.vwap
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