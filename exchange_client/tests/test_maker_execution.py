"""Unit tests for the pure maker-execution helpers. No live exchange, no DB.

The execution itself is async (orders-table driven, in TradingService +
MonitoringService), and its order-placement / fill / cancel paths must be
validated against the live venue — see the LIVE: markers in the code. What is
unit-testable here is the side-effect-free decision logic, covered below.
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.maker_execution import (best_maker_price, entry_order_expired,
                                       executed_qty, maker_entry_limit_price,
                                       normalize_status)


def test_limit_price_is_signal_price_unmodified():
    assert maker_entry_limit_price(100.0) == Decimal("100.0")
    assert maker_entry_limit_price("64810.42") == Decimal("64810.42")
    print("  ok fallback limit price = signal price, no offset")


def test_best_maker_price_long_uses_best_bid():
    # bids ascending (Backpack style): best bid is the highest = 99.98
    depth = {"bids": [["99.90", "1"], ["99.95", "2"], ["99.98", "3"]],
             "asks": [["100.02", "1"], ["100.05", "2"]]}
    assert best_maker_price(depth, is_long=True) == Decimal("99.98")   # rest AT best bid
    print("  ok long -> best bid")


def test_best_maker_price_short_uses_best_ask():
    depth = {"bids": [["99.98", "1"]], "asks": [["100.05", "2"], ["100.02", "1"]]}
    assert best_maker_price(depth, is_long=False) == Decimal("100.02")  # rest AT best ask
    print("  ok short -> best ask")


def test_best_maker_price_handles_float_and_unsorted():
    depth = {"bids": [[76.10, 5], [76.14, 2], [76.09, 9]],
             "asks": [[76.20, 1], [76.16, 3]]}
    assert best_maker_price(depth, is_long=True) == Decimal("76.14")
    assert best_maker_price(depth, is_long=False) == Decimal("76.16")
    print("  ok float prices + any sort order")


def test_best_maker_price_none_on_bad_book():
    assert best_maker_price(None, True) is None
    assert best_maker_price({}, True) is None
    assert best_maker_price({"bids": [], "asks": []}, True) is None
    # crossed book -> untrusted -> None (caller falls back)
    crossed = {"bids": [["100.10", "1"]], "asks": [["100.00", "1"]]}
    assert best_maker_price(crossed, True) is None
    print("  ok None on missing/empty/crossed book (caller falls back)")


def test_expiry():
    assert entry_order_expired(46, 45) is True
    assert entry_order_expired(45, 45) is True
    assert entry_order_expired(44.9, 45) is False
    print("  ok expiry boundary")


def test_normalize_status_and_qty():
    class O:
        class _S:
            value = "Filled"
        status = _S()
        executed_quantity = "2.5"
    assert normalize_status({"status": "New"}) == "New"
    assert normalize_status(O()) == "Filled"
    assert normalize_status(None) == "UNKNOWN"
    assert executed_qty({"executedQuantity": "1.25"}) == Decimal("1.25")
    assert executed_qty(O()) == Decimal("2.5")
    assert executed_qty(None) == Decimal("0")
    print("  ok status + qty extraction")


if __name__ == "__main__":
    for fn in [test_limit_price_is_signal_price_unmodified,
               test_best_maker_price_long_uses_best_bid,
               test_best_maker_price_short_uses_best_ask,
               test_best_maker_price_handles_float_and_unsorted,
               test_best_maker_price_none_on_bad_book,
               test_expiry, test_normalize_status_and_qty]:
        fn()
    print("\nALL MAKER HELPER TESTS PASSED")
