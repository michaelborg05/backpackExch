"""Validate services/indicators.py against TradingView's stored values.

Run this after ANY change to services/indicators.py, and again after switching
candle sources. It compares each locally computed indicator against the TV value
already stored in trend_analysis_log for the same bar.

    python Tools/validate_indicators.py
    python Tools/validate_indicators.py --symbols SOL_USDC BTC_USDC --days 25

Thresholds: median abs error < 0.01% is a match. Anything above ~0.5% means the
implementation differs from TV and the profile thresholds will not transfer.
"""
import argparse
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from db.utils import get_db_session
from services import indicators as ind

PASS, CLOSE = 0.01, 0.5


def load(db, symbol, timeframe, days):
    rows = db.execute(text("""
        SELECT timestamp, open, high, low, close, volume,
               rsi, adx, vwap, ema20, ema50, bb_upper, bb_lower, bb_basis,
               volume_sma, volume_ratio
        FROM trend_analysis_log
        WHERE symbol=:s AND timeframe=:tf
          AND timestamp > now() - (:iv)::interval
          AND close IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL
        ORDER BY timestamp
    """), {"s": symbol, "tf": timeframe, "iv": f"{days} days"}).fetchall()
    seen, out = set(), []
    for r in rows:
        key = r[0].replace(second=0, microsecond=0)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def compare(label, local, stored, warmup, results):
    pairs = [(a, float(b)) for a, b in zip(local[warmup:], stored[warmup:])
             if a is not None and b is not None and float(b) != 0]
    if len(pairs) < 50:
        print(f"    {label:<26} SKIP (n={len(pairs)})")
        return
    errs = sorted(abs(a - b) / abs(b) * 100 for a, b in pairs)
    med = st.median(errs)
    p95 = errs[int(len(errs) * 0.95)]
    verdict = "PASS" if med < PASS else ("CLOSE" if med < CLOSE else "FAIL")
    results.append((label, med, verdict))
    print(f"    {label:<26} n={len(pairs):>5}  median {med:>8.4f}%  p95 {p95:>8.4f}%   {verdict}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+",
                    default=["SOL_USDC", "BTC_USDC", "ETH_USDC", "XRP_USDC"])
    ap.add_argument("--timeframe", default="15")
    ap.add_argument("--days", type=int, default=25)
    ap.add_argument("--warmup", type=int, default=150)
    args = ap.parse_args()

    results = []
    with get_db_session() as db:
        for sym in args.symbols:
            rows = load(db, sym, args.timeframe, args.days)
            if len(rows) < args.warmup + 100:
                print(f"\n{sym}: only {len(rows)} candles — skipping")
                continue
            times = [r[0] for r in rows]
            highs = [float(r[2]) for r in rows]
            lows = [float(r[3]) for r in rows]
            closes = [float(r[4]) for r in rows]
            vols = [float(r[5]) if r[5] is not None else None for r in rows]
            print(f"\n{sym}  ({len(rows)} candles, tf={args.timeframe})")

            compare("EMA20", ind.ema(closes, 20), [r[9] for r in rows], args.warmup, results)
            compare("EMA50", ind.ema(closes, 50), [r[10] for r in rows], args.warmup, results)
            compare("RSI14", ind.rsi(closes), [r[6] for r in rows], args.warmup, results)
            compare("ADX14", ind.adx(highs, lows, closes), [r[7] for r in rows], args.warmup, results)

            basis, upper, lower = ind.bollinger(closes)
            compare("BB basis", basis, [r[13] for r in rows], args.warmup, results)
            compare("BB upper", upper, [r[11] for r in rows], args.warmup, results)
            compare("BB lower", lower, [r[12] for r in rows], args.warmup, results)

            if all(v is not None for v in vols):
                compare("VWAP (session)", ind.vwap_session(times, highs, lows, closes, vols),
                        [r[8] for r in rows], args.warmup, results)
                vsma, vratio = ind.volume_metrics(vols)
                compare("volume_sma", vsma, [r[14] for r in rows], args.warmup, results)
                compare("volume_ratio", vratio, [r[15] for r in rows], args.warmup, results)
            else:
                print("    volume incomplete — VWAP/volume checks skipped")

    print("\n" + "=" * 66)
    fails = [r for r in results if r[2] == "FAIL"]
    closes_ = [r for r in results if r[2] == "CLOSE"]
    print(f"  {len(results)} checks: {len(results) - len(fails) - len(closes_)} PASS, "
          f"{len(closes_)} CLOSE, {len(fails)} FAIL")
    if fails:
        print("\n  FAILING — these will not transfer to a new candle source:")
        for label, med, _ in sorted(set((f[0], round(f[1], 4), f[2]) for f in fails)):
            print(f"    {label:<26} median {med}%")
    print("=" * 66)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
