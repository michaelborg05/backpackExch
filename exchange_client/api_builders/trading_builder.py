from decimal import Decimal, InvalidOperation, ROUND_DOWN
from services.client import api_request
from typing import Dict, Optional, Any
from utils.config import Config
from utils.logging import log_manager
from utils.endpoints import APIEndpoints
from utils import data_converters
from utils.constants import HttpMethod
from services.balance_cache import get_balance_cache
from services.price_cache import get_price_cache
from services.market_info_cache import get_market_info_cache
from utils.constants import Side, OrderType
from utils.data_converters import round_down
from models.webhook import TradingViewAlert,  TradingViewAction
from utils.exceptions import ExchangeAPIError, InvalidQuantityError, InvalidPriceError, InsufficientBalanceError   
from models.trade import (
    OrderExecuteRequest, 
    OrderResponse, 
    OrderCancelRequest,
    FillHistory,
    create_buy,
    create_sell
)
from fastapi import HTTPException
from models.trading_profile import TradingProfile
from utils.config import Config
from db.session import SessionLocal
from db.crud import close_positions_fifo, save_trade, open_position, close_position, get_open_position_for_symbol
from utils.position_calculator import PositionCalculator

class TradingService:
    def __init__(self, profile: TradingProfile):
        self.config = Config()

        self.trader_logger = log_manager.get_logger("TradingService")
        self.balance_cache = get_balance_cache()
        self.price_cache = get_price_cache()
        self.market_info_cache = get_market_info_cache()  

        if profile:
            self.profile = profile  # Store the full profile
            self.trader_logger.info(f"Initialized with profile: {profile.name}")
        else:
            # Create default profile from config
            self.profile = TradingProfile(
                name="default",
                api_key=self.config.api_key,
                secret=self.config.secret
            )
            self.trader_logger.info("Initialized with default config")
            

    def _validate_and_adjust_order(self, order: OrderExecuteRequest, profile_name: str = "default") -> OrderExecuteRequest:
        """
        Validate order against available balance and adjust if needed
        Handles both BUY (checks quote asset) and SELL (checks base asset)
        
        Args:
            order: Order to validate
            
        Returns:
            Adjusted order (or original if no adjustment needed)
            
        Raises:
            ValueError: If order cannot be validated or executed
        """
        # Parse symbol (e.g., "SOL_USDC" -> base="SOL", quote="USDC")
        parts = order.symbol.split("_")
        if len(parts) != 2:
            raise ValueError(f"Invalid symbol format: {order.symbol}")
        
        base_asset, quote_asset = parts
        
        # Determine which asset to check based on order side
        if order.side == Side.ASK:  # SELL - check base asset
            return self._validate_sell_order(order, base_asset, profile_name=profile_name)
        else:  # BID - check quote asset (USDC)
            return self._validate_buy_order(order, base_asset, quote_asset, profile_name=profile_name)


    def _validate_sell_order(self, order: OrderExecuteRequest, base_asset: str, profile_name: str = "default") -> OrderExecuteRequest:
        """
        Validate SELL order against available base asset balance
        
        Args:
            order: Order to validate
            base_asset: Base asset symbol (e.g., "SOL")
            
        Returns:
            Adjusted order if needed
        """
        available = self.balance_cache.get_available_balance(profile_name=profile_name, asset=base_asset)
        # Parse order quantity
        order_qty = self._parse_order_quantity(order.quantity, available, base_asset)
        
        # Validate we have balance data
        if available is None:
            self.trader_logger.warning(
                f"Could not retrieve balance for {profile_name} {base_asset}, proceeding without validation"
            )
            if order_qty is None:
                raise InvalidQuantityError(
                    f"Order quantity '{order.quantity}' requires balance data",
                    quantity=order.quantity,
                    asset=base_asset
                )
            order.quantity = str(order_qty)
            return order
        
        # Check sufficient balance
        if available <= 0:
            raise InsufficientBalanceError(
                f"No available balance for {base_asset}",
                available=available,
                required=order_qty,
                asset=base_asset
            ) 
               
        # If "MAX", use all available with buffer
        if order_qty is None:
            # Apply buffer for fees (0.01% safety margin)
            buffered_qty = available * Decimal("0.9999")
            
            self.trader_logger.info(
                f"MAX sell order: {available} {base_asset} → {buffered_qty} (buffered, will be rounded by market rules)"
            )
            order.quantity = str(buffered_qty)
            return order
        
        # For explicit quantities, check if adjustment needed
        adjusted_qty = self._adjust_quantity_to_balance(order_qty, available, base_asset)
        order.quantity = str(adjusted_qty)
        
        return order

    def _validate_buy_order(
        self, 
        order: OrderExecuteRequest, 
        base_asset: str, 
        quote_asset: str,
        profile_name: str = "default"
    ) -> OrderExecuteRequest:
        """
        Validate BUY order against available quote asset balance (USDC)
        
        Args:
            order: Order to validate
            base_asset: Base asset symbol (e.g., "SOL")
            quote_asset: Quote asset symbol (e.g., "USDC")
            
        Returns:
            Adjusted order if needed
        """
        # Get available quote balance (USDC)
        available_quote = self.balance_cache.get_available_balance(profile_name=profile_name, asset=quote_asset)
        
        if available_quote is None:
            self.trader_logger.warning(
                f"Could not retrieve balance for {quote_asset}, proceeding without validation"
            )
            return order
        
        if available_quote <= 0:
            raise ValueError(f"No available balance for {quote_asset}")
        
        # Get current price
        price = self._get_order_price(order, base_asset, quote_asset)
        
        if price is None:
            self.trader_logger.warning(
                f"Could not retrieve price for {order.symbol}, proceeding without validation"
            )
            return order
        
        # Parse order quantity
        order_qty = self._parse_order_quantity(order.quantity, None, base_asset)
        
        # Calculate required quote amount
        if order_qty is None:  # "MAX" - buy as much as possible
            # Calculate max base quantity we can buy with available quote
            max_base_qty = available_quote / price
            adjusted_qty = self._apply_buffer_and_round(max_base_qty, price)
            
            self.trader_logger.info(
                f"MAX buy order: {available_quote} {quote_asset} @ {price} = {adjusted_qty} {base_asset}"
            )
            order.quantity = str(adjusted_qty)
        else:
            # Check if we have enough quote asset to buy requested quantity
            required_quote = order_qty * price
            
            if required_quote > available_quote:
                self.trader_logger.warning(
                    f"Insufficient {quote_asset} for buy order. "
                    f"Required: {required_quote}, Available: {available_quote}"
                )
                
                # Calculate max we can buy
                max_base_qty = available_quote / price
                adjusted_qty = self._apply_buffer_and_round(max_base_qty, price)
                
                self.trader_logger.info(
                    f"Adjusted buy quantity from {order_qty} to {adjusted_qty} {base_asset}"
                )
                order.quantity = str(adjusted_qty)
        
        return order


    def _get_order_price(
        self, 
        order: OrderExecuteRequest, 
        base_asset: str, 
        quote_asset: str
    ) -> Optional[Decimal]:
        """
        Get price for the order (from order.price or cache)
        
        Args:
            order: Order with optional price
            base_asset: Base asset symbol
            quote_asset: Quote asset symbol
            
        Returns:
            Price as Decimal, or None if not available
        """
        # If limit order, use specified price
        if order.order_type == OrderType.LIMIT and order.price:
            try:
                return Decimal(order.price)
            except:
                self.trader_logger.warning(f"Invalid limit price: {order.price}")
        
        # For market orders, get from cache
        symbol = f"{base_asset}_{quote_asset}"
        cached_price = self.price_cache.get_price(symbol)
        
        if cached_price is None:
            self.trader_logger.warning(f"Price not found in cache for {symbol}")
        
        return cached_price


    def _apply_buffer_and_round(self, quantity: Decimal, price: Decimal) -> Decimal:
        """
        Apply fee buffer and round quantity appropriately
        
        Args:
            quantity: Base quantity
            price: Price per unit
            
        Returns:
            Adjusted and rounded quantity
        """
        # Apply fee buffer (0.05% for safety)
        buffered = quantity * Decimal("0.9995")
        
        # Round based on value size
        total_value = buffered * price
        
        if total_value < Decimal("10"):
            # Small orders: 2-4 decimal places
            return self._round_down(buffered, 4)
        elif total_value < Decimal("100"):
            # Medium orders: 2 decimal places
            return self._round_down(buffered, 2)
        else:
            # Large orders: 1 decimal or whole numbers
            if price > Decimal("100"):
                return self._round_down(buffered, 2)
            else:
                return self._round_down(buffered, 1)


    def _parse_order_quantity(
        self, 
        quantity_str: str, 
        available: Optional[Decimal],
        asset: str
    ) -> Optional[Decimal]:
        """
        Parse order quantity string (handles "MAX" and numeric values)
        
        Args:
            quantity_str: Order quantity as string (e.g., "10", "MAX")
            available: Available balance (can be None)
            asset: Asset symbol for logging
            
        Returns:
            Decimal quantity, or None if "MAX"
            
        Raises:
            ValueError: If quantity is invalid
        """
        # Handle "MAX" case
        if quantity_str.upper() == "MAX":
            return None  # Signal to use maximum possible
        
        # Try to parse as numeric
        try:
            qty = Decimal(quantity_str)
            if qty <= 0:
                raise ValueError(f"Order quantity must be positive: {quantity_str}")
            return qty
        except (ValueError, InvalidOperation):
            raise ValueError(f"Invalid order quantity: {quantity_str}")


    def _adjust_quantity_to_balance(
        self,
        order_qty: Decimal,
        available: Decimal,
        asset: str
    ) -> Decimal:
        """
        Adjust order quantity to available balance if needed (for SELL orders)
        Applies fee buffer when quantity exceeds or equals available balance
        
        NOTE: Does NOT round - rounding is handled by _validate_market_rules
        
        Args:
            order_qty: Requested order quantity
            available: Available balance
            asset: Asset symbol for logging
            
        Returns:
            Adjusted quantity (with fee buffer applied if needed)
        """
        # If requested quantity is safely below balance, no adjustment needed
        # Use a small threshold (0.1%) to avoid adjusting unnecessarily
        if order_qty <= available * Decimal("0.999"):
            return order_qty
        
        # Order quantity equals or exceeds balance - need to adjust
        self.trader_logger.warning(
            f"Order quantity close to or exceeds balance for {asset}. "
            f"Requested: {order_qty}, Available: {available}"
        )
        
        # Apply fee buffer (0.01%)
        adjusted = available * Decimal("0.9999")
        
        self.trader_logger.info(
            f"Adjusted order quantity from {order_qty} to {adjusted} (with fee buffer, will be rounded by market rules)"
        )
        
        return adjusted

    def _round_down(self, value: Decimal, decimals: int) -> Decimal:
        """
        Round down to specified decimal places
        
        Args:
            value: Value to round
            decimals: Number of decimal places
            
        Returns:
            Rounded value
        """
        if decimals == 0:
            return Decimal(int(value))
        
        quantize_str = "0." + "0" * decimals
        return value.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)

    def order_buy(self, symbol: str, quantity: str, price:str = "0",source:str = "MANUAL",profile_name: str = "default", **kwargs) -> OrderResponse:
        """Execute a market buy order"""
        order = create_buy(symbol, quantity, price, **kwargs)
        order = self._validate_and_adjust_order(order, profile_name=profile_name)
        order = self._validate_market_rules(order)
        return self.ExecuteOrder(order, source=source)

    def order_sell(self, symbol: str, quantity: str, price:str = "0", source:str = "MANUAL", profile_name: str = "default",position_id: str =None,**kwargs) -> OrderResponse:
        """Execute a market sell order"""
        order = create_sell(symbol, quantity, price, **kwargs)
        order = self._validate_and_adjust_order(order, profile_name=profile_name)
        order = self._validate_market_rules(order)
        return self.ExecuteOrder(order, source=source, position_id=position_id)

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

    def _validate_market_rules(self, order: OrderExecuteRequest) -> OrderExecuteRequest:
        """
        Validate and adjust order to comply with market rules
        
        Args:
            order: Order to validate
            
        Returns:
            Adjusted order
        """
        market_info = self.market_info_cache.get_market_info(order.symbol)
        
        if market_info is None:
            self.trader_logger.warning(
                f"Market info not available for {order.symbol}, skipping market rules validation"
            )
            return order
        
        # Validate and adjust quantity
        quantity = Decimal(order.quantity)
        
        if quantity <= 0:
            raise InvalidQuantityError(
                "Quantity must be greater than zero",
                quantity=quantity,
                symbol=order.symbol
            )

        # Round to step size
        rounded_qty = market_info.round_quantity(quantity)
        
        if rounded_qty != quantity:
            self.trader_logger.info(
                f"Adjusted quantity from {quantity} to {rounded_qty} to comply with step size {market_info.step_size}"
            )
            quantity = rounded_qty

        if quantity == 0:
            raise InvalidQuantityError(
                f"Quantity rounded to zero due to step size {market_info.step_size}",
                quantity=quantity,
                original_quantity=Decimal(order.quantity),
                step_size=market_info.step_size,
                symbol=order.symbol
            )
                
        # Validate quantity
        is_valid, error_msg = market_info.validate_quantity(quantity)
        if not is_valid:
            raise InvalidQuantityError(
                    error_msg,
                    quantity=quantity,
                    symbol=order.symbol
            )
        order.quantity = str(quantity)
        
        # Validate price (if limit order)
        if order.price and order.price != "0":
            price = Decimal(order.price)
            
            # Round to tick size
            rounded_price = market_info.round_price(price)
            
            if rounded_price != price:
                self.trader_logger.info(
                    f"Adjusted price from {price} to {rounded_price} to comply with tick size {market_info.tick_size}"
                )
                price = rounded_price
            
            # Validate price
            is_valid, error_msg = market_info.validate_price(price)
            if not is_valid:
                raise InvalidPriceError(
                    error_msg,
                    price=price,
                    symbol=order.symbol
                )
            order.price = str(price)
        
        return order

    def ExecuteOrder(self, order: OrderExecuteRequest, source: str = "MANUAL", position_id: str = None) -> OrderResponse:
        url = APIEndpoints.backpack_ExecuteOrder()
        
        # Convert model to dict, excluding None values
        order_data = order.model_dump(by_alias=True, exclude_none=True)
            
        headers=data_converters.build_authorisation_header(
            api_key=self.profile.api_key,
            secret=self.profile.secret,
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
                order_response = OrderResponse(**trade)
                self.trader_logger.info(f"Trade executed: {order_response}")
                # Save to database
                db = SessionLocal()
                try:
                    saved_trade = save_trade(db, order_response, self.profile.name, source)
                    self.trader_logger.info(f"Trade saved to database: ID {saved_trade.id}")
                    # Open position if this is a BUY order
                    if order_response.side.upper() == "BID":
                        # Calculate position prices based on profile settings
                        tp_price, sl_price, trailing_sl_price = PositionCalculator.calculate_position_prices(
                            entry_price=saved_trade.price,
                            side=saved_trade.side,
                            profile=self.profile  # You'll need to store the profile object
                        )
                        
                        # Open the position
                        position = open_position(
                            db=db,
                            trade=saved_trade,
                            tp_price=tp_price,
                            sl_price=sl_price,
                            trailing_sl_price=trailing_sl_price,
                            highest_price=saved_trade.price
                        )
                        
                        self.trader_logger.info(
                            f"Position opened: ID {position.id}, "
                            f"TP: {tp_price}, SL: {sl_price}, Trailing: {trailing_sl_price}"
                        )
                    else:
                        from db.crud import close_positions_fifo
                        if position_id:
                            try:
                                position_id_int = int(position_id)
                                closed_position = close_position(
                                    db=db,
                                    position_id=position_id_int,
                                    sell_trade=saved_trade,
                                    reason=source
                                )

                                closed_positions = [{
                                    'position_id': closed_position.id,
                                    'status': 'FULLY_CLOSED',
                                    'closed_quantity': closed_position.quantity,
                                    'profit': closed_position.profit,
                                    'profit_pct': (
                                        (closed_position.exit_price - closed_position.entry_price)
                                        / closed_position.entry_price
                                    ) * 100
                                }]                                
                                
                                # Calculate P/L for logging
                                entry_price = closed_position.entry_price
                                exit_price = saved_trade.price
                                quantity = saved_trade.quantity
                                profit = (exit_price - entry_price) * quantity
                                profit_pct = ((exit_price - entry_price) / entry_price) * 100
                                
                                self.trader_logger.info(
                                    f"Closed position {position_id}: {closed_position.symbol}, "
                                    f"P/L: ${profit:.2f} ({profit_pct:+.2f}%)"
                                )
                            except ValueError as e:
                                self.trader_logger.error(f"Invalid position_id: {position_id}")
                                # Fall back to FIFO
                                closed_positions = close_positions_fifo(
                                    db=db,
                                    profile_name=self.profile.name,
                                    symbol=saved_trade.symbol,
                                    sell_trade=saved_trade,
                                    reason=source
                                )
                        else:
                            # No specific position - use FIFO
                            closed_positions = close_positions_fifo(
                                db=db,
                                profile_name=self.profile.name,
                                symbol=saved_trade.symbol,
                                sell_trade=saved_trade,
                                reason=source
                            )
                                                    
                        if not closed_positions:
                            self.trader_logger.warning(
                                f"No open positions found for {saved_trade.symbol} to close"
                            )
                        else:
                            # Log details of closed positions
                            total_profit = sum(p['profit'] for p in closed_positions)
                            
                            summary = f"Closed {len(closed_positions)} position(s) for {saved_trade.symbol}:\n"
                            for p in closed_positions:
                                summary += (
                                    f"  - Position {p['position_id']}: {p['status']}, "
                                    f"Qty: {p['closed_quantity']}, "
                                    f"P/L: ${p['profit']:.2f} ({p['profit_pct']:+.2f}%)\n"
                                )
                            summary += f"Total P/L: ${total_profit:.2f}"
                            
                            self.trader_logger.info(summary)
                            order_response.profit = total_profit

                    # Refresh balance cache after trade
                    self._refresh_balance_cache_after_trade(order_response)

                except Exception as db_error:
                    self.trader_logger.error(f"Failed to save trade to database: {db_error}")
                finally:
                    db.close()
                
                return order_response
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
        
    def _refresh_balance_cache_after_trade(self, order_response: OrderResponse):
        """
        Refresh balance cache after a successful trade to ensure 
        subsequent orders have up-to-date balance information
        
        Args:
            order_response: The executed order response
        """
        try:
            from api_builders.account_builder import get_balances
            
            self.trader_logger.info(
                f"Refreshing balance cache after {order_response.side} order for {self.profile.name}"
            )
            
            # Fetch fresh balances for this profile and update cache
            get_balances(
                source="TradingService",
                profile=self.profile,
                update_cache=True
            )
            
            self.trader_logger.debug(
                f"Balance cache refreshed successfully for {self.profile.name}"
            )
            
        except Exception as e:
            # Don't fail the trade if cache refresh fails
            self.trader_logger.warning(
                f"Failed to refresh balance cache after trade: {e}. "
                "Cache will be updated on next monitoring cycle."
            )        

async def process_tradingview_alert(trading: TradingService, alert: TradingViewAlert, profile_name: str, source: str = "WEBHOOK") -> Optional[OrderResponse]:
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

    # if alert.quote_quantity:
    #     kwargs['quote_quantity'] = alert.quote_quantity

    # if alert.stop_loss:
    #     kwargs['stop_loss_trigger_price'] = alert.stop_loss

    # if alert.take_profit:
    #     kwargs['take_profit_trigger_price'] = alert.take_profit

    # if alert.post_only:
    #     kwargs['post_only'] = alert.post_only

    # if alert.reduce_only:
    #     kwargs['reduce_only'] = alert.reduce_only

    # Execute order based on action
    if alert.action == TradingViewAction.BUY:
        if alert.price and alert.price != "0":
            # Limit buy
            return trading.order_buy(
                symbol=alert.symbol,
                price=alert.price,
                quantity=alert.quantity,
                source=source,
                profile_name=profile_name,
                **kwargs
            )
        else:
            # Market buy
            return trading.order_buy(
                symbol=alert.symbol,
                quantity=alert.quantity,
                source=source,
                profile_name=profile_name,
                **kwargs
            )

    elif alert.action == TradingViewAction.SELL:
        if alert.price and alert.price != "0":
            # Limit sell
            return trading.order_sell(
                symbol=alert.symbol,
                price=alert.price,
                quantity=alert.quantity,
                source=source,
                profile_name=profile_name,
                **kwargs
            )
        else:
            # Market sell
            return trading.order_sell(
                symbol=alert.symbol,
                quantity=alert.quantity,
                source=source,
                profile_name=profile_name,
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
    
