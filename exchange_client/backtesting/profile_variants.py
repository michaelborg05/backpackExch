"""
backtesting/profile_variants.py
=================================
Curated indicator configuration variants for backtesting.

Each variant set is grounded in what ACTUALLY went wrong in the two
losing trades (2026-02-23):

  TRADE 1 — range_trading (15m_MB): SOL $82.77 — stopped out 20min later
    Root cause: SOL was in a downtrend (60m RSI=33.2, EMA20 1.4% above price).
    The range_trading profile fired because the 15m bounced off the BB lower
    while price happened to be above VWAP — the HTF trend gate was too weak.

  TRADE 2 — mean_reversion (15m_MB_ATR): SUI 0.9249 — stopped out 5hrs later
    Root cause: Not a real oversold setup. BB pct_b=0.41 (middle of band),
    volume only 1.2x, EMA20 distance only -0.11%. The RSI bounce looked good
    but no other indicator confirmed true exhaustion/capitulation.

Variants are organised by profile and strategy type. Use with BacktestEngine:

    from backtesting.profile_variants import RANGE_VARIANTS, MEAN_REV_VARIANTS
    from backtesting.backtest_engine import BacktestProfile, BacktestEngine

    for name, config in RANGE_VARIANTS.items():
        profile = BacktestProfile.from_dict(name, config)
        result  = BacktestEngine(db, profile).run("SOL_USDC", start, end)
        print(f"{name}: {result.win_rate:.0%} win | {result.total_pnl_pct:+.1f}% PnL")
"""

from backtesting.profile_samples.swing_variants import SWING_VARIANTS
from backtesting.profile_samples.mean_reversion_variants import MEAN_REV_VARIANTS
from  backtesting.profile_samples.range_variants import RANGE_VARIANTS
from backtesting.profile_samples.trend_variants import TREND_VARIANTS

# =============================================================================
# Convenience: all variants in one dict
# =============================================================================
ALL_VARIANTS = {**RANGE_VARIANTS, **MEAN_REV_VARIANTS, **TREND_VARIANTS, **SWING_VARIANTS}

# =============================================================================
# Quick sweep runner — use this to run all variants in one go
# =============================================================================
def run_all_variants(
    db_session,
    symbol: str,
    start,
    end,
    variant_set: dict = None,
    verbose: bool = False,
    show_trades: bool = False,
    export_csv: str = None,
) -> list:
    """
    Run all variants and return sorted results.

    Args:
        show_trades: print per-trade breakdown table under each variant
        export_csv:  filepath to write all trades across all variants as CSV

    Example:
        results = run_all_variants(db, "SOL_USDC", start, end, RANGE_VARIANTS,
                                   show_trades=True, export_csv="trades.csv")
    """
    from backtesting.backtest_engine import BacktestEngine, BacktestProfile

    if variant_set is None:
        variant_set = ALL_VARIANTS

    results = []
    for name, config in variant_set.items():
        profile = BacktestProfile.from_dict(name, config)
        engine  = BacktestEngine(db_session, profile, verbose=verbose)
        result  = engine.run(symbol=symbol, start=start, end=end)
        results.append(result)

    results.sort(key=lambda r: (r.win_rate, r.total_pnl_pct), reverse=True)

    # ---- Summary table ----
    print(f"\n{'Variant':<35} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} {'ProfFact':>9}")
    print("-" * 80)
    for r in results:
        print(
            f"{r.profile_name:<35} {r.total_trades:>7} {r.win_rate:>6.0%} "
            f"{r.avg_pnl_pct:>7.2f}% {r.total_pnl_pct:>9.2f}% {r.profit_factor:>9.2f}x"
        )

    # ---- Per-trade breakdown ----
    if show_trades:
        print("\n" + "=" * 80)
        print("TRADE-BY-TRADE BREAKDOWN")
        print("=" * 80)
        for r in results:
            if r.total_trades == 0:
                print(f"\n{r.profile_name}: (no trades)")
                continue
            print(f"\n-- {r.profile_name} --")
            print(r.trade_log())

    # ---- CSV export ----

    if export_csv:
        import csv
        import os 

        fields = [
            "variant", "symbol", "trade_num", "outcome",
            "entry_time", "exit_time", "hold_minutes",
            "entry_price", "exit_price", "pnl_pct",
            "exit_reason", "confidence", "volume_ratio", "rsi_at_entry",
        ]
        
        file_exists = os.path.isfile(export_csv) and os.path.getsize(export_csv) > 0
        
        # Open with 'a' (append) instead of 'w' (write/overwrite)
        with open(export_csv, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            
            if not file_exists:
                writer.writeheader()
                
            for r in results:
                for i, t in enumerate(r.trades, 1):
                    writer.writerow({
                        "variant":      r.profile_name,
                        "symbol":       r.symbol,
                        "trade_num":    i,
                        "outcome":      "WIN" if t.won else ("OPEN" if t.exit_price is None else "LOSS"),
                        "entry_time":   t.entry_time.isoformat() if t.entry_time else "",
                        "exit_time":    t.exit_time.isoformat()  if t.exit_time  else "",
                        "hold_minutes": round(t.hold_minutes, 1) if t.hold_minutes else "",
                        "entry_price":  t.entry_price,
                        "exit_price":   t.exit_price or "",
                        "pnl_pct":      round(t.pnl_pct, 4),
                        "exit_reason":  t.exit_reason,
                        "confidence":   t.entry_details.get("confidence", ""),
                        "volume_ratio": t.entry_details.get("volume_ratio", ""),
                        "rsi_at_entry": t.entry_details.get("rsi", ""),
                    })
        print(f"\n[CSV] Trade log exported -> {export_csv}")
    return results



