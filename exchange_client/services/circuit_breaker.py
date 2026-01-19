# services/circuit_breaker.py
from typing import Optional, Dict, Tuple
from decimal import Decimal
from datetime import datetime, timedelta
import time
from utils.logging import log_manager
from cache.balance_cache import get_balance_cache
from cache.portfolio_cache import get_portfolio_cache


class CircuitBreakerState:
    """State for a single circuit breaker"""
    
    def __init__(
        self,
        profile_name: str,
        reason: str,
        triggered_at: float,
        reset_at: float,
        trigger_value: Optional[Decimal] = None
    ):
        self.profile_name = profile_name
        self.reason = reason
        self.triggered_at = triggered_at
        self.reset_at = reset_at
        self.trigger_value = trigger_value
    
    def is_active(self) -> bool:
        """Check if circuit breaker is still active"""
        return time.time() < self.reset_at
    
    def time_remaining(self) -> int:
        """Get seconds remaining until reset"""
        remaining = self.reset_at - time.time()
        return max(0, int(remaining))
    
    def to_dict(self) -> dict:
        return {
            "profile": self.profile_name,
            "reason": self.reason,
            "triggered_at": datetime.fromtimestamp(self.triggered_at).isoformat(),
            "reset_at": datetime.fromtimestamp(self.reset_at).isoformat(),
            "time_remaining_seconds": self.time_remaining(),
            "trigger_value": str(self.trigger_value) if self.trigger_value else None
        }


