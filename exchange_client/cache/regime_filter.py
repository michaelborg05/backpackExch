# cache/regime_filter.py
"""
Market Regime Filter - Broad market condition classifier

This filter sits ABOVE your existing trend logic and prevents trading in truly
adverse market conditions. It's designed to be permissive (not block good trades)
but protective (avoid terrible market environments).

Philosophy:
- Uses 60m data as primary regime indicator (broader context)
- Uses 15m data as confirmation (current conditions)
- Three regimes: TRENDING (trade), UNCERTAIN (wait), HIGH_RISK (stop)
- Focused on what actually caused your losses: choppy/distribution days
"""

from typing import Optional, Tuple, Dict
from enum import Enum
import time
from utils.logging import log_manager
from cache.trend_cache import get_trend_cache
from cache.atr_cache import get_atr_cache


class MarketRegime(Enum):
    """Market regime classification"""
    TRENDING = "trending"           # ✅ Safe to trade momentum/trend strategies
    UNCERTAIN = "uncertain"         # ⚠️ Wait - no clear direction
    HIGH_RISK = "high_risk"        # 🚫 Don't trade - dangerous conditions


class RegimeFilter:
    """
    Determines current market regime to prevent trading in bad conditions
    
    Uses dual-timeframe analysis:
    - 60m (primary): Overall market structure and momentum
    - 15m (confirm): Current execution environment
    
    Designed to be PERMISSIVE - only blocks truly bad conditions
    """
    
    def __init__(self):
        self.logger = log_manager.get_logger("RegimeFilter")
        self.trend_cache = get_trend_cache()
        self.atr_cache = get_atr_cache()
        
        # Regime detection settings (tuned to be permissive)
        self.ema_trending_threshold = 0.20  # 0.2% separation = trending (was 0.3% - too strict)
        self.rsi_neutral_range = (38, 65)   # Outside this = directional (was 40-60)
        self.rsi_extreme_low = 30           # Below this = panic/distribution
        self.rsi_extreme_high = 78          # Above this = euphoria (was 75)
        self.atr_spike_threshold = 1.8      # ATR > 1.8x average = volatility spike (was 1.5x)
        
        # Cache regime results (avoid recalculating same data)
        self._regime_cache: Dict[str, Tuple[MarketRegime, str, float]] = {}
        self._cache_ttl = 60  # Cache regime for 60 seconds
        
        self.logger.info("RegimeFilter initialized with permissive thresholds")
    
    def get_regime(
        self, 
        symbol: str,
        primary_timeframe: str = "60",
        confirm_timeframe: str = "15"
    ) -> Tuple[MarketRegime, str]:
        """
        Determine current market regime for a symbol
        
        Args:
            symbol: Trading symbol (e.g., "SOL_USDC")
            primary_timeframe: Higher timeframe for regime (default: 60m)
            confirm_timeframe: Lower timeframe for confirmation (default: 15m)
        
        Returns:
            (regime, reason) tuple
            - regime: MarketRegime enum value
            - reason: Human-readable explanation
        """
        # Check cache first
        cache_key = f"{symbol}_{primary_timeframe}_{confirm_timeframe}"
        if cache_key in self._regime_cache:
            regime, reason, timestamp = self._regime_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return regime, reason
        
        # Get trend data for both timeframes
        primary_trend = self.trend_cache.get(symbol, primary_timeframe)
        confirm_trend = self.trend_cache.get(symbol, confirm_timeframe)
        
        if primary_trend is None:
            return MarketRegime.UNCERTAIN, f"Regime Uncertain: No {primary_timeframe}m data available"
        
        # STEP 1: Check for HIGH RISK conditions (these override everything)
        high_risk, risk_reason = self._check_high_risk(
            symbol, 
            primary_trend, 
            confirm_trend,
            primary_timeframe
        )
        
        if high_risk:
            regime = MarketRegime.HIGH_RISK
            reason = f"🚫 {risk_reason}"
            self._regime_cache[cache_key] = (regime, reason, time.time())
            self.logger.warning(f"{symbol}: {reason}")
            return regime, reason
        
        # STEP 2: Check for TRENDING conditions
        is_trending, trend_reason = self._check_trending(
            symbol,
            primary_trend,
            confirm_trend,
            primary_timeframe,
            confirm_timeframe
        )
        
        if is_trending:
            regime = MarketRegime.TRENDING
            reason = f"✅ {trend_reason}"
            self._regime_cache[cache_key] = (regime, reason, time.time())
            self.logger.debug(f"{symbol}: {reason}")
            return regime, reason
        
        # STEP 3: Default to UNCERTAIN (not trending, not high-risk)
        regime = MarketRegime.UNCERTAIN
        reason = f"⚠️ No clear trend - {trend_reason}"
        self._regime_cache[cache_key] = (regime, reason, time.time())
        self.logger.debug(f"{symbol}: {reason}")
        
        return regime, reason
    
    def _check_high_risk(
        self, 
        symbol: str,
        primary_trend,
        confirm_trend,
        primary_timeframe: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check for HIGH RISK conditions that should block ALL trading
        
        High risk indicators:
        1. RSI in extreme ranges (panic selling or euphoric buying)
        2. Volatility spike (ATR expansion)
        3. Rapid trend reversals (whipsawing)
        
        Returns:
            (is_high_risk, reason)
        """
        # 1. Check for RSI extremes on primary timeframe
        rsi = primary_trend.rsi
        
        if rsi < self.rsi_extreme_low:
            return True, f"RSI {rsi:.0f} - panic/distribution zone (60m)"
        
        if rsi > self.rsi_extreme_high:
            return True, f"RSI {rsi:.0f} - euphoric/exhaustion zone (60m)"
        
        # 2. Check for volatility spike (if ATR data available)
        atr_data = self.atr_cache.get(symbol, primary_timeframe)
        if atr_data is not None:
            atr_ratio = atr_data.get_ratio()
            if atr_ratio > self.atr_spike_threshold:
                return True, f"ATR spike {atr_ratio:.2f}x - excessive volatility"
        
        # 3. Check for rapid EMA crossover on lower timeframe (whipsaw)
        if confirm_trend is not None:
            # Calculate the strength AND direction of both trends
            # Positive = bullish (EMA20 > EMA50), Negative = bearish (EMA20 < EMA50)
            primary_diff_pct = ((primary_trend.ema20 - primary_trend.ema50) / primary_trend.ema50) * 100
            confirm_diff_pct = ((confirm_trend.ema20 - confirm_trend.ema50) / confirm_trend.ema50) * 100
            
            # Only flag as dangerous whipsaw if:
            # 1. 60m has a VERY STRONG trend in one direction (>1.0% or <-1.0%)
            # 2. 15m has reversed to the opposite direction with strength (opposite sign, >0.8% magnitude)
            # 
            # Examples:
            # ✅ GOOD (15m leading): 60m=-0.97%, 15m=+1.60% → both moving toward bullish
            # ✅ GOOD (15m leading): 60m=+0.5%, 15m=+1.5% → both bullish, 15m stronger
            # 🚫 BAD (whipsaw): 60m=+1.5%, 15m=-1.0% → strong bullish reversing to bearish
            # 🚫 BAD (whipsaw): 60m=-1.5%, 15m=+1.0% → strong bearish reversing to bullish
            
            # Check if 60m has strong established trend
            if primary_diff_pct > 1.0:  # Strong bullish on 60m
                # Flag if 15m is strongly bearish (reversing)
                if confirm_diff_pct < -0.8:
                    return True, f"Dangerous whipsaw - strong bullish 60m reversing (60m +{primary_diff_pct:.2f}% vs 15m {confirm_diff_pct:.2f}%)"
            
            elif primary_diff_pct < -1.0:  # Strong bearish on 60m
                # Flag if 15m is strongly bullish (reversing)
                if confirm_diff_pct > 0.8:
                    return True, f"Dangerous whipsaw - strong bearish 60m reversing (60m {primary_diff_pct:.2f}% vs 15m +{confirm_diff_pct:.2f}%)"
        
        return False, None
    
    def _check_trending(
        self,
        symbol: str,
        primary_trend,
        confirm_trend,
        primary_timeframe: str,
        confirm_timeframe: str
    ) -> Tuple[bool, str]:
        """
        Check if market is in TRENDING regime
        
        Trending conditions (need 2 of 3):
        1. EMA separation on 60m (momentum exists)
        2. RSI shows direction (not stuck in neutral zone)
        3. Price structure aligned on both timeframes
        
        This is PERMISSIVE - designed to catch trending conditions early
        
        Returns:
            (is_trending, reason)
        """
        conditions_met = []
        conditions_failed = []
        
        # CONDITION 1: EMA separation on primary timeframe
        ema_diff_pct = ((primary_trend.ema20 - primary_trend.ema50) / primary_trend.ema50) * 100
        
        if ema_diff_pct > self.ema_trending_threshold:
            conditions_met.append(f"60m EMA+{ema_diff_pct:.2f}%")
        else:
            conditions_failed.append(f"60m EMA only {ema_diff_pct:.2f}%")
        
        # CONDITION 2: RSI shows directional bias (not neutral)
        rsi = primary_trend.rsi
        rsi_low, rsi_high = self.rsi_neutral_range
        
        if rsi > rsi_high:
            # Get RSI momentum if available
            rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
                symbol, 
                primary_timeframe
            )
            
            if rsi_direction == "increasing":
                conditions_met.append(f"60m RSI {rsi:.0f} rising")
            else:
                conditions_met.append(f"60m RSI {rsi:.0f} bullish")
        elif rsi < rsi_low:
            conditions_failed.append(f"60m RSI {rsi:.0f} weak")
        else:
            # In neutral zone - check momentum to see if we're building
            rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
                symbol, 
                primary_timeframe
            )
            
            if rsi_direction == "increasing" and rsi > 45:
                conditions_met.append(f"60m RSI {rsi:.0f} building momentum")
            else:
                conditions_failed.append(f"60m RSI {rsi:.0f} neutral")
        
        # CONDITION 3: Price structure alignment
        # Both timeframes should be above VWAP (institutional support)
        primary_above_vwap = primary_trend.price > primary_trend.vwap
        
        if confirm_trend is not None:
            confirm_above_vwap = confirm_trend.price > confirm_trend.vwap
            
            if primary_above_vwap and confirm_above_vwap:
                conditions_met.append("Price > VWAP both TFs")
            elif primary_above_vwap:
                conditions_met.append("60m Price > VWAP")
            else:
                conditions_failed.append("Price below VWAP")
        else:
            # No confirm data - just check primary
            if primary_above_vwap:
                conditions_met.append("60m Price > VWAP")
            else:
                conditions_failed.append("60m Price below VWAP")
        
        # Evaluate: need 2 of 3 conditions
        if len(conditions_met) >= 2:
            reason = f"{len(conditions_met)}/3: {', '.join(conditions_met)}"
            return True, reason
        else:
            # Explain why we're not trending
            all_conditions = conditions_met + conditions_failed
            reason = f"Only {len(conditions_met)}/3: {', '.join(all_conditions)}"
            return False, reason
    
    def can_trade(
        self,
        symbol: str,
        profile_name: str,
        primary_timeframe: str = "60",
        confirm_timeframe: str = "15"
    ) -> Tuple[bool, str]:
        """
        Simple yes/no check if trading is allowed
        
        Args:
            symbol: Trading symbol
            profile_name: Trading profile name (for logging)
            primary_timeframe: Higher timeframe for regime
            confirm_timeframe: Lower timeframe for confirmation
        
        Returns:
            (can_trade, reason) tuple
        """
        regime, reason = self.get_regime(symbol, primary_timeframe, confirm_timeframe)
        
        if regime == MarketRegime.TRENDING:
            return True, reason
        elif regime == MarketRegime.HIGH_RISK:
            self.logger.warning(
                f"[{profile_name}] {symbol}: Trading BLOCKED - {reason}"
            )
            return False, reason
        else:  # UNCERTAIN
            self.logger.info(
                f"[{profile_name}] {symbol}: Trading PAUSED - {reason}"
            )
            return False, reason
    
    def get_regime_summary(self, symbols: list) -> dict:
        """
        Get regime classification for multiple symbols
        
        Args:
            symbols: List of symbols to check
        
        Returns:
            Dictionary with regime counts and details
        """
        regimes = {
            MarketRegime.TRENDING: [],
            MarketRegime.UNCERTAIN: [],
            MarketRegime.HIGH_RISK: []
        }
        
        for symbol in symbols:
            regime, reason = self.get_regime(symbol)
            regimes[regime].append({
                "symbol": symbol,
                "reason": reason
            })
        
        return {
            "trending": len(regimes[MarketRegime.TRENDING]),
            "uncertain": len(regimes[MarketRegime.UNCERTAIN]),
            "high_risk": len(regimes[MarketRegime.HIGH_RISK]),
            "details": {
                "trending": regimes[MarketRegime.TRENDING],
                "uncertain": regimes[MarketRegime.UNCERTAIN],
                "high_risk": regimes[MarketRegime.HIGH_RISK]
            }
        }


# Global instance
_regime_filter = None


def get_regime_filter() -> RegimeFilter:
    """Get or create global regime filter"""
    global _regime_filter
    if _regime_filter is None:
        _regime_filter = RegimeFilter()
    return _regime_filter