# services/position_manager.py 

from typing import Tuple, Optional
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from utils.logging import log_manager
from cache.trend_cache import get_trend_cache
from models.trading_profile import TradingProfile
from db.models import Position


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
            if should_exit:
                return True, f"TREND_INVALIDATION: {reason}"
        
        # Check stale/dead money (time-based backstop)
        if self._should_use_time_exits(profile):
            should_exit, reason = self._check_stale_position(
                position, profile, current_price
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
        min_age = getattr(profile, 'min_position_age_for_trend_check', 1)  # hours
        position_age_hours = self._get_position_age_hours(position)
        
        if position_age_hours < min_age:
            return False, f"Too young ({position_age_hours:.1f}h < {min_age}h)"
        
        # Get trend data
        trend_timeframe = getattr(profile, 'trend_timeframe', '60')
        trend = self.trend_cache.get(symbol, trend_timeframe)
        
        if trend is None:
            return False, "No trend data"
        
        # Calculate position state
        entry_price = float(position.entry_price)
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Exit scoring system (need 3+ points to exit)
        exit_score = 0
        reasons = []
        
        # 1. Trend turned bearish (STRONG signal - worth 3 points alone)
        is_bullish, trend_reason = self.trend_cache.is_bullish(
            symbol=symbol,
            timeframe=trend_timeframe,
            indicators_config=profile.trend_indicators,
            min_indicators_required=profile.min_indicators_required
        )
        
        if not is_bullish:
            exit_score += 3
            reasons.append(f"Trend bearish")
        
        # 2. Price broke below EMA20 support
        if current_price < trend.ema20:
            distance_pct = ((current_price - trend.ema20) / trend.ema20) * 100
            
            if distance_pct < -1.5:  # Serious break
                exit_score += 2
                reasons.append(f"Price {abs(distance_pct):.1f}% below EMA20")
            else:
                exit_score += 1
                reasons.append("Price below EMA20")
        
        # 3. RSI weak (especially if in loss)
        if trend.rsi < 40:
            exit_score += 2
            reasons.append(f"RSI oversold ({trend.rsi:.0f})")
        elif trend.rsi < 45:
            exit_score += 1
            reasons.append(f"RSI weak ({trend.rsi:.0f})")
        
        # 4. Small profit but momentum dying (take it and run)
        if 0.2 < profit_pct < 0.8:  # Small profit range
            rsi_momentum, rsi_direction = self.trend_cache._get_rsi_momentum(
                symbol, trend_timeframe
            )
            
            if rsi_direction == "decreasing":
                exit_score += 1
                reasons.append(f"Profit {profit_pct:.1f}% but fading")
        
        # 5. Price vs VWAP (institutional support broken)
        if current_price < trend.vwap * 0.995:  # 0.5% below VWAP
            exit_score += 1
            reasons.append("Below VWAP support")
        
        # Decision: Exit if score >= 3
        should_exit = exit_score >= 3
        
        if should_exit:
            reason = f"Score {exit_score} ({', '.join(reasons)})"
        else:
            reason = f"Holding (score {exit_score}, need 3+)"
        
        return should_exit, reason
    
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
        position_age_hours = self._get_position_age_hours(position)
        
        # Not old enough yet
        if position_age_hours < max_hours:
            return False, f"Age {position_age_hours:.1f}h < {max_hours}h"
        
        # Calculate progress toward TP
        entry_price = float(position.entry_price)
        current_profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        tp_target_pct = float(profile.take_profit_pct)
        progress_pct = (current_profit_pct / tp_target_pct) * 100
        
        # If making good progress (> 50% to TP), let it run
        if progress_pct > 50:
            return False, f"Age {position_age_hours:.1f}h but {progress_pct:.0f}% to TP"
        
        # If in meaningful profit (> 0.5%), let it run
        #removed this. Would rather exit here
#        if current_profit_pct > 0.5:
#            return False, f"Age {position_age_hours:.1f}h but +{current_profit_pct:.1f}%"
        
        # Position is old AND not progressing - exit
        return True, (
            f"Stale: {position_age_hours:.1f}h old, "
            f"{current_profit_pct:+.2f}% profit, "
            f"only {progress_pct:.0f}% to TP"
        )
    
    def _get_position_age_hours(self, position: Position) -> float:
        """Calculate position age in hours"""
        age = datetime.now(timezone.utc) - position.created_at
        return age.total_seconds() / 3600


# Global instance
_position_manager = None


def get_position_manager() -> PositionManager:
    """Get or create global position manager"""
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager
