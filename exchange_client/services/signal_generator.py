# services/signal_generator.py - REFACTORED: Fully YAML-driven, no duplication
from typing import Optional, List, Dict, Tuple
from decimal import Decimal
from enum import Enum
import time
from utils.logging import log_manager
from utils.constants import TradeSide, StrategyType
from cache.trend_cache import get_trend_cache
from cache.atr_cache import get_atr_cache
from cache.price_cache import get_price_cache
from models.trading_profile import TradingProfile
from models.trading_signal import TradingSignal, SignalStrength
from api_builders.trading_builder import TradingService
from cache.regime_filter import get_regime_filter
from models.signal_validation import SignalValidationResult, ValidationGroup, MarketContext, IndicatorResult

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
        self.strategy_type = getattr(profile, 'strategy_type', StrategyType.TREND_FOLLOWING)

        # Signal generation settings from profile
        self.trading_timeframe = getattr(profile, 'signal_timeframe', '15')
        self.trend_timeframe = getattr(profile, 'trend_timeframe', '60')
        
        # Entry filter settings (for multi-TF validation)
        self.use_trend_filter = getattr(profile, 'use_trend_filter', False)
        self.use_entry_filter = getattr(profile, 'use_entry_filter', False)
        self.entry_timeframe = getattr(profile, 'entry_timeframe', self.trading_timeframe)
        
        # NEW: Determine regime filter timeframes based on strategy
        if self.strategy_type == StrategyType.MEAN_REVERSION:
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
        self.trend_weight = 40.0  if self.use_trend_filter else 0.0 # Trend filter contributes 40%
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
            f"✨ Initialized SignalGenerator [{self.strategy_type.value}]: "
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
        validation = SignalValidationResult(
            timestamp=time.time(),
            symbol=symbol,
            signal_timeframe=self.trading_timeframe,
            strategy_type=self.strategy_type.value,
            order_type=TradeSide.BUY,
            score=0.0,
            score_components=0,
            market_context=MarketContext(),
            trend_validation=ValidationGroup(enabled=self.profile.use_trend_filter),
            entry_validation=ValidationGroup(enabled=self.use_entry_filter)
        )

        confidence_score = 0.0
        
        # 4. TREND FILTER (Higher Timeframe - ONLY for trend_following)
        if self.profile.use_trend_filter:
            trend_check, trend_reason, trend_indicators = self._check_trend(symbol, self.trend_timeframe)
            indicators['trend'] = trend_check

            validation.trend_validation.timeframe = self.trend_timeframe
            validation.trend_validation.passed = trend_check
            validation.trend_validation.indicators = trend_indicators
            validation.trend_validation.indicators_total = len(trend_indicators)
            validation.trend_validation.indicators_passed = sum(
                1 for ind in trend_indicators if ind.is_bullish
            )
            validation.trend_validation.summary = trend_reason

            if not trend_check:
                self.logger.debug(
                    f"{symbol}: ❌ Trend filter failed ({self.trend_timeframe}m) - {trend_reason}"
                )
                return None
            
            reasons.append(f"✅ Trend ({self.trend_timeframe}m): {trend_reason}")
            confidence_score += self.trend_weight

        else:
            reasons.append(f"✅ Trend filter not applied")
            confidence_score += self.trend_weight

        # 5. ENTRY FILTER (Execution Timeframe)
        if self.use_entry_filter:
            entry_check, entry_reason, entry_indicators = self._check_entry_filter(symbol, self.entry_timeframe)
            indicators['entry_filter'] = entry_check

            validation.entry_validation.timeframe = self.entry_timeframe
            validation.entry_validation.passed = entry_check
            validation.entry_validation.indicators = entry_indicators
            validation.entry_validation.indicators_total = len(entry_indicators)
            validation.entry_validation.indicators_passed = sum(
                1 for ind in entry_indicators if ind.is_bullish
            )
            validation.entry_validation.summary = entry_reason

            if not entry_check:
                self.logger.info(
                    f"{symbol}: ❌ Entry filter failed ({self.entry_timeframe}m) - {entry_reason}"
                )
                return None
            else:
                self.logger.info(
                    f"{symbol}: ✅ Entry filter passed ({self.entry_timeframe}m) - {entry_reason}"
                )
            
            reasons.append(f"✅ Entry ({self.entry_timeframe}m): {entry_reason}")
            confidence_score += self.entry_weight
        
        # 6. VOLUME CONFIRMATION
        volume_check, volume_reason = self._check_volume(symbol, self.trading_timeframe)
        indicators['volume'] = volume_check

        validation.market_context.volume = {
            "is_sufficient": volume_check['has_volume'],
            "ratio": float(volume_check['volume_ratio']),
            "required_ratio": self.min_volume_ratio,
            "message": f"{volume_check['volume_ratio']:.1f}x average ({self.min_volume_ratio}x required)"
        }        
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
            if atr_check['is_valid'] == False:
                validation.market_context.atr = {
                    "is_valid"   : atr_check['is_valid'],
                    "message": f"{atr_reason}"
                }        
            else: 
                validation.market_context.atr = {
                    "is_valid"   : atr_check['is_valid'],
                    "is_volatile": atr_check['is_volatile'],
                    "ratio": float(atr_check['ratio']),
                    "message": f"{atr_check['ratio']:.1f}x average ({self.profile.atr_threshold}x - {self.profile.atr_filter_mode})"
                }        

            if not atr_check['is_valid']:
                self.logger.debug(f"{symbol}: ❌ ATR check failed - {atr_reason}")
                #return None
            
            reasons.append(f"✅ ATR: {atr_reason}")
        
        # 8. NOT OVERBOUGHT (safety check - different for each strategy)
        if self.strategy_type in (StrategyType.TREND_FOLLOWING, StrategyType.RANGE_TRADING):
            overbought_check, ob_reason = self._check_not_overbought(symbol, self.trading_timeframe)
            indicators['overbought'] = overbought_check
            ob_check = IndicatorResult(
                type="rsi_overbought",
                is_bullish=overbought_check['is_valid'],
                config={"threshold": 70},
                values={"rsi": float(overbought_check['rsi'])},
                message=f"RSI {overbought_check['rsi']:.0f} {'not overbought' if overbought_check['is_valid'] else 'overbought'}"
            )
            validation.additional_checks.append(ob_check)

            if not overbought_check['is_valid']:
                reasons.append(f"⚠️  RSI: {ob_reason}")
                # If over 80, penalise
                if overbought_check['rsi'] > 80:
                    confidence_score += -30
                else:
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
        if self.strategy_type == StrategyType.MEAN_REVERSION:
            # Mean reversion has different confidence factors
            confidence_pct = self._mean_reversion_confidence_score(
                symbol, 
                self.entry_timeframe,
                base_score=confidence_score,
                max_score=self.max_confidence
            )
        elif self.strategy_type == StrategyType.RANGE_TRADING:
            confidence_pct = self._range_trading_confidence_score(
                symbol,
                self.entry_timeframe,
                trend_timeframe=self.trend_timeframe,
                base_score=confidence_score,
                max_score=self.max_confidence
            )
        else:
            # Trend following uses standard normalization
            confidence_pct = (confidence_score / self.max_confidence) * 100

        validation.score = confidence_pct
        validation.score_components = 3  # trend, entry, volume

        # Check minimum confidence threshold
        if confidence_pct < self.min_confidence:
            self.logger.debug(
                f"{symbol}: ❌ Confidence too low: {confidence_pct:.1f}% < {self.min_confidence}%"
            )
            return None
        
        # Build human-readable summary
        parts = []
        if validation.trend_validation.enabled:
            icon = "✅" if validation.trend_validation.passed else "❌"
            parts.append(f"{icon} Trend ({validation.trend_validation.timeframe}m): "
                        f"{validation.trend_validation.indicators_passed}/{validation.trend_validation.indicators_total}")
        if validation.entry_validation.enabled:
            icon = "✅" if validation.entry_validation.passed else "❌"
            parts.append(f"{icon} Entry ({validation.entry_validation.timeframe}m): "
                        f"{validation.entry_validation.indicators_passed}/{validation.entry_validation.indicators_total}")
        parts.append(f"Vol: {volume_check['volume_ratio']:.1f}x")
        parts.append(f"Score: {confidence_pct:.1f}%")
        
        validation.human_readable = " | ".join(parts)
        validation.overall_passed = True
         
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
            action=TradeSide.BUY,
            strength=strength,
            confidence=confidence_pct,
            timeframe=self.trading_timeframe,
            trend_timeframe=self.trend_timeframe,
            indicators=indicators,
            timestamp=time.time(),
            reasons=reasons,
            validation_details=validation.to_json(),
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
            return True, "Trend filter disabled"
        
        indicators_config = getattr(self.profile, 'trend_indicators', None)
        min_required = getattr(self.profile, 'min_indicators_required', 2)

        is_bullish, reason, indicator_results = self.trend_cache.is_bullish(
            symbol=symbol,
            timeframe=timeframe,
            indicators_config=indicators_config,
            min_indicators_required=min_required,
            return_structured=True
        )

        return is_bullish, reason, indicator_results

    def _check_entry_filter(self, symbol: str, timeframe: str) -> Tuple[dict, str]:
        """Check entry conditions using YAML-configured entry_indicators"""
        indicators_config = getattr(self.profile, 'entry_indicators', None)
        min_required = getattr(self.profile, 'min_entry_indicators_required', 2)
        
        if indicators_config is None:
            # No entry filter configured - pass
            return True, "No entry filter configured"
        
        is_bullish, reason, indicator_results = self.trend_cache.is_bullish(
            symbol=symbol,
            timeframe=timeframe,
            indicators_config=indicators_config,
            min_indicators_required=min_required,
            return_structured=True
        )
        
        return is_bullish, reason, indicator_results

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
        if rsi < 65:
            return {"is_valid": True, "rsi": float(rsi)}, f"RSI {rsi:.0f} not overbought"
        elif rsi < 70:
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

    def _range_trading_confidence_score(
        self,
        symbol: str,
        timeframe: str,
        trend_timeframe: str,
        base_score: float,
        max_score: float
    ) -> float:
        """
        Calculate confidence for range/oscillation trading setups.

        Range trading is the INVERSE of trend following — we WANT:
        - Flat, compressed EMAs (no directional bias)
        - RSI cycling in the mid-band (40–60), not trending
        - Price near the lower portion of the range (VWAP / EMA proximity)
        - Low-to-moderate ATR (contained volatility, range intact)
        - RSI just starting to turn up from a dip (timing the bounce)

        Bonus factors (max +20 points total):
        1. 60m EMA compression     — flat HTF confirms we're ranging   (+5)
        2. RSI mid-band position   — not trending, cycling              (+5)
        3. RSI momentum turn       — dipping then turning up            (+5)
        4. VWAP proximity          — price near but below VWAP          (+3)
        5. Low ATR                 — range is intact, not breaking      (+2)

        Args:
            symbol:           Trading symbol
            timeframe:        Entry timeframe (15m)
            trend_timeframe:  Higher timeframe used for range confirmation (60m)
            base_score:       Points accumulated from indicator pass/fail checks
            max_score:        Maximum points possible from those checks

        Returns:
            Confidence percentage (0–100)
        """
        entry_trend = self.trend_cache.get(symbol, timeframe)
        htf_trend = self.trend_cache.get(symbol, trend_timeframe)

        # If we have no data at all, fall back to base score normalisation
        if entry_trend is None:
            return (base_score / max_score) * 100

        bonus_points = 0.0
        max_bonus = 20.0

        # ------------------------------------------------------------------
        # FACTOR 1: 60m EMA Compression (+5 points)
        # Tight EMA spread on the higher timeframe means no trend is forming.
        # The tighter the spread, the more confident we are in the range.
        # ------------------------------------------------------------------
        if htf_trend is not None:
            ema_diff_pct = abs(
                ((htf_trend.ema20 - htf_trend.ema50) / htf_trend.ema50) * 100
            )
            if ema_diff_pct < 0.1:
                bonus_points += 5.0   # Very tight — strong range confirmation
            elif ema_diff_pct < 0.25:
                bonus_points += 4.0   # Tight
            elif ema_diff_pct < 0.5:
                bonus_points += 2.5   # Moderate compression
            elif ema_diff_pct < 0.8:
                bonus_points += 1.0   # Slight compression — range may be early/late
            # > 0.8% spread = trending, no bonus (trend followers would catch this)

            self.logger.debug(
                f"{symbol} Range Score | "
                f"60m EMA spread: {ema_diff_pct:.3f}% → bonus +{bonus_points:.1f}"
            )

        # ------------------------------------------------------------------
        # FACTOR 2: RSI Mid-Band Position (+5 points)
        # We want RSI cycling in the 40–60 zone on the entry TF.
        # Entering when RSI has dipped toward the lower half (40–50) gives the
        # best risk/reward for a bounce back to the midpoint.
        # ------------------------------------------------------------------
        rsi = entry_trend.rsi
        rsi_bonus = 0.0

        if 42 <= rsi <= 50:
            rsi_bonus = 5.0   # Sweet spot: dipped low in range, primed to bounce
        elif 50 < rsi <= 55:
            rsi_bonus = 3.0   # Acceptable — mid-range, can still bounce to VWAP
        elif 38 <= rsi < 42:
            rsi_bonus = 2.0   # Getting deeper — valid but approaching MR territory
        elif 55 < rsi <= 60:
            rsi_bonus = 1.0   # Too close to range top — lower confidence entry
        # RSI < 38 or > 60: no bonus — either too oversold or too close to top

        bonus_points += rsi_bonus
        self.logger.debug(
            f"{symbol} Range Score | "
            f"15m RSI: {rsi:.1f} → bonus +{rsi_bonus:.1f}"
        )

        # ------------------------------------------------------------------
        # FACTOR 3: RSI Momentum Turn (+5 points)
        # We want RSI to have recently dipped and now be turning back up.
        # This confirms we're catching the bounce, not a continuing decline.
        # ------------------------------------------------------------------
        rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
            symbol, timeframe, lookback=2
        )

        momentum_bonus = 0.0
        if rsi_momentum is not None and rsi_direction == "increasing":
            if rsi_momentum >= 3.0:
                momentum_bonus = 5.0   # Strong turn — high conviction
            elif rsi_momentum >= 2.0:
                momentum_bonus = 4.0   # Good turn
            elif rsi_momentum >= 1.0:
                momentum_bonus = 3.0   # Moderate — turning but gently
            elif rsi_momentum >= 0.5:
                momentum_bonus = 1.5   # Early signs — lower confidence
        elif rsi_direction == "stable":
            momentum_bonus = 1.0       # Flat is ok — not falling further

        bonus_points += momentum_bonus
        self.logger.debug(
            f"{symbol} Range Score | "
            f"RSI momentum: {rsi_momentum:+.1f} ({rsi_direction}) → bonus +{momentum_bonus:.1f}"
        )

        # ------------------------------------------------------------------
        # FACTOR 4: VWAP Proximity (+3 points)
        # On a range day VWAP acts as the midpoint / fair value.
        # We want price slightly below VWAP (buying discount toward fair value),
        # but not so far below that it's a trending/breakdown move.
        # ------------------------------------------------------------------
        vwap_bonus = 0.0
        if entry_trend.vwap and entry_trend.vwap > 0:
            vwap_gap_pct = ((entry_trend.price - entry_trend.vwap) / entry_trend.vwap) * 100

            if -0.5 <= vwap_gap_pct < -0.05:
                vwap_bonus = 3.0   # Just below VWAP — ideal range dip entry
            elif -1.0 <= vwap_gap_pct < -0.5:
                vwap_bonus = 2.0   # Slightly more extended — still valid
            elif vwap_gap_pct >= -0.05:
                vwap_bonus = 1.0   # At or just above VWAP — tight but acceptable
            # < -1.0%: no bonus — too extended for a range play, MR profile is better

            bonus_points += vwap_bonus
            self.logger.debug(
                f"{symbol} Range Score | "
                f"VWAP gap: {vwap_gap_pct:+.2f}% → bonus +{vwap_bonus:.1f}"
            )

        # ------------------------------------------------------------------
        # FACTOR 5: ATR Containment (+2 points)
        # Low ATR means the range is intact. If ATR is spiking, the range is
        # likely breaking and we should have less confidence.
        # Note: ATR filter in the profile will hard-block if ratio > threshold,
        # but here we reward for being well within that limit.
        # ------------------------------------------------------------------
        atr_bonus = 0.0
        atr_data = self.atr_cache.get(symbol, self.profile.atr_timeframe
                                    if hasattr(self.profile, 'atr_timeframe') else timeframe)
        if atr_data is not None:
            atr_ratio = float(atr_data.get_ratio())
            if atr_ratio < 0.8:
                atr_bonus = 2.0   # Very low volatility — strong range containment
            elif atr_ratio < 1.0:
                atr_bonus = 1.5   # Below average — range solid
            elif atr_ratio < 1.2:
                atr_bonus = 0.5   # Slightly elevated — range may be testing edges

            bonus_points += atr_bonus
            self.logger.debug(
                f"{symbol} Range Score | "
                f"ATR ratio: {atr_ratio:.2f}x → bonus +{atr_bonus:.1f}"
            )

        # ------------------------------------------------------------------
        # Final calculation
        # ------------------------------------------------------------------
        bonus_points = min(bonus_points, max_bonus)
        total_score = base_score + bonus_points
        confidence_pct = (total_score / (max_score + max_bonus)) * 100

        self.logger.debug(
            f"{symbol} Range Trading Confidence: "
            f"Base {base_score:.1f} + Bonus {bonus_points:.1f} = "
            f"{total_score:.1f}/{max_score + max_bonus:.1f} = {confidence_pct:.1f}% "
            f"(RSI:{rsi:.1f}, "
            f"VWAP:{vwap_gap_pct:+.2f}% " if (entry_trend.vwap and entry_trend.vwap > 0) else
            f"(RSI:{rsi:.1f}, VWAP:N/A "
            f"Momentum:{rsi_momentum:+.1f} [{rsi_direction}])"
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