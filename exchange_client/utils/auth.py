"""Exchange-agnostic authentication helpers.

Each exchange has a different auth mechanism:
  - Backpack: HMAC-SHA256 signed headers (X-API-KEY, X-SIGNATURE, X-TIMESTAMP, X-WINDOW)
  - Bullet:   No auth headers for reads (wallet address in query param).
              Writes use a Borsh-serialised, Ed25519-signed transaction posted to /tx/submit.

Usage:
    from utils.auth import build_auth_headers, build_bullet_transaction

    # For read requests:
    headers = build_auth_headers("backpack", profile, instruction="balanceQuery")
    headers = build_auth_headers("bullet", profile)   # returns {} — no headers needed

    # For Bullet write requests (order placement / cancellation):
    tx_b64 = build_bullet_transaction(profile.secret, call_data, chain_id, chain_hash)
"""
import base64
import struct
import time
from decimal import Decimal as PyDecimal
from typing import Dict, Any, Optional
from utils import data_converters


# ── Public entry point ────────────────────────────────────────────────────────

def build_auth_headers(
    exchange_type: str,
    profile,
    instruction: str = "",
    query_params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    window: int = 60000,
) -> Dict[str, str]:
    """Return HTTP headers needed to authenticate a request."""
    if exchange_type == "backpack":
        return _backpack_headers(
            api_key=profile.api_key,
            secret=profile.secret,
            instruction=instruction,
            query_params=query_params or {},
            body=body,
            window=window,
        )
    if exchange_type == "bullet":
        return {}  # Bullet reads: no auth headers — wallet address goes in the URL
    raise ValueError(
        f"Unknown exchange type: {exchange_type!r}. Valid: 'backpack', 'bullet'"
    )


def build_bullet_transaction(
    private_key_b64: str,
    call_data: Dict[str, Any],
    chain_id: int = 4321,
    chain_hash: Optional[bytes] = None,
) -> str:
    """Build and sign a Bullet on-chain transaction.

    Reference: https://tradingapi.bullet.xyz/docs/tx-signing.html

    Signing procedure (from official docs):
        msg = borsh(UnsignedTransaction) + chain_hash
        signature = ed25519_sign(keypair, msg)
        signed_tx = borsh(SignedTransaction::V0 { signature, pub_key, tx: unsigned })
        submit as base64 via POST /tx/submit  {"body": "<base64>"}

    call_data format for place_orders:
        {
            "action": "place_orders",
            "market_id": <int>,          # u16 index from exchangeInfo symbols list
            "orders": [{
                "price": <float|str>,
                "size": <float|str>,
                "side": "BID"|"ASK",
                "order_type": "LIMIT"|"POSTONLY"|"FOK"|"IOC",
                "reduce_only": <bool>,
                "client_order_id": <int|None>,
                "pending_tpsl_pair": <dict|None>,
            }],
            "replace": <bool>,
        }

    call_data format for cancel_orders:
        {
            "action": "cancel_orders",
            "market_id": <int>,
            "orders": [{"order_id": <int|None>, "client_order_id": <int|None>}],
        }

    Args:
        private_key_b64: Base64/hex/base58-encoded Ed25519 private key seed (32 bytes)
        call_data:       Runtime call payload dict (see above)
        chain_id:        Bullet chain ID (4321=mainnet, 4322=testnet)
        chain_hash:      32-byte chain hash from GET /fapi/v1/exchangeInfo → chainHash.
                         If None, fetched automatically (one HTTP call per invocation).

    Returns:
        Base64-encoded signed transaction string — use as {"body": "<value>"} in POST /tx/submit
    """
    import nacl.signing  # PyNaCl — already in requirements.txt

    seed = _decode_ed25519_seed(private_key_b64)
    signing_key = nacl.signing.SigningKey(seed)
    pub_key_bytes = bytes(signing_key.verify_key)  # 32 bytes

    if chain_hash is None:
        chain_hash = _fetch_chain_hash()

    # Serialise UnsignedTransaction
    runtime_call_bytes = _serialize_runtime_call(call_data)
    uniqueness_bytes   = _serialize_uniqueness()
    details_bytes      = _serialize_tx_details(chain_id)
    unsigned_tx        = runtime_call_bytes + uniqueness_bytes + details_bytes

    # Sign: borsh(unsigned_tx) + chain_hash
    msg = unsigned_tx + chain_hash
    signed    = signing_key.sign(msg)
    signature = signed.signature  # 64 bytes

    # SignedTransaction::V0 { signature[64], pub_key[32], tx: UnsignedTransaction }
    # Wrapped in SignedTransaction enum discriminant 0
    signed_tx = struct.pack("<B", 0) + signature + pub_key_bytes + unsigned_tx

    return base64.b64encode(signed_tx).decode("utf-8")


