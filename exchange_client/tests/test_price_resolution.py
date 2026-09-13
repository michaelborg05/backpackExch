"""Unit tests for order-book reference pricing.

The bug these pin: Backpack's /ticker `lastPrice` is the last *fill* and carries
no timestamp, so on a thin market the price cache was holding an hours-old
number — measured up to 6% away from the live book across the monitored roster.
Everything downstream (TP/SL, trailing stops, circuit-breaker marks, position
sizing) read that.

These cover the pure resolution rules plus the shape of the monitoring loop's
market-data calls: one bulk /tickers request, one depth request per symbol.

No DB, no exchange — collaborators are stubbed.
"""
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.price_resolution import (
    book_top,
    deviation_pct,
    resolve_reference_price,
)


# Backpack returns bids ASCENDING — best bid is the last element, not the first.
UNI_BOOK = {
    "bids": [["5.9500", "1.0"], ["5.9550", "2.0"], ["5.9600", "1.1"]],
    "asks": [["5.9650", "1.3"], ["5.9700", "80.0"]],
    "timestamp": 1789214477734524,
}


# ── book_top ────────────────────────────────────────────────────────────────

def test_best_bid_is_taken_from_ascending_bids():
    top = book_top(UNI_BOOK)
    assert top.bid == Decimal("5.9600")
    assert top.ask == Decimal("5.9650")
    assert top.mid == Decimal("5.9625")
    assert top.timestamp_us == 1789214477734524


def test_bid_order_does_not_matter():
    descending = {"bids": list(reversed(UNI_BOOK["bids"])), "asks": UNI_BOOK["asks"]}
    assert book_top(descending).bid == Decimal("5.9600")


def test_spread_pct_is_relative_to_mid():
    top = book_top(UNI_BOOK)
    expected = (Decimal("5.9650") - Decimal("5.9600")) / Decimal("5.9625") * 100
    assert top.spread_pct == expected


def test_crossed_book_is_rejected():
    assert book_top({"bids": [["10", "1"]], "asks": [["9", "1"]]}) is None


def test_one_sided_and_empty_books_are_rejected():
    assert book_top({"bids": [["10", "1"]], "asks": []}) is None
    assert book_top({"bids": [], "asks": [["10", "1"]]}) is None
    assert book_top({}) is None
    assert book_top(None) is None


def test_unparseable_levels_are_skipped_not_fatal():
    top = book_top({"bids": [["oops", "1"], ["5.96", "1"]], "asks": [["5.97", "1"]]})
    assert top.bid == Decimal("5.96")


def test_missing_timestamp_is_tolerated():
    assert book_top({"bids": [["1", "1"]], "asks": [["2", "1"]]}).timestamp_us is None


# ── resolve_reference_price ─────────────────────────────────────────────────

def test_stale_last_fill_loses_to_the_book():
    """The live UNI case: last fill 6.30, book sitting at ~5.96."""
    quote = resolve_reference_price("6.3000", book_top(UNI_BOOK), max_spread_pct=2.0)
    assert quote.source == "book_mid"
    assert quote.price == Decimal("5.9625")
    assert quote.bid == Decimal("5.9600")
    assert quote.ask == Decimal("5.9650")


def test_fresh_last_fill_still_yields_the_mid():
    """Mid is used unconditionally when the book is sane, not only when last drifts."""
    quote = resolve_reference_price("5.9625", book_top(UNI_BOOK))
    assert quote.source == "book_mid"
    assert quote.price == Decimal("5.9625")


def test_wide_book_falls_back_to_the_last_fill():
    wide = {"bids": [["90", "1"]], "asks": [["110", "1"]]}   # 20% spread
    quote = resolve_reference_price("100", book_top(wide), max_spread_pct=2.0)
    assert quote.source == "last_wide_book"
    assert quote.price == Decimal("100")
    assert quote.spread_pct is not None   # still reported for diagnostics


def test_wide_book_with_no_last_fill_uses_the_mid_and_says_so():
    wide = {"bids": [["90", "1"]], "asks": [["110", "1"]]}
    quote = resolve_reference_price(None, book_top(wide), max_spread_pct=2.0)
    assert quote.source == "book_mid_wide"
    assert quote.price == Decimal("100")


def test_no_book_falls_back_to_the_last_fill():
    quote = resolve_reference_price("6.3000", None)
    assert quote.source == "last_no_book"
    assert quote.price == Decimal("6.3000")
    assert quote.bid is None


def test_no_book_and_no_last_fill_yields_no_price():
    quote = resolve_reference_price(None, None)
    assert quote.price is None
    assert quote.source == "unavailable"


def test_nonsense_last_price_is_treated_as_absent():
    for bad in ("0", "-1", "", "null", object()):
        assert resolve_reference_price(bad, None).price is None


def test_deviation_pct_is_signed_and_coerces_input():
    assert deviation_pct("6.30", "6.00") == Decimal("5")
    assert deviation_pct(5.7, Decimal("6.00")) == Decimal("-5")
    assert deviation_pct(None, "6.00") is None
    assert deviation_pct("6.00", 0) is None


# ── monitoring loop call shape ──────────────────────────────────────────────

TICKERS = ["BTC_USDC", "UNI_USDC", "RAY_USDC"]


