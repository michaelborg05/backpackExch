"""Unit tests for the signal-scan loop's DB cost and cooldown semantics.

Position sizing used to run for every symbol of every profile on every cycle,
before any signal existed — a DB session and ~4 queries each, almost always
wasted. These tests pin the new ordering: a cycle that produces no signal must
not size anything, and the per-symbol cooldown must only start once a signal
was actually acted on.

No DB, no exchange — collaborators are stubbed.
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.monitoring_service import MonitoringService

SYMBOLS = ["BTC_USDC", "ETH_USDC", "SOL_USDC", "ZEC_USDC"]


def _profile(**over):
    base = dict(
        name="profile4",
        display_name="15m_tf_v9_atrcap070",
        trading_hours=[],
        signal_cooldown_minutes=15,
        max_open_positions_per_profile=2,
        risk_group=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _service():
    """A MonitoringService with only the attributes the scan path touches."""
    svc = object.__new__(MonitoringService)
    svc.logger = mock.MagicMock()
    svc._last_signals = {}
    svc._symbol_cache = mock.MagicMock()
    svc._symbol_cache.get_symbols_for_profile.return_value = list(SYMBOLS)
    svc.position_calculator = mock.MagicMock()
    svc._get_risk_group_config = mock.MagicMock(return_value=None)
    return svc


def _patches(signals, open_positions=0):
    cb = mock.MagicMock()
    cb.check_circuit_breakers.return_value = (True, "ok")
    gen = mock.MagicMock()
    gen.scan_symbols.return_value = signals
    return (
        mock.patch("services.monitoring_service.get_circuit_breaker", return_value=cb),
        mock.patch("services.monitoring_service.get_signal_generator", return_value=gen),
        mock.patch("services.monitoring_service.get_db_session"),
        mock.patch("services.monitoring_service.count_open_positions_for_profiles",
                   return_value=open_positions),
        gen,
    )


def test_quiet_cycle_never_sizes_a_position():
    """No signals -> position sizing must not be called at all."""
    svc = _service()
    p_cb, p_gen, p_db, p_count, gen = _patches(signals=[])
    with p_cb, p_gen, p_db, p_count:
        svc._process_signals_for_profile(_profile())

    gen.scan_symbols.assert_called_once_with(SYMBOLS)
    assert svc.position_calculator.calculate_buy_quantity.call_count == 0, (
        "a quiet cycle sized a position — the per-symbol pre-flight is back"
    )
    print("  ok quiet cycle: 0 sizing calls, all symbols still scanned")


def test_at_profile_cap_short_circuits_before_scanning():
    """At the position cap nothing can trade, so don't even scan."""
    svc = _service()
    p_cb, p_gen, p_db, p_count, gen = _patches(signals=[], open_positions=2)
    with p_cb, p_gen, p_db, p_count:
        svc._process_signals_for_profile(_profile(max_open_positions_per_profile=2))

    gen.scan_symbols.assert_not_called()
    assert svc.position_calculator.calculate_buy_quantity.call_count == 0
    print("  ok at cap: bails before scanning, one capacity query only")


def test_symbols_in_cooldown_are_not_scanned():
    svc = _service()
    svc._last_signals["profile4_BTC_USDC"] = time.time()      # fresh -> in cooldown
    svc._last_signals["profile4_ETH_USDC"] = time.time() - 3600  # expired
    p_cb, p_gen, p_db, p_count, gen = _patches(signals=[])
    with p_cb, p_gen, p_db, p_count:
        svc._process_signals_for_profile(_profile())

    scanned = gen.scan_symbols.call_args[0][0]
    assert "BTC_USDC" not in scanned
    assert "ETH_USDC" in scanned
    print("  ok cooldown filter still applies, and costs no DB call")


def test_cooldown_stamped_only_when_signal_executed():
    """A rejected signal must not silence the symbol for a whole cooldown."""
    for executed, should_stamp in ((True, True), (False, False)):
        svc = _service()
        signal = SimpleNamespace(symbol="SOL_USDC", confidence=90.0)
        p_cb, p_gen, p_db, p_count, gen = _patches(signals=[signal])
        svc._execute_signal = mock.MagicMock(return_value=executed)
        with p_cb, p_gen, p_db, p_count:
            svc._process_signals_for_profile(_profile())

        stamped = "profile4_SOL_USDC" in svc._last_signals
        assert stamped is should_stamp, (
            f"executed={executed}: expected stamped={should_stamp}, got {stamped}"
        )
    print("  ok cooldown stamped on execution only, not on rejection")


def test_all_symbols_in_cooldown_skips_scan_entirely():
    svc = _service()
    for s in SYMBOLS:
        svc._last_signals[f"profile4_{s}"] = time.time()
    p_cb, p_gen, p_db, p_count, gen = _patches(signals=[])
    with p_cb, p_gen, p_db, p_count:
        svc._process_signals_for_profile(_profile())

    gen.scan_symbols.assert_not_called()
    print("  ok fully-cooled profile does no scan and no sizing")


if __name__ == "__main__":
    for fn in [test_quiet_cycle_never_sizes_a_position,
               test_at_profile_cap_short_circuits_before_scanning,
               test_symbols_in_cooldown_are_not_scanned,
               test_cooldown_stamped_only_when_signal_executed,
               test_all_symbols_in_cooldown_skips_scan_entirely]:
        fn()
    print("\nALL SIGNAL-LOOP TESTS PASSED")
