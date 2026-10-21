"""Unit tests for the two guards against a thin Backpack book.

1. Binance cross-check: a Backpack price more than max_reference_deviation_pct
   from Binance is not cached (RAY_USDC: +33% on 2026-10-18, -5% on 2026-10-20,
   Binance unmoved both times).
2. IOC limit exits: automated long exits sell no lower than
   exit_max_slippage_pct below the cached price instead of market-selling into
   a hollow bid side (2026-10-20: RAY filled at 1.8686 with Binance at 2.007).
   Nothing filled -> position stays open and retries; part filled -> the rest
   stays open and retries.

No DB, no exchange — collaborators are stubbed.
"""
import sys
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.price_resolution import book_top


SANE_RAY_BOOK = {"bids": [["2.0040", "167"]], "asks": [["2.0060", "160"]]}   # mid 2.005


# ── fetch_reference_prices ──────────────────────────────────────────────────

def test_reference_prices_are_keyed_by_backpack_symbol():
    from api_builders import market_builder
    rows = [{"symbol": "RAYUSDT", "price": "2.0070"}, {"symbol": "BTCUSDT", "price": "83000"}]
    with mock.patch.object(market_builder, "api_request", return_value=rows) as req:
        prices = market_builder.fetch_reference_prices(["RAY_USDC", "BTC_USDC"])

    assert prices == {"RAY_USDC": Decimal("2.0070"), "BTC_USDC": Decimal("83000")}
    assert req.call_count == 1                       # one request for the roster
    assert "RAYUSDT" in req.call_args.args[0]


def test_rejected_batch_falls_back_to_the_full_price_list():
    """Binance 400s the whole batch if one symbol is unknown to it."""
    from api_builders import market_builder
    full = [{"symbol": "RAYUSDT", "price": "2.0070"}, {"symbol": "ETHUSDT", "price": "2450"}]
    with mock.patch.object(market_builder, "api_request", side_effect=[None, full]):
        prices = market_builder.fetch_reference_prices(["RAY_USDC", "NEWCOIN_USDC"])

    assert prices == {"RAY_USDC": Decimal("2.0070")}


def test_http_error_on_the_batch_still_falls_back():
    """api_request RAISES on HTTP 400 — found against the live API."""
    from api_builders import market_builder
    from utils.exceptions import ExchangeAPIError
    full = [{"symbol": "RAYUSDT", "price": "2.0070"}]
    with mock.patch.object(market_builder, "api_request",
                           side_effect=[ExchangeAPIError("HTTP 400 Invalid symbol"), full]):
        assert market_builder.fetch_reference_prices(["RAY_USDC", "X_USDC"]) == \
            {"RAY_USDC": Decimal("2.0070")}


def test_binance_down_returns_no_references():
    from api_builders import market_builder
    with mock.patch.object(market_builder, "api_request", return_value=None):
        assert market_builder.fetch_reference_prices(["RAY_USDC"]) == {}


# ── cross-check in _monitor_prices ──────────────────────────────────────────

def _price_service(max_ref_dev=1.5):
    from services.monitoring_service import MonitoringService
    svc = object.__new__(MonitoringService)
    svc.logger = mock.MagicMock()
    svc._symbol_cache = mock.MagicMock()
    svc._symbol_cache.get_all_symbols.return_value = ["RAY_USDC"]
    svc.price_cache = mock.MagicMock()
    svc.settings = SimpleNamespace(max_book_spread_pct=2.0, price_stale_warn_pct=1.0,
                                   max_last_fill_age_secs=300,
                                   max_reference_deviation_pct=max_ref_dev)
    return svc


def _run_prices(svc, references, book=SANE_RAY_BOOK):
    with mock.patch("services.monitoring_service.fetch_all_tickers", return_value={}), \
         mock.patch("services.monitoring_service.fetch_book_top", return_value=book_top(book)), \
         mock.patch("services.monitoring_service.fetch_reference_prices",
                    return_value=references) as refs:
        svc._monitor_prices()
    return refs


def test_price_far_from_binance_is_not_cached():
    """2026-10-18 shape: Backpack book reads 2.005, Binance says 1.78 (+12.6%)."""
    svc = _price_service()
    _run_prices(svc, {"RAY_USDC": Decimal("1.78")})

    svc.price_cache.update_ticker.assert_not_called()
    message = svc.logger.error.call_args.args[0]
    assert "Rejected RAY_USDC" in message and "off Binance" in message


def test_price_close_to_binance_is_cached():
    svc = _price_service()
    _run_prices(svc, {"RAY_USDC": Decimal("2.007")})      # -0.10%, the normal basis

    args, _ = svc.price_cache.update_ticker.call_args
    assert Decimal(args[1]) == Decimal("2.005")


