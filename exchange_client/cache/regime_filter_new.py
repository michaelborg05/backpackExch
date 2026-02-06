# Enhanced Regime Filter - Multi-Timeframe Decay/Expansion Detection

"""
PHILOSOPHY UPDATE:

The regime filter should answer: "Is NOW a good time to trade this symbol?"

This requires looking at BOTH timeframes:
- Lower TF (15m/1h): Early warning signals - catches decay/expansion FIRST
- Higher TF (60m/4h): Structural confirmation - confirms it's REAL not noise

Key insight: Decay shows in LTF first, but you want HTF confirmation before acting.
Focus areas:
1. CHOP DETECTION - Avoid whipsaw environments
2. VOLUME QUALITY - Ensure conviction behind moves  
3. VOLATILITY SPIKES - Detect when risk has expanded
4. MOMENTUM QUALITY - Catch exhaustion/distribution

DETECTION HIERARCHY:
1. LTF shows decay → "Early warning" (might be temporary)
2. HTF confirms decay → "Structural problem" (avoid trading)
3. LTF shows expansion → "Early opportunity" (wait for HTF)
4. HTF confirms expansion → "Strong setup" (best trades)
"""

from typing import Optional, Tuple, Dict
from enum import Enum
import time
from utils.logging import log_manager
from cache.trend_cache import get_trend_cache
from cache.atr_cache import get_atr_cache
from utils.constants import MarketRegime, TrendState    



