"""Unit tests for the remaining per-call config reads on the hot paths.

Three separate leaks found in the Neon query audit:

  * symbol_configs was queried once per (profile, symbol) on every sizing
    attempt — static config, 111k calls.
  * update_daily_snapshot SELECTed the row, wrote it, then db.refresh()ed it
    straight back — which is why it appeared twice in pg_stat_statements
    (6,954 with LIMIT, 6,733 without) — and committed even when nothing moved.
  * The candle fetcher re-read monitored_symbols every cycle, duplicating a
    list SymbolCache already holds.

No DB — the loaders are stubbed.
"""
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cache.symbol_config_cache import CachedSymbolConfig, SymbolConfigCache


def _rows(*specs):
    """Fake ORM rows: (profile, symbol, order_size)."""
    return [
        SimpleNamespace(profile_name=p, symbol=s,
                        order_size_usdc=Decimal(str(size)),
                        max_position_size_pct=None)
        for p, s, size in specs
    ]


def _cache_with(rows, ttl=300):
    """A SymbolConfigCache whose loader returns `rows`, counting DB trips."""
    cache = SymbolConfigCache(ttl_seconds=ttl)
    calls = {"n": 0}

    def _fake_session():
        calls["n"] += 1
        db = mock.MagicMock()
        db.query.return_value.filter.return_value.all.return_value = rows
        ctx = mock.MagicMock()
        ctx.__enter__ = mock.Mock(return_value=db)
        ctx.__exit__ = mock.Mock(return_value=False)
        return ctx

    patcher = mock.patch("db.utils.get_db_session", side_effect=_fake_session)
    return cache, calls, patcher


# --------------------------------------------------------------------------
# symbol_configs cache
# --------------------------------------------------------------------------

def test_whole_table_loads_in_one_query_and_serves_every_lookup():
    rows = _rows(("p1", "BTC_USDC", 100), ("p1", "ETH_USDC", 50),
                 ("p2", "SOL_USDC", 25))
    cache, calls, patcher = _cache_with(rows)

    with patcher:
        for _ in range(20):
            assert cache.get("p1", "BTC_USDC").order_size_usdc == Decimal("100")
            assert cache.get("p2", "SOL_USDC").order_size_usdc == Decimal("25")

    assert calls["n"] == 1, f"expected a single load, got {calls['n']}"


def test_absent_symbol_is_an_answer_not_a_cache_miss():
    """The common sizing case. Re-querying each unconfigured symbol is what
    made this hot in the first place."""
    cache, calls, patcher = _cache_with(_rows(("p1", "BTC_USDC", 100)))

    with patcher:
        for _ in range(10):
            assert cache.get("p1", "DOGE_USDC") is None

    assert calls["n"] == 1


def test_invalidate_forces_exactly_one_reload():
    cache, calls, patcher = _cache_with(_rows(("p1", "BTC_USDC", 100)))

    with patcher:
        cache.get("p1", "BTC_USDC")
        cache.invalidate()
        cache.get("p1", "BTC_USDC")
        cache.get("p1", "BTC_USDC")

    assert calls["n"] == 2


def test_ttl_expiry_reloads():
    cache, calls, patcher = _cache_with(_rows(("p1", "BTC_USDC", 100)), ttl=0)

    with patcher:
        cache.get("p1", "BTC_USDC")
        cache.get("p1", "BTC_USDC")

    assert calls["n"] == 2, "a zero TTL must reload every read"


def test_failed_refresh_keeps_serving_the_previous_load():
    """A DB blip must not stop the bot sizing trades."""
    cache, calls, patcher = _cache_with(_rows(("p1", "BTC_USDC", 100)))
    with patcher:
        assert cache.get("p1", "BTC_USDC").order_size_usdc == Decimal("100")

    cache.invalidate()
    with mock.patch("db.utils.get_db_session", side_effect=RuntimeError("neon down")):
        assert cache.get("p1", "BTC_USDC").order_size_usdc == Decimal("100")


def test_cached_config_is_immutable():
    """Handing out a mutable row would let one caller corrupt every other."""
    cfg = CachedSymbolConfig("p1", "BTC_USDC", Decimal("100"), None)
    try:
        cfg.order_size_usdc = Decimal("999")
    except Exception:
        return
    raise AssertionError("CachedSymbolConfig must be frozen")


def test_sizing_refuses_without_a_config_and_opens_no_session():
    """The refusal path should not cost a connection."""
    from utils.position_calculator import PositionCalculator

    calc = object.__new__(PositionCalculator)
    calc.logger = mock.MagicMock()
    calc.price_cache = mock.MagicMock()
    calc.price_cache.get_price.return_value = Decimal("100")
    calc.balance_cache = mock.MagicMock()

    cache = mock.MagicMock()
    cache.get.return_value = None
    profile = SimpleNamespace(name="p1", leverage_multiplier=1.0, max_open_positions=1)

    with mock.patch("utils.position_calculator.get_symbol_config_cache",
                    return_value=cache), \
            mock.patch("utils.position_calculator.get_db_session") as sess, \
            mock.patch("cache.portfolio_cache.get_portfolio_cache"):
        qty, reason = calc.calculate_buy_quantity("DOGE_USDC", profile)

    assert qty is None
    assert "No symbol config" in reason
    assert sess.call_count == 0, "no config -> no session"


