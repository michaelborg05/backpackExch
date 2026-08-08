"""Unit tests for the batched re-entry lookup.

can_reenter() used to open a DB session per symbol — a full remote round trip
each, which dominated the scan loop. It now prefers a batch primed once per
scan. These tests pin the behaviour that must not change: the batch has to give
the same answers as the per-symbol query, and it must never outlive its scan.

No DB — the query path is stubbed.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.reentry_manager import ReEntryManager, RecentExit
from utils.constants import StrategyType

NOW = datetime.now(timezone.utc)


def _mgr():
    mgr = object.__new__(ReEntryManager)
    mgr.logger = mock.MagicMock()
    mgr.settings = SimpleNamespace(
        cooldown_stop_loss_mins=35,
        cooldown_take_profit_mins=35,
        cooldown_default_mins=15,
    )
    mgr._prefetched = {}
    return mgr


def _trend():
    return SimpleNamespace(rsi=55.0, symbol="SOL_USDC", timeframe="15")


def test_lookback_covers_the_longest_cooldown():
    """The prefetch window must not be shorter than the cooldown it gates."""
    mgr = _mgr()
    # 490m SL cooldown -> ceil(490/60)+1 = 10h
    assert mgr.reentry_lookback_hours(490, 250) == 10
    # short cooldowns still floor at 2h
    assert mgr.reentry_lookback_hours(5, 5) == 2
    # profile overrides of None fall back to global settings (35/35/15 -> 2h)
    assert mgr.reentry_lookback_hours(None, None) == 2
    print("  ok lookback window derived once, covers the longest cooldown")


def test_primed_batch_avoids_the_db_entirely():
    mgr = _mgr()
    mgr._prefetched["profile4"] = {}          # primed, no exits found
    with mock.patch("services.reentry_manager.get_db_session") as db:
        ok, reason = mgr.can_reenter(
            symbol="SOL_USDC", profile_name="profile4", timeframe="15",
            current_trend=_trend(), strategy_type=StrategyType.TREND_FOLLOWING,
        )
    db.assert_not_called()
    assert ok and reason == "No recent exit"
    print("  ok primed scan answers with zero DB sessions")


def test_unprimed_profile_still_queries():
    """Callers outside the scan loop must keep working."""
    mgr = _mgr()
    with mock.patch("services.reentry_manager.get_db_session") as db, \
         mock.patch.object(ReEntryManager, "_get_most_recent_exit", return_value=None) as q:
        ok, reason = mgr.can_reenter(
            symbol="SOL_USDC", profile_name="profile4", timeframe="15",
            current_trend=_trend(), strategy_type=StrategyType.TREND_FOLLOWING,
        )
    db.assert_called_once()
    q.assert_called_once()
    assert ok and reason == "No recent exit"
    print("  ok unprimed profile falls back to the single-symbol query")


def test_batch_and_per_symbol_agree_on_an_active_cooldown():
    """A symbol inside its cooldown must be blocked either way."""
    recent = RecentExit(symbol="SOL_USDC", closed_at=NOW - timedelta(minutes=5),
                        close_reason="STOP_LOSS", exit_price=100.0)
    answers = []

    # via primed batch
    mgr = _mgr()
    mgr._prefetched["profile4"] = {"SOL_USDC": recent}
    with mock.patch("services.reentry_manager.get_db_session"):
        answers.append(mgr.can_reenter(
            symbol="SOL_USDC", profile_name="profile4", timeframe="15",
            current_trend=_trend(), strategy_type=StrategyType.TREND_FOLLOWING,
            sl_cooldown_minutes=130))

    # via per-symbol query
    mgr2 = _mgr()
    with mock.patch("services.reentry_manager.get_db_session"), \
         mock.patch.object(ReEntryManager, "_get_most_recent_exit", return_value=recent):
        answers.append(mgr2.can_reenter(
            symbol="SOL_USDC", profile_name="profile4", timeframe="15",
            current_trend=_trend(), strategy_type=StrategyType.TREND_FOLLOWING,
            sl_cooldown_minutes=130))

    assert answers[0] == answers[1], f"batch and per-symbol disagree: {answers}"
    assert answers[0][0] is False and "Cooldown" in answers[0][1]
    print("  ok batch and per-symbol give identical cooldown verdicts")


def test_missing_symbol_in_batch_reads_as_no_recent_exit():
    """Prefetch stores only symbols that had exits; absence means none."""
    mgr = _mgr()
    mgr._prefetched["profile4"] = {
        "BTC_USDC": RecentExit("BTC_USDC", NOW - timedelta(minutes=1), "STOP_LOSS", 1.0)
    }
    with mock.patch("services.reentry_manager.get_db_session") as db:
        ok, reason = mgr.can_reenter(
            symbol="SOL_USDC", profile_name="profile4", timeframe="15",
            current_trend=_trend(), strategy_type=StrategyType.TREND_FOLLOWING,
        )
    db.assert_not_called()
    assert ok and reason == "No recent exit"
    print("  ok symbol absent from batch == no recent exit, no extra query")


def test_clear_restores_live_lookups():
    mgr = _mgr()
    mgr._prefetched["profile4"] = {}
    mgr.clear_recent_exits("profile4")
    with mock.patch("services.reentry_manager.get_db_session"), \
         mock.patch.object(ReEntryManager, "_get_most_recent_exit", return_value=None) as q:
        mgr.can_reenter(
            symbol="SOL_USDC", profile_name="profile4", timeframe="15",
            current_trend=_trend(), strategy_type=StrategyType.TREND_FOLLOWING,
        )
    q.assert_called_once()

    mgr._prefetched["a"] = {}
    mgr._prefetched["b"] = {}
    mgr.clear_recent_exits()
    assert mgr._prefetched == {}
    print("  ok cleared batch cannot outlive its scan")


if __name__ == "__main__":
    for fn in [test_lookback_covers_the_longest_cooldown,
               test_primed_batch_avoids_the_db_entirely,
               test_unprimed_profile_still_queries,
               test_batch_and_per_symbol_agree_on_an_active_cooldown,
               test_missing_symbol_in_batch_reads_as_no_recent_exit,
               test_clear_restores_live_lookups]:
        fn()
    print("\nALL RE-ENTRY PREFETCH TESTS PASSED")
