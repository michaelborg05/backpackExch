# services/health_alerting_service.py
"""
Standalone health alerting service that runs independently of the main monitoring loop.
Checks core system health and sends Telegram alerts when issues are detected.

Intentionally kept simple and isolated - this service should never crash the main app.
"""

import time
import threading
import httpx
from typing import Optional
from utils.logging import log_manager
from utils.config import Config
from utils.constants import MessagePriority
from utils.settings_helper import get_settings_helper

class HealthAlertingService:
    """
    Lightweight, independent health monitor.
    
    Runs in its own thread, separate from the monitoring loop.
    Checks:
      1. Monitoring loop is alive (thread running + recent activity)
      2. API server is responding
      3. Trend cache is fresh (candle fetcher / Binance feed still updating it)
      4. Price cache is fresh (exchange price fetches still working)
      5. Candle fetcher service itself is alive and completing cycles
    
    Sends Telegram alerts when issues are detected, with cooldown to avoid spam.
    """

    def __init__(
        self,
    ):
        self.logger = log_manager.get_logger("HealthAlertingService")
        self.config = Config()
        self._start_time: Optional[float] = None
        self.settings = get_settings_helper()

        self.check_interval = self.settings.alert_healthcheck_interval      # How often to run health checks
        self.trend_max_age = self.settings.alert_trend_max_age              # Floor for the per-timeframe trend staleness thresholds (see _trend_allowed_age)
        self.price_max_age = self.settings.alert_price_max_age              # How stale price data can be before we alert (monitoring loop runs every 30s)
        self.re_alert_cooldown = self.settings.alert_re_alert_cooldown      # How often to re-alert on the same issue (avoid spam)
        self.startup_grace_period = self.settings.alert_startup_grace_period    #time after startup before enabling the alerting

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()


        # Track last alert times per issue key so we don't spam
        self._last_alerted: dict[str, float] = {}

        # Track which issues are currently active (for recovery alerts)
        self._active_issues: set[str] = set()

        # Reference to monitoring service (set after construction)
        self._monitoring_service = None

    def set_monitoring_service(self, monitoring_service) -> None:
        """Inject the monitoring service so we can check its thread health."""
        self._monitoring_service = monitoring_service

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """Start the health check loop in a background thread."""
        if self._thread and self._thread.is_alive():
            self.logger.warning("HealthAlertingService already running")
            return

        self._stop_event.clear()
        self._start_time = time.time()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="HealthAlertingService",
            daemon=True,
        )
        self._thread.start()
        self.logger.info(
            f"✅ HealthAlertingService started "
            f"(interval={self.check_interval}s, "
            f"trend_max_age={self.trend_max_age}s, "
            f"price_max_age={self.price_max_age}s)"
        )

    def stop(self) -> None:
        """Stop the health check loop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.logger.info("HealthAlertingService stopped")

    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Main health check loop. Catches all exceptions to stay alive."""
        self.logger.info("Health check loop starting...")

        while not self._stop_event.is_set():
            try:
                elapsed = time.time() - (self._start_time or 0)
                if elapsed < self.startup_grace_period:
                    remaining = int(self.startup_grace_period - elapsed)
                    self.logger.debug(f"Startup grace period active — {remaining}s remaining, skipping checks")
                    self._stop_event.wait(timeout=self.check_interval)
                    continue

                self._run_checks()
            except Exception as e:
                # Never let an exception kill this thread
                self.logger.error(f"Unexpected error in health check loop: {e}", exc_info=True)

            self._stop_event.wait(timeout=self.check_interval)

        self.logger.info("Health check loop exited")

    def _run_checks(self) -> None:
        """Run all health checks."""
        self._check_monitoring_loop()
        self._check_api_server()
        self._check_trend_cache()
        self._check_price_cache()
        self._check_candle_fetcher()

    # -------------------------------------------------------------------------
    # Individual checks
    # -------------------------------------------------------------------------

    def _check_monitoring_loop(self) -> None:
        """Check that the monitoring service thread is alive."""
        issue_key = "monitoring_loop_dead"

        if self._monitoring_service is None:
            # Not injected yet - skip
            return

        try:
            thread: Optional[threading.Thread] = getattr(self._monitoring_service, "thread", None)
            is_running: bool = getattr(self._monitoring_service, "is_running", False)
            thread_alive = thread is not None and thread.is_alive()

            if not thread_alive or not is_running:
                self._trigger_alert(
                    issue_key=issue_key,
                    message=(
                        "🚨 <b>MONITORING LOOP DOWN</b>\n\n"
                        f"Thread alive: {thread_alive}\n"
                        f"is_running flag: {is_running}\n\n"
                        "The main monitoring loop has stopped. "
                        "Price checks and signal processing are NOT running."
                    ),
                )
            else:
                self._clear_alert(
                    issue_key=issue_key,
                    recovery_message="✅ <b>Monitoring loop recovered</b> — thread is alive again.",
                )

        except Exception as e:
            self.logger.error(f"Error checking monitoring loop: {e}")

    def _check_api_server(self) -> None:
        """Check that the FastAPI server is responding to HTTP requests."""
        issue_key = "api_server_down"
        url = f"http://localhost:{self.config.port}/health"

        try:
            response = httpx.get(url, timeout=5.0)
            if response.status_code == 200:
                self._clear_alert(
                    issue_key=issue_key,
                    recovery_message="✅ <b>API server recovered</b> — health endpoint responding.",
                )
            else:
                self._trigger_alert(
                    issue_key=issue_key,
                    message=(
                        f"⚠️ <b>API SERVER UNHEALTHY</b>\n\n"
                        f"Health endpoint returned HTTP {response.status_code}.\n"
                        f"URL: <code>{url}</code>"
                    ),
                )
        except httpx.ConnectError:
            self._trigger_alert(
                issue_key=issue_key,
                message=(
                    "🚨 <b>API SERVER DOWN</b>\n\n"
                    f"Could not connect to <code>{url}</code>.\n"
                    "The FastAPI server may have crashed."
                ),
            )
        except Exception as e:
            self.logger.error(f"Error checking API server: {e}")

    def _candle_fetch_interval(self) -> int:
        """Current candle fetcher cycle length, falling back to the 900s default."""
        try:
            from services.candle_fetcher_service import get_candle_fetcher_service
            service = get_candle_fetcher_service()
            if service is not None:
                return service.interval
        except Exception:
            pass
        return 900

    def _trend_allowed_age(self, key: str, fetch_interval: int) -> int:
        """
        Staleness threshold for one TrendCache entry (key = SYMBOL_QUOTE_TF).

        The candle fetcher only replays an entry into TrendCache when a NEW
        closed candle exists for its timeframe, so a 240m entry is legitimately
        up to 4 hours old even when the fetcher is healthy. Allow one full
        candle period plus a fetch cycle plus slack; alert_trend_max_age acts
        as a floor so short timeframes keep a minimum grace period.
        """
        tf_seconds = 0
        suffix = key.rsplit("_", 1)[-1]
        if suffix.isdigit():
            tf_seconds = int(suffix) * 60
        elif suffix[:-1].isdigit() and suffix[-1] in ("D", "W"):
            # Day/week timeframes ("1D", "1W") — entry only refreshes at close.
            tf_seconds = int(suffix[:-1]) * (1440 if suffix[-1] == "D" else 10080) * 60
        return max(self.trend_max_age, tf_seconds + fetch_interval + 180)

    def _check_trend_cache(self) -> None:
        """
        Check that the trend cache has been updated recently.

        Each entry only refreshes when a new candle CLOSES on its timeframe,
        so the allowed age is per-timeframe (see _trend_allowed_age) rather
        than a single flat threshold.
        """
        issue_key = "trend_cache_stale"

        try:
            from cache.trend_cache import get_trend_cache
            trend_cache = get_trend_cache()

            if trend_cache is None:
                self._trigger_alert(
                    issue_key=issue_key,
                    message=(
                        "⚠️ <b>TREND CACHE UNAVAILABLE</b>\n\n"
                        "The trend cache has not been initialised yet."
                    ),
                )
                return

            cache_info = trend_cache.get_cache_info()
            entries = cache_info.get("entries", [])

            if not entries:
                # No data at all yet - only alert if we've been running a while
                # (give TradingView time to send its first webhook)
                self.logger.debug("Trend cache is empty - skipping staleness check")
                return

            # Only alert on symbols that are actively monitored and enabled
            try:
                from db.utils import get_db_session
                from db.crud_monitored_symbols import get_enabled_symbols_set
                with get_db_session() as _db:
                    monitored = get_enabled_symbols_set(_db)
            except Exception:
                monitored = None  # Fall back to checking all cached entries

            fetch_interval = self._candle_fetch_interval()
            stale_entries = []
            for e in entries:
                key = e.get("key", "")
                if monitored is not None and not any(
                    key.startswith(sym + "_") for sym in monitored
                ):
                    continue
                allowed = self._trend_allowed_age(key, fetch_interval)
                if e.get("age_seconds", 0) > allowed:
                    stale_entries.append((e, allowed))

            if stale_entries:
                stale_list = "\n".join(
                    f"  • {e['key']}: {int(e['age_seconds'])}s old (limit {allowed}s)"
                    for e, allowed in stale_entries
                )
                oldest_age = max(e["age_seconds"] for e, _ in stale_entries)
                self._trigger_alert(
                    issue_key=issue_key,
                    message=(
                        f"📡 <b>TREND DATA STALE</b>\n\n"
                        f"The Binance candle fetcher may have stopped updating TrendCache.\n\n"
                        f"Symbols older than one candle period + fetch cycle:\n{stale_list}\n\n"
                        f"Oldest: {int(oldest_age)}s ago "
                        f"({oldest_age / 60:.1f} mins)\n\n"
                        "Check CandleFetcherService logs — see the CANDLE FETCHER "
                        "alert if one also fired."
                    ),
                )
            else:
                self._clear_alert(
                    issue_key=issue_key,
                    recovery_message=(
                        "✅ <b>Trend cache recovered</b> — "
                        "the candle fetcher is updating it again."
                    ),
                )

        except Exception as e:
            self.logger.error(f"Error checking trend cache: {e}")

    def _check_price_cache(self) -> None:
        """
        Check that price cache data is fresh.
        Monitoring loop updates prices every ~30s; alert if any price is older than price_max_age.
        """
        issue_key = "price_cache_stale"

        try:
            from cache.price_cache import get_price_cache
            price_cache = get_price_cache()

            if price_cache is None:
                return

            # Try to get cache info - different caches expose this differently
            cache_info = None
            if hasattr(price_cache, "get_cache_info"):
                cache_info = price_cache.get_cache_info()
            elif hasattr(price_cache, "_cache"):
                # Fallback: inspect internal cache directly
                cache_info = self._inspect_price_cache_directly(price_cache)

            if cache_info is None:
                self.logger.debug("Cannot inspect price cache internals - skipping check")
                return

            entries = cache_info.get("entries", [])
            if not entries:
                self.logger.debug("Price cache is empty - skipping staleness check")
                return

            stale_entries = [
                e for e in entries
                if e.get("age_seconds", 0) > self.price_max_age
            ]

            if stale_entries:
                stale_list = "\n".join(
                    f"  • {e.get('symbol', e.get('key', '?'))}: {int(e['age_seconds'])}s old"
                    for e in stale_entries
                )
                oldest_age = max(e["age_seconds"] for e in stale_entries)
                self._trigger_alert(
                    issue_key=issue_key,
                    message=(
                        f"💹 <b>PRICE DATA STALE</b>\n\n"
                        f"Exchange price fetches may have stopped.\n\n"
                        f"Stale symbols (>{self.price_max_age}s):\n{stale_list}\n\n"
                        f"Oldest: {int(oldest_age)}s ago\n\n"
                        "There may be a problem connecting to the exchange."
                    ),
                )
            else:
                self._clear_alert(
                    issue_key=issue_key,
                    recovery_message=(
                        "✅ <b>Price cache recovered</b> — "
                        "exchange prices are updating normally."
                    ),
                )

        except Exception as e:
            self.logger.error(f"Error checking price cache: {e}")

    def _check_candle_fetcher(self) -> None:
        """
        Check that CandleFetcherService — the primary trend/candle data feed
        since the 2026-07 cutover from TradingView webhooks — is alive and
        completing cycles. Catches a dead/failing feed within a cycle or two,
        rather than waiting for _check_trend_cache's 20-minute staleness window.
        """
        issue_key = "candle_fetcher_down"

        try:
            from services.candle_fetcher_service import get_candle_fetcher_service
            service = get_candle_fetcher_service()

            if service is None:
                # ENABLE_CANDLE_FETCHER is off — nothing to check.
                return

            status = service.status()

            if not status["running"]:
                self._trigger_alert(
                    issue_key=issue_key,
                    message=(
                        "🚨 <b>CANDLE FETCHER DOWN</b>\n\n"
                        "CandleFetcherService's thread is not running. This is the "
                        "primary trend data feed — TrendCache will go stale and "
                        "signals will stop updating on new candles."
                    ),
                )
                return

            if status["last_run"] is None:
                # Hasn't completed its first cycle yet since startup — nothing
                # to judge yet, avoid a false positive here.
                return

            if not status["healthy"]:
                self._trigger_alert(
                    issue_key=issue_key,
                    message=(
                        f"🚨 <b>CANDLE FETCHER UNHEALTHY</b>\n\n"
                        f"Last completed cycle: {status['last_run']}\n"
                        f"Consecutive failures: {status['consecutive_failures']}\n\n"
                        "Binance candle fetching has stalled or is failing repeatedly. "
                        "TrendCache is not receiving fresh data."
                    ),
                )
            else:
                self._clear_alert(
                    issue_key=issue_key,
                    recovery_message=(
                        "✅ <b>Candle fetcher recovered</b> — "
                        "Binance fetch cycles are completing normally."
                    ),
                )

        except Exception as e:
            self.logger.error(f"Error checking candle fetcher: {e}")

    def _inspect_price_cache_directly(self, price_cache) -> Optional[dict]:
        """
        Fallback: build a cache_info dict by inspecting the internal _cache dict.
        Handles the common pattern where cache entries are dicts or objects with a timestamp.
        """
        try:
            now = time.time()
            entries = []

            for symbol, data in price_cache._cache.items():
                # Support both dict-style and object-style cache entries
                if isinstance(data, dict):
                    ts = data.get("timestamp") or data.get("time") or data.get("updated_at")
                else:
                    ts = getattr(data, "timestamp", None) or getattr(data, "updated_at", None)

                if ts is not None:
                    entries.append({
                        "symbol": symbol,
                        "age_seconds": now - ts,
                    })

            return {"entries": entries}

        except Exception as e:
            self.logger.debug(f"Could not inspect price cache directly: {e}")
            return None

    # -------------------------------------------------------------------------
    # Alert helpers
    # -------------------------------------------------------------------------

    def _trigger_alert(self, issue_key: str, message: str) -> None:
        """
        Send a Telegram alert for the given issue.
        Respects cooldown so we don't spam the same alert.
        """
        now = time.time()
        last_alerted = self._last_alerted.get(issue_key, 0)

        if now - last_alerted < self.re_alert_cooldown:
            # Still in cooldown window - log only
            self.logger.warning(
                f"[{issue_key}] Issue ongoing (cooldown active, "
                f"{int(self.re_alert_cooldown - (now - last_alerted))}s remaining)"
            )
            return

        self.logger.warning(f"[{issue_key}] ALERT: {message[:120]}")
        self._last_alerted[issue_key] = now
        self._active_issues.add(issue_key)
        self._send_telegram(message, priority=MessagePriority.HIGH)

    def _clear_alert(self, issue_key: str, recovery_message: str) -> None:
        """
        If an issue was previously active, send a recovery notification.
        """
        if issue_key not in self._active_issues:
            return  # Issue was never triggered - nothing to clear

        self.logger.info(f"[{issue_key}] Recovered: {recovery_message[:80]}")
        self._active_issues.discard(issue_key)
        self._last_alerted.pop(issue_key, None)
        self._send_telegram(recovery_message, priority=MessagePriority.NORMAL)

    def _send_telegram(self, message: str, priority: MessagePriority = MessagePriority.NORMAL) -> None:
        """Send a message via Telegram, safely."""
        try:
            from services.telegram_service import get_telegram
            telegram = get_telegram()
            if telegram is None:
                self.logger.warning("Telegram not available - cannot send health alert")
                return
            telegram.send_message_sync(message, priority=priority)
        except Exception as e:
            self.logger.error(f"Failed to send health alert via Telegram: {e}")


# ---------------------------------------------------------------------------
# Global instance helpers (mirrors the pattern used elsewhere in the codebase)
# ---------------------------------------------------------------------------

_health_alerting_service: Optional[HealthAlertingService] = None


def get_health_alerting_service() -> Optional[HealthAlertingService]:
    return _health_alerting_service


def initialize_health_alerting_service(**kwargs) -> HealthAlertingService:
    """Create and store the global HealthAlertingService instance."""
    global _health_alerting_service
    _health_alerting_service = HealthAlertingService(**kwargs)
    return _health_alerting_service