from services.client import api_request
from typing import Dict, Optional, Any
from utils.config import Config
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters
from models.balance import BalanceReader
from decimal import Decimal

config = Config()
account_logger = log_manager.get_logger("AccountBuilder")

def _is_zero_balance(balance_data: dict) -> bool:
    """Check if all balance fields are zero"""
    try:
        total = sum(
            Decimal(balance_data.get(field, "0"))
            for field in ["available", "locked", "staked"]
        )
        return total == 0
    except:
        return False
    
def get_balances(source: str = "API") -> Optional[BalanceReader]:
    url = APIEndpoints.backpack_balances()
    headers=data_converters.build_authorisation_header(
        api_key=config.api_key,
        secret=config.secret,
        query_params={},
        body=None,
        instruction="balanceQuery",
        window=60000
    )

    balances = api_request(url, headers)
    
    if balances:
        account_logger.debug("API call for balances completed successfully")
        
        # Filter out zero balances
        filtered_balances = {
            asset: balance_data
            for asset, balance_data in balances.items()
            if not _is_zero_balance(balance_data)
        }
        
        if len(filtered_balances) < len(balances):
            account_logger.debug(
                f"Filtered out {len(balances) - len(filtered_balances)} zero balance assets"
            )
        if source == "API":
            return filtered_balances
        else:
            return BalanceReader(filtered_balances)
        #active_assets = balancelist.get_non_zero_balances()
        #print(balancelist.summary())
    else:
        account_logger.error("API call for balances failed")
        return None
