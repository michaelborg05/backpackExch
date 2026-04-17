"""Quick manual test for BulletAdapter functions.

Run from exchange_client/:
    python Tools/test_bullet_adapter.py [test_name]

Tests (run all if no argument given):
    ticker       - get_ticker for SOL-USD
    depth        - get_depth order book
    klines       - get_klines CoinGecko fallback
    markets      - get_markets + market_id lookup
    balances     - get_balances (reads from wallet_address in .env)
    account      - get_account full state
    open_orders  - get_open_orders for SOL-USD
    order_history- get_order_history
    funding      - get_funding_rate
    tx_build     - build_bullet_transaction (does NOT submit — just serialises + signs)
"""
import os
import sys
import json
from time import time

# Allow running from exchange_client/ or exchange_client/Tools/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from types import SimpleNamespace
from api_builders.adapters.bullet import BulletAdapter

# ── Fake profile built from env vars ──────────────────────────────────────────
# Set these in .env or export them before running:
#   BULLET_WALLET_ADDRESS  — main wallet (for reads)
#   BULLET_DELEGATE_KEY    — delegate wallet address (api_key field)
#   BULLET_PRIVATE_KEY     — base64-encoded Ed25519 seed (secret field)
WALLET  = os.getenv("BULLET_WALLET_ADDRESS", "")
DELEGATE = os.getenv("BULLET_DELEGATE_KEY", WALLET)
SECRET   = os.getenv("BULLET_PRIVATE_KEY", "")

profile = SimpleNamespace(
    name="bullet_test",
    exchange_type="bullet",
    wallet_address=WALLET,
    api_key=DELEGATE,
    secret=SECRET,
    # Set these to test on-chain TP/SL attachment (optional)
    take_profit_pct=float(os.getenv("BULLET_TEST_TP_PCT", "0") or 0),
    stop_loss_pct=float(os.getenv("BULLET_TEST_SL_PCT", "0") or 0),
)

adapter = BulletAdapter(profile)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _pp(label: str, result):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print('='*60)
    if result is None:
        print("  (None returned)")
    else:
        try:
            print(json.dumps(result, indent=2, default=str))
        except Exception:
            print(repr(result))


# ── Individual tests ──────────────────────────────────────────────────────────

def test_ticker():
    result = adapter.get_ticker("SOL")
    _pp("get_ticker('SOL')", result)

def test_depth():
    result = adapter.get_depth("SOL")
    _pp("get_depth('SOL')", result)

def test_klines():
    result = adapter.get_klines("SOL", interval="1h", start_time=0, limit=5)
    _pp("get_klines('SOL', '1h', limit=5) — CoinGecko fallback", result)

def test_markets():
    result = adapter.get_markets()
    _pp(f"get_markets() — {len(result) if result else 0} markets", result)
    # Also show the market_id for SOL-USD
    mid = adapter._get_market_id("SOL-USD")
    print(f"\n  market_id for SOL-USD: {mid}")

def test_balances():
    if not WALLET:
        print("\n  SKIP: set BULLET_WALLET_ADDRESS in .env to test balances")
        return
    result = adapter.get_balances()
    _pp(f"get_balances() — wallet={WALLET[:12]}...", result)

def test_account():
    if not WALLET:
        print("\n  SKIP: set BULLET_WALLET_ADDRESS in .env to test account")
        return
    result = adapter.get_account()
    _pp(f"get_account() — wallet={WALLET[:12]}...", result)

def test_open_orders():
    if not WALLET:
        print("\n  SKIP: set BULLET_WALLET_ADDRESS in .env to test open_orders")
        return
    result = adapter.get_open_orders("SOL")
    _pp(f"get_open_orders('SOL')", result)

def test_order_history():
    if not WALLET:
        print("\n  SKIP: set BULLET_WALLET_ADDRESS in .env to test order_history")
        return
    result = adapter.get_order_history("SOL")
    _pp("get_order_history('SOL')", result)

def test_funding():
    result = adapter.get_funding_rate("SOL")
    _pp("get_funding_rate('SOL')", result)

def test_tx_build():
    """Serialise + sign a place_order transaction without submitting it.

    Requires BULLET_PRIVATE_KEY to be set. Does NOT hit the network.
    """
    if not SECRET:
        print("\n  SKIP: set BULLET_PRIVATE_KEY in .env to test tx building")
        return

    from utils.auth import build_bullet_transaction

    call_data = {
        "action": "place_orders",
        "market_id": 0,   # SOL-USD is typically index 0
        "orders": [{
            "price": "150.00",
            "size": "0.1",
            "side": "BID",
            "order_type": "LIMIT",
            "reduce_only": False,
            "client_order_id": None,
        }],
        "replace": False,
        "sub_account_index": 0,
    }

    nonce = int(time.time() * 1000)
    try:
        tx_b64 = build_bullet_transaction(
            private_key_b64=SECRET,
            call_data=call_data,
        )
        print(f"\n{'='*60}")
        print("  build_bullet_transaction — place_order (NOT submitted)")
        print('='*60)
        print(f"  nonce   : {nonce}")
        print(f"  tx_b64  : {tx_b64[:64]}...")
        print(f"  tx_len  : {len(tx_b64)} chars")
    except Exception as e:
        print(f"\n  ERROR: {e}")


