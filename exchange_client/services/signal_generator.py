# services/signal_generator.py - Fully configurable via YAML
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
    Generates trading signals based on fully configurable indicators from YAML
    
    Philosophy:
    - Multiple timeframe analysis (trend on higher TF, entry on lower TF)
    - All validation logic configured via profile YAML
    - Support for new indicators: price_vs_ema, ema_slope, rsi_range, etc.
    - Separate trend_indicators and entry_indicators for multi-TF strategy
    """
    
    def __init__(self, profile: TradingProfile):
        self.profile = profile
        self.logger = log_manager.get_logger(f"SignalGenerator[{profile.name}]")
        self.trend_cache = get_trend_cache()
        self.atr_cache = get_atr_cache()
        self.price_cache = get_price_cache()
        self.regime_filter = get_regime_filter()

        # Signal generation settings from profile
        self.trading_timeframe = getattr(profile, 'signal_timeframe', '15')
        self.trend_timeframe = getattr(profile, 'trend_timeframe', '60')  # Higher TF for trend
        
        # NEW: Entry filter settings (for multi-TF validation)
        self.use_entry_filter = getattr(profile, 'use_entry_filter', False)
        self.entry_timeframe = getattr(profile, 'entry_timeframe', self.trading_timeframe)
        
        # Thresholds
        self.min_volume_ratio = getattr(profile, 'min_volume_ratio', 1.5)
        self.min_confidence = getattr(profile, 'min_signal_confidence', 70.0)
        
        log_msg = (
            f"Initialized SignalGenerator: "
            f"trading_tf={self.trading_timeframe}, "
            f"trend_tf={self.trend_timeframe}"
        )
        
        if self.use_entry_filter:
            log_msg += f", entry_filter=ON (entry_tf={self.entry_timeframe})"
        
        log_msg += f", min_volume={self.min_volume_ratio}x, min_confidence={self.min_confidence}%"
        
        self.logger.info(log_msg)
    
    def generate_signal(self, symbol: str) -> Optional[TradingSignal]:
        """
        Generate trading signal for a symbol
        
        Signal Logic (all configurable via YAML):
        1. ✅ Balance check
        2. ✅ Regime filter (optional)
        3. ✅ Re-entry check
        4. ✅ Trend filter (higher TF) - uses trend_indicators from YAML
        5. ✅ Entry filter (execution TF) - uses entry_indicators from YAML (NEW)
        6. ✅ Volume confirmation
        7. ✅ ATR check (optional)
        8. ✅ Not overbought
        
        Returns:
            TradingSignal or None if no signal
        """
        
        # Create trading service
        trading = TradingService(self.profile)

        # 1. Check if balance is available
        is_valid, balance_error = trading.validate_balance_for_trade(
            sale_action="BUY", 
            symbol=symbol,
            profile_name=self.profile.name
        )
        
        if not is_valid:
            # Skip this profile - balance unusable
            self.logger.warning(
                f"[{self.profile.name}] Skipping trade: {balance_error}"
            )
            return None

        # 2. Regime filter check (optional)
        if self.profile.use_market_regime_filter:
            can_trade, regime_reason = self.regime_filter.can_trade(
                symbol=symbol,
                profile_name=self.profile.name,
                primary_timeframe=self.trend_timeframe,
                confirm_timeframe=self.trading_timeframe
            )
            
            if not can_trade:
                self.logger.debug(
                    f"{symbol}: Market regime check failed - {regime_reason}"
                )
                return None

        # 3. Re-entry check
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
                # Log successful re-entry clearance at debug level
                self.logger.debug(
                    f"{symbol}: Re-entry OK - {reentry_reason}"
                )
                        
        reasons = []
        indicators = {}
        confidence_score = 0.0
        max_confidence = 100.0
        
        # 4. TREND FILTER (Higher Timeframe - e.g., 4h for 1h trading)
        # Uses trend_indicators from YAML
        trend_check, trend_reason = self._check_trend(symbol, self.trend_timeframe)
        indicators['trend'] = trend_check
        
        if not trend_check['is_bullish']:
            self.logger.debug(f"{symbol}: Trend check failed - {trend_reason}")
            return None  # HARD STOP - trend must be bullish
        
        reasons.append(f"✅ Trend ({self.trend_timeframe}m): {trend_reason}")
        confidence_score += 30.0
        
        # 5. ENTRY FILTER (Execution Timeframe - e.g., 1h)
        # Uses entry_indicators from YAML (NEW)
        if self.use_entry_filter:
            entry_check, entry_reason = self._check_entry_filter(symbol, self.entry_timeframe)
            indicators['entry_filter'] = entry_check
            
            if not entry_check['is_bullish']:
                self.logger.debug(f"{symbol}: Entry filter failed - {entry_reason}")
                return None  # HARD STOP
            
            reasons.append(f"✅ Entry ({self.entry_timeframe}m): {entry_reason}")
            confidence_score += 20.0
            max_confidence += 20.0  # Adjust max since we added a check
        
        # 6. ENTRY CONDITIONS (Trading Timeframe)
        # This is the scoring-based check (60/100 points required)
        entry_check, entry_reason = self._check_entry_conditions(symbol, self.trading_timeframe)
        indicators['entry'] = entry_check
        
        if not entry_check['is_valid']:
            self.logger.debug(f"{symbol}: Entry conditions failed - {entry_reason}")
            return None
        
        reasons.append(f"✅ Entry: {entry_reason}")
        confidence_score += 25.0
        
        # 7. VOLUME CONFIRMATION
        volume_check, volume_reason = self._check_volume(symbol, self.trading_timeframe)
        indicators['volume'] = volume_check
        
        if volume_check['has_volume']:
            reasons.append(f"✅ Volume: {volume_reason}")
            confidence_score += 20.0
        else:
            reasons.append(f"⚠️ Volume: {volume_reason}")
            confidence_score += 5.0
        
        # 8. ATR/VOLATILITY CHECK (optional)
        if self.profile.use_atr_filter:
            atr_check, atr_reason = self._check_atr(symbol)
            indicators['atr'] = atr_check
            
            if not atr_check['is_valid']:
                self.logger.debug(f"{symbol}: ATR check failed - {atr_reason}")
                return None
            
            reasons.append(f"✅ ATR: {atr_reason}")
            confidence_score += 15.0
        else:
            confidence_score += 15.0
        
        # 9. NOT OVERBOUGHT
        overbought_check, ob_reason = self._check_not_overbought(symbol, self.trading_timeframe)
        indicators['overbought'] = overbought_check
        
        if not overbought_check['is_valid']:
            reasons.append(f"⚠️ RSI: {ob_reason}")
            confidence_score += 3.0
        else:
            reasons.append(f"✅ RSI: {ob_reason}")
            confidence_score += 10.0
        
        # Normalize confidence to 0-100
        confidence_pct = (confidence_score / max_confidence) * 100
        
        # Check minimum confidence threshold
        if confidence_pct < self.min_confidence:
            self.logger.debug(
                f"{symbol}: Signal below threshold "
                f"({confidence_pct:.1f}% < {self.min_confidence}%)"
            )
            return None
        
        # Determine signal strength
        if confidence_pct >= 90:
            strength = SignalStrength.VERY_STRONG
        elif confidence_pct >= 80:
            strength = SignalStrength.STRONG
        elif confidence_pct >= 70:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        regime, regime_reason = self.regime_filter.get_regime(
            symbol=symbol,
            primary_timeframe=self.trend_timeframe,
            confirm_timeframe=self.trading_timeframe       
        )

        # Get current price
        current_price = self.price_cache.get_price(symbol)
        
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
            market_regime=regime.value,
            reasons=reasons,
            regime_confidence=regime_reason
        )

        self.logger.info(
            f"🎯 SIGNAL GENERATED: {symbol} | "
            f"Strength: {strength.value} | "
            f"Confidence: {confidence_pct:.1f}% "
            
        )
        
        return signal
    
    def _check_trend(self, symbol: str, timeframe: str) -> Tuple[dict, str]:
        """
        Check if higher timeframe trend is bullish
        
        Uses trend_indicators from profile YAML
        This validates the TREND AUTHORITY timeframe (e.g., 4h for 1h trading)
        """
        # Get indicator config from profile
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
        """
        NEW: Check entry filter (execution timeframe validation)
        
        Uses entry_indicators from profile YAML
        This validates the EXECUTION timeframe (e.g., 1h for 1h trading)
        
        This is separate from _check_entry_conditions which does scoring.
        This is a hard pass/fail based on configured indicators.
        """
        # Get entry indicator config from profile
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
    
    def _check_entry_conditions(self, symbol: str, timeframe: str) -> Tuple[dict, str]:
        """
        Check entry conditions on trading timeframe
        
        Scoring (max 100 points):
        - Price vs VWAP: 0-30 points
        - EMA alignment: 0-30 points  
        - RSI position: 0-20 points
        - RSI momentum: 0-20 points
        """
        trend = self.trend_cache.get(symbol, timeframe)
        
        if trend is None:
            return {"is_valid": False, "score": 0}, f"No trend data"
        
        score = 0
        checks = []
        
        # 1. Price vs VWAP (0-30 points)
        if trend.price > trend.vwap * 1.002:  # 0.2% above
            score += 30
            checks.append("VWAP++ (above)")
        elif trend.price > trend.vwap * 0.998:  # Near VWAP
            score += 20
            checks.append("VWAP+ (near)")
        else:
            score += 0
            checks.append("VWAP- (below)")
        
        # 2. EMA alignment (0-30 points)
        ema_diff_pct = ((trend.ema20 - trend.ema50) / trend.ema50) * 100
        
        if ema_diff_pct > 0.5:  # Strong bullish alignment
            score += 30
            checks.append(f"EMA++ ({ema_diff_pct:.1f}%)")
        elif ema_diff_pct > 0:  # Mild bullish
            score += 20
            checks.append(f"EMA+ ({ema_diff_pct:.1f}%)")
        elif ema_diff_pct > -0.5:  # Converging
            score += 10
            checks.append(f"EMA~ (converging)")
        else:  # Bearish
            score += 0
            checks.append(f"EMA- (bearish)")
        
        # 3. RSI position (0-20 points)
        rsi = trend.rsi
        
        if 45 <= rsi <= 60:  # Sweet spot
            score += 20
            checks.append(f"RSI++ ({rsi:.0f})")
        elif 40 <= rsi < 45 or 60 < rsi <= 65:  # Acceptable
            score += 15
            checks.append(f"RSI+ ({rsi:.0f})")
        elif 35 <= rsi < 40 or 65 < rsi <= 70:  # Edge cases
            score += 10
            checks.append(f"RSI~ ({rsi:.0f})")
        else:  # Too extreme
            score += 0
            checks.append(f"RSI- ({rsi:.0f})")
        
        # 4. RSI momentum (0-20 points)
        rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(symbol, timeframe)
        
        if rsi_momentum is not None:
            if rsi_direction == "increasing" and rsi_momentum > 1.0:  # Strong increase
                score += 20
                checks.append(f"MOM++ (+{rsi_momentum:.1f})")
            elif rsi_direction == "increasing":  # Mild increase
                score += 15
                checks.append(f"MOM+ (+{rsi_momentum:.1f})")
            elif rsi_direction == "flat":  # Stable
                score += 10
                checks.append(f"MOM~ ({rsi_momentum:+.1f})")
            elif rsi_direction == "decreasing" and rsi_momentum > -1.0:  # Mild decrease
                score += 5
                checks.append(f"MOM- ({rsi_momentum:.1f})")
            else:  # Sharp decrease
                score += 0
                checks.append(f"MOM-- ({rsi_momentum:.1f})")
        else:
            score += 10  # Neutral if no momentum data
            checks.append("MOM? (no data)")
        
        # Require minimum 60/100 points to be valid
        is_valid = score >= 60
        reason = f"Score: {score}/100 ({', '.join(checks)})"
        
        return {
            "is_valid": is_valid,
            "score": score,
            "checks": checks,
            "price_vs_vwap": trend.price > trend.vwap,
            "ema_diff_pct": float(ema_diff_pct),
            "rsi": float(rsi),
            "rsi_momentum": float(rsi_momentum) if rsi_momentum else None,
            "rsi_direction": rsi_direction
        }, reason

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
        """Ensure we're not buying into overbought conditions"""
        trend = self.trend_cache.get(symbol, timeframe)
        
        if trend is None:
            return {"is_valid": False}, "No RSI data"
        
        rsi = trend.rsi
        
        # RSI thresholds
        if rsi < 70:
            return {
                "is_valid": True,
                "rsi": float(rsi)
            }, f"RSI {rsi:.0f} not overbought"
        elif rsi < 75:
            return {
                "is_valid": False,
                "rsi": float(rsi)
            }, f"RSI {rsi:.0f} getting overbought"
        else:
            return {
                "is_valid": False,
                "rsi": float(rsi)
            }, f"RSI {rsi:.0f} overbought"
    
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
                self.logger.error(f"Error generating signal for {symbol}: {e}", exc_info=True)
        
        # Sort by confidence (highest first)
        signals.sort(key=lambda s: s.confidence, reverse=True)
        
        if signals:
            self.logger.info(
                f"Scan complete: {len(signals)} signal(s) found from {len(symbols)} symbols"
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