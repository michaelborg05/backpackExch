import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.profile_variants import RANGE_VARIANTS, MEAN_REV_VARIANTS, TREND_VARIANTS, SWING_VARIANTS, MEAN_REV_SHORT_VARIANTS, MEAN_REV_SHORT_EXPERIMENTS, TREND_SHORT_VARIANTS, FADE_SHORT_VARIANTS,run_all_variants
from backtesting.backtest_engine import ProfileOpenPositionCap, ConsecutiveSLBreaker
from backtesting.period import DAYS_HELP, parse_period, print_period
from db.utils import get_db_session

parser = argparse.ArgumentParser(description="Run profile variant backtests")
parser.add_argument("--days",    default="30-60",  #Can now give a range. 0-30, 60-90
                    help=DAYS_HELP)
parser.add_argument("--symbol",  default=None,
                    help="Single symbol override, e.g. SOL_USDC (default: all 4)")
parser.add_argument("--set",     default="trend", choices=["all", "range", "mr", "trend", "4hr_swing", "mr_short", "trend_short", "mrs_exp"],
                    help="Which variant set to run (default: all)")
parser.add_argument("--trades",  action="store_true", default=True,
                    help="Print per-trade breakdown table under each variant")
parser.add_argument("--csv",     default="/home/michael/Downloads/backtestresults.csv",
#parser.add_argument("--csv",     default="c:\\temp\\backtestresults.csv",
#parser.add_argument("--csv",     default="",
                    help="Export all trades to CSV. Filename is auto-suffixed per set/symbol.")
parser.add_argument("--verbose", action="store_true",
                    help="Per-candle debug output from the engine")
parser.add_argument("--profile", default=None,
                    help="Run only this variant, e.g. p3_v4_ema50drop")
parser.add_argument("--data-source", default="log", choices=["log", "shadow"],
                    help="Candle source. 'log' = trend_analysis_log (TradingView webhooks, "
                         "~60d of history). 'shadow' = trend_analysis_shadow (programmatically "
                         "fetched candles, years of history). Default: log")
parser.add_argument("--shadow-source", default=None,
                    help="Which shadow feed to read, e.g. binance:USDT. Default: whichever "
                         "source has the most rows for the symbol. Only used with "
                         "--data-source shadow.")
parser.add_argument("--tick-source", default="webhook", choices=["webhook", "path1m"],
                    help="Where intra-candle price path comes from in tick mode. "
                         "'webhook' = webhook_price_ticks (~2min sample, ~60d history). "
                         "'path1m' = price_path_shadow 1m OHLC expanded to O/H/L/C "
                         "(60 points per 15m bar, full history).")
parser.add_argument("--price-source", default="ticks", choices=["ticks", "candle"],
                    help="Fill model. 'ticks' needs webhook_price_ticks coverage and falls "
                         "back to candle automatically when the window is not covered "
                         "(which is normal for long shadow backtests).")
args = parser.parse_args()

start, end, period_label = parse_period(args.days)
print_period(start, end, period_label)
print(f"Candle source: {args.data_source}"
      + (f" ({args.shadow_source})" if args.shadow_source else "")
      + f"   |   fill model: {args.price_source}")

VARIANT_SETS = {
    "range": (RANGE_VARIANTS,    ["SOL_USDC", "BTC_USDC","ZEC_USDC","BNB_USDC","XRP_USDC","ETH_USDC"]),
    "mr":    (MEAN_REV_VARIANTS,  ["SOL_USDC", "ETH_USDC", "BTC_USDC","ZEC_USDC","XRP_USDC","BNB_USDC"]),
    "trend": (TREND_VARIANTS,  ["SOL_USDC", "ETH_USDC", "BTC_USDC","BNB_USDC","XRP_USDC","ZEC_USDC"]),
    "4hr_swing": (SWING_VARIANTS, ["SOL_USDC", "ETH_USDC", "BTC_USDC","XRP_USDC","BNB_USDC","ZEC_USDC"]),
    "mr_short":    (MEAN_REV_SHORT_VARIANTS,    ["SOL_USDC", "ETH_USDC", "BTC_USDC","XRP_USDC","ZEC_USDC"]),
    "mrs_exp":     (MEAN_REV_SHORT_EXPERIMENTS,["SOL_USDC", "ETH_USDC", "BTC_USDC","XRP_USDC","ZEC_USDC"]),
    "trend_short": (TREND_SHORT_VARIANTS,      ["ETH_USDC", "XRP_USDC", "ZEC_USDC"]),
    "fade_short":  (FADE_SHORT_VARIANTS,      ["SOL_USDC", "ETH_USDC", "BTC_USDC","XRP_USDC","ZEC_USDC"]),

}
sets_to_run = list(VARIANT_SETS.items()) if args.set == "all" else [(args.set, VARIANT_SETS[args.set])]

