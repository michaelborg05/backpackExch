from client import api_request
from typing import Dict, Optional, Any
from utils.config import Config
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters
from utils.constants import HttpMethod
from models.trade import (
    OrderExecuteRequest, 
    OrderResponse, 
    OrderCancelRequest,
    FillHistory,
    create_buy,
    create_sell
)

class TradingService:
    config = Config()
    trader_logger = log_manager.get_logger("TradingBuilder")

    def market_buy(self, symbol: str, quantity: str, **kwargs) -> OrderResponse:
            """Execute a market buy order"""
            order = create_buy(symbol, quantity, **kwargs)
            return self.ExecuteOrder(order)

    def market_sell(self, symbol: str, quantity: str, **kwargs) -> OrderResponse:
        """Execute a market sell order"""
        order = create_sell(symbol, quantity, **kwargs)
        return self.ExecuteOrder(order)

    # Limit orders
    def limit_buy(self, symbol: str, price: str, quantity: str, **kwargs) -> OrderResponse:
        """Place a limit buy order"""
        order = create_buy(symbol,  quantity, price=price, **kwargs)
        return self.ExecuteOrder(order)

    def limit_sell(self, symbol: str, price: str, quantity: str, **kwargs) -> OrderResponse:
        """Place a limit sell order"""
        order = create_sell(symbol, quantity, price=price, **kwargs)
        return self.ExecuteOrder(order)

    # Order management
    def cancel_order(self, symbol: str, order_id: Optional[str] = None, client_id: Optional[int] = None):
        """Cancel an order"""
        return self.CancelOrder(symbol, order_id, client_id)

    def get_open_orders(self, symbol: Optional[str] = None):
        """Get open orders"""
        return self.get_open_orders(symbol)

    def cancel_all_orders(self, symbol: str):
        """Cancel all orders for a symbol"""
        return self.cancel_all_orders(symbol)

    def ExecuteOrder(self, order: OrderExecuteRequest) -> OrderResponse:
        url = APIEndpoints.backpack_ExecuteOrder()
        
        # Convert model to dict, excluding None values
        order_data = order.model_dump(by_alias=True, exclude_none=True)
            
        headers=data_converters.build_authorisation_header(
            api_key=self.config.api_key,
            secret=self.config.secret,
            query_params={},
            body=order_data,
            instruction="orderExecute",
            window=60000
        )

        trade = api_request(url, headers,requestType=HttpMethod.POST, body=order_data)
        
        if trade:
            self.trader_logger.debug(f"API call for trade completed successfully\r\n{trade}")
            return OrderResponse(**trade)
        else:
            self.trader_logger.error(f"API call for balances failed\r\n{trade}")

        return None
    """
    def CancelOrder(self, symbol: str, order_id: Optional[str] = None, client_id: Optional[int] = None) -> OrderResponse:
        url = APIEndpoints.backpack_ExecuteOrder()
        # Convert model to dict, excluding None values
        order_data = order.model_dump(by_alias=True, exclude_none=True)
            
        headers=data_converters.build_authorisation_header(
            api_key=config.api_key,
            secret=config.secret,
            query_params={},
            body=order_data,
            instruction="orderExecute",
            window=60000
        )

        trade = api_request(url, headers,requestType="POST")
        
        if trade:
            trader_logger.debug(f"API call for trade completed successfully\r\n{trade}")
            return trade
        else:
            trader_logger.error(f"API call for balances failed\r\n{trade}")

        return None

        """