"""
backtesting/optimizers/swing_exit_optimizer.py
================================================
Grid search over TSL / SL / TP exit parameters for the p3_v7 and p3_v8
swing profiles. Indicators are locked to the production configs; only
the exit mechanics are varied.

Current production values (v7 & v8):
  trailing_stop_pct     = 1.2   (Claude suggestion: tighten to 0.8)
  arm_trailing_stop_pct = 1.5
  stop_loss_pct         = 2.0
  take_profit_pct       = 3.0

Usage:
  cd exchange_client
  python backtesting/optimizers/swing_exit_optimizer.py
  python backtesting/optimizers/swing_exit_optimizer.py --days 90
  python backtesting/optimizers/swing_exit_optimizer.py --profile v7   # only v7
  python backtesting/optimizers/swing_exit_optimizer.py --profile v8   # only v8
  python backtesting/optimizers/swing_exit_optimizer.py --no-fixed     # skip fixed TP variants
"""

import argparse
import copy
import csv
import itertools
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.backtest_engine import BacktestEngine, BacktestProfile, BacktestResult
from backtesting.profile_samples.swing_variants import SWING_VARIANTS
from db.utils import get_db_session

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYMBOLS   = ["SOL_USDC", "ETH_USDC", "BTC_USDC", "XRP_USDC", "BNB_USDC", "ZEC_USDC"]
SCAN_DAYS = 60
MIN_TRADES = 5   # swing fires less often — lower bar

CSV_PATH = "/home/michael/Downloads/swing_exit_optimizer.csv"

# ---------------------------------------------------------------------------
# Exit parameter grids
# ---------------------------------------------------------------------------
# TSL variants: 7 × 5 × 3 × 3 = 315 combos
# arm_trailing_stop_pct is the profit % at which TSL activates.
# trailing_stop_pct is how far the stop trails below the highest peak.
# Note: arm < trailing means the stop can still exit at a small loss (intentional).
TRAILING_GRID: Dict[str, List[Any]] = {
    "trailing_stop_pct":     [0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5],
    "arm_trailing_stop_pct": [0.8, 1.0, 1.2, 1.5, 2.0],
    "stop_loss_pct":         [1.5, 2.0, 2.5],
    "take_profit_pct":       [2.5, 3.0, 3.5],
}

# Fixed TP (no trailing stop): 3 × 4 = 12 combos
FIXED_GRID: Dict[str, List[Any]] = {
    "use_trailing_stop": [False],
    "stop_loss_pct":     [1.5, 2.0, 2.5],
    "take_profit_pct":   [2.5, 3.0, 3.5, 4.0],
}

# ---------------------------------------------------------------------------
# Base configs: lock indicators, strip exit params (will be overridden by grid)
# ---------------------------------------------------------------------------

_EXIT_KEYS = {"trailing_stop_pct", "arm_trailing_stop_pct", "stop_loss_pct",
              "take_profit_pct", "use_trailing_stop"}


def _base_for(variant_name: str) -> dict:
    """Return the swing variant config with all exit params removed (grid will supply them)."""
    cfg = copy.deepcopy(SWING_VARIANTS[variant_name])
    for k in _EXIT_KEYS:
        cfg.pop(k, None)
    return cfg


V7_BASE = _base_for("p3_v7_rsi_pullback")
V8_BASE = _base_for("p3_v8_vol_pullback")

PROFILES = {
    "v7": V7_BASE,
    "v8": V8_BASE,
}

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score(result: BacktestResult) -> float:
    """
    Composite score matching swing_indicator_search.py (avg_pnl-weighted).
    Heavily weights avg_pnl since swing has fewer trades and each must count.
    """
    if result.total_trades < MIN_TRADES:
        return -999.0
    pf  = min(result.profit_factor, 6.0)
    wr  = result.win_rate
    pnl = result.total_pnl_pct
    avg = result.avg_pnl_pct
    return avg * 200 + pf * 0.35 + wr * 100 * 0.30 + min(pnl, 40.0) * 0.08


# ---------------------------------------------------------------------------
# Grid runner
# ---------------------------------------------------------------------------

