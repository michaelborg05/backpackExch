"""
backtesting/run_optimizer.py
============================
Multi-phase parameter optimizer for trend-following profiles.

Phase 1 (fast scan, 14 days):
  Grid-search TP / SL / trailing-stop params across all 7 symbols.
  Aggregate trades across symbols, then rank by composite score.

Phase 2 (60-day validation):
  Re-run top-N Phase-1 combos on a longer window to confirm they aren't
  just overfit to the recent 14-day window.

Usage:
  cd exchange_client
  python backtesting/run_optimizer.py
  python backtesting/run_optimizer.py --phase1-only
  python backtesting/run_optimizer.py --top-n 10 --p2-days 90
"""

import argparse
import copy
import itertools
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.backtest_engine import BacktestEngine, BacktestProfile, BacktestResult
from backtesting.profile_samples.trend_variants import _TF_BASE
from db.utils import get_db_session

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYMBOLS = ["SOL_USDC", "ETH_USDC", "BTC_USDC", "HYPE_USDC", "BNB_USDC", "XRP_USDC", "ZEC_USDC"]
P1_DAYS   = 14
P2_DAYS   = 60     # overridden by --p2-days
TOP_N     = 5      # overridden by --top-n
MIN_TRADES = 4     # ignore combos with fewer total trades across all symbols

CSV_PATH  = "/home/michael/Downloads/optimizer_p1.csv"
CSV_P2    = "/home/michael/Downloads/optimizer_p2.csv"

# ---------------------------------------------------------------------------
# Phase-1 grid  (TP / SL / trailing — highest impact on expectancy)
# ---------------------------------------------------------------------------
# 4 × 3 × 3 × 3 = 108 combos × 7 symbols = 756 backtests
PHASE1_GRID: Dict[str, List[Any]] = {
    "take_profit_pct":       [0.6,  0.8,  1.0,  1.2],
    "stop_loss_pct":         [0.4,  0.5,  0.6],
    "trailing_stop_pct":     [0.2,  0.3,  0.4],
    "arm_trailing_stop_pct": [0.3,  0.4,  0.5],
}

# Also test "no trailing stop" variants (fixed TP/SL only):
# 4 × 3 = 12 combos × 7 symbols = 84 extra backtests
PHASE1_FIXED_GRID: Dict[str, List[Any]] = {
    "use_trailing_stop": [False],
    "take_profit_pct":   [0.6, 0.8, 1.0, 1.2],
    "stop_loss_pct":     [0.4, 0.5, 0.6],
}

# ---------------------------------------------------------------------------
# Phase-2 grid  (filter / signal quality — run on top-N Phase-1 configs)
# ---------------------------------------------------------------------------
# 3 × 3 × 3 = 27 combos per base profile
PHASE2_GRID: Dict[str, List[Any]] = {
    "min_signal_confidence": [65.0, 70.0, 75.0],
    "min_volume_ratio":      [1.0,  1.1,  1.3],
    "max_position_hours":    [8,    12,   24],
}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score(result: BacktestResult) -> float:
    """
    Composite score used to rank combined (multi-symbol) results.

    Rewards:
      - High profit factor (capped at 5x to avoid infinite on zero-loss runs)
      - Win rate
      - Positive total PnL (small bonus)

    Penalises configs with too few trades (unreliable stats).
    """
    if result.total_trades < MIN_TRADES:
        return -999.0
    pf  = min(result.profit_factor, 5.0)
    wr  = result.win_rate
    pnl = result.total_pnl_pct
    return pf * 0.45 + wr * 100 * 0.40 + min(pnl, 20) * 0.15


def merge_results(results: List[BacktestResult], name: str) -> BacktestResult:
    """Combine per-symbol results for the same config into one aggregate result."""
    merged = BacktestResult(
        profile_name=name,
        symbol="ALL",
        start=results[0].start,
        end=results[0].end,
    )
    for r in results:
        merged.trades.extend(r.trades)
        merged.signals_fired  += r.signals_fired
        merged.regime_blocked += r.regime_blocked
        merged.rows_processed += r.rows_processed
    merged.profile_params = results[0].profile_params
    return merged


