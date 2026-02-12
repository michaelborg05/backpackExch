# services/signal_generator.py - REFACTORED: Fully YAML-driven, no duplication
from typing import Optional, List, Dict, Tuple
from decimal import Decimal
from enum import Enum
import time
from utils.logging import log_manager
from cache.trend_cache import get_trend_cache
from cache.atr_cache import get_atr_cache
from cache.price_cache import get_price_cache
from models.trading_profile import TradingProfile
from models.trading_signal import TradingSignal, SignalStrength
from api_builders.trading_builder import TradingService
from cache.regime_filter import get_regime_filter

class SignalGenerator:
    """
    REFACTORED: Fully YAML-driven signal generation with zero hardcoded logic
    
    Philosophy:
    - Multi-timeframe analysis (trend on higher TF, entry on execution TF)
    - ALL validation logic configured via profile YAML
    - No hardcoded indicator checks - everything in trend_cache.is_bullish()
    - Cleaner, shorter, easier to maintain
    
    Changes from original:
    - ❌ REMOVED: _check_entry_conditions() - 300 lines of hardcoded logic
    - ✅ SIMPLIFIED: All checks now via trend_filter and entry_filter
    - ✅ CONSOLIDATED: Single scoring model (no hybrid)
    - ✅ CLEANER: ~200 lines vs ~500 lines
    CHANGES added 11th Feb 2026
    1. Added strategy_type detection and regime timeframe logic (lines 40-60)
    2. Added mean_reversion_confidence_score() method (lines 460-550)
    3. Modified confidence scoring to call appropriate method (lines 246-260)
    4. Updated logging to include strategy type (line 82)
"""
    
    def __init__(self, profile: TradingProfile):
        self.profile = profile
        self.logger = log_manager.get_logger(f"SignalGenerator[{profile.name}]")
        self.trend_cache = get_trend_cache()
        self.atr_cache = get_atr_cache()
        self.price_cache = get_price_cache()
        self.regime_filter = get_regime_filter()

        # NEW: Strategy type detection
        self.strategy_type = getattr(profile, 'strategy_type', 'trend_following')

        # Signal generation settings from profile
        self.trading_timeframe = getattr(profile, 'signal_timeframe', '15')
        self.trend_timeframe = getattr(profile, 'trend_timeframe', '60')
        
        # Entry filter settings (for multi-TF validation)
        self.use_entry_filter = getattr(profile, 'use_entry_filter', False)
        self.entry_timeframe = getattr(profile, 'entry_timeframe', self.trading_timeframe)
        
        # NEW: Determine regime filter timeframes based on strategy
        if self.strategy_type == "mean_reversion":
            # Mean reversion: regime checks execution timeframe (where entry logic lives)
            self.regime_primary_tf = self.entry_timeframe    # 15m
            self.regime_confirm_tf = self.entry_timeframe    # 15m
        else:
            # Trend following: regime checks higher TF + lower TF
            self.regime_primary_tf = self.trend_timeframe    # 60m
            self.regime_confirm_tf = self.entry_timeframe    # 15m
        
        # Thresholds
        self.min_volume_ratio = getattr(profile, 'min_volume_ratio', 1.5)
        self.min_confidence = getattr(profile, 'min_signal_confidence', 70.0)
        
        # Calculate max confidence based on enabled features
        # This ensures confidence scores are properly normalized
        self.base_confidence = 100.0
        self.trend_weight = 40.0  # Trend filter contributes 40%
        self.entry_weight = 35.0 if self.use_entry_filter else 0.0  # Entry filter 35%
        self.volume_weight = 15.0  # Volume contributes 15%
        self.safety_weight = 10.0  # Not overbought check 10%
        self.max_confidence = (
            self.trend_weight + 
            self.entry_weight + 
            self.volume_weight + 
            self.safety_weight
        )
        
        log_msg = (
            f"✨ Initialized SignalGenerator [{self.strategy_type}]: "
            f"trading_tf={self.trading_timeframe}m, "
            f"trend_tf={self.trend_timeframe}m"
        )
        
        if self.use_entry_filter:
            log_msg += f", entry_filter=ON (entry_tf={self.entry_timeframe}m)"
        else:
            log_msg += f", entry_filter=OFF (single-TF mode)"
        
        log_msg += (
            f", regime_tf={self.regime_primary_tf}m, "
            f"min_volume={self.min_volume_ratio}x, "
            f"min_confidence={self.min_confidence}%"
        )
        
        self.logger.info(log_msg)
    
    def generate_signal(self, symbol: str) -> Optional[TradingSignal]:
        """
        Generate trading signal for a symbol
        
        Validation Pipeline:
        1. Balance check
        2. Regime filter (with correct timeframes for strategy)
        3. Re-entry check
        4. Trend filter (higher TF) - ONLY for trend_following
        5. Entry filter (execution TF) - uses strategy-specific indicators
        6. Volume confirmation
        7. ATR check (optional)
        8. Not overbought (safety check)
        
        Returns:
            TradingSignal or None if no signal
        """
        
        # Create trading service
        trading = TradingService(self.profile)

        # 1. BALANCE CHECK
        is_valid, balance_error = trading.validate_balance_for_trade(
            sale_action="BUY", 
            symbol=symbol
        )
        
        if not is_valid:
            # Skip this profile - balance unusable
            self.logger.warning(
                f"[{self.profile.name}] Skipping {symbol}: {balance_error}"
            )
            return None

        # 2. REGIME FILTER (NEW: Pass correct timeframes for strategy)
        if self.profile.use_market_regime_filter:
            can_trade, regime_reason = self.regime_filter.can_trade(
                symbol=symbol,
                profile_name=self.profile.name,
                primary_timeframe=self.regime_primary_tf,   
                confirm_timeframe=self.regime_confirm_tf,   
                strategy_type=self.strategy_type
            )

            if not can_trade:
                self.logger.debug(
                    f"{symbol}: Market regime blocked - {regime_reason}"
                )
                return None
        else:
            self.logger.debug(
                f"{symbol}: Market regime filter not applied"
            )
            regime_reason = "Regime filter disabled"

        # 3. RE-ENTRY CHECK
        from services.reentry_manager import get_reentry_manager
    
        reentry_mgr = get_reentry_manager()
        trend = self.trend_cache.get(symbol, self.trading_timeframe)

        if trend:
            can_enter, reentry_reason = reentry_mgr.can_reenter(
                symbol=symbol,
                profile_name=self.profile.name,
                timeframe=self.trading_timeframe,
                current_trend=trend
            )
            
            if not can_enter:
                self.logger.debug(
                    f"{symbol}: Re-entry blocked - {reentry_reason}"
                )
                return None
            else:
                self.logger.debug(
                    f"{symbol}: Re-entry OK - {reentry_reason}"
                )
                        
        # Initialize scoring
        reasons = []
        indicators = {}
        confidence_score = 0.0
        
        # 4. TREND FILTER (Higher Timeframe - ONLY for trend_following)
        if self.profile.use_trend_filter:
            trend_check, trend_reason = self._check_trend(symbol, self.trend_timeframe)
            indicators['trend'] = trend_check
            
            if not trend_check['is_bullish']:
                self.logger.debug(
                    f"{symbol}: ❌ Trend filter failed ({self.trend_timeframe}m) - {trend_reason}"
                )
                return None
            
            reasons.append(f"✅ Trend ({self.trend_timeframe}m): {trend_reason}")
            confidence_score += self.trend_weight
        elif self.strategy_type == "trend_following":
            reasons.append(f"✅ Trend filter not applied")
            confidence_score += self.trend_weight

        # 5. ENTRY FILTER (Execution Timeframe)
        if self.use_entry_filter:
            entry_check, entry_reason = self._check_entry_filter(symbol, self.entry_timeframe)
            indicators['entry_filter'] = entry_check
            
            if not entry_check['is_bullish']:
                self.logger.debug(
                    f"{symbol}: ❌ Entry filter failed ({self.entry_timeframe}m) - {entry_reason}"
                )
                return None
            
            reasons.append(f"✅ Entry ({self.entry_timeframe}m): {entry_reason}")
            confidence_score += self.entry_weight
        
        # 6. VOLUME CONFIRMATION
        volume_check, volume_reason = self._check_volume(symbol, self.trading_timeframe)
        indicators['volume'] = volume_check
        
        if volume_check['has_volume']:
            reasons.append(f"✅ Volume: {volume_reason}")
            confidence_score += self.volume_weight
        else:
            reasons.append(f"⚠️  Volume: {volume_reason}")
            confidence_score += self.volume_weight * 0.3
        
        # 7. ATR/VOLATILITY CHECK (optional)
        if self.profile.use_atr_filter:
            atr_check, atr_reason = self._check_atr(symbol)
            indicators['atr'] = atr_check
            
            if not atr_check['is_valid']:
                self.logger.debug(f"{symbol}: ❌ ATR check failed - {atr_reason}")
                return None
            
            reasons.append(f"✅ ATR: {atr_reason}")
        
        # 8. NOT OVERBOUGHT (safety check - different for each strategy)
        if self.strategy_type == "trend_following":
            overbought_check, ob_reason = self._check_not_overbought(symbol, self.trading_timeframe)
            indicators['overbought'] = overbought_check
            
            if not overbought_check['is_valid']:
                reasons.append(f"⚠️  RSI: {ob_reason}")
                confidence_score += self.safety_weight * 0.3
            else:
                reasons.append(f"✅ RSI: {ob_reason}")
                confidence_score += self.safety_weight
        else:
            # Mean reversion doesn't need overbought check (wants oversold)
            # But entry indicators already check rsi_oversold, so we skip this
            reasons.append(f"✅ RSI: Mean reversion (oversold check in entry)")
            confidence_score += self.safety_weight
        
        # NEW: Calculate confidence based on strategy type
        if self.strategy_type == "mean_reversion":
            # Mean reversion has different confidence factors
            confidence_pct = self._mean_reversion_confidence_score(
                symbol, 
                self.entry_timeframe,
                base_score=confidence_score,
                max_score=self.max_confidence
            )
        else:
            # Trend following uses standard normalization
            confidence_pct = (confidence_score / self.max_confidence) * 100
        
        # Check minimum confidence threshold
        if confidence_pct < self.min_confidence:
            self.logger.debug(
                f"{symbol}: ❌ Confidence too low: {confidence_pct:.1f}% < {self.min_confidence}%"
            )
            return None
        
        # Determine signal strength
        if confidence_pct >= 85:
            strength = SignalStrength.STRONG
        elif confidence_pct >= 75:
            strength = SignalStrength.MEDIUM
        else:
            strength = SignalStrength.WEAK

        reasons.append(f"Score {confidence_pct:.1f}% ({strength.value})")

        # Get current price
        current_price = self.price_cache.get_price(symbol)
        if current_price is None or current_price <= 0:
            self.logger.warning(f"{symbol}: No valid price data")
            return None
        
        # Create signal
        signal = TradingSignal(
            symbol=symbol,
            action="BUY",
            strength=strength,
            confidence=confidence_pct,
            timeframe=self.trading_timeframe,
            trend_timeframe=self.trend_timeframe,
            indicators=indicators,
            timestamp=time.time(),
            reasons=reasons,
            regime_confidence=regime_reason
        )

        self.logger.info(
            f"🎯 SIGNAL GENERATED [{self.strategy_type}]: {symbol} | "
            f"Strength: {strength.value} | "
            f"Confidence: {confidence_pct:.1f}%"
        )
        
        return signal
    
    def _check_trend(self, symbol: str, timeframe: str) -> Tuple[dict, str]:
        """Check trend conditions using YAML-configured trend_indicators"""
        if not self.profile.use_trend_filter:
            return {"is_bullish": True}, "Trend filter disabled"
        
        indicators_config = getattr(self.profile, 'trend_indicators', None)
        min_required = getattr(self.profile, 'min_indicators_required', 2)

        is_bullish, reason = self.trend_cache.is_bullish(
            symbol=symbol,
            timeframe=timeframe,
            indicators_config=indicators_config,
            min_indicators_required=min_required
        )
        
        return {"is_bullish": is_bullish}, reason
    
    def _check_entry_filter(self, symbol: str, timeframe: str) -> Tuple[dict, str]:
        """Check entry conditions using YAML-configured entry_indicators"""
        indicators_config = getattr(self.profile, 'entry_indicators', None)
        min_required = getattr(self.profile, 'min_entry_indicators_required', 2)
        
        if indicators_config is None:
            # No entry filter configured - pass
            return {"is_bullish": True}, "No entry filter configured"
        
        is_bullish, reason = self.trend_cache.is_bullish(
            symbol=symbol,
            timeframe=timeframe,
            indicators_config=indicators_config,
            min_indicators_required=min_required
        )
        
        return {"is_bullish": is_bullish}, reason

    def _check_volume(self, symbol: str, timeframe: str) -> Tuple[dict, str]:
        """Check volume confirmation"""
        trend = self.trend_cache.get(symbol, timeframe)
        
        if trend is None or trend.volume_ratio is None:
            return {
                "has_volume": False,
                "volume_ratio": None
            }, "No volume data"
        
        volume_ratio = trend.volume_ratio
        
        if volume_ratio >= self.min_volume_ratio:
            return {
                "has_volume": True,
                "volume_ratio": float(volume_ratio)
            }, f"{volume_ratio:.1f}x average ({self.min_volume_ratio}x required)"
        else:
            # If volume is less than 50% of the minimum required
            if volume_ratio < self.min_volume_ratio * 0.5:
                return {
                    "has_volume": False,
                    "volume_ratio": float(volume_ratio)
                }, f"Only {volume_ratio:.1f} - Less than half of minimum (need {self.min_volume_ratio}x)"
            else:
                return {
                    "has_volume": False,
                    "volume_ratio": float(volume_ratio)
                }, f"Only {volume_ratio:.1f}x average (need {self.min_volume_ratio}x)"
    
    def _check_atr(self, symbol: str) -> Tuple[dict, str]:
        """Check ATR/volatility conditions"""
        atr_data = self.atr_cache.get(symbol, self.profile.atr_timeframe)
        
        if atr_data is None:
            return {"is_valid": False}, f"No ATR data"
        
        is_volatile, reason = self.atr_cache.is_volatile(
            symbol=symbol,
            timeframe=self.profile.atr_timeframe,
            threshold=self.profile.atr_threshold
        )
        
        # Check filter mode
        if self.profile.atr_filter_mode == "require_high":
            is_valid = is_volatile
        elif self.profile.atr_filter_mode == "require_low":
            is_valid = not is_volatile
        else:
            is_valid = True
        
        return {
            "is_valid": is_valid,
            "is_volatile": is_volatile,
            "ratio": float(atr_data.get_ratio())
        }, reason
    
    def _check_not_overbought(self, symbol: str, timeframe: str) -> Tuple[dict, str]:
        """Ensure we're not buying into overbought conditions (trend following only)"""
        trend = self.trend_cache.get(symbol, timeframe)
        
        if trend is None:
            return {"is_valid": False}, "No RSI data"
        
        rsi = trend.rsi
        
        # RSI thresholds
        if rsi < 70:
            return {"is_valid": True, "rsi": float(rsi)}, f"RSI {rsi:.0f} not overbought"
        elif rsi < 75:
            return {"is_valid": False, "rsi": float(rsi)}, f"RSI {rsi:.0f} getting overbought"
        else:
            return {"is_valid": False, "rsi": float(rsi)}, f"RSI {rsi:.0f} overbought"
    
    def _mean_reversion_confidence_score(
        self, 
        symbol: str, 
        timeframe: str,
        base_score: float,
        max_score: float
    ) -> float:
        """
        Calculate mean reversion confidence based on oversold depth and setup quality
        
        Mean reversion confidence factors:
        1. RSI oversold depth (deeper = higher confidence)
        2. Volume spike magnitude (bigger = higher confidence)  
        3. Price extension below VWAP (further = higher confidence)
        4. Price extension below EMA20 (further = higher confidence)
        5. RSI momentum turning (stronger reversal = higher confidence)
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe to check (15m for mean reversion)
            base_score: Base confidence from entry indicators passing
            max_score: Maximum possible score
            
        Returns:
            Confidence percentage (0-100)
        """
        trend = self.trend_cache.get(symbol, timeframe)
        if trend is None:
            return (base_score / max_score) * 100
        
        # Start with base score from passing indicators
        bonus_points = 0.0
        max_bonus = 25.0  # Can add up to 25 points beyond base
        
        # FACTOR 1: RSI Oversold Depth (max +10 points)
        # Deeper oversold = higher probability of bounce
        rsi = trend.rsi
        if rsi < 20:
            bonus_points += 10.0  # Extreme oversold
        elif rsi < 25:
            bonus_points += 8.0   # Very oversold
        elif rsi < 30:
            bonus_points += 6.0   # Oversold
        elif rsi < 35:
            bonus_points += 4.0   # Slightly oversold
        
        # FACTOR 2: Volume Spike Magnitude (max +8 points)
        # Higher volume = more conviction in selling climax
        if trend.volume_ratio is not None:
            if trend.volume_ratio >= 3.0:
                bonus_points += 8.0   # Major volume spike
            elif trend.volume_ratio >= 2.5:
                bonus_points += 6.0   # Strong volume
            elif trend.volume_ratio >= 2.0:
                bonus_points += 4.0   # Good volume
            elif trend.volume_ratio >= 1.5:
                bonus_points += 2.0   # Decent volume
        
        # FACTOR 3: Price Extension Below VWAP (max +5 points)
        # Further below VWAP = more stretched = higher bounce potential
        vwap_gap_pct = ((trend.price - trend.vwap) / trend.vwap) * 100
        if vwap_gap_pct < -4.0:
            bonus_points += 5.0   # Very extended
        elif vwap_gap_pct < -3.0:
            bonus_points += 4.0   # Extended
        elif vwap_gap_pct < -2.0:
            bonus_points += 3.0   # Moderate
        elif vwap_gap_pct < -1.0:
            bonus_points += 1.5   # Slight
        
        # FACTOR 4: Price Extension Below EMA20 (max +4 points)
        ema20_gap_pct = ((trend.price - trend.ema20) / trend.ema20) * 100
        if ema20_gap_pct < -5.0:
            bonus_points += 4.0   # Very extended
        elif ema20_gap_pct < -3.0:
            bonus_points += 3.0   # Extended
        elif ema20_gap_pct < -2.0:
            bonus_points += 2.0   # Moderate
        elif ema20_gap_pct < -1.0:
            bonus_points += 1.0   # Slight
        
        # FACTOR 5: RSI Momentum Turning (max +5 points)
        # Strong upward reversal = higher confidence
        rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
            symbol, timeframe
        )
        
        if rsi_momentum is not None and rsi_direction == "increasing":
            if rsi_momentum >= 5.0:
                bonus_points += 5.0   # Strong reversal
            elif rsi_momentum >= 3.0:
                bonus_points += 4.0   # Good reversal
            elif rsi_momentum >= 2.0:
                bonus_points += 3.0   # Moderate reversal
            elif rsi_momentum >= 1.0:
                bonus_points += 2.0   # Slight reversal
        
        # Cap bonus at max_bonus
        bonus_points = min(bonus_points, max_bonus)
        
        # Calculate final confidence
        total_score = base_score + bonus_points
        confidence_pct = (total_score / (max_score + max_bonus)) * 100
        
        # Log the breakdown for debugging
        self.logger.debug(
            f"{symbol} Mean Reversion Confidence: "
            f"Base {base_score:.1f} + Bonus {bonus_points:.1f} = "
            f"{total_score:.1f}/{max_score + max_bonus:.1f} = {confidence_pct:.1f}% "
            f"(RSI:{rsi:.1f}, Vol:{trend.volume_ratio:.1f}x, "
            f"VWAP:{vwap_gap_pct:+.1f}%, EMA20:{ema20_gap_pct:+.1f}%)"
        )
        
        return confidence_pct
    
    def scan_symbols(self, symbols: List[str]) -> List[TradingSignal]:
        """
        Scan multiple symbols for signals
        
        Returns:
            List of signals sorted by confidence (highest first)
        """
        signals = []
        
        for symbol in symbols:
            try:
                signal = self.generate_signal(symbol)
                if signal:
                    signals.append(signal)
            except Exception as e:
                self.logger.error(
                    f"❌ Error generating signal for {symbol}: {e}", 
                    exc_info=True
                )
        
        # Sort by confidence (highest first)
        signals.sort(key=lambda s: s.confidence, reverse=True)
        
        if signals:
            self.logger.info(
                f"✅ Scan complete: {len(signals)} signal(s) found from {len(symbols)} symbols"
            )
        else:
            self.logger.debug(
                f"No signals found from {len(symbols)} symbols"
            )
        
        return signals


# Global instances per profile
_signal_generators: Dict[str, SignalGenerator] = {}


def get_signal_generator(profile: TradingProfile) -> SignalGenerator:
    """Get or create signal generator for a profile"""
    global _signal_generators
    
    if profile.name not in _signal_generators:
        _signal_generators[profile.name] = SignalGenerator(profile)
    
    return _signal_generators[profile.name]


def get_all_signal_generators() -> Dict[str, SignalGenerator]:
    """Get all signal generators"""
    return _signal_generators.copy()