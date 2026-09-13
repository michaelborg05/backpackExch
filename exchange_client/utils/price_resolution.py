"""Reference-price resolution: prefer the live book over the last fill.

Backpack's `/api/v1/ticker` carries no timestamp, and its `lastPrice` is the
last *fill*, which on a thin market can be hours old. A 2026-09-12 sweep of the
23-symbol roster found a median last-trade age of 2.1 hours, with `lastPrice`
up to 6% away from the book (RAY +5.98%, WLD -4.06%, AAVE -2.35%). Everything
downstream of the price cache — TP/SL triggers, trailing stops, circuit-breaker
marks, position sizing, maker limit prices — was reading that number.

Top-of-book spread stayed under 0.18% even on the worst of those symbols, so
the midpoint is the better reference price and `lastPrice` is only the fallback
for when the book is unusable.

Both helpers are pure: no HTTP, no cache, no settings. The fetching lives in
`api_builders.market_builder`.
"""
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, NamedTuple, Optional


class BookTop(NamedTuple):
    """Top of the order book plus the derived midpoint."""
    bid: Decimal
    ask: Decimal
    mid: Decimal
    spread_pct: Decimal
    timestamp_us: Optional[int]


class PriceQuote(NamedTuple):
    """The reference price actually chosen, and where it came from.

    `source` is stored on the cache entry so a surprising valuation can be
    traced back to book vs last fill without re-deriving it.
    """
    price: Optional[Decimal]
    source: str
    bid: Optional[Decimal]
    ask: Optional[Decimal]
    spread_pct: Optional[Decimal]


def _levels(raw) -> list:
    """Parse [[price, qty], ...] into a list of Decimal prices, skipping junk."""
    out = []
    for level in raw or []:
        try:
            out.append(Decimal(str(level[0])))
        except (InvalidOperation, TypeError, IndexError, ValueError):
            continue
    return out


def book_top(depth: Optional[Dict[str, Any]]) -> Optional[BookTop]:
    """Best bid/ask/mid from a raw depth response, or None when unusable.

    Backpack returns bids *ascending*, so the best bid is the last element — this
    takes max/min instead of indexing, so it holds for any sort order and for any
    exchange's depth payload. (`maker_execution.best_maker_price` does the same
    for the one side it needs; it deliberately tolerates a one-sided book, which
    a midpoint cannot.)

    Returns None when either side is empty or the book is crossed, so callers
    fall back rather than acting on a broken quote.
    """
    if not isinstance(depth, dict):
        return None

    bids = _levels(depth.get("bids"))
    asks = _levels(depth.get("asks"))
    if not bids or not asks:
        return None

    bid, ask = max(bids), min(asks)
    if bid <= 0 or ask <= 0 or bid >= ask:
        return None

    mid = (bid + ask) / 2
    spread_pct = (ask - bid) / mid * 100

    timestamp_us = None
    try:
        if depth.get("timestamp") is not None:
            timestamp_us = int(depth["timestamp"])
    except (TypeError, ValueError):
        pass

    return BookTop(bid=bid, ask=ask, mid=mid, spread_pct=spread_pct,
                   timestamp_us=timestamp_us)


def resolve_reference_price(
    last_price: Optional[Any],
    top: Optional[BookTop],
    max_spread_pct: float = 2.0,
) -> PriceQuote:
    """Choose the price the rest of the system should treat as "current".

    The book midpoint wins whenever the book is usable and its spread is sane.
    A spread wider than *max_spread_pct* means a broken or abandoned book — the
    measured worst case on the live roster was 0.18% — so that falls back to the
    last fill, which at least was a real trade. If neither is available the price
    is None and the caller should leave the cache entry alone: going stale is
    safer than valuing a position off a made-up number.
    """
    try:
        last = Decimal(str(last_price)) if last_price is not None else None
        if last is not None and last <= 0:
            last = None
    except (InvalidOperation, TypeError, ValueError):
        last = None

    if top is None:
        return PriceQuote(last, "last_no_book" if last else "unavailable",
                          None, None, None)

    if top.spread_pct > Decimal(str(max_spread_pct)):
        if last is not None:
            return PriceQuote(last, "last_wide_book", top.bid, top.ask, top.spread_pct)
        return PriceQuote(top.mid, "book_mid_wide", top.bid, top.ask, top.spread_pct)

    return PriceQuote(top.mid, "book_mid", top.bid, top.ask, top.spread_pct)


def deviation_pct(price: Optional[Any], reference: Optional[Any]) -> Optional[Decimal]:
    """How far *price* sits from *reference*, as a signed percentage.

    Used to log how stale the last fill was relative to the book actually used.
    Accepts str/float/Decimal and returns None for anything unusable.
    """
    try:
        if price is None or reference is None:
            return None
        p, r = Decimal(str(price)), Decimal(str(reference))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if r == 0:
        return None
    return (p - r) / r * 100
