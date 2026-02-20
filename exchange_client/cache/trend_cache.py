# cache/trend_cache.py - Enhanced with database persistence for cache warmup

from typing import Dict, List, Tuple, Optional, Any
from models.signal_validation import IndicatorResult
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

    

    
    def _get_rsi_momentum(self, symbol: str, timeframe: str, lookback: int = 2) -> Tuple[Optional[float], Optional[str]]:
        """
        Calculate RSI momentum (rate of change)
        
        Returns:
            (momentum_value, direction_description)
            - momentum_value: absolute change in RSI
            - direction: "increasing", "decreasing", or "stable"
        """
        key = f"{symbol}_{timeframe}"
        if key not in self._rsi_history or len(self._rsi_history[key]) < lookback + 1:
            return None, None
        
        history = self._rsi_history[key]
        
        rsi_values = [entry[1] for entry in history]
        momentums = []
        for i in range(lookback):
            # Compare each period: newest - previous
            momentum = rsi_values[-(i+1)] - rsi_values[-(i+2)]
            momentums.append(momentum)
        
        # Average momentum over lookback periods
        avg_momentum = sum(momentums) / len(momentums)
        most_recent_momentum = momentums[0]  # First in list is most recent
        if avg_momentum > 0 and most_recent_momentum <= 0:
            direction = "unstable"
        # Determine direction based on average momentum
        elif avg_momentum > 1:  # Increasing threshold
            direction = "increasing"
        elif avg_momentum < -1:  # Decreasing threshold
            direction = "decreasing"
        else:
            direction = "stable"
        
        return avg_momentum, direction
    
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
        min_indicators_required: int = 2,
        return_structured: bool = False,
        use_hard_stops: bool = True
    ):
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
            return False, f"No trend data for {symbol} {timeframe}", []
        
        # Default to all 3 indicators if not specified
        if indicators_config is None:
            indicators_config = [
                {"type": "ema_cross", "params": {"fast": 20, "slow": 50}},
                {"type": "rsi_threshold", "params": {"period": 14, "min_value": 50}},
                {"type": "price_vs_vwap", "params": {}}
            ]
        
        is_bullish, summary, indicator_results = self._validate_timeframe_indicators(
            symbol, timeframe, trend, indicators_config, min_indicators_required, use_hard_stops
        )
        
        if return_structured:
            return is_bullish, summary, indicator_results
        else:
            # Backward compatible - return just bool and string
            return is_bullish, summary

    
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
        min_indicators_required: int,
        use_hard_stops: bool = True
    ) -> Tuple[bool, str, List[IndicatorResult]]:
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
        indicator_results = []

        from cache.price_cache import get_price_cache
        price_cache = get_price_cache()
        price = price_cache.get_price(symbol)
        current_price = float(price) if price is not None else trend.price

        for indicator_config in indicators:
            indicator_type = indicator_config.get("type")
            params = indicator_config.get("params", {})
            hard_stop = params.get("hard_stop", False)  
            is_bullish = False
            msg = ""
            values = {}

            # === BACKWARD COMPATIBILITY: ema_alignment → ema_cross ===
            if indicator_type == "ema_alignment":
                indicator_type = "ema_cross"  # Treat as ema_cross
            
            # === CORE INDICATORS (ORIGINAL) ===
            
            if indicator_type == "ema_cross":
                # EMA20 must be above EMA50 (with optional slope check)
                use_slope = params.get("use_slope", False)
                min_slope_pct = params.get("min_slope_pct", 0.01)
                values["ema20"] = trend.ema20
                values["ema50"] = trend.ema50
                
                if use_slope:
                    # Check both cross and slope
                    slope_pct, slope_direction = self._get_ema_slope(symbol, timeframe, "ema20")
                    
                    if slope_pct is None:
                        is_bullish = trend.ema20 > trend.ema50
                        msg = f"EMA cross: {'✓' if is_bullish else '✗'} (no slope data)"
                    else:
                        values["slope_pct"] = slope_pct
                        values["slope_direction"] = slope_direction
                        is_bullish = (
                            trend.ema20 > trend.ema50 and 
                            slope_pct >= min_slope_pct
                        )
                        msg = f"EMA cross: {'✓' if is_bullish else '✗'} ({trend.ema20:.2f} vs {trend.ema50:.2f} - slope: {slope_direction})"
                else:
                    is_bullish = trend.ema20 > trend.ema50
                    msg = f"EMA cross: {'✓' if is_bullish else '✗'} ({trend.ema20:.2f} vs {trend.ema50:.2f})"
                
            elif indicator_type == "rsi_threshold":
                # Enhanced RSI logic with momentum
                min_rsi = params.get("min_value", 50)
                use_momentum = params.get("use_momentum", True)
                early_threshold = params.get("early_threshold", 40)
                
                rsi = trend.rsi
                values["rsi"] = float(rsi)
                values["threshold"] = min_rsi

                if use_momentum:
                    rsi_momentum, rsi_direction = self._get_rsi_momentum(symbol, timeframe)
                    values["momentum"] = rsi_momentum
                    values["direction"] = rsi_direction
                    
                    # Early entry logic
                    if rsi >= early_threshold and rsi < min_rsi:
                        if rsi_direction == "increasing" and rsi_momentum >= 1.0:
                            is_bullish = True
                            msg = f"RSI: ✓ {rsi:.1f} early entry (> {early_threshold}  momentum +{rsi_momentum:.1f})"
                        else:
                            is_bullish = False
                            msg = f"RSI: ✗ {rsi:.1f} below {min_rsi} (momentum {rsi_direction} {rsi_momentum:+.1f})"
                    elif rsi >= min_rsi:
                        if rsi_momentum >= 0:
                            is_bullish = True
                        else:
                            is_bullish = False
                        msg = f"RSI: {'✓' if is_bullish else '✗'} {rsi:.1f} > {min_rsi} - {rsi_direction} momentum {rsi_momentum:+.1f}"
                    else:
                        is_bullish = False
                        msg = f"RSI: ✗ {rsi:.1f} < {min_rsi} (no momentum)"
                else:
                    # Simple threshold check
                    is_bullish = rsi >= min_rsi
                    msg = f"RSI: {'✓' if is_bullish else '✗'} {rsi:.1f} {'>' if is_bullish else '<'} {min_rsi}"

            elif indicator_type == "price_vs_vwap":
                # Uses latest price and VWAP (refreshed every update)
                is_bullish = current_price > trend.vwap
                values["price"] = float(current_price)
                values["vwap"] = float(trend.vwap)

                msg = f"Price vs VWAP: {'✓' if is_bullish else '✗'} ({current_price:.2f} vs {trend.vwap:.2f})"
            
            elif indicator_type == "price_vs_ema":
                # Check if price is above a specific EMA
                # params: {ema: 20|50, min_gap_pct: 0.0}
                ema_type = params.get("ema", 20)
                min_gap_pct = params.get("min_gap_pct", 0.0)
                max_gap_pct = params.get("max_gap_pct", 0.0)

                ema_value = trend.ema20 if ema_type == 20 else trend.ema50
                gap_pct = ((current_price - ema_value) / ema_value) * 100
                values["ema_value"] = float(ema_value)
                values["gap_pct"] = float(gap_pct)

                is_bullish = gap_pct >= min_gap_pct
                if max_gap_pct > 0:
                    is_bullish = is_bullish and gap_pct <= max_gap_pct
                msg = f"Price vs EMA{ema_type}: {'✓' if is_bullish else '✗'} ({gap_pct:+.2f}% gap - min {min_gap_pct:+.2f}%" 
                if max_gap_pct > 0:
                    msg += f" - max {max_gap_pct:+.2f}%)"
                else:
                    msg += f" - no max limit)"
            
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
                    values["slope_pct"] = f"NA"

                else:
                    values["slope_pct"] = float(slope_pct)
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
                values["rsi_momentum"] = rsi_momentum
                values["rsi_direction"] = rsi_direction
                values["rsi"] = trend.rsi

                in_range = min_rsi <= trend.rsi <= max_rsi
                values["within_range"] = in_range
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
            
            elif indicator_type == "ema_gap":
                # Check gap between EMA20 and EMA50
                # params: {min_gap_pct: 0.3, mode: "min"|"max"}
                # mode="min": Require gap > min_gap_pct (trending)
                # mode="max": Require gap < min_gap_pct (not overextended)
                min_gap_pct = params.get("min_gap_pct", 0.3)
                mode = params.get("mode", "min")
                max_gap_pct = params.get("max_gap_pct", 0.3)
                
                gap_pct = abs((trend.ema20 - trend.ema50) / trend.ema50) * 100
                values["ema20"] = trend.ema20
                values["ema50"] = trend.ema50
                values["gap_pct"] = gap_pct

                if mode == "min":
                    is_bullish = gap_pct >= min_gap_pct
                    msg = f"EMA gap: {'✓' if is_bullish else '✗'} ({gap_pct:.2f}% gap - need >{min_gap_pct}%)"
                else:  # mode == "max"
                    is_bullish = gap_pct <= max_gap_pct
                    msg = f"EMA gap: {'✓' if is_bullish else '✗'} ({gap_pct:.2f}% gap - need <{max_gap_pct}%)"

            elif indicator_type == "price_ema50_range":
                # Check if price is oscillating around EMA50 (choppy)
                # params: {max_gap_pct: 1.0}
                # Blocks if price is within +/- max_gap_pct of EMA50
                max_gap_pct = params.get("max_gap_pct", 1.0)
                
                gap_pct = abs((current_price - trend.ema50) / trend.ema50) * 100
                values["price"] = current_price
                values["ema50"] = trend.ema50
                values["gap_pct"] = gap_pct
                
                is_bullish = gap_pct > max_gap_pct
                msg = f"Price/EMA50 range: {'✓' if is_bullish else '✗'} ({gap_pct:.2f}% from EMA50 - need >{max_gap_pct}%)"

            elif indicator_type == "rsi_oversold":
                """
                Enter when RSI is LOW (oversold) but starting to turn up
                params: {
                    max_value: 35,          # RSI must be below this (oversold)
                    require_rising: true,   # Must be turning up (not knife-catching)
                    min_momentum: 0.5       # Minimum upward momentum required
                }
                """
                max_value = params.get("max_value", 35)
                require_rising = params.get("require_rising", True)
                min_momentum = params.get("min_momentum", 0.5)
                
                # Check if oversold
                is_oversold = trend.rsi < max_value
                values["rsi"] = trend.rsi

                if require_rising:
                    rsi_momentum, rsi_direction = self._get_rsi_momentum(symbol, timeframe)
                    is_turning_up = (
                        rsi_momentum is not None and 
                        rsi_direction == "increasing" and 
                        rsi_momentum >= min_momentum
                    )
                    values["rsi_momentum"] = rsi_momentum
                    values["rsi_direction"] = rsi_direction
                    values["oversold"] = is_oversold
                    values["is_turning_up"] = is_turning_up

                    is_bullish = is_oversold and is_turning_up
                    msg = (
                        f"RSI oversold: {'✓' if is_bullish else '✗'} "
                        f"(RSI {trend.rsi:.1f} {'<' if is_oversold else '>'} {max_value}, "
                        f"momentum {rsi_momentum if rsi_momentum else 'N/A'} - {rsi_direction})"
                    )
                else:
                    is_bullish = is_oversold
                    msg = f"RSI oversold: {'✓' if is_bullish else '✗'} (RSI {trend.rsi:.1f} < {max_value})"

            elif indicator_type == "rsi_overbought":
                """
                INVERSE - for short positions or avoiding longs
                params: {min_value: 70}
                """
                min_value = params.get("min_value", 70)
                is_overbought = trend.rsi > min_value
                is_bullish = not is_overbought  # Bullish = NOT overbought
                msg = f"RSI overbought check: {'✓' if is_bullish else '✗'} (RSI {trend.rsi:.1f})"
                values["rsi"] = trend.rsi

            elif indicator_type == "price_below_vwap":
                """
                Bullish when price is BELOW VWAP (oversold)
                params: {
                    min_gap_pct: -1.0,      # Require at least 1% below VWAP
                    max_gap_pct: -5.0       # But not more than 5% (too extended)
                }
                """
                min_gap_pct = params.get("min_gap_pct", -1.0)  # e.g., -1.0 = 1% below
                max_gap_pct = params.get("max_gap_pct", -10.0)  # e.g., -10.0 = max 10% below

                gap_pct = ((current_price - trend.vwap) / trend.vwap) * 100
                values["price"] = current_price
                values["vwap"] = trend.vwap
                values["gap_pct"] = gap_pct

                # Want price below VWAP but not TOO far below
                is_bullish = max_gap_pct <= gap_pct <= min_gap_pct
                
                msg = (
                    f"Price below VWAP: {'✓' if is_bullish else '✗'} "
                    f"({gap_pct:+.2f}% - need between {max_gap_pct:.1f}% and {min_gap_pct:.1f}%)"
                )

            elif indicator_type == "price_extended_below_ema":
                """
                Bullish when price is stretched below EMA (rubber band effect)
                params: {
                    ema: 20,                # Which EMA to check
                    min_gap_pct: -2.0,      # Must be at least 2% below
                    max_gap_pct: -8.0       # But not more than 8% (too risky)
                }
                """
                ema_type = params.get("ema", 20)
                min_gap_pct = params.get("min_gap_pct", -2.0)
                max_gap_pct = params.get("max_gap_pct", -10.0)
                
                ema_value = trend.ema20 if ema_type == 20 else trend.ema50
                gap_pct = ((current_price - ema_value) / ema_value) * 100
                values["price"] = current_price
                values["ema"] = ema_value
                values["gap_pct"] = gap_pct

                # Want price below EMA (negative gap) but not too far
                is_bullish = max_gap_pct <= gap_pct <= min_gap_pct
                
                msg = (
                    f"Price below EMA{ema_type}: {'✓' if is_bullish else '✗'} "
                    f"({gap_pct:+.2f}% - need between {max_gap_pct:.1f}% and {min_gap_pct:.1f}%)"
                )

            elif indicator_type == "bollinger_bands":
                """
                Check price position relative to Bollinger Bands.

                Modes:
                  "touch"   — price is within tolerance_pct of a band edge
                  "breach"  — price has crossed outside a band
                  "pct_b"   — price position within the band as 0.0–1.0
                              0.0 = at lower band, 1.0 = at upper band
                              Best mode for range trading entry timing

                params: {
                    band:          "lower" | "upper"   default "lower"
                    mode:          "touch" | "breach" | "pct_b"   default "touch"
                    tolerance_pct: 0.5     # for "touch" mode: within 0.5% of band
                    max_pct_b:     0.25    # for "pct_b" mode: price in lower 25% of band
                    min_pct_b:     0.75    # for "pct_b" mode (upper band): price in upper 25%
                }
                """
                band          = params.get("band", "lower")
                mode          = params.get("mode", "touch")
                tolerance_pct = params.get("tolerance_pct", 0.5)
                max_pct_b     = params.get("max_pct_b", 0.25)   # for pct_b lower mode
                min_pct_b     = params.get("min_pct_b", 0.75)   # for pct_b upper mode

                bb_lower = trend.bb.bb_lower
                bb_upper = trend.bb.bb_upper
                bb_basis = trend.bb.bb_basis

                values["bb_lower"] = bb_lower
                values["bb_upper"] = bb_upper
                values["bb_basis"] = bb_basis
                values["price"]    = current_price

                if bb_lower is None or bb_upper is None:
                    is_bullish = False
                    msg = "Bollinger Bands: ✗ (no BB data — check Pine script is sending bb fields)"
                else:
                    band_width = bb_upper - bb_lower
                    pct_b = (current_price - bb_lower) / band_width if band_width > 0 else None
                    bb_width_norm = (band_width / bb_basis) if bb_basis and bb_basis > 0 else None

                    values["pct_b"]    = round(pct_b, 4) if pct_b is not None else None
                    values["bb_width"] = round(bb_width_norm, 5) if bb_width_norm is not None else None

                    if mode == "pct_b":
                        # Most useful for range trading — where in the band is price?
                        if pct_b is None:
                            is_bullish = False
                            msg = "BB %B: ✗ (band width is zero)"
                        elif band == "lower":
                            # Bullish = price in lower portion of band (near lower band)
                            is_bullish = pct_b <= max_pct_b
                            msg = (
                                f"BB %B lower: {'✓' if is_bullish else '✗'} "
                                f"(%B={pct_b:.2f} - need <={max_pct_b:.2f})"
                            )
                        else:  # upper — avoid entries near top of band
                            is_bullish = pct_b < min_pct_b
                            msg = (
                                f"BB %B upper check: {'✓' if is_bullish else '✗'} "
                                f"(%B={pct_b:.2f} - need <{min_pct_b:.2f})"
                            )

                    elif mode == "touch":
                        target_band = bb_lower if band == "lower" else bb_upper
                        distance_pct = abs((current_price - target_band) / target_band) * 100
                        values["distance_pct"] = round(distance_pct, 4)
                        is_bullish = distance_pct <= tolerance_pct
                        msg = (
                            f"BB {band} touch: {'✓' if is_bullish else '✗'} "
                            f"(price {distance_pct:.2f}% from {band} band, "
                            f"need <={tolerance_pct:.2f}%)"
                        )

                    else:  # "breach"
                        if band == "lower":
                            is_bullish = current_price <= bb_lower
                            gap_pct = ((current_price - bb_lower) / bb_lower) * 100
                            values["gap_pct"] = round(gap_pct, 4)
                            msg = (
                                f"BB lower breach: {'✓' if is_bullish else '✗'} "
                                f"(price {gap_pct:+.2f}% vs lower band)"
                            )
                        else:  # upper
                            is_bullish = current_price < bb_upper
                            gap_pct = ((current_price - bb_upper) / bb_upper) * 100
                            values["gap_pct"] = round(gap_pct, 4)
                            msg = (
                                f"BB upper breach check: {'✓' if is_bullish else '✗'} "
                                f"(price {gap_pct:+.2f}% vs upper band)"
                            )
                
            elif indicator_type == "volume_spike":
                """
                Bullish when volume spikes (selling climax/capitulation)
                params: {
                    min_ratio: 1.5,         # Volume must be 1.5x average
                    max_ratio: 5.0          # But not insane (flash crash)
                }
                """
                min_ratio = params.get("min_ratio", 1.5)
                max_ratio = params.get("max_ratio", 10.0)
                
                if trend.volume_ratio is None:
                    values["volume_ratio"] = None
                    is_bullish = False
                    msg = "Volume spike: ✗ (no volume data)"
                else:
                    values["volume_ratio"] = trend.volume_ratio
                    is_bullish = min_ratio <= trend.volume_ratio <= max_ratio
                    msg = (
                        f"Volume spike: {'✓' if is_bullish else '✗'} "
                        f"({trend.volume_ratio:.2f}x - need {min_ratio:.1f}x-{max_ratio:.1f}x)"
                    )
                
            elif indicator_type == "reversal_candle":
                """
                Check for bullish reversal candle patterns using the previous
                closed candle's OHLC data (prev_open/high/low/close from Pine).

                Patterns:
                  "hammer"     — small body at top, long lower wick (>=2x body),
                                 tiny upper wick (<=0.3x body). Bullish reversal.
                  "engulfing"  — current candle's body fully engulfs previous
                                 candle's body AND current is bullish (close > open).
                                 Requires 2 candles worth of data — uses prev_close
                                 as current close and current_price as live price.
                  "doji"       — open ≈ close (body < min_body_pct of total range).
                                 Signals indecision / potential reversal.

                params: {
                    pattern:       "hammer"   # "hammer" | "engulfing" | "doji"
                    min_body_pct:  0.1        # Min body as % of candle range (hammer/engulfing)
                    max_body_pct:  0.3        # Max body as % of range for doji
                }
                """
                pattern      = params.get("pattern", "hammer")
                min_body_pct = params.get("min_body_pct", 0.1)
                max_body_pct = params.get("max_body_pct", 0.3)

                # ── Correctly read prev_candle fields ────────────────────────
                # Pine sends the previous CLOSED candle's OHLC as:
                #   prev_open, prev_high, prev_low, prev_close
                # trend.price is the LIVE price — not the closed candle close.
                candle_open  = trend.prev_candle.prev_open
                candle_high  = trend.prev_candle.prev_high
                candle_low   = trend.prev_candle.prev_low
                candle_close = trend.prev_candle.prev_close   # ← was incorrectly trend.price

                values["candle_open"]  = candle_open
                values["candle_high"]  = candle_high
                values["candle_low"]   = candle_low
                values["candle_close"] = candle_close
                values["pattern"]      = pattern

                if candle_open is None or candle_high is None or candle_low is None or candle_close is None:
                    is_bullish = False
                    msg = (
                        f"Reversal candle ({pattern}): ✗ "
                        f"(no prev_candle OHLC data — check Pine script is sending prev_candle fields)"
                    )
                else:
                    total_range  = candle_high - candle_low
                    body_size    = abs(candle_close - candle_open)
                    lower_wick   = min(candle_open, candle_close) - candle_low
                    upper_wick   = candle_high - max(candle_open, candle_close)
                    is_bull_candle = candle_close > candle_open

                    values["total_range"]    = round(total_range, 6)
                    values["body_size"]      = round(body_size, 6)
                    values["lower_wick"]     = round(lower_wick, 6)
                    values["upper_wick"]     = round(upper_wick, 6)
                    values["is_bull_candle"] = is_bull_candle

                    if total_range == 0:
                        is_bullish = False
                        msg = f"Reversal candle ({pattern}): ✗ (zero range candle — doji)"
                    
                    elif pattern == "hammer":
                        # Hammer criteria:
                        #   1. Long lower wick (>= 2x body size)
                        #   2. Small upper wick (<= 0.3x body size)
                        #   3. Body is at least min_body_pct of total range
                        #      (avoids gravestone doji being called a hammer)
                        body_pct = body_size / total_range
                        lower_wick_ratio = lower_wick / body_size if body_size > 0 else 0
                        upper_wick_ratio = upper_wick / body_size if body_size > 0 else 999

                        values["body_pct"]          = round(body_pct, 4)
                        values["lower_wick_ratio"]  = round(lower_wick_ratio, 4)
                        values["upper_wick_ratio"]  = round(upper_wick_ratio, 4)

                        is_bullish = (
                            lower_wick_ratio >= 2.0 and    # long lower wick
                            upper_wick_ratio <= 0.3 and    # small upper wick
                            body_pct >= min_body_pct       # has a real body
                        )
                        msg = (
                            f"Hammer: {'✓' if is_bullish else '✗'} "
                            f"(lower_wick={lower_wick_ratio:.1f}x body, "
                            f"upper_wick={upper_wick_ratio:.1f}x body, "
                            f"body={body_pct:.1%} of range)"
                        )

                    elif pattern == "engulfing":
                        # Bullish engulfing criteria:
                        #   1. Current candle is bullish (close > open)
                        #   2. Current body fully contains previous candle's body
                        #   3. Previous candle was bearish (open > close)
                        # We use prev_candle as the "previous" candle and
                        # current_price + prev_close as the "current" candle.
                        # Since we only have one candle of history from Pine,
                        # we approximate: prev candle = prev_open/close,
                        # current candle = prev_close (open) → current_price (close)
                        curr_open  = candle_close   # current candle opened at prev close
                        curr_close = current_price  # current candle's live close
                        prev_open  = candle_open
                        prev_close = candle_close

                        curr_bull = curr_close > curr_open
                        prev_bear = prev_close < prev_open
                        curr_body_low  = min(curr_open, curr_close)
                        curr_body_high = max(curr_open, curr_close)
                        prev_body_low  = min(prev_open, prev_close)
                        prev_body_high = max(prev_open, prev_close)

                        engulfs = curr_body_low <= prev_body_low and curr_body_high >= prev_body_high

                        values["curr_bull"]   = curr_bull
                        values["prev_bear"]   = prev_bear
                        values["engulfs"]     = engulfs

                        is_bullish = curr_bull and prev_bear and engulfs
                        msg = (
                            f"Bullish engulfing: {'✓' if is_bullish else '✗'} "
                            f"(curr_bull={curr_bull}, prev_bear={prev_bear}, engulfs={engulfs})"
                        )

                    elif pattern == "doji":
                        # Doji criteria: body is very small relative to total range
                        # Signals indecision — potential reversal when at range extremes
                        body_pct = body_size / total_range
                        values["body_pct"] = round(body_pct, 4)

                        is_bullish = body_pct <= max_body_pct
                        msg = (
                            f"Doji: {'✓' if is_bullish else '✗'} "
                            f"(body={body_pct:.1%} of range, max={max_body_pct:.1%})"
                        )

                    else:
                        is_bullish = False
                        msg = f"Reversal candle: ✗ (unknown pattern '{pattern}' — use hammer/engulfing/doji)"


            elif indicator_type == "rsi_reversal_momentum":
                # Parameters
                lookback_candles = params.get("lookback_candles", 5)  # Check last 5 candles
                oversold_threshold = params.get("oversold_threshold", 30)  # Must have been <30
                current_min = params.get("current_min", 35)  # Current RSI must be >35
                jump_required = params.get("jump_required", True)  #Requires a jump in RSI. Disabled on trend invalidation checks
                min_jump = params.get("min_jump", 5.0)  # Must have jumped >5 points
                require_sustained = params.get("require_sustained", True)  # Rising for multiple candles
                
                # Get RSI history
                key = f"{symbol}_{timeframe}"
                rsi_history = self._rsi_history.get(key, [])
                
                if len(rsi_history) < lookback_candles:
                    is_bullish = False
                    msg = f"RSI Reversal Momentum: ✗ (insufficient history)"
                    values["history_length"] = len(rsi_history)
                else:
                    current_rsi = trend.rsi
                    recent_history = rsi_history[-lookback_candles:]
                    
                    # Check 1: Was RSI deeply oversold in lookback window?
                    rsi_values = [rsi for _, rsi in recent_history]
                    touched_oversold = any(rsi < oversold_threshold for rsi in rsi_values)
                    min_rsi = min(rsi_values) if rsi_values else current_rsi
                    
                    values["touched_oversold"] = touched_oversold
                    values["min_rsi"] = float(min_rsi)
                    
                    # Check 2: Did RSI jump sharply (>5 points) at some point?
                    if jump_required:
                        max_jump = 0.0
                        jump_found = False
                        
                        min_rsi_found = False
                        for i in range(1, len(rsi_values)):
                            #only look at jumps AFTER min_rsi found
                            if not min_rsi_found and rsi_values[i-1] == min_rsi:
                                min_rsi_found = True
                            if min_rsi_found: 
                                jump = rsi_values[i] - rsi_values[i-1]
                                if jump > max_jump:
                                    max_jump = jump
                                if jump >= min_jump:
                                    jump_found = True
                        
                        values["max_jump"] = float(max_jump)
                        values["jump_found"] = jump_found
                    else:
                        jump_found = True
                        max_jump = 0

                    # Check 3: Current RSI above minimum?
                    current_above_min = current_rsi >= current_min
                    values["current_rsi"] = float(current_rsi)
                    
                    #check momentum
                    rsi_momentum, rsi_direction = self._get_rsi_momentum(symbol, timeframe, lookback=2)
                    values["rsi_direction"] = rsi_direction
                    values["rsi_momentum"] = float(rsi_momentum)

                    #current rising is true if momentum above 2 and direction increasing.
                    # Direction increasing only possible if recent candle is positive
                    if jump_required:
                        currently_rising = rsi_momentum > 2 and rsi_direction == "increasing"
                    else:
                        #In trend invalidation check, we set jump_required to false so don't need to check for increase. 
                        currently_rising = True

                    # Check 5 (optional): Sustained rise (rising for 2+ candles)?
                    sustained_rise = True
                    if require_sustained and len(rsi_history) >= 3:
                        # Check last 3 candles show progression
                        last_3 = [rsi for _, rsi in rsi_history[-3:]]
                        sustained_rise = (last_3[1] > last_3[0]) and (last_3[2] > last_3[1])
                        values["sustained_rise"] = sustained_rise
                    
                    # ALL conditions must pass
                    is_bullish = (
                        touched_oversold and 
                        jump_found and 
                        current_above_min and 
                        currently_rising
                    )
                    
                    if require_sustained:
                        is_bullish = is_bullish and sustained_rise
                    
                    # Build message
                    if is_bullish:
                        msg = (
                            f"RSI Reversal Momentum: ✓ "
                            f"(RSI {min_rsi:.0f}→{current_rsi:.0f}, "
                            f"max jump +{max_jump:.1f}, "
                            f"momentum {rsi_momentum:+.1f})"
                        )
                    else:
                        reasons = []
                        if not touched_oversold:
                            reasons.append(f"never <{oversold_threshold}")
                        if not jump_found:
                            reasons.append(f"no +{min_jump} jump")
                        if not current_above_min:
                            reasons.append(f"RSI {current_rsi:.0f}<{current_min}")
                        if not currently_rising:
                            reasons.append("falling")
                        if require_sustained and not sustained_rise:
                            reasons.append("not sustained")
                        
                        msg = f"RSI Reversal Momentum: ✗ ({', '.join(reasons)})"
    
            results.append((is_bullish, msg))
            if hard_stop and not is_bullish:
                values["hard_stop"] = True
                hard_stop_failures.append(msg)

            result = IndicatorResult(
                type=indicator_type,
                is_bullish=is_bullish,
                config=params,
                values=values,
                message=msg
            )
            indicator_results.append(result)
        

        # NEW: Check for hard_stop failures FIRST (before scoring) - Skip if use_hard_stops is false (Mainly for trend invalidation checks)
        if use_hard_stops and hard_stop_failures:
            details = ", ".join(msg for _, msg in results)
            failed_indicators = "; ".join(hard_stop_failures)
            return False, f"🚫 HARD STOP: {failed_indicators} ({details})", indicator_results   
             
        # Count bullish indicators
        bullish_count = sum(1 for r in indicator_results if r.is_bullish)
        total_count = len(indicator_results)
        
        # Build detailed reason
        details = ", ".join(r.message for r in indicator_results)

        if bullish_count >= min_indicators_required:
            summary = f"{bullish_count}/{total_count} bullish ({details})"
            return True, summary, indicator_results
        else:
            summary = f"Only {bullish_count}/{total_count} bullish, need {min_indicators_required} ({details})"
            return False, summary, indicator_results
    
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