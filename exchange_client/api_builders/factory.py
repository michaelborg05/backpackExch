"""Adapter factory — returns the correct ExchangeAdapter for a given profile.

Usage:
    from api_builders.factory import get_adapter

    adapter = get_adapter(profile)
    price   = adapter.get_ticker("SOL_USDC")
    balance = adapter.get_balances()
"""
from api_builders.adapters.base import ExchangeAdapter
from models.trading_profile import TradingProfile


def get_adapter(profile: TradingProfile) -> ExchangeAdapter:
    """Return the ExchangeAdapter instance appropriate for *profile*.

    The exchange type is read from profile.exchange_type which is populated
    from exchange_accounts.exchange_type when profiles are loaded from the DB.

    Args:
        profile: TradingProfile pydantic model.

    Returns:
        BackpackAdapter or BulletAdapter instance bound to this profile.

    Raises:
        ValueError: if profile.exchange_type is not recognised.
    """
    exchange_type = getattr(profile, "exchange_type", "backpack") or "backpack"

    if exchange_type == "backpack":
        from api_builders.adapters.backpack import BackpackAdapter
        return BackpackAdapter(profile)

    if exchange_type == "bullet":
        from api_builders.adapters.bullet import BulletAdapter
        return BulletAdapter(profile)

    raise ValueError(
        f"Unknown exchange_type {exchange_type!r} on profile {profile.name!r}. "
        f"Valid options: 'backpack', 'bullet'"
    )
