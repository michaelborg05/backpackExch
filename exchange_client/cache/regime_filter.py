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
from decimal import Decimal
from enum import Enum
import time
from utils.constants import StrategyType, MarketRegime
from utils.logging import log_manager
from cache.trend_cache import get_trend_cache


class RegimeFilter:
    """
    Risk-based regime filter focused on WHAT YOUR TREND LOGIC DOESN'T SEE
    
    Your trend_cache answers: "Is there a bullish setup?" (2/3 indicators)
    This filter answers: "Is the market safe enough to act on that setup?"
    """
    
    def __init__(self):
        self.logger = log_manager.get_logger("RegimeFilter")
        self.trend_cache = get_trend_cache()

        # ------------------------------------------------------------------
        # RISK DETECTION THRESHOLDS (permissive - only catch real danger)
        # ------------------------------------------------------------------
        
        # 1. CHOP DETECTION
        self.chop_ema_range_pct = 0.5       # EMAs within 0.5% = choppy
        self.chop_rsi_neutral = (45, 55)    # RSI stuck here = no momentum
        self.adx_trending_threshold = 22    # ADX above this = trending (suppress compression flags)
        
        # 2. EXTREME CONDITIONS  
        self.rsi_panic = 30                 # Panic selling
        self.rsi_euphoria = 78              # Euphoric buying

        # 3. VOLUME QUALITY
        self.min_volume_ratio = 0.4         # Below 0.4x = dead market
        self.min_volume_ratio_confirm = 0.5  # NEW: Stricter for 15m
        self.distribution_volume = 1.5      # High volume + down = distribution

        # 4. WHIPSAW DETECTION
        self.whipsaw_threshold = 1.0  # Require very strong established UPTREND
        self.reversal_threshold = -0.8  # Strong bearish reversal on LTF

        # 5. SUSTAINED TREND (counter-trend strategies)
        # EMA20/50 spread on the regime timeframe beyond this blocks shorting
        # into a rally (short strategies) / dip-buying a downtrend (mean reversion)
        self.sustained_trend_spread_pct = 2.0
            
        # Cache results
        self._regime_cache: Dict[str, Tuple[MarketRegime, str, float]] = {}
        self._cache_ttl = 240
        
        self.logger.info("RegimeFilter initialized - RISK-FOCUSED MODE")
    
    def get_regime(
        self, 
        symbol: str,
        primary_timeframe: str = "60",
        confirm_timeframe: str = "15",
        strategy_type: StrategyType = StrategyType.TREND_FOLLOWING
    ) -> Tuple[MarketRegime, str]:
        """
        Determine if market environment is SAFE for trading
         Args:
            strategy_type: "trend_following" or "mean_reversion"
        Returns:
            (regime, reason) where regime is SAFE, CHOPPY, or HIGH_RISK
        """

        cache_key = f"{symbol}_{primary_timeframe}_{confirm_timeframe}_{strategy_type.value}"
        if cache_key in self._regime_cache:
            regime, reason, timestamp = self._regime_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                
                
                return regime, reason
        
        primary_trend = self.trend_cache.get(symbol, primary_timeframe)
        confirm_trend = self.trend_cache.get(symbol, confirm_timeframe)
        
        if primary_trend is None:
            return MarketRegime.UNKNOWN, f"No {primary_timeframe}m data - cannot assess risk"
        

        from cache.price_cache import get_price_cache
        price_cache = get_price_cache()
        price = price_cache.get_price(symbol)
        current_price = float(price) if price is not None else confirm_trend.price

        # PRIORITY 1: Check for HIGH RISK (blocks everything)
        high_risk, risk_reason = self._check_high_risk(
            symbol, primary_trend, confirm_trend, primary_timeframe, strategy_type=strategy_type, price=current_price
        )
        if high_risk:
            regime = MarketRegime.HIGH_RISK
            reason = f"🚫 {risk_reason}"
            self._regime_cache[cache_key] = (regime, reason, time.time())
            self.logger.warning(f"{symbol}: {reason}")
            return regime, reason
        
        # PRIORITY 2: Check for CHOPPY conditions (wait for better setup)
        is_choppy, chop_reason = self._check_choppy(
            symbol, primary_trend, confirm_trend, primary_timeframe, confirm_timeframe, price=current_price
        )
        if is_choppy:
            regime = MarketRegime.CHOPPY
            reason = f"{" Good for Range Trading profile - " if strategy_type == StrategyType.RANGE_TRADING else "⚠️"} {chop_reason}"
            self._regime_cache[cache_key] = (regime, reason, time.time())
            self.logger.info(f"{symbol}: {reason}")
            return regime, reason
        
        # DEFAULT: SAFE - trust your trend signals
        regime = MarketRegime.SAFE
        reason = "Market conditions safe - trust trend signals"
        self._regime_cache[cache_key] = (regime, reason, time.time())
        return regime, reason
    
    def _check_high_risk(
        self,
        symbol: str,
        primary_trend,
        confirm_trend,
        primary_timeframe: str,
        strategy_type: StrategyType = StrategyType.TREND_FOLLOWING,
        price: Decimal = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Detect HIGH RISK conditions that invalidate ALL setups.
        Short strategy variants flip the long-side RSI and whipsaw conditions.
        """
        rsi = primary_trend.rsi
        if price is None:
            price = confirm_trend.price

        # 1. PANIC / SQUEEZE ZONES (direction-aware)
        if strategy_type.is_short:
            # For shorts: extreme oversold = high bounce risk
            if rsi < 20:
                return True, f"Extreme oversold - RSI {rsi:.0f} too low for shorting (bounce risk)"
            rsi_momentum, _ = self.trend_cache._get_rsi_momentum(symbol, primary_timeframe)
            if rsi_momentum is not None and rsi_momentum < -12:
                return True, f"RSI already in free-fall ({rsi_momentum:.1f}) - short entry too late"
        elif strategy_type in (StrategyType.TREND_FOLLOWING, StrategyType.RANGE_TRADING):
            if rsi < self.rsi_panic:  # 30
                return True, f"Panic zone - RSI {rsi:.0f} indicates distribution"
        elif strategy_type == StrategyType.MEAN_REVERSION:
            # Mean reversion LOVES oversold, but not EXTREME panic
            rsi_momentum, _ = self.trend_cache._get_rsi_momentum(symbol, primary_timeframe)
            if rsi < 20:
                return True, f"Extreme panic - RSI {rsi:.0f} too low even for mean reversion"
            if rsi_momentum is not None and rsi_momentum < -10:
                return True, f"Free fall - RSI dropping {rsi_momentum:.1f} (wait for stabilization)"

        # 2. EUPHORIA / OVERBOUGHT ZONE
        if strategy_type == StrategyType.SHORT_MEAN_REVERSION:
            # Short mean reversion WANTS overbought — only block extreme RSI still surging
            if rsi > 85:
                rsi_momentum, _ = self.trend_cache._get_rsi_momentum(symbol, primary_timeframe)
                if rsi_momentum is not None and rsi_momentum > 8:
                    return True, f"Extreme overbought with surge - RSI {rsi:.0f} still climbing ({rsi_momentum:+.1f})"
        elif strategy_type == StrategyType.SHORT_TREND_FOLLOWING:
            # Short trend following: high RSI is our setup — only block if RSI surging upward
            if rsi > 80:
                rsi_momentum, _ = self.trend_cache._get_rsi_momentum(symbol, primary_timeframe)
                if rsi_momentum is not None and rsi_momentum > 10:
                    return True, f"Euphoria surge - RSI {rsi:.0f} climbing fast ({rsi_momentum:+.1f}) — wait for rollover"
        else:
            if rsi > self.rsi_euphoria:
                return True, f"Euphoria zone - RSI {rsi:.0f} indicates exhaustion"

        # 3. WHIPSAW / REVERSAL / SUSTAINED-TREND DETECTION
        primary_diff_pct = ((primary_trend.ema20 - primary_trend.ema50) / primary_trend.ema50) * 100

        if strategy_type == StrategyType.SHORT_TREND_FOLLOWING:
            # Sustained rally on the regime timeframe — don't fade a market that
            # has been grinding up for days (e.g. 4h EMA20 > EMA50 by 2%+)
            if primary_diff_pct > self.sustained_trend_spread_pct:
                return True, (
                    f"Sustained {primary_timeframe}m uptrend - EMA20/50 spread "
                    f"{primary_diff_pct:+.2f}% > {self.sustained_trend_spread_pct}% — no shorting into strength"
                )
            # Block: strong bearish HTF + bullish LTF reversal = short squeeze forming
            if confirm_trend is not None:
                confirm_diff_pct = ((confirm_trend.ema20 - confirm_trend.ema50) / confirm_trend.ema50) * 100
                if primary_diff_pct < -self.whipsaw_threshold:  # Strong bearish 60m
                    if confirm_diff_pct > abs(self.reversal_threshold):  # LTF turning bullish
                        if price > confirm_trend.ema20:  # Price recaptured LTF EMA = genuine recovery
                            return True, (
                                f"Short squeeze risk - strong downtrend but LTF recovering "
                                f"(HTF {primary_diff_pct:+.2f}%, LTF {confirm_diff_pct:+.2f}%)"
                            )
        elif strategy_type == StrategyType.SHORT_MEAN_REVERSION:
            # Sustained rally on the regime timeframe (too late/dangerous to short).
            # Uses the regime TF alone: the LTF being merely overbought is the
            # setup, not a safety signal — what matters is the higher-TF trend.
            if primary_diff_pct > self.sustained_trend_spread_pct:
                return True, (
                    f"Sustained {primary_timeframe}m rally - EMA20/50 spread "
                    f"{primary_diff_pct:+.2f}% > {self.sustained_trend_spread_pct}% — wait for exhaustion"
                )
        elif strategy_type == StrategyType.MEAN_REVERSION:
            # Mean reversion LIKES volatility and reversals — but not dip-buying
            # a sustained downtrend on the regime timeframe
            if primary_diff_pct < -self.sustained_trend_spread_pct:
                return True, (
                    f"Sustained {primary_timeframe}m downtrend - EMA20/50 spread "
                    f"{primary_diff_pct:+.2f}% < -{self.sustained_trend_spread_pct}% — no dip-buying a falling market"
                )
        elif strategy_type == StrategyType.RANGE_TRADING:
            # Range trading relies on its own entry indicators — skip whipsaw check
            pass
        else:
            # TREND_FOLLOWING: block strong bullish HTF + bearish LTF reversal
            if confirm_trend is not None:
                primary_diff_pct = ((primary_trend.ema20 - primary_trend.ema50) / primary_trend.ema50) * 100
                confirm_diff_pct = ((confirm_trend.ema20 - confirm_trend.ema50) / confirm_trend.ema50) * 100
                if primary_diff_pct > self.whipsaw_threshold:  # Strong bullish 60m
                    if confirm_diff_pct < self.reversal_threshold:  # Strong bearish 15m
                        if price > confirm_trend.ema20:
                            pass  # Recovery, not breakdown — let it through
                        else:
                            return True, (
                                f"Whipsaw reversal - strong uptrend breaking "
                                f"(HTF {primary_diff_pct:+.2f}%, LTF {confirm_diff_pct:+.2f}%)"
                            )

        # 5. DISTRIBUTION PATTERN - High volume selling (long strategies only)
        # For short strategies, high volume selling is a confirmation, not a risk
        if not strategy_type.is_short and primary_trend.volume_ratio is not None:
            if primary_trend.volume_ratio > self.distribution_volume:
                if price < primary_trend.vwap:  # Below VWAP
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
        confirm_timeframe: str,
        price: Decimal = None
    ) -> Tuple[bool, str]:
        """
        Detect CHOPPY conditions where trends are unreliable
        
        This is NOT about "is there a trend?" (trend_cache handles that)
        This is about "is the market structure clean enough to trade?"
        """
        issues = []

        if price is None:
            price = primary_trend.price
            

        # 1. EMA COMPRESSION - Tight range indicates indecision
        # IMPORTANT: Gap alone is not enough. A compressing gap during a trend
        # recovery (EMA20 rising toward EMA50 from below) is NOT chop — it's
        # structural consolidation before continuation. We check two extra conditions:
        #   a) EMA20 slope must be flat or falling (a rising slope = recovering trend)
        #   b) ADX must be below trending threshold (high ADX = real trend, not chop)
        ema_diff_pct = abs(((primary_trend.ema20 - primary_trend.ema50) / primary_trend.ema50) * 100)

        # Get 60m EMA20 slope and ADX for context
        ema20_slope_pct, ema20_slope_dir = self.trend_cache._get_ema_slope(
            symbol, primary_timeframe, "ema20"
        )
        adx_value = getattr(primary_trend, "adx", None)
        adx_is_trending = (
            adx_value is not None and float(adx_value) > self.adx_trending_threshold
        )

        if ema_diff_pct < self.chop_ema_range_pct:
            # Suppress if EMA20 is rising — gap is closing because trend is recovering,
            # not because market is oscillating flatly
            ema_rising = ema20_slope_dir == "rising"

            if ema_rising:
                # Gap is closing due to upward recovery — not chop, skip this issue
                pass
            elif adx_is_trending:
                # ADX confirms a real trend is in play — tight gap is structural, not chop
                pass
            else:
                issues.append(
                    f"60m EMAs compressed ({ema_diff_pct:.2f}% - no clear direction)"
                )

        # Check 15m compression too, but only flag "both TFs compressed" when
        # ADX is also low (confirming genuine range/chop, not a trending structure)
        if confirm_trend is not None:
            confirm_ema_diff = abs(((confirm_trend.ema20 - confirm_trend.ema50) /
                                    confirm_trend.ema50) * 100)

            if confirm_ema_diff < self.chop_ema_range_pct and ema_diff_pct < self.chop_ema_range_pct:
                if adx_is_trending:
                    # High ADX: both EMAs compressed because a trend is underway and
                    # EMAs are catching up — do NOT call this choppy
                    pass
                elif ema20_slope_dir == "rising":
                    # Rising 60m EMA20 slope: trend recovering, gap closing naturally
                    pass
                else:
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
            #Remove first check. Low volume is counting as 2 issues and will cause choppy all the time during low trade windows

            #if primary_trend.volume_ratio < self.min_volume_ratio:
                #issues.append(
                #    f"Dead volume ({primary_trend.volume_ratio:.2f}x - no conviction)"
                #)
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
        price_ema20_gap = abs((price - primary_trend.ema20) / 
                              primary_trend.ema20) * 100
        price_ema50_gap = abs((price - primary_trend.ema50) / 
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
        strategy_type: StrategyType = StrategyType.TREND_FOLLOWING
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
        match strategy_type:
            case StrategyType.RANGE_TRADING:
                if regime == MarketRegime.HIGH_RISK:
                    # Panic, volatility spike, distribution — dangerous for everyone
                    self.logger.warning(
                        f"[{profile_name}] {symbol}: RANGE BLOCKED (high risk) - {reason}"
                    )
                    return False, reason

                elif regime == MarketRegime.CHOPPY:
                    # Ideal range trading conditions — compressed EMAs, neutral RSI,
                    # price oscillating. Pass through and let confidence scorer
                    # reward this via _range_trading_confidence_score().
                    self.logger.info(
                        f"[{profile_name}] {symbol}: RANGE CHOPPY (ideal) - {reason}"
                    )
                    return True, reason

                else:  # SAFE
                    # Normal trending market — not ideal but not dangerous.
                    # Entry indicators (BB pct_b, RSI dip, VWAP) are already
                    # doing the work of finding the dip. Let them decide.
                    # Confidence scorer gives lower bonus for SAFE vs CHOPPY.
                    self.logger.info(
                        f"[{profile_name}] {symbol}: RANGE  SAFE (acceptable) - {reason}"
                    )
                    return True, reason

            case StrategyType.MEAN_REVERSION | StrategyType.SHORT_MEAN_REVERSION | StrategyType.SHORT_TREND_FOLLOWING:
                # Counter-trend strategies: chop/ranging is their habitat — only
                # HIGH_RISK (incl. sustained trend against the trade direction) blocks.
                if regime == MarketRegime.HIGH_RISK:
                    self.logger.warning(f"[{profile_name}] {symbol}: BLOCKED - {reason}")
                    return False, reason
                return True, reason  # SAFE and CHOPPY both tradeable

            case _:  # TREND_FOLLOWING — original logic unchanged
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
            MarketRegime.HIGH_RISK: [],
            MarketRegime.UNKNOWN: []
        }
        
        for symbol in symbols:
            regime, reason = self.get_regime(symbol)
            regimes[regime].append({"symbol": symbol, "reason": reason})
        
        return {
            "safe": len(regimes[MarketRegime.SAFE]),
            "choppy": len(regimes[MarketRegime.CHOPPY]),
            "high_risk": len(regimes[MarketRegime.HIGH_RISK]),
            "unknown": len(regimes[MarketRegime.UNKNOWN]),
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