def run_grid(
    db,
    profile_label: str,
    base_config: dict,
    param_grid: Dict[str, List[Any]],
    symbols: List[str],
    start: datetime,
    end: datetime,
    extra_overrides: dict = None,
) -> List[BacktestResult]:
    """
    Run every combination in param_grid over all symbols.
    Returns merged (multi-symbol) BacktestResult objects, one per combo.
    """
    keys   = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))
    total  = len(combos) * len(symbols)
    done   = 0

    print(f"\n[{profile_label}] {len(combos)} combos × {len(symbols)} symbols = {total} backtests")

    combo_results: Dict[int, List[BacktestResult]] = defaultdict(list)

    for ci, combo in enumerate(combos):
        overrides = dict(zip(keys, combo))
        if extra_overrides:
            overrides = {**extra_overrides, **overrides}
        cfg = {**base_config, **overrides}

        # Readable name: e.g. v7_trl0.8_arm1.0_sl2.0_tp3.0
        tag = "_".join(f"{k[:3]}{v}" for k, v in overrides.items())
        combo_name = f"{profile_label}_{tag}"

        for sym in symbols:
            profile = BacktestProfile.from_dict(combo_name, cfg)
            engine  = BacktestEngine(db, profile)
            r       = engine.run(symbol=sym, start=start, end=end, price_source="ticks")
            r.profile_params = {**overrides, "profile": profile_label}
            combo_results[ci].append(r)
            done += 1

        if done % max(1, total // 20) == 0 or done == total:
            pct = done / total * 100
            print(f"  {done}/{total} ({pct:.0f}%) ...", flush=True)

    # Merge per-symbol results into one per combo
    merged_list: List[BacktestResult] = []
    for ci, sym_results in combo_results.items():
        merged = _merge(sym_results, sym_results[0].profile_name)
        merged.profile_params = sym_results[0].profile_params
        merged_list.append(merged)

    return merged_list


def _merge(results: List[BacktestResult], name: str) -> BacktestResult:
    m = BacktestResult(profile_name=name, symbol="ALL",
                       start=results[0].start, end=results[0].end)
    for r in results:
        m.trades.extend(r.trades)
        m.signals_fired  += r.signals_fired
        m.regime_blocked += r.regime_blocked
        m.rows_processed += r.rows_processed
    return m


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_ranking(results: List[BacktestResult], title: str, top_n: int = 30):
    ranked = sorted(results, key=score, reverse=True)
    qualifying = [r for r in ranked if score(r) > -100]

    print(f"\n{'='*110}")
    print(f"  {title}")
    print(f"  {len(qualifying)} qualifying (≥{MIN_TRADES} trades) / {len(results)} total")
    print(f"{'='*110}")
    print(f"{'Rank':<5} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} "
          f"{'ProfFact':>9} {'Score':>8}  Params")
    print("-"*110)

    for rank, r in enumerate(qualifying[:top_n], 1):
        sc = score(r)
        params = r.profile_params or {}
        tsl   = params.get("trailing_stop_pct", "-")
        arm   = params.get("arm_trailing_stop_pct", "-")
        sl    = params.get("stop_loss_pct", "-")
        tp    = params.get("take_profit_pct", "-")
        use_t = params.get("use_trailing_stop", True)
        mode  = f"TSL={tsl} arm={arm}" if use_t else "fixed"
        print(
            f"{rank:<5} {r.total_trades:>7} {r.win_rate:>6.1%} "
            f"{r.avg_pnl_pct:>7.2f}% {r.total_pnl_pct:>9.2f}% "
            f"{r.profit_factor:>9.2f}x {sc:>8.2f}  "
            f"SL={sl} TP={tp} {mode}"
        )

    if not qualifying:
        print(f"  (no combos reached {MIN_TRADES} trades — market may be slow, try --days 90)")
    print("="*110)
    return ranked


def export_csv(results: List[BacktestResult], path: str):
    if not results:
        return
    param_keys = sorted({k for r in results for k in (r.profile_params or {})})
    fields = (
        ["rank", "name", "trades", "signals", "win_rate", "avg_pnl",
         "total_pnl", "profit_factor", "score"]
        + param_keys
    )
    ranked = sorted(results, key=score, reverse=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for rank, r in enumerate(ranked, 1):
            row = {
                "rank":          rank,
                "name":          r.profile_name,
                "trades":        r.total_trades,
                "signals":       r.signals_fired,
                "win_rate":      round(r.win_rate, 4),
                "avg_pnl":       round(r.avg_pnl_pct, 4),
                "total_pnl":     round(r.total_pnl_pct, 4),
                "profit_factor": round(r.profit_factor, 4),
                "score":         round(score(r), 3),
            }
            row.update(r.profile_params or {})
            w.writerow(row)
    print(f"\n[CSV] Saved → {path}")


def print_snippet(r: BacktestResult, profile_label: str):
    """Print a ready-to-paste swing_variants.py config block for the winner."""
    p = r.profile_params or {}
    use_t = p.get("use_trailing_stop", True)
    tsl   = p.get("trailing_stop_pct", 1.2)
    arm   = p.get("arm_trailing_stop_pct", 1.5)
    sl    = p.get("stop_loss_pct", 2.0)
    tp    = p.get("take_profit_pct", 3.0)

    base_name = "p3_v7_rsi_pullback" if profile_label == "v7" else "p3_v8_vol_pullback"

    print(f'\n    # Score={score(r):.2f} | {r.total_trades}T | WR={r.win_rate:.0%} '
          f'| PF={r.profit_factor:.2f}x | AvgPnL={r.avg_pnl_pct:+.2f}%')
    print(f'    "{base_name}": {{')
    print(f'        **_SWING_BASE,  # ... (keep existing indicators)')
    print(f'        "take_profit_pct":       {tp},')
    print(f'        "stop_loss_pct":         {sl},')
    print(f'        "use_trailing_stop":     {use_t},')
    if use_t:
        print(f'        "trailing_stop_pct":     {tsl},')
        print(f'        "arm_trailing_stop_pct": {arm},')
    print(f'    }},')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Swing exit parameter optimizer (TSL/SL/TP grid)")
    parser.add_argument("--days",      type=int, default=SCAN_DAYS,
                        help=f"Lookback window in days (default {SCAN_DAYS})")
    parser.add_argument("--profile",   default="both", choices=["v7", "v8", "both"],
                        help="Which profile to optimize (default: both)")
    parser.add_argument("--symbols",   nargs="+", default=SYMBOLS,
                        help="Override symbol list")
    parser.add_argument("--no-fixed",  action="store_true",
                        help="Skip fixed TP/SL (no trailing stop) variants")
    parser.add_argument("--top-n",     type=int, default=20,
                        help="How many top results to display (default 20)")
    args = parser.parse_args()

    end   = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.days)

    profiles_to_run = (
        {"v7": V7_BASE, "v8": V8_BASE} if args.profile == "both"
        else {args.profile: PROFILES[args.profile]}
    )

    # Combo count summary
    trailing_combos = len(list(itertools.product(*TRAILING_GRID.values())))
    fixed_combos    = 0 if args.no_fixed else len(list(itertools.product(*[
        v for k, v in FIXED_GRID.items() if k != "use_trailing_stop"
    ])))
    total_combos = trailing_combos + fixed_combos
    total_backtests = total_combos * len(args.symbols) * len(profiles_to_run)

    print(f"\n{'#'*80}")
    print(f"  SWING EXIT OPTIMIZER — TSL / SL / TP Grid Search")
    print(f"  Window  : {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')} ({args.days}d)")
    print(f"  Symbols : {args.symbols}")
    print(f"  Profiles: {list(profiles_to_run.keys())}")
    print(f"  Grid    : {trailing_combos} trailing + {fixed_combos} fixed = {total_combos} combos")
    print(f"  Total   : {total_backtests} backtests")
    print(f"{'#'*80}")

    all_results: List[BacktestResult] = []

    with get_db_session() as db:
        for profile_label, base_cfg in profiles_to_run.items():
            label_trl = f"{profile_label} — TSL/SL/TP sweep"
            trl_results = run_grid(
                db, label_trl, base_cfg,
                TRAILING_GRID, args.symbols, start, end,
                extra_overrides={"use_trailing_stop": True},
            )
            all_results.extend(trl_results)

            if not args.no_fixed:
                label_fix = f"{profile_label} — fixed TP/SL (no trailing)"
                fix_results = run_grid(
                    db, label_fix, base_cfg,
                    {k: v for k, v in FIXED_GRID.items() if k != "use_trailing_stop"},
                    args.symbols, start, end,
                    extra_overrides={"use_trailing_stop": False},
                )
                all_results.extend(fix_results)

    # Per-profile ranking
    for profile_label in profiles_to_run:
        subset = [r for r in all_results if
                  (r.profile_params or {}).get("profile") == profile_label]
        if subset:
            print_ranking(subset, f"{profile_label.upper()} RESULTS ({args.days}d, all symbols)",
                          top_n=args.top_n)

    # Combined ranking (both profiles together)
    if len(profiles_to_run) > 1:
        print_ranking(all_results, f"COMBINED RESULTS (v7 + v8, {args.days}d)", top_n=args.top_n)

    export_csv(all_results, CSV_PATH)

    # Paste-ready snippets for best per profile
    print(f"\n\n{'='*80}")
    print(f"  RECOMMENDED CONFIGS (best per profile)")
    print(f"{'='*80}")
    for profile_label in profiles_to_run:
        subset = [r for r in all_results if
                  (r.profile_params or {}).get("profile") == profile_label]
        ranked = sorted(subset, key=score, reverse=True)
        qualifying = [r for r in ranked if score(r) > -100]
        if qualifying:
            print(f"\n--- {profile_label.upper()} winner ---")
            print_snippet(qualifying[0], profile_label)

    print("\nDone.")


if __name__ == "__main__":
    main()