# ── Chain info ────────────────────────────────────────────────────────────────

_cached_chain_info: Dict[str, Any] = {}


def _fetch_chain_hash() -> bytes:
    """Fetch chain_hash from Bullet and cache it.

    Tries /rollup/schema first (already used elsewhere), then /fapi/v1/exchangeInfo.
    Uses api_request so the User-Agent header is set correctly (avoids Cloudflare 403).
    """
    global _cached_chain_info
    if _cached_chain_info.get("chain_hash"):
        return _cached_chain_info["chain_hash"]

    from services.client import api_request

    # /rollup/schema returns {"schema": {...}, "chain_hash": "<hex>"}
    data = api_request("https://tradingapi.mainnet.bullet.xyz/rollup/schema")
    hex_str = (data or {}).get("chain_hash", "")

    if not hex_str:
        # Fallback: exchangeInfo
        data = api_request("https://tradingapi.mainnet.bullet.xyz/fapi/v1/exchangeInfo")
        data = data or {}
        hex_str = (
            data.get("chainHash")
            or data.get("chain_hash")
            or (data.get("chainInfo") or {}).get("chainHash")
            or ""
        )

    if not hex_str:
        raise RuntimeError("Could not fetch Bullet chain_hash from /rollup/schema or /fapi/v1/exchangeInfo")

    if hex_str.startswith("0x"):
        hex_str = hex_str[2:]
    chain_hash = bytes.fromhex(hex_str)
    _cached_chain_info["chain_hash"] = chain_hash
    return chain_hash


# ── Key decoding ─────────────────────────────────────────────────────────────

