"""
Data models for trade information
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from decimal import Decimal
from utils.constants import (
    Side, 
    OrderType, 
    TimeInForce, 
    SelfTradePrevention,
    OrderStatus,
    SlippageToleranceType,
    MarketType,
    ExpiryReason,
    SystemOrderType
)

class OrderRequest(BaseModel):
    symbol: str
    quantity: str
    side: str  # "buy" or "sell"
    profile_name: str = "default"
    price: str = None

# Request Models
class OrderExecuteRequest(BaseModel):
    """Model for executing an order on Backpack Exchange"""
    symbol: str = Field(..., description="The market for the order (e.g., 'BTC_USDC')")
    side: Side = Field(..., description="Order side (Bid or Ask)")
    order_type: OrderType = Field(..., alias="orderType", description="Order type (Market or Limit)")
    
    # Optional fields
    quantity: Optional[str] = Field(None, description="Order quantity (required for limit orders)")
    quote_quantity: Optional[str] = Field(None, alias="quoteQuantity", description="Quote quantity for market orders")
    price: Optional[str] = Field(None, description="Limit price (required for limit orders)")
    
    # Advanced order options
    client_id: Optional[int] = Field(None, alias="clientId", description="Custom order ID")
    post_only: Optional[bool] = Field(None, alias="postOnly", description="Post only (limit orders)")
    reduce_only: Optional[bool] = Field(None, alias="reduceOnly", description="Reduce only (futures)")
    time_in_force: Optional[TimeInForce] = Field(None, alias="timeInForce")
    self_trade_prevention: Optional[SelfTradePrevention] = Field(None, alias="selfTradePrevention")
    
    # Stop loss / Take profit
    stop_loss_trigger_price: Optional[str] = Field(None, alias="stopLossTriggerPrice")
    stop_loss_limit_price: Optional[str] = Field(None, alias="stopLossLimitPrice")
    stop_loss_trigger_by: Optional[str] = Field(None, alias="stopLossTriggerBy")
    take_profit_trigger_price: Optional[str] = Field(None, alias="takeProfitTriggerPrice")
    take_profit_limit_price: Optional[str] = Field(None, alias="takeProfitLimitPrice")
    take_profit_trigger_by: Optional[str] = Field(None, alias="takeProfitTriggerBy")
    
    
    # Slippage
    slippage_tolerance: Optional[str] = Field(None, alias="slippageTolerance")
    slippage_tolerance_type: Optional[SlippageToleranceType] = Field(None, alias="slippageToleranceType")
    
    class Config:
        populate_by_name = True
        use_enum_values = True


class OrderCancelRequest(BaseModel):
    """Model for canceling an order"""
    symbol: str = Field(..., description="Market symbol")
    order_id: Optional[str] = Field(None, alias="orderId", description="Order ID to cancel")
    client_id: Optional[int] = Field(None, alias="clientId", description="Client ID to cancel")

    class Config:
        populate_by_name = True


class OrderCancelAllRequest(BaseModel):
    """Model for canceling all orders on a symbol"""
    symbol: str = Field(..., description="Market symbol")
    order_type: Optional[str] = Field(None, alias="orderType", description="Type of orders to cancel")

    class Config:
        populate_by_name = True


# Response Models
class OrderResponse(BaseModel):
    """Model for order response"""
    id: str = Field(..., description="Order ID")
    order_type: OrderType = Field(..., alias="orderType")
    symbol: str
    side: Side
    status: OrderStatus
    
    quantity: Optional[str] = None
    quote_quantity: Optional[str] = Field(None, alias="quoteQuantity")
    price: Optional[str] = None
    
    executed_quantity: str = Field(..., alias="executedQuantity")
    executed_quote_quantity: str = Field(..., alias="executedQuoteQuantity")
    
    client_id: Optional[int] = Field(None, alias="clientId")
    created_at: int = Field(..., alias="createdAt", description="Creation timestamp in ms")
    
    reduce_only: Optional[bool] = Field(None, alias="reduceOnly")
    time_in_force: Optional[TimeInForce] = Field(None, alias="timeInForce")
    self_trade_prevention: Optional[SelfTradePrevention] = Field(None, alias="selfTradePrevention")
    
    # Conditional fields
    trigger_price: Optional[str] = Field(None, alias="triggerPrice")
    trigger_by: Optional[str] = Field(None, alias="triggerBy")
    trigger_quantity: Optional[str] = Field(None, alias="triggerQuantity")
    triggered_at: Optional[int] = Field(None, alias="triggeredAt")
    
    # TP/SL fields
    stop_loss_trigger_price: Optional[str] = Field(None, alias="stopLossTriggerPrice")
    stop_loss_limit_price: Optional[str] = Field(None, alias="stopLossLimitPrice")
    stop_loss_trigger_by: Optional[str] = Field(None, alias="stopLossTriggerBy")
    take_profit_trigger_price: Optional[str] = Field(None, alias="takeProfitTriggerPrice")
    take_profit_limit_price: Optional[str] = Field(None, alias="takeProfitLimitPrice")
    take_profit_trigger_by: Optional[str] = Field(None, alias="takeProfitTriggerBy")
    
    related_order_id: Optional[str] = Field(None, alias="relatedOrderId")
    strategy_id: Optional[str] = Field(None, alias="strategyId")
    
    slippage_tolerance: Optional[str] = Field(None, alias="slippageTolerance")
    slippage_tolerance_type: Optional[SlippageToleranceType] = Field(None, alias="slippageToleranceType")

    entry_price: Optional[str] = Field(None, alias="entry_price")
    exit_price: Optional[str] = Field(None, alias="exit_price")
    profit: Optional[str] = Field(None, alias="profit")

    class Config:
        populate_by_name = True
        use_enum_values = True


class FillHistory(BaseModel):
    """Model for fill/trade history"""
    trade_id: int = Field(..., alias="tradeId")
    order_id: str = Field(..., alias="orderId")
    symbol: str
    side: Side
    price: str
    quantity: str
    fee: str
    fee_symbol: str = Field(..., alias="feeSymbol")
    is_maker: bool = Field(..., alias="isMaker")
    timestamp: str
    client_id: Optional[str] = Field(None, alias="clientId")
    system_order_type: Optional[str] = Field(None, alias="systemOrderType")

    class Config:
        populate_by_name = True


class Position(BaseModel):
    """Open position"""
    id: str
    symbol: str
    net_quantity: str = Field(..., alias="netQuantity")
    mark_price: str = Field(..., alias="markPrice")
    net_exposure_quantity: str = Field(..., alias="netExposureQuantity")
    net_exposure_notional: str = Field(..., alias="netExposureNotional")
    imf: str
    mmf: str

    class Config:
        populate_by_name = True


# Helper functions for creating common orders
def create_buy(symbol: str, quantity: str = None, price: str = None, **kwargs) -> OrderExecuteRequest:
    """
    Create a buy order (market or limit based on price)
    
    Args:
        symbol: Trading pair (e.g., "SOL_USDC")
        quantity: Base asset quantity (omit if using quoteQuantity)
        price: Limit price (omit or "0" for market order)
        **kwargs: Additional order parameters
    """
    params = {
        "symbol": symbol,
        "side": Side.BID,
        "quantity": quantity,
    }
    
    if price and price != "0":
        params["order_type"] = OrderType.LIMIT
        params["price"] = price
    else:
        params["order_type"] = OrderType.MARKET
        
    params.update(kwargs)
    return OrderExecuteRequest(**params)

def create_sell(symbol: str, quantity: str = None, price: str = None, **kwargs) -> OrderExecuteRequest:
    """
    Create a sell order (market or limit based on price)
    
    Args:
        symbol: Trading pair (e.g., "SOL_USDC")
        quantity: Base asset quantity (omit if using quoteQuantity)
        price: Limit price (omit or "0" for market order)
        **kwargs: Additional order parameters
    """
    params = {
        "symbol": symbol,
        "side": Side.ASK,
        "quantity": quantity,
    }
    
    if price and price != "0":
        params["order_type"] = OrderType.LIMIT
        params["price"] = price
    else:
        params["order_type"] = OrderType.MARKET
    
    params.update(kwargs)
    return OrderExecuteRequest(**params)


class OrderHistoryResponse(BaseModel):
    id: str
    createdAt: str

    executedQuantity: Optional[Decimal] = None
    executedQuoteQuantity: Optional[Decimal] = None

    expiryReason: Optional[ExpiryReason] = None

    orderType: OrderType
    postOnly: Optional[bool] = None

    price: Optional[Decimal] = None
    quantity: Optional[Decimal] = None
    quoteQuantity: Optional[Decimal] = None

    selfTradePrevention: SelfTradePrevention

    status: OrderStatus
    side: Side

    stopLossTriggerPrice: Optional[str] = None
    stopLossLimitPrice: Optional[Decimal] = None
    stopLossTriggerBy: Optional[str] = None

    symbol: str

    takeProfitTriggerPrice: Optional[str] = None
    takeProfitLimitPrice: Optional[Decimal] = None
    takeProfitTriggerBy: Optional[str] = None

    timeInForce: TimeInForce

    triggerBy: Optional[str] = None
    triggerPrice: Optional[str] = None
    triggerQuantity: Optional[str] = None

    clientId: Optional[int] = None

    systemOrderType: Optional[SystemOrderType] = None
    strategyId: Optional[str] = None

    slippageTolerance: Optional[Decimal] = None
    slippageToleranceType: Optional[SlippageToleranceType] = None

    entry_price: Optional[str] = Field(None, alias="entry_price")
    exit_price: Optional[str] = Field(None, alias="exit_price")
    profit: Optional[str] = Field(None, alias="profit")