# --------------------------------------------------------------------------
# update_daily_snapshot
# --------------------------------------------------------------------------

def _snapshot_db(snapshot):
    db = mock.MagicMock()
    db.query.return_value.filter.return_value.first.return_value = snapshot
    return db


def test_snapshot_update_does_not_commit_when_nothing_moved():
    from db.crud import update_daily_snapshot

    snap = SimpleNamespace(id=1, highest_balance=Decimal("200"),
                           lowest_balance=Decimal("50"))
    db = _snapshot_db(snap)

    update_daily_snapshot(db, 1, Decimal("100"))   # inside the existing range

    assert db.commit.call_count == 0
    assert db.refresh.call_count == 0


def test_snapshot_update_commits_once_when_the_high_moves():
    from db.crud import update_daily_snapshot

    snap = SimpleNamespace(id=1, highest_balance=Decimal("200"),
                           lowest_balance=Decimal("50"))
    db = _snapshot_db(snap)

    update_daily_snapshot(db, 1, Decimal("250"))

    assert snap.highest_balance == Decimal("250")
    assert db.commit.call_count == 1
    assert db.refresh.call_count == 0, "refresh re-SELECTs a row we just wrote"


def test_snapshot_update_still_seeds_null_extremes():
    from db.crud import update_daily_snapshot

    snap = SimpleNamespace(id=1, highest_balance=None, lowest_balance=None)
    db = _snapshot_db(snap)

    update_daily_snapshot(db, 1, Decimal("100"))

    assert snap.highest_balance == Decimal("100")
    assert snap.lowest_balance == Decimal("100")
    assert db.commit.call_count == 1


# --------------------------------------------------------------------------
# candle fetcher symbol resolution
# --------------------------------------------------------------------------

def test_resolve_symbols_reads_the_cache_not_the_db():
    from services.candle_fetcher_service import CandleFetcherService

    svc = CandleFetcherService(timeframes=["15"])
    svc.logger = mock.MagicMock()

    cache = mock.MagicMock()
    cache.get_all_symbols.return_value = ["BTC_USDC", "ETH_USDC"]

    with mock.patch("services.candle_fetcher_service.get_symbol_cache",
                    return_value=cache), \
            mock.patch("services.candle_fetcher_service.get_db_session") as sess, \
            mock.patch("services.candle_fetcher_service.get_settings_cache",
                       return_value=None):
        symbols = svc.resolve_symbols()

    assert symbols == ["BTC_USDC", "ETH_USDC"]
    assert sess.call_count == 0, "monitored_symbols must not be re-queried per cycle"


def test_resolve_symbols_falls_back_to_db_when_cache_is_empty():
    """The fetcher can start before anything has populated SymbolCache."""
    from services.candle_fetcher_service import CandleFetcherService

    svc = CandleFetcherService(timeframes=["15"])
    svc.logger = mock.MagicMock()

    cache = mock.MagicMock()
    cache.get_all_symbols.return_value = []

    with mock.patch("services.candle_fetcher_service.get_symbol_cache",
                    return_value=cache), \
            mock.patch("services.candle_fetcher_service.get_db_session"), \
            mock.patch("services.candle_fetcher_service.get_enabled_symbols_set",
                       return_value={"BTC_USDC"}) as db_read, \
            mock.patch("services.candle_fetcher_service.get_settings_cache",
                       return_value=None):
        symbols = svc.resolve_symbols()

    assert symbols == ["BTC_USDC"]
    assert db_read.call_count == 1


# --------------------------------------------------------------------------
# position sizing: three position queries collapsed into one
# --------------------------------------------------------------------------

def _sizing_calc(**over):
    """A PositionCalculator wired for calculate_buy_quantity, no DB."""
    from utils.position_calculator import PositionCalculator

    calc = object.__new__(PositionCalculator)
    calc.logger = mock.MagicMock()
    calc.price_cache = mock.MagicMock()
    calc.price_cache.get_price.return_value = Decimal("10")
    calc.balance_cache = mock.MagicMock()
    calc.balance_cache.get_available_balance.return_value = Decimal("100000")
    for k, v in over.items():
        setattr(calc, k, v)
    return calc


def _sizing_profile(**over):
    base = dict(name="p1", leverage_multiplier=1.0, max_open_positions=5,
                max_open_positions_per_profile=None)
    base.update(over)
    return SimpleNamespace(**base)


def _open_position(symbol, qty="1"):
    return SimpleNamespace(symbol=symbol, remaining_quantity=Decimal(str(qty)))


