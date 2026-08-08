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


def _reconcile_fixture(status, thesis_snapshot):
    """Drive _reconcile_maker_entry against fakes: no exchange, no DB, no Telegram.

    Returns (fake_self, adapter, calls) after one reconcile of a maker entry order
    that the adapter reports as `status` ("filled" or "resting" -> timed out).
    """
    import contextlib
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    import services.monitoring_service as ms
    from services.monitoring_service import MonitoringService

    calls = {"order_kwargs": None, "stamped": None}

    class FakeAdapter:
        def reconcile_entry_order(self, order):
            return {"status": status}

        def cancel_order(self, order_id, symbol):
            return None

        def order_buy(self, **kwargs):
            calls["order_kwargs"] = kwargs
            return SimpleNamespace(executed_quantity="1", executed_quote_quantity="100")

    class FakeSelf:
        logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                                 error=lambda *a, **k: None, debug=lambda *a, **k: None)
        _thesis_header_lines = staticmethod(MonitoringService._thesis_header_lines)
        _thesis_reasons_block = staticmethod(MonitoringService._thesis_reasons_block)

        def __init__(self):
            self._pending_maker_theses = {}

        def _stamp_fill_type_on_position(self, *a, **k):
            return None

        def _send_telegram(self, *a, **k):
            return None

        def _stamp_signal_snapshot_on_trade(self, order_id, profile_name, snapshot):
            calls["stamped"] = snapshot

    fake = FakeSelf()
    fake._pending_maker_theses["EX-1"] = {
        "reasons": ["trend ok"], "strength": "STRONG", "confidence": 90.0,
        "snapshot": thesis_snapshot,
    }
    profile = SimpleNamespace(name="profile10", display_name="P10", maker_timeout_sec=60)
    order = SimpleNamespace(
        exchange_order_id="EX-1", symbol="ZEC_USDC", side="BID", quantity="1",
        # well past the 60s timeout, so a resting order falls back to taker
        created_at=datetime.now(timezone.utc) - timedelta(seconds=600),
    )

    # The fallback marks the DB order cancelled; keep that off the real database.
    original = ms.get_db_session
    ms.get_db_session = lambda: contextlib.nullcontext(None)
    try:
        MonitoringService._reconcile_maker_entry(fake, FakeAdapter(), profile, order)
    finally:
        ms.get_db_session = original
    return fake, calls


def test_taker_fallback_passes_signal_snapshot():
    # Regression: the fallback used to call order_buy with only source/profile_name,
    # so MAKER_TIMEOUT_TAKER trades were booked with a null signal_snapshot.
    snap = {"entry": {"timeframe": "60", "rsi": 46.0}}
    fake, calls = _reconcile_fixture("resting", snap)
    assert calls["order_kwargs"] is not None, "taker fallback did not place an order"
    assert calls["order_kwargs"]["signal_snapshot"] == snap
    assert calls["order_kwargs"]["source"] == "MAKER_TIMEOUT_TAKER"
    assert fake._pending_maker_theses == {}, "thesis not popped"
    print("  ok taker fallback carries the signal snapshot")


def test_maker_fill_stamps_signal_snapshot():
    snap = {"entry": {"timeframe": "60", "rsi": 51.2}}
    fake, calls = _reconcile_fixture("filled", snap)
    assert calls["stamped"] == snap, "maker fill did not stamp the snapshot onto the trade"
    assert fake._pending_maker_theses == {}, "thesis not popped"
    print("  ok maker fill stamps the signal snapshot onto the trade")


def test_missing_thesis_still_trades():
    # A restart drops the in-memory thesis; the entry must still go through, just
    # without a snapshot.
    fake, calls = _reconcile_fixture("resting", None)
    assert calls["order_kwargs"]["signal_snapshot"] is None
    print("  ok missing thesis degrades to no snapshot, trade still placed")


def test_limit_exit_fill_stamps_close_snapshot():
    """A TP/SL that fills as a resting limit is booked by the adapter via
    save_limit_trade, which writes no snapshot — _monitor_orders must stamp
    close-time market state on afterwards."""
    import contextlib
    from types import SimpleNamespace

    import services.monitoring_service as ms
    from services.monitoring_service import MonitoringService
    from utils.constants import OrderStatus

    calls = {"stamped": None, "stamped_order_id": None}
    profile = SimpleNamespace(name="profile3", display_name="P3",
                              entry_timeframe="15", trend_timeframe="60")
    order = SimpleNamespace(exchange_order_id="53113310569", symbol="ZEC_USDC",
                            purpose="TAKE_PROFIT", position_id=42, status="New")
    filled = SimpleNamespace(status=OrderStatus.FILLED, symbol="ZEC_USDC",
                             entry_price=100.0, exit_price=101.0,
                             executedQuantity=1.0, profit=1.0)

    class FakeSelf:
        logger = SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                                 error=lambda *a, **k: None, debug=lambda *a, **k: None)

        def _send_telegram(self, *a, **k):
            return None

        def _build_close_snapshot(self, profile, symbol):
            return {"entry": {"timeframe": "15", "rsi": 71.0}}

        def _stamp_signal_snapshot_on_trade(self, order_id, profile_name, snapshot):
            calls["stamped"] = snapshot
            calls["stamped_order_id"] = order_id

    patched = {
        "get_profile_manager": lambda: SimpleNamespace(_profiles={"profile3": profile}),
        "get_db_session": lambda: contextlib.nullcontext(None),
        "get_active_orders": lambda db, name: [order],
        "get_adapter": lambda p: SimpleNamespace(
            process_limit_order=lambda order, position_id: filled),
        "get_position": lambda db, pid: SimpleNamespace(ai_log_id=None),
    }
    originals = {k: getattr(ms, k) for k in patched}
    for k, v in patched.items():
        setattr(ms, k, v)
    try:
        MonitoringService._monitor_orders(FakeSelf())
    finally:
        for k, v in originals.items():
            setattr(ms, k, v)

    assert calls["stamped"] == {"entry": {"timeframe": "15", "rsi": 71.0}}
    # order_id is the join key onto the trade save_limit_trade booked
    assert calls["stamped_order_id"] == "53113310569"
    print("  ok limit TP/SL fill stamps a close snapshot")


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
               test_expiry, test_normalize_status_and_qty,
               test_taker_fallback_passes_signal_snapshot,
               test_maker_fill_stamps_signal_snapshot,
               test_missing_thesis_still_trades,
               test_limit_exit_fill_stamps_close_snapshot]:
        fn()
    print("\nALL MAKER HELPER TESTS PASSED")
