# services/circuit_breaker.py
from typing import Optional, Tuple
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from utils.logging import log_manager
from cache.balance_cache import get_balance_cache
from cache.portfolio_cache import get_portfolio_cache
from services.telegram_service import get_telegram
from utils.constants import MessagePriority
from db.utils import get_db_session
from db.crud import (
    get_circuit_breaker_config,
    get_active_circuit_breaker,
    create_circuit_breaker_event,
    expire_circuit_breaker,
    manually_reset_circuit_breaker,
    get_current_daily_snapshot,
    create_daily_snapshot,
    update_daily_snapshot,
    finalize_daily_snapshot,
    reset_circuit_breaker_baseline 
)


class CircuitBreakerService:
    """
    Database-backed circuit breaker service
    - Config stored in DB (per profile)
    - Events logged to DB for persistence
    - Balance snapshots saved every 5 minutes
    - Uses circuit_breaker_baseline to prevent lock loops while preserving historical data
    """
    
    def __init__(self):
        self.logger = log_manager.get_logger("CircuitBreaker")
        self._snapshot_update_counter = 0
        self._snapshot_update_interval = 10  # Update snapshots every 10 cycles (~5 min if 30s cycle)
    
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
            check_pnl: Whether to check PnL limits
            
        Returns:
            (can_trade, block_reason) tuple
        """
        with get_db_session() as db:
            # Check if there's an active circuit breaker in DB
            active_breaker = get_active_circuit_breaker(db, profile_name)
            
            if active_breaker:
                now = datetime.now(timezone.utc)
                time_remaining = (active_breaker.reset_at - now).total_seconds()
                
                if time_remaining > 0:
                    reason = (
                        f"Circuit breaker active: {active_breaker.reason} "
                        f"({int(time_remaining)}s remaining)"
                    )
                    self.logger.debug(f"[{profile_name}] {reason}")
                    return False, reason
                else:
                    # Breaker expired - handle baseline reset
                    self._handle_breaker_expiration(db, active_breaker, profile_name)
            
            # Only check for BUY orders
            if alert_action.lower() != "buy":
                return True, None
            
            # Check daily PnL limits
            if check_pnl:
                should_trigger, trigger_reason = self._check_daily_pnl_limits(
                    db, profile_name
                )
                
                if should_trigger:
                    return False, trigger_reason
            
            return True, None
    
    def _handle_breaker_expiration(self, db, active_breaker, profile_name: str):
        """
        Handle circuit breaker expiration
        
        For PROFIT limits: Reset circuit_breaker_baseline to avoid lock loops
        For LOSS limits: reset circuit_breaker_baseline to half the gap between starting balance and current
        """
        self.logger.info(
            f"[{profile_name}] Circuit breaker expired: {active_breaker.reason}"
        )
        
        # Mark breaker as expired
        expire_circuit_breaker(db, active_breaker.id)
        
        # Check if this was a profit limit (not a loss limit)
        is_profit_limit = "profit" in active_breaker.reason.lower()
        
        if active_breaker.balance_at_trigger:
            # Reset circuit breaker baseline (NOT starting_balance - that stays for historical tracking)
            snapshot = get_current_daily_snapshot(db, profile_name)
            
            if snapshot:
                old_baseline = snapshot.circuit_breaker_baseline or snapshot.starting_balance
                #If profit, reset baseline to new balance
                # if loss, reset balance to half way between both balances
                new_baseline = ( active_breaker.balance_at_trigger if is_profit_limit else (old_baseline + active_breaker.balance_at_trigger) / 2 )
                
                
                reset_circuit_breaker_baseline(db, snapshot.id, new_baseline)
                
                self.logger.info(
                    f"[{profile_name}] 🔄 Reset circuit breaker baseline: "
                    f"${old_baseline:.2f} → ${new_baseline:.2f} "
                    f"(Daily start: ${snapshot.starting_balance:.2f} unchanged)"
                )
                
                daily_pnl_pct = ((new_baseline - snapshot.starting_balance) / snapshot.starting_balance * 100)
                # Send notification
                self._send_telegram(
                        f"🔄 Circuit Breaker Reset [{profile_name}]\n"
                        f"lock expired\n"
                        f"New CB baseline: ${new_baseline:.2f}\n"
                        f"Previous CB baseline: ${old_baseline:.2f}\n"
                        f"Daily start (unchanged): ${snapshot.starting_balance:.2f}\n"
                        f"% from day start: {daily_pnl_pct:+.2f}%"
                    )
    
    def monitor_all_profiles(self):
        """
        Monitor all profiles and trigger circuit breakers if needed
        Also updates balance snapshots periodically
        """
        from services.profile_manager import get_profile_manager
        
        profile_manager = get_profile_manager()
        if not profile_manager:
            return
        
        self._snapshot_update_counter += 1
        should_update_snapshots = (
            self._snapshot_update_counter >= self._snapshot_update_interval
        )
        
        with get_db_session() as db:
            for profile in profile_manager.get_all_profiles():
                try:
                    # Update balance snapshot periodically (every ~5 min)
                    if should_update_snapshots:
                        self._update_balance_snapshot(db, profile.name)
                    
                    # Check if circuit breaker should trigger
                    self._check_daily_pnl_limits(db, profile.name)
                    
                except Exception as e:
                    self.logger.error(
                        f"Error monitoring {profile.name}: {e}",
                        exc_info=True
                    )
        
        if should_update_snapshots:
            self._snapshot_update_counter = 0
    
    def _check_daily_pnl_limits(
        self, 
        db, 
        profile_name: str
    ) -> Tuple[bool, Optional[str]]:
        """Check if daily PnL has exceeded limits"""
        try:
            # CRITICAL: Check for active breaker FIRST before any calculations
            # This prevents duplicate events on restart and saves CPU cycles
            active_breaker = get_active_circuit_breaker(db, profile_name)
            if active_breaker:
                now = datetime.now(timezone.utc)
                
                time_remaining = (active_breaker.reset_at - now).total_seconds()
                if time_remaining > 0:
                    # Already active - don't re-check or re-trigger
                    # Only log at debug level to avoid spam
                    return True, active_breaker.reason
                else:
                    # Expired - handle expiration (which may reset baseline)
                    self._handle_breaker_expiration(db, active_breaker, profile_name)
            
            # Get config
            config = get_circuit_breaker_config(db, profile_name)
            if not config:
                return False, None

            #Get current profile balance            
            portfolio = get_portfolio_cache()
            current_value = portfolio.get_total_value(profile_name, "USDC")

            # Get most recent snapshot 
            snapshot = get_current_daily_snapshot(db, profile_name)
            #If no snapshot for profile, create and return false
            if not snapshot:
                # Create initial snapshot
                create_daily_snapshot(db, profile_name, current_value)
                return False, None

            if snapshot:
                #If snapshot found, confirm age is within 24 hours
                snapshot_age = (
                    datetime.now(timezone.utc) - snapshot.snapshot_date
                ).total_seconds() / 3600
                
                if snapshot_age >= 24:
                    # Finalize old snapshot and create new one. Return false as pnl cannot be calculated on first entry of the day
                    finalize_daily_snapshot(db, snapshot.id, current_value)
                    
                    # Create new snapshot
                    create_daily_snapshot(db, profile_name, current_value)
                    return False, None


            # ⭐ KEY CHANGE: Use circuit_breaker_baseline if set, otherwise use starting_balance
            # This allows profit limit resets without losing historical tracking
            cb_baseline = snapshot.circuit_breaker_baseline or snapshot.starting_balance
            
            
            # Calculate PnL from circuit breaker baseline
            cb_pnl_pct = ((current_value - cb_baseline) / cb_baseline) * 100
            
            # Also calculate actual daily PnL for logging (from starting_balance)
            daily_pnl_pct = ((current_value - snapshot.starting_balance) / snapshot.starting_balance) * 100
            
            self.logger.debug(
                f"[{profile_name}] CB PnL: {cb_pnl_pct:+.2f}% from ${cb_baseline:.2f} "
                f"(Daily: {daily_pnl_pct:+.2f}% from ${snapshot.starting_balance:.2f})"
            )
            
            # Check profit limit using circuit breaker baseline
            if cb_pnl_pct >= float(config.max_daily_profit_pct):
                reason = (
                    f"Daily profit limit reached: {cb_pnl_pct:+.2f}% "
                    f"(limit: +{config.max_daily_profit_pct}%)"
                )
                
                create_circuit_breaker_event(
                    db,
                    profile_name=profile_name,
                    reason=reason,
                    trigger_value_pct=Decimal(str(cb_pnl_pct)),
                    balance_at_trigger=current_value,
                    daily_start_balance=cb_baseline,  # Store the baseline used for this trigger
                    lock_hours=config.profit_lock_hours
                )
                
                self.logger.warning(
                    f"[{profile_name}] 🚨 CIRCUIT BREAKER TRIGGERED: {reason} "
                    f"(locked for {config.profit_lock_hours}h) "
                    f"[Actual daily PnL: {daily_pnl_pct:+.2f}%]"
                )
                
                self._send_telegram(
                    f"🚨 CIRCUIT BREAKER TRIGGERED: {reason} \n"
                    f"locked for {config.profit_lock_hours}h) "
                    f"daily PnL: {daily_pnl_pct:+.2f}%\n"
                )
                return True, reason
            
          
            if cb_pnl_pct <= -float(config.max_daily_loss_pct):
                reason = (
                    f"Daily loss limit reached: {cb_pnl_pct:+.2f}% "
                    f"(limit: -{config.max_daily_loss_pct}%)"
                )
                
                create_circuit_breaker_event(
                    db,
                    profile_name=profile_name,
                    reason=reason,
                    trigger_value_pct=Decimal(str(cb_pnl_pct)),
                    balance_at_trigger=current_value,
                    daily_start_balance=cb_baseline,
                    lock_hours=config.loss_lock_hours
                )
                
                self.logger.warning(
                    f"[{profile_name}] 🚨 CIRCUIT BREAKER TRIGGERED: {reason} "
                    f"(locked for {config.loss_lock_hours}h)"
                )
                
                return True, reason
            
            return False, None
            
        except Exception as e:
            self.logger.error(f"Error checking PnL limits: {e}", exc_info=True)
            return False, None
    
    def _update_balance_snapshot(self, db, profile_name: str):
        """Update current snapshot with latest balance"""
        try:
            snapshot = get_current_daily_snapshot(db, profile_name)
            portfolio = get_portfolio_cache()
            current_value = portfolio.get_total_value(profile_name, "USDC")
            
            if not snapshot:
                # Create initial snapshot
                create_daily_snapshot(db, profile_name, current_value)
                self.logger.info(
                    f"[{profile_name}] Created initial snapshot: ${current_value:.2f}"
                )
                return
            
            # Check if snapshot is older than 24 hours
            snapshot_age = (
                datetime.now(timezone.utc) - snapshot.snapshot_date
            ).total_seconds() / 3600
            
            if snapshot_age >= 24:
                # Finalize old snapshot with ending values
                finalize_daily_snapshot(db, snapshot.id, current_value)
                                
                # Create new snapshot for the next 24h period
                create_daily_snapshot(db, profile_name, current_value)
                
                self.logger.info(
                    f"[{profile_name}] 🔄 Created new 24h snapshot: ${current_value:.2f}"
                )
            else:
                # Update existing snapshot (high/low tracking)
                update_daily_snapshot(db, snapshot.id, current_value)
                
                self.logger.debug(
                    f"[{profile_name}] Updated snapshot "
                    f"(Age: {snapshot_age:.1f}h, Current: ${current_value:.2f})"
                )
                
        except Exception as e:
            self.logger.error(
                f"Error updating snapshot for {profile_name}: {e}",
                exc_info=True
            )
    
    def force_reset_breaker(self, profile_name: str) -> bool:
        """Manually reset a circuit breaker"""
        with get_db_session() as db:
            event = manually_reset_circuit_breaker(db, profile_name)
            
            if event:
                self.logger.info(
                    f"[{profile_name}] Circuit breaker manually reset: {event.reason}"
                )
                return True
            
            return False
    
    def get_all_breakers(self) -> dict:
        """Get status of all active circuit breakers"""
        results = {}
        
        with get_db_session() as db:
            from services.profile_manager import get_profile_manager
            profile_manager = get_profile_manager()
            
            if not profile_manager:
                return results
            
            for profile in profile_manager.get_all_profiles():
                breaker = get_active_circuit_breaker(db, profile.name)
                
                if breaker:
                    now = datetime.now(timezone.utc)
                    time_remaining = max(0, (breaker.reset_at - now).total_seconds())
                    
                    if time_remaining > 0:
                        results[profile.name] = {
                            "profile": profile.name,
                            "reason": breaker.reason,
                            "triggered_at": breaker.triggered_at.isoformat(),
                            "reset_at": breaker.reset_at.isoformat(),
                            "time_remaining_seconds": int(time_remaining),
                            "trigger_value": str(breaker.trigger_value_pct) if breaker.trigger_value_pct else None
                        }
        
        return results
    
    def get_daily_summary(self, profile_name: str) -> dict:
        """Get daily PnL summary for a profile"""
        with get_db_session() as db:
            config = get_circuit_breaker_config(db, profile_name)
            snapshot = get_current_daily_snapshot(db, profile_name)
            active_breaker = get_active_circuit_breaker(db, profile_name)
            
            portfolio = get_portfolio_cache()
            current_value = portfolio.get_total_value(profile_name, "USDC")
            
            if snapshot:
                # Actual daily PnL (from starting_balance - never changes)
                daily_pnl = current_value - snapshot.starting_balance
                daily_pnl_pct = (daily_pnl / snapshot.starting_balance) * 100
                
                # Circuit breaker PnL (from circuit_breaker_baseline - may be reset)
                cb_baseline = snapshot.circuit_breaker_baseline or snapshot.starting_balance
                cb_pnl = current_value - cb_baseline
                cb_pnl_pct = (cb_pnl / cb_baseline) * 100
                
                snapshot_age = (
                    datetime.now(timezone.utc) - snapshot.snapshot_date
                ).total_seconds() / 3600
            else:
                daily_pnl = None
                daily_pnl_pct = None
                cb_pnl_pct = None
                cb_baseline = None
                snapshot_age = None
            
            if active_breaker is not None:
                hours_remaining = (active_breaker.reset_at - datetime.now(timezone.utc)).total_seconds()/3600
            else: 
                hours_remaining = None

            return {
                "profile": profile_name,
                "daily_start_balance": str(snapshot.starting_balance) if snapshot else "No snapshot",
                "circuit_breaker_baseline": str(cb_baseline) if cb_baseline else "Same as daily start",
                "current_balance": str(current_value),
                "daily_pnl": str(daily_pnl) if daily_pnl else "N/A",
                "daily_pnl_pct": f"{daily_pnl_pct:+.2f}%" if daily_pnl_pct else "N/A",
                "cb_pnl_pct": f"{cb_pnl_pct:+.2f}%" if cb_pnl_pct is not None else "N/A",
                "hours_elapsed": round(snapshot_age, 1) if snapshot_age else "N/A",
                "profit_limit": f"+{config.max_daily_profit_pct}%" if config else "N/A",
                "loss_limit": f"-{config.max_daily_loss_pct}%" if config else "N/A",
                "circuit_breaker_active": active_breaker is not None,
                "hours_remaining": round(hours_remaining, 2) if hours_remaining else "N/A"
            }

    def _send_telegram(self, message: str, priority: MessagePriority = MessagePriority.NORMAL):
        """
        Helper to send Telegram messages from sync monitoring thread.
        Uses thread-safe scheduling to main event loop.
        """
        
        try:
            telegram = get_telegram()
            if not telegram:
                return
            
            if not telegram._initialized:
                self.logger.debug("Telegram not initialized - skipping message")
                return
            
            # Use the thread-safe sync wrapper
            success = telegram.send_message_sync(message, priority)
            
            if not success:
                # Only log if we're still running (not shutting down)
                if self.is_running and telegram._initialized:
                    self.logger.debug(f"Failed to send Telegram message (may be shutting down)")
                    
        except Exception as e:
            # Catch any unexpected errors
            if self.is_running:
                self.logger.debug(f"Could not send Telegram message: {e}")


# Global instance
_circuit_breaker = None

def get_circuit_breaker() -> CircuitBreakerService:
    """Get or create global circuit breaker instance"""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreakerService()
    return _circuit_breaker