"""Rank Backpack markets by EXECUTABLE liquidity, not daily volume.

Daily volume tells you how much others traded; it does not tell you what your
own order will cost. This measures the thing that actually matters for a
strategy with a ~0.35%/trade edge: how many bps you give up crossing the book
for your typical order size, and how tight the resting spread is.

Public market-data endpoints only — no auth, no orders placed.

    python Tools/check_market_depth.py --size 500 1000 2500
"""
import argparse
import json
import sys
import time
import urllib.request

BASE = "https://api.backpack.exchange"


def get(path: str):
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": "depth-check/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def slippage_bps(levels, usd_size: float, side: str):
    """Volume-weighted slippage in bps to fill usd_size by crossing the book.

    levels: [[price, qty], ...] — asks ascending for a buy, bids descending for a sell.
    Returns None if the book cannot fill the order at all.
    """
    if not levels:
        return None
    best = float(levels[0][0])
    remaining, cost, filled = usd_size, 0.0, 0.0
    for price, qty in levels:
        price, qty = float(price), float(qty)
        avail_usd = price * qty
        take = min(remaining, avail_usd)
        cost += take
        filled += take / price
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0 or filled <= 0:
        return None
    vwap = cost / filled
    return abs(vwap - best) / best * 10_000 * (1 if side == "buy" else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=float, nargs="+", default=[500, 1000, 2500],
                    help="Order sizes in USD to price out")
    ap.add_argument("--quote", default="USDC", help="Quote asset filter")
    ap.add_argument("--min-vol", type=float, default=0.0, help="Skip markets under this 24h USD volume")
    args = ap.parse_args()

    markets = get("/api/v1/markets")
    tickers = {t["symbol"]: t for t in get("/api/v1/tickers")}

    syms = [m["symbol"] for m in markets
            if m.get("quoteSymbol") == args.quote and m.get("orderBookState", "Open") == "Open"]
    print(f"{len(syms)} {args.quote} markets open. Pricing {args.size} USD orders...\n")

    rows = []
    for sym in syms:
        t = tickers.get(sym, {})
        vol = float(t.get("quoteVolume") or 0)
        if vol < args.min_vol:
            continue
        try:
            book = get(f"/api/v1/depth?symbol={sym}")
        except Exception as e:
            print(f"  ! {sym}: {e}", file=sys.stderr)
            continue
        # Backpack returns bids ascending — reverse so best bid is first.
        bids = sorted(book.get("bids", []), key=lambda x: -float(x[0]))
        asks = sorted(book.get("asks", []), key=lambda x: float(x[0]))
        if not bids or not asks:
            continue
        bid, ask = float(bids[0][0]), float(asks[0][0])
        mid = (bid + ask) / 2
        spread_bps = (ask - bid) / mid * 10_000
        slips = [slippage_bps(asks, s, "buy") for s in args.size]
        rows.append((sym, vol, spread_bps, slips))
        time.sleep(0.08)  # be polite to the public endpoint

    rows.sort(key=lambda r: (r[3][0] is None, r[3][0] if r[3][0] is not None else 9e9))

    size_hdr = "".join(f"{'$'+str(int(s)):>10}" for s in args.size)
    print(f"{'symbol':<16}{'24h vol $':>14}{'spread bps':>12}{size_hdr}   round-trip cost")
    print("-" * (42 + 10 * len(args.size) + 20))
    for sym, vol, spread, slips in rows:
        cells = "".join(f"{(f'{s:.1f}' if s is not None else 'n/a'):>10}" for s in slips)
        # round trip = spread crossed twice (in and out) at the smallest size
        rt = (slips[0] * 2 + spread) / 100 if slips[0] is not None else None
        rt_s = f"{rt:.3f}%" if rt is not None else "  n/a"
        flag = ""
        if rt is not None:
            flag = "  <-- viable" if rt < 0.15 else ("  marginal" if rt < 0.30 else "  too costly")
        print(f"{sym:<16}{vol:>14,.0f}{spread:>12.1f}{cells}   {rt_s}{flag}")

    print("\nround-trip cost = 2x slippage at the smallest size + spread, as % of notional.")
    print("Compare against your gross edge (~0.35%/trade) BEFORE fees.")
    print("A market is only worth trading if this is a small fraction of that.")


if __name__ == "__main__":
    main()
