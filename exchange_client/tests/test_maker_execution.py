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

from services.maker_execution import (entry_order_expired, executed_qty,
                                       maker_entry_limit_price, normalize_status)


def test_limit_price_is_signal_price_unmodified():
    # Must NOT price-improve — resting away from the signal price forfeits winners.
    assert maker_entry_limit_price(100.0) == Decimal("100.0")
    assert maker_entry_limit_price("64810.42") == Decimal("64810.42")
    print("  ok limit price = signal price, no offset")


def test_expiry():
    assert entry_order_expired(46, 45) is True
    assert entry_order_expired(45, 45) is True
    assert entry_order_expired(44.9, 45) is False
    assert entry_order_expired(0, 45) is False
    print("  ok expiry boundary")


def test_normalize_status_dict_and_obj():
    class O:
        class _S:
            value = "Filled"
        status = _S()
    assert normalize_status({"status": "New"}) == "New"
    assert normalize_status(O()) == "Filled"
    assert normalize_status(None) == "UNKNOWN"
    assert normalize_status({}) == "UNKNOWN"
    print("  ok status normalisation (dict, pydantic-like, none)")


def test_executed_qty():
    class O:
        executed_quantity = "2.5"
    assert executed_qty({"executedQuantity": "1.25"}) == Decimal("1.25")
    assert executed_qty({"executed_quantity": "3"}) == Decimal("3")
    assert executed_qty(O()) == Decimal("2.5")
    assert executed_qty(None) == Decimal("0")
    assert executed_qty({"executedQuantity": None}) == Decimal("0")
    print("  ok executed qty extraction")


if __name__ == "__main__":
    for fn in [test_limit_price_is_signal_price_unmodified, test_expiry,
               test_normalize_status_dict_and_obj, test_executed_qty]:
        fn()
    print("\nALL MAKER HELPER TESTS PASSED")