def _run_sizing(calc, profile, symbol, positions, portfolio=Decimal("100000")):
    """Run calculate_buy_quantity; returns (result, query_mock)."""
    cfg = CachedSymbolConfig("p1", symbol, Decimal("100"), Decimal("50"))
    portfolio_cache = mock.MagicMock()
    portfolio_cache.get_total_value.return_value = portfolio

    with mock.patch("utils.position_calculator.get_symbol_config_cache") as cache, \
            mock.patch("utils.position_calculator.get_db_session"), \
            mock.patch("cache.portfolio_cache.get_portfolio_cache",
                       return_value=portfolio_cache), \
            mock.patch("db.crud.get_open_positions_for_profile",
                       return_value=positions) as q:
        cache.return_value.get.return_value = cfg
        result = calc.calculate_buy_quantity(symbol, profile)
    return result, q


def test_sizing_issues_exactly_one_position_query():
    calc, profile = _sizing_calc(), _sizing_profile()
    (qty, reason), q = _run_sizing(calc, profile, "BTC_USDC", [])

    assert q.call_count == 1, f"expected 1 position query, got {q.call_count}"
    assert qty is not None, reason


def test_per_symbol_cap_still_counts_only_that_symbol():
    """The collapsed read spans every symbol — the cap must not count them all."""
    calc = _sizing_calc()
    profile = _sizing_profile(max_open_positions=2)
    positions = [_open_position("BTC_USDC"), _open_position("ETH_USDC"),
                 _open_position("SOL_USDC")]

    (qty, reason), q = _run_sizing(calc, profile, "BTC_USDC", positions)

    assert q.call_count == 1
    assert qty is not None, f"1 BTC position is under the cap of 2, got: {reason}"


def test_per_symbol_cap_still_blocks_at_the_limit():
    calc = _sizing_calc()
    profile = _sizing_profile(max_open_positions=2)
    positions = [_open_position("BTC_USDC"), _open_position("BTC_USDC"),
                 _open_position("ETH_USDC")]

    (qty, reason), _ = _run_sizing(calc, profile, "BTC_USDC", positions)

    assert qty is None
    assert "Max open positions reached for symbol" in reason
    assert "2/2" in reason


def test_per_profile_cap_still_counts_every_symbol():
    calc = _sizing_calc()
    profile = _sizing_profile(max_open_positions=99,
                              max_open_positions_per_profile=3)
    positions = [_open_position("BTC_USDC"), _open_position("ETH_USDC"),
                 _open_position("SOL_USDC")]

    (qty, reason), q = _run_sizing(calc, profile, "BTC_USDC", positions)

    assert qty is None
    assert "Max open positions reached for profile" in reason
    assert "3/3" in reason
    assert q.call_count == 1


def test_existing_exposure_sums_only_the_requested_symbol():
    """Capacity maths must not charge other symbols' positions against it."""
    calc = _sizing_calc()
    profile = _sizing_profile()
    # max_position_size_pct 50% of 100k = 50k cap. 3 BTC @ 10 = 30 used.
    positions = [_open_position("BTC_USDC", 1), _open_position("BTC_USDC", 2),
                 _open_position("ETH_USDC", 9999)]

    assert calc._existing_position_value(
        [p for p in positions if p.symbol == "BTC_USDC"], Decimal("10")
    ) == Decimal("30")

    (qty, reason), _ = _run_sizing(calc, profile, "BTC_USDC", positions)
    assert qty is not None, f"ETH exposure must not block BTC: {reason}"


def test_existing_exposure_is_zero_with_no_positions():
    calc = _sizing_calc()
    assert calc._existing_position_value([], Decimal("10")) == Decimal("0")


if __name__ == "__main__":
    for fn in [test_whole_table_loads_in_one_query_and_serves_every_lookup,
               test_absent_symbol_is_an_answer_not_a_cache_miss,
               test_invalidate_forces_exactly_one_reload,
               test_ttl_expiry_reloads,
               test_failed_refresh_keeps_serving_the_previous_load,
               test_cached_config_is_immutable,
               test_sizing_refuses_without_a_config_and_opens_no_session,
               test_snapshot_update_does_not_commit_when_nothing_moved,
               test_snapshot_update_commits_once_when_the_high_moves,
               test_snapshot_update_still_seeds_null_extremes,
               test_resolve_symbols_reads_the_cache_not_the_db,
               test_resolve_symbols_falls_back_to_db_when_cache_is_empty,
               test_sizing_issues_exactly_one_position_query,
               test_per_symbol_cap_still_counts_only_that_symbol,
               test_per_symbol_cap_still_blocks_at_the_limit,
               test_per_profile_cap_still_counts_every_symbol,
               test_existing_exposure_sums_only_the_requested_symbol,
               test_existing_exposure_is_zero_with_no_positions]:
        fn()
        print(f"  ok {fn.__name__}")
    print("\nALL CONFIG-CACHE DB COST TESTS PASSED")