def test_place_order():
    """Submit a real LIMIT BUY order to Bullet at a price well below market.

    Uses a price 30% below market so it sits as an open order and can be
    cancelled immediately — safe for testing without risking a fill.

    Requires BULLET_PRIVATE_KEY (and optionally BULLET_WALLET_ADDRESS) in .env.

    To customise, set env vars before running:
        BULLET_TEST_SYMBOL   — default: SOL    (base asset, not Bullet format)
        BULLET_TEST_QTY      — default: 0.01   (quantity in base asset)
        BULLET_TEST_SIDE     — default: BUY    (BUY or SELL)
        BULLET_TEST_SAFE     — default: true   (set to 'false' to use market price)
    """
    if not SECRET:
        print("\n  SKIP: set BULLET_PRIVATE_KEY in .env to place a real order")
        return

    symbol   = os.getenv("BULLET_TEST_SYMBOL", "SOL")
    qty      = os.getenv("BULLET_TEST_QTY", "1")
    side     = os.getenv("BULLET_TEST_SIDE", "BUY").upper()
    safe     = os.getenv("BULLET_TEST_SAFE", "true").lower() != "false"

    # Get current market price
    current_price = adapter.get_ticker(symbol)
    if not current_price:
        print(f"\n  ERROR: could not fetch price for {symbol} — cannot place order")
        return

    from api_builders.adapters.bullet import _to_bullet_symbol
    bullet_symbol = _to_bullet_symbol(symbol)
    tick_size, step_size, min_qty = adapter._get_market_filters(bullet_symbol)

    def _round(val, unit):
        from decimal import Decimal
        v = Decimal(str(val)); u = Decimal(str(unit))
        if u <= 0: return val
        r = (v // u) * u
        places = max(0, -u.as_tuple().exponent)
        return float(f"{r:.{places}f}")

    if safe:
        raw_price  = current_price * (0.90 if side == "BUY" else 1.10)
        limit_price = _round(raw_price, tick_size)
        order_type = "LIMIT"
        print(f"\n  Safe mode: {side} LIMIT at {limit_price} (market={current_price}, 30% away, tick={tick_size})")
    else:
        raw_price  = current_price * (1.02 if side == "BUY" else 0.98)
        limit_price = _round(raw_price, tick_size)
        order_type = "IOC"
        print(f"\n  ⚠️  Live mode: {side} IOC at {limit_price} (market={current_price}) — WILL FILL")

    qty = str(_round(float(qty), step_size))

    print(f"  Symbol: {symbol}, Qty: {qty}, Price: {limit_price}")
    print()

    confirm = input("  Press ENTER to submit, or Ctrl+C to abort: ")

    from utils.auth import build_bullet_transaction
    from utils.endpoints import BulletEndpoints
    from services.client import api_request
    from utils.constants import HttpMethod

    market_id = adapter._get_market_id(bullet_symbol)
    # Build TP/SL from env vars if set (e.g. BULLET_TEST_TP_PCT=5 BULLET_TEST_SL_PCT=2)
    tpsl = adapter._build_tpsl(float(limit_price), side="BID" if side == "BUY" else "ASK")
    if tpsl:
        tp = tpsl.get("tp")
        sl = tpsl.get("sl")
        print(f"  TP/SL: tp={tp['trigger_price'] if tp else None}, sl={sl['trigger_price'] if sl else None}")

    call_data = {
        "action": "place_orders",
        "market_id": market_id,
        "orders": [{
            "price": str(limit_price),
            "size": str(qty),
            "side": "BID" if side == "BUY" else "ASK",
            "order_type": order_type,
            "reduce_only": False,
            "client_order_id": None,
            "pending_tpsl_pair": tpsl,
        }],
        "replace": False,
        "sub_account_index": 0,
    }

    try:
        tx_b64 = build_bullet_transaction(
            private_key_b64=SECRET,
            call_data=call_data,
        )
    except Exception as e:
        print(f"\n  ERROR building tx: {e}")
        return

    print(f"  tx_b64: {tx_b64[:64]}...")

    url = BulletEndpoints.submit_tx()
    try:
        result = api_request(url, body={"body": tx_b64}, requestType=HttpMethod.POST)
        _pp(f"POST /tx/submit — {side} {qty} {symbol} @ {limit_price}", result)
    except Exception as e:
        print(f"\n  ERROR submitting tx: {e}")
        return

    # If a limit order was placed (safe mode), offer to cancel it immediately.
    # NOTE: /tx/submit returns a tx hash (0x...), NOT the numeric order ID.
    #       We must fetch open orders to find the real orderId for cancellation.
    if safe:
        cancel = input("\n  Cancel this order via open_orders lookup? [Y/n]: ").strip().lower()
        if cancel in ("", "y", "yes"):
            import time as _time
            _time.sleep(1)  # brief pause for order to appear on-chain
            open_orders = adapter.get_open_orders(symbol)
            if not open_orders:
                print("  No open orders found — order may not have landed yet, check Bullet UI")
            else:
                _pp("Open orders (pick orderId to cancel)", open_orders)
                for o in open_orders:
                    oid = o.get("orderId") or o.get("id")
                    oprice = o.get("price", "?")
                    if oid:
                        do_cancel = input(f"  Cancel order {oid} @ {oprice}? [Y/n]: ").strip().lower()
                        if do_cancel in ("", "y", "yes"):
                            cancel_result = adapter.cancel_order(str(oid), symbol)
                            _pp("cancel_order result", cancel_result)


# ── Runner ────────────────────────────────────────────────────────────────────

TESTS = {
    "ticker":        test_ticker,
    "depth":         test_depth,
    "klines":        test_klines,
    "markets":       test_markets,
    "balances":      test_balances,
    "account":       test_account,
    "open_orders":   test_open_orders,
    "order_history": test_order_history,
    "funding":       test_funding,
    "tx_build":      test_tx_build,
    "place_order":   test_place_order,
}

if __name__ == "__main__":
    requested = sys.argv[1:] or list(TESTS.keys())
    for name in requested:
        if name not in TESTS:
            print(f"Unknown test '{name}'. Available: {', '.join(TESTS)}")
            sys.exit(1)
        TESTS[name]()