class RegimeFilterTesting:
    """
    Risk-based regime filter with multi-timeframe trend state analysis
    
    Analyzes BOTH timeframes:
    - Lower TF: Early detection of changes
    - Higher TF: Structural confirmation
    """
    
    def __init__(self):
        self.logger = log_manager.get_logger("RegimeFilter")
        self.trend_cache = get_trend_cache()
        self.atr_cache = get_atr_cache()
        
        # HIGH RISK thresholds (unchanged)
        self.rsi_panic = 30
        self.rsi_euphoria = 78
        self.atr_spike = 1.8
        
        # CHOP thresholds (unchanged)
        self.chop_ema_range_pct = 0.3
        self.chop_rsi_neutral = (45, 55)
        self.min_volume_ratio = 0.3
        
        # DECAY thresholds (for trend health)
        self.decay_ema_gap_threshold = 0.5      # EMAs converging to <0.5%
        self.decay_volume_threshold = 0.6        # Volume fading to <0.8x
        self.decay_rsi_momentum_threshold = 1.0  # RSI momentum weak
        
        # 3. VOLUME QUALITY
        self.min_volume_ratio = 0.5         # Below 0.5x = dead market
        self.distribution_volume = 1.5      # High volume + down = distribution
        
        # 4. WHIPSAW DETECTION
        self.whipsaw_threshold = 1.0  # Require very strong established UPTREND
        self.reversal_threshold = -0.8  # Strong bearish reversal on LTF

        #5. Expansion detection
        self.expansion_ema_gap_threshold = 1.0   # EMAs diverging to >1.0%
        self.expansion_volume_threshold = 1.5     # Volume surging to >1.5x
        self.expansion_rsi_momentum_threshold = 3.0  # RSI momentum strong

        # Cache results
        self._regime_cache: Dict[str, Tuple[MarketRegime, str, float]] = {}
        self._cache_ttl = 60
        
        self.logger.info("RegimeFilter initialized - MULTI-TIMEFRAME MODE")
    
    def get_regime(
        self, 
        symbol: str,
        primary_timeframe: str = "60",   # HTF (trend authority)
        confirm_timeframe: str = "15"    # LTF (early signals)
    ) -> Tuple[MarketRegime, str]:
        """
        Determine market regime using both timeframes
        
        Flow:
        1. Check HIGH_RISK (absolute blocks - either TF)
        2. Analyze trend health (both TFs)
        3. Detect decay/expansion patterns
        4. Determine regime
        """
        cache_key = f"{symbol}_{primary_timeframe}_{confirm_timeframe}"
        if cache_key in self._regime_cache:
            regime, reason, timestamp = self._regime_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return regime, reason
        
        primary_trend = self.trend_cache.get(symbol, primary_timeframe)
        confirm_trend = self.trend_cache.get(symbol, confirm_timeframe)
        
        if primary_trend is None:
            return MarketRegime.CHOPPY, f"No {primary_timeframe}m data"
        
        # PRIORITY 1: Check for HIGH RISK (either timeframe can block)
        high_risk, risk_reason = self._check_high_risk(
            symbol, primary_trend, confirm_trend, primary_timeframe
        )
        if high_risk:
            regime = MarketRegime.HIGH_RISK
            reason = f"🚫 {risk_reason}"
            self._regime_cache[cache_key] = (regime, reason, time.time())
            self.logger.warning(f"{symbol}: {reason}")
            return regime, reason
        
        # PRIORITY 2: Analyze trend health (both timeframes)
        htf_state = self._get_trend_state(primary_trend, primary_timeframe, symbol)
        ltf_state = self._get_trend_state(confirm_trend, confirm_timeframe, symbol) if confirm_trend else None
        
        # PRIORITY 3: Determine regime based on trend states
        regime, reason = self._classify_regime(
            htf_state, ltf_state, primary_trend, confirm_trend,
            primary_timeframe, confirm_timeframe
        )
        
        self._regime_cache[cache_key] = (regime, reason, time.time())
        
        if regime == MarketRegime.SAFE or regime == MarketRegime.EXPANDING:
            self.logger.info(f"{symbol}: {reason}")
        else:
            self.logger.warning(f"{symbol}: {reason}")
        
        return regime, reason
    
    def _get_trend_state(
        self,
        trend,
        timeframe: str,
        symbol: str
    ) -> TrendState:
        """
        Analyze single timeframe to determine trend health
        
        Enhanced with EMA slope direction (like RSI momentum)
        
        Returns: EXPANDING, HEALTHY, DECAYING, or BROKEN
        """
        if trend is None:
            return TrendState.BROKEN
        
        # Calculate key metrics
        ema_gap_pct = ((trend.ema20 - trend.ema50) / trend.ema50) * 100
        price_vs_ema20_pct = ((trend.price - trend.ema20) / trend.ema20) * 100
        
        # Get slopes (NEW - like RSI momentum)
        ema20_slope, ema20_direction = self.trend_cache._get_ema_slope(
            symbol, timeframe, "ema20"
        )
        ema50_slope, ema50_direction = self.trend_cache._get_ema_slope(
            symbol, timeframe, "ema50"
        )
        
        # Get RSI momentum
        rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
            symbol, timeframe
        )
        
        volume_ratio = trend.volume_ratio if trend.volume_ratio else 1.0
        
        # Score different aspects (0-100 total)
        structure_score = 0  # 0-30 points (gap + slope direction)
        momentum_score = 0   # 0-30 points (RSI)
        volume_score = 0     # 0-20 points
        position_score = 0   # 0-20 points
        
        # ========================================================================
        # 1. STRUCTURE SCORE (Gap + Slope Direction)
        # ========================================================================
        
        # Base points from gap size
        gap_points = 0
        if ema_gap_pct > self.expansion_ema_gap_threshold:  # >1.0%
            gap_points = 15  # Strong gap
        elif ema_gap_pct > 0.5:
            gap_points = 10  # Healthy gap
        elif ema_gap_pct > 0.3:
            gap_points = 5   # Weak gap
        elif ema_gap_pct < 0.3:
            gap_points = -10   # ema20 below ema50 - structural problem
        else:
            gap_points = 0   # Converging
        
        # Additional points from slope direction
        slope_points = 0
        
        if ema20_slope is not None and ema50_slope is not None:
            # IDEAL: Both rising, EMA20 rising faster
            if ema20_slope > 0 and ema50_slope > 0:
                if ema20_slope > ema50_slope:
                    # Perfect expansion: both rising, fast EMA pulling away
                    slope_points = 15
                else:
                    # Good: both rising, but slow EMA catching up (gap shrinking)
                    slope_points = 10
            
            # GOOD: EMA20 rising, EMA50 flat/slightly falling (early trend)
            elif ema20_slope > 0 and ema50_slope >= -0.01:
                slope_points = 12
            
            # WARNING: EMA20 flat, EMA50 rising (losing momentum)
            elif abs(ema20_slope) < 0.01 and ema50_slope > 0:
                slope_points = 5
            
            # BAD: EMA20 falling
            elif ema20_slope < 0:
                if ema50_slope < 0:
                    # Both falling - confirmed decline
                    slope_points = 0
                else:
                    # EMA20 falling but EMA50 rising - conflict/reversal
                    slope_points = 3
            
            # DEFAULT: Both flat
            else:
                slope_points = 5
        
        structure_score = gap_points + slope_points
        
        # ========================================================================
        # 2. MOMENTUM SCORE (RSI)
        # ========================================================================
        
        if rsi_momentum is not None:
            if rsi_momentum > self.expansion_rsi_momentum_threshold:  # >3.0
                momentum_score = 30  # Strong momentum
            elif rsi_momentum > 2.0:
                momentum_score = 20  # Good momentum
            elif rsi_momentum > 1.0:
                momentum_score = 10  # Weak momentum
            elif rsi_momentum < 1.0:
                momentum_score = -10  # negative momentum
            else:
                momentum_score = 0   # Flat
        
        # ========================================================================
        # 3. VOLUME SCORE
        # ========================================================================
        
        if volume_ratio > self.expansion_volume_threshold:  # >1.5x
            volume_score = 20  # Surging
        elif volume_ratio > 1.0:
            volume_score = 15  # Above average
        elif volume_ratio > 0.8:
            volume_score = 10  # Normal
        else:
            volume_score = 0   # Fading
        
        # ========================================================================
        # 4. POSITION SCORE (Price vs EMA20)
        # ========================================================================
        
        if price_vs_ema20_pct > 1.0:
            position_score = 20  # Extended
        elif price_vs_ema20_pct > 0.0:
            position_score = 15  # Above
        elif price_vs_ema20_pct > -0.5:
            position_score = 10  # Near
        else:
            position_score = 0   # Below
        
        # ========================================================================
        # TOTAL SCORE & CLASSIFICATION
        # ========================================================================
        
        total_score = structure_score + momentum_score + volume_score + position_score
        
        # Log detailed breakdown (for debugging)
        self.logger.debug(
            f"{symbol} {timeframe} state: "
            f"Structure={structure_score} (gap={gap_points}, slope={slope_points}), "
            f"Momentum={momentum_score}, Volume={volume_score}, Position={position_score} "
            f"→ Total={total_score}"
        )
        
        # Classify based on total score
        if total_score >= 70:
            return TrendState.EXPANDING  # 70-100: Strong trend
        elif total_score >= 50:
            return TrendState.HEALTHY    # 50-69: Stable trend
        elif total_score >= 30:
            return TrendState.DECAYING   # 30-49: Weakening
        else:
            return TrendState.BROKEN     # 0-29: Failed

    def _classify_regime(
        self,
        htf_state: TrendState,
        ltf_state: Optional[TrendState],
        htf_trend,
        ltf_trend,
        htf_timeframe: str,
        ltf_timeframe: str
    ) -> Tuple[MarketRegime, str]:
        """
        Classify regime based on both timeframe states
        
        Decision matrix:
        
        HTF State    | LTF State    | Regime      | Reason
        -------------|--------------|-------------|---------------------------
        EXPANDING    | EXPANDING    | EXPANDING   | 🚀 Both TFs strong
        EXPANDING    | HEALTHY      | EXPANDING   | 🚀 HTF strong, LTF stable
        EXPANDING    | DECAYING     | SAFE        | ⚠️ HTF strong but LTF weakening
        EXPANDING    | BROKEN       | CHOPPY      | ⚠️ HTF strong but LTF broken
        
        HEALTHY      | EXPANDING    | EXPANDING   | 🚀 HTF stable, LTF accelerating
        HEALTHY      | HEALTHY      | SAFE        | ✅ Both stable
        HEALTHY      | DECAYING     | CHOPPY      | ⚠️ LTF showing early decay
        HEALTHY      | BROKEN       | CHOPPY      | ⚠️ LTF broken
        
        DECAYING     | EXPANDING    | CHOPPY      | ⚠️ Conflicted (wait)
        DECAYING     | HEALTHY      | CHOPPY      | ⚠️ HTF weakening
        DECAYING     | DECAYING     | CHOPPY      | ⚠️ Both weakening
        DECAYING     | BROKEN       | HIGH_RISK   | 🚫 Both failing
        
        BROKEN       | *            | HIGH_RISK   | 🚫 HTF broken
        """
        
        if ltf_state is None:
            # Single timeframe mode (fallback)
            if htf_state == TrendState.EXPANDING:
                return MarketRegime.EXPANDING, f"🚀 {htf_timeframe}m trend expanding"
            elif htf_state == TrendState.HEALTHY:
                return MarketRegime.SAFE, f"✅ {htf_timeframe}m trend healthy"
            elif htf_state == TrendState.DECAYING:
                return MarketRegime.CHOPPY, f"⚠️ {htf_timeframe}m trend decaying"
            else:
                return MarketRegime.HIGH_RISK, f"🚫 {htf_timeframe}m trend broken"
        
        # Multi-timeframe logic
        
        # HTF BROKEN = Always block
        if htf_state == TrendState.BROKEN:
            return (
                MarketRegime.HIGH_RISK,
                f"🚫 {htf_timeframe}m trend broken (structure failed)"
            )
        
        # HTF EXPANDING
        if htf_state == TrendState.EXPANDING:
            if ltf_state == TrendState.EXPANDING:
                return (
                    MarketRegime.EXPANDING,
                    f"🚀 BEST SETUP: {htf_timeframe}m + {ltf_timeframe}m both expanding"
                )
            elif ltf_state == TrendState.HEALTHY:
                return (
                    MarketRegime.EXPANDING,
                    f"🚀 Strong: {htf_timeframe}m expanding, {ltf_timeframe}m stable"
                )
            elif ltf_state == TrendState.DECAYING:
                return (
                    MarketRegime.SAFE,
                    f"⚠️ {htf_timeframe}m strong but {ltf_timeframe}m showing early decay"
                )
            else:  # LTF BROKEN
                return (
                    MarketRegime.CHOPPY,
                    f"⚠️ {htf_timeframe}m expanding but {ltf_timeframe}m broken - wait for sync"
                )
        
        # HTF HEALTHY
        elif htf_state == TrendState.HEALTHY:
            if ltf_state == TrendState.EXPANDING:
                return (
                    MarketRegime.EXPANDING,
                    f"🚀 {ltf_timeframe}m leading: expanding while {htf_timeframe}m stable"
                )
            elif ltf_state == TrendState.HEALTHY:
                return (
                    MarketRegime.SAFE,
                    f"✅ Both timeframes healthy - normal conditions"
                )
            elif ltf_state == TrendState.DECAYING:
                return (
                    MarketRegime.CHOPPY,
                    f"⚠️ {ltf_timeframe}m showing early decay (HTF stable)"
                )
            else:  # LTF BROKEN
                return (
                    MarketRegime.CHOPPY,
                    f"⚠️ {ltf_timeframe}m broken (HTF still healthy)"
                )
        
        # HTF DECAYING
        else:  # htf_state == TrendState.DECAYING
            if ltf_state == TrendState.EXPANDING:
                return (
                    MarketRegime.CHOPPY,
                    f"⚠️ Conflicted: {htf_timeframe}m decaying but {ltf_timeframe}m expanding"
                )
            elif ltf_state == TrendState.HEALTHY:
                return (
                    MarketRegime.CHOPPY,
                    f"⚠️ {htf_timeframe}m decaying - wait for confirmation"
                )
            elif ltf_state == TrendState.DECAYING:
                return (
                    MarketRegime.CHOPPY,
                    f"⚠️ BOTH timeframes decaying - avoid"
                )
            else:  # LTF BROKEN
                return (
                    MarketRegime.HIGH_RISK,
                    f"🚫 Both timeframes failing ({htf_timeframe}m decay, {ltf_timeframe}m broken)"
                )
    
    def _check_high_risk(
        self,
        symbol: str,
        primary_trend,
        confirm_trend,
        primary_timeframe: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check for HIGH RISK conditions (absolute blocks)
        
        These are extreme conditions that override everything else:
        1. Panic/Euphoria RSI levels
        2. Volatility spikes (ATR)
        3. Whipsaw reversals (strong trend breaking sharply)
        4. Distribution patterns (institutional selling)
        """
        # 1. PANIC ZONE - Institutional dumping
        rsi = primary_trend.rsi
        if rsi < self.rsi_panic:
            return True, f"Panic zone - RSI {rsi:.0f} indicates distribution"
        
        # 2. EUPHORIA ZONE - Retail FOMO topping
        if rsi > self.rsi_euphoria:
            return True, f"Euphoria zone - RSI {rsi:.0f} indicates exhaustion"
        
        # 3. VOLATILITY SPIKE - Risk expanded beyond normal
        atr_data = self.atr_cache.get(symbol, primary_timeframe)
        if atr_data is not None:
            atr_ratio = atr_data.get_ratio()
            if atr_ratio > self.atr_spike:
                return True, f"Volatility spike - ATR {atr_ratio:.2f}x normal (stops unreliable)"
        
         # 4. DANGEROUS WHIPSAW - Strong UPTREND breaking sharply
        # IMPORTANT: Only block when a strong UPTREND is breaking down
        # Do NOT block bullish recoveries from downtrends (that's 15m leading, which is GOOD)
        #
        # Philosophy:
        # - Uptrend breaking = Danger (institutional exit, something broke)
        # - Downtrend recovering = Opportunity (15m leading HTF into recovery)
        #
        # We're trading LONG only, so:
        # - Block: Strong bullish HTF + bearish LTF reversal (uptrend breaking)
        # - Allow: Bearish HTF + bullish LTF recovery (downtrend recovering - GOOD!)

        if confirm_trend is not None:
            primary_diff_pct = ((primary_trend.ema20 - primary_trend.ema50) / primary_trend.ema50) * 100
            confirm_diff_pct = ((confirm_trend.ema20 - confirm_trend.ema50) / confirm_trend.ema50) * 100
                        
            # ONLY Case: Strong bullish HTF + Strong bearish LTF
            # (Do NOT check the inverse - that's a recovery, not a whipsaw)
            if primary_diff_pct > self.whipsaw_threshold:  # Strong bullish 60m
                if confirm_diff_pct < self.reversal_threshold:  # Strong bearish 15m (reversal)
                    return True, (
                        f"Whipsaw reversal - strong uptrend breaking "
                        f"(HTF {primary_diff_pct:+.2f}%, LTF {confirm_diff_pct:+.2f}%)"
                    )
        
        # 5. DISTRIBUTION PATTERN - High volume selling (institutional exit)
        # Only flag if we have volume data AND multiple signals align
        if primary_trend.volume_ratio is not None:
            distribution_threshold = 1.5  # High volume threshold
            
            if primary_trend.volume_ratio > distribution_threshold:
                # High volume present - check if it's selling pressure
                if primary_trend.price < primary_trend.vwap:  # Below VWAP = sellers in control
                    # Get RSI momentum to confirm distribution (not just volatility)
                    rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
                        symbol, primary_timeframe
                    )
                    if rsi_direction == "decreasing":
                        return True, (
                            f"Distribution pattern - high volume "
                            f"({primary_trend.volume_ratio:.1f}x) selling below VWAP "
                            f"with RSI declining"
                        )
        
        # 6. CHECK LTF EXTREMES (if available)
        # Sometimes LTF shows extremes before HTF (early warning)
        if confirm_trend is not None:
            ltf_rsi = confirm_trend.rsi
            if ltf_rsi < self.rsi_panic:
                return True, f"LTF panic - RSI {ltf_rsi:.0f}"
            if ltf_rsi > self.rsi_euphoria:
                return True, f"LTF euphoria - RSI {ltf_rsi:.0f}"
        
        return False, None
    
    def can_trade(
        self,
        symbol: str,
        profile_name: str,
        primary_timeframe: str = "60",
        confirm_timeframe: str = "15"
    ) -> Tuple[bool, str]:
        """
        Simple yes/no: Is the market safe enough to trade?
        
        Returns:
            (can_trade, reason)
        """
        regime, reason = self.get_regime(symbol, primary_timeframe, confirm_timeframe)
        
        # EXPANDING and SAFE = green light
        if regime in [MarketRegime.SAFE, MarketRegime.EXPANDING]:
            return True, reason
        
        # HIGH_RISK = red light
        elif regime == MarketRegime.HIGH_RISK:
            self.logger.warning(f"[{profile_name}] {symbol}: BLOCKED - {reason}")
            return False, reason
        
        # CHOPPY = yellow light
        else:  # CHOPPY
            self.logger.info(f"[{profile_name}] {symbol}: WAIT - {reason}")
            return False, reason
    
    def get_trend_state_summary(
        self,
        symbol: str,
        primary_timeframe: str = "60",
        confirm_timeframe: str = "15"
    ) -> dict:
        """
        Get detailed trend state for both timeframes (for debugging)
        """
        primary_trend = self.trend_cache.get(symbol, primary_timeframe)
        confirm_trend = self.trend_cache.get(symbol, confirm_timeframe)
        
        htf_state = self._get_trend_state(primary_trend, primary_timeframe, symbol)
        ltf_state = self._get_trend_state(confirm_trend, confirm_timeframe, symbol) if confirm_trend else None
        
        return {
            "symbol": symbol,
            "htf": {
                "timeframe": primary_timeframe,
                "state": htf_state.value,
                "ema_gap": abs((primary_trend.ema20 - primary_trend.ema50) / primary_trend.ema50) * 100 if primary_trend else None,
                "volume": primary_trend.volume_ratio if primary_trend else None
            },
            "ltf": {
                "timeframe": confirm_timeframe,
                "state": ltf_state.value if ltf_state else None,
                "ema_gap": abs((confirm_trend.ema20 - confirm_trend.ema50) / confirm_trend.ema50) * 100 if confirm_trend else None,
                "volume": confirm_trend.volume_ratio if confirm_trend else None
            }
        }

        
    def get_regime_summary(self, symbols: list) -> dict:
        """Get regime classification for multiple symbols"""
        regimes = {
            MarketRegime.SAFE: [],
            MarketRegime.CHOPPY: [],
            MarketRegime.HIGH_RISK: [],
            MarketRegime.EXPANDING: []
        }
        
        for symbol in symbols:
            regime, reason = self.get_regime(symbol)
            regimes[regime].append({"symbol": symbol, "reason": reason})
        
        return {
            "safe": len(regimes[MarketRegime.SAFE]),
            "choppy": len(regimes[MarketRegime.CHOPPY]),
            "high_risk": len(regimes[MarketRegime.HIGH_RISK]),
            "expanding": len(regimes[MarketRegime.EXPANDING]),
            "details": {
                "safe": regimes[MarketRegime.SAFE],
                "choppy": regimes[MarketRegime.CHOPPY],
                "high_risk": regimes[MarketRegime.HIGH_RISK],
                "expanding": regimes[MarketRegime.EXPANDING]
            }
        }


# Global instance
_regime_filter = None


def get_regime_filter_new() -> RegimeFilterTesting:
    """Get or create global regime filter"""
    global _regime_filter
    if _regime_filter is None:
        _regime_filter = RegimeFilterTesting()
    return _regime_filter