def test_no_reference_means_no_check():
    """Binance down or symbol not listed there: can't check, so don't block."""
    svc = _price_service()
    _run_prices(svc, {})
    assert svc.price_cache.update_ticker.call_count == 1


def test_zero_deviation_setting_disables_the_check():
    svc = _price_service(max_ref_dev=0)
    refs = _run_prices(svc, {"RAY_USDC": Decimal("1.0")})
    refs.assert_not_called()
    assert svc.price_cache.update_ticker.call_count == 1


# ── exit floor ──────────────────────────────────────────────────────────────

def _exit_service(slippage=1.0, cached="2.0050"):
    from services.monitoring_service import MonitoringService
    svc = object.__new__(MonitoringService)
    svc.logger = mock.MagicMock()
    svc.price_cache = mock.MagicMock()
    svc.price_cache.get_price.return_value = Decimal(cached) if cached else None
    svc.settings = SimpleNamespace(exit_max_slippage_pct=slippage)
    svc._unfilled_exit_alerts = {}
    svc._last_signals = {}
    svc._send_telegram = mock.MagicMock()
    svc._build_close_snapshot = mock.MagicMock(return_value=None)
    svc.circuit_breaker = mock.MagicMock()
    return svc


def _profile(exchange="backpack"):
    return SimpleNamespace(name="profile7", display_name=None, exchange_type=exchange)


def test_long_backpack_exit_floor_is_slippage_below_the_cached_price():
    svc = _exit_service()
    assert svc._exit_floor_price(_profile(), "RAY_USDC", True) == Decimal("2.0050") * Decimal("0.99")


def test_market_order_when_floor_does_not_apply():
    assert _exit_service()._exit_floor_price(_profile(), "RAY_USDC", False) is None        # short
    assert _exit_service()._exit_floor_price(_profile("bullet"), "RAY_USDC", True) is None
    assert _exit_service(slippage=0)._exit_floor_price(_profile(), "RAY_USDC", True) is None
    assert _exit_service(cached=None)._exit_floor_price(_profile(), "RAY_USDC", True) is None


# ── _execute_close outcomes ─────────────────────────────────────────────────

def _position():
    return SimpleNamespace(id=5648, symbol="RAY_USDC", remaining_quantity=Decimal("241"),
                           direction="LONG", ai_log_id=None,
                           entry_trade=SimpleNamespace(price=Decimal("1.9379")))


def _close(svc, result):
    adapter = mock.MagicMock()
    adapter.order_sell.return_value = result
    with mock.patch("services.monitoring_service.get_adapter", return_value=adapter):
        svc._execute_close(db=mock.MagicMock(), position=_position(),
                           profile=_profile(), reason="TRAILING_STOP")
    return adapter


def test_exit_goes_out_as_an_ioc_limit_at_the_floor():
    svc = _exit_service()
    result = SimpleNamespace(id="1", quantity="241", executed_quantity="241",
                             executed_quote_quantity=str(Decimal("241") * Decimal("2.004")))
    adapter = _close(svc, result)

    kwargs = adapter.order_sell.call_args.kwargs
    assert Decimal(kwargs["price"]) == Decimal("2.0050") * Decimal("0.99")
    assert kwargs["time_in_force"] == "IOC"
    assert "RAY_USDC" in svc._send_telegram.call_args.args[0]
    assert "profile7_RAY_USDC" in svc._last_signals              # a real close


def test_unfilled_exit_keeps_the_position_and_alerts_once():
    svc = _exit_service()
    nothing = SimpleNamespace(id="1", quantity="241", executed_quantity="0",
                              executed_quote_quantity="0")
    _close(svc, nothing)
    _close(svc, nothing)                                          # next cycle

    assert svc._send_telegram.call_count == 1                     # throttled
    assert "Exit held" in svc._send_telegram.call_args.args[0]
    assert svc._last_signals == {}                                # not a close
    svc.circuit_breaker.record_position_close.assert_not_called()


def test_partial_exit_reports_and_does_not_count_as_a_close():
    svc = _exit_service()
    part = SimpleNamespace(id="1", quantity="241", executed_quantity="100",
                           executed_quote_quantity="200.4")
    _close(svc, part)

    assert "Partial exit" in svc._send_telegram.call_args.args[0]
    assert svc._last_signals == {}
    svc.circuit_breaker.record_position_close.assert_not_called()


# ── ProcessMarketOrder bookkeeping ──────────────────────────────────────────

def _trading_service():
    from api_builders.trading_builder import TradingService
    ts = object.__new__(TradingService)
    ts.logger = mock.MagicMock()
    ts.profile = SimpleNamespace(name="profile7")
    ts._refresh_balance_cache_after_trade = mock.MagicMock()
    return ts


def _ioc_sell():
    from models.trade import create_sell
    return create_sell("RAY_USDC", "241", "1.98495", time_in_force="IOC")


