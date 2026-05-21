# services/circuit_breaker.py
from typing import Optional, Tuple, Dict
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
    manually_expire_event,
    get_current_daily_snapshot,
    create_daily_snapshot,
    update_daily_snapshot,
    finalize_daily_snapshot,
    reset_circuit_breaker_baseline,
    adjust_snapshot_for_transfer,
)
from models.circuit_breaker import (
    CachedCircuitBreakerConfig,
    CachedCircuitBreakerEvent,
    CachedDailySnapshot,
)


# ── ORM → cache converters ────────────────────────────────────────────────────

def _to_cached_event(event) -> CachedCircuitBreakerEvent:
    return CachedCircuitBreakerEvent(
        id=event.id,
        profile_name=event.profile_name,
        account_id=event.account_id,
        reason=event.reason,
        triggered_at=event.triggered_at,
        reset_at=event.reset_at,
        balance_at_trigger=event.balance_at_trigger,
        trigger_value_pct=event.trigger_value_pct,
    )


def _to_cached_snapshot(snapshot) -> CachedDailySnapshot:
    return CachedDailySnapshot(
        id=snapshot.id,
        snapshot_date=snapshot.snapshot_date,
        starting_balance=snapshot.starting_balance,
        highest_balance=snapshot.highest_balance or snapshot.starting_balance,
        circuit_breaker_baseline=snapshot.circuit_breaker_baseline,
    )


