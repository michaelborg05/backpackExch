#!/usr/bin/env python3
"""
backtesting/run_backtest.py
============================
Run a single profile variant with optional parameter sweeps.

Pick a profile from one of the profile_samples files, then run it
with a TP/SL sweep (or single run) across one or more symbols.

Examples:
    # List available profiles in swing_variants
    python -m backtesting.run_backtest --file swing_variants --list

    # Single run: p3_base profile from swing_variants on SOL
    python -m backtesting.run_backtest --file swing_variants --profile p3_base --symbol SOL_USDC

    # TP/SL sweep across symbols
    python -m backtesting.run_backtest --file swing_variants --profile p3_base --sweep --sweep-grid tp_sl

    # Confidence/volume sweep, 14 days, export CSV
    python -m backtesting.run_backtest --file mr --profile mr_v1 --sweep --sweep-grid confidence_volume --days 14 --csv
"""

import argparse
import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Map --file shorthand -> (module path, dict name)
# ---------------------------------------------------------------------------
FILE_MAP = {
    "swing":    ("backtesting.profile_samples.swing_variants",                "SWING_VARIANTS"),
    "range":    ("backtesting.profile_samples.range_variants",                "RANGE_VARIANTS"),
    "mr":       ("backtesting.profile_samples.mean_reversion_variants",       "MEAN_REV_VARIANTS"),
    "mr_short": ("backtesting.profile_samples.mean_reversion_short_variants", "MEAN_REV_SHORT_VARIANTS"),
    "trend":    ("backtesting.profile_samples.trend_variants",                "TREND_VARIANTS"),
}

# Aliases so the full filename also works without extension
for _fname in list(FILE_MAP.keys()):
    FILE_MAP[f"{_fname}_variants"] = FILE_MAP[_fname]


def load_variant_dict(file_key: str) -> tuple[str, dict]:
    """Return (resolved_key, variants_dict) for a given --file value."""
    key = file_key.removesuffix(".py")
    if key not in FILE_MAP:
        print(f"ERROR: Unknown --file '{file_key}'")
        print(f"Available: {sorted(set(FILE_MAP.keys()))}")
        sys.exit(1)
    mod_path, dict_name = FILE_MAP[key]
    mod = importlib.import_module(mod_path)
    return key, getattr(mod, dict_name)


def get_db_session():
    from db.utils import get_db_session as _get
    return _get()


def run_single(args, profile_name: str, profile_config: dict):
    from backtesting.backtest_engine import BacktestEngine, BacktestProfile

    profile = BacktestProfile.from_dict(profile_name, profile_config)
    end   = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.days)

    symbols = [args.symbol] if args.symbol else ["BTC_USDC"]

    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"  {profile_name}  --  {symbol}")
        print(f"{'='*60}")
        with get_db_session() as db:
            engine = BacktestEngine(db, profile, verbose=args.verbose)
            result = engine.run(symbol=symbol, start=start, end=end)

        print(result.summary())

        if args.trades:
            print("\nPer-trade log:")
            for i, t in enumerate(result.trades, 1):
                exit_px = f"{t.exit_price:.4f}" if t.exit_price else "OPEN"
                print(f"  [{i:>3}] {t.entry_time} | entry={t.entry_price:.4f} "
                      f"exit={exit_px:<10} pnl={t.pnl_pct:+.2f}% | {t.exit_reason}")


def run_sweep(args, profile_name: str, profile_config: dict):
    from backtesting.backtest_engine import BacktestProfile, ParameterSweep

    profile = BacktestProfile.from_dict(profile_name, profile_config)
    end   = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.days)

    param_grids = {
        "tp_sl": {
            "take_profit_pct": [0.8, 1.0, 1.5, 2.0, 2.5, 3.0],
            "stop_loss_pct":   [0.7, 0.8, 1.0, 1.5, 2.5, 3.0],
        },
        "confidence_volume": {
            "min_signal_confidence": [60.0, 65.0, 70.0, 75.0, 80.0],
            "min_volume_ratio":      [0.8, 1.0, 1.1, 1.3, 1.5],
        },
        "trailing": {
            "arm_trailing_stop_pct": [0.3, 0.5, 0.7, 1.0],
            "trailing_stop_pct":     [0.3, 0.5, 0.7, 1.0],
        },
    }

    grid = param_grids[args.sweep_grid]
    symbols = [args.symbol] if args.symbol else ["BTC_USDC"]

    print(f"[run_backtest] Profile: {profile_name}  |  Sweep: '{args.sweep_grid}'")
    print(f"Grid: {grid}\n")

    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"  {profile_name}  --  {symbol}")
        print(f"{'='*60}")
        with get_db_session() as db:
            sweep   = ParameterSweep(db, profile, verbose=args.verbose)
            results = sweep.run(symbol=symbol, start=start, end=end, param_grid=grid)

        ParameterSweep.print_comparison(results, top_n=20)

        if args.csv:
            csv_path = f"backtest_{profile_name}_{symbol}_{args.sweep_grid}.csv"
            ParameterSweep.to_csv(results, csv_path)
            print(f"CSV saved: {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Run a single profile variant with optional TP/SL or confidence sweeps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--file",    required=False, default="swing",
                        help="Profile sample file (swing, range, mr, mr_short, trend)")
    parser.add_argument("--profile", default="p3_v19_tight_pullback",
                        help="Profile key within that file (use --list to see options)")
    parser.add_argument("--list",    action="store_true",
                        help="List available profile names in --file and exit")
    parser.add_argument("--symbol",  default="ETH_USDC",
                        help="Symbol override, e.g. SOL_USDC (default: BTC_USDC)")
    parser.add_argument("--days",    type=int, default=35,
                        help="Lookback window in days (default: 35)")
    parser.add_argument("--sweep",   action="store_true", default=True,
                        help="Run parameter sweep instead of single backtest")
    parser.add_argument("--sweep-grid", default="tp_sl",
                        choices=["tp_sl", "confidence_volume", "trailing"],
                        help="Which parameter grid to sweep (default: tp_sl)")
    parser.add_argument("--trades",  action="store_true", default=False,
                        help="Print per-trade log (single run only)")
    parser.add_argument("--verbose", action="store_true",
                        help="Per-candle debug output")
    parser.add_argument("--csv",     action="store_true",
                        help="Export sweep results to CSV")
    args = parser.parse_args()

    if not args.file:
        print("ERROR: --file is required.")
        print(f"Available files: {sorted(set(FILE_MAP.keys()))}")
        sys.exit(1)

    _, variants = load_variant_dict(args.file)

    if args.list:
        print(f"Profiles in '{args.file}':")
        for name in variants:
            print(f"  {name}")
        sys.exit(0)

    if not args.profile:
        print("ERROR: --profile is required (use --list to see options).")
        sys.exit(1)

    if args.profile not in variants:
        print(f"ERROR: Profile '{args.profile}' not found in '{args.file}'.")
        print(f"Available: {list(variants.keys())}")
        sys.exit(1)

    profile_config = variants[args.profile]

    end   = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.days)
    print(f"Period: {start.strftime('%Y-%m-%d %H:%M')} -> {end.strftime('%Y-%m-%d %H:%M')} UTC ({args.days}d)")

    if args.sweep:
        run_sweep(args, args.profile, profile_config)
    else:
        run_single(args, args.profile, profile_config)


if __name__ == "__main__":
    main()
