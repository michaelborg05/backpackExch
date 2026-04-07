from services.client import api_request
from typing import Dict, Optional, Any
from utils.config import Config
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters
from models.balance import BalanceReader
from decimal import Decimal
from models.trading_profile import TradingProfile
from cache.balance_cache import get_balance_cache
from services.profile_manager import get_profile_manager

config = Config()
account_logger = log_manager.get_logger("AccountBuilder")

def get_balances(
    source: str = "API",
    profile: Optional[TradingProfile] = None,
    update_cache: bool = False
) -> Optional[BalanceReader]:
    """
    Get balances for a specific profile or all profiles.
    When fetching all profiles, deduplicates API calls so accounts shared by
    multiple profiles are only queried once.

    Returns:
        BalanceReader for single profile, or Dict[profile_name, BalanceReader] for all profiles
    """
    if profile:
        return _get_profile_balances(profile, source, update_cache)
    else:
        return _get_all_profile_balances(source, update_cache)


def _get_profile_balances(
    profile: TradingProfile,
    source: str = "API",
    update_cache: bool = False
) -> Optional[BalanceReader]:
    """Get balances for a specific profile via the exchange API."""
    url = APIEndpoints.backpack_balances()
    headers = data_converters.build_authorisation_header(
        api_key=profile.api_key,
        secret=profile.secret,
        query_params={},
        body=None,
        instruction="balanceQuery",
        window=60000
    )

    balances = api_request(url, headers)

    if balances:
        account_logger.debug(f"API call for balances completed successfully for profile: {profile.name}")

        balance_reader = BalanceReader(balances)

        if update_cache and isinstance(balance_reader, BalanceReader):
            cache = get_balance_cache()
            balance_dict = _convert_balance_reader_to_dict(balance_reader)
            cache.update_profile_balances(
                profile.name,
                balance_dict,
                account_id=getattr(profile, 'account_id', None)
            )
            account_logger.debug(f"Updated cache for profile: {profile.name} (account_id={profile.account_id})")

        return balance_reader
    else:
        account_logger.error(f"API call for balances failed for profile: {profile.name}")
        return None


def _get_all_profile_balances(
    source: str = "API",
    update_cache: bool = False
) -> Dict[str, BalanceReader]:
    """
    Get balances for all active profiles, deduplicating API calls per account.
    Profiles sharing the same exchange account only trigger one API call; the
    cache is written once (keyed by account) and all sibling profiles are
    registered to that account key.
    """
    profile_manager = get_profile_manager()
    if not profile_manager:
        account_logger.error("Profile manager not initialized")
        return {}

    all_balances = {}
    profiles = profile_manager.get_all_profiles()
    cache = get_balance_cache()

    # Track which account_ids we've already fetched to avoid duplicates
    fetched_account_ids: Dict[int, BalanceReader] = {}  # account_id → BalanceReader

    for profile in profiles:
        account_id = getattr(profile, 'account_id', None)

        if account_id and account_id in fetched_account_ids:
            # Re-use already-fetched balance for this account; just register the mapping
            balance_reader = fetched_account_ids[account_id]
            if update_cache:
                cache.register_profile_account(
                    profile.name,
                    f"account_{account_id}"
                )
            all_balances[profile.name] = balance_reader
            account_logger.debug(
                f"Reusing cached fetch for profile '{profile.name}' (account_id={account_id})"
            )
            continue

        balance_reader = _get_profile_balances(profile, source, update_cache)
        if balance_reader:
            all_balances[profile.name] = balance_reader
            if account_id:
                fetched_account_ids[account_id] = balance_reader

    account_logger.info(
        f"Retrieved balances for {len(all_balances)} profiles "
        f"({len(fetched_account_ids)} unique exchange account(s))"
    )
    return all_balances


def _convert_balance_reader_to_dict(balance_reader: BalanceReader) -> Dict[str, Dict]:
    return balance_reader.to_dict()
