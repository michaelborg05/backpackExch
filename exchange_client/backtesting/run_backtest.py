#!/usr/bin/env python3
"""
backtesting/run_backtest.py
============================
Entry point for running backtests and parameter sweeps.

Run from project root:
    python -m backtesting.run_backtest
    python -m backtesting.run_backtest --profile default --symbol SOL_USDC --sweep
    python -m backtesting.run_backtest --profile 15m_MB  --symbol BTC_USDC --days 7
"""

import argparse
import sys
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — adjust if your project layout differs
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_profiles_yaml(path: str = "trading_profiles.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def get_db_session():
    """Import your real DB session factory here."""
    from db.utils import get_db_session as _get
    return _get()


def run_single(args, profile_config: dict):
    from backtesting.backtest_engine import BacktestEngine, BacktestProfile

    profile = BacktestProfile.from_dict(args.profile, profile_config)

    end   = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.days)

    with get_db_session() as db:
        engine = BacktestEngine(db, profile, verbose=args.verbose)
        result = engine.run(symbol=args.symbol, start=start, end=end)

    print(result.summary())

    if args.trades:
        print("\nPer-trade log:")
        for i, t in enumerate(result.trades, 1):
            print(f"  [{i:>3}] {t.entry_time} | entry={t.entry_price:.4f} "
                  f"exit={t.exit_price if t.exit_price else 'OPEN':<10} "
                  f"pnl={t.pnl_pct:+.2f}% | {t.exit_reason}")


def run_sweep(args, profile_config: dict):
    from backtesting.backtest_engine import BacktestProfile, ParameterSweep

    profile = BacktestProfile.from_dict(args.profile, profile_config)

    end   = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.days)

    # -----------------------------------------------------------------------
    # EDIT THIS GRID TO SUIT YOUR EXPERIMENT
    # -----------------------------------------------------------------------
    param_grids = {
        # Confidence + volume threshold sweep (good starting point for any profile)
        "confidence_volume": {
            "min_signal_confidence": [60.0, 65.0, 70.0, 75.0, 80.0],
            "min_volume_ratio":      [0.8, 1.0, 1.1, 1.3, 1.5],
        },

        # Take-profit / stop-loss ratio sweep
        "tp_sl": {
            "take_profit_pct": [0.8, 1.0, 1.5, 2.0,2.5,3],
            "stop_loss_pct":   [0.7, 0.8, 1.0,1.5,2.5,3],
        },

        # Trailing stop sensitivity
        "trailing": {
            "arm_trailing_stop_pct":  [0.3, 0.5, 0.7, 1.0],
            "trailing_stop_pct":      [0.3, 0.5, 0.7, 1.0],
        },
    }

    grid = param_grids.get(args.sweep_grid, param_grids["confidence_volume"])
    print(f"[run_backtest] Sweep grid: '{args.sweep_grid}'\n{grid}\n")

    with get_db_session() as db:
        sweep   = ParameterSweep(db, profile, verbose=args.verbose)
        results = sweep.run(symbol=args.symbol, start=start, end=end, param_grid=grid)

    ParameterSweep.print_comparison(results, top_n=20)

    if args.csv:
        sweep_csv = f"backtest_{args.profile}_{args.symbol}_{args.sweep_grid}.csv"
        ParameterSweep.to_csv(results, sweep_csv)


def main():
    import sys
    parser = argparse.ArgumentParser(description="Run strategy backtests")
    parser.add_argument("--profile",    default="default",       help="Profile name from YAML")
    parser.add_argument("--symbol",     default="BTC_USDC",      help="Trading pair")
    parser.add_argument("--days",       type=int, default=7,     help="Lookback window in days")
    parser.add_argument("--yaml",       default="config/trading_profiles.yaml", help="Path to profiles YAML")
    parser.add_argument("--sweep",      action="store_true",     help="Run parameter sweep", default=False)
    parser.add_argument("--sweep-grid", default="tp_sl",
                        choices=["confidence_volume", "tp_sl", "trailing"],
                        help="Which parameter grid to sweep")
    parser.add_argument("--trades",     action="store_true",     help="Print per-trade log (single run only)", default=False)
    parser.add_argument("--verbose",    action="store_true",     help="Print per-candle debug")
    parser.add_argument("--csv",        action="store_true",     help="Export sweep results to CSV", default=False)
    args = parser.parse_args()

    yaml_data = load_profiles_yaml(args.yaml)
    profile_config = yaml_data["profiles"].get(args.profile)
    if not profile_config:
        print(f"ERROR: Profile '{args.profile}' not found in {args.yaml}")
        print(f"Available: {list(yaml_data['profiles'].keys())}")
        sys.exit(1)

    if args.sweep:
        run_sweep(args, profile_config)
    else:
        run_single(args, profile_config)


if __name__ == "__main__":
    main()