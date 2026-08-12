"""Unit tests for the monitoring loop's per-iteration DB cost.

_monitor_orders, _monitor_open_positions and _validate_open_positions each ran
one query per profile on every iteration — and _monitor_orders opened a fresh
session per profile on top. With 8 profiles that is 16 queries and 8 sessions
per loop, which made these the two most-called statements in the database.
These tests pin the batched shape: one query each, one session, and every
profile still sees exactly its own rows.

No DB, no exchange — collaborators are stubbed.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.monitoring_service import MonitoringService, _group_by_profile

PROFILES = ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"]


def _profile(name):
    return SimpleNamespace(name=name, display_name=name, market_type="SPOT")


def _service():
    """A MonitoringService with only what these three paths touch."""
    svc = object.__new__(MonitoringService)
    svc.logger = mock.MagicMock()
    svc.price_cache = mock.MagicMock()
    svc.price_cache.get_price.return_value = None   # skip the TP/SL body
    svc.settings = SimpleNamespace(trend_invalidation_interval=999)
    svc._trend_invalidation_counter = 0
    return svc


def _profile_manager():
    pm = mock.MagicMock()
    pm._profiles = {n: _profile(n) for n in PROFILES}
    return pm


def _position(profile_name, symbol="BTC_USDC"):
    return SimpleNamespace(
        profile_name=profile_name, symbol=symbol, direction="LONG",
        entry_price=100.0, tp_price=None, sl_price=None,
        trailing_sl_price=None, trailing_stop_armed=False,
        highest_price=None, lowest_price=None, id=1,
    )


def _order(profile_name, purpose="TAKE_PROFIT"):
    return SimpleNamespace(
        profile_name=profile_name, symbol="BTC_USDC", purpose=purpose,
        position_id=1, exchange_order_id="x1", created_at=0,
    )


# --------------------------------------------------------------------------
# _monitor_orders
# --------------------------------------------------------------------------

def test_monitor_orders_uses_one_query_and_one_session():
    svc = _service()
    orders = [_order(n) for n in PROFILES]

    with mock.patch("services.monitoring_service.get_profile_manager",
                    return_value=_profile_manager()), \
            mock.patch("services.monitoring_service.get_db_session") as sess, \
            mock.patch("services.monitoring_service.get_active_orders_for_profiles",
                       return_value=orders) as batched, \
            mock.patch("services.monitoring_service.get_adapter") as adapter:
        adapter.return_value.process_limit_order.return_value = None
        svc._monitor_orders()

    assert batched.call_count == 1, "one query for every profile, not one each"
    assert sess.call_count == 1, "one session for every profile, not one each"
    assert batched.call_args.args[1] == PROFILES


def test_monitor_orders_gives_each_profile_only_its_own_orders():
    svc = _service()
    # p1 has two orders, p3 has one, everyone else none.
    orders = [_order("p1"), _order("p1"), _order("p3")]
    seen = []

    with mock.patch("services.monitoring_service.get_profile_manager",
                    return_value=_profile_manager()), \
            mock.patch("services.monitoring_service.get_db_session"), \
            mock.patch("services.monitoring_service.get_active_orders_for_profiles",
                       return_value=orders), \
            mock.patch("services.monitoring_service.get_adapter") as adapter:
        adapter.return_value.process_limit_order.side_effect = (
            lambda order, position_id: seen.append(order.profile_name)
        )
        svc._monitor_orders()

    assert seen == ["p1", "p1", "p3"]


def test_monitor_orders_entry_purpose_still_routes_to_the_reconciler():
    """Grouping must not disturb the ENTRY vs exit split."""
    svc = _service()
    svc._reconcile_maker_entry = mock.MagicMock()
    orders = [_order("p1", purpose="ENTRY"), _order("p2", purpose="STOP_LOSS")]

    with mock.patch("services.monitoring_service.get_profile_manager",
                    return_value=_profile_manager()), \
            mock.patch("services.monitoring_service.get_db_session"), \
            mock.patch("services.monitoring_service.get_active_orders_for_profiles",
                       return_value=orders), \
            mock.patch("services.monitoring_service.get_adapter") as adapter:
        adapter.return_value.process_limit_order.return_value = None
        svc._monitor_orders()

    assert svc._reconcile_maker_entry.call_count == 1
    assert svc._reconcile_maker_entry.call_args.args[2].profile_name == "p1"
    assert adapter.return_value.process_limit_order.call_count == 1


# --------------------------------------------------------------------------
# _monitor_open_positions
# --------------------------------------------------------------------------

def test_monitor_open_positions_uses_one_query():
    svc = _service()
    positions = [_position(n) for n in PROFILES]

    with mock.patch("services.monitoring_service.get_profile_manager",
                    return_value=_profile_manager()), \
            mock.patch("services.monitoring_service.get_position_manager"), \
            mock.patch("services.monitoring_service.get_db_session"), \
            mock.patch("services.monitoring_service.get_open_positions_for_profiles",
                       return_value=positions) as batched:
        svc._monitor_open_positions()

    assert batched.call_count == 1
    assert batched.call_args.args[1] == PROFILES


def test_monitor_open_positions_walks_every_profiles_rows():
    svc = _service()
    positions = [_position("p2"), _position("p2"), _position("p7")]

    with mock.patch("services.monitoring_service.get_profile_manager",
                    return_value=_profile_manager()), \
            mock.patch("services.monitoring_service.get_position_manager"), \
            mock.patch("services.monitoring_service.get_db_session"), \
            mock.patch("services.monitoring_service.get_open_positions_for_profiles",
                       return_value=positions):
        svc._monitor_open_positions()

    # price_cache is consulted once per position — 3 rows, 3 lookups, so no
    # profile's rows were dropped and none were visited twice.
    assert svc.price_cache.get_price.call_count == 3


# --------------------------------------------------------------------------
# _validate_open_positions
# --------------------------------------------------------------------------

def test_validate_open_positions_uses_one_query():
    svc = _service()
    svc._validate_spot_positions = mock.MagicMock()
    positions = [_position("p1"), _position("p4")]

    with mock.patch("services.monitoring_service.get_profile_manager",
                    return_value=_profile_manager()), \
            mock.patch("services.monitoring_service.get_db_session"), \
            mock.patch("services.monitoring_service.get_balance_cache"), \
            mock.patch("services.monitoring_service.get_open_positions_for_profiles",
                       return_value=positions) as batched:
        svc._validate_open_positions()

    assert batched.call_count == 1
    # Profiles with nothing open are skipped, exactly as before.
    assert svc._validate_spot_positions.call_count == 2
    validated = [c.args[1].name for c in svc._validate_spot_positions.call_args_list]
    assert validated == ["p1", "p4"]


def test_validate_open_positions_skips_profiles_with_nothing_open():
    svc = _service()
    svc._validate_spot_positions = mock.MagicMock()

    with mock.patch("services.monitoring_service.get_profile_manager",
                    return_value=_profile_manager()), \
            mock.patch("services.monitoring_service.get_db_session"), \
            mock.patch("services.monitoring_service.get_balance_cache"), \
            mock.patch("services.monitoring_service.get_open_positions_for_profiles",
                       return_value=[]):
        svc._validate_open_positions()

    assert svc._validate_spot_positions.call_count == 0


def test_grouping_returns_empty_list_for_an_absent_profile():
    """A KeyError here would take down the whole loop iteration."""
    grouped = _group_by_profile([_position("p1")])
    assert grouped.get("p9", []) == []
    assert len(grouped["p1"]) == 1


if __name__ == "__main__":
    for fn in [test_monitor_orders_uses_one_query_and_one_session,
               test_monitor_orders_gives_each_profile_only_its_own_orders,
               test_monitor_orders_entry_purpose_still_routes_to_the_reconciler,
               test_monitor_open_positions_uses_one_query,
               test_monitor_open_positions_walks_every_profiles_rows,
               test_validate_open_positions_uses_one_query,
               test_validate_open_positions_skips_profiles_with_nothing_open,
               test_grouping_returns_empty_list_for_an_absent_profile]:
        fn()
        print(f"  ok {fn.__name__}")
    print("\nALL MONITOR-LOOP DB COST TESTS PASSED")
