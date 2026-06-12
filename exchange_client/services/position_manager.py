# services/position_manager.py 

from typing import Tuple, Optional
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from utils.logging import log_manager
from cache.trend_cache import get_trend_cache
from models.trading_profile import TradingProfile
from db.models import Position
from utils.settings_helper import get_settings_helper


class PositionManager:
    """
    Manages position lifecycle beyond simple TP/SL
    
    Exit Strategy Hierarchy:
    1. TAKE_PROFIT - Hit target (highest priority)
    2. STOP_LOSS - Hit stop (highest priority)
    3. TRAILING_STOP - Trailing stop hit (highest priority)
    4. TREND_INVALIDATION - Market structure broken (medium priority)
    5. STALE_POSITION - Dead money + time limit (low priority)
    
    Philosophy:
    - Let winners run if trend intact
    - Cut losers when trend breaks
    - Exit "dead money" that's not progressing
    """
    
    def __init__(self):
        self.logger = log_manager.get_logger("PositionManager")
        self.trend_cache = get_trend_cache()
        self.settings = get_settings_helper()
    
    def should_exit_position(
        self,
        position: Position,
        profile: TradingProfile,
        current_price: float
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if position should be exited (beyond TP/SL/Trailing)
        
        Args:
            position: Position to check
            profile: Trading profile with exit settings
            current_price: Current market price
            
        Returns:
            (should_exit, reason) tuple
        """
        # Check trend invalidation first (more important than time)
        if self._should_use_trend_exits(profile):
            should_exit, reason = self._check_trend_invalidation(
                position, profile, current_price
            )
            self.logger.info(
                f"Trend Position status: {position.symbol} - should_exit {should_exit} - {reason} "
            )
            if should_exit:
                return True, f"TREND_INVALIDATION: {reason}"
        
        # Check stale/dead money (time-based backstop)
        if self._should_use_time_exits(profile):
            should_exit, reason = self._check_stale_position(
                position, profile, current_price
            )
            self.logger.info(
                f"Stale Position status: {position.symbol} - should_exit {should_exit} - {reason} "
            )
            if should_exit:
                return True, f"STALE_POSITION: {reason}"
        
        return False, None
    
    def _should_use_trend_exits(self, profile: TradingProfile) -> bool:
        """Check if profile uses trend invalidation exits"""
        return getattr(profile, 'use_trend_invalidation_exit', False)

    def _should_use_time_exits(self, profile: TradingProfile) -> bool:
        """Check if profile uses time-based exits"""
        return getattr(profile, 'max_position_hours', None) is not None
    
    def _check_trend_invalidation(
        self,
        position: Position,
        profile: TradingProfile,
        current_price: float
    ) -> Tuple[bool, str]:
        """
        Check if trend that justified entry is now invalid
        
        Returns:
            (should_exit, reason)
        """
        symbol = position.symbol
        
        # Don't check very new positions (let them develop)
        min_age = getattr(profile, 'min_position_age_for_trend_check', 120)  # minutes
        position_age_minutes = self._get_position_age_minutes(position)

        if position_age_minutes < min_age:
            return False, f"Too young ({position_age_minutes:.1f}m < {min_age}m)"

        # Get entry data. If not found, use trend data
        if getattr(profile, 'trend_invalidation_indicators', "entry") == "exit":
            exit_inds = getattr(profile, 'exit_indicators', None)
            if exit_inds:
                indicators_config = exit_inds
                min_required = getattr(profile, 'min_exit_indicators_required', 2)
                exit_tf = getattr(profile, 'exit_timeframe', None)
                indicator_timeframe = exit_tf or getattr(profile, 'entry_timeframe', '15')
            else:
                # No exit indicators configured — fall back to entry indicators
                indicators_config = getattr(profile, 'entry_indicators', None)
                min_required = getattr(profile, 'min_entry_indicators_required', 2) - 1
                indicator_timeframe = getattr(profile, 'entry_timeframe', '15')

        elif getattr(profile, 'trend_invalidation_indicators', "entry") == "entry":
            indicators_config = getattr(profile, 'entry_indicators', None)
            min_required = getattr(profile, 'min_entry_indicators_required', 2) - 1 #Reduce min required by 1 for trend invalidation
            indicator_timeframe = getattr(profile, 'entry_timeframe', '15')

        elif getattr(profile, 'trend_invalidation_indicators', "entry") == "mean_reversion":
            lookback_candles = self.settings.mean_rever_rsi_lookback_candles
            min_rsi = self.settings.mean_rever_rsi_inval_threshold
            #try to use custom rsi_reversal_momentum logic for mean reversion strategy.
            # Set oversold_threshold high as we dont need this limit in this check

            indicators_config = [
                {"type": "rsi_reversal_momentum", "params":
                 {"lookback_candles": lookback_candles, "oversold_threshold": 60,
                  "current_min": min_rsi,"min_jump":1, "require_sustained":False,
                  "jump_required": False
                 }}
            ]
            min_required = 1
            indicator_timeframe = getattr(profile, 'entry_timeframe', '15')

        elif profile.use_trend_filter:
            indicators_config = getattr(profile, 'trend_indicators', None)
            min_required = getattr(profile, 'min_indicators_required', 2)  - 1 #Reduce min required by 1 for trend invalidation
            indicator_timeframe = getattr(profile, 'trend_timeframe', '15')

        if indicators_config is not None:
            is_bullish, reason = self.trend_cache.is_bullish(
                symbol=symbol,
                timeframe=indicator_timeframe,
                indicators_config=indicators_config,
                min_indicators_required=min_required,
                use_hard_stops=False    #For trend invalidation, want to check all indicators, not reject on 1 failure
            )

        if not is_bullish:
            return True, f"TREND_INVALIDATION: {reason}"
        else:
            return False, f"Trend intact: {reason}"
        
        # # Calculate position state
        # entry_price = float(position.entry_price)
        # profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        # # Exit scoring system (need 3+ points to exit)
        # exit_score = 0
        
        # # 1. Trend turned bearish (STRONG signal - worth 3 points alone)
        # is_bullish, trend_reason = self.trend_cache.is_bullish(
        #     symbol=symbol,
        #     timeframe=trend_timeframe,
        #     indicators_config=profile.trend_indicators,
        #     min_indicators_required=profile.min_indicators_required
        # )
        
        # if not is_bullish:
        #     exit_score += 3
        #    reasons.append(f"Trend bearish")
        
        # 2. Price broke below EMA20 support
        # if current_price < trend.ema20:
        #     distance_pct = ((current_price - trend.ema20) / trend.ema20) * 100
            
        #     if distance_pct < -1.5:  # Serious break
        #         exit_score += 2
        #         reasons.append(f"Price {abs(distance_pct):.1f}% below EMA20")
        #     else:
        #         exit_score += 1
        #         reasons.append("Price below EMA20")
        
        # 3. RSI weak (especially if in loss)
        # if trend.rsi < 40:
        #     exit_score += 2
        #     reasons.append(f"RSI oversold ({trend.rsi:.0f})")
        # elif trend.rsi < 45:
        #     exit_score += 1
        #     reasons.append(f"RSI weak ({trend.rsi:.0f})")
        
        # # 4. Small profit but momentum dying (take it and run)
        # if 0.2 < profit_pct < 0.8:  # Small profit range
        #     rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
        #         symbol, trend_timeframe
        #     )
            
        #     if rsi_direction == "decreasing":
        #         exit_score += 1
        #         reasons.append(f"Profit {profit_pct:.1f}% but fading")
        
        # # 5. Price vs VWAP (institutional support broken)
        # if current_price < trend.vwap * 0.995:  # 0.5% below VWAP
        #     exit_score += 1
        #     reasons.append("Below VWAP support")
        
        # # Decision: Exit if score >= 3
        # should_exit = exit_score >= 3
        
        # if should_exit:
        #     reason = f"Score {exit_score} ({', '.join(reasons)})"
        # else:
        #     reason = f"Holding (score {exit_score}, need 3+)"
        
        # return should_exit, reason
    
    def _check_stale_position(
        self,
        position: Position,
        profile: TradingProfile,
        current_price: float
    ) -> Tuple[bool, str]:
        """
        Check if position is "stale" (time-based backstop)
        
        Only exits if:
        - Position has been open too long AND
        - Not making meaningful progress toward TP
        
        This is the LAST RESORT exit, not primary strategy
        """
        max_hours = getattr(profile, 'max_position_hours', 24)
        position_age_minutes = self._get_position_age_minutes(position)
        
        # Not old enough yet
        if position_age_minutes < max_hours * 60:
            return False, f"Age {position_age_minutes:.1f}m < {max_hours * 60}m"

        # Calculate progress toward TP
        entry_price = float(position.entry_price)
        current_profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        tp_target_pct = float(profile.take_profit_pct)
        progress_pct = (current_profit_pct / tp_target_pct) * 100
        
        # If making good progress (> 50% to TP), let it run
        if progress_pct > 50:
            return False, f"Age {position_age_minutes:.1f}m but {progress_pct:.0f}% to TP"

        # If in meaningful profit (> 0.5%), let it run
        #removed this. Would rather exit here
#        if current_profit_pct > 0.5:
#            return False, f"Age {position_age_hours:.1f}h but +{current_profit_pct:.1f}%"
        
        # Position is old AND not progressing - exit
        return True, (
            f"Stale: {position_age_minutes:.1f}m old, "
            f"{current_profit_pct:+.2f}% profit, "
            f"only {progress_pct:.0f}% to TP"
        )

    def _get_position_age_minutes(self, position: Position) -> float:
        """Calculate position age in minutes"""
        age = datetime.now(timezone.utc) - position.created_at
        return age.total_seconds() / 60


# Global instance
_position_manager = None


def get_position_manager() -> PositionManager:
    """Get or create global position manager"""
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager
