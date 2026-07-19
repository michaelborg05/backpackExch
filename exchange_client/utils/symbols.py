"""Canonical symbol normalisation.

The system keys everything — profiles, positions, monitored_symbols,
trend_analysis_log — on the Backpack spot name, e.g. "SOL_USDC". Data can
arrive labelled a dozen other ways depending on which venue and quote asset the
source happens to be using:

    SOLUSDT   SOLUSDC   SOL_USDT   SOL/USDC   BINANCE:SOLUSDT   sol-usdc

All of them mean the same instrument for signalling purposes — the quote asset
is a ~0.06% basis, not a different market. normalize_symbol() collapses them to
the canonical form so a data-source change can never silently orphan a symbol.

Why this exists as server-side code even though the Pine script already
normalises: the Pine script uses unanchored str.replace, which would corrupt any
base asset containing "USD" (e.g. a hypothetical USDX pair -> "X_USDC"), and it
only protects the TradingView path. This is anchored on the suffix and applies
to every ingest path.
"""
from __future__ import annotations

from typing import Optional

CANONICAL_QUOTE = "USDC"

# Longest first so USDT/USDC are stripped before the shorter USD.
_QUOTES = ("USDT", "USDC", "USDD", "FDUSD", "BUSD", "USD", "PERP")

# Bases that legitimately end in one of the quote strings would be corrupted by
# naive suffix stripping. None are traded today; listed so the guard is explicit.
_PROTECTED_BASES = {"USDC", "USDT", "BUSD", "FDUSD", "PAXG"}


def normalize_symbol(raw: Optional[str], canonical_quote: str = CANONICAL_QUOTE) -> Optional[str]:
    """Collapse any venue/quote spelling of a symbol to the canonical form.

    >>> normalize_symbol("SOLUSDT")
    'SOL_USDC'
    >>> normalize_symbol("BINANCE:SOL/USDT")
    'SOL_USDC'
    >>> normalize_symbol("SOL_USDC")
    'SOL_USDC'
    >>> normalize_symbol("PAXGUSDT")
    'PAXG_USDC'

    Returns None for input that cannot be resolved to a base asset, so callers
    can reject rather than silently inventing a symbol.
    """
    if not raw:
        return None

    s = raw.strip().upper()
    if not s:
        return None

    # Venue prefix: "BINANCE:SOLUSDT", "COINBASE:SOL-USD"
    if ":" in s:
        s = s.split(":", 1)[1]

    # Separators: SOL/USDT, SOL-USDC, SOL_USDC
    for sep in ("/", "-", "_"):
        s = s.replace(sep, " ")
    parts = [p for p in s.split() if p]
    if not parts:
        return None

    if len(parts) >= 2:
        # Already separated: take the first token as the base. Trailing tokens
        # are the quote and/or contract-type markers (PERP).
        base = parts[0]
    else:
        token = parts[0]
        if token in _PROTECTED_BASES:
            base = token
        else:
            base = token
            for q in _QUOTES:
                if token.endswith(q) and len(token) > len(q):
                    base = token[: -len(q)]
                    break

    base = base.strip()
    if not base:
        return None
    return f"{base}_{canonical_quote}"


def base_asset(raw: Optional[str]) -> Optional[str]:
    """Return just the base asset, e.g. "SOLUSDT" -> "SOL"."""
    canon = normalize_symbol(raw)
    return canon.rsplit("_", 1)[0] if canon else None


def to_venue_symbol(canonical: str, quote: str) -> Optional[str]:
    """Render a canonical symbol for a venue using `quote`, e.g. -> "SOLUSDT"."""
    base = base_asset(canonical)
    return f"{base}{quote.upper()}" if base else None
