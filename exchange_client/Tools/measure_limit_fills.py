"""Measure adverse selection on limit-order entries.

The question this answers: if entries were posted as passive limit orders instead
of crossing the spread, would the maker fee saving survive the trades you no
longer get?

The worry is not "catching a falling knife" — these are pullback entries, the dip
has already happened by the time the signal fires. The real hazard is ADVERSE
SELECTION: a resting buy fills when price keeps coming toward you, and does not
fill when price runs away. The trades that run away immediately are
disproportionately the WINNERS, so passive entry can systematically keep the
worse half of the distribution.

Method: for every historical entry, post a hypothetical limit at (or below) the
signal price and use 1m OHLC to determine whether it would have filled inside a
timeout. Then compare the realised PnL of FILLED versus MISSED trades. If missed
trades are materially better than filled ones, the fee saving is an illusion.

1m data is fetched on demand and never stored — nothing is written to the DB.

    python Tools/measure_limit_fills.py --variant tf_v9_atrcap070
    python Tools/measure_limit_fills.py --variant tf_v9_trail20 --timeouts 5 15 30
"""
import argparse
import csv
import glob
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.candle_fetcher import fetch_klines


def load_trades(csv_glob, variants):
    f = sorted(glob.glob(csv_glob))
    if not f:
        raise SystemExit(f"no csv matching {csv_glob}")
    rows = []
    for r in csv.DictReader(open(f[-1])):
        if variants and r["variant"] not in variants:
            continue
        rows.append({
            "variant": r["variant"], "symbol": r["symbol"],
            "entry": datetime.fromisoformat(r["entry_time"]),
            "price": float(r["entry_price"]), "pnl": float(r["pnl_pct"]),
        })
    return f[-1], rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="/home/michael/Downloads/backtest_v9*.csv")
    ap.add_argument("--variant", nargs="+", default=["tf_v9_atrcap070"])
    ap.add_argument("--offsets-bps", type=float, nargs="+", default=[0, 5, 10, 20],
                    help="how far BELOW the signal price to rest the bid")
    ap.add_argument("--timeouts", type=int, nargs="+", default=[15, 30, 60],
                    help="minutes to leave the order resting before giving up")
    args = ap.parse_args()

    path, trades = load_trades(args.csv, set(args.variant))
    print(f"{path}\n{len(trades)} entries across {len(set(t['symbol'] for t in trades))} symbols "
          f"({', '.join(args.variant)})\n")

    # Group by symbol+day so each 1m fetch is reused across that day's entries.
    by_day = defaultdict(list)
    for t in trades:
        by_day[(t["symbol"], t["entry"].date())].append(t)

    max_to = max(args.timeouts)
    bars = {}
    print(f"fetching 1m data for {len(by_day)} symbol-days...")
    for i, ((sym, day), ts) in enumerate(sorted(by_day.items()), 1):
        lo = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        hi = lo + timedelta(days=1, minutes=max_to)
        try:
            candles, _ = fetch_klines(sym, "1", lo, hi)
            bars[(sym, day)] = candles
        except Exception as e:  # noqa: BLE001
            print(f"  ! {sym} {day}: {e}")
        if i % 25 == 0:
            print(f"  {i}/{len(by_day)}")

    print("\nFILL RATE and ADVERSE SELECTION")
    print("  'missed' = the trade a passive order would NOT have got.")
    print("  If missed PnL >> filled PnL, the fee saving is an illusion.\n")
    header = f"  {'offset':>7}{'timeout':>9}{'filled':>8}{'fill%':>7}{'avg filled':>12}{'avg missed':>12}{'edge lost':>11}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for off in args.offsets_bps:
        for to in args.timeouts:
            filled, missed = [], []
            for t in trades:
                cs = bars.get((t["symbol"], t["entry"].date()))
                if not cs:
                    continue
                limit = t["price"] * (1 - off / 10_000)
                deadline = t["entry"] + timedelta(minutes=to)
                got = False
                for c in cs:
                    if c.open_time < t["entry"]:
                        continue
                    if c.open_time > deadline:
                        break
                    if c.low <= limit:     # a resting bid fills when price trades down to it
                        got = True
                        break
                (filled if got else missed).append(t["pnl"])
            if not filled and not missed:
                continue
            n = len(filled) + len(missed)
            af = st.mean(filled) if filled else 0.0
            am = st.mean(missed) if missed else 0.0
            # Edge lost = how much worse the filled subset is than the full set.
            full = st.mean(filled + missed)
            lost = af - full
            print(f"  {off:>6.0f}b{to:>8}m{len(filled):>8}{len(filled)/n:>6.0%}"
                  f"{af:>+11.4f}%{am:>+11.4f}%{lost:>+10.4f}%")

    print("\n  offset 0b = rest at the signal price; 10b = 0.10% below it.")
    print("  'edge lost' is the change in avg PnL/trade from only getting the fills.")
    print("  Compare against the fee saving: taker->maker is worth roughly")
    print("  +0.03% to +0.07% per round trip depending on tier.")


if __name__ == "__main__":
    main()
