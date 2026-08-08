#!/usr/bin/env python3
"""
test_exit_indicators.py
=======================
Run exit indicator variants for dip_v5 and dip_v7 profiles over the last 14 days.

Tests three hypotheses about current early exits:
1. Higher RSI thresholds (60, 65 vs current 55-59)
2. Higher EMA20 gap or switch to EMA50
3. Switch to 1D timeframe for exits

Usage:
    python test_exit_indicators.py
    python test_exit_indicators.py --symbol SOL_USDC   # single symbol
    python test_exit_indicators.py --symbol SOL_USDC --show-trades
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.backtest_engine import BacktestEngine, BacktestProfile
from backtesting.profile_samples.dip_buy_exit_tests import DIP_BUY_EXIT_TESTS
from db.utils import get_db_session

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Test exit indicator variants for dip profiles")
    parser.add_argument("--symbol", type=str, default=None, help="Test single symbol only (default: all)")
    parser.add_argument("--show-trades", action="store_true", help="Print per-trade breakdown")
    parser.add_argument("--days", type=int, default=14, help="Lookback window in days (default 14)")
    args = parser.parse_args()

    # Use fixed end date based on available data (last candle is 2026-08-01)
    end = datetime(2026, 8, 1).date()
    start = end - timedelta(days=args.days)

    print(f"\n{'='*100}")
    print(f"DIP PROFILE EXIT INDICATOR TESTS")
    print(f"{'='*100}")
    print(f"Period: {start} → {end}")
    print()

    # Group variants by profile
    v5_variants = {k: v for k, v in DIP_BUY_EXIT_TESTS.items() if 'v5' in k}
    v7_variants = {k: v for k, v in DIP_BUY_EXIT_TESTS.items() if 'v7' in k}

    with get_db_session() as db:
        for profile_name, variants in [("V5 (RSI Reversal + Trail)", v5_variants), ("V7 (Deep Dip Satellite)", v7_variants)]:
            print(f"\n{profile_name}")
            print(f"{'-'*100}")
            print(f"{'Variant':<30} {'Symbols':>8} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} {'ProfFact':>9}")
            print(f"{'-'*100}")

            results = []
            for variant_key, config in variants.items():
                # Allow single-symbol test
                symbols = [args.symbol] if args.symbol else config.get("symbols", [])

                for symbol in symbols:
                    profile = BacktestProfile.from_dict(f"{config['display_name']}/{symbol}", config)
                    engine = BacktestEngine(db, profile, verbose=False)
                    result = engine.run(symbol=symbol, start=start, end=end)
                    results.append(result)

            # Sort by win rate, then total PnL
            results.sort(key=lambda r: (r.win_rate, r.total_pnl_pct), reverse=True)

            for r in results:
                print(
                    f"{r.profile_name:<30} {1:>8} {r.total_trades:>7} "
                    f"{r.win_rate:>6.0%} {r.avg_pnl_pct:>7.2f}% {r.total_pnl_pct:>9.2f}% {r.profit_factor:>9.2f}x"
                )

            # Show trade breakdown if requested
            if args.show_trades:
                print(f"\n{'TRADE-BY-TRADE BREAKDOWN':^100}")
                for r in results:
                    if r.total_trades == 0:
                        print(f"\n{r.profile_name}: (no trades)")
                        continue
                    print(f"\n-- {r.profile_name} --")
                    print(r.trade_log())

    print(f"\n{'='*100}\n")


if __name__ == "__main__":
    main()
