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
        
        # BB history for lookback breach checks (updated when indicators change)
        self._bb_history: Dict[str, list] = {}

        # Closed candle OHLC history — populated from prev_candle on every
        # indicator change.  Patterns like higher_low and bull_close need
        # two *confirmed* closed candles, not one closed + one live candle.
        # Stored as dicts: {timestamp, open, high, low, close}
        # Kept to last 6 candles (patterns never need more than 3).
        self._candle_history: Dict[str, list] = {}
        
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
            if len(self._rsi_history[key]) > 15:
                self._rsi_history[key] = self._rsi_history[key][-15:]
            
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
            
            # Update BB history for lookback breach checks
            if trend_data.bb is not None and trend_data.bb.bb_lower is not None:
                if key not in self._bb_history:
                    self._bb_history[key] = []
                
                close_price = trend_data.prev_candle.prev_close if trend_data.prev_candle.prev_close else trend_data.price
                self._bb_history[key].append({
                    'timestamp': trend_data.timestamp,
                    'bb_lower':  trend_data.bb.bb_lower,
                    'bb_upper':  trend_data.bb.bb_upper,
                    'bb_basis':  trend_data.bb.bb_basis,
                    'price':     close_price,   # close price at this candle
                })
                
                # Keep last 15 candles (matches RSI history cap)
                if len(self._bb_history[key]) > 15:
                    self._bb_history[key] = self._bb_history[key][-15:]

            # Update closed candle OHLC history (for multi-candle reversal patterns)
            # prev_candle always holds the most recently *closed* bar from Pine.
            # We deduplicate on timestamp so re-fires of the same candle don't
            # double-append (Pine can send the same prev_candle across several
            # 15m bars before the next one closes).
            if trend_data.prev_candle is not None:
                pc = trend_data.prev_candle
                if (pc.prev_open is not None and pc.prev_high is not None
                        and pc.prev_low is not None and pc.prev_close is not None):
                    if key not in self._candle_history:
                        self._candle_history[key] = []

                    # Deduplicate: only append if close price differs from last entry
                    # (timestamp alone isn't reliable — Pine doesn't always send one)
                    last = self._candle_history[key][-1] if self._candle_history[key] else None
                    is_new_candle = (
                        last is None
                        or abs(last['close'] - pc.prev_close) > 0.0001
                        or abs(last['open']  - pc.prev_open)  > 0.0001
                    )
                    if is_new_candle:
                        self._candle_history[key].append({
                            'timestamp': trend_data.timestamp,
                            'open':  pc.prev_open,
                            'high':  pc.prev_high,
                            'low':   pc.prev_low,
                            'close': pc.prev_close,
                        })
                        # Keep last 6 candles — no pattern needs more than 3
                        if len(self._candle_history[key]) > 6:
                            self._candle_history[key] = self._candle_history[key][-6:]
            
            # Persist to database if enabled
            if persist_to_db:
                self._log_for_analysis(trend_data)

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
    
    def _log_for_analysis(self, trend_data: TrendData):
        """Specialized logging for trade pattern analysis"""
        from db.utils import get_db_session
        from db.crud_trend import log_trend_for_analysis

        with get_db_session() as db:
            try:
                # You can make the 72 hours configurable
                log_trend_for_analysis(db, trend_data, retention_hours=72)
            except Exception as e:
                self.logger.error(f"❌ Analysis Log Failed: {e}")
                    
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
    
    def _get_rsi_min(self, symbol: str, timeframe: str, lookback: int = 8) -> Optional[float]:
        """
        Return the lowest RSI seen in the last N significant candles.
        
        Used by _mean_reversion_confidence_score to reward setups where RSI
        dipped deeply even if it has since recovered (which is required for
        entry indicators to pass).
        
        Args:
            symbol:   Trading symbol
            timeframe: Timeframe key
            lookback: Number of historical entries to scan (default 8 candles)
            
        Returns:
            Minimum RSI value found, or None if insufficient history
        """
        key = f"{symbol}_{timeframe}"
        history = self._rsi_history.get(key, [])
        
        if not history:
            return None
        
        # Scan whichever is smaller: available history or requested lookback
        window = history[-lookback:]
        rsi_values = [rsi for _, rsi in window]
        return min(rsi_values) if rsi_values else None


    def _get_bb_width_trend(
        self, symbol: str, timeframe: str, lookback: int = 4,
        expand_threshold_pct: float = 0.08,   # 8% change per step = expanding
        contract_threshold_pct: float = 0.08, # 8% change per step = contracting
    ) -> Tuple[Optional[float], Optional[str], Optional[float]]:
        """
        Is the Bollinger Band expanding, contracting, or stable?

        Measures normalised band width (upper - lower) / basis across the last
        N history entries and returns the direction of that change.

        Used by bb_width_regime indicator — intended as a 60m HTF regime filter.
        Expanding bands on the HTF mean a breakout or trend is forming, which
        is the opposite of the flat oscillation a range trade needs.

        Returns:
            (avg_change_per_candle, direction, current_width)
            direction: "expanding" | "contracting" | "stable"
            current_width: latest normalised band width (upper - lower) / basis
            Returns (None, None, None) if insufficient history.
        """
        key = f"{symbol}_{timeframe}"
        history = self._bb_history.get(key, [])

        if len(history) < 2:
            return None, None, None

        window = history[-lookback:] if len(history) >= lookback else history

        widths = []
        for entry in window:
            basis = entry.get('bb_basis')
            upper = entry.get('bb_upper')
            lower = entry.get('bb_lower')
            if basis and basis > 0 and upper is not None and lower is not None:
                widths.append((upper - lower) / basis)

        if len(widths) < 2:
            return None, None, None

        # Average per-step change across the window
        avg_change    = (widths[-1] - widths[0]) / (len(widths) - 1)
        avg_width     = sum(widths) / len(widths)
        current_width = widths[-1]

        # Threshold scales with the typical width of this symbol/timeframe
        expand_threshold   =  avg_width * expand_threshold_pct
        contract_threshold = -avg_width * contract_threshold_pct

        if avg_change > expand_threshold:
            direction = "expanding"
        elif avg_change < contract_threshold:
            direction = "contracting"
        else:
            direction = "stable"

        return avg_change, direction, current_width

    def _get_pct_b_trend(
        self, symbol: str, timeframe: str, lookback: int = 4
    ) -> Tuple[Optional[float], Optional[str]]:
        """
        Is %B moving lower (price falling toward lower band) or higher?

        Measures the change in %B across the last N history entries.
        Used by bb_pct_b_momentum indicator on the 15m entry filter.

        For a range-trade long entry we want %B to be falling toward the lower
        band and then flattening/turning — not still in free-fall.

        direction values:
          "falling"  — %B dropping toward lower band  (good: dip forming)
          "rising"   — %B moving toward upper band    (bad: dip has reversed, chasing)
          "flat"     — %B stable                      (neutral)

        Returns:
            (total_change_over_window, direction)
            Returns (None, None) if insufficient history.
        """
        key = f"{symbol}_{timeframe}"
        history = self._bb_history.get(key, [])

        if len(history) < 2:
            return None, None

        window = history[-lookback:] if len(history) >= lookback else history

        pct_b_values = []
        for entry in window:
            upper = entry.get('bb_upper')
            lower = entry.get('bb_lower')
            price = entry.get('price')
            if upper is not None and lower is not None and price is not None:
                band_width = upper - lower
                if band_width > 0:
                    pct_b_values.append((price - lower) / band_width)

        if len(pct_b_values) < 2:
            return None, None

        # Total change from start to end of window
        total_change = pct_b_values[-1] - pct_b_values[0]

        if total_change < -0.08:
            direction = "falling"
        elif total_change > 0.08:
            direction = "rising"
        else:
            direction = "flat"

        return total_change, direction

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
                # params: {ema: 20|50, direction: "rising"|"not_falling", min_slope_pct: 0.01, max_slope_pct: None}
                ema_type = params.get("ema", 20)
                required_direction = params.get("direction", "rising")
                min_slope_pct = params.get("min_slope_pct", 0.01)
                max_slope_pct = params.get("max_slope_pct", None)

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

                    if is_bullish and max_slope_pct is not None and slope_pct > max_slope_pct:
                        is_bullish = False
                        direction = "too steep"

                    max_str = f", max {max_slope_pct:+.3f}%" if max_slope_pct is not None else ""
                    msg = f"EMA{ema_type} slope: {'✓' if is_bullish else '✗'} ({direction} {slope_pct:+.3f}%{max_str})"
                
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
                params: {
                    min_value: 70,              # RSI threshold — fail if above this
                    lookback_candles: null      # Optional: also fail if RSI exceeded
                                                # min_value in the last N candles of
                                                # history (catches post-peak cooling).
                                                # When omitted, only checks current RSI.
                }

                Without lookback_candles (original behaviour):
                  Blocks if current RSI > min_value.

                With lookback_candles (new):
                  Blocks if EITHER:
                    - current RSI > min_value, OR
                    - RSI exceeded min_value at any point in the last N significant
                      candles (i.e. the trend recently peaked and is now cooling).

                Use on the 60m trend filter to catch post-peak entries where the
                1h RSI has already spiked and fallen back but the trend is spent:
                  - type: "rsi_overbought"
                    params:
                      min_value: 68
                      lookback_candles: 6   # Block if 60m RSI was >68 in last 6 candles
                      hard_stop: true
                """
                min_value = params.get("min_value", 70)
                lookback_candles = params.get("lookback_candles", None)

                current_rsi = float(trend.rsi)
                values["rsi"] = current_rsi
                values["threshold"] = min_value

                # --- current candle check (always performed) ---
                is_overbought = current_rsi > min_value

                # --- optional historical lookback ---
                peak_in_lookback = False
                if lookback_candles is not None:
                    key = f"{symbol}_{timeframe}"
                    rsi_history = self._rsi_history.get(key, [])
                    if len(rsi_history) >= lookback_candles:
                        recent_rsi_values = [rsi for _, rsi in rsi_history[-lookback_candles:]]
                        peak_rsi = max(recent_rsi_values)
                        peak_in_lookback = peak_rsi > min_value
                        values["lookback_candles"] = lookback_candles
                        values["peak_rsi_in_lookback"] = round(peak_rsi, 2)
                    else:
                        # Insufficient history — fail safe: don't block on missing data
                        values["lookback_candles"] = lookback_candles
                        values["lookback_history_len"] = len(rsi_history)

                is_bullish = not is_overbought and not peak_in_lookback

                # Build descriptive message
                if is_overbought:
                    msg = (
                        f"RSI overbought check: ✗ "
                        f"(RSI {current_rsi:.1f} > {min_value})"
                    )
                elif peak_in_lookback:
                    msg = (
                        f"RSI overbought check: ✗ "
                        f"(RSI {current_rsi:.1f} ok now, but peaked at "
                        f"{values['peak_rsi_in_lookback']:.1f} > {min_value} "
                        f"in last {lookback_candles} candles)"
                    )
                else:
                    lookback_note = (
                        f", peak {values.get('peak_rsi_in_lookback', 'N/A'):.1f} "
                        f"in last {lookback_candles} ok"
                        if lookback_candles is not None and "peak_rsi_in_lookback" in values
                        else ""
                    )
                    msg = (
                        f"RSI overbought check: ✓ "
                        f"(RSI {current_rsi:.1f}{lookback_note})"
                    )

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
                    f"({gap_pct:+.2f}% - need between {max_gap_pct:.2f}% and {min_gap_pct:.2f}%)"
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

            elif indicator_type == "price_above_vwap":
                """
                Bearish when price is ABOVE VWAP (overbought).
                params: {
                    min_gap_pct: 1.0,       # Require at least 1% above VWAP
                    max_gap_pct: 10.0       # But not more than 10% (too extended)
                }
                """
                min_gap_pct = params.get("min_gap_pct", 1.0)
                max_gap_pct = params.get("max_gap_pct", 10.0)

                gap_pct = ((current_price - trend.vwap) / trend.vwap) * 100
                values["price"] = current_price
                values["vwap"] = trend.vwap
                values["gap_pct"] = gap_pct

                # Want price above VWAP but not TOO far above
                is_bullish = min_gap_pct <= gap_pct <= max_gap_pct

                msg = (
                    f"Price above VWAP: {'✓' if is_bullish else '✗'} "
                    f"({gap_pct:+.2f}% - need between {min_gap_pct:.2f}% and {max_gap_pct:.2f}%)"
                )

            elif indicator_type == "price_extended_above_ema":
                """
                Bearish when price is stretched above EMA (rubber band effect).
                params: {
                    ema: 20,                # Which EMA to check
                    min_gap_pct: 2.0,       # Must be at least 2% above
                    max_gap_pct: 10.0       # But not more than 10% (too risky)
                }
                """
                ema_type = params.get("ema", 20)
                min_gap_pct = params.get("min_gap_pct", 2.0)
                max_gap_pct = params.get("max_gap_pct", 10.0)

                ema_value = trend.ema20 if ema_type == 20 else trend.ema50
                gap_pct = ((current_price - ema_value) / ema_value) * 100
                values["price"] = current_price
                values["ema"] = ema_value
                values["gap_pct"] = gap_pct

                # Want price above EMA (positive gap) but not too far
                is_bullish = min_gap_pct <= gap_pct <= max_gap_pct

                msg = (
                    f"Price above EMA{ema_type}: {'✓' if is_bullish else '✗'} "
                    f"({gap_pct:+.2f}% - need between {min_gap_pct:.1f}% and {max_gap_pct:.1f}%)"
                )

            elif indicator_type == "bollinger_bands":
                """
                Check price position relative to Bollinger Bands.

                Modes:
                  "touch" — price is within tolerance_pct of a band edge
                  "breach" — price has crossed outside a band
                  "pct_b" — price position within the band as 0.0–1.0
                              0.0 = at lower band, 1.0 = at upper band
                              Best mode for range trading entry timing

                params: {
                    band: "lower" | "upper" default "lower"
                    mode: "touch" | "breach" | "pct_b" default "touch"
                    tolerance_pct: 0.5 # for "touch" mode: within 0.5% of band
                    # pct_b mode — both params apply to both bands as an inclusive range:
                    # min_pct_b: %B >= this (exclude breaches, e.g. 0.10 blocks price below lower band)
                    # max_pct_b: %B <= this (upper limit, e.g. 0.35 for lower entry, 0.75 for upper avoid)
                    # Omit min_pct_b (or set to null) to allow breached values (<0.0) to also pass.
                    min_pct_b: null # no lower bound by default
                    max_pct_b: 0.25 # %B must be at or below this
                }
                """
                band = params.get("band", "lower")
                mode = params.get("mode", "touch")
                tolerance_pct = params.get("tolerance_pct", 0.5)
                max_pct_b = params.get("max_pct_b", 0.25)
                min_pct_b = params.get("min_pct_b", None) # None = no lower bound
                lookback_candles = params.get("lookback_candles", 0)

                if trend.bb is None:
                    is_bullish = False
                    msg = "Bollinger Bands: ✗ (no BB data — check Pine script is sending bb fields)"
                else: 
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
                            # Range check: is %B within [min_pct_b, max_pct_b]?
                            # Works identically for band="lower" and band="upper" —
                            # the YAML params define the window, not the band direction.
                            # min_pct_b: optional lower bound (exclude breaches below band)
                            # max_pct_b: upper bound (%B must not exceed this)
                            if pct_b is None:
                                is_bullish = False
                                msg = "BB %B: ✗ (band width is zero)"
                            else:
                                below_max = pct_b <= max_pct_b
                                above_min = (min_pct_b is None) or (pct_b >= min_pct_b)
                                is_bullish = below_max and above_min

                                # Build readable range string for the log message
                                if min_pct_b is not None:
                                    range_str = f"need {min_pct_b:.2f}–{max_pct_b:.2f}"
                                else:
                                    range_str = f"need <={max_pct_b:.2f}"

                                msg = (
                                    f"BB %B ({band}): {'✓' if is_bullish else '✗'} "
                                    f"(%B={pct_b:.2f} - {range_str})"
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
                            
                            if lookback_candles > 0:
                                # Lookback mode: did price breach the band in the last N candles?
                                bb_key = f"{symbol}_{timeframe}"
                                bb_hist = self._bb_history.get(bb_key, [])
                                window = bb_hist[-lookback_candles:] if bb_hist else []
                                
                                values["lookback_candles"] = lookback_candles
                                values["history_candles"] = len(window)
                                
                                if not window:
                                    is_bullish = False
                                    msg = (
                                        f"BB {band} breach (lookback {lookback_candles}): ✗ "
                                        f"(no BB history yet)"
                                    )
                                elif band == "lower":
                                    breached = any(entry['price'] <= entry['bb_lower'] for entry in window)
                                    is_bullish = breached
                                    msg = (
                                        f"BB lower breach (lookback {lookback_candles}): "
                                        f"{'✓' if is_bullish else '✗'} "
                                        f"({'breach found' if breached else 'no breach'} "
                                        f"in last {len(window)} candles)"
                                    )
                                else:  # upper
                                    breached = any(entry['price'] >= entry['bb_upper'] for entry in window)
                                    is_bullish = breached
                                    msg = (
                                        f"BB upper breach (lookback {lookback_candles}): "
                                        f"{'✓' if is_bullish else '✗'} "
                                        f"({'breach found' if breached else 'no breach'} "
                                        f"in last {len(window)} candles)"
                                    )
                            elif band == "lower":
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
                Check for bullish reversal candle patterns.

                Patterns that use only the single most-recent closed candle
                (sourced from trend.prev_candle — Pine's previous closed bar):
                  "hammer"    — long lower wick, small upper wick, real body.
                  "doji"      — body tiny relative to total range (indecision).
                  "bull_close"— candle closed in its upper half despite being
                                red or small; sellers tried, buyers held.

                Patterns that use _candle_history (two confirmed closed candles):
                  "higher_low"  — candle[-1].low > candle[-2].low.
                                  Selling exhaustion: each swing-low is shallower.
                                  Works even when both candles are red.
                  "engulfing"   — candle[-1] is bullish AND its body fully
                                  contains candle[-2]'s body, AND candle[-2]
                                  was bearish.  Uses two closed candles so the
                                  pattern is confirmed, not approximated against
                                  a live price.

                Common params:
                    pattern:       "doji"    # see list above
                    min_body_pct:  0.1       # hammer/bull_close: min body as % of range
                    max_body_pct:  0.35      # doji: max body as % of range
                    min_close_pct: 0.6       # bull_close: close must be in top X% of range

                History-based patterns fall back gracefully to the single
                prev_candle when _candle_history has fewer than 2 entries.
                """
                pattern        = params.get("pattern", "doji")
                min_body_pct   = params.get("min_body_pct", 0.1)
                max_body_pct   = params.get("max_body_pct", 0.35)
                min_close_pct  = params.get("min_close_pct", 0.6)   # for bull_close

                values["pattern"] = pattern

                # ── Helper: derive candle metrics from an OHLC dict ──────────
                def _candle_metrics(o, h, l, c):
                    total  = h - l
                    body   = abs(c - o)
                    l_wick = min(o, c) - l
                    u_wick = h - max(o, c)
                    return total, body, l_wick, u_wick, c > o   # (range, body, lw, uw, is_bull)

                # ── Resolve which candles to use ─────────────────────────────
                # For history-based patterns we prefer _candle_history so both
                # candles are confirmed closed bars.  Single-candle patterns
                # always use trend.prev_candle (most up-to-date closed bar).

                ch_key   = f"{symbol}_{timeframe}"
                ch       = self._candle_history.get(ch_key, [])
                have_history = len(ch) >= 2

                # Most-recent closed candle (used by all single-candle patterns
                # and as the fallback for history-based ones)
                if trend.prev_candle is not None:
                    pc_o = trend.prev_candle.prev_open
                    pc_h = trend.prev_candle.prev_high
                    pc_l = trend.prev_candle.prev_low
                    pc_c = trend.prev_candle.prev_close
                else:
                    pc_o = pc_h = pc_l = pc_c = None

                # ── Single-candle patterns ────────────────────────────────────
                if pattern in ("hammer", "doji", "bull_close", "shooting_star", "bear_close"):
                    if pc_o is None:
                        is_bullish = False
                        msg = (
                            f"Reversal candle ({pattern}): ✗ "
                            f"(no prev_candle OHLC — check Pine script)"
                        )
                    else:
                        total, body, l_wick, u_wick, is_bull = _candle_metrics(pc_o, pc_h, pc_l, pc_c)
                        values.update({
                            "candle_open":  pc_o, "candle_high": pc_h,
                            "candle_low":   pc_l, "candle_close": pc_c,
                            "total_range":  round(total, 6),
                            "body_size":    round(body, 6),
                            "lower_wick":   round(l_wick, 6),
                            "upper_wick":   round(u_wick, 6),
                            "is_bull_candle": is_bull,
                        })

                        if total == 0:
                            is_bullish = False
                            msg = f"Reversal candle ({pattern}): ✗ (zero-range candle)"

                        elif pattern == "hammer":
                            # Long lower wick (>=2x body), small upper wick (<=0.3x body),
                            # body at least min_body_pct of total range.
                            body_pct       = body / total
                            lw_ratio       = l_wick / body if body > 0 else 0
                            uw_ratio       = u_wick / body if body > 0 else 999
                            values["body_pct"]         = round(body_pct, 4)
                            values["lower_wick_ratio"] = round(lw_ratio, 4)
                            values["upper_wick_ratio"] = round(uw_ratio, 4)
                            is_bullish = (lw_ratio >= 2.0 and uw_ratio <= 0.3
                                          and body_pct >= min_body_pct)
                            msg = (
                                f"Hammer: {'✓' if is_bullish else '✗'} "
                                f"(lower_wick={lw_ratio:.1f}x body, "
                                f"upper_wick={uw_ratio:.1f}x body, "
                                f"body={body_pct:.1%} of range)"
                            )

                        elif pattern == "doji":
                            body_pct = body / total
                            values["body_pct"] = round(body_pct, 4)
                            is_bullish = body_pct <= max_body_pct
                            msg = (
                                f"Doji: {'✓' if is_bullish else '✗'} "
                                f"(body={body_pct:.1%} of range, max={max_body_pct:.1%})"
                            )

                        elif pattern == "bull_close":
                            # Candle closed in the upper portion of its range regardless
                            # of whether it was a red or green candle.
                            # close_position: 0.0 = closed at the low, 1.0 = at the high.
                            # Use case: in a range, small red candles that hold their
                            # upper half show buyers absorbing the sell pressure.
                            close_pos = (pc_c - pc_l) / total if total > 0 else 0
                            values["close_position"] = round(close_pos, 4)
                            values["min_close_pct"]  = min_close_pct
                            is_bullish = close_pos >= min_close_pct
                            msg = (
                                f"Bull close: {'✓' if is_bullish else '✗'} "
                                f"(closed at {close_pos:.1%} of range, "
                                f"need >={min_close_pct:.1%})"
                            )

                        elif pattern == "shooting_star":
                            # Long upper wick (>=2x body), small lower wick (<=0.3x body).
                            # Mirror of hammer: rejection at highs, bearish reversal signal.
                            body_pct       = body / total
                            uw_ratio       = u_wick / body if body > 0 else 0
                            lw_ratio       = l_wick / body if body > 0 else 999
                            values["body_pct"]         = round(body_pct, 4)
                            values["upper_wick_ratio"] = round(uw_ratio, 4)
                            values["lower_wick_ratio"] = round(lw_ratio, 4)
                            is_bullish = (uw_ratio >= 2.0 and lw_ratio <= 0.3
                                          and body_pct >= min_body_pct)
                            msg = (
                                f"Shooting star: {'✓' if is_bullish else '✗'} "
                                f"(upper_wick={uw_ratio:.1f}x body, "
                                f"lower_wick={lw_ratio:.1f}x body, "
                                f"body={body_pct:.1%} of range)"
                            )

                        elif pattern == "bear_close":
                            # Candle closed in the lower portion of its range.
                            # Mirror of bull_close: sellers dominated into the close.
                            max_close_pct = params.get("max_close_pct", 0.4)
                            close_pos = (pc_c - pc_l) / total if total > 0 else 0
                            values["close_position"] = round(close_pos, 4)
                            values["max_close_pct"]  = max_close_pct
                            is_bullish = close_pos <= max_close_pct
                            msg = (
                                f"Bear close: {'✓' if is_bullish else '✗'} "
                                f"(closed at {close_pos:.1%} of range, "
                                f"need <={max_close_pct:.1%})"
                            )

                # ── Two-closed-candle patterns ────────────────────────────────
                elif pattern in ("higher_low", "engulfing", "lower_high", "bear_engulfing"):

                    # Resolve the two closed candles.
                    # Prefer history (both confirmed), fall back to history[-1] +
                    # prev_candle if history only has one entry, and finally fall
                    # back to prev_candle + current_price (old behaviour for
                    # engulfing) so we degrade gracefully on first start.
                    if have_history:
                        c1 = ch[-2]   # older closed candle
                        c2 = ch[-1]   # most-recent closed candle
                        data_source = "history"
                    elif len(ch) == 1 and pc_o is not None:
                        # history has one entry; use prev_candle as c2
                        c1 = ch[-1]
                        c2 = {"open": pc_o, "high": pc_h, "low": pc_l, "close": pc_c}
                        data_source = "partial_history"
                    elif pc_o is not None:
                        # No history yet — fall back to prev_candle vs live price
                        # (only usable for engulfing; higher_low skips)
                        c1 = {"open": pc_o,    "high": pc_h,          "low": pc_l,
                              "close": pc_c}
                        c2 = {"open": pc_c,    "high": current_price,  "low": current_price,
                              "close": current_price}
                        data_source = "live_fallback"
                    else:
                        c1 = c2 = None
                        data_source = "no_data"

                    values["data_source"] = data_source

                    if c1 is None or c2 is None:
                        is_bullish = False
                        msg = (
                            f"Reversal candle ({pattern}): ✗ "
                            f"(no candle data — check Pine script and allow cache to warm up)"
                        )

                    elif pattern == "higher_low":
                        # c2 (recent) low must be strictly above c1 (older) low.
                        # Both can be red — the signal is that the sell pressure is
                        # waning: each dip finds support at a higher level.
                        # Optional: require c2 to also be a bull candle for a
                        # stricter version (set require_bull: true in params).
                        require_bull = params.get("require_bull", False)

                        hl_ok   = c2["low"] > c1["low"]
                        bull_ok = (not require_bull) or (c2["close"] > c2["open"])

                        values["c1_low"]       = c1["low"]
                        values["c2_low"]       = c2["low"]
                        values["higher_low"]   = hl_ok
                        values["require_bull"] = require_bull
                        values["c2_is_bull"]   = c2["close"] > c2["open"]

                        is_bullish = hl_ok and bull_ok
                        msg = (
                            f"Higher low: {'✓' if is_bullish else '✗'} "
                            f"(c2_low={c2['low']:.4f} vs c1_low={c1['low']:.4f}"
                            + (f", bull={bull_ok}" if require_bull else "")
                            + f") [{data_source}]"
                        )

                    elif pattern == "engulfing":
                        # Bullish engulfing (two confirmed closed candles):
                        #   c1 (older) was bearish, c2 (recent) is bullish and
                        #   its body fully contains c1's body.
                        # Skip live_fallback for this pattern — an unfinished
                        # candle can't confirm an engulf.
                        if data_source == "live_fallback":
                            is_bullish = False
                            msg = (
                                "Bullish engulfing: ✗ "
                                "(candle history warming up — need 2 closed candles)"
                            )
                        else:
                            c2_total, c2_body, _, _, c2_bull = _candle_metrics(
                                c2["open"], c2["high"], c2["low"], c2["close"])
                            _, c1_body, _, _, c1_bull = _candle_metrics(
                                c1["open"], c1["high"], c1["low"], c1["close"])

                            c1_bear        = not c1_bull
                            c2_body_lo     = min(c2["open"], c2["close"])
                            c2_body_hi     = max(c2["open"], c2["close"])
                            c1_body_lo     = min(c1["open"], c1["close"])
                            c1_body_hi     = max(c1["open"], c1["close"])
                            engulfs        = (c2_body_lo <= c1_body_lo
                                              and c2_body_hi >= c1_body_hi)
                            body_pct       = c2_body / c2_total if c2_total > 0 else 0

                            values.update({
                                "c1_open": c1["open"], "c1_close": c1["close"],
                                "c2_open": c2["open"], "c2_close": c2["close"],
                                "c1_bear": c1_bear,    "c2_bull":  c2_bull,
                                "engulfs": engulfs,    "body_pct": round(body_pct, 4),
                            })

                            is_bullish = c2_bull and c1_bear and engulfs
                            msg = (
                                f"Bullish engulfing: {'✓' if is_bullish else '✗'} "
                                f"(c2_bull={c2_bull}, c1_bear={c1_bear}, "
                                f"engulfs={engulfs}) [{data_source}]"
                            )

                    elif pattern == "lower_high":
                        # c2 (recent) high must be strictly below c1 (older) high.
                        # Mirror of higher_low: buying exhaustion, each rally
                        # finds resistance at a lower level.
                        require_bear = params.get("require_bear", False)

                        lh_ok   = c2["high"] < c1["high"]
                        bear_ok = (not require_bear) or (c2["close"] < c2["open"])

                        values["c1_high"]      = c1["high"]
                        values["c2_high"]      = c2["high"]
                        values["lower_high"]   = lh_ok
                        values["require_bear"] = require_bear
                        values["c2_is_bear"]   = c2["close"] < c2["open"]

                        is_bullish = lh_ok and bear_ok
                        msg = (
                            f"Lower high: {'✓' if is_bullish else '✗'} "
                            f"(c2_high={c2['high']:.4f} vs c1_high={c1['high']:.4f}"
                            + (f", bear={bear_ok}" if require_bear else "")
                            + f") [{data_source}]"
                        )

                    elif pattern == "bear_engulfing":
                        # Bearish engulfing (two confirmed closed candles):
                        #   c1 (older) was bullish, c2 (recent) is bearish and
                        #   its body fully contains c1's body.
                        if data_source == "live_fallback":
                            is_bullish = False
                            msg = (
                                "Bearish engulfing: ✗ "
                                "(candle history warming up — need 2 closed candles)"
                            )
                        else:
                            c2_total, c2_body, _, _, c2_bull = _candle_metrics(
                                c2["open"], c2["high"], c2["low"], c2["close"])
                            _, c1_body, _, _, c1_bull = _candle_metrics(
                                c1["open"], c1["high"], c1["low"], c1["close"])

                            c2_bear        = not c2_bull
                            c2_body_lo     = min(c2["open"], c2["close"])
                            c2_body_hi     = max(c2["open"], c2["close"])
                            c1_body_lo     = min(c1["open"], c1["close"])
                            c1_body_hi     = max(c1["open"], c1["close"])
                            engulfs        = (c2_body_lo <= c1_body_lo
                                              and c2_body_hi >= c1_body_hi)
                            body_pct       = c2_body / c2_total if c2_total > 0 else 0

                            values.update({
                                "c1_open": c1["open"], "c1_close": c1["close"],
                                "c2_open": c2["open"], "c2_close": c2["close"],
                                "c1_bull": c1_bull,    "c2_bear":  c2_bear,
                                "engulfs": engulfs,    "body_pct": round(body_pct, 4),
                            })

                            is_bullish = c2_bear and c1_bull and engulfs
                            msg = (
                                f"Bearish engulfing: {'✓' if is_bullish else '✗'} "
                                f"(c2_bear={c2_bear}, c1_bull={c1_bull}, "
                                f"engulfs={engulfs}) [{data_source}]"
                            )

                else:
                    is_bullish = False
                    msg = (
                        f"Reversal candle: ✗ (unknown pattern '{pattern}' — "
                        f"use hammer | doji | bull_close | shooting_star | bear_close "
                        f"| higher_low | engulfing | lower_high | bear_engulfing)"
                    )

                # ── Post-pattern guard: price must not have dropped too far
                # from the candle close since the signal fired.
                #
                # Why this matters: a bull_close (or any reversal pattern) is
                # evaluated against the *closed* candle.  If the live price has
                # already fallen X% below that close by the time the entry order
                # runs, the bullish thesis is already breaking down and buying
                # here means chasing the exit of the move, not joining it.
                #
                # Applies to ALL patterns — the candle close is always the
                # reference price the pattern used to signal, so any material
                # drop from that close is a red flag regardless of pattern type.
                #
                # params:
                #   max_drop_from_close_pct: float  (default: None = disabled)
                #       Maximum allowed drop (%) from the candle close to the
                #       current live price.  E.g. 0.5 means "block if price is
                #       already >0.5% below the candle close".
                #       Recommended starting value: 0.4–0.6 for 15m candles.
                #
                # YAML example:
                #   - type: "reversal_candle"
                #     params:
                #       pattern: "bull_close"
                #       min_close_pct: 0.55
                #       max_drop_from_close_pct: 0.5   # block if price drops >0.5% from close
                #
                max_drop_from_close_pct = params.get("max_drop_from_close_pct", None)
                if max_drop_from_close_pct is not None:
                    # Determine the reference candle close (whichever the pattern used)
                    ref_close = None
                    if pattern in ("hammer", "doji", "bull_close") and pc_c is not None:
                        ref_close = pc_c
                    elif pattern in ("higher_low", "engulfing"):
                        # Use c2 close if we resolved it, otherwise fall back to prev_candle
                        try:
                            ref_close = c2["close"] if c2 is not None else pc_c
                        except (NameError, TypeError):
                            ref_close = pc_c

                    if ref_close is not None and ref_close > 0:
                        drop_pct = ((ref_close - current_price) / ref_close) * 100
                        values["candle_close_ref"]      = ref_close
                        values["drop_from_close_pct"]   = round(drop_pct, 4)
                        values["max_drop_from_close_pct"] = max_drop_from_close_pct

                        if drop_pct > max_drop_from_close_pct:
                            # Price has fallen too far below the candle close —
                            # override the pattern result regardless of what it found.
                            prev_result = "✓" if is_bullish else "✗"
                            is_bullish = False
                            msg = (
                                f"Reversal candle ({pattern}): ✗ "
                                f"(pattern {prev_result} but price dropped "
                                f"{drop_pct:.2f}% from candle close "
                                f"${ref_close:.4f} → ${current_price:.4f}, "
                                f"max allowed {max_drop_from_close_pct:.2f}%)"
                            )

                # ── Post-pattern guard for bear patterns: price must not have
                # risen too far from the candle close since the signal fired.
                # Mirror of max_drop_from_close_pct — if price has already
                # rallied X% above the close, the bearish thesis is breaking down.
                #
                # params:
                #   max_rise_from_close_pct: float  (default: None = disabled)
                #       E.g. 0.5 means "block if price is already >0.5% above close".
                max_rise_from_close_pct = params.get("max_rise_from_close_pct", None)
                if max_rise_from_close_pct is not None:
                    ref_close = None
                    if pattern in ("shooting_star", "bear_close") and pc_c is not None:
                        ref_close = pc_c
                    elif pattern in ("lower_high", "bear_engulfing"):
                        try:
                            ref_close = c2["close"] if c2 is not None else pc_c
                        except (NameError, TypeError):
                            ref_close = pc_c

                    if ref_close is not None and ref_close > 0:
                        rise_pct = ((current_price - ref_close) / ref_close) * 100
                        values["candle_close_ref"]        = ref_close
                        values["rise_from_close_pct"]     = round(rise_pct, 4)
                        values["max_rise_from_close_pct"] = max_rise_from_close_pct

                        if rise_pct > max_rise_from_close_pct:
                            prev_result = "✓" if is_bullish else "✗"
                            is_bullish = False
                            msg = (
                                f"Reversal candle ({pattern}): ✗ "
                                f"(pattern {prev_result} but price rose "
                                f"{rise_pct:.2f}% from candle close "
                                f"${ref_close:.4f} → ${current_price:.4f}, "
                                f"max allowed {max_rise_from_close_pct:.2f}%)"
                            )


            elif indicator_type == "rsi_reversal_momentum":
                # Parameters
                lookback_candles = params.get("lookback_candles", 5)  # Check last 5 candles
                oversold_threshold = params.get("oversold_threshold", 30)  # Must have been <30
                current_min = params.get("current_min", 35)  # Current RSI must be >35
                jump_required = params.get("jump_required", True)  #Requires a jump in RSI. Disabled on trend invalidation checks
                min_jump = params.get("min_jump", 5.0)  # Must have jumped >5 points
                require_sustained = params.get("require_sustained", True)  # Rising for multiple candles
                sustained_rise_mode = params.get("sustained_rise_mode", "strict")                

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
                    if require_sustained == True:
                        #If require sustained, look over last 2 candle gaps
                        rsi_momentum, rsi_direction  = self._get_rsi_momentum(symbol, timeframe, lookback=2)
                    else:
                        #else just check previous jump
                        rsi_momentum, rsi_direction  = self._get_rsi_momentum(symbol, timeframe, lookback=1)
                        
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
                        if sustained_rise_mode == "net":
                            # Allow: consecutive up-up OR dip-then-higher-high (last3[2] > last3[0])
                            consecutive    = last_3[1] > last_3[0] and last_3[2] > last_3[1]
                            net_higher     = last_3[2] > last_3[0]
                            sustained_rise = consecutive or net_higher
                        else:
                            # "strict" (default): must be strictly consecutive up-up
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

            elif indicator_type == "rsi_overbought_momentum":
                # Mirror of rsi_reversal_momentum for short entries.
                # Confirms RSI peaked above overbought, then dropped sharply and is falling.
                lookback_candles     = params.get("lookback_candles", 5)
                overbought_threshold = params.get("overbought_threshold", 70)
                current_max          = params.get("current_max", 65)
                drop_required        = params.get("drop_required", True)
                min_drop             = params.get("min_drop", 5.0)
                require_sustained    = params.get("require_sustained", True)
                sustained_fall_mode  = params.get("sustained_fall_mode", "strict")

                key = f"{symbol}_{timeframe}"
                rsi_history = self._rsi_history.get(key, [])

                if len(rsi_history) < lookback_candles:
                    is_bullish = False
                    msg = f"RSI Overbought Momentum: ✗ (insufficient history)"
                    values["history_length"] = len(rsi_history)
                else:
                    current_rsi    = trend.rsi
                    recent_history = rsi_history[-lookback_candles:]

                    # Check 1: Was RSI overbought in the lookback window?
                    rsi_values = [rsi for _, rsi in recent_history]
                    touched_overbought = any(rsi > overbought_threshold for rsi in rsi_values)
                    max_rsi = max(rsi_values) if rsi_values else current_rsi

                    values["touched_overbought"] = touched_overbought
                    values["max_rsi"] = float(max_rsi)

                    # Check 2: Did RSI drop sharply (>= min_drop points) after the peak?
                    if drop_required:
                        max_drop = 0.0
                        drop_found = False

                        max_rsi_found = False
                        for i in range(1, len(rsi_values)):
                            if not max_rsi_found and rsi_values[i-1] == max_rsi:
                                max_rsi_found = True
                            if max_rsi_found:
                                drop = rsi_values[i-1] - rsi_values[i]
                                if drop > max_drop:
                                    max_drop = drop
                                if drop >= min_drop:
                                    drop_found = True

                        values["max_drop"] = float(max_drop)
                        values["drop_found"] = drop_found
                    else:
                        drop_found = True
                        max_drop = 0

                    # Check 3: Current RSI below maximum?
                    current_below_max = current_rsi <= current_max
                    values["current_rsi"] = float(current_rsi)

                    if require_sustained:
                        rsi_momentum, rsi_direction = self._get_rsi_momentum(symbol, timeframe, lookback=2)
                    else:
                        rsi_momentum, rsi_direction = self._get_rsi_momentum(symbol, timeframe, lookback=1)

                    values["rsi_direction"] = rsi_direction
                    values["rsi_momentum"] = float(rsi_momentum) if rsi_momentum is not None else None

                    if drop_required:
                        currently_falling = (rsi_momentum is not None
                                             and rsi_momentum < -2
                                             and rsi_direction == "decreasing")
                    else:
                        currently_falling = True

                    # Check 5 (optional): Sustained fall (falling for 2+ candles)?
                    sustained_fall = True
                    if require_sustained and len(rsi_history) >= 3:
                        last_3 = [rsi for _, rsi in rsi_history[-3:]]
                        if sustained_fall_mode == "net":
                            consecutive    = last_3[1] < last_3[0] and last_3[2] < last_3[1]
                            net_lower      = last_3[2] < last_3[0]
                            sustained_fall = consecutive or net_lower
                        else:
                            sustained_fall = (last_3[1] < last_3[0]) and (last_3[2] < last_3[1])
                            values["sustained_fall"] = sustained_fall

                    is_bullish = (
                        touched_overbought and
                        drop_found and
                        current_below_max and
                        currently_falling
                    )

                    if require_sustained:
                        is_bullish = is_bullish and sustained_fall

                    if is_bullish:
                        msg = (
                            f"RSI Overbought Momentum: ✓ "
                            f"(RSI {max_rsi:.0f}→{current_rsi:.0f}, "
                            f"max drop -{max_drop:.1f}, "
                            f"momentum {rsi_momentum:+.1f})"
                        )
                    else:
                        reasons = []
                        if not touched_overbought:
                            reasons.append(f"never >{overbought_threshold}")
                        if not drop_found:
                            reasons.append(f"no -{min_drop} drop")
                        if not current_below_max:
                            reasons.append(f"RSI {current_rsi:.0f}>{current_max}")
                        if not currently_falling:
                            reasons.append("rising")
                        if require_sustained and not sustained_fall:
                            reasons.append("not sustained")

                        msg = f"RSI Overbought Momentum: ✗ ({', '.join(reasons)})"

            elif indicator_type == "adx_regime":
                """
                ADX-based ranging regime filter.

                ADX measures trend STRENGTH regardless of direction.
                Low ADX = weak trend = ranging conditions = good for range trades.
                High ADX = strong trend = bad for range trades.

                Requires the Pine script to send an "adx" field in the payload.
                Add ta.dmi(14, 14) to get_trend_data() in Pine and include
                "adx" in the JSON — see updated Pine script for implementation.

                Typical use: HTF (60m) trend filter.
                  adx < 20  → strong ranging conditions    ✅
                  adx < 25  → acceptable ranging           ✅
                  adx > 25  → trending — block range trade ❌
                  adx > 30  → strong trend — definitely block

                params: {
                    max_adx: 25,        # Block if ADX is above this (trending)
                    min_adx: 0,         # Optional: block if ADX is too low (dead market)
                    hard_stop: false
                }

                YAML example (60m trend filter):
                  - type: "adx_regime"
                    params:
                      max_adx: 25
                      hard_stop: true
                """
                max_adx   = params.get("max_adx", 25)
                min_adx   = params.get("min_adx", 0)

                adx_value = getattr(trend, 'adx', None)
                values["adx"] = adx_value
                values["max_adx"] = max_adx
                values["min_adx"] = min_adx

                if adx_value is None:
                    # ADX not yet in TrendData — fail gracefully rather than crash.
                    # Add 'adx: float = None' to your TrendData model and update
                    # the Pine webhook to send it.
                    is_bullish = False
                    msg = "ADX regime: ✗ (no ADX data — add adx field to TrendData and Pine script)"
                else:
                    adx_value = float(adx_value)
                    below_max = adx_value <= max_adx
                    above_min = adx_value >= min_adx
                    is_bullish = below_max and above_min

                    if is_bullish:
                        msg = (
                            f"ADX regime: ✓ "
                            f"(ADX={adx_value:.1f} — ranging, need <={max_adx})"
                        )
                    else:
                        reason = f"ADX={adx_value:.1f} > {max_adx} (trending)" if not below_max else f"ADX={adx_value:.1f} < {min_adx} (dead)"
                        msg = f"ADX regime: ✗ ({reason})"

            elif indicator_type == "bb_width_regime":
                """
                Bollinger Band width trend — is the band expanding or contracting?

                Expanding bands = volatility increasing, breakout/trend forming.
                  → BAD for range trades. Block.
                Contracting or stable bands = volatility compressing.
                  → GOOD for range trades. Allow.

                Uses _bb_history to compute the slope of normalised band width
                (upper - lower) / basis across the last N candles.

                Typical use: HTF (60m) trend filter alongside adx_regime.
                Provides a second independent confirmation that the market is
                actually ranging rather than trending — ADX can lag, but band
                width expansion is visible immediately.

                params: {
                    required_direction: "not_expanding",  # "contracting" | "stable" | "not_expanding"
                    lookback: 4,                          # candles of BB history to use
                    min_width: 0.015,                     # optional: minimum normalised band width floor
                    hard_stop: false
                }

                Direction options:
                  "not_expanding"  — pass if stable OR contracting (recommended default)
                  "contracting"    — only pass when bands are actively narrowing (strict)
                  "stable"         — only pass when bands are flat (very strict)

                min_width: blocks entry when bands are too narrow regardless of direction.
                  Normalised width = (upper - lower) / basis. Typical values: 0.01–0.03.
                  ~0.015 is a reasonable floor to avoid entering in dead/squeezed markets.

                YAML example (15m entry filter):
                  - type: "bb_width_regime"
                    params:
                      required_direction: "not_expanding"
                      min_width: 0.015
                      lookback: 4
                      hard_stop: true
                """
                required_direction = params.get("required_direction", "not_expanding")
                lookback           = params.get("lookback", 4)
                expand_threshold_pct   = params.get("expand_threshold_pct", 0.08)
                contract_threshold_pct = params.get("contract_threshold_pct", 0.08)
                min_width          = params.get("min_width", None)

                width_change, width_direction, current_width = self._get_bb_width_trend(
                    symbol, timeframe, lookback,
                    expand_threshold_pct, contract_threshold_pct
                )

                values["width_direction"] = width_direction
                values["width_change"]    = round(width_change, 6) if width_change is not None else None
                values["current_width"]   = round(current_width, 6) if current_width is not None else None
                values["required"]        = required_direction
                values["lookback"]        = lookback

                if width_direction is None:
                    is_bullish = False
                    msg = f"BB width regime: ✗ (insufficient BB history — need {lookback} candles)"
                elif min_width is not None and current_width < min_width:
                    is_bullish = False
                    msg = (
                        f"BB width regime: ✗ "
                        f"(bands too narrow: width={current_width:.4f} < min_width={min_width})"
                    )
                else:
                    if required_direction == "not_expanding":
                        is_bullish = width_direction != "expanding"
                    elif required_direction == "contracting":
                        is_bullish = width_direction == "contracting"
                    elif required_direction == "stable":
                        is_bullish = width_direction == "stable"
                    else:
                        is_bullish = False

                    if is_bullish:
                        msg = (
                            f"BB width regime: ✓ "
                            f"(bands {width_direction}, Δ={width_change:+.4f}/candle, "
                            f"width={current_width:.4f} — need {required_direction})"
                        )
                    else:
                        msg = (
                            f"BB width regime: ✗ "
                            f"(bands {width_direction}, Δ={width_change:+.4f}/candle, "
                            f"width={current_width:.4f} — need {required_direction})"
                        )

            elif indicator_type == "bb_pct_b_momentum":
                """
                Bollinger Band %B momentum — is %B falling, rising, or flat?

                Tracks the direction %B has been moving across the last N candles
                using _bb_history.

                For a range-trade long entry on the 15m:
                  - "falling" means price has been moving toward the lower band
                    → the dip is forming, not already bouncing → good timing
                  - "flat"    means price has stalled near the lower band
                    → potential floor forming → acceptable timing
                  - "rising"  means price is already bouncing away from the floor
                    → entry is late, chasing a move already in progress → block

                Typical use: 15m entry filter.

                params: {
                    required_direction: "not_rising",  # "falling" | "flat" | "not_rising"
                    lookback: 3,                       # candles of BB history to use
                    hard_stop: false
                }

                Direction options:
                  "not_rising"  — pass if falling OR flat (recommended — catches both
                                  active dips and stalled floors without being too strict)
                  "falling"     — only pass when %B is actively falling (strict — good for
                                  catching dips early but may miss slow floor formations)
                  "flat"        — only pass when %B has stabilised (very strict — only
                                  enters after the dip has clearly stopped)

                YAML example (15m entry filter):
                  - type: "bb_pct_b_momentum"
                    params:
                      required_direction: "not_rising"
                      lookback: 3
                """
                required_direction = params.get("required_direction", "not_rising")
                lookback           = params.get("lookback", 3)

                pct_b_change, pct_b_direction = self._get_pct_b_trend(symbol, timeframe, lookback)

                values["pct_b_direction"] = pct_b_direction
                values["pct_b_change"]    = round(pct_b_change, 4) if pct_b_change is not None else None
                values["required"]        = required_direction
                values["lookback"]        = lookback

                if pct_b_direction is None:
                    is_bullish = False
                    msg = f"BB %B momentum: ✗ (insufficient BB history — need {lookback} candles)"
                else:
                    if required_direction == "not_rising":
                        is_bullish = pct_b_direction != "rising"
                    elif required_direction == "falling":
                        is_bullish = pct_b_direction == "falling"
                    elif required_direction == "flat":
                        is_bullish = pct_b_direction == "flat"
                    else:
                        is_bullish = False

                    direction_symbol = "↓" if pct_b_direction == "falling" else ("↑" if pct_b_direction == "rising" else "→")

                    if is_bullish:
                        msg = (
                            f"BB %B momentum: ✓ "
                            f"(%B {direction_symbol} {pct_b_direction}, Δ={pct_b_change:+.3f} "
                            f"over {lookback} candles — need {required_direction})"
                        )
                    else:
                        msg = (
                            f"BB %B momentum: ✗ "
                            f"(%B {direction_symbol} {pct_b_direction}, Δ={pct_b_change:+.3f} "
                            f"over {lookback} candles — need {required_direction})"
                        )
                        
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