# ---------------------------------------------------------------------------
# Grid runner
# ---------------------------------------------------------------------------

def run_grid(
    db,
    base_config: dict,
    param_grid: Dict[str, List[Any]],
    symbols: List[str],
    start: datetime,
    end: datetime,
    label: str = "sweep",
) -> List[BacktestResult]:
    """
    Run every combination in param_grid over all symbols.
    Returns a list of merged (multi-symbol) BacktestResult objects, one per combo.
    """
    keys   = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))
    total  = len(combos) * len(symbols)
    done   = 0

    print(f"\n[{label}] {len(combos)} combos × {len(symbols)} symbols = {total} backtests")

    combo_results: Dict[int, List[BacktestResult]] = defaultdict(list)

    for ci, combo in enumerate(combos):
        overrides = dict(zip(keys, combo))
        cfg       = {**base_config, **overrides}
        combo_name = "combo_" + "_".join(f"{k[:4]}{v}" for k, v in overrides.items())

        for sym in symbols:
            profile = BacktestProfile.from_dict(combo_name, cfg)
            engine  = BacktestEngine(db, profile)
            r       = engine.run(symbol=sym, start=start, end=end)
            r.profile_params = overrides
            combo_results[ci].append(r)
            done += 1

        if done % max(1, total // 20) == 0:
            pct = done / total * 100
            print(f"  {done}/{total} ({pct:.0f}%) ...", flush=True)

    # Merge per-symbol results into one per combo
    merged_list: List[BacktestResult] = []
    for ci, sym_results in combo_results.items():
        combo_name = sym_results[0].profile_name
        merged     = merge_results(sym_results, combo_name)
        merged_list.append(merged)

    return merged_list


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_ranking(results: List[BacktestResult], title: str, top_n: int = 20):
    ranked = sorted(results, key=score, reverse=True)
    print(f"\n{'='*90}")
    print(f"  {title}")
    print(f"{'='*90}")
    print(f"{'Rank':<5} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} {'ProfFact':>9}  Params")
    print("-"*90)
    for rank, r in enumerate(ranked[:top_n], 1):
        sc = score(r)
        if sc < -100:
            print(f"  (remaining {len(ranked)-rank+1} combos had <{MIN_TRADES} trades)")
            break
        print(
            f"{rank:<5} {r.total_trades:>7} {r.win_rate:>6.1%} "
            f"{r.avg_pnl_pct:>7.2f}% {r.total_pnl_pct:>9.2f}% "
            f"{r.profit_factor:>9.2f}x  {r.profile_params}"
        )
    print("="*90)
    return ranked


def export_csv(results: List[BacktestResult], path: str):
    import csv, os
    if not results:
        return
    param_keys = sorted({k for r in results for k in (r.profile_params or {})})
    fields = (
        ["rank", "symbol", "trades", "signals", "win_rate", "avg_pnl",
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
                "symbol":        r.symbol,
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


def print_config_snippet(overrides: dict, base_config: dict):
    """Print a ready-to-paste TREND_VARIANTS entry for a winning config."""
    merged = {**base_config, **overrides}
    name_parts = "_".join(
        f"{k.replace('_pct','').replace('_','')[:5]}{v}"
        for k, v in overrides.items()
    )
    print(f'\n    "opt_{name_parts}": {{')
    for key, val in overrides.items():
        print(f'        "{key}": {repr(val)},')
    print("        **_TF_BASE,")
    print("    },")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Trend profile parameter optimizer")
    parser.add_argument("--phase1-only", action="store_true",
                        help="Stop after Phase 1 (no 60-day validation)")
    parser.add_argument("--top-n",   type=int, default=TOP_N,
                        help=f"Top-N Phase-1 configs to validate in Phase 2 (default {TOP_N})")
    parser.add_argument("--p2-days", type=int, default=P2_DAYS,
                        help=f"Lookback days for Phase-2 validation (default {P2_DAYS})")
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS,
                        help="Override symbol list")
    parser.add_argument("--no-fixed", action="store_true",
                        help="Skip the fixed-TP/SL (no trailing stop) sub-grid")
    args = parser.parse_args()

    end   = datetime.now(tz=timezone.utc)
    p1_start = end - timedelta(days=P1_DAYS)
    p2_start = end - timedelta(days=args.p2_days)

    print(f"Phase 1 window: {p1_start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')} ({P1_DAYS}d)")
    print(f"Phase 2 window: {p2_start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')} ({args.p2_days}d)")
    print(f"Symbols       : {args.symbols}")

    with get_db_session() as db:

        # ── Phase 1a: trailing-stop grid ──────────────────────────────────────
        p1a = run_grid(
            db, _TF_BASE, PHASE1_GRID, args.symbols,
            p1_start, end, label="Phase 1a — TP/SL/Trailing sweep"
        )

        # ── Phase 1b: fixed TP/SL (no trailing stop) ──────────────────────────
        if not args.no_fixed:
            p1b = run_grid(
                db, _TF_BASE, PHASE1_FIXED_GRID, args.symbols,
                p1_start, end, label="Phase 1b — Fixed TP/SL (no trailing)"
            )
            all_p1 = p1a + p1b
        else:
            all_p1 = p1a

        ranked_p1 = print_ranking(all_p1, "PHASE 1 RESULTS (14-day, all symbols combined)", top_n=30)
        export_csv(all_p1, CSV_PATH)

        if args.phase1_only:
            print("\n[--phase1-only] Stopping here.")
            return

        # ── Phase 2: validate top-N on 60 days ────────────────────────────────
        top_configs = [
            r for r in ranked_p1[:args.top_n * 3]   # take 3× buffer to skip low-trade combos
            if r.total_trades >= MIN_TRADES
        ][:args.top_n]

        if not top_configs:
            print("\n[Phase 2] No qualifying configs to validate. Reduce --top-n or MIN_TRADES.")
            return

        print(f"\n[Phase 2] Validating top {len(top_configs)} configs on {args.p2_days}-day window...")

        p2_results: List[BacktestResult] = []
        for r in top_configs:
            overrides = r.profile_params
            cfg       = {**_TF_BASE, **overrides}
            sym_results = []
            for sym in args.symbols:
                profile = BacktestProfile.from_dict(r.profile_name, cfg)
                engine  = BacktestEngine(db, profile)
                res     = engine.run(symbol=sym, start=p2_start, end=end)
                res.profile_params = overrides
                sym_results.append(res)
            merged = merge_results(sym_results, r.profile_name)
            p2_results.append(merged)

        ranked_p2 = print_ranking(
            p2_results, f"PHASE 2 RESULTS ({args.p2_days}-day validation, all symbols combined)",
            top_n=args.top_n
        )
        export_csv(p2_results, CSV_P2)

        # ── Phase 3 (bonus): filter sweep on best Phase-2 config ─────────────
        if ranked_p2:
            best = ranked_p2[0]
            print(f"\n[Phase 3] Signal-quality sweep on best config: {best.profile_params}")
            best_cfg = {**_TF_BASE, **best.profile_params}

            p3 = run_grid(
                db, best_cfg, PHASE2_GRID, args.symbols,
                p2_start, end, label="Phase 3 — Confidence/Volume/Hours sweep"
            )
            ranked_p3 = print_ranking(p3, "PHASE 3 — SIGNAL QUALITY SWEEP", top_n=15)

            # Print ready-to-paste variant snippets for top 3 final configs
            print("\n\n" + "="*70)
            print("  READY-TO-PASTE TREND_VARIANTS ENTRIES  (top 3 final configs)")
            print("="*70)
            final_top = [r for r in ranked_p3 if r.total_trades >= MIN_TRADES][:3]
            for r in final_top:
                print_config_snippet(r.profile_params, best.profile_params)

        print("\nDone.")


if __name__ == "__main__":
    main()
