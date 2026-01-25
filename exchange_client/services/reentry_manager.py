from typing import Optional, Tuple
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from db.utils import get_db_session
from db.models import Position
from models.webhook import TrendData
from utils.logging import log_manager


class ReEntryManager:
    """
    Manages re-entry rules based on previous exits (DB-backed)
    
    Philosophy:
    - After profitable exit: Wait for momentum reset
    - After stop loss: Require trend re-validation
    - Use DB as source of truth (survives restarts)
    """
    
    def __init__(self):
        self.logger = log_manager.get_logger("ReEntryManager")
        
        # Cooldown periods by timeframe (in seconds)
        self._cooldown_periods = {
            "1": 300,      # 1m → 5 min cooldown
            "5": 600,      # 5m → 10 min cooldown  
            "15": 900,     # 15m → 15 min cooldown
            "60": 3600,    # 1h → 60 min cooldown
        }
    
    def can_reenter(
        self,
        symbol: str,
        profile_name: str,
        timeframe: str,
        current_trend: TrendData  # Your TrendData from trend_cache
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if re-entry is allowed based on recent DB exits
        
        Args:
            symbol: Trading symbol (e.g., "SOL_USDC")
            profile_name: Profile name
            timeframe: Trading timeframe (e.g., "15")
            current_trend: Current trend data for momentum checks
            
        Returns:
            (can_enter, reason) tuple
        """
        with get_db_session() as db:
            # Get most recent closed position for this symbol/profile
            recent_exit = self._get_most_recent_exit(db, profile_name, symbol)
            
            # No recent exit = free to enter
            if recent_exit is None:
                return True, "No recent exit"
            
            # Calculate time since exit
            now = datetime.now(timezone.utc)
            time_since_exit = (now - recent_exit.closed_at).total_seconds()
            
            # Get cooldown period for this timeframe
            cooldown = self._cooldown_periods.get(timeframe, 900)  # Default 15 min
            
            # RULE 1: Minimum cooldown period (always enforced)
            if time_since_exit < cooldown:
                remaining = int(cooldown - time_since_exit)
                return False, f"Cooldown: {remaining}s remaining (last exit: {recent_exit.close_reason})"
            
            # RULE 2: Exit-specific requirements
            close_reason = recent_exit.close_reason
            
            # After profitable exit (TP/Trailing Stop), require momentum reset
            if close_reason in ["TAKE_PROFIT", "TRAILING_STOP"]:
                reset_ok, reset_reason = self._check_momentum_reset(
                    recent_exit,
                    current_trend
                )
                
                if not reset_ok:
                    return False, f"Profitable exit @ {recent_exit.closed_at.strftime('%H:%M')}: {reset_reason}"
                else:
                    return True, f"Momentum reset OK after {close_reason}"
            
            # After stop loss, allow but log it (signal generator should be more cautious)
            elif close_reason == "STOP_LOSS":
                self.logger.info(
                    f"Re-entry after SL on {symbol} - ensure signal quality is high"
                )
                return True, f"Cooldown passed after SL"
            
            # Other close reasons (MANUAL, INVALID, etc.)
            else:
                return True, f"Cooldown passed after {close_reason}"
    
    def _get_most_recent_exit(
        self,
        db: Session,
        profile_name: str,
        symbol: str,
        lookback_hours: int = 6  # Only check last 6 hours
    ) -> Optional[Position]:
        """
        Get the most recent closed position for a symbol
        
        Args:
            db: Database session
            profile_name: Profile name
            symbol: Symbol
            lookback_hours: How far back to look (default 6 hours)
            
        Returns:
            Most recent Position or None
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        
        return (
            db.query(Position)
            .filter(
                Position.profile_name == profile_name,
                Position.symbol == symbol,
                Position.status == "CLOSED",
                Position.closed_at >= cutoff,  # Only recent exits
                Position.close_reason.isnot(None)  # Must have a reason
            )
            .order_by(Position.closed_at.desc())
            .first()
        )
    
    def _check_momentum_reset(
        self,
        recent_exit: Position,
        current_trend: TrendData
    ) -> Tuple[bool, str]:
        """
        Check if momentum has reset enough to allow re-entry
        
        After a profitable exit, we want to ensure:
        1. RSI has pulled back (not overbought)
        2. RSI is in a healthy range for re-entry
        3. Price hasn't crashed below key levels
        
        Args:
            recent_exit: The Position that was closed
            current_trend: Current market trend data
            
        Returns:
            (reset_ok, reason) tuple
        """
        checks = []
        all_pass = True
        
        # 1. RSI not overbought (must be below 65)
        if current_trend.rsi > 65:
            checks.append(f"RSI still high ({current_trend.rsi:.1f})")
            all_pass = False
        else:
            checks.append(f"RSI cooled ({current_trend.rsi:.1f})")
        
        # 2. RSI in "buy zone" (45-60 is ideal for re-entry)
        if 45 <= current_trend.rsi <= 60:
            checks.append("RSI in buy zone")
        elif 40 <= current_trend.rsi < 45:
            checks.append("RSI slightly low")
            # Don't fail, just note it
        else:
            checks.append(f"RSI not optimal ({current_trend.rsi:.1f})")
            all_pass = False
        
        # 3. Price must be near or above EMA20 (support level)
        # Allow 0.3% below EMA20 (small wiggle room)
        if current_trend.price >= current_trend.ema20 * 0.997:
            checks.append("Price @ EMA20+")
        else:
            price_vs_ema = ((current_trend.price - current_trend.ema20) / current_trend.ema20) * 100
            checks.append(f"Price below EMA20 ({price_vs_ema:.2f}%)")
            all_pass = False
        
        # 4. Optional: Check we're not re-entering at a worse price
        # (This prevents "catching a falling knife")
        exit_price = float(recent_exit.exit_price)
        current_price = float(current_trend.price)
        
        # If current price is >2% below our exit, be cautious
        if exit_price and exit_price > 0:
            price_change_pct = ((current_price - exit_price) / exit_price) * 100
        else:
            price_change_pct = 0
        if price_change_pct < -2.0:
            checks.append(f"Price dropped {abs(price_change_pct):.1f}% since exit")
            all_pass = False
        elif price_change_pct < 0:
            checks.append(f"Price down {abs(price_change_pct):.1f}%")
            # Note it but don't fail
        
        reason = ", ".join(checks)
        return all_pass, reason
    
    def get_recent_exits_summary(
        self,
        profile_name: str,
        hours: int = 24
    ) -> dict:
        """
        Get summary of recent exits for debugging/analysis
        
        Args:
            profile_name: Profile to check
            hours: Lookback period
            
        Returns:
            Summary dict with exit counts by reason
        """
        with get_db_session() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            exits = (
                db.query(Position)
                .filter(
                    Position.profile_name == profile_name,
                    Position.status == "CLOSED",
                    Position.closed_at >= cutoff
                )
                .all()
            )
            
            # Count by reason
            by_reason = {}
            for exit in exits:
                reason = exit.close_reason or "UNKNOWN"
                if reason not in by_reason:
                    by_reason[reason] = 0
                by_reason[reason] += 1
            
            return {
                "total_exits": len(exits),
                "by_reason": by_reason,
                "lookback_hours": hours
            }

# Global instance
_reentry_manager = None


def get_reentry_manager() -> ReEntryManager:
    """Get or create global re-entry manager"""
    global _reentry_manager
    if _reentry_manager is None:
        _reentry_manager = ReEntryManager()
    return _reentry_manager