# Filter to a single profile variant if requested
if args.profile:
    filtered = []
    for set_name, (variants, syms) in sets_to_run:
        if args.profile in variants:
            filtered.append((set_name, ({args.profile: variants[args.profile]}, syms)))
    if not filtered:
        all_names = [n for _, (v, _) in sets_to_run for n in v]
        print(f"ERROR: profile '{args.profile}' not found in set '{args.set}'. Available: {all_names}")
        sys.exit(1)
    sets_to_run = filtered

symbols_override = [args.symbol] if args.symbol else None

csv_path = None
if args.csv and args.trades:
    base     = args.csv.replace(".csv", "")
    csv_path = f"{base}_{args.set}_{period_label}.csv"
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
        elif set_name == "mrs_exp":
            label   = "MR SHORT EXPERIMENTS"
        elif set_name == "trend_short":
            label   = "TREND FOLLOWING SHORT"
        elif set_name == "trend_short":
            label   = "TREND FOLLOWING SHORT"
        elif set_name == "fade_short":
            label   = "FADE SHORT"

        # Build per-variant profile caps once, shared across all symbol runs for this set.
        # Each cap accumulates open positions across symbols so the limit is enforced
        # globally for the profile (e.g. SOL and ETH share the same open-position budget).
        profile_caps = {}
        for name, config in variants.items():
            max_open_per_profile = config.get("max_open_positions_per_profile")
            if max_open_per_profile:
                profile_caps[name] = ProfileOpenPositionCap(max_open_per_profile)

        # Per-variant consecutive-SL breakers, shared across symbol runs so the
        # pause after N straight stop losses spans all symbols (like the live CB).
        sl_breakers = {}
        for name, config in variants.items():
            max_consec_sl = config.get("max_consecutive_stop_losses")
            if max_consec_sl:
                sl_breakers[name] = ConsecutiveSLBreaker(
                    int(max_consec_sl),
                    float(config.get("consecutive_sl_lock_hours", 24) or 24),
                )

        # Warn about profile-level symbols that won't be visited (not in default set)
        default_symbols_set = set(symbols)
        for name, config in variants.items():
            prof_syms = config.get("symbols")
            if prof_syms:
                for s in prof_syms:
                    if s not in default_symbols_set:
                        print(f"  WARNING: '{name}' lists symbol '{s}' which is not in the default set for '{set_name}' — skipped")

        for symbol in symbols:

            # Filter to variants that have no symbol restriction, or explicitly include this symbol
            active_variants = {
                name: config for name, config in variants.items()
                if not config.get("symbols") or symbol in config["symbols"]
            }
            if not active_variants:
                continue

            print(f"\n{'='*60}")
            print(f"  {label} -- {symbol}")
            print(f"{'='*60}")

            symbol_results = run_all_variants(
                db,
                symbol,
                start,
                end,
                variant_set=active_variants,
                verbose=args.verbose,
                show_trades=args.trades,
                export_csv=csv_path,
                price_source=args.price_source,
                profile_caps=profile_caps,
                sl_breakers=sl_breakers,
                data_source=args.data_source,
                shadow_source=args.shadow_source,
                tick_source=args.tick_source,
            )

            for r in symbol_results:
                if r.profile_name not in all_results_by_variant:
                    all_results_by_variant[r.profile_name] = r
                else:
                    all_results_by_variant[r.profile_name].trades.extend(r.trades)
                    all_results_by_variant[r.profile_name].signals_fired += r.signals_fired
                    all_results_by_variant[r.profile_name].profile_cap_blocked += r.profile_cap_blocked

    if all_results_by_variant:
        merged = list(all_results_by_variant.values())
        merged.sort(key=lambda r: r.profit_factor, reverse=True)

        print(f"\n\n{'='*80}")
        print(f"  TOTALS ACROSS ALL SYMBOLS  - {period_label}")
        print(f"{'='*80}")
        print(f"{'Variant':<35} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} {'ProfFact':>9}")
        print("-" * 80)
        for r in merged:
            print(
                f"{r.profile_name:<35} {r.total_trades:>7} {r.win_rate:>6.0%} "
                f"{r.avg_pnl_pct:>7.2f}% {r.total_pnl_pct:>9.2f}% {r.profit_factor:>9.2f}x"
            )