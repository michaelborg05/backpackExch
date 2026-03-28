# services/circuit_breaker.py
from typing import Optional, Tuple
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from utils.logging import log_manager
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
    reset_circuit_breaker_baseline,
)


class CircuitBreakerService:
    """
    Database-backed circuit breaker service.

    Account-aware: when multiple profiles share the same ExchangeAccount,
    circuit breaker limits and daily snapshots are keyed by account_id so
    one lock covers all sibling profiles.

    Standalone profiles (account_id=None) fall back to profile_name lookups
    so all existing behaviour is preserved without any data changes.
    """

    def __init__(self):
        self.logger = log_manager.get_logger("CircuitBreaker")
        self._snapshot_update_counter = 0
        self._snapshot_update_interval = 10  # cycles between snapshot updates

    # ── Account helpers ───────────────────────────────────────────────────────

    def _get_account_id(self, profile_name: str) -> Optional[int]:
        """
        Return the account_id for this profile, or None if standalone.
        Never raises — any failure returns None so fallback logic applies.
        """
        try:
            from services.profile_manager import get_profile_manager
            pm = get_profile_manager()
            if pm is None:
                return None
            profile = pm.get_profile(profile_name)
            return getattr(profile, 'account_id', None) if profile else None
        except Exception as e:
            self.logger.debug(f"_get_account_id fallback for {profile_name}: {e}")
            return None

    def _get_portfolio_value(
        self,
        profile_name: str,
        account_id: Optional[int],
    ) -> Optional[Decimal]:
        """
        Return the portfolio value for this profile/account.

        For shared accounts we read from the canonical profile (lowest id)
        to avoid double-counting the same balance across siblings.
        For standalone profiles we read directly.
        """
        try:
            if account_id is not None:
                from services.profile_manager import get_profile_manager
                pm = get_profile_manager()
                if pm is not None:
                    canonical = pm.get_canonical_profile_for_account(account_id)
                    if canonical:
                        return get_portfolio_cache().get_total_value(
                            canonical.name, "USDC"
                        )
            return get_portfolio_cache().get_total_value(profile_name, "USDC")
        except Exception as e:
            self.logger.error(
                f"Error getting portfolio value for {profile_name}: {e}"
            )
            return None

    # ── Public API ────────────────────────────────────────────────────────────

    def check_circuit_breakers(
        self,
        profile_name: str,
        alert_action: str = "buy",
        check_pnl: bool = True,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if any circuit breakers should prevent trading.

        Uses account_id for DB lookups when available so a lock triggered
        by one profile blocks all siblings on the same account.

        Returns:
            (can_trade, block_reason)
        """
        account_id = self._get_account_id(profile_name)

        with get_db_session() as db:
            active_breaker = get_active_circuit_breaker(
                db, profile_name, account_id
            )

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
                    self._handle_breaker_expiration(
                        db, active_breaker, profile_name, account_id
                    )

            if alert_action.lower() != "buy":
                return True, None

            if check_pnl:
                should_trigger, trigger_reason = self._check_daily_pnl_limits(
                    db, profile_name, account_id
                )
                if should_trigger:
                    return False, trigger_reason

            return True, None

    def monitor_all_profiles(self):
        """
        Monitor all profiles and trigger circuit breakers if needed.

        Deduplicates by account_id so shared-account profiles are only
        checked once — avoids redundant balance reads and duplicate events.
        """
        from services.profile_manager import get_profile_manager

        profile_manager = get_profile_manager()
        if not profile_manager:
            return

        self._snapshot_update_counter += 1
        should_update_snapshots = (
            self._snapshot_update_counter >= self._snapshot_update_interval
        )

        # Track which account_ids (and standalone profile names) we've processed
        seen_account_ids: set = set()
        seen_standalone: set = set()

        with get_db_session() as db:
            for profile in profile_manager.get_all_profiles():
                account_id = self._get_account_id(profile.name)

                # Deduplicate shared accounts
                if account_id is not None:
                    if account_id in seen_account_ids:
                        self.logger.debug(
                            f"[{profile.name}] Skipping — "
                            f"account_id={account_id} already processed"
                        )
                        continue
                    seen_account_ids.add(account_id)
                else:
                    # Standalone profile — deduplicate by name
                    if profile.name in seen_standalone:
                        continue
                    seen_standalone.add(profile.name)

                try:
                    if should_update_snapshots:
                        self._update_balance_snapshot(
                            db, profile.name, account_id
                        )
                    self._check_daily_pnl_limits(db, profile.name, account_id)

                except Exception as e:
                    self.logger.error(
                        f"Error monitoring {profile.name} "
                        f"(account_id={account_id}): {e}",
                        exc_info=True,
                    )

        if should_update_snapshots:
            self._snapshot_update_counter = 0

    # ── Internal checks ───────────────────────────────────────────────────────

    def _handle_breaker_expiration(
        self,
        db,
        active_breaker,
        profile_name: str,
        account_id: Optional[int],
    ):
        """
        Handle circuit breaker expiration and CB baseline reset.
        Logs using profile_name for readability; all DB ops use account_id.
        """
        self.logger.info(
            f"[{profile_name}] Circuit breaker expired: {active_breaker.reason}"
        )

        expire_circuit_breaker(db, active_breaker.id)

        is_profit_limit = "profit" in active_breaker.reason.lower()

        if active_breaker.balance_at_trigger:
            snapshot = get_current_daily_snapshot(db, profile_name, account_id)

            if snapshot:
                old_baseline = (
                    snapshot.circuit_breaker_baseline or snapshot.starting_balance
                )
                new_baseline = (
                    active_breaker.balance_at_trigger
                    if is_profit_limit
                    else (old_baseline + active_breaker.balance_at_trigger) / 2
                )

                reset_circuit_breaker_baseline(db, snapshot.id, new_baseline)

                daily_pnl_pct = (
                    (new_baseline - snapshot.starting_balance)
                    / snapshot.starting_balance
                    * 100
                )
                self.logger.info(
                    f"[{profile_name}] 🔄 Reset CB baseline: "
                    f"${old_baseline:.2f} → ${new_baseline:.2f} "
                    f"(Daily start: ${snapshot.starting_balance:.2f} unchanged)"
                )
                self._send_telegram(
                    f"🔄 Circuit Breaker Reset [{profile_name}]\n"
                    f"Lock expired\n"
                    f"New CB baseline: ${new_baseline:.2f}\n"
                    f"Previous CB baseline: ${old_baseline:.2f}\n"
                    f"Daily start (unchanged): ${snapshot.starting_balance:.2f}\n"
                    f"% from day start: {daily_pnl_pct:+.2f}%"
                )

    def _check_daily_pnl_limits(
        self,
        db,
        profile_name: str,
        account_id: Optional[int],
    ) -> Tuple[bool, Optional[str]]:
        """
        Check daily P&L limits.

        - Config is per-profile (each profile can have its own limits).
        - Snapshot and events are per-account when account_id is set.
        - Balance is read from the canonical profile to avoid double-counting.
        """
        try:
            # Re-check for an active breaker first to avoid duplicate events
            active_breaker = get_active_circuit_breaker(
                db, profile_name, account_id
            )
            if active_breaker:
                now = datetime.now(timezone.utc)
                time_remaining = (active_breaker.reset_at - now).total_seconds()
                if time_remaining > 0:
                    return True, active_breaker.reason
                else:
                    self._handle_breaker_expiration(
                        db, active_breaker, profile_name, account_id
                    )

            config = get_circuit_breaker_config(db, profile_name)
            if not config:
                return False, None

            snapshot = get_current_daily_snapshot(db, profile_name, account_id)
            if not snapshot:
                return False, None

            current_value = self._get_portfolio_value(profile_name, account_id)
            if current_value is None or current_value <= 0:
                return False, "Current value not available or invalid"

            # Daily P&L — always from starting_balance for user-facing reporting
            daily_pnl = current_value - snapshot.starting_balance
            daily_pnl_pct = (daily_pnl / snapshot.starting_balance) * 100

            # CB baseline — may be shifted after profit limit resets
            cb_baseline = (
                snapshot.circuit_breaker_baseline
                if snapshot.circuit_breaker_baseline
                else snapshot.starting_balance
            )

            cb_pnl = current_value - cb_baseline
            cb_pnl_pct = (cb_pnl / cb_baseline) * 100

            self.logger.debug(
                f"[{profile_name}] CB PnL: {cb_pnl_pct:+.2f}% "
                f"from ${cb_baseline:.2f} "
                f"(Daily: {daily_pnl_pct:+.2f}% "
                f"from ${snapshot.starting_balance:.2f})"
            )

            # ── Profit limit ──────────────────────────────────────────────────
            if cb_pnl_pct >= float(config.max_daily_profit_pct):
                reason = (
                    f"Daily profit limit reached: "
                    f"+{cb_pnl_pct:.2f}% "
                    f"(limit: +{config.max_daily_profit_pct}%)"
                )
                create_circuit_breaker_event(
                    db=db,
                    profile_name=profile_name,
                    account_id=account_id,
                    reason=reason,
                    trigger_value_pct=cb_pnl_pct,
                    balance_at_trigger=current_value,
                    daily_start_balance=cb_baseline,
                    lock_hours=config.profit_lock_hours,
                )
                self._send_telegram(
                    f"🚨 CIRCUIT BREAKER TRIGGERED [{profile_name}]\n"
                    f"Profit limit: +{cb_pnl_pct:.2f}%\n"
                    f"Locked for: {config.profit_lock_hours}h\n"
                    f"Balance: ${current_value:.2f}"
                )
                self.logger.warning(
                    f"[{profile_name}] 🚨 CIRCUIT BREAKER TRIGGERED: {reason} "
                    f"(locked for {config.profit_lock_hours}h)"
                )
                return True, reason

            # ── Loss limit (drawdown from high water mark) ────────────────────
            drawdown_pnl = current_value - snapshot.highest_balance
            drawdown_pnl_pct = (drawdown_pnl / snapshot.highest_balance) * 100

            if drawdown_pnl_pct <= -float(config.max_daily_loss_pct):
                reason = (
                    f"Daily loss limit reached: "
                    f"{drawdown_pnl_pct:.2f}% "
                    f"(limit: -{config.max_daily_loss_pct}%)"
                )
                create_circuit_breaker_event(
                    db=db,
                    profile_name=profile_name,
                    account_id=account_id,
                    reason=reason,
                    trigger_value_pct=cb_pnl_pct,
                    balance_at_trigger=current_value,
                    daily_start_balance=cb_baseline,
                    lock_hours=config.loss_lock_hours,
                )
                self._send_telegram(
                    f"🚨 CIRCUIT BREAKER TRIGGERED [{profile_name}]\n"
                    f"Loss limit: {drawdown_pnl_pct:.2f}%\n"
                    f"Locked for: {config.loss_lock_hours}h\n"
                    f"Balance: ${current_value:.2f}"
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

    def _update_balance_snapshot(
        self,
        db,
        profile_name: str,
        account_id: Optional[int],
    ):
        """
        Update the daily balance snapshot.
        Snapshot is stored under account_id when available so all sibling
        profiles share one snapshot row.
        """
        try:
            snapshot = get_current_daily_snapshot(db, profile_name, account_id)
            current_value = self._get_portfolio_value(profile_name, account_id)

            if current_value is None:
                self.logger.warning(
                    f"[{profile_name}] Cannot update snapshot — "
                    f"portfolio value unavailable"
                )
                return

            now_utc = datetime.now(timezone.utc)

            if not snapshot:
                create_daily_snapshot(
                    db, profile_name, current_value, account_id
                )
                self.logger.info(
                    f"[{profile_name}] Created initial snapshot: "
                    f"${current_value:.2f}"
                )
                return

            snapshot_date = snapshot.snapshot_date.date()
            current_date = now_utc.date()

            if current_date > snapshot_date:
                # New UTC day — finalise old snapshot and open a new one
                finalize_daily_snapshot(db, snapshot.id, current_value)
                create_daily_snapshot(
                    db, profile_name, current_value, account_id
                )
                self.logger.info(
                    f"[{profile_name}] 🔄 UTC date changed — "
                    f"new snapshot: ${current_value:.2f} "
                    f"(previous day: {snapshot_date})"
                )
            else:
                update_daily_snapshot(db, snapshot.id, current_value)

                next_midnight = datetime.combine(
                    current_date + timedelta(days=1),
                    datetime.min.time(),
                ).replace(tzinfo=timezone.utc)
                hours_until_reset = (
                    next_midnight - now_utc
                ).total_seconds() / 3600

                self.logger.debug(
                    f"[{profile_name}] Updated snapshot "
                    f"(Current: ${current_value:.2f}, "
                    f"Reset in: {hours_until_reset:.1f}h)"
                )

        except Exception as e:
            self.logger.error(
                f"Error updating snapshot for {profile_name}: {e}",
                exc_info=True,
            )

    # ── Public management methods ─────────────────────────────────────────────

    def force_reset_breaker(self, profile_name: str) -> bool:
        """Manually reset the active circuit breaker for a profile or account."""
        account_id = self._get_account_id(profile_name)
        with get_db_session() as db:
            # manually_reset_circuit_breaker needs to know which row to reset
            # so we fetch it first using our account-aware helper
            event = get_active_circuit_breaker(db, profile_name, account_id)
            if not event:
                return False
            event.is_active = False
            event.manually_reset_at = datetime.now(timezone.utc)
            db.commit()
            self.logger.info(
                f"[{profile_name}] Circuit breaker manually reset: "
                f"{event.reason}"
            )
            return True

    def get_all_breakers(self) -> dict:
        """
        Get status of all active circuit breakers, deduplicated by account.
        Returns a dict keyed by account_id (or profile_name for standalones).
        """
        results = {}
        seen_account_ids: set = set()
        seen_standalone: set = set()

        with get_db_session() as db:
            from services.profile_manager import get_profile_manager
            profile_manager = get_profile_manager()
            if not profile_manager:
                return results

            for profile in profile_manager.get_all_profiles():
                account_id = self._get_account_id(profile.name)

                if account_id is not None:
                    if account_id in seen_account_ids:
                        continue
                    seen_account_ids.add(account_id)
                    result_key = f"account_{account_id}"
                else:
                    if profile.name in seen_standalone:
                        continue
                    seen_standalone.add(profile.name)
                    result_key = profile.name

                breaker = get_active_circuit_breaker(
                    db, profile.name, account_id
                )
                if not breaker:
                    continue

                now = datetime.now(timezone.utc)
                time_remaining = max(
                    0, (breaker.reset_at - now).total_seconds()
                )
                if time_remaining > 0:
                    results[result_key] = {
                        "profile":               profile.name,
                        "account_id":            account_id,
                        "reason":                breaker.reason,
                        "triggered_at":          breaker.triggered_at.isoformat(),
                        "reset_at":              breaker.reset_at.isoformat(),
                        "time_remaining_seconds": int(time_remaining),
                        "trigger_value":         (
                            str(breaker.trigger_value_pct)
                            if breaker.trigger_value_pct else None
                        ),
                    }

        return results

    def get_daily_summary(self, profile_name: str) -> dict:
        """
        Get daily P&L summary for a profile.
        Snapshot is read from the account-level row when account_id is set.
        """
        account_id = self._get_account_id(profile_name)

        with get_db_session() as db:
            config = get_circuit_breaker_config(db, profile_name)
            snapshot = get_current_daily_snapshot(db, profile_name, account_id)
            active_breaker = get_active_circuit_breaker(
                db, profile_name, account_id
            )
            current_value = self._get_portfolio_value(profile_name, account_id)

            if snapshot and current_value:
                daily_pnl = current_value - snapshot.starting_balance
                daily_pnl_pct = (daily_pnl / snapshot.starting_balance) * 100

                cb_baseline = (
                    snapshot.circuit_breaker_baseline
                    if snapshot.circuit_breaker_baseline
                    else max(
                        snapshot.starting_balance, snapshot.highest_balance
                    )
                )

                cb_pnl = current_value - cb_baseline
                cb_pnl_pct = (cb_pnl / cb_baseline) * 100

                now_utc = datetime.now(timezone.utc)
                next_midnight = datetime.combine(
                    now_utc.date() + timedelta(days=1),
                    datetime.min.time(),
                ).replace(tzinfo=timezone.utc)
                hours_until_reset = (
                    next_midnight - now_utc
                ).total_seconds() / 3600
            else:
                daily_pnl = daily_pnl_pct = None
                cb_pnl_pct = cb_baseline = hours_until_reset = None

            hours_remaining = (
                (
                    active_breaker.reset_at - datetime.now(timezone.utc)
                ).total_seconds() / 3600
                if active_breaker
                else None
            )

            return {
                "profile":                  profile_name,
                "account_id":               account_id,
                "daily_start_balance":      (
                    str(snapshot.starting_balance)
                    if snapshot else "No snapshot"
                ),
                "circuit_breaker_baseline": (
                    str(cb_baseline)
                    if cb_baseline else "Same as daily start"
                ),
                "current_balance":          str(current_value),
                "daily_pnl":                (
                    str(daily_pnl) if daily_pnl is not None else "N/A"
                ),
                "daily_pnl_pct":            (
                    f"{daily_pnl_pct:+.2f}%"
                    if daily_pnl_pct is not None else "N/A"
                ),
                "cb_pnl_pct":               (
                    f"{cb_pnl_pct:+.2f}%"
                    if cb_pnl_pct is not None else "N/A"
                ),
                "hours_until_reset":        (
                    round(hours_until_reset, 1)
                    if hours_until_reset else "N/A"
                ),
                "profit_limit":             (
                    f"+{config.max_daily_profit_pct}%" if config else "N/A"
                ),
                "loss_limit":               (
                    f"-{config.max_daily_loss_pct}%" if config else "N/A"
                ),
                "circuit_breaker_active":   active_breaker is not None,
                "hours_remaining":          (
                    round(hours_remaining, 2)
                    if hours_remaining else "N/A"
                ),
            }

    # ── Telegram helper ───────────────────────────────────────────────────────

    def _send_telegram(
        self,
        message: str,
        priority: MessagePriority = MessagePriority.NORMAL,
    ):
        try:
            telegram = get_telegram()
            if not telegram or not telegram._initialized:
                return
            telegram.send_message_sync(message, priority)
        except Exception as e:
            self.logger.debug(f"Could not send Telegram message: {e}")


# ── Global instance ───────────────────────────────────────────────────────────

_circuit_breaker: Optional[CircuitBreakerService] = None


def get_circuit_breaker() -> CircuitBreakerService:
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreakerService()
    return _circuit_breaker