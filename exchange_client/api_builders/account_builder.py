from client import api_request
from typing import Dict, Optional, Any
from utils.config import Config
from exchange_client.models.ticker import BackpackTicker,TickerDepth
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters
from exchange_client.models.balance import BalanceReader

config = Config()
account_logger = log_manager.get_logger("AccountBuilder")

def get_balances() -> Optional[BalanceReader]:
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
        account_logger.info("API call for balances completed successfully")
        return BalanceReader(balances)
        #active_assets = balancelist.get_non_zero_balances()
        #print(balancelist.summary())
    else:
        account_logger.error("API call for balances failed")

    return None