def _service():
    """A MonitoringService with only what _monitor_prices touches.

    `tickers` is a read-only property over the symbol cache, so stub the cache.
    """
    from services.monitoring_service import MonitoringService
    svc = object.__new__(MonitoringService)
    svc.logger = mock.MagicMock()
    svc._symbol_cache = mock.MagicMock()
    svc._symbol_cache.get_all_symbols.return_value = list(TICKERS)
    svc.price_cache = mock.MagicMock()
    svc.settings = SimpleNamespace(max_book_spread_pct=2.0, price_stale_warn_pct=1.0)
    return svc


def _bulk_rows():
    return {
        s: {"symbol": s, "lastPrice": "6.3000", "priceChangePercent": "0.063",
            "high": "6.45", "low": "5.88", "volume": "439"}
        for s in TICKERS
    }


def test_one_bulk_ticker_call_and_one_depth_call_per_symbol():
    svc = _service()
    with mock.patch("services.monitoring_service.fetch_all_tickers") as bulk, \
         mock.patch("services.monitoring_service.fetch_book_top") as depth:
        bulk.return_value = _bulk_rows()
        depth.return_value = book_top(UNI_BOOK)
        svc._monitor_prices()

    assert bulk.call_count == 1
    assert depth.call_count == len(TICKERS)
    assert [c.args[0] for c in depth.call_args_list] == TICKERS


def test_cache_receives_the_mid_plus_book_provenance():
    svc = _service()
    with mock.patch("services.monitoring_service.fetch_all_tickers") as bulk, \
         mock.patch("services.monitoring_service.fetch_book_top") as depth:
        bulk.return_value = _bulk_rows()
        depth.return_value = book_top(UNI_BOOK)
        svc._monitor_prices()

    assert svc.price_cache.update_ticker.call_count == len(TICKERS)
    _, kwargs = svc.price_cache.update_ticker.call_args
    assert kwargs["price_source"] == "book_mid"
    assert kwargs["bid"] == Decimal("5.9600")
    assert kwargs["last_trade_price"] == "6.3000"
    # 24h metadata still arrives, now from the bulk call.
    assert kwargs["volume"] == "439"

    args, _ = svc.price_cache.update_ticker.call_args
    assert args[1] == str(Decimal("5.9625"))   # the mid, not the 6.30 last fill


def test_bulk_failure_still_prices_off_the_book():
    svc = _service()
    with mock.patch("services.monitoring_service.fetch_all_tickers") as bulk, \
         mock.patch("services.monitoring_service.fetch_book_top") as depth:
        bulk.return_value = {}
        depth.return_value = book_top(UNI_BOOK)
        svc._monitor_prices()

    assert svc.price_cache.update_ticker.call_count == len(TICKERS)
    _, kwargs = svc.price_cache.update_ticker.call_args
    assert kwargs["price_source"] == "book_mid"
    assert kwargs["volume"] is None


def test_both_sources_down_leaves_the_cache_untouched():
    """Going stale beats valuing positions off an invented price."""
    svc = _service()
    with mock.patch("services.monitoring_service.fetch_all_tickers") as bulk, \
         mock.patch("services.monitoring_service.fetch_book_top") as depth:
        bulk.return_value = {}
        depth.return_value = None
        svc._monitor_prices()

    svc.price_cache.update_ticker.assert_not_called()
    assert svc.logger.error.call_count == len(TICKERS)


def test_one_symbol_failing_does_not_stop_the_rest():
    svc = _service()
    with mock.patch("services.monitoring_service.fetch_all_tickers") as bulk, \
         mock.patch("services.monitoring_service.fetch_book_top") as depth:
        bulk.return_value = _bulk_rows()
        depth.side_effect = [book_top(UNI_BOOK), RuntimeError("boom"), book_top(UNI_BOOK)]
        svc._monitor_prices()

    assert svc.price_cache.update_ticker.call_count == 2
    assert svc.logger.error.called


if __name__ == "__main__":
    for fn in [test_best_bid_is_taken_from_ascending_bids,
               test_bid_order_does_not_matter,
               test_spread_pct_is_relative_to_mid,
               test_crossed_book_is_rejected,
               test_one_sided_and_empty_books_are_rejected,
               test_unparseable_levels_are_skipped_not_fatal,
               test_missing_timestamp_is_tolerated,
               test_stale_last_fill_loses_to_the_book,
               test_fresh_last_fill_still_yields_the_mid,
               test_wide_book_falls_back_to_the_last_fill,
               test_wide_book_with_no_last_fill_uses_the_mid_and_says_so,
               test_no_book_falls_back_to_the_last_fill,
               test_no_book_and_no_last_fill_yields_no_price,
               test_nonsense_last_price_is_treated_as_absent,
               test_deviation_pct_is_signed_and_coerces_input,
               test_one_bulk_ticker_call_and_one_depth_call_per_symbol,
               test_cache_receives_the_mid_plus_book_provenance,
               test_bulk_failure_still_prices_off_the_book,
               test_both_sources_down_leaves_the_cache_untouched,
               test_one_symbol_failing_does_not_stop_the_rest]:
        fn()
        print(f"  ok  {fn.__name__}")
    print("\nALL PRICE RESOLUTION TESTS PASSED")
