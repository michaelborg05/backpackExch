"""
backtesting/run_prod_backtest.py
================================
Run live production profiles across the backtest dataset to compare
backtest results against actual prod performance.

Profiles and their symbols are defined entirely in prod_profiles.py.
To add/remove a profile, edit PROD_PROFILES there — no changes needed here.

Usage:
    python backtesting/run_prod_backtest.py --days 30
    python backtesting/run_prod_backtest.py --days 14 --symbol SOL_USDC
    python backtesting/run_prod_backtest.py --days 30 --trades --csv /tmp/prod_backtest.csv
    python backtesting/run_prod_backtest.py --days 30 --profile prod_mean_rev
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.profile_samples.prod_profiles import PROD_PROFILES
from backtesting.profile_variants import run_all_variants
from db.utils import get_db_session

parser = argparse.ArgumentParser(description="Run prod profile backtests")
parser.add_argument("--days",    type=int, default=14,
                    help="Lookback window in days (default: 14)")
parser.add_argument("--symbol",  default=None,
                    help="Single symbol override applied to all profiles, e.g. SOL_USDC")
parser.add_argument("--profile", default=None,
                    help="Run only one prod profile by name, e.g. prod_mean_rev")
parser.add_argument("--trades",  action="store_true", default=False,
                    help="Print per-trade breakdown under each profile")
parser.add_argument("--csv",     default="/home/michael/Downloads/prod_backtest.csv",
                    help="Export all trades to CSV (requires --trades)")
parser.add_argument("--verbose", action="store_true",
                    help="Per-candle debug output from the engine")
args = parser.parse_args()

end   = datetime.now(tz=timezone.utc)
start = end - timedelta(days=args.days)
print(f"Period: {start.strftime('%Y-%m-%d %H:%M')} -> {end.strftime('%Y-%m-%d %H:%M')} UTC ({args.days}d)")

# ---------------------------------------------------------------------------
# Profile selection
# ---------------------------------------------------------------------------
if args.profile:
    if args.profile not in PROD_PROFILES:
        print(f"ERROR: '{args.profile}' not found. Available: {list(PROD_PROFILES.keys())}")
        sys.exit(1)
    profiles_to_run = {args.profile: PROD_PROFILES[args.profile]}
else:
    profiles_to_run = PROD_PROFILES

symbols_override = [args.symbol] if args.symbol else None

# ---------------------------------------------------------------------------
# CSV setup
# ---------------------------------------------------------------------------
csv_path = None
if args.csv and args.trades:
    csv_path = args.csv.replace(".csv", "_prod.csv")
    if os.path.exists(csv_path):
        os.remove(csv_path)
        print(f"Deleted {csv_path}. Starting fresh.")

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
with get_db_session() as db:
    all_results_by_profile: dict = {}

    for profile_name, profile_config in profiles_to_run.items():
        symbols = symbols_override or profile_config.get("symbols", [])
        if not symbols:
            print(f"\nWARNING: no symbols configured for {profile_name}, skipping.")
            continue

        variant_set = {profile_name: profile_config}

        for symbol in symbols:
            print(f"\n{'='*60}")
            print(f"  {profile_name} -- {symbol}")
            print(f"{'='*60}")

            symbol_results = run_all_variants(
                db,
                symbol,
                start,
                end,
                variant_set=variant_set,
                verbose=args.verbose,
                show_trades=args.trades,
                export_csv=csv_path,
                price_source="ticks",
            )

            for r in symbol_results:
                if r.profile_name not in all_results_by_profile:
                    all_results_by_profile[r.profile_name] = r
                else:
                    all_results_by_profile[r.profile_name].trades.extend(r.trades)
                    all_results_by_profile[r.profile_name].signals_fired += r.signals_fired

    # -----------------------------------------------------------------------
    # Totals across all symbols
    # -----------------------------------------------------------------------
    if all_results_by_profile:
        merged = list(all_results_by_profile.values())
        merged.sort(key=lambda r: (r.win_rate, r.total_pnl_pct), reverse=True)

        print(f"\n\n{'='*80}")
        print(f"  PROD PROFILES — TOTALS ACROSS ALL SYMBOLS")
        print(f"{'='*80}")
        print(f"{'Profile':<30} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} {'ProfFact':>9}")
        print("-" * 80)
        for r in merged:
            print(
                f"{r.profile_name:<30} {r.total_trades:>7} {r.win_rate:>6.0%} "
                f"{r.avg_pnl_pct:>7.2f}% {r.total_pnl_pct:>9.2f}% {r.profit_factor:>9.2f}x"
            )
