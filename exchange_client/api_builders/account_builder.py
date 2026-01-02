from services.client import api_request
from typing import Dict, Optional, Any
from utils.config import Config
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters
from models.balance import BalanceReader
from decimal import Decimal
from models.trading_profile import TradingProfile
from services.balance_cache import get_balance_cache
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
    
    Args:
        source: Source identifier for logging
        profile: Specific profile to get balances for. If None, gets all profiles
        update_cache: If True, updates the balance cache with results
    
    Returns:
        BalanceReader for single profile, or Dict[profile_name, BalanceReader] for all profiles
    """
    if profile:
        # Get balances for specific profile
        return _get_profile_balances(profile, source, update_cache)
    else:
        # Get balances for all active profiles
        return _get_all_profile_balances(source, update_cache)
    

def _get_profile_balances(
    profile: TradingProfile,
    source: str = "API",
    update_cache: bool = False
) -> Optional[BalanceReader]:
    """Get balances for a specific profile"""
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
        
        # Update cache if requested
        if update_cache and isinstance(balance_reader, BalanceReader):
            cache = get_balance_cache()
            balance_dict = _convert_balance_reader_to_dict(balance_reader)
            cache.update_profile_balances(profile.name, balance_dict)
            account_logger.debug(f"Updated cache for profile: {profile.name}")
        
        return balance_reader
    else:
        account_logger.error(f"API call for balances failed for profile: {profile.name}")
        return None

def _get_all_profile_balances(
    source: str = "API",
    update_cache: bool = False
) -> Dict[str, BalanceReader]:
    """Get balances for all active profiles"""
    profile_manager = get_profile_manager()
    if not profile_manager:
        account_logger.error("Profile manager not initialized")
        return {}
    
    all_balances = {}
    profiles = profile_manager.get_all_profiles()
    
    for profile in profiles:
        balances = _get_profile_balances(profile, source, update_cache)
        if balances:
            all_balances[profile.name] = balances
    
    account_logger.info(f"Retrieved balances for {len(all_balances)} profiles")
    return all_balances


def _convert_balance_reader_to_dict(balance_reader: BalanceReader) -> Dict[str, Dict]:
    return balance_reader.to_dict()
