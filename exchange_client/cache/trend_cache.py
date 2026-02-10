# cache/trend_cache.py - Enhanced with database persistence for cache warmup

from typing import Dict, Optional, Tuple, List
import time
from utils.logging import log_manager
from models.webhook import TrendData


class TrendCache:
    """
    Smart cache with dual tracking + configurable multi-timeframe validation + DB persistence
    1. Always refreshes cache (for volume, VWAP, price)
    2. Only tracks RSI/EMA history when indicators actually change
    3. Multi-timeframe validation fully configurable via profile YAML
    4. Persists significant indicator changes to database for cache warmup after restarts
    """
    
    def __init__(self, max_age: int = 1200):
        self.logger = log_manager.get_logger("TrendCache")
        self.max_age = max_age
        
        # Main cache (always updated - keeps fresh timestamps)
        self._cache: Dict[str, TrendData] = {}
        
        # RSI history (only updated when RSI actually changes)
        self._rsi_history: Dict[str, list] = {}
        
        # EMA history for slope calculation (only updated when EMAs change)
        self._ema_history: Dict[str, list] = {}
        
        # Track statistics
        self._stats = {
            'total_updates': 0,
            'indicator_changes': 0,
            'refresh_only': 0,
            'db_saves': 0,
            'db_save_errors': 0
        }
    
    def update(self, trend_data: TrendData, persist_to_db: bool = True):
        """
        Update trend data with smart handling
        
        Always updates cache (to refresh timestamp, price, volume, VWAP)
        Only updates RSI/EMA history when indicators actually changed
        Optionally persists significant changes to database
        
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
        
        # Only update histories when indicators actually changed
        if indicators_changed:
            # Update RSI history
            if key not in self._rsi_history:
                self._rsi_history[key] = []
            
            self._rsi_history[key].append((trend_data.timestamp, trend_data.rsi))
            
            # Keep last 5 significant changes
            if len(self._rsi_history[key]) > 5:
                self._rsi_history[key] = self._rsi_history[key][-5:]
            
            # Update EMA history for slope calculation
            if key not in self._ema_history:
                self._ema_history[key] = []
            
            self._ema_history[key].append({
                'timestamp': trend_data.timestamp,
                'ema20': trend_data.ema20,
                'ema50': trend_data.ema50
            })
            
            # Keep last 3 significant changes for slope (need 2-3 points)
            if len(self._ema_history[key]) > 3:
                self._ema_history[key] = self._ema_history[key][-3:]
            
            # Persist to database if enabled
            if persist_to_db:
                self._save_to_database(trend_data)
            
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
    
    def _save_to_database(self, trend_data: TrendData):
        """
        Save trend snapshot to database for cache warmup after restarts.
        Uses a separate session to avoid interfering with main application flow.
        """
        
        from db.utils import get_db_session

        with get_db_session() as db:
            from db.crud_trend import save_trend_snapshot
            
            try:
                save_trend_snapshot(db, trend_data, max_entries_per_symbol=5)
                self._stats['db_saves'] += 1
                
                self.logger.debug(
                    f"💾 Saved to DB: {trend_data.symbol} ({trend_data.timeframe})"
                )
            except Exception as e:
                self._stats['db_save_errors'] += 1
                self.logger.error(
                    f"❌ Failed to save trend to database: {e}",
                    exc_info=True
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
    
    def _get_ema_slope(self, symbol: str, timeframe: str, ema_type: str = 'ema20') -> Tuple[Optional[float], Optional[str]]:
        """
        Calculate EMA slope (rate of change)
        
        Returns:
            (slope_value, direction_description)
            - slope_value: positive = rising, negative = falling (percentage change)
            - direction: "rising", "falling", or "flat"
        """
        key = f"{symbol}_{timeframe}"
        
        if key not in self._ema_history or len(self._ema_history[key]) < 2:
            return None, None
        
        history = self._ema_history[key]
        
        # Get current and previous EMA values
        current = history[-1][ema_type]
        previous = history[-2][ema_type]
        
        # Calculate percentage change
        slope_pct = ((current - previous) / previous) * 100
        
        # Determine direction
        if slope_pct > 0.01:  # Rising threshold: 0.01%
            direction = "rising"
        elif slope_pct < -0.01:  # Falling threshold: -0.01%
            direction = "falling"
        else:
            direction = "flat"
        
        return slope_pct, direction

    

    
    def _get_rsi_momentum(self, symbol: str, timeframe: str) -> Tuple[Optional[float], Optional[str]]:
        """
        Calculate RSI momentum (rate of change)
        
        Returns:
            (momentum_value, direction_description)
            - momentum_value: absolute change in RSI
            - direction: "increasing", "decreasing", or "stable"
        """
        key = f"{symbol}_{timeframe}"
        
        if key not in self._rsi_history or len(self._rsi_history[key]) < 2:
            return None, None
        
        history = self._rsi_history[key]
        
        # Get current and previous RSI values
        current_rsi = history[-1][1]
        previous_rsi = history[-2][1]
        
        # Calculate momentum
        momentum = current_rsi - previous_rsi
        
        # Determine direction
        if momentum > 1:  # Increasing threshold
            direction = "increasing"
        elif momentum < -1:  # Decreasing threshold
            direction = "decreasing"
        else:
            direction = "stable"
        
        return momentum, direction
    
    def get(self, symbol: str, timeframe: str) -> Optional[TrendData]:
        """Get cached trend data if available and not stale"""
        key = f"{symbol}_{timeframe}"
        trend_data = self._cache.get(key)
        
        if trend_data and hasattr(trend_data, 'timestamp'):
            age = time.time() - trend_data.timestamp
            if age <= self.max_age:
                return trend_data
            else:
                self.logger.warning(f"Stale trend data for {key} (age: {age:.0f}s)")
        
        return None
    
    def is_bullish(
        self,
        symbol: str,
        timeframe: str,
        indicators_config: List[Dict] = None,
        min_indicators_required: int = 2
    ) -> Tuple[bool, str]:
        """
        ORIGINAL FUNCTION PRESERVED - Check if trend is bullish for a single timeframe
        
        This is the main function used by:
        - position_manager.py (_check_trend_invalidation)
        - signal_generator.py (should_trade)
        - api_server.py (various endpoints)
        
        Args:
            symbol: Trading symbol
            timeframe: Single timeframe to check
            indicators_config: List of indicator configs
            min_indicators_required: Minimum bullish indicators needed
            
        Returns:
            (is_bullish, reason_string)
        """
        trend = self.get(symbol, timeframe)
        
        if trend is None:
            return False, f"No trend data for {symbol} {timeframe}"
        
        # Default to all 3 indicators if not specified
        if indicators_config is None:
            indicators_config = [
                {"type": "ema_cross", "params": {"fast": 20, "slow": 50}},
                {"type": "rsi_threshold", "params": {"period": 14, "min_value": 50}},
                {"type": "price_vs_vwap", "params": {}}
            ]

        return self._validate_timeframe_indicators(
            symbol,
            timeframe,
            trend,
            indicators_config,
            min_indicators_required
        )
    
    def validate_multi_timeframe_trend(
        self,
        symbol: str,
        required_timeframes: List[Dict]
    ) -> Tuple[bool, str]:
        """
        NEW FUNCTION - Validate trend across multiple timeframes
        
        This is an ADDITIONAL function, not a replacement for is_bullish()
        Use this when you need to check multiple timeframes at once.
        
        Args:
            symbol: The trading symbol
            required_timeframes: List of dicts, each with:
                {
                    "timeframe": "1h",
                    "min_indicators_required": 3,
                    "indicators": [
                        {"type": "ema_cross", "params": {...}},
                        {"type": "rsi_threshold", "params": {...}},
                        ...
                    ]
                }
        
        Returns:
            (is_valid, reason_string)
        """
        if not required_timeframes:
            return True, "No timeframe requirements"
        
        results = []
        
        for tf_config in required_timeframes:
            timeframe = tf_config["timeframe"]
            min_indicators = tf_config.get("min_indicators_required", len(tf_config["indicators"]))
            indicators = tf_config.get("indicators", [])
            
            trend = self.get(symbol, timeframe)
            
            if not trend:
                results.append((False, f"{timeframe}: No data"))
                continue
            
            # Validate indicators for this timeframe
            is_valid, reason = self._validate_timeframe_indicators(
                symbol,
                timeframe,
                trend,
                indicators,
                min_indicators
            )
            
            results.append((is_valid, f"{timeframe}: {reason}"))
        
        # All required timeframes must pass
        all_valid = all(is_valid for is_valid, _ in results)
        
        if all_valid:
            reasons = [reason for _, reason in results]
            return True, " | ".join(reasons)
        else:
            # Return first failure
            for is_valid, reason in results:
                if not is_valid:
                    return False, reason
            
            return False, "Unknown validation failure"
    
    def _validate_timeframe_indicators(
        self,
        symbol: str,
        timeframe: str,
        trend: TrendData,
        indicators: List[Dict],
        min_indicators_required: int
    ) -> Tuple[bool, str]:
        """
        Validate multiple indicators for a single timeframe.
        Returns True if at least min_indicators_required pass.
        
        SUPPORTS BOTH OLD AND NEW INDICATOR NAMES:
        - "ema_alignment" (old) → treated as "ema_cross"
        - "ema_cross" (new) → EMA20 > EMA50
        - Both work identically
        """
        results = []
        hard_stop_failures = []

        for indicator_config in indicators:
            indicator_type = indicator_config.get("type")
            params = indicator_config.get("params", {})
            hard_stop = params.get("hard_stop", False)  

            # === BACKWARD COMPATIBILITY: ema_alignment → ema_cross ===
            if indicator_type == "ema_alignment":
                indicator_type = "ema_cross"  # Treat as ema_cross
            
            # === CORE INDICATORS (ORIGINAL) ===
            
            if indicator_type == "ema_cross":
                # EMA20 must be above EMA50 (with optional slope check)
                use_slope = params.get("use_slope", False)
                min_slope_pct = params.get("min_slope_pct", 0.01)
                
                if use_slope:
                    # Check both cross and slope
                    slope_pct, slope_direction = self._get_ema_slope(symbol, timeframe, "ema20")
                    
                    if slope_pct is None:
                        is_bullish = trend.ema20 > trend.ema50
                        msg = f"EMA cross: {'✓' if is_bullish else '✗'} (no slope data)"
                    else:
                        is_bullish = (
                            trend.ema20 > trend.ema50 and 
                            slope_pct > min_slope_pct
                        )
                        msg = f"EMA cross: {'✓' if is_bullish else '✗'} ({trend.ema20:.2f} vs {trend.ema50:.2f} - slope: {slope_direction})"
                else:
                    is_bullish = trend.ema20 > trend.ema50
                    msg = f"EMA cross: {'✓' if is_bullish else '✗'} ({trend.ema20:.2f} vs {trend.ema50:.2f})"
                
                results.append((is_bullish, msg))
                if hard_stop and not is_bullish:
                    hard_stop_failures.append(msg)
                
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
                        (trend.rsi > min_rsi and rsi_direction in ("increasing", "stable")) or 
                        (trend.rsi > early_threshold and rsi_momentum > 2)
                    )
                    
                    # Build descriptive message
                    if trend.rsi > min_rsi  and rsi_direction in ("increasing", "stable"):
                        msg = f"RSI: ✓ ({trend.rsi:.1f} > {min_rsi}) - {rsi_direction} momentum {rsi_momentum:+.1f}"
                    elif trend.rsi > early_threshold and rsi_direction == "increasing":
                        msg = f"RSI: ✓ ({trend.rsi:.1f} {rsi_direction} momentum: {rsi_momentum:+.1f})"
                    else:
                        msg = f"RSI: ✗ ({trend.rsi:.1f} {rsi_direction or 'no momentum'})"
                else:
                    is_bullish = trend.rsi > min_rsi
                    msg = f"RSI: {'✓' if is_bullish else '✗'} ({trend.rsi:.1f} vs {min_rsi})"
                
                results.append((is_bullish, msg))
                if hard_stop and not is_bullish:
                    hard_stop_failures.append(msg)

            elif indicator_type == "price_vs_vwap":
                # Uses latest price and VWAP (refreshed every update)
                is_bullish = trend.price > trend.vwap
                msg = f"Price vs VWAP: {'✓' if is_bullish else '✗'} ({trend.price:.2f} vs {trend.vwap:.2f})"
                results.append((is_bullish, msg))
                if hard_stop and not is_bullish:
                    hard_stop_failures.append(msg)
            
            # === NEW INDICATORS ===
            
            elif indicator_type == "price_vs_ema":
                # Check if price is above a specific EMA
                # params: {ema: 20|50, min_gap_pct: 0.0}
                ema_type = params.get("ema", 20)
                min_gap_pct = params.get("min_gap_pct", 0.0)
                max_gap_pct = params.get("max_gap_pct", 0.0)

                ema_value = trend.ema20 if ema_type == 20 else trend.ema50
                gap_pct = ((trend.price - ema_value) / ema_value) * 100
                
                is_bullish = gap_pct >= min_gap_pct
                if max_gap_pct > 0:
                    is_bullish = is_bullish and gap_pct <= max_gap_pct
                msg = f"Price vs EMA{ema_type}: {'✓' if is_bullish else '✗'} ({gap_pct:+.2f}% gap - min {min_gap_pct:+.2f}%" 
                if max_gap_pct > 0:
                    msg += f"/max {max_gap_pct:+.2f}%)"
                else:
                    msg += f"/no max limit)"
                results.append((is_bullish, msg))
                if hard_stop and not is_bullish:
                    hard_stop_failures.append(msg)
            
            elif indicator_type == "ema_slope":
                # Check if EMA is rising/falling/flat
                # params: {ema: 20|50, direction: "rising"|"not_falling", min_slope_pct: 0.01}
                ema_type = params.get("ema", 20)
                required_direction = params.get("direction", "rising")
                min_slope_pct = params.get("min_slope_pct", 0.01)
                
                ema_name = f"ema{ema_type}"
                slope_pct, _ = self._get_ema_slope(symbol, timeframe, ema_name)
                
                if slope_pct is None:
                    is_bullish = False
                    msg = f"EMA{ema_type} slope: ✗ (no data)"
                else:
                    if required_direction == "rising":
                        is_bullish = slope_pct > min_slope_pct
                        direction = "rising" if slope_pct > min_slope_pct else "flat/falling"
                    elif required_direction == "not_falling":
                        is_bullish = slope_pct >= -min_slope_pct
                        direction = "rising/flat" if is_bullish else "falling"
                    else:
                        is_bullish = abs(slope_pct) <= min_slope_pct
                        direction = "flat"
                    
                    msg = f"EMA{ema_type} slope: {'✓' if is_bullish else '✗'} ({direction} {slope_pct:+.3f}%)"
                
                results.append((is_bullish, msg))
                if hard_stop and not is_bullish:
                    hard_stop_failures.append(msg)
            
            elif indicator_type == "rsi_range":
                # Block if RSI is in a specific range (indecision zone)
                # params: {min: 48, max: 52, invert: false}
                # If invert=false: BLOCKS when RSI is in range (default for indecision)
                # If invert=true: BLOCKS when RSI is NOT in range
                min_rsi = params.get("min", 30)
                max_rsi = params.get("max", 70)
                invert = params.get("invert", False)
                momentum_override = params.get('momentum_override_threshold', None)
                rsi_momentum, rsi_direction = self._get_rsi_momentum(symbol, timeframe)

                in_range = min_rsi <= trend.rsi <= max_rsi
                if invert:
                    is_bullish = in_range
                    msg = f"RSI range: {'✓' if is_bullish else '✗'} (RSI {trend.rsi:.1f} {'in' if in_range else 'outside'} {min_rsi}-{max_rsi})"
                else:
                    is_bullish = not in_range
                    if is_bullish == False and momentum_override is not None and rsi_momentum is not None:
                        if abs(rsi_momentum) >= momentum_override:
                            is_bullish = rsi_momentum > 0 
                            msg = (
                                f"RSI range: momentum override {'✓' if is_bullish else '✗'} "
                                f"(RSI {trend.rsi:.1f}, momentum {rsi_momentum:+.2f} - "
                                f"direction {rsi_direction})"
                            )
                        else: 
                            msg = f"RSI range: {'✓' if is_bullish else '✗'} (RSI {trend.rsi:.1f} {'outside' if is_bullish else 'in'} indecision {min_rsi}-{max_rsi})"
                    else: 
                        msg = f"RSI range: {'✓' if is_bullish else '✗'} (RSI {trend.rsi:.1f} {'outside' if is_bullish else 'in'} indecision {min_rsi}-{max_rsi})"

                results.append((is_bullish, msg))
                if hard_stop and not is_bullish:
                    hard_stop_failures.append(msg)
            
            elif indicator_type == "ema_gap":
                # Check gap between EMA20 and EMA50
                # params: {min_gap_pct: 0.3, mode: "min"|"max"}
                # mode="min": Require gap > min_gap_pct (trending)
                # mode="max": Require gap < min_gap_pct (not overextended)
                min_gap_pct = params.get("min_gap_pct", 0.3)
                mode = params.get("mode", "min")
                max_gap_pct = params.get("max_gap_pct", 0.3)
                
                gap_pct = abs((trend.ema20 - trend.ema50) / trend.ema50) * 100
                
                if mode == "min":
                    is_bullish = gap_pct >= min_gap_pct
                    msg = f"EMA gap: {'✓' if is_bullish else '✗'} ({gap_pct:.2f}% gap - need >{min_gap_pct}%)"
                else:  # mode == "max"
                    is_bullish = gap_pct <= max_gap_pct
                    msg = f"EMA gap: {'✓' if is_bullish else '✗'} ({gap_pct:.2f}% gap - need <{max_gap_pct}%)"

                results.append((is_bullish, msg))
                if hard_stop and not is_bullish:
                    hard_stop_failures.append(msg)
            
            elif indicator_type == "price_ema50_range":
                # Check if price is oscillating around EMA50 (choppy)
                # params: {max_gap_pct: 1.0}
                # Blocks if price is within +/- max_gap_pct of EMA50
                max_gap_pct = params.get("max_gap_pct", 1.0)
                
                gap_pct = abs((trend.price - trend.ema50) / trend.ema50) * 100
                
                is_bullish = gap_pct > max_gap_pct
                msg = f"Price/EMA50 range: {'✓' if is_bullish else '✗'} ({gap_pct:.2f}% from EMA50 - need >{max_gap_pct}%)"
                results.append((is_bullish, msg))
                if hard_stop and not is_bullish:
                    hard_stop_failures.append(msg)

        # NEW: Check for hard_stop failures FIRST (before scoring)
        if hard_stop_failures:
            details = ", ".join(msg for _, msg in results)
            failed_indicators = "; ".join(hard_stop_failures)
            return False, f"🚫 HARD STOP: {failed_indicators} ({details})"   
             
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
        """Get cache status with statistics including DB persistence stats"""
        total = self._stats['total_updates']
        significant = self._stats['indicator_changes']
        refresh = self._stats['refresh_only']
        db_saves = self._stats['db_saves']
        db_errors = self._stats['db_save_errors']
        
        return {
            "symbols_cached": len(self._cache),
            "total_updates": total,
            "indicator_changes": significant,
            "refresh_only": refresh,
            "efficiency_pct": (refresh / total * 100) if total > 0 else 0,
            "db_saves": db_saves,
            "db_save_errors": db_errors,
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


def initialize_trend_cache_with_db() -> TrendCache:
    """
    Initialize the global trend cache with database support.
    Call this during application startup after database is configured.
    
    Args:
        db_session_factory: Factory function that returns a new database session
        persist_to_db: Whether to persist trend changes to database (default True)
        
    Returns:
        Initialized TrendCache instance
    """
    global _trend_cache
    _trend_cache = TrendCache()
    return _trend_cache