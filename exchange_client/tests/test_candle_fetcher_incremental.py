"""Unit tests for the candle fetcher's incremental write path.

The live loop used to re-upsert its whole lookback window every cycle — ~1,500
rows per cycle to persist the ~2 bars that had actually closed, plus a
max(timestamp) query and a read-back per series. These tests pin the cheap
behaviour: a quiet cycle writes only the repair bar, asks the DB nothing it
already knows, and replays nothing into TrendCache.

No DB, no network — fetch_klines and the write are stubbed.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import candle_fetcher as cf
from services.candle_fetcher_service import CandleFetcherService

TF = "15"
TF_DELTA = timedelta(minutes=15)
# compute_rows needs more than WARMUP_BARS + 5 candles before it emits anything.
N_CANDLES = cf.WARMUP_BARS + 100


def _candles(end: datetime, n: int = N_CANDLES):
    """n contiguous 15m candles whose last one closes at `end`."""
    first_open = end - TF_DELTA * n
    out = []
    for i in range(n):
        price = 100.0 + i * 0.1
        out.append(cf.Candle(
            open_time=first_open + TF_DELTA * i,
            open=price, high=price + 1, low=price - 1, close=price + 0.5,
            volume=1000.0 + i,
        ))
    return out


def _run_fetch(since, now, written):
    """fetch_and_store with the network and the DB write stubbed out.

    `written` is the list the captured rows are appended to.
    """
    end = now
    start = end - timedelta(hours=30)
    candles = _candles(end)
    report = cf.FetchReport(symbol="BTC_USDC", timeframe=TF, returned=len(candles))

    def _capture(db, rows):
        written.extend(rows)
        return len(rows)

    with mock.patch.object(cf, "fetch_klines", return_value=(candles, report)), \
            mock.patch.object(cf, "write_trend_rows", side_effect=_capture), \
            mock.patch.object(cf, "datetime", wraps=cf.datetime) as dt:
        # compute_rows drops the in-progress bar by comparing against now.
        dt.now.return_value = now
        return cf.fetch_and_store(object(), "BTC_USDC", TF, start, end, since=since)


def test_full_window_written_when_no_since():
    """Backfill / first-ever fetch keeps writing the whole window."""
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    written = []
    report = _run_fetch(since=None, now=now, written=written)

    # Everything past the warmup region, i.e. the whole window.
    assert len(written) == N_CANDLES - cf.WARMUP_BARS
    assert report.written == len(written)
    assert report.newest == max(r["timestamp"] for r in written)


def test_quiet_cycle_writes_only_the_repair_bar():
    """`since` = newest stored bar, nothing new closed -> exactly one row."""
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    written = []
    # The last bar to close at `now` is timestamped at its close.
    since = now
    report = _run_fetch(since=since, now=now, written=written)

    assert len(written) == 1, f"expected 1 repair row, got {len(written)}"
    assert written[0]["timestamp"] == since
    assert report.newest == since


def test_only_new_bars_plus_repair_written_after_a_gap():
    """Three bars closed since the last write -> repair + 3, not the window."""
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    written = []
    since = now - TF_DELTA * 3
    report = _run_fetch(since=since, now=now, written=written)

    stamps = sorted(r["timestamp"] for r in written)
    assert stamps == [since + TF_DELTA * i for i in range(4)], stamps
    assert report.newest == now


def test_repair_bar_is_rewritten_so_revisions_still_heal():
    """The bar at `since` is re-sent every cycle — that is the self-healing."""
    now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    written = []
    _run_fetch(since=now, now=now, written=written)
    assert [r["timestamp"] for r in written] == [now]


# --------------------------------------------------------------------------
# Service loop
# --------------------------------------------------------------------------

def _service():
    svc = CandleFetcherService(symbols=["BTC_USDC"], timeframes=[TF],
                               interval_seconds=300, lookback_hours=30)
    svc.logger = mock.MagicMock()
    return svc


def _row(ts):
    return SimpleNamespace(timestamp=ts, symbol="BTC_USDC", timeframe=TF)


def _cycle(svc, newest, rows_after=()):
    """Run one _fetch_once with every collaborator stubbed.

    Returns (latest_ts_mock, rows_after_mock, trend_cache_mock).
    """
    report = cf.FetchReport(symbol="BTC_USDC", timeframe=TF, written=1, newest=newest)
    with mock.patch("services.candle_fetcher_service.get_db_session"), \
            mock.patch("services.candle_fetcher_service.fetch_and_store",
                       return_value=report) as fas, \
            mock.patch("services.candle_fetcher_service.get_latest_trend_timestamp",
                       return_value=None) as latest, \
            mock.patch("services.candle_fetcher_service.get_trend_rows_after",
                       return_value=list(rows_after)) as after, \
            mock.patch("services.candle_fetcher_service.get_trend_cache") as cache, \
            mock.patch("services.candle_fetcher_service.load_trend_data_from_history"):
        svc._fetch_once()
    return latest, after, cache, fas


def test_first_cycle_seeds_since_from_the_db_once():
    """The max(timestamp) query is allowed exactly once per series per process."""
    svc = _service()
    bar1 = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    bar2 = bar1 + TF_DELTA

    latest, _, _, _ = _cycle(svc, newest=bar1, rows_after=[_row(bar1)])
    assert latest.call_count == 1
    assert svc._last_ts[("BTC_USDC", TF)] == bar1

    # Second cycle knows where it is — no second max() query.
    latest, _, _, fas = _cycle(svc, newest=bar2, rows_after=[_row(bar2)])
    assert latest.call_count == 0
    assert fas.call_args.kwargs["since"] == bar1
    assert svc._last_ts[("BTC_USDC", TF)] == bar2


def test_quiet_cycle_does_not_read_back_or_replay():
    """No bar newer than `since` -> no follow-up SELECT, no cache update."""
    svc = _service()
    bar = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    svc._last_ts[("BTC_USDC", TF)] = bar

    latest, after, cache, _ = _cycle(svc, newest=bar)

    assert latest.call_count == 0, "should not re-query a timestamp it already has"
    assert after.call_count == 0, "nothing new — must not read rows back"
    assert cache.return_value.update.call_count == 0
    assert svc._last_ts[("BTC_USDC", TF)] == bar


def test_new_bar_is_replayed_into_the_cache():
    svc = _service()
    bar = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    nxt = bar + TF_DELTA
    svc._last_ts[("BTC_USDC", TF)] = bar

    _, after, cache, _ = _cycle(svc, newest=nxt, rows_after=[_row(nxt)])

    assert after.call_count == 1
    assert after.call_args.args[3] == bar, "replay must start from the last seen bar"
    assert cache.return_value.update.call_count == 1
    assert svc._last_ts[("BTC_USDC", TF)] == nxt


def test_capped_read_back_leaves_the_remainder_for_next_cycle():
    """get_trend_rows_after is limited; advance only as far as we replayed."""
    svc = _service()
    bar = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    svc._last_ts[("BTC_USDC", TF)] = bar
    replayed = [_row(bar + TF_DELTA * i) for i in (1, 2)]

    _cycle(svc, newest=bar + TF_DELTA * 9, rows_after=replayed)

    assert svc._last_ts[("BTC_USDC", TF)] == bar + TF_DELTA * 2


def test_failed_series_does_not_advance_since():
    """A raising fetch leaves the watermark alone so the bars get retried."""
    svc = _service()
    bar = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    svc._last_ts[("BTC_USDC", TF)] = bar

    with mock.patch("services.candle_fetcher_service.get_db_session"), \
            mock.patch("services.candle_fetcher_service.fetch_and_store",
                       side_effect=RuntimeError("binance down")), \
            mock.patch("services.candle_fetcher_service.get_trend_cache"):
        svc._fetch_once()

    assert svc._last_ts[("BTC_USDC", TF)] == bar


if __name__ == "__main__":
    for fn in [test_full_window_written_when_no_since,
               test_quiet_cycle_writes_only_the_repair_bar,
               test_only_new_bars_plus_repair_written_after_a_gap,
               test_repair_bar_is_rewritten_so_revisions_still_heal,
               test_first_cycle_seeds_since_from_the_db_once,
               test_quiet_cycle_does_not_read_back_or_replay,
               test_new_bar_is_replayed_into_the_cache,
               test_capped_read_back_leaves_the_remainder_for_next_cycle,
               test_failed_series_does_not_advance_since]:
        fn()
        print(f"  ok {fn.__name__}")
    print("\nALL CANDLE FETCHER INCREMENTAL TESTS PASSED")
