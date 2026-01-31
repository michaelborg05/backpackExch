# services/signal_generator.py
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
    Generates trading signals based on multiple indicators
    
    Philosophy:
    - Multiple timeframe analysis (trend on higher TF, entry on lower TF)
    - Volume confirmation (no volume = no conviction)
    - Volatility awareness (ATR filter)
    - Momentum detection (RSI direction)
    - Risk management (don't buy overbought)
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
        
        # Thresholds
        self.min_volume_ratio = getattr(profile, 'min_volume_ratio', 1.5)  # Volume must be 50% above average
        self.min_confidence = getattr(profile, 'min_signal_confidence', 70.0)  # Don't trade below 70%
        
        self.logger.info(
            f"Initialized SignalGenerator: "
            f"trading_tf={self.trading_timeframe}, "
            f"trend_tf={self.trend_timeframe}, "
            f"min_volume_ratio={self.min_volume_ratio}, "
            f"min_confidence={self.min_confidence}%"
        )
    
    def generate_signal(self, symbol: str) -> Optional[TradingSignal]:
        """
        Generate trading signal for a symbol
        
        Signal Logic:
        1. ✅ Higher timeframe trend is bullish (required)
        2. ✅ Trading timeframe shows entry opportunity
        3. ✅ Volume confirms the move
        4. ✅ Volatility is appropriate (ATR check)
        5. ✅ Not overbought (RSI < 70)
        6. ✅ Momentum is positive (RSI increasing)
        
        Returns:
            TradingSignal or None if no signal
        """
        
                # Create trading service
        trading = TradingService(self.profile)

        #Check if balance is available to buy before proceeding with signal checks
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

        if self.profile.use_market_regime_filter:

            #1. Add Regime check first - If market is not worth trading, exit early
            can_trade, regime_reason = self.regime_filter.can_trade(
                symbol=symbol,
                profile_name=self.profile.name,
                primary_timeframe=self.trend_timeframe,  # Uses your 60m timeframe
                confirm_timeframe=self.trading_timeframe  # Uses your 15m timeframe
            )
            
            if not can_trade:
                # Log at debug level to avoid spam (most rejections will be UNCERTAIN regime)
                self.logger.debug(
                    f"{symbol}: Market regime check failed - {regime_reason}"
                )
                return None

        # 2. Before any signal checks, check reentry conditions to make sure we did not just exit a position
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
        
        # 3. CHECK HIGHER TIMEFRAME TREND (30 points)
        trend_check, trend_reason = self._check_trend(symbol, self.trend_timeframe)
        indicators['trend'] = trend_check
        
        if not trend_check['is_bullish']:
            self.logger.debug(f"{symbol}: No signal - {trend_reason}")
            return None  # HARD STOP - trend must be bullish
        
        reasons.append(f"✅ Trend: {trend_reason}")
        confidence_score += 30.0
        
        # 4. CHECK TRADING TIMEFRAME ENTRY (25 points)
        entry_check, entry_reason = self._check_entry_conditions(symbol, self.trading_timeframe)
        indicators['entry'] = entry_check
        
        if not entry_check['is_valid']:
            self.logger.debug(f"{symbol}: No signal - {entry_reason}")
            return None
        
        reasons.append(f"✅ Entry: {entry_reason}")
        confidence_score += 25.0
        
        # 5. VOLUME CONFIRMATION (20 points)
        volume_check, volume_reason = self._check_volume(symbol, self.trading_timeframe)
        indicators['volume'] = volume_check
        
        if volume_check['has_volume']:
            reasons.append(f"✅ Volume: {volume_reason}")
            confidence_score += 20.0
        else:
            # Volume not available or weak - reduce confidence
            reasons.append(f"⚠️ Volume: {volume_reason}")
            confidence_score += 5.0  # Small penalty
        
        # 6. ATR/VOLATILITY CHECK (15 points)
        if self.profile.use_atr_filter:
            atr_check, atr_reason = self._check_atr(symbol)
            indicators['atr'] = atr_check
            
            if not atr_check['is_valid']:
                self.logger.debug(f"{symbol}: No signal - {atr_reason}")
                return None
            
            reasons.append(f"✅ ATR: {atr_reason}")
            confidence_score += 15.0
        else:
            confidence_score += 15.0  # Give full points if not using ATR filter
        
        # 7. NOT OVERBOUGHT (10 points)
        overbought_check, ob_reason = self._check_not_overbought(symbol, self.trading_timeframe)
        indicators['overbought'] = overbought_check
        
        if not overbought_check['is_valid']:
            reasons.append(f"⚠️ RSI: {ob_reason}")
            confidence_score += 3.0  # Partial credit
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

        signal = TradingSignal(
            symbol=symbol,
            action="BUY",
            strength=strength,
            confidence=confidence_pct,
            reasons=reasons + [f"Market: {regime_reason}"],  # Add regime to reasons
            indicators=indicators,
            timestamp=time.time(),
            timeframe=self.trading_timeframe
        )
        
        self.logger.info(
            f"🎯 SIGNAL GENERATED: {symbol} - "
            f"{strength.name} ({confidence_pct:.1f}%) - "
            f"{', '.join(reasons)}"
        )
        
        return signal
    
    def _check_trend(self, symbol: str, timeframe: str) -> Tuple[dict, str]:
        """Check if higher timeframe trend is bullish"""
        trend = self.trend_cache.get(symbol, timeframe)
        
        if trend is None:
            return {"is_bullish": False}, f"No trend data for {timeframe}"
        
        # Use profile's trend filter logic
        is_bullish, reason = self.trend_cache.is_bullish(
            symbol=symbol,
            timeframe=timeframe,
            indicators_config=self.profile.trend_indicators,
            min_indicators_required=self.profile.min_indicators_required
        )
        
        return {
            "is_bullish": is_bullish,
            "ema20": float(trend.ema20),
            "ema50": float(trend.ema50),
            "rsi": float(trend.rsi),
            "vwap": float(trend.vwap),
            "price": float(trend.price)
        }, reason
    
    def _check_entry_conditions(self, symbol: str, timeframe: str) -> Tuple[dict, str]:
        """
        Check entry conditions with momentum awareness
        
        Scoring system (0-100 points):
        - Price vs VWAP: 0-30 points
        - EMA alignment: 0-30 points  
        - RSI position: 0-20 points
        - RSI momentum: 0-20 points (NEW)
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
        
        # 4. RSI momentum (0-20 points) - NEW!
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