_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58decode(s: str) -> bytes:
    """Minimal base58 decode (no checksum). Handles Solana keypair exports."""
    alphabet = _B58_ALPHABET
    n = 0
    for char in s.encode("ascii"):
        digit = alphabet.index(char)
        n = n * 58 + digit
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + n.to_bytes((n.bit_length() + 7) // 8 or 1, "big")


def _decode_ed25519_seed(raw: str) -> bytes:
    """Decode an Ed25519 private key in any common format and return the 32-byte seed."""
    raw = raw.strip()

    # Try base64
    try:
        decoded = base64.b64decode(raw)
        return _extract_seed(decoded, "base64")
    except Exception:
        pass

    # Try hex
    try:
        decoded = bytes.fromhex(raw)
        return _extract_seed(decoded, "hex")
    except Exception:
        pass

    # Try base58 (Solana keypair export)
    try:
        decoded = _b58decode(raw)
        return _extract_seed(decoded, "base58")
    except Exception:
        pass

    raise ValueError(
        f"Cannot decode Bullet private key (tried base64, hex, base58). "
        f"Expected a 32-byte Ed25519 seed or 64-byte Solana keypair. "
        f"Raw value starts with: {raw[:20]!r}"
    )


def _extract_seed(decoded: bytes, fmt: str) -> bytes:
    if len(decoded) == 32:
        return decoded
    if len(decoded) == 64:
        return decoded[:32]
    raise ValueError(
        f"Decoded {fmt} key is {len(decoded)} bytes — expected 32 (seed) or 64 (full keypair)"
    )


# ── Bullet Borsh serialisation ────────────────────────────────────────────────
#
# Reference types (from official Rust SDK docs):
#
#   enum RuntimeCall            { Exchange((ExchangeCallMessage,)) = 7 }
#   enum ExchangeCallMessage    { User(ExchangeUserAction) = 0 }
#   enum ExchangeUserAction     { PlaceOrders(PlaceOrdersCall) = 20, CancelOrders(CancelOrdersCall) = 22 }
#
#   struct PlaceOrdersCall      { market_id: MarketId(u16), orders: Vec<NewOrderArgs>,
#                                 replace: bool, sub_account_index: Option<u8> }
#   struct CancelOrdersCall     { market_id: MarketId(u16), orders: Vec<CancelOrderArgs>,
#                                 sub_account_index: Option<u8> }
#
#   struct NewOrderArgs         { price: SurrogateDecimal, size: SurrogateDecimal,
#                                 side: Side, order_type: OrderType, reduce_only: bool,
#                                 client_order_id: Option<ClientOrderId(u64)>,
#                                 pending_tpsl_pair: Option<PendingTpslPair> }
#
#   struct SurrogateDecimal     { flags: u32, hi: u32, lo: u32, mid: u32 }
#     (rust_decimal::Decimal layout: flags bit31=sign, bits16-23=scale; mantissa=hi<<64|mid<<32|lo)
#
#   struct PendingTpslPair      { tpsl_pair: TpslPair, dynamic_size: bool }
#   struct TpslPair             { take_profit: Option<TpslLeg>, stop_loss: Option<TpslLeg> }
#   struct TpslLeg              { trigger_price: SurrogateDecimal,
#                                 order_price: Option<SurrogateDecimal>,
#                                 trigger_condition: TriggerPriceCondition }
#   enum TriggerPriceCondition  { Mark=0, Oracle=1, LastTrade=2 }
#
#   enum UniquenessData         { Nonce(u64)=0, Generation(u64)=1 }
#     (examples use Generation with microsecond timestamp)
#
#   struct TxDetails            { max_priority_fee_bips: u64, max_fee: Amount(u128),
#                                 gas_limit: Option<[u64;2]>, chain_id: u64 }
#
#   enum OrderType              { Limit=0, PostOnly=1, FillOrKill=2, ImmediateOrCancel=3,
#                                 PostOnlySlide=4, PostOnlyFront=5 }

_ORDER_TYPE_MAP = {
    "LIMIT": 0,
    "POSTONLY": 1,
    "FILLORKILL": 2,
    "FOK": 2,
    "IOC": 3,
    "IMMEDIATEORCANCEL": 3,
}

_TRIGGER_CONDITION_MAP = {
    "MARK": 0,
    "ORACLE": 1,
    "LASTTRADE": 2,
    "LAST": 2,
}


def _serialize_runtime_call(call_data: Dict) -> bytes:
    """RuntimeCall::Exchange((ExchangeCallMessage::User(action),)) = 0x07 0x00 <action>"""
    action = call_data.get("action")
    if action == "place_orders":
        user_action = _serialize_place_orders(call_data)
    elif action == "cancel_orders":
        user_action = _serialize_cancel_orders(call_data)
    else:
        raise ValueError(f"Unknown call_data action: {action!r}")

    return (
        struct.pack("<B", 7)   # RuntimeCall::Exchange discriminant
        + struct.pack("<B", 0) # ExchangeCallMessage::User discriminant
        + user_action
    )


def _serialize_place_orders(call_data: Dict) -> bytes:
    """ExchangeUserAction::PlaceOrders(PlaceOrdersCall) = discriminant 20."""
    market_id = int(call_data.get("market_id", 0))
    orders    = call_data.get("orders", [])
    replace   = bool(call_data.get("replace", False))

    result  = struct.pack("<B", 20)           # discriminant
    result += struct.pack("<H", market_id)    # MarketId(u16)
    result += struct.pack("<I", len(orders))  # Vec length prefix
    for order in orders:
        result += _serialize_new_order_args(order)
    result += struct.pack("<?", replace)      # bool
    result += b"\x00"                         # sub_account_index: Option<u8> = None
    return result


def _serialize_cancel_orders(call_data: Dict) -> bytes:
    """ExchangeUserAction::CancelOrders(CancelOrdersCall) = discriminant 22."""
    market_id = int(call_data.get("market_id", 0))
    orders    = call_data.get("orders", [])

    result  = struct.pack("<B", 22)
    result += struct.pack("<H", market_id)    # MarketId(u16)
    result += struct.pack("<I", len(orders))
    for order in orders:
        result += _serialize_cancel_order_args(order)
    result += b"\x00"                         # sub_account_index: Option<u8> = None
    return result


def _serialize_new_order_args(order: Dict) -> bytes:
    """NewOrderArgs Borsh serialisation."""
    price_bytes = _surrogate_decimal(order.get("price", 0))
    size_bytes  = _surrogate_decimal(order.get("size", 0))

    side_str = str(order.get("side", "BID")).upper()
    side_disc = 0 if side_str in ("BID", "BUY", "LONG") else 1

    ot_str   = str(order.get("order_type", "LIMIT")).upper().replace("_", "").replace(" ", "")
    ot_disc  = _ORDER_TYPE_MAP.get(ot_str, 0)

    reduce_only      = bool(order.get("reduce_only", False))
    client_order_id  = order.get("client_order_id")
    tpsl             = order.get("pending_tpsl_pair")

    result  = price_bytes
    result += size_bytes
    result += struct.pack("<B", side_disc)
    result += struct.pack("<B", ot_disc)
    result += struct.pack("<?", reduce_only)
    # Option<ClientOrderId(u64)>
    if client_order_id is not None:
        result += b"\x01" + struct.pack("<Q", int(client_order_id))
    else:
        result += b"\x00"
    # Option<PendingTpslPair>
    result += _serialize_option_tpsl(tpsl)
    return result


def _serialize_cancel_order_args(order: Dict) -> bytes:
    """CancelOrderArgs { order_id: Option<OrderId(u64)>, client_order_id: Option<ClientOrderId(u64)> }"""
    order_id        = order.get("order_id")
    client_order_id = order.get("client_order_id")

    result  = (b"\x01" + struct.pack("<Q", int(order_id))) if order_id is not None else b"\x00"
    result += (b"\x01" + struct.pack("<Q", int(client_order_id))) if client_order_id is not None else b"\x00"
    return result


def _serialize_option_tpsl(tpsl: Optional[Dict]) -> bytes:
    if not tpsl:
        return b"\x00"
    return b"\x01" + _serialize_pending_tpsl_pair(tpsl)


def _serialize_pending_tpsl_pair(tpsl: Dict) -> bytes:
    """PendingTpslPair { tpsl_pair: TpslPair, dynamic_size: bool }"""
    dynamic_size = bool(tpsl.get("dynamic_size", False))
    result  = _serialize_tpsl_pair(tpsl)
    result += struct.pack("<?", dynamic_size)
    return result


def _serialize_tpsl_pair(tpsl: Dict) -> bytes:
    """TpslPair { take_profit: Option<TpslLeg>, stop_loss: Option<TpslLeg> }"""
    tp = tpsl.get("tp") or tpsl.get("take_profit")
    sl = tpsl.get("sl") or tpsl.get("stop_loss")
    return _serialize_option_tpsl_leg(tp) + _serialize_option_tpsl_leg(sl)


def _serialize_option_tpsl_leg(leg: Optional[Dict]) -> bytes:
    if not leg:
        return b"\x00"
    return b"\x01" + _serialize_tpsl_leg(leg)


def _serialize_tpsl_leg(leg: Dict) -> bytes:
    """Serialize Tpsl struct — field order from GET /rollup/schema (canonical):
        order_price:     SurrogateDecimal  (NOT optional)
        trigger_price:   SurrogateDecimal  (NOT optional)
        price_condition: TriggerPriceCondition (u8)
        order_type:      OrderType (u8)

    Note: the Rust SDK docs show a different struct (TpslLeg) with a different
    field order and Option<order_price>. The rollup schema overrides that.
    """
    order_price   = _surrogate_decimal(leg.get("order_price", leg.get("trigger_price", 0)))
    trigger_price = _surrogate_decimal(leg.get("trigger_price", 0))

    cond_str  = str(leg.get("price_condition", leg.get("trigger_condition", "Mark"))).upper().replace(" ", "").replace("_", "")
    cond_disc = _TRIGGER_CONDITION_MAP.get(cond_str, 0)

    ot_str   = str(leg.get("order_type", "IOC")).upper().replace("_", "").replace(" ", "")
    ot_disc  = _ORDER_TYPE_MAP.get(ot_str, 3)  # default IOC

    return order_price + trigger_price + struct.pack("<B", cond_disc) + struct.pack("<B", ot_disc)


def _serialize_uniqueness() -> bytes:
    """UniquenessData::Generation(u64) — microsecond timestamp (as used in official examples)."""
    ts_us = int(time.time() * 1_000_000)
    return struct.pack("<B", 1) + struct.pack("<Q", ts_us)  # discriminant 1 + u64


def _serialize_tx_details(chain_id: int) -> bytes:
    """TxDetails { max_priority_fee_bips: u64, max_fee: Amount(u128), gas_limit: Option<[u64;2]>, chain_id: u64 }"""
    max_priority_fee_bips = 0
    max_fee = 1 << 48  # Amount(1 << 48) as per official default_tx_details()
    result  = struct.pack("<Q", max_priority_fee_bips)  # u64
    result += (max_fee).to_bytes(16, "little")          # Amount(u128)
    result += b"\x00"                                   # gas_limit: None
    result += struct.pack("<Q", chain_id)               # u64
    return result


# ── SurrogateDecimal (rust_decimal::Decimal layout) ──────────────────────────

def _surrogate_decimal(value) -> bytes:
    """Encode a numeric value as rust_decimal::Decimal (SurrogateDecimal) in Borsh.

    SurrogateDecimal { flags: u32, hi: u32, lo: u32, mid: u32 }
    - flags: bit 31 = negative, bits 16-23 = scale (decimal places)
    - mantissa: 96-bit uint = hi<<64 | mid<<32 | lo
    - actual value = (-1 if negative) * mantissa / 10^scale
    """
    d = PyDecimal(str(value))
    negative = d < 0
    if negative:
        d = -d

    # Determine scale from the decimal's own tuple
    _, digits, exponent = d.as_tuple()
    scale = max(0, -exponent)
    if scale > 28:
        scale = 28

    mantissa = int(d * PyDecimal(10) ** scale)

    flags = (scale << 16) | (0x80000000 if negative else 0)
    lo  = mantissa & 0xFFFFFFFF
    mid = (mantissa >> 32) & 0xFFFFFFFF
    hi  = (mantissa >> 64) & 0xFFFFFFFF

    # Field order per struct definition: flags, hi, lo, mid
    return struct.pack("<IIII", flags, hi, lo, mid)


# ── Private helpers ───────────────────────────────────────────────────────────

def _backpack_headers(
    api_key: str,
    secret: str,
    instruction: str,
    query_params: Dict[str, Any],
    body: Optional[Dict[str, Any]],
    window: int,
) -> Dict[str, str]:
    return data_converters.build_authorisation_header(
        api_key=api_key,
        secret=secret,
        query_params=query_params,
        body=body,
        instruction=instruction,
        window=window,
    )