class CircuitBreakerService:
    """
    Cache-backed circuit breaker service.

    In-memory caches for config, active events, and daily snapshots eliminate
    per-call DB reads during normal operation.  The DB is only hit on:
      - first use (state recovery after restart)
      - write-path operations (trigger, expire, reset, snapshot persist)
      - config TTL refresh (every 5 minutes)

    Account-aware: when multiple profiles share the same ExchangeAccount,
    circuit breaker limits and daily snapshots are keyed by account_id so
    one lock covers all sibling profiles.

    Standalone profiles (account_id=None) fall back to profile_name lookups
    so all existing behaviour is preserved without any data changes.
    """

    def __init__(self):
        self.logger = log_manager.get_logger("CircuitBreaker")
        self._snapshot_update_counter = 0
        self._snapshot_update_interval = 10  # cycles between snapshot DB writes

        # In-memory caches
        self._config_cache: Dict[str, CachedCircuitBreakerConfig] = {}   # keyed by profile_name
        self._event_cache: Dict[str, Optional[CachedCircuitBreakerEvent]] = {}   # keyed by cache_key
        self._snapshot_cache: Dict[str, CachedDailySnapshot] = {}                # keyed by cache_key
        self._initialized = False

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _cache_key(self, profile_name: str, account_id: int) -> str:
        return f"acct_{account_id}"

    def _ensure_initialized(self):
        if not self._initialized:
            self._load_state_from_db()

    def _load_state_from_db(self):
        """Bulk-load active events, snapshots, and configs from DB on startup."""
        self.logger.info("CircuitBreaker: loading state from DB")
        from services.profile_manager import get_profile_manager
        pm = get_profile_manager()
        if not pm:
            self._initialized = True
            return

        seen_account_ids: set = set()
        try:
            with get_db_session() as db:
                for profile in pm.get_all_profiles():
                    account_id = self._get_account_id(profile.name)
                    if account_id in seen_account_ids:
                        continue
                    seen_account_ids.add(account_id)
                    key = self._cache_key(profile.name, account_id)

                    event = get_active_circuit_breaker(db, profile.name, account_id)
                    self._event_cache[key] = _to_cached_event(event) if event else None

                    snapshot = get_current_daily_snapshot(db, account_id) if account_id else None
                    if snapshot:
                        self._snapshot_cache[key] = _to_cached_snapshot(snapshot)

                    config = get_circuit_breaker_config(db, profile.name)
                    if config:
                        self._config_cache[profile.name] = CachedCircuitBreakerConfig(
                            max_daily_profit_pct=config.max_daily_profit_pct,
                            max_daily_loss_pct=config.max_daily_loss_pct,
                            profit_lock_hours=config.profit_lock_hours,
                            loss_lock_hours=config.loss_lock_hours,
                        )
        except Exception as e:
            self.logger.error(
                f"Error loading circuit breaker state from DB: {e}", exc_info=True
            )
        self._initialized = True

    def _get_cached_config(self, profile_name: str) -> Optional[CachedCircuitBreakerConfig]:
        """Return config from cache. Only hits DB on cache miss (startup or after invalidate_config_cache())."""
        cached = self._config_cache.get(profile_name)
        if cached:
            return cached

        with get_db_session() as db:
            config = get_circuit_breaker_config(db, profile_name)

        if not config:
            return None

        cached = CachedCircuitBreakerConfig(
            max_daily_profit_pct=config.max_daily_profit_pct,
            max_daily_loss_pct=config.max_daily_loss_pct,
            profit_lock_hours=config.profit_lock_hours,
            loss_lock_hours=config.loss_lock_hours,
        )
        self._config_cache[profile_name] = cached
        return cached

    def _get_cached_event(
        self, profile_name: str, account_id: Optional[int]
    ) -> Optional[CachedCircuitBreakerEvent]:
        """Return active event from cache; loads from DB on first access for new profiles."""
        key = self._cache_key(profile_name, account_id)
        if key not in self._event_cache:
            with get_db_session() as db:
                event = get_active_circuit_breaker(db, profile_name, account_id)
            self._event_cache[key] = _to_cached_event(event) if event else None
        return self._event_cache[key]

    def _get_cached_snapshot(
        self, profile_name: str, account_id: Optional[int]
    ) -> Optional[CachedDailySnapshot]:
        """Return snapshot from cache; loads from DB on first access for new profiles."""
        key = self._cache_key(profile_name, account_id)
        if key not in self._snapshot_cache:
            with get_db_session() as db:
                snapshot = get_current_daily_snapshot(db, account_id) if account_id else None
            if snapshot:
                self._snapshot_cache[key] = _to_cached_snapshot(snapshot)
            else:
                return None
        return self._snapshot_cache.get(key)

    def invalidate_config_cache(self, profile_name: Optional[str] = None):
        """Force config re-fetch from DB on next access. Call after updating config."""
        if profile_name:
            self._config_cache.pop(profile_name, None)
        else:
            self._config_cache.clear()

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

        Hot path reads entirely from cache — no DB I/O unless a breaker
        expires (writes to DB) or a new limit is hit (writes to DB).

        Returns:
            (can_trade, block_reason)
        """
        self._ensure_initialized()
        account_id = self._get_account_id(profile_name)

        active_event = self._get_cached_event(profile_name, account_id)
        if active_event:
            now = datetime.now(timezone.utc)
            time_remaining = (active_event.reset_at - now).total_seconds()

            if time_remaining > 0:
                reason = (
                    f"Circuit breaker active: {active_event.reason} "
                    f"({int(time_remaining)}s remaining)"
                )
                self.logger.debug(f"[{profile_name}] {reason}")
                return False, reason
            else:
                self._handle_breaker_expiration(active_event, profile_name, account_id)

        if alert_action.lower() != "buy":
            return True, None

        if check_pnl:
            should_trigger, trigger_reason = self._check_daily_pnl_limits(
                profile_name, account_id
            )
            if should_trigger:
                return False, trigger_reason

        return True, None

    def monitor_all_profiles(self):
        """
        Monitor all profiles and trigger circuit breakers if needed.

        Snapshot writes are batched into a single DB session every N cycles.
        PnL limit checks read from cache; DB is only opened if a breaker fires.
        """
        from services.profile_manager import get_profile_manager

        self._ensure_initialized()
        profile_manager = get_profile_manager()
        if not profile_manager:
            return

        self._snapshot_update_counter += 1
        should_update_snapshots = (
            self._snapshot_update_counter >= self._snapshot_update_interval
        )

        seen_account_ids: set = set()

        with get_db_session() as db:
            for profile in profile_manager.get_all_profiles():
                account_id = self._get_account_id(profile.name)

                if account_id in seen_account_ids:
                    self.logger.debug(
                        f"[{profile.name}] Skipping — "
                        f"account_id={account_id} already processed"
                    )
                    continue
                seen_account_ids.add(account_id)

                try:
                    if should_update_snapshots:
                        self._update_balance_snapshot(db, profile.name, account_id)
                    # PnL check reads from cache; opens its own session only on trigger
                    self._check_daily_pnl_limits(profile.name, account_id)

                except Exception as e:
                    self.logger.error(
                        f"Error monitoring {profile.name} "
                        f"(account_id={account_id}): {e}",
                        exc_info=True,
                    )

        if should_update_snapshots:
            self._snapshot_update_counter = 0

    # ── Internal checks ───────────────────────────────────────────────────────

    def _apply_baseline_reset(
        self,
        db,
        event: CachedCircuitBreakerEvent,
        key: str,
        profile_name: str,
        reset_label: str,
    ):
        """
        Recalculate and persist the CB baseline after a breaker clears.

        Called by both natural expiry and manual reset so the next PnL check
        starts from a shifted baseline rather than immediately re-triggering.

        - Profit limit reset: baseline moves to balance_at_trigger (lock in the
          gains as the new floor).
        - Loss limit reset: baseline is averaged between old baseline and
          balance_at_trigger (partial recovery — softer re-entry).
        """
        if not event.balance_at_trigger:
            return

        cached_snap = self._snapshot_cache.get(key)
        if not cached_snap:
            return

        is_profit_limit = "profit" in event.reason.lower()
        old_baseline = (
            cached_snap.circuit_breaker_baseline or cached_snap.starting_balance
        )
        new_baseline = (
            event.balance_at_trigger
            if is_profit_limit
            else (old_baseline + event.balance_at_trigger) / 2
        )

        reset_circuit_breaker_baseline(db, cached_snap.id, new_baseline)
        cached_snap.circuit_breaker_baseline = new_baseline

        daily_pnl_pct = (
            (new_baseline - cached_snap.starting_balance)
            / cached_snap.starting_balance
            * 100
        )
        self.logger.info(
            f"[{profile_name}] 🔄 Reset CB baseline: "
            f"${old_baseline:.2f} → ${new_baseline:.2f} "
            f"(Daily start: ${cached_snap.starting_balance:.2f} unchanged)"
        )
        self._send_telegram(
            f"🔄 Circuit Breaker Reset [{profile_name}]\n"
            f"{reset_label}\n"
            f"New CB baseline: ${new_baseline:.2f}\n"
            f"Previous CB baseline: ${old_baseline:.2f}\n"
            f"Daily start (unchanged): ${cached_snap.starting_balance:.2f}\n"
            f"% from day start: {daily_pnl_pct:+.2f}%"
        )

    def _clear_breaker(
        self,
        event: CachedCircuitBreakerEvent,
        profile_name: str,
        account_id: Optional[int],
        *,
        manually_reset: bool = False,
    ):
        """
        Single code path for deactivating a breaker and resetting the CB baseline.
        Used by both natural expiry and manual reset.

        Clears the event cache immediately, then writes to DB and updates the
        snapshot cache via _apply_baseline_reset.
        """
        key = self._cache_key(profile_name, account_id)
        self._event_cache[key] = None

        reset_label = "Manually reset" if manually_reset else "Lock expired"

        with get_db_session() as db:
            if manually_reset:
                manually_expire_event(db, event.id)
            else:
                expire_circuit_breaker(db, event.id)
            self._apply_baseline_reset(db, event, key, profile_name, reset_label)

    def _handle_breaker_expiration(
        self,
        event: CachedCircuitBreakerEvent,
        profile_name: str,
        account_id: Optional[int],
    ):
        """Handle natural expiration — delegates to _clear_breaker."""
        self.logger.info(
            f"[{profile_name}] Circuit breaker expired: {event.reason}"
        )
        self._clear_breaker(event, profile_name, account_id, manually_reset=False)

    def _adjust_snapshot_for_transfer(
        self,
        profile_name: str,
        account_id: Optional[int],
        snapshot: CachedDailySnapshot,
        transfer_amount: Decimal,
    ) -> None:
        direction = "DEPOSIT" if transfer_amount > 0 else "WITHDRAWAL"
        snapshot.starting_balance += transfer_amount
        if transfer_amount > 0:
            # Deposit: the live balance already includes the deposit, so don't add
            # transfer_amount again — just ensure highest >= new starting
            snapshot.highest_balance = max(snapshot.highest_balance, snapshot.starting_balance)
        else:
            # Withdrawal: reset high water mark to new starting balance so the
            # drawdown check doesn't compare against a peak that included withdrawn funds
            snapshot.highest_balance = snapshot.starting_balance
        if snapshot.circuit_breaker_baseline is not None:
            snapshot.circuit_breaker_baseline += transfer_amount

        with get_db_session() as db:
            adjust_snapshot_for_transfer(
                db,
                snapshot.id,
                snapshot.starting_balance,
                snapshot.highest_balance,
                snapshot.circuit_breaker_baseline,
            )

        cb_baseline_str = f"${snapshot.circuit_breaker_baseline:.2f}" if snapshot.circuit_breaker_baseline is not None else "None"
        self.logger.info(
            f"[{profile_name}] {direction} detected (${abs(float(transfer_amount)):.2f}) — "
            f"CB baselines adjusted. starting=${snapshot.starting_balance:.2f}, "
            f"cb_baseline={cb_baseline_str}"
        )
        self._send_telegram(
            f"Transfer Detected [{profile_name}]\n"
            f"Type: {direction}\n"
            f"Amount: ${abs(float(transfer_amount)):.2f}\n"
            f"CB baselines adjusted — no circuit breaker triggered\n"
            f"New starting balance: ${snapshot.starting_balance:.2f}"
        )

    def _check_transfer_explains_change(
        self,
        profile_name: str,
        account_id: Optional[int],
        snapshot: CachedDailySnapshot,
        balance_change: Decimal,
        config: CachedCircuitBreakerConfig,
    ) -> bool:
        """
        Returns True if a recent deposit/withdrawal explains the balance change
        and snapshot baselines have been adjusted. Fail-safe: any error returns False.
        """
        cb_baseline = snapshot.circuit_breaker_baseline or snapshot.starting_balance
        if not cb_baseline or cb_baseline <= 0:
            return False

        threshold_pct =  max(
            float(config.max_daily_profit_pct),
            float(config.max_daily_loss_pct),
        )
        change_pct = abs(float(balance_change / cb_baseline * 100))
        if change_pct < threshold_pct:
            return False

        from services.profile_manager import get_profile_manager
        from api_builders.account_builder import get_recent_transfers
        from utils.settings_helper import SettingsHelper
        from utils.config import Config
        pm = get_profile_manager()
        profile = pm.get_profile(profile_name) if pm else None
        if not profile:
            return False

        try:
            _settings = SettingsHelper()
            _config = Config()
            cycle_seconds = (_settings.circuit_breaker_interval or 2) * (_config.monitor_delay_interval or 30)
            lookback_seconds = cycle_seconds + (_config.monitor_delay_interval or 30)  # one extra cycle as buffer
            transfers = get_recent_transfers(profile, lookback_seconds=lookback_seconds)
        except Exception as e:
            self.logger.warning(f"[{profile_name}] Transfer check failed: {e} — proceeding with CB trigger")
            return False

        if transfers is None:
            self.logger.warning(
                f"[{profile_name}] Transfer check API unavailable — proceeding with CB trigger"
            )
            return False

        net_transfer = Decimal(0)
        confirmed_statuses = {"confirmed", "complete", "completed", "success"}
        for deposit in transfers.get("deposits", []):
            if str(deposit.get("status", "")).lower() in confirmed_statuses:
                try:
                    net_transfer += Decimal(str(deposit.get("quantity", 0)))
                except Exception:
                    pass
        for withdrawal in transfers.get("withdrawals", []):
            if str(withdrawal.get("status", "")).lower() in confirmed_statuses:
                try:
                    net_transfer -= Decimal(str(withdrawal.get("quantity", 0)))
                except Exception:
                    pass

        if net_transfer == 0:
            self.logger.info(
                f"[{profile_name}] Suspicious balance change ({change_pct:.1f}%), "
                f"no confirming transfer found — proceeding with CB trigger"
            )
            return False

        tolerance = abs(float(balance_change)) * 0.05
        if abs(float(balance_change) - float(net_transfer)) <= tolerance:
            self._adjust_snapshot_for_transfer(profile_name, account_id, snapshot, net_transfer)
            return True

        return False

    def _check_daily_pnl_limits(
        self,
        profile_name: str,
        account_id: Optional[int],
    ) -> Tuple[bool, Optional[str]]:
        """
        Check daily P&L limits using cached config and snapshot.

        highest_balance is updated in-memory every call so drawdown tracking
        is always current even between periodic DB snapshot writes.
        DB is opened only when a limit is hit (to create the breaker event).
        """
        try:
            # Re-check for an active event from cache to avoid duplicate triggers
            active_event = self._get_cached_event(profile_name, account_id)
            if active_event:
                now = datetime.now(timezone.utc)
                time_remaining = (active_event.reset_at - now).total_seconds()
                if time_remaining > 0:
                    return True, active_event.reason
                else:
                    self._handle_breaker_expiration(
                        active_event, profile_name, account_id
                    )

            config = self._get_cached_config(profile_name)
            if not config:
                return False, None

            snapshot = self._get_cached_snapshot(profile_name, account_id)
            if not snapshot:
                return False, None

            current_value = self._get_portfolio_value(profile_name, account_id)
            if current_value is None or current_value <= 0:
                return False, "Current value not available or invalid"

            # Keep highest_balance up-to-date in the cache on every check
            if current_value > (snapshot.highest_balance or Decimal(0)):
                snapshot.highest_balance = current_value

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
                balance_change = current_value - snapshot.starting_balance
                if self._check_transfer_explains_change(
                    profile_name, account_id, snapshot, balance_change, config
                ):
                    self.logger.info(
                        f"[{profile_name}] Profit limit apparent breach suppressed — "
                        f"deposit detected and baselines adjusted"
                    )
                    return False, None
                reason = (
                    f"Daily profit limit reached: "
                    f"+{cb_pnl_pct:.2f}% "
                    f"(limit: +{config.max_daily_profit_pct}%)"
                )
                key = self._cache_key(profile_name, account_id)
                with get_db_session() as db:
                    event = create_circuit_breaker_event(
                        db=db,
                        profile_name=profile_name,
                        account_id=account_id,
                        reason=reason,
                        trigger_value_pct=cb_pnl_pct,
                        balance_at_trigger=current_value,
                        daily_start_balance=cb_baseline,
                        lock_hours=config.profit_lock_hours,
                    )
                    self._event_cache[key] = _to_cached_event(event)
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
                balance_change = current_value - snapshot.highest_balance
                if self._check_transfer_explains_change(
                    profile_name, account_id, snapshot, balance_change, config
                ):
                    self.logger.info(
                        f"[{profile_name}] Loss limit apparent breach suppressed — "
                        f"withdrawal detected and baselines adjusted"
                    )
                    return False, None
                reason = (
                    f"Daily loss limit reached: "
                    f"{drawdown_pnl_pct:.2f}% "
                    f"(limit: -{config.max_daily_loss_pct}%)"
                )
                key = self._cache_key(profile_name, account_id)
                with get_db_session() as db:
                    event = create_circuit_breaker_event(
                        db=db,
                        profile_name=profile_name,
                        account_id=account_id,
                        reason=reason,
                        trigger_value_pct=drawdown_pnl_pct,
                        balance_at_trigger=current_value,
                        daily_start_balance=cb_baseline,
                        lock_hours=config.loss_lock_hours,
                    )
                    self._event_cache[key] = _to_cached_event(event)
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
        Persist the daily balance snapshot to DB and keep the cache in sync.
        Called every N cycles from monitor_all_profiles with a shared session.
        """
        try:
            key = self._cache_key(profile_name, account_id)
            cached_snap = self._snapshot_cache.get(key)
            current_value = self._get_portfolio_value(profile_name, account_id)

            if current_value is None:
                self.logger.warning(
                    f"[{profile_name}] Cannot update snapshot — "
                    f"portfolio value unavailable"
                )
                return

            now_utc = datetime.now(timezone.utc)

            if not cached_snap:
                new_snap = create_daily_snapshot(
                    db,
                    account_id=account_id,
                    starting_balance=current_value,
                    profile_name=profile_name,
                )
                self._snapshot_cache[key] = _to_cached_snapshot(new_snap)
                self.logger.info(
                    f"[{profile_name}] Created initial snapshot: "
                    f"${current_value:.2f}"
                )
                return

            snapshot_date = cached_snap.snapshot_date.date()
            current_date = now_utc.date()

            if current_date > snapshot_date:
                # New UTC day — finalise old snapshot and open a new one
                finalize_daily_snapshot(db, cached_snap.id, current_value)
                new_snap = create_daily_snapshot(
                    db,
                    account_id=account_id,
                    starting_balance=current_value,
                    profile_name=profile_name,
                )
                self._snapshot_cache[key] = _to_cached_snapshot(new_snap)
                self.logger.info(
                    f"[{profile_name}] 🔄 UTC date changed — "
                    f"new snapshot: ${current_value:.2f} "
                    f"(previous day: {snapshot_date})"
                )
            else:
                update_daily_snapshot(db, cached_snap.id, current_value)

                # Keep cache in sync with what we just persisted
                if current_value > (cached_snap.highest_balance or Decimal(0)):
                    cached_snap.highest_balance = current_value

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
        """
        Manually reset the active circuit breaker for a profile or account.

        Delegates to _clear_breaker so the baseline reset logic is identical
        to natural expiry — preventing an immediate re-trigger on the next cycle.
        """
        self._ensure_initialized()
        account_id = self._get_account_id(profile_name)
        key = self._cache_key(profile_name, account_id)

        cached_event = self._event_cache.get(key)
        if not cached_event:
            return False

        self._clear_breaker(cached_event, profile_name, account_id, manually_reset=True)
        self.logger.info(
            f"[{profile_name}] Circuit breaker manually reset: "
            f"{cached_event.reason}"
        )
        return True

    def get_all_breakers(self) -> dict:
        """
        Get status of all active circuit breakers, deduplicated by account.
        Returns a dict keyed by account_id (or profile_name for standalones).
        Reads entirely from cache — no DB I/O.
        """
        self._ensure_initialized()
        results = {}
        seen_account_ids: set = set()
        seen_standalone: set = set()
        now = datetime.now(timezone.utc)

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

            key = self._cache_key(profile.name, account_id)
            event = self._event_cache.get(key)
            if not event:
                continue

            time_remaining = max(0, (event.reset_at - now).total_seconds())
            if time_remaining <= 0:
                continue

            results[result_key] = {
                "profile":                profile.name,
                "account_id":             account_id,
                "reason":                 event.reason,
                "triggered_at":           event.triggered_at.isoformat(),
                "reset_at":               event.reset_at.isoformat(),
                "time_remaining_seconds": int(time_remaining),
                "trigger_value":          (
                    str(event.trigger_value_pct)
                    if event.trigger_value_pct else None
                ),
            }

        return results

    def get_day_start(self, profile_name: str) -> Optional[datetime]:
        """Return the snapshot_date (day-start) for this profile's account, or None."""
        self._ensure_initialized()
        account_id = self._get_account_id(profile_name)
        snapshot = self._get_cached_snapshot(profile_name, account_id)
        return snapshot.snapshot_date if snapshot else None

    def get_daily_summary(self, profile_name: str) -> dict:
        """
        Get daily P&L summary for a profile.
        Reads from cache — no DB I/O.
        """
        self._ensure_initialized()
        account_id = self._get_account_id(profile_name)

        config = self._get_cached_config(profile_name)
        snapshot = self._get_cached_snapshot(profile_name, account_id)
        active_event = self._get_cached_event(profile_name, account_id)
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

            highest = snapshot.highest_balance or snapshot.starting_balance
            drawdown_pnl = current_value - highest
            drawdown_pnl_pct = (drawdown_pnl / highest) * 100

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
            drawdown_pnl_pct = highest = None

        hours_remaining = (
            (
                active_event.reset_at - datetime.now(timezone.utc)
            ).total_seconds() / 3600
            if active_event
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
            "highest_balance":          (
                str(highest) if highest is not None else "N/A"
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
            "drawdown_pnl_pct":         (
                f"{drawdown_pnl_pct:+.2f}%"
                if drawdown_pnl_pct is not None else "N/A"
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
            "circuit_breaker_active":   active_event is not None,
            "event_reason":             active_event.reason if active_event else None,
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
