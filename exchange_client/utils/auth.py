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
    tx_b64 = build_bullet_transaction(profile.secret, call_data, nonce)
"""
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
    """Return HTTP headers needed to authenticate a request.

    For Backpack:  returns signed X-API-KEY / X-SIGNATURE / X-TIMESTAMP / X-WINDOW headers.
    For Bullet:    returns {} — Bullet reads are authenticated by ?address= query param only.

    Args:
        exchange_type: "backpack" or "bullet"
        profile:       TradingProfile instance (must have .api_key and .secret)
        instruction:   Backpack instruction string (e.g. "balanceQuery", "orderExecute")
        query_params:  Backpack query params to include in signature
        body:          Backpack request body to include in signature
        window:        Backpack signature window in ms

    Returns:
        Dict of HTTP headers (may be empty for Bullet reads)
    """
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
    nonce: int,
    chain_id: int = 4321,
) -> str:
    """Build and sign a Bullet on-chain transaction for order placement/cancellation.

    Bullet uses a Borsh-serialised transaction signed with an Ed25519 keypair.
    The signed transaction is base64-encoded and posted to POST /tx/submit.

    Args:
        private_key_b64: Base64-encoded Ed25519 private key (seed, 32 bytes)
        call_data:       Runtime call payload (e.g. exchange.place_order args)
        nonce:           Uniqueness nonce — increment per request to prevent replay
        chain_id:        Bullet chain ID (4321 = mainnet, 4322 = testnet)

    Returns:
        Base64-encoded signed transaction string ready for /tx/submit

    Raises:
        NotImplementedError: until Borsh serialisation is fully implemented.
                             Requires: pip install borsh-python PyNaCl
    """
    # TODO: implement full Borsh serialisation + Ed25519 signing.
    #
    # Outline of what needs to happen:
    #   1. Derive Ed25519 keypair from private_key_b64 (32-byte seed)
    #   2. Construct the transaction body:
    #        {
    #          "version": "V0",
    #          "signature": <64-byte sig hex>,
    #          "public_key": <32-byte pubkey hex>,
    #          "runtime_call": call_data,          # e.g. {"exchange": {"place_order": {...}}}
    #          "nonce": nonce,
    #          "chain_id": chain_id,
    #          "gas_limit": None,                  # None = use Paymaster
    #          "priority_fee": "0",
    #        }
    #   3. Borsh-serialise the body (field order matters — fetch /rollup/schema for layout)
    #   4. Sign the serialised bytes with the Ed25519 private key
    #   5. Embed the signature and return base64(serialised_tx)
    #
    # Required libraries (add to requirements.txt):
    #   borsh-python>=0.1.3
    #   PyNaCl>=1.5.0
    #
    # Example (pseudocode):
    #   import nacl.signing
    #   import borsh
    #   signing_key = nacl.signing.SigningKey(seed_bytes)
    #   tx_bytes = borsh.serialize(TX_SCHEMA, tx_body)
    #   sig = signing_key.sign(tx_bytes).signature
    #   tx_body["signature"] = sig.hex()
    #   return base64.b64encode(borsh.serialize(TX_SCHEMA, tx_body)).decode()

    raise NotImplementedError(
        "Bullet transaction signing is not yet implemented. "
        "See build_bullet_transaction() docstring for implementation guide."
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _backpack_headers(
    api_key: str,
    secret: str,
    instruction: str,
    query_params: Dict[str, Any],
    body: Optional[Dict[str, Any]],
    window: int,
) -> Dict[str, str]:
    """Delegate to the existing Backpack HMAC builder in data_converters."""
    return data_converters.build_authorisation_header(
        api_key=api_key,
        secret=secret,
        query_params=query_params,
        body=body,
        instruction=instruction,
        window=window,
    )
