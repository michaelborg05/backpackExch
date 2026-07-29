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
from backtesting.profile_samples.mean_reversion_short_variants import MEAN_REV_SHORT_VARIANTS, MEAN_REV_SHORT_EXPERIMENTS
from backtesting.profile_samples.trend_short_variants import TREND_SHORT_VARIANTS
from backtesting.profile_samples.fade_short_variants import FADE_SHORT_VARIANTS
from backtesting.profile_samples.dip_buy_variants import DIP_BUY_VARIANTS
# =============================================================================
# Convenience: all variants in one dict
# =============================================================================
ALL_VARIANTS = {**RANGE_VARIANTS, **MEAN_REV_VARIANTS, **TREND_VARIANTS, **SWING_VARIANTS, **MEAN_REV_SHORT_VARIANTS, **TREND_SHORT_VARIANTS, **FADE_SHORT_VARIANTS, **DIP_BUY_VARIANTS}

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
    price_source: str = "candle",
    price_mode: str = "close",  # "auto" | "close" | "low" | "high" — engine.run()'s "auto"
                                # picks "low" for mean_reversion strategy_type, which won't
                                # match a profile validated with "close" (e.g. dip_buy's
                                # logical-level exit design)
    profile_caps: dict = None,  # variant_name -> ProfileOpenPositionCap; shared across symbol runs
    sl_breakers: dict = None,   # variant_name -> ConsecutiveSLBreaker; shared across symbol runs
    data_source: str = "log",   # "log"/"shadow" both read trend_analysis_log (kept as synonyms
                                # for back-compat with pre-cutover callers)
    shadow_source: str = None,  # e.g. "binance:USDT"; None = whichever source has most rows
    tick_source: str = "webhook",  # "webhook" | "path1m" (1m OHLC expanded to a path)
) -> list:
    """
    Run all variants and return sorted results.

    Args:
        show_trades:  print per-trade breakdown table under each variant
        export_csv:   filepath to write all trades across all variants as CSV
        profile_caps: pre-created ProfileOpenPositionCap objects keyed by variant name,
                      shared across symbol calls to enforce the cross-symbol open-position cap
        sl_breakers:  pre-created ConsecutiveSLBreaker objects keyed by variant name,
                      shared across symbol calls so the consecutive stop-loss pause
                      spans every symbol the profile trades (mirrors the live breaker)

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
        cap     = profile_caps.get(name) if profile_caps else None
        breaker = sl_breakers.get(name) if sl_breakers else None
        result  = engine.run(symbol=symbol, start=start, end=end, price_source=price_source,
                             price_mode=price_mode,
                             profile_cap=cap, sl_breaker=breaker,
                             data_source=data_source, shadow_source=shadow_source,
                             tick_source=tick_source)
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
            "exit_reason", "confidence", "volume_ratio",
            # Entry TF indicators at trigger
            "rsi", "ema20", "ema50", "adx", "vwap", "bb_pct_b",
            # Trend TF (HTF) indicators at trigger
            "htf_rsi", "htf_ema20", "htf_ema50", "htf_adx",
            # Entry TF indicators at close (for diagnosing what went wrong)
            "exit_rsi", "exit_ema20", "exit_ema50", "exit_adx", "exit_vwap", "exit_bb_pct_b",
            # Trend TF (HTF) indicators at close
            "exit_htf_rsi", "exit_htf_ema20", "exit_htf_ema50", "exit_htf_adx",
        ]

        file_exists = os.path.isfile(export_csv) and os.path.getsize(export_csv) > 0

        # Open with 'a' (append) instead of 'w' (write/overwrite)
        with open(export_csv, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)

            if not file_exists:
                writer.writeheader()

            for r in results:
                for i, t in enumerate(r.trades, 1):
                    d = t.entry_details
                    e = t.exit_details
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
                        "confidence":   d.get("confidence", ""),
                        "volume_ratio": d.get("volume_ratio", ""),
                        "rsi":          d.get("rsi", ""),
                        "ema20":        d.get("ema20", ""),
                        "ema50":        d.get("ema50", ""),
                        "adx":          d.get("adx", ""),
                        "vwap":         d.get("vwap", ""),
                        "bb_pct_b":     d.get("bb_pct_b", ""),
                        "htf_rsi":      d.get("htf_rsi", ""),
                        "htf_ema20":    d.get("htf_ema20", ""),
                        "htf_ema50":    d.get("htf_ema50", ""),
                        "htf_adx":      d.get("htf_adx", ""),
                        "exit_rsi":       e.get("rsi", ""),
                        "exit_ema20":     e.get("ema20", ""),
                        "exit_ema50":     e.get("ema50", ""),
                        "exit_adx":       e.get("adx", ""),
                        "exit_vwap":      e.get("vwap", ""),
                        "exit_bb_pct_b":  e.get("bb_pct_b", ""),
                        "exit_htf_rsi":   e.get("htf_rsi", ""),
                        "exit_htf_ema20": e.get("htf_ema20", ""),
                        "exit_htf_ema50": e.get("htf_ema50", ""),
                        "exit_htf_adx":   e.get("htf_adx", ""),
                    })
        print(f"\n[CSV] Trade log exported -> {export_csv}")
    return results



