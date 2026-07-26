"""Detect and repair bad rows in trend_analysis_log (Binance candle fetcher feed).

Table was trend_analysis_shadow until the 2026-07 cutover; renamed to
trend_analysis_log when it was promoted to be the primary feed.

Finds two classes of problem:

  1. PARTIAL BARS — a row written while its candle was still in progress. Its
     OHLC and volume are incomplete, which corrupts volume_ratio (a hard entry
     gate). These used to be permanent: the insert was ON CONFLICT DO NOTHING,
     so the correct values were never written once the bar closed. The insert
     is now DO UPDATE, so re-fetching repairs them — this tool finds which
     windows need it.

  2. GAPS — missing bars. RSI and ADX are Wilder recursions and drift for many
     bars after a gap, so a gap is not a local problem.

Detection samples the stored rows against a fresh fetch and compares close and
volume. Volume is the sensitive one: a partial bar's price may look plausible
while its volume is a fraction of the true value.

    python Tools/verify_shadow_data.py --days 30
    python Tools/verify_shadow_data.py --days 730 --sample 400
    python Tools/verify_shadow_data.py --days 30 --repair
"""
import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from db.utils import get_db_session
from services.candle_fetcher import (SYMBOL_BASES, TF_MINUTES, fetch_and_store,
                                     fetch_klines, get_quote)

# A bar is flagged when volume differs by more than this. Genuine float noise is
# ~0; a partial bar is typically off by tens of percent.
VOL_TOLERANCE_PCT = 1.0
PRICE_TOLERANCE_PCT = 0.05


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30, help="window to verify")
    ap.add_argument("--symbols", nargs="+", default=None)
    ap.add_argument("--timeframes", nargs="+", default=["15", "60", "240"])
    ap.add_argument("--sample", type=int, default=250,
                    help="bars to verify per window (0 = all in window)")
    ap.add_argument("--windows", type=int, default=1,
                    help="number of probe windows spread evenly across --days. "
                         "1 (default) checks only the most recent bars; use e.g. 10 "
                         "to actually verify the whole history rather than the tail.")
    ap.add_argument("--repair", action="store_true",
                    help="re-fetch affected windows (now safe: upsert is DO UPDATE)")
    args = ap.parse_args()

    quote = get_quote()
    source = f"binance:{quote}"
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    symbols = args.symbols or sorted(SYMBOL_BASES)

    print(f"Verifying source '{source}'  {start:%Y-%m-%d} -> {end:%Y-%m-%d}\n")

    problems = defaultdict(list)
    with get_db_session() as db:
        for sym in symbols:
            for tf in args.timeframes:
                tf_min = TF_MINUTES[tf]
                # Probe windows spread evenly across the range. Checking only the
                # tail would leave the bulk of the history unverified.
                span = (end - start) / max(args.windows, 1)
                checked = bad_vol = bad_px = unmatched = 0
                for w in range(max(args.windows, 1)):
                    w_hi = end - span * w
                    w_lo = w_hi - timedelta(minutes=tf_min * (args.sample or 500))
                    if w_lo < start:
                        w_lo = start
                    rows = db.execute(text("""
                        SELECT timestamp, close, volume FROM trend_analysis_log
                        WHERE symbol=:s AND timeframe=:t AND source=:src
                          AND timestamp BETWEEN :lo AND :hi
                        ORDER BY timestamp
                    """), {"s": sym, "t": tf, "src": source,
                           "lo": w_lo, "hi": w_hi}).fetchall()
                    if not rows:
                        continue
                    try:
                        candles, _ = fetch_klines(
                            sym, tf,
                            rows[0][0] - timedelta(minutes=tf_min * 2),
                            rows[-1][0] + timedelta(minutes=tf_min))
                    except Exception as e:  # noqa: BLE001
                        print(f"  {sym:<11} tf={tf:<4} window {w} fetch failed: {e}")
                        continue
                    # Row timestamp is the bar CLOSE; kline key is the bar OPEN.
                    fresh = {c.open_time + timedelta(minutes=tf_min): c for c in candles}
                    for ts, close, vol in rows:
                        c = fresh.get(ts)
                        if c is None:
                            unmatched += 1
                            continue
                        checked += 1
                        if c.volume and abs(float(vol) - c.volume) / c.volume * 100 > VOL_TOLERANCE_PCT:
                            bad_vol += 1
                            problems[(sym, tf)].append(ts)
                        elif c.close and abs(float(close) - c.close) / c.close * 100 > PRICE_TOLERANCE_PCT:
                            bad_px += 1
                            problems[(sym, tf)].append(ts)

                if not checked:
                    print(f"  {sym:<11} tf={tf:<4} no rows")
                    continue
                status = "ok" if not (bad_vol or bad_px) else "PARTIAL/STALE"
                extra = f"  unmatched={unmatched}" if unmatched else ""
                print(f"  {sym:<11} tf={tf:<4} checked={checked:>5}  "
                      f"bad_volume={bad_vol:<4} bad_price={bad_px:<4} {status}{extra}")

    print()
    if not problems:
        print("✅ No partial or stale bars found in the sampled window.")
        return 0

    total = sum(len(v) for v in problems.values())
    print(f"⚠️  {total} suspect bar(s) across {len(problems)} series:")
    for (sym, tf), times in sorted(problems.items()):
        span = f"{min(times):%Y-%m-%d %H:%M} -> {max(times):%Y-%m-%d %H:%M}"
        print(f"    {sym}/{tf}: {len(times)} bar(s)  {span}")

    if not args.repair:
        print("\nRe-run with --repair to re-fetch these windows "
              "(safe: the upsert now updates in place).")
        return 1

    print("\nRepairing...")
    with get_db_session() as db:
        for (sym, tf), times in sorted(problems.items()):
            tf_min = TF_MINUTES[tf]
            lo = min(times) - timedelta(minutes=tf_min * 2)
            hi = max(times) + timedelta(minutes=tf_min)
            try:
                rep = fetch_and_store(db, sym, tf, lo, hi)
                print(f"    {sym}/{tf}: rewrote {rep.written} row(s)")
            except Exception as e:  # noqa: BLE001
                print(f"    {sym}/{tf}: FAILED — {e}")
    print("\nRe-run without --repair to confirm.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
