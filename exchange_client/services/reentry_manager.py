from typing import Dict, List, NamedTuple, Optional, Tuple
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from db.utils import get_db_session
from db.models import Position
from models.webhook import TrendData
from utils.logging import log_manager
from utils.settings_helper import get_settings_helper
from utils.constants import PositionCloseReason,StrategyType


class RecentExit(NamedTuple):
    """The fields of a closed Position that re-entry rules actually read.

    Materialised while the DB session is open so the rest of the check — and
    any batch prefetch that outlives its session — never touches a detached
    ORM instance.
    """
    symbol: str
    closed_at: datetime
    close_reason: Optional[str]
    exit_price: Optional[float]

    @classmethod
    def from_position(cls, pos: Position) -> "RecentExit":
        return cls(
            symbol=pos.symbol,
            closed_at=pos.closed_at,
            close_reason=pos.close_reason,
            exit_price=float(pos.exit_price) if pos.exit_price is not None else None,
        )


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
        self.settings = get_settings_helper()
        # profile_name -> {symbol: RecentExit}. Populated by prime_recent_exits()
        # for the duration of one scan so can_reenter() costs no DB round trip.
        self._prefetched: Dict[str, Dict[str, RecentExit]] = {}

    def reentry_lookback_hours(
        self,
        sl_cooldown_minutes: Optional[int] = None,
        tp_cooldown_minutes: Optional[int] = None,
    ) -> int:
        """Hours of exit history a re-entry decision needs.

        Single definition so the batch prefetch and the per-symbol lookup can
        never disagree about the window — a prefetch that looked back less far
        than can_reenter() would silently turn a live cooldown into
        "No recent exit".
        """
        sl_mins = sl_cooldown_minutes if sl_cooldown_minutes is not None else self.settings.cooldown_stop_loss_mins
        tp_mins = tp_cooldown_minutes if tp_cooldown_minutes is not None else self.settings.cooldown_take_profit_mins
        max_cooldown_mins = max(sl_mins, tp_mins, self.settings.cooldown_default_mins)
        return max(2, -(-max_cooldown_mins // 60) + 1)  # ceil(mins/60) + 1hr buffer

    def prime_recent_exits(
        self,
        profile_name: str,
        symbols: List[str],
        lookback_hours: int,
    ) -> None:
        """Load every symbol's most recent exit for this profile in one query.

        can_reenter() previously opened its own DB session per symbol. On a
        remote Postgres that is a full round trip each (~380ms observed against
        Neon from Render), so a 20-symbol scan spent seconds doing almost
        nothing. Call this once before a scan; call clear_recent_exits() after.
        """
        if not symbols:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        with get_db_session() as db:
            rows = (
                db.query(Position)
                .filter(
                    Position.profile_name == profile_name,
                    Position.symbol.in_(list(symbols)),
                    Position.status == "CLOSED",
                    Position.closed_at >= cutoff,
                    Position.close_reason.isnot(None),
                )
                .order_by(Position.closed_at.desc())
                .all()
            )
            # Rows are newest-first, so the first hit per symbol is the latest.
            latest: Dict[str, RecentExit] = {}
            for pos in rows:
                if pos.symbol not in latest:
                    latest[pos.symbol] = RecentExit.from_position(pos)
        # Symbols with no recent exit are recorded as absent, which the lookup
        # below reads as "no recent exit" — the same answer the per-symbol query
        # gave, without another trip.
        self._prefetched[profile_name] = latest

    def clear_recent_exits(self, profile_name: Optional[str] = None) -> None:
        """Drop primed data so later callers fall back to a live query."""
        if profile_name is None:
            self._prefetched.clear()
        else:
            self._prefetched.pop(profile_name, None)

    def can_reenter(
        self,
        symbol: str,
        profile_name: str,
        timeframe: str,     #Uses Trading timeframe
        current_trend: TrendData,  # Your TrendData from trend_cache - Trading timeframe
        strategy_type: StrategyType,
        sl_cooldown_minutes: Optional[int] = None,  # Per-profile override; None = use global setting
        tp_cooldown_minutes: Optional[int] = None,  # Per-profile override; None = use global setting
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
        # Lookback must cover the longest possible cooldown so we don't miss a recent exit
        lookback_hours = self.reentry_lookback_hours(sl_cooldown_minutes, tp_cooldown_minutes)

        # Use the batch primed by prime_recent_exits() when this scan has one;
        # otherwise fall back to a single-symbol query so callers outside the
        # scan loop (API endpoints, tests) behave exactly as before. Only the
        # lookup needs a session — everything after works off RecentExit.
        primed = self._prefetched.get(profile_name)
        if primed is not None:
            recent_exit = primed.get(symbol)
        else:
            with get_db_session() as db:
                # Get most recent closed position for this symbol/profile
                recent_exit = self._get_most_recent_exit(db, profile_name, symbol, lookback_hours=lookback_hours)

        # No recent exit = free to enter
        if recent_exit is None:
            return True, "No recent exit"

        # Calculate time since exit
        now = datetime.now(timezone.utc)
        time_since_exit = (now - recent_exit.closed_at).total_seconds()

        #Get last exit reason
        close_reason = recent_exit.close_reason

        # Get cooldown period based on last exit - convert minutes to seconds
        # Per-profile overrides take priority over global settings
        if close_reason == PositionCloseReason.TAKE_PROFIT:
            mins = tp_cooldown_minutes if tp_cooldown_minutes is not None else self.settings.cooldown_take_profit_mins
            cooldown = mins * 60
        elif close_reason in (PositionCloseReason.STOP_LOSS, PositionCloseReason.TREND_INVALIDATION):
            # Trend invalidation is a signal-failure exit like a stop loss - trigger conditions failed
            mins = sl_cooldown_minutes if sl_cooldown_minutes is not None else self.settings.cooldown_stop_loss_mins
            cooldown = mins * 60
        else:
            cooldown = self.settings.cooldown_default_mins * 60

        # RULE 1: Minimum cooldown period (always enforced)
        if time_since_exit < cooldown:
            remaining = int(cooldown - time_since_exit)
            return False, f"Cooldown: {remaining}s remaining (last exit: {recent_exit.close_reason})"

        #If not Trend following strategy, can exit re-entry here as true. If trend following, continue
        if strategy_type != StrategyType.TREND_FOLLOWING:
            return True, f"Cooldown passed after {close_reason}"

        # RULE 2: Exit-specific requirements
        from cache.price_cache import get_price_cache
        price_cache = get_price_cache()
        price = price_cache.get_price(symbol)
        if price is None:
            return False, "Price not available"

        current_price = float(price)
        # Don't re-enter at higher price after stop - Adjusted 21st Feb to do this check for ALL positions , not just stop loss
        #if current_price > recent_exit.exit_price:
        #    return False, f"Re-entry rejected. Price higher than exit (Curr: {current_price:.2f} > Exit: {recent_exit.exit_price:.2f})"

        # After exit (TP/Trailing Stop/SL/Trend Invalidation), require momentum reset
        if close_reason in ["TAKE_PROFIT", "TRAILING_STOP", "STOP_LOSS", "TREND_INVALIDATION"]:
            reset_ok, reset_reason = self._check_momentum_reset(
                recent_exit,
                current_trend,
                current_price
            )

            if not reset_ok:
                return False, f"Last {close_reason} exit @ {recent_exit.closed_at.strftime('%H:%M')}: {reset_reason}"
            else:
                return True, f"Momentum reset OK after {close_reason} - {reset_reason}"

        # Other close reasons (MANUAL, INVALID, etc.)
        else:
            return True, f"Cooldown passed after {close_reason}"
    
    def _get_most_recent_exit(
        self,
        db: Session,
        profile_name: str,
        symbol: str,
        lookback_hours: int = 2
    ) -> Optional[RecentExit]:
        """
        Get the most recent closed position for a symbol

        Args:
            db: Database session
            profile_name: Profile name
            symbol: Symbol
            lookback_hours: How far back to look — caller must pass a value that covers the full cooldown window
            
        Returns:
            Most recent Position or None
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

        pos = (
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
        # Snapshot inside the session — the caller reads these fields after it closes.
        return RecentExit.from_position(pos) if pos is not None else None

    def _check_momentum_reset(
        self,
        recent_exit: RecentExit,
        current_trend: TrendData,
        current_price: float
    ) -> Tuple[bool, str]:
        """
        Check momentum reset using TRADING timeframe
        
        Why trading timeframe?
        - Re-entry is a tactical decision (entry timing)
        - Need responsive signals, not lagging trend
        - current_trend is already from trading TF
        """
        checks = []
        score = 0
        
        rsi = current_trend.rsi
        
        # Get momentum from THE SAME TIMEFRAME as current_trend
        from cache.trend_cache import get_trend_cache
        cache = get_trend_cache()
        
        # Extract symbol from current_trend (it's already properly formatted)
        symbol = current_trend.symbol
        
        # Use the TRADING timeframe passed in (e.g., "15")
        rsi_momentum, rsi_direction = cache._get_rsi_momentum(
            symbol,
            current_trend.timeframe  
        )
        
        # 1. RSI not overbought (0-30 points)
        if rsi < 60:
            score += 30
            checks.append(f"RSI cooled ({rsi:.1f})")
        elif rsi < 65:
            score += 15
            checks.append(f"RSI moderate ({rsi:.1f})")
        else:
            score += 0
            checks.append(f"RSI still high ({rsi:.1f})")
        
        # 2. RSI in healthy range WITH momentum check (0-40 points)
        if 45 <= rsi <= 58:
            if rsi_direction == "increasing" or rsi_direction == "flat":
                score += 40
                checks.append(f"RSI optimal + {rsi_direction}")
            else:
                score += 25  # In range but weakening
                checks.append(f"RSI OK but {rsi_direction}")
        
        elif 40 <= rsi < 45:
            if rsi_direction == "increasing":
                score += 35  # Building momentum from low base
                checks.append(f"RSI building ({rsi:.1f}, {rsi_direction})")
            else:
                score += 15
                checks.append(f"RSI slightly low + {rsi_direction}")
        
        elif 58 < rsi < 65:
            if rsi_direction == "decreasing":
                score += 30  # Pulling back from high - good!
                checks.append(f"RSI cooling from high ({rsi:.1f}, {rsi_direction})")
            else:
                score += 10  # Still elevated and not cooling
                checks.append(f"RSI elevated + {rsi_direction}")
        
        else:
            score += 0
            checks.append(f"RSI extreme ({rsi:.1f})")
        
        # 3. Price vs EMA20 (0-20 points)
        if current_price >= current_trend.ema20 * 0.997:
            score += 20
            checks.append("Price @ EMA20+")
        elif current_price >= current_trend.ema20 * 0.99:
            score += 10
            checks.append("Price near EMA20")
        else:
            price_vs_ema = ((current_price - current_trend.ema20) / current_trend.ema20) * 100
            score += 0
            checks.append(f"Price below EMA20 ({price_vs_ema:.2f}%)")
        
        # 4. Price vs exit price (0-10 points)
        exit_price = float(recent_exit.exit_price)
        if exit_price and exit_price > 0:
            price_change_pct = ((current_price - exit_price) / exit_price) * 100
            
            if -1.0 <= price_change_pct <= 0.5:  # Slight pullback is ideal
                score += 10
                checks.append(f"Price reset OK ({price_change_pct:+.1f}%)")
            elif price_change_pct < -2.0:
                score += 0
                checks.append(f"Price dropped {abs(price_change_pct):.1f}%")
            else:
                score += 5
                checks.append(f"Price {price_change_pct:+.1f}%")
        
        # Need 70/100 points to allow re-entry
        reset_ok = score >= 70
        reason = f"Score: {score}/100 - {', '.join(checks)}"
        
        return reset_ok, reason
    
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
