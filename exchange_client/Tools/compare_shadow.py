"""Step 3 of the migration: diff the shadow feed against the live TradingView feed.

Run this after the fetcher has been running in parallel for a while. It answers
the only question that matters before cutover: would the new feed have produced
the same signals as the old one?

    python Tools/compare_shadow.py --days 7
    python Tools/compare_shadow.py --days 14 --symbols SOL_USDC BTC_USDC

Matching: TradingView rows are NOT on exact bar boundaries (the webhook fires a
few minutes after the close), so rows are paired to the nearest shadow bar
within a tolerance rather than joined on an exact timestamp.

Two classes of output:

  * INDICATOR DRIFT — median/p95 % difference per indicator. Small drift is
    expected (different venue's candles), it just has to be small.

  * GATE FLIPS — the number that actually decides cutover. For each threshold
    the live profiles gate on, how often do the two feeds disagree about which
    side of it we are on? A 0.02% indicator drift is irrelevant; a 5% gate flip
    rate means the profile behaves differently on the new feed.
"""
import argparse
import statistics as st
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from db.utils import get_db_session

# Thresholds the live trend profiles actually gate on — see
# backtesting/profile_samples/trend_variants.py
GATES = [
    ("adx",          [18, 22, 25, 28, 30]),
    ("rsi",          [38, 44, 55, 56, 60, 66, 68, 72]),
    ("volume_ratio", [1.1, 1.5]),
]

