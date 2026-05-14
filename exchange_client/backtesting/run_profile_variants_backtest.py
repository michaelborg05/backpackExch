import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.profile_variants import RANGE_VARIANTS, MEAN_REV_VARIANTS, TREND_VARIANTS,SWING_VARIANTS,MEAN_REV_SHORT_VARIANTS, run_all_variants
from db.utils import get_db_session

parser = argparse.ArgumentParser(description="Run profile variant backtests")
parser.add_argument("--days",    type=int, default= 14,
                    help="Lookback window in days (default: 7)")
parser.add_argument("--symbol",  default=None,
                    help="Single symbol override, e.g. SOL_USDC (default: all 4)")
parser.add_argument("--set",     default="mr_short", choices=["all", "range", "mr"],
                    help="Which variant set to run (default: all)")
parser.add_argument("--trades",  action="store_true", default=False,
                    help="Print per-trade breakdown table under each variant")
parser.add_argument("--csv",     default="/home/michael/Downloads/backtestresults.csv",
#parser.add_argument("--csv",     default="c:\\temp\\backtestresults.csv",
#parser.add_argument("--csv",     default="",
                    help="Export all trades to CSV. Filename is auto-suffixed per set/symbol.")
parser.add_argument("--verbose", action="store_true",
                    help="Per-candle debug output from the engine")
args = parser.parse_args()

end   = datetime.now(tz=timezone.utc)
start = end - timedelta(days=args.days)
print(f"Period: {start.strftime('%Y-%m-%d %H:%M')} -> {end.strftime('%Y-%m-%d %H:%M')} UTC ({args.days}d)")

VARIANT_SETS = {
    "range": (RANGE_VARIANTS,    ["SOL_USDC", "ETH_USDC", "BTC_USDC","HYPE_USDC","SUI_USDC","BNB_USDC"]),
    "mr":    (MEAN_REV_VARIANTS,  ["SOL_USDC", "ETH_USDC", "BTC_USDC","HYPE_USDC","SUI_USDC","BNB_USDC"]),
    "trend": (TREND_VARIANTS,  ["SOL_USDC", "ETH_USDC", "BTC_USDC","HYPE_USDC","BNB_USDC"]),
    "4hr_swing": (SWING_VARIANTS, ["SOL_USDC", "ETH_USDC", "BTC_USDC","HYPE_USDC","SUI_USDC","BNB_USDC"]),
    "mr_short":    (MEAN_REV_SHORT_VARIANTS,  ["SOL_USDC", "ETH_USDC", "BTC_USDC","BNB_USDC"]),

}
sets_to_run = list(VARIANT_SETS.items()) if args.set == "all" else [(args.set, VARIANT_SETS[args.set])]
symbols_override = [args.symbol] if args.symbol else None

csv_path = None
if args.csv and args.trades:
    base     = args.csv.replace(".csv", "")
    csv_path = f"{base}_{args.set}.csv"
    import os
    if os.path.exists(csv_path):
    #     choice = input(f"File '{csv_path}' already exists. Delete and restart? (y/n): ").lower()
        
    #     if choice == 'y':
        os.remove(csv_path)
        print(f"Deleted {csv_path}. Starting fresh.")
        # else:
        #     print(f"Continuing. Data will be appended to {csv_path}.")
with get_db_session() as db:
    all_results_by_variant: dict = {}  # variant_name -> merged BacktestResult

    for set_name, (variants, default_symbols) in sets_to_run:
        symbols = symbols_override or default_symbols

        if set_name == "range":
            label   = "RANGE TRADING"
        elif set_name == "mr":
            label   = "MEAN REVERSION"
        elif set_name == "mr_short":
            label   = "MEAN REVERSION SHORT"
        elif set_name == "trend":
            label   = "TREND FOLLOWING"
        elif set_name == "4hr_swing":
            label   = "4hr_swing"


        for symbol in symbols:

            print(f"\n{'='*60}")
            print(f"  {label} -- {symbol}")
            print(f"{'='*60}")

            symbol_results = run_all_variants(
                db,
                symbol,
                start,
                end,
                variant_set=variants,
                verbose=args.verbose,
                show_trades=args.trades,
                export_csv=csv_path,
            )

            for r in symbol_results:
                if r.profile_name not in all_results_by_variant:
                    all_results_by_variant[r.profile_name] = r
                else:
                    all_results_by_variant[r.profile_name].trades.extend(r.trades)
                    all_results_by_variant[r.profile_name].signals_fired += r.signals_fired

    if all_results_by_variant:
        merged = list(all_results_by_variant.values())
        merged.sort(key=lambda r: (r.win_rate, r.total_pnl_pct), reverse=True)

        print(f"\n\n{'='*80}")
        print(f"  TOTALS ACROSS ALL SYMBOLS")
        print(f"{'='*80}")
        print(f"{'Variant':<35} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} {'ProfFact':>9}")
        print("-" * 80)
        for r in merged:
            print(
                f"{r.profile_name:<35} {r.total_trades:>7} {r.win_rate:>6.0%} "
                f"{r.avg_pnl_pct:>7.2f}% {r.total_pnl_pct:>9.2f}% {r.profit_factor:>9.2f}x"
            )