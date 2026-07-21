"""Pure helpers for maker-first entry execution.

The execution itself is async and orders-table driven — the same pattern as the
TP/SL limit orders (see docs/maker_execution_plan.md):

  * MonitoringService._place_entry_order rests a PostOnly limit at the signal
    price via adapter.place_maker_entry_order() and returns immediately.
  * MonitoringService._monitor_orders -> _reconcile_maker_entry drives it each
    cycle: fill opens the position, timeout cancels and falls back to taker.

Nothing here blocks the trading loop. This module holds only the small,
side-effect-free decisions so they can be unit-tested without a live exchange
(tests/test_maker_execution.py).

Design constants baked into the helpers:
  * Rest AT the signal price — never price-improve. The adverse-selection test
    (Tools/measure_limit_fills.py) showed improving even 5bps forfeits the
    winners; resting at the signal price fills ~100% with ~0 adverse selection.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

MAKER_DEFAULT_TIMEOUT_SEC = 45   # rest this long before cancelling + taking


def maker_entry_limit_price(signal_price) -> Decimal:
    """Fallback price to rest a maker entry at: the signal price, unmodified.

    Do NOT add an offset. Price-improvement forfeits the winners (measured).
    Prefer best_maker_price() off live depth; this is the fallback when depth
    is unavailable.
    """
    return Decimal(str(signal_price))


def best_maker_price(depth: Any, is_long: bool) -> Optional[Decimal]:
    """Best price to REST a maker order at, from a live order book.

    A resting order is a maker only if it does not cross the book:
      * long  (buy)  -> rest AT the best BID (highest bid). Joins the bid queue.
      * short (sell) -> rest AT the best ASK (lowest ask).  Joins the ask queue.

    Using the live book instead of a ~30s-stale last price both avoids spurious
    PostOnly rejections and guarantees the order rests as a maker. Returns None
    when the book is missing/empty/crossed so the caller can fall back to the
    signal price.

    `depth` is the raw exchange depth: {"bids": [[price, qty], ...],
    "asks": [[price, qty], ...]} with prices as str or float, any sort order.
    """
    if not isinstance(depth, dict):
        return None
    bids = depth.get("bids") or []
    asks = depth.get("asks") or []

    def _prices(levels):
        out = []
        for lvl in levels:
            try:
                out.append(Decimal(str(lvl[0])))
            except Exception:  # noqa: BLE001
                continue
        return out

    bid_prices = _prices(bids)
    ask_prices = _prices(asks)
    best_bid = max(bid_prices) if bid_prices else None
    best_ask = min(ask_prices) if ask_prices else None

    # Sanity: a valid book has best_bid < best_ask. If crossed or one side is
    # empty, don't trust it — let the caller fall back.
    if best_bid is not None and best_ask is not None and best_bid >= best_ask:
        return None

    if is_long:
        return best_bid
    return best_ask


def entry_order_expired(age_seconds: float, timeout_sec: int) -> bool:
    """True when a resting entry order has waited past its timeout."""
    return age_seconds >= timeout_sec


def normalize_status(order_obj: Any) -> str:
    """Extract a status string from a dict or a pydantic order object."""
    if order_obj is None:
        return "UNKNOWN"
    raw = order_obj.get("status") if isinstance(order_obj, dict) else getattr(order_obj, "status", None)
    return str(getattr(raw, "value", raw) or "UNKNOWN")


def executed_qty(order_obj: Any) -> Decimal:
    """Extract executed quantity from a dict or a pydantic order object."""
    if order_obj is None:
        return Decimal("0")
    if isinstance(order_obj, dict):
        val = order_obj.get("executedQuantity") or order_obj.get("executed_quantity")
    else:
        val = getattr(order_obj, "executed_quantity", None)
    try:
        return Decimal(str(val or "0"))
    except Exception:  # noqa: BLE001
        return Decimal("0")