FIELDS = ["close", "rsi", "ema20", "ema50", "adx", "vwap",
          "bb_upper", "bb_lower", "bb_basis", "volume_ratio"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--symbols", nargs="+", default=None)
    ap.add_argument("--timeframe", default="15")
    ap.add_argument("--tolerance-min", type=int, default=8,
                    help="max minutes between a TV row and its shadow bar")
    ap.add_argument("--source", default=None,
                    help="shadow source to compare, e.g. binance:USDC. "
                         "Match this to whatever quote your TradingView feed uses — "
                         "comparing a USDT shadow against a USDC TV feed shows the "
                         "-0.057%% basis as drift and masks real differences. "
                         "Default: whichever source has the most rows.")
    args = ap.parse_args()

    with get_db_session() as db:
        source = args.source
        if not source:
            row = db.execute(text("""
                SELECT source, count(*) c FROM trend_analysis_shadow
                WHERE timestamp > now() - (:iv)::interval
                GROUP BY source ORDER BY c DESC LIMIT 1
            """), {"iv": f"{args.days} days"}).fetchone()
            source = row[0] if row else None
        if not source:
            print("No shadow data yet. Run: python Tools/run_candle_fetcher.py live")
            return 1
        print(f"Comparing trend_analysis_log against shadow source '{source}'\n")

        syms = args.symbols or [r[0] for r in db.execute(text("""
            SELECT DISTINCT symbol FROM trend_analysis_shadow
            WHERE timestamp > now() - (:iv)::interval AND source=:src ORDER BY symbol
        """), {"iv": f"{args.days} days", "src": source}).fetchall()]

        if not syms:
            print("No shadow data yet. Run: python Tools/run_candle_fetcher.py live")
            return 1

        cols = ", ".join(FIELDS)
        overall = defaultdict(list)
        gate_flips = defaultdict(lambda: [0, 0])

        for sym in syms:
            live = db.execute(text(f"""
                SELECT timestamp, {cols} FROM trend_analysis_log
                WHERE symbol=:s AND timeframe=:tf AND timestamp > now() - (:iv)::interval
                ORDER BY timestamp
            """), {"s": sym, "tf": args.timeframe, "iv": f"{args.days} days"}).fetchall()
            shadow = db.execute(text(f"""
                SELECT timestamp, {cols} FROM trend_analysis_shadow
                WHERE symbol=:s AND timeframe=:tf AND timestamp > now() - (:iv)::interval
                  AND source=:src
                ORDER BY timestamp
            """), {"s": sym, "tf": args.timeframe, "iv": f"{args.days} days",
                   "src": source}).fetchall()

            if not live or not shadow:
                print(f"\n{sym}: live={len(live)} shadow={len(shadow)} — skipping")
                continue

            shadow_times = [r[0] for r in shadow]
            tol = timedelta(minutes=args.tolerance_min)
            pairs = []
            j = 0
            for lrow in live:
                lt = lrow[0]
                while j + 1 < len(shadow_times) and abs(shadow_times[j + 1] - lt) < abs(shadow_times[j] - lt):
                    j += 1
                if abs(shadow_times[j] - lt) <= tol:
                    pairs.append((lrow, shadow[j]))

            print(f"\n{sym}  live={len(live)} shadow={len(shadow)} matched={len(pairs)}")
            if len(pairs) < 20:
                print("   too few matched bars to judge")
                continue

            for fi, field in enumerate(FIELDS, start=1):
                errs = []
                for lrow, srow in pairs:
                    a, b = lrow[fi], srow[fi]
                    if a is None or b is None or float(a) == 0:
                        continue
                    errs.append(abs(float(b) - float(a)) / abs(float(a)) * 100)
                if len(errs) < 20:
                    continue
                errs.sort()
                med, p95 = st.median(errs), errs[int(len(errs) * .95)]
                overall[field].extend(errs)
                mark = "ok" if med < 0.1 else ("check" if med < 0.5 else "DRIFT")
                print(f"    {field:<14} median {med:>7.4f}%  p95 {p95:>7.4f}%   {mark}")

            for field, thresholds in GATES:
                fi = FIELDS.index(field) + 1
                for thr in thresholds:
                    same = diff = 0
                    for lrow, srow in pairs:
                        a, b = lrow[fi], srow[fi]
                        if a is None or b is None:
                            continue
                        if (float(a) >= thr) == (float(b) >= thr):
                            same += 1
                        else:
                            diff += 1
                    if same + diff >= 20:
                        gate_flips[(field, thr)][0] += diff
                        gate_flips[(field, thr)][1] += same + diff

        print("\n" + "=" * 70)
        print("  AGGREGATE INDICATOR DRIFT")
        print("=" * 70)
        for field, errs in overall.items():
            errs.sort()
            print(f"  {field:<14} n={len(errs):>6}  median {st.median(errs):>7.4f}%  "
                  f"p95 {errs[int(len(errs)*.95)]:>7.4f}%")

        print("\n" + "=" * 70)
        print("  GATE FLIP RATE  — the cutover decision")
        print("=" * 70)
        print("  How often the two feeds disagree about which side of a live")
        print("  threshold we are on. Under ~1% is fine. Over ~5% means the")
        print("  profiles will behave differently and must be re-validated.\n")
        worst = 0.0
        for (field, thr), (diff, total) in sorted(gate_flips.items()):
            if not total:
                continue
            rate = diff / total * 100
            worst = max(worst, rate)
            mark = "ok" if rate < 1 else ("CHECK" if rate < 5 else "BLOCKER")
            print(f"  {field:<14} >= {thr:<6} flips {diff:>4}/{total:<6} = {rate:>5.2f}%   {mark}")

        print("\n" + "=" * 70)
        if not gate_flips or not overall:
            print("  VERDICT: NO COMPARISON MADE — no bars matched between the feeds.")
            print("           This is not a pass. Check that both feeds cover the")
            print("           requested window (a stalled TradingView webhook shows up")
            print("           here as live=0) and that --tolerance-min is wide enough.")
            print("=" * 70)
            return 2
        if worst < 1:
            print("  VERDICT: feeds agree. Safe to cut over.")
        elif worst < 5:
            print(f"  VERDICT: worst gate flip {worst:.2f}%. Re-run the variant set on")
            print("           shadow data and compare results before cutting over.")
        else:
            print(f"  VERDICT: worst gate flip {worst:.2f}% — DO NOT cut over yet.")
            print("           Investigate the drifting indicator above.")
        print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