class CircuitBreakerService:
    """
    Manages trading circuit breakers (kill switches) based on PnL and market conditions
    """
    
    def __init__(self):
        self.logger = log_manager.get_logger("CircuitBreaker")
        
        # Active circuit breakers: {profile_name: CircuitBreakerState}
        self._active_breakers: Dict[str, CircuitBreakerState] = {}
        
        # Configuration (can be moved to YAML later)
        self.max_daily_profit_pct = Decimal("5.0")   # Stop at +5% daily profit
        self.max_daily_loss_pct = Decimal("2.0")      # Stop at -2% daily loss
        self.profit_lock_hours = 6                    # Lock for 6 hours after +5%
        self.loss_lock_hours = 12                     # Lock for 12 hours after -2%

        # Track starting balance for each profile (reset every 24h)
        self._daily_start_balance: Dict[str, Decimal] = {}
        self._daily_start_time: Dict[str, float] = {}
    
    def check_circuit_breakers(
        self, 
        profile_name: str,
        alert_action: str = "buy",
        check_pnl: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if any circuit breakers should prevent trading
        
        Args:
            profile_name: Trading profile name
            alert_action: "buy" or "sell"
            check_pnl: Whether to check PnL limits (False for monitoring updates)
            
        Returns:
            (can_trade, block_reason) tuple
        """
        # Check if there's an active circuit breaker
        if profile_name in self._active_breakers:
            breaker = self._active_breakers[profile_name]
            
            if breaker.is_active():
                reason = (
                    f"Circuit breaker active: {breaker.reason} "
                    f"({breaker.time_remaining()}s remaining)"
                )
                self.logger.debug(f"[{profile_name}] {reason}")
                return False, reason
            else:
                # Breaker expired, remove it
                self.logger.info(f"[{profile_name}] Circuit breaker expired: {breaker.reason}")
                del self._active_breakers[profile_name]
        
        # Only check for BUY orders (let SELLs through to close positions)
        if alert_action.lower() != "buy":
            return True, None
        
        # Check daily PnL limits (unless disabled)
        if check_pnl:
            should_trigger, trigger_reason = self._check_daily_pnl_limits(profile_name)
            
            if should_trigger:
                return False, trigger_reason
        
        return True, None
    
    def monitor_all_profiles(self):
        """
        Monitor all profiles and trigger circuit breakers if needed
        Called by MonitoringService on each cycle
        
        This proactively checks PnL even without webhooks
        """
        from services.profile_manager import get_profile_manager
        
        profile_manager = get_profile_manager()
        if not profile_manager:
            return
        
        for profile in profile_manager.get_all_profiles():
            try:
                # Check if this profile should trigger a circuit breaker
                # Use check_pnl=True to evaluate limits
                should_trigger, trigger_reason = self._check_daily_pnl_limits(profile.name)
                
                # We don't block here - just trigger the breaker if needed
                # The actual blocking happens in check_circuit_breakers()
                
            except Exception as e:
                self.logger.error(
                    f"Error monitoring circuit breaker for {profile.name}: {e}",
                    exc_info=True
                )
    
    def _check_daily_pnl_limits(self, profile_name: str) -> Tuple[bool, Optional[str]]:
        """
        Check if daily PnL has exceeded limits
        
        Returns:
            (should_trigger, reason) tuple
        """
        try:
            # CRITICAL FIX: Don't re-trigger if already active
            # This prevents the timer from resetting on every check
            if profile_name in self._active_breakers:
                breaker = self._active_breakers[profile_name]
                if breaker.is_active():
                    # Return the existing breaker's reason without re-triggering
                    self.logger.debug(
                        f"[{profile_name}] Circuit breaker already active: "
                        f"{breaker.time_remaining()}s remaining"
                    )
                    return True, breaker.reason
            
            # Get starting balance for today
            daily_start = self._get_daily_start_balance(profile_name)
            
            if daily_start is None:
                return False, None
            
            # Get current total value
            portfolio = get_portfolio_cache()
            current_value = portfolio.get_total_value(profile_name, "USDC")
            
            # Calculate daily PnL %
            daily_pnl_pct = ((current_value - daily_start) / daily_start) * 100
            
            self.logger.debug(
                f"[{profile_name}] Daily PnL: {daily_pnl_pct:+.2f}% "
                f"(Start: ${daily_start:.2f}, Current: ${current_value:.2f})"
            )
            
            # Check profit limit
            if daily_pnl_pct >= self.max_daily_profit_pct:
                reason = f"Daily profit limit reached: {daily_pnl_pct:+.2f}% (limit: +{self.max_daily_profit_pct}%)"
                self._trigger_circuit_breaker(
                    profile_name,
                    reason,
                    hours=self.profit_lock_hours,
                    trigger_value=daily_pnl_pct
                )
                return True, reason
            
            # Check loss limit
            if daily_pnl_pct <= -self.max_daily_loss_pct:
                reason = f"Daily loss limit reached: {daily_pnl_pct:+.2f}% (limit: -{self.max_daily_loss_pct}%)"
                self._trigger_circuit_breaker(
                    profile_name,
                    reason,
                    hours=self.loss_lock_hours,
                    trigger_value=daily_pnl_pct
                )
                return True, reason
            
            return False, None
            
        except Exception as e:
            self.logger.error(f"Error checking daily PnL limits: {e}", exc_info=True)
            return False, None
    
    def _get_daily_start_balance(self, profile_name: str) -> Optional[Decimal]:
        """Get the starting balance for today (resets every 24 hours)"""
        current_time = time.time()
        
        # Check if we need to reset (new day)
        if profile_name in self._daily_start_time:
            time_since_reset = current_time - self._daily_start_time[profile_name]
            
            # Reset after 24 hours
            if time_since_reset > 86400:  # 24 hours
                self.logger.info(
                    f"[{profile_name}] Resetting daily start balance (24h elapsed)"
                )
                self._reset_daily_start_balance(profile_name)
        
        # If no start balance recorded, record current value
        if profile_name not in self._daily_start_balance:
            portfolio = get_portfolio_cache()
            current_value = portfolio.get_total_value(profile_name, "USDC")
            
            self._daily_start_balance[profile_name] = current_value
            self._daily_start_time[profile_name] = current_time
            
            self.logger.info(
                f"[{profile_name}] Set daily start balance: ${current_value:.2f}"
            )
        
        return self._daily_start_balance.get(profile_name)
    
    def _reset_daily_start_balance(self, profile_name: str):
        """Reset daily start balance (called every 24h)"""
        portfolio = get_portfolio_cache()
        current_value = portfolio.get_total_value(profile_name, "USDC")
        
        old_balance = self._daily_start_balance.get(profile_name, 0)
        daily_pnl = current_value - old_balance
        daily_pnl_pct = (daily_pnl / old_balance * 100) if old_balance > 0 else 0
        
        self.logger.info(
            f"[{profile_name}] 24h Summary: "
            f"${old_balance:.2f} → ${current_value:.2f} "
            f"({daily_pnl_pct:+.2f}%)"
        )
        
        self._daily_start_balance[profile_name] = current_value
        self._daily_start_time[profile_name] = time.time()
    
    def _trigger_circuit_breaker(
        self,
        profile_name: str,
        reason: str,
        hours: int,
        trigger_value: Optional[Decimal] = None
    ):
        """Activate a circuit breaker"""
        current_time = time.time()
        reset_time = current_time + (hours * 3600)
        
        breaker = CircuitBreakerState(
            profile_name=profile_name,
            reason=reason,
            triggered_at=current_time,
            reset_at=reset_time,
            trigger_value=trigger_value
        )
        
        self._active_breakers[profile_name] = breaker
        
        self.logger.warning(
            f"[{profile_name}] 🚨 CIRCUIT BREAKER TRIGGERED: {reason} "
            f"(locked for {hours}h)"
        )
    
    def force_reset_breaker(self, profile_name: str) -> bool:
        """Manually reset a circuit breaker (admin function)"""
        if profile_name in self._active_breakers:
            breaker = self._active_breakers.pop(profile_name)
            self.logger.info(
                f"[{profile_name}] Circuit breaker manually reset: {breaker.reason}"
            )
            return True
        return False
    
    def get_all_breakers(self) -> Dict[str, dict]:
        """Get status of all active circuit breakers"""
        return {
            profile: breaker.to_dict()
            for profile, breaker in self._active_breakers.items()
            if breaker.is_active()
        }
    
    def get_daily_summary(self, profile_name: str) -> dict:
        """Get daily PnL summary for a profile"""
        daily_start = self._daily_start_balance.get(profile_name)
        
        if daily_start is None:
            return {
                "profile": profile_name,
                "error": "No daily start balance recorded"
            }
        
        portfolio = get_portfolio_cache()
        current_value = portfolio.get_total_value(profile_name, "USDC")
        
        daily_pnl = current_value - daily_start
        daily_pnl_pct = (daily_pnl / daily_start) * 100
        
        time_since_start = time.time() - self._daily_start_time.get(profile_name, time.time())
        
        return {
            "profile": profile_name,
            "daily_start_balance": str(daily_start),
            "current_balance": str(current_value),
            "daily_pnl": str(daily_pnl),
            "daily_pnl_pct": f"{daily_pnl_pct:+.2f}%",
            "hours_elapsed": round(time_since_start / 3600, 1),
            "profit_limit": f"+{self.max_daily_profit_pct}%",
            "loss_limit": f"-{self.max_daily_loss_pct}%",
            "circuit_breaker_active": profile_name in self._active_breakers
        }


# Global instance
_circuit_breaker = None


def get_circuit_breaker() -> CircuitBreakerService:
    """Get or create global circuit breaker instance"""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreakerService()
    return _circuit_breaker