# cache/regime_filter.py
"""
Market Regime Filter - Risk-based market condition classifier

PHILOSOPHY:
This filter is NOT about confirming trends (your trend_cache does that).
This filter answers: "Is the market environment SAFE for trend trading?"

Focus areas:
1. CHOP DETECTION - Avoid whipsaw environments
2. VOLUME QUALITY - Ensure conviction behind moves  
3. VOLATILITY SPIKES - Detect when risk has expanded
4. MOMENTUM QUALITY - Catch exhaustion/distribution

PERMISSIVE BY DEFAULT: Only blocks genuinely dangerous conditions
"""

from typing import Optional, Tuple, Dict
from enum import Enum
import time
from utils.logging import log_manager
from cache.trend_cache import get_trend_cache
from cache.atr_cache import get_atr_cache


class MarketRegime(Enum):
    """Market regime classification based on RISK, not trend"""
    SAFE = "safe"               # ✅ Safe to trade - trust your trend signals
    CHOPPY = "choppy"           # ⚠️ Whipsaw risk - wait for clarity
    HIGH_RISK = "high_risk"     # 🚫 Dangerous - don't trade


class RegimeFilter:
    """
    Risk-based regime filter focused on WHAT YOUR TREND LOGIC DOESN'T SEE
    
    Your trend_cache answers: "Is there a bullish setup?" (2/3 indicators)
    This filter answers: "Is the market safe enough to act on that setup?"
    """
    
    def __init__(self):
        self.logger = log_manager.get_logger("RegimeFilter")
        self.trend_cache = get_trend_cache()
        self.atr_cache = get_atr_cache()
        
        # ------------------------------------------------------------------
        # RISK DETECTION THRESHOLDS (permissive - only catch real danger)
        # ------------------------------------------------------------------
        
        # 1. CHOP DETECTION
        self.chop_ema_range_pct = 0.5       # EMAs within 0.5% = choppy
        self.chop_rsi_neutral = (45, 55)    # RSI stuck here = no momentum
        
        # 2. EXTREME CONDITIONS  
        self.rsi_panic = 30                 # Panic selling
        self.rsi_euphoria = 78              # Euphoric buying
        self.atr_spike = 1.8                # Volatility explosion
        
        # 3. VOLUME QUALITY
        self.min_volume_ratio = 0.6         # Below 0.6x = dead market
        self.min_volume_ratio_confirm = 0.7  # NEW: Stricter for 15m        
        self.distribution_volume = 1.5      # High volume + down = distribution

        # 4. WHIPSAW DETECTION
        self.whipsaw_threshold = 1.0  # Require very strong established UPTREND
        self.reversal_threshold = -0.8  # Strong bearish reversal on LTF
            
        # Cache results
        self._regime_cache: Dict[str, Tuple[MarketRegime, str, float]] = {}
        self._cache_ttl = 60
        
        self.logger.info("RegimeFilter initialized - RISK-FOCUSED MODE")
    
    def get_regime(
        self, 
        symbol: str,
        primary_timeframe: str = "60",
        confirm_timeframe: str = "15",
        strategy_type: str = "trend_following"
    ) -> Tuple[MarketRegime, str]:
        """
        Determine if market environment is SAFE for trading
         Args:
            strategy_type: "trend_following" or "mean_reversion"
        Returns:
            (regime, reason) where regime is SAFE, CHOPPY, or HIGH_RISK
        """
        cache_key = f"{symbol}_{primary_timeframe}_{confirm_timeframe}"
        if cache_key in self._regime_cache:
            regime, reason, timestamp = self._regime_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return regime, reason
        
        primary_trend = self.trend_cache.get(symbol, primary_timeframe)
        confirm_trend = self.trend_cache.get(symbol, confirm_timeframe)
        
        if primary_trend is None:
            return MarketRegime.CHOPPY, f"No {primary_timeframe}m data - cannot assess risk"
        
        # PRIORITY 1: Check for HIGH RISK (blocks everything)
        high_risk, risk_reason = self._check_high_risk(
            symbol, primary_trend, confirm_trend, primary_timeframe, strategy_type=strategy_type
        )
        if high_risk:
            regime = MarketRegime.HIGH_RISK
            reason = f"🚫 {risk_reason}"
            self._regime_cache[cache_key] = (regime, reason, time.time())
            self.logger.warning(f"{symbol}: {reason}")
            return regime, reason
        
        # PRIORITY 2: Check for CHOPPY conditions (wait for better setup)
        is_choppy, chop_reason = self._check_choppy(
            symbol, primary_trend, confirm_trend, primary_timeframe, confirm_timeframe
        )
        if is_choppy:
            regime = MarketRegime.CHOPPY
            reason = f"⚠️ {chop_reason}"
            self._regime_cache[cache_key] = (regime, reason, time.time())
            self.logger.info(f"{symbol}: {reason}")
            return regime, reason
        
        # DEFAULT: SAFE - trust your trend signals
        regime = MarketRegime.SAFE
        reason = "✅ Market conditions safe - trust trend signals"
        self._regime_cache[cache_key] = (regime, reason, time.time())
        return regime, reason
    
    def _check_high_risk(
        self, 
        symbol: str,
        primary_trend,
        confirm_trend,
        primary_timeframe: str,
        strategy_type: str = "trend_following"
    ) -> Tuple[bool, Optional[str]]:
        """
        Detect HIGH RISK conditions that invalidate ALL setups
        
        These are conditions where even a "perfect" 3/3 bullish trend should be avoided
        """
        rsi = primary_trend.rsi

        #1. Panic zone
        if strategy_type == "trend_following":
            # Original logic - block extreme panic
            if rsi < self.rsi_panic:  # 30
                return True, f"Panic zone - RSI {rsi:.0f} indicates distribution"
        
        elif strategy_type == "mean_reversion":
            # Mean reversion LOVES oversold, but not EXTREME panic
            # Only block if RSI < 20 (true panic) or dropping very fast
            rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
                symbol, primary_timeframe
            )
            
            if rsi < 20:  # Extreme panic
                return True, f"Extreme panic - RSI {rsi:.0f} too low even for mean reversion"
            
            # Block if RSI is plummeting (momentum < -10)
            if rsi_momentum is not None and rsi_momentum < -10:
                return True, f"Free fall - RSI dropping {rsi_momentum:.1f} (wait for stabilization)"
                
        
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

        if strategy_type == "trend_following":
            # ... existing whipsaw logic ...
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
        
        elif strategy_type == "mean_reversion":
            # Mean reversion LIKES volatility and reversals
            # Only block if BOTH timeframes are in free fall
            if confirm_trend is not None:
                primary_diff_pct = ((primary_trend.ema20 - primary_trend.ema50) / primary_trend.ema50) * 100
                confirm_diff_pct = ((confirm_trend.ema20 - confirm_trend.ema50) / confirm_trend.ema50) * 100
                
                # Only block if BOTH very bearish (coordinated crash)
                if primary_diff_pct < -2.0 and confirm_diff_pct < -2.0:
                    return True, (
                        f"Coordinated crash - both timeframes very bearish "
                        f"(HTF {primary_diff_pct:+.2f}%, LTF {confirm_diff_pct:+.2f}%)"
                    )
        
         
        # 5. DISTRIBUTION PATTERN - High volume selling
        # (Only flag if we have volume data AND it's extreme)
        if primary_trend.volume_ratio is not None:
            if primary_trend.volume_ratio > self.distribution_volume:
                # High volume - check if it's selling pressure
                if primary_trend.price < primary_trend.vwap:  # Below VWAP
                    # Get RSI momentum to confirm distribution
                    rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
                        symbol, primary_timeframe
                    )
                    if rsi_direction == "decreasing":
                        return True, f"Distribution pattern - high volume ({primary_trend.volume_ratio:.1f}x) selling below VWAP"
        
        return False, None
    
    def _check_choppy(
        self,
        symbol: str,
        primary_trend,
        confirm_trend,
        primary_timeframe: str,
        confirm_timeframe: str
    ) -> Tuple[bool, str]:
        """
        Detect CHOPPY conditions where trends are unreliable
        
        This is NOT about "is there a trend?" (trend_cache handles that)
        This is about "is the market structure clean enough to trade?"
        """
        issues = []
        
        # 1. EMA COMPRESSION - Tight range indicates indecision
        ema_diff_pct = abs(((primary_trend.ema20 - primary_trend.ema50) / primary_trend.ema50) * 100)
        if ema_diff_pct < self.chop_ema_range_pct:
            issues.append(f"60m EMAs compressed ({ema_diff_pct:.2f}% - no clear direction)")

        # NEW: Check 15m compression too
        if confirm_trend is not None:
            confirm_ema_diff = abs(((confirm_trend.ema20 - confirm_trend.ema50) / 
                                    confirm_trend.ema50) * 100)
            
            if confirm_ema_diff < self.chop_ema_range_pct:
                # Both compressed = definitely choppy
                if ema_diff_pct < self.chop_ema_range_pct:
                    issues.append(
                        f"Both TFs compressed (60m: {ema_diff_pct:.2f}%, "
                        f"15m: {confirm_ema_diff:.2f}%)"
                    )        
        # 2. RSI STUCK IN NEUTRAL - No momentum
        rsi_low, rsi_high = self.chop_rsi_neutral
        if rsi_low < primary_trend.rsi < rsi_high:
            # Check if RSI has been stuck here (no momentum building)
            rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
                symbol, primary_timeframe
            )
            # Only flag if RSI is truly flat/weak
            if rsi_momentum is not None and abs(rsi_momentum) < 1.0:
                issues.append(f"60m RSI stuck neutral ({primary_trend.rsi:.0f}, momentum {rsi_momentum:+.1f})")
        
        # 3. DEAD VOLUME - No conviction
        if primary_trend.volume_ratio is not None:
            if primary_trend.volume_ratio < self.min_volume_ratio:
                issues.append(
                    f"Dead volume ({primary_trend.volume_ratio:.2f}x - no conviction)"
                )
            
            # NEW: Check both timeframes
            if confirm_trend is not None and confirm_trend.volume_ratio is not None:
                if (primary_trend.volume_ratio < self.min_volume_ratio and 
                    confirm_trend.volume_ratio < self.min_volume_ratio_confirm):
                    issues.append(
                        f"Both TFs dead volume (60m: {primary_trend.volume_ratio:.2f}x, "
                        f"15m: {confirm_trend.volume_ratio:.2f}x)"
                    )

        # 4. PRICE STAGNATION (NEW - use price vs EMA as proxy)
        # If price is very close to BOTH EMA20 and EMA50, it's oscillating (dead)
        price_ema20_gap = abs((primary_trend.price - primary_trend.ema20) / 
                              primary_trend.ema20) * 100
        price_ema50_gap = abs((primary_trend.price - primary_trend.ema50) / 
                              primary_trend.ema50) * 100
        
        if price_ema20_gap < 0.3 and price_ema50_gap < 0.5:
            issues.append(
                f"Price stagnant (EMA20: {price_ema20_gap:.2f}%, "
                f"EMA50: {price_ema50_gap:.2f}%)"
            )
            # If we found price stagnation, it's definitely choppy
            issues.append("Price stagnation detected")

        # Evaluate: flag as choppy if we found 2+ issues
        if len(issues) >= 2:
            return True, f"Choppy conditions ({len(issues)} issues): {'; '.join(issues)}"
        
        return False, ""
        
    def can_trade(
        self,
        symbol: str,
        profile_name: str,
        primary_timeframe: str = "60",
        confirm_timeframe: str = "15",
        strategy_type: str = "trend_following"
    ) -> Tuple[bool, str]:
        """
        Simple yes/no: Is the market SAFE enough to trade?
        
        This should be checked BEFORE your trend logic
        
        Flow:
        1. Regime filter: Is market safe? → If no, skip this symbol entirely
        2. Trend logic: Is there a bullish setup? → If yes, enter
        """
        
        regime, reason = self.get_regime(
            symbol, 
            primary_timeframe, 
            confirm_timeframe, 
            strategy_type=strategy_type
        )
        
        if regime == MarketRegime.SAFE:
            # Market is safe - now use your trend logic to find entries
            return True, reason
        
        elif regime == MarketRegime.HIGH_RISK:
            # Dangerous conditions - block all trading
            self.logger.warning(f"[{profile_name}] {symbol}: BLOCKED - {reason}")
            return False, reason
        
        else:  # CHOPPY
            # Wait for cleaner setup - not worth the risk
            self.logger.info(f"[{profile_name}] {symbol}: WAIT - {reason}")
            return False, reason
    
    def get_regime_summary(self, symbols: list) -> dict:
        """Get regime classification for multiple symbols"""
        regimes = {
            MarketRegime.SAFE: [],
            MarketRegime.CHOPPY: [],
            MarketRegime.HIGH_RISK: []
        }
        
        for symbol in symbols:
            regime, reason = self.get_regime(symbol)
            regimes[regime].append({"symbol": symbol, "reason": reason})
        
        return {
            "safe": len(regimes[MarketRegime.SAFE]),
            "choppy": len(regimes[MarketRegime.CHOPPY]),
            "high_risk": len(regimes[MarketRegime.HIGH_RISK]),
            "details": {
                "safe": regimes[MarketRegime.SAFE],
                "choppy": regimes[MarketRegime.CHOPPY],
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