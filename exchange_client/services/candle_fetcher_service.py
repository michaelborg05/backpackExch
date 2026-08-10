"""Background service that keeps trend_analysis_log topped up.

Runs the programmatic candle fetcher on an interval, in its own daemon thread.
Since the 2026-07 cutover this is the PRIMARY trend data feed — the
TradingView webhook path (/webhook/tradingview/trend) is now a no-op, so
TrendCache is only ever refreshed from here (plus once at startup, replayed
from history by cache/trend_cache_warmup.py). If this service is down for
longer than `max_age` (TrendCache), signals go stale silently.

Deliberately isolated from trading:
  * Own thread — a hang or crash here cannot stall the monitoring loop.
  * Every exception is swallowed and logged; the thread never dies.
  * Set ENABLE_CANDLE_FETCHER=true to turn it on (see .env).
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from cache.settings_cache import get_settings_cache
from cache.trend_cache import get_trend_cache
from db.crud_monitored_symbols import get_enabled_symbols_set
from db.crud_trend import get_latest_trend_timestamp, get_trend_rows_after, load_trend_data_from_history
from db.utils import get_db_session
from services.candle_fetcher import SYMBOL_MAP, TF_MINUTES, fetch_and_store, get_quote
from utils.logging import log_manager
from utils.symbols import normalize_symbol

# candle_fetcher.compute_rows() only emits rows once it has fetched more than
# WARMUP_BARS(300) + 5 candles. The backward warmup extension always supplies
# the first 300; candle_fetcher_lookback_hours supplies the rest as "new" bars
# to catch up on. That setting is sized for fast timeframes (30h is hundreds
# of 15m bars) but is far too small for slow ones — 30h is ~1 daily bar, so
# 1D never clears the threshold and silently writes nothing every cycle. Force
# a floor of MIN_CATCHUP_BARS bars of *this* timeframe regardless of the
# global setting, so every timeframe reliably clears the +5 margin.
MIN_CATCHUP_BARS = 10


class CandleFetcherService:
    """Periodically fetch candles, write them to trend_analysis_log, and replay
    the new rows into TrendCache so signals see fresh data.

    Configuration lives in the DB (`settings` table, via SettingsCache) and the
    symbol list comes from `monitored_symbols` — the same list the monitoring
    loop uses. Only the on/off switch is an env var, because it has to be
    readable before the DB session exists and it is a deploy-time decision.

    Settings (all global, i.e. profile_name NULL):
        candle_fetcher_quote            default "USDT"
        candle_fetcher_timeframes       default "15,60"
        candle_fetcher_interval         default 900   (seconds)
        candle_fetcher_lookback_hours   default 6
        candle_fetcher_symbols          default ""    (blank = use monitored_symbols)

    Symbols resolve as: candle_fetcher_symbols if set, else the enabled rows of
    monitored_symbols — minus anything with no mapping on the source venue
    (e.g. HYPE, which Binance does not list). Re-resolved every cycle, so adding
    a monitored symbol picks it up without a restart.
    """

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        timeframes: Optional[List[str]] = None,
        interval_seconds: Optional[int] = None,
        lookback_hours: Optional[int] = None,
    ):
        self.logger = log_manager.get_logger("candle_fetcher")

        # Explicit constructor args win (used by tests); otherwise resolved from
        # settings on each cycle so changes take effect without a redeploy.
        self._symbols_override = symbols
        self._timeframes_override = timeframes
        self._interval_override = interval_seconds
        self._lookback_override = lookback_hours

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_run_ts: Optional[float] = None
        self._last_rows: int = 0
        self._last_symbols: List[str] = []
        self._consecutive_failures: int = 0
        self._warned_unmapped: set = set()
        # (symbol, timeframe) -> newest bar this process has written AND replayed
        # into TrendCache. Seeded from the DB the first time a series is fetched,
        # maintained in memory afterwards, so the steady state costs no query.
        self._last_ts: dict = {}

    # -- configuration -----------------------------------------------------

    def _setting(self, name: str, default):
        cache = get_settings_cache()
        if cache is None:
            return default
        if isinstance(default, int):
            return cache.get_int(name, default=default)
        return cache.get(name, default=default)

    @property
    def interval(self) -> int:
        if self._interval_override is not None:
            return self._interval_override
        return max(60, self._setting("candle_fetcher_interval", 900))

    @property
    def lookback_hours(self) -> int:
        if self._lookback_override is not None:
            return self._lookback_override
        return max(1, self._setting("candle_fetcher_lookback_hours", 6))

    @property
    def timeframes(self) -> List[str]:
        if self._timeframes_override:
            return self._timeframes_override
        raw = self._setting("candle_fetcher_timeframes", "15,60") or "15,60"
        return [t.strip() for t in str(raw).split(",") if t.strip()]

    def resolve_symbols(self) -> List[str]:
        """Symbols to fetch: explicit override > setting > monitored_symbols.

        Anything the source venue does not list is dropped with a one-time
        warning rather than failing the cycle.
        """
        if self._symbols_override:
            candidates = list(self._symbols_override)
        else:
            raw = self._setting("candle_fetcher_symbols", "") or ""
            if str(raw).strip():
                candidates = [s.strip().upper() for s in str(raw).split(",") if s.strip()]
            else:
                try:
                    with get_db_session() as db:
                        candidates = sorted(get_enabled_symbols_set(db))
                except Exception as e:  # noqa: BLE001
                    self.logger.error(f"Could not read monitored_symbols: {e}")
                    return []

        usable, unmapped = [], []
        for sym in candidates:
            canonical = normalize_symbol(sym) or sym
            (usable if canonical in SYMBOL_MAP else unmapped).append(canonical)

        for sym in unmapped:
            if sym not in self._warned_unmapped:
                self._warned_unmapped.add(sym)
                self.logger.warning(
                    f"{sym} is monitored but not listed on the candle source "
                    f"({get_quote()}) — skipping. Add it to "
                    f"services/candle_fetcher.SYMBOL_BASES if that is wrong."
                )
        return usable

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            self.logger.warning("CandleFetcherService already running")
            return
        # Do not gate startup on the symbol list — it is resolved per cycle from
        # monitored_symbols, so an empty list now may be populated later.
        symbols = self.resolve_symbols()
        if not symbols:
            self.logger.warning(
                "CandleFetcherService starting with no resolvable symbols — "
                "will re-check monitored_symbols each cycle"
            )
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="CandleFetcherService", daemon=True
        )
        self._thread.start()
        self.logger.info(
            f"✅ CandleFetcherService started (symbols={len(symbols)}: {symbols}, "
            f"timeframes={self.timeframes}, interval={self.interval}s, "
            f"lookback={self.lookback_hours}h, quote={get_quote()}) "
            f"-> trend_analysis_log"
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=30)
        self.logger.info("CandleFetcherService stopped")

    @property
    def is_healthy(self) -> bool:
        """True if a run completed within the last 3 intervals."""
        if self._last_run_ts is None:
            return False
        return (time.time() - self._last_run_ts) < (self.interval * 3)

    def status(self) -> dict:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "healthy": self.is_healthy,
            "symbols": self._last_symbols or self.resolve_symbols(),
            "timeframes": self.timeframes,
            "interval_seconds": self.interval,
            "quote": get_quote(),
            "last_run": (
                datetime.fromtimestamp(self._last_run_ts, tz=timezone.utc).isoformat()
                if self._last_run_ts else None
            ),
            "last_run_rows": self._last_rows,
            "consecutive_failures": self._consecutive_failures,
        }

    # -- loop --------------------------------------------------------------

    def _run_loop(self) -> None:
        # Small stagger so startup does not contend with cache warmup.
        self._stop_event.wait(timeout=30)
        while not self._stop_event.is_set():
            try:
                self._fetch_once()
                self._consecutive_failures = 0
            except Exception as e:  # noqa: BLE001 — must never kill the thread
                self._consecutive_failures += 1
                self.logger.error(
                    f"Candle fetch cycle failed ({self._consecutive_failures} in a row): {e}",
                    exc_info=True,
                )
            self._stop_event.wait(timeout=self.interval)
        self.logger.info("Candle fetch loop exited")

    def _fetch_once(self) -> None:
        symbols = self.resolve_symbols()
        if not symbols:
            self.logger.warning("No fetchable symbols this cycle — skipping")
            return
        self._last_symbols = symbols

        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(hours=self.lookback_hours)
        total, gapped, failed = 0, [], []
        trend_cache = get_trend_cache()
        cache_updates = 0

        with get_db_session() as db:
            for symbol in symbols:
                for tf in self.timeframes:
                    if self._stop_event.is_set():
                        return
                    try:
                        # The newest bar on record BEFORE this cycle's fetch.
                        # It does double duty: it tells fetch_and_store how much
                        # of the window is already stored and can be skipped,
                        # and it marks where the TrendCache replay must start —
                        # replaying already-seen bars would double-count them in
                        # the RSI/EMA/BB history TrendCache keeps for slope and
                        # momentum calculations. Read from the DB once per
                        # series per process, then tracked in memory: this value
                        # is exactly what we last wrote, so re-reading it every
                        # cycle only re-derives what we already know.
                        key = (symbol, tf)
                        since = self._last_ts.get(key)
                        if since is None:
                            since = get_latest_trend_timestamp(db, symbol, tf)
                            if since is not None:
                                self._last_ts[key] = since
                        tf_start = min(start, end - timedelta(
                            minutes=TF_MINUTES[tf] * MIN_CATCHUP_BARS
                        ))
                        report = fetch_and_store(db, symbol, tf, tf_start, end, since=since)
                        total += report.written
                        if not report.contiguous:
                            gapped.append(report.describe())
                        # `written` counts the repair rewrite too, so it is truthy
                        # on quiet cycles. Only a bar strictly newer than `since`
                        # is something TrendCache has not seen.
                        has_new_bar = report.newest is not None and (
                            since is None or report.newest > since
                        )
                        if has_new_bar:
                            new_rows = get_trend_rows_after(db, symbol, tf, since)
                            for row in new_rows:
                                trend_cache.update(
                                    load_trend_data_from_history(row), persist_to_db=False
                                )
                                cache_updates += 1
                            # Advance to the last bar actually replayed, not to
                            # report.newest: get_trend_rows_after is capped, so
                            # a long outage leaves a remainder that the next
                            # cycle must pick up. An exception above leaves
                            # `since` untouched and those bars get retried.
                            # (Both read paths return rows oldest-first.)
                            self._last_ts[key] = (
                                new_rows[-1].timestamp if new_rows else report.newest
                            )
                    except Exception as e:  # noqa: BLE001 — one symbol must not stop the rest
                        failed.append(f"{symbol}/{tf}: {e}")

        self._last_run_ts = time.time()
        self._last_rows = total
        self.logger.info(
            f"Candle fetch cycle complete — {total} rows upserted "
            f"(includes one repair rewrite per series), "
            f"{cache_updates} TrendCache update(s) replayed"
        )
        if gapped:
            # Wilder recursions (RSI/ADX) drift across gaps; surface loudly.
            self.logger.warning(f"Gaps detected in {len(gapped)} series: {'; '.join(gapped[:5])}")
        if failed:
            self.logger.error(f"{len(failed)} series failed: {'; '.join(failed[:5])}")


_service: Optional[CandleFetcherService] = None


def get_candle_fetcher_service() -> Optional[CandleFetcherService]:
    return _service


def initialize_candle_fetcher_service(**kwargs) -> Optional[CandleFetcherService]:
    """Create the service if ENABLE_CANDLE_FETCHER is truthy, else return None."""
    global _service
    enabled = os.getenv("ENABLE_CANDLE_FETCHER", "false").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        log_manager.get_logger("candle_fetcher").info(
            "CandleFetcherService disabled (set ENABLE_CANDLE_FETCHER=true to enable)"
        )
        _service = None
        return None
    _service = CandleFetcherService(**kwargs)
    return _service