def _response(executed, quote):
    return SimpleNamespace(id="9", side="Ask", status="Expired", executed_quantity=executed,
                           executed_quote_quantity=quote, profit=None)


def test_unfilled_ioc_records_nothing():
    ts = _trading_service()
    ts.ExecuteOrder = mock.MagicMock(return_value=_response("0", "0"))
    with mock.patch("api_builders.trading_builder.SessionLocal"), \
         mock.patch("api_builders.trading_builder.save_trade") as save, \
         mock.patch("api_builders.trading_builder.close_position") as close:
        ts.ProcessMarketOrder(_ioc_sell(), source="TRAILING_STOP", position_id="5648")

    save.assert_not_called()
    close.assert_not_called()


def test_part_filled_ioc_reduces_instead_of_closing():
    ts = _trading_service()
    ts.ExecuteOrder = mock.MagicMock(return_value=_response("100", "200.4"))
    trade = SimpleNamespace(id=1, price=Decimal("2.004"), quantity=Decimal("100"),
                            symbol="RAY_USDC")
    with mock.patch("api_builders.trading_builder.SessionLocal"), \
         mock.patch("api_builders.trading_builder.save_trade", return_value=trade), \
         mock.patch("api_builders.trading_builder.close_position") as close, \
         mock.patch("db.crud.reduce_position") as reduce:
        reduce.return_value = SimpleNamespace(symbol="RAY_USDC", remaining_quantity=Decimal("141"))
        ts.ProcessMarketOrder(_ioc_sell(), source="TRAILING_STOP", position_id="5648")

    close.assert_not_called()
    assert reduce.call_args.args[1] == 5648


def test_fully_filled_ioc_closes():
    ts = _trading_service()
    ts.ExecuteOrder = mock.MagicMock(return_value=_response("241", "482.964"))
    trade = SimpleNamespace(id=1, price=Decimal("2.004"), quantity=Decimal("241"),
                            symbol="RAY_USDC")
    closed = SimpleNamespace(id=5648, symbol="RAY_USDC", direction="LONG",
                             entry_price=Decimal("1.9379"), quantity=Decimal("241"),
                             profit=Decimal("16.07"))
    with mock.patch("api_builders.trading_builder.SessionLocal"), \
         mock.patch("api_builders.trading_builder.save_trade", return_value=trade), \
         mock.patch("api_builders.trading_builder.close_position", return_value=closed) as close, \
         mock.patch("db.crud.reduce_position") as reduce:
        ts.ProcessMarketOrder(_ioc_sell(), source="TRAILING_STOP", position_id="5648")

    assert close.call_count == 1
    reduce.assert_not_called()


# ── crud P/L across partial exits ───────────────────────────────────────────

def _db_returning(position):
    db = mock.MagicMock()
    db.query.return_value.filter.return_value.first.return_value = position
    return db


def test_partial_then_final_exit_profit_adds_up():
    from db.crud import close_position, reduce_position
    pos = SimpleNamespace(id=1, direction="LONG", entry_price=Decimal("2.00"),
                          quantity=Decimal("300"), remaining_quantity=Decimal("300"),
                          profit=None)
    db = _db_returning(pos)

    reduce_position(db, 1, SimpleNamespace(price=Decimal("2.10"), quantity=Decimal("100")))
    assert pos.remaining_quantity == Decimal("200")
    assert pos.profit == Decimal("10.00")                 # 100 x +0.10

    close_position(db, 1, SimpleNamespace(id=7, price=Decimal("1.90")))
    assert pos.profit == Decimal("-10.00")                # +10 then 200 x -0.10
    assert pos.remaining_quantity == 0 and pos.status == "CLOSED"


def test_unpartialled_close_profit_is_unchanged():
    from db.crud import close_position
    pos = SimpleNamespace(id=1, direction="LONG", entry_price=Decimal("1.9379"),
                          quantity=Decimal("241"), remaining_quantity=Decimal("241"),
                          profit=None)
    close_position(_db_returning(pos), 1, SimpleNamespace(id=7, price=Decimal("1.8685")))
    assert pos.profit == (Decimal("1.8685") - Decimal("1.9379")) * Decimal("241")


def test_save_trade_records_the_average_fill_not_the_limit():
    from db.crud import save_trade
    order = SimpleNamespace(id="9", symbol="RAY_USDC", side="Ask", price="1.98495",
                            executed_quantity="241", executed_quote_quantity="482.964")
    with mock.patch("db.crud.Trade", side_effect=lambda **kw: SimpleNamespace(**kw)):
        trade = save_trade(mock.MagicMock(), order, "profile7", "TRAILING_STOP")
    assert trade.price == Decimal("482.964") / Decimal("241")      # 2.004, not 1.98495


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\nALL {len(tests)} EXIT PROTECTION TESTS PASSED")
