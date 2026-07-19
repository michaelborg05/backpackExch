"""Fetch candles from Binance, compute indicators locally, write to the shadow table.

Two modes:

  BACKFILL — pull history for one or more symbols. This is what unblocks
  backtesting new symbols immediately instead of waiting weeks for TradingView
  alerts to accumulate data.

      python Tools/run_candle_fetcher.py backfill --days 365
      python Tools/run_candle_fetcher.py backfill --symbols SUI_USDC DOGE_USDC --days 720

  LIVE — append recent bars. Run on a schedule (cron / the monitoring loop)
  alongside the TradingView webhooks during the parallel-run period.

      python Tools/run_candle_fetcher.py live
      python Tools/run_candle_fetcher.py live --lookback-hours 6

Nothing here writes to trend_analysis_log — the live signal path is untouched.
"""
import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.utils import get_db_session
from services.candle_fetcher import SYMBOL_MAP, fetch_and_store

DEFAULT_SYMBOLS = ["SOL_USDC", "ETH_USDC", "BTC_USDC", 
                   "BNB_USDC", "XRP_USDC", "ZEC_USDC"]
DEFAULT_TFS = ["15", "60"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["backfill", "live"])
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS,
                    help=f"default: the 7 live symbols. Known: {', '.join(sorted(SYMBOL_MAP))}")
    ap.add_argument("--timeframes", nargs="+", default=DEFAULT_TFS)
    ap.add_argument("--days", type=int, default=365, help="backfill window")
    ap.add_argument("--lookback-hours", type=int, default=6, help="live window")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    unknown = [s for s in args.symbols if s not in SYMBOL_MAP]
    if unknown:
        print(f"ERROR: no Binance mapping for {unknown}. Add them to "
              f"services/candle_fetcher.SYMBOL_MAP first.")
        return 1

    end = datetime.now(tz=timezone.utc)
    if args.mode == "backfill":
        start = end - timedelta(days=args.days)
        is_backfill = True
    else:
        start = end - timedelta(hours=args.lookback_hours)
        is_backfill = False

    print(f"{args.mode.upper()}  {start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} UTC")
    print(f"symbols={len(args.symbols)} timeframes={args.timeframes}\n")

    gapped, failed, total = [], [], 0
    with get_db_session() as db:
        for sym in args.symbols:
            for tf in args.timeframes:
                try:
                    rep = fetch_and_store(db, sym, tf, start, end, is_backfill=is_backfill)
                    total += rep.returned
                    flag = "" if rep.contiguous else "   <-- GAPS"
                    print(f"  {rep.describe()}{flag}")
                    if not rep.contiguous:
                        gapped.append(rep)
                except Exception as e:  # noqa: BLE001 — report and continue
                    print(f"  {sym}/{tf}: FAILED — {e}")
                    failed.append((sym, tf, str(e)))

    print(f"\n{total} rows written to trend_analysis_shadow")
    if gapped:
        print(f"\n{len(gapped)} series had gaps. Wilder recursions (RSI/ADX) drift across")
        print("gaps — re-run those before trusting their indicator values:")
        for r in gapped:
            for a, b, n in r.gaps[:3]:
                print(f"    {r.symbol}/{r.timeframe}: {n} bar(s) missing {a:%Y-%m-%d %H:%M} -> {b:%H:%M}")
    if failed:
        print(f"\n{len(failed)} series failed:")
        for s, tf, e in failed:
            print(f"    {s}/{tf}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
