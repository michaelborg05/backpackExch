from services.client import api_request
from typing import Dict, Optional, Any
from utils.config import Config
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters
from utils.constants import HttpMethod
from services.balance_cache import get_balance_cache
from decimal import Decimal
from utils.constants import Side
from utils.data_converters import round_down
from models.webhook import TradingViewAlert,  TradingViewAction
from utils.exceptions import ExchangeAPIError   
from models.trade import (
    OrderExecuteRequest, 
    OrderResponse, 
    OrderCancelRequest,
    FillHistory,
    create_buy,
    create_sell
)
from fastapi import HTTPException

class TradingService:
    def __init__(self):
        self.config = Config()
        self.trader_logger = log_manager.get_logger("TradingService")
        self.balance_cache = get_balance_cache()

    def _validate_and_adjust_order(self, order: OrderExecuteRequest) -> OrderExecuteRequest:
        """
        Validate order against available balance and adjust if needed
        
        Args:
            order: Order to validate
            
        Returns:
            Adjusted order (or original if no adjustment needed)
        """
        # Only validate sell orders (Ask side)
        if order.side != Side.ASK:
            return order
        
        adjusted_qty = None
        # Extract base asset from symbol (e.g., "SOL_USDC" -> "SOL")
        base_asset = order.symbol.split("_")[0]
        
        # Get available balance
        available = self.balance_cache.get_available_balance(base_asset)
        
        if available is None:
            
            self.trader_logger.warning(
                f"Could not retrieve balance for {base_asset}, proceeding without validation"
            )
            try:
                order_qty = Decimal(order.quantity)
                if order_qty <= 0:
                    raise ValueError(f"Invalid order quantity: {order.quantity}")
            except:
                self.trader_logger.warning(
                    f"Invalid order quantity: {order.quantity} for {base_asset}. "
                    f"Proceeding without validation"
                )
                raise ValueError(f"Order quantity {order.quantity} must be numeric. Unable to validate order.")
            return order
        
        else:
            if available <= 0:
                self.trader_logger.warning(
                    f"No available balance for {base_asset}, cannot proceed with sell order"
                )
                raise ValueError(f"Insufficient balance for {base_asset}")
            try:

                order_qty = Decimal(order.quantity)
                # Check if we have enough balance
                if order_qty > available:
                    self.trader_logger.warning(
                        f"Insufficient balance for {base_asset}. "
                        f"Requested: {order_qty}, Available: {available}"
                    )
                    
                    # Adjust to max available (with small buffer for fees)
                    adjusted_qty = available * Decimal("0.9999")  # 0.1% buffer
                    if adjusted_qty < Decimal("10"):
                        adjusted_qty = round_down(adjusted_qty,2)
                    else:
                        adjusted_qty = round_down(adjusted_qty,0)
                    self.trader_logger.info(
                        f"Adjusting order quantity from {order_qty} to {adjusted_qty}"
                    )
            except:
                adjusted_qty = available * Decimal("0.9999")  # 0.1% buffer
                if adjusted_qty < Decimal("10"):
                    adjusted_qty = round_down(adjusted_qty,2)
                else:
                    adjusted_qty = int(adjusted_qty)
                self.trader_logger.warning(
                    f"Invalid order quantity: {order.quantity} for {base_asset}. "
                    f"Adjusting to available amount: {adjusted_qty}"
                )

                #raise ValueError(f"Invalid order quantity: {order.quantity}")
           
            # Create adjusted order
        if adjusted_qty is not None:
            order.quantity = str(adjusted_qty)

        return order

    def order_buy(self, symbol: str, quantity: str, price:str = "0",**kwargs) -> OrderResponse:
        """Execute a market buy order"""
        order = create_buy(symbol, quantity, price, **kwargs)
        #order = self._validate_and_adjust_order(order)
        return self.ExecuteOrder(order)

    def order_sell(self, symbol: str, quantity: str, price:str = "0", **kwargs) -> OrderResponse:
        """Execute a market sell order"""
        order = create_sell(symbol, quantity, price, **kwargs)
        order = self._validate_and_adjust_order(order)
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

        try:
            self.trader_logger.info(f"Debug Trade Request: \r\n{order_data}")
            trade = api_request(url, headers,requestType=HttpMethod.POST, body=order_data)

            if trade:
                self.trader_logger.debug(f"API call for trade completed successfully\r\n{trade}")
                return OrderResponse(**trade)
            else:
                self.trader_logger.error(f"API call for trade failed\r\n{trade}")
                raise ExchangeAPIError("Empty response from exchange")
        except ExchangeAPIError as e:
            # Log and re-raise as HTTPException for FastAPI
            self.trader_logger.error(f"Exchange API error: {e.message}")
            raise HTTPException(
                status_code=e.status_code or 500,
                detail=f"Exchange API error: {e.message}"
            )
        except Exception as e:
            # Handle other errors
            self.trader_logger.error(f"Unexpected error: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Trading service error: {str(e)}"
            )
    
async def process_tradingview_alert(trading: TradingService, alert: TradingViewAlert):
    """
    Process TradingView alert and execute appropriate trade

    Args:
        trading: TradingService instance
        alert: TradingView alert data

    Returns:
        OrderResponse or None
    """

    # Validate required fields
    if not alert.quantity and not alert.quote_quantity:
        raise ValueError("Either quantity or quoteQuantity must be provided")

    # Build order kwargs
    kwargs = {}

    if alert.quote_quantity:
        kwargs['quote_quantity'] = alert.quote_quantity

    if alert.stop_loss:
        kwargs['stop_loss_trigger_price'] = alert.stop_loss

    if alert.take_profit:
        kwargs['take_profit_trigger_price'] = alert.take_profit

    if alert.post_only:
        kwargs['post_only'] = alert.post_only

    if alert.reduce_only:
        kwargs['reduce_only'] = alert.reduce_only

    # Execute order based on action
    if alert.action == TradingViewAction.BUY:
        if alert.price and alert.price != "0":
            # Limit buy
            return trading.order_buy(
                symbol=alert.symbol,
                price=alert.price,
                quantity=alert.quantity,
                **kwargs
            )
        else:
            # Market buy
            return trading.order_buy(
                symbol=alert.symbol,
                quantity=alert.quantity,
                **kwargs
            )

    elif alert.action == TradingViewAction.SELL:
        if alert.price and alert.price != "0":
            # Limit sell
            return trading.order_sell(
                symbol=alert.symbol,
                price=alert.price,
                quantity=alert.quantity,
                **kwargs
            )
        else:
            # Market sell
            return trading.order_sell(
                symbol=alert.symbol,
                quantity=alert.quantity,
                **kwargs
            )

    elif alert.action in [TradingViewAction.CLOSE, TradingViewAction.CLOSE_LONG, TradingViewAction.CLOSE_SHORT]:
        # Cancel all open orders and close position
        trading.cancel_all_orders(alert.symbol)
        
        # Get current position and close it
        # You'll need to implement position fetching and closing logic
        return None

    else:
        raise ValueError(f"Unknown action: {alert.action}")

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