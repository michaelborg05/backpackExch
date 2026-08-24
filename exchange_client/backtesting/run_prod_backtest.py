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
    python backtesting/run_prod_backtest.py --days 30-60   # non-overlapping older window
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.profile_samples.prod_profiles import PROD_PROFILES as _PROD_PROFILES_LIST
from backtesting.profile_variants import run_all_variants
from backtesting.backtest_engine import ConsecutiveSLBreaker, ProfileOpenPositionCap
from backtesting.period import DAYS_HELP, parse_period, print_period

PROD_PROFILES = {c["display_name"]: c for c in _PROD_PROFILES_LIST}
from db.utils import get_db_session

parser = argparse.ArgumentParser(description="Run prod profile backtests")
parser.add_argument("--days",    default="14",
                    help=DAYS_HELP)
parser.add_argument("--symbol",  default=None,
                    help="Single symbol override applied to all profiles, e.g. SOL_USDC")
parser.add_argument("--symbols", nargs="+", default=None,
                    help="Multi-symbol override applied to all profiles. Use EXPANDED for "
                         "the 14 symbols added 2026-08-22 (true out-of-sample — no profile "
                         "was ever fitted to them), or ALL for those plus the original 9.")
parser.add_argument("--profile", default=None,
                    help="Run only one prod profile by name, e.g. prod_mean_rev")
parser.add_argument("--trades",  action="store_true", default=True,
                    help="Print per-trade breakdown under each profile")
parser.add_argument("--csv",     default="/home/michael/Downloads/prod_backtest.csv",
                    help="Export all trades to CSV (requires --trades)")
parser.add_argument("--verbose", action="store_true",
                    help="Per-candle debug output from the engine")
parser.add_argument("--data-source", default="shadow", choices=["log", "shadow"],
                    help="Candle source. Both values now read trend_analysis_log — kept as "
                         "synonyms for back-compat with pre-cutover scripts, when 'log' was "
                         "TradingView webhook data and 'shadow' was the fetched-candle table. "
                         "Default: shadow")
parser.add_argument("--shadow-source", default=None,
                    help="Which provenance source to read, e.g. binance:USDT. Default: "
                         "whichever source has the most rows for the symbol.")
parser.add_argument("--tick-source", default="path1m", choices=["path1m"],
                    help="Accepted for back-compat with existing scripts; price_path_shadow "
                         "(1m OHLC expanded to O/H/L/C, full history, consistent across all "
                         "symbols) is now the only intra-candle path source. The old "
                         "'webhook' sample was dropped 2026-08.")
parser.add_argument("--allow-candle-fallback", action="store_true",
                    help="Accept candle fills when the requested tick source can't cover the "
                         "window. Off by default: a silent fallback changes the fill model "
                         "(stops fill at the exact stop price with no intra-bar path) and makes "
                         "the run answer a different question than the one asked.")
args = parser.parse_args()

start, end, period_label = parse_period(args.days)
print_period(start, end, period_label)
print(f"Candle source: {args.data_source}"
      + (f" ({args.shadow_source})" if args.shadow_source else "")
      + f"   |   tick source: {args.tick_source}")

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

ORIGINAL_9 = ["SOL_USDC", "ZEC_USDC", "BTC_USDC", "ETH_USDC", "BNB_USDC",
              "SUI_USDC", "DOGE_USDC", "SEI_USDC", "XRP_USDC"]
EXPANDED_14 = ["TRX_USDC", "LINK_USDC", "UNI_USDC", "LDO_USDC", "SHIB_USDC",
               "AAVE_USDC", "RAY_USDC", "PEPE_USDC", "WLD_USDC", "JTO_USDC",
               "BONK_USDC", "PYTH_USDC", "STRK_USDC", "W_USDC"]

if args.symbols:
    if args.symbols == ["EXPANDED"]:
        symbols_override = EXPANDED_14
    elif args.symbols == ["ALL"]:
        symbols_override = ORIGINAL_9 + EXPANDED_14
    else:
        symbols_override = args.symbols
elif args.symbol:
    symbols_override = [args.symbol]
else:
    symbols_override = None

# ---------------------------------------------------------------------------
# CSV setup
# ---------------------------------------------------------------------------
csv_path = None
if args.csv and args.trades:
    csv_path = args.csv.replace(".csv", f"_prod_{period_label}.csv")
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

        # One shared open-position cap per profile so the limit applies across
        # symbols. Without this, each symbol run gets a local cap that can
        # never bind (the engine holds at most one position per symbol).
        profile_caps = {}
        max_open_per_profile = profile_config.get("max_open_positions_per_profile")
        if max_open_per_profile:
            profile_caps[profile_name] = ProfileOpenPositionCap(int(max_open_per_profile))

        # One shared consecutive-SL breaker per profile so the pause after
        # N straight stop losses spans all symbols (mirrors the live CB).
        sl_breakers = {}
        max_consec_sl = profile_config.get("max_consecutive_stop_losses")
        if max_consec_sl:
            sl_breakers[profile_name] = ConsecutiveSLBreaker(
                int(max_consec_sl),
                float(profile_config.get("consecutive_sl_lock_hours", 24) or 24),
            )

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
                profile_caps=profile_caps,
                sl_breakers=sl_breakers,
                data_source=args.data_source,
                shadow_source=args.shadow_source,
                on_missing_ticks="fallback" if args.allow_candle_fallback else "error",
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
        print(f"  PROD PROFILES — TOTALS ACROSS ALL SYMBOLS - {period_label}")
        print(f"{'='*80}")
        print(f"{'Profile':<30} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} {'ProfFact':>9}")
        print("-" * 80)
        for r in merged:
            print(
                f"{r.profile_name:<30} {r.total_trades:>7} {r.win_rate:>6.0%} "
                f"{r.avg_pnl_pct:>7.2f}% {r.total_pnl_pct:>9.2f}% {r.profit_factor:>9.2f}x"
            )
