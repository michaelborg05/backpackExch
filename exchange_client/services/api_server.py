# api_server.py
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.responses import JSONResponse
from typing import Optional
import hmac
import hashlib
from contextlib import asynccontextmanager
from models.webhook import TradingViewAlert, WebhookResponse, TradingViewAction
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price, TickerRequest, UpdateTickersRequest
from models.trade import OrderRequest
from api_builders.trading_builder import TradingService
from services.monitoring_service import MonitoringService
from services.balance_cache import get_balance_cache
from services.telegram_listener import get_telegram_listener
from utils.config import Config
from utils.logging import log_manager
from utils.security import (
    require_read_permission,
    require_trade_permission,
    require_admin_permission,
    require_webhook_permission,
    check_rate_limit
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events - runs on startup and shutdown"""
    global telegram
    
    # Startup
    telegram = get_telegram_listener()
    if telegram:
        telegram.send_message_sync("🚀 API Started")
    
    yield  # Application runs here
    
    # Shutdown
    if telegram:
        telegram.send_message_sync("🛑 API Shutting Down")


app = FastAPI(title="Trading API", lifespan=lifespan)
config = Config()
webhook_logger = log_manager.get_logger("Webhook")

WEBHOOK_SECRET = config.webhook_secret if hasattr(config, 'webhook_secret') else None

# Global reference to monitoring service (injected from main.py)
_monitoring_service: Optional[MonitoringService] = None

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Catches ALL HTTPExceptions across the entire app
    Sends Telegram notification automatically
    """
    # Send Telegram notification for errors
    if telegram and exc.status_code >= 400:
        telegram.send_error_notification(
            error_type=f"HTTP {exc.status_code}",
            error_message=exc.detail,
            endpoint=f"{request.method} {request.url.path}",
            details={
                "status_code": exc.status_code,
                "client": request.client.host if request.client else "unknown"
            }
        )
    
    # Return standard JSON response
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

def verify_webhook_signature(payload: str, signature: str, secret: str) -> bool:
    """
    Verify webhook signature (optional security measure)
    
    Args:
        payload: Raw webhook payload
        signature: Signature from header
        secret: Shared secret
    
    Returns:
        True if signature is valid
    """
    if not secret:
        return True  # Skip verification if no secret configured
    
    expected_signature = hmac.new(
        secret.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)


def set_monitoring_service(service: MonitoringService):
    """Set the monitoring service instance (called from main.py)"""
    global _monitoring_service
    _monitoring_service = service

def get_monitoring_service() -> MonitoringService:
    """Get the monitoring service instance"""
    if _monitoring_service is None:
        raise HTTPException(
            status_code=503, 
            detail="Monitoring service not initialized"
        )
    return _monitoring_service


# Public endpoints (no auth)
@app.get("/health")
def health_check():
    """Public health check"""
    return {"status": "healthy"}

@app.get("/webhook/test")
def test_webhook():
    """Test endpoint to verify webhook is accessible"""
    """Public test endpoint"""
    return {
        "status": "ok",
        "message": "Webhook endpoint is accessible",        
    }

#Read only endpoints
@app.get("/monitoring/status", dependencies=[Depends(require_read_permission)])
def get_monitoring_status():
    """Get monitoring service status"""
    service = get_monitoring_service()
    return service.get_status()

@app.get("/monitoring/tickers", dependencies=[Depends(require_read_permission)])
def get_tickers():
    """Get list of monitored tickers"""
    service = get_monitoring_service()
    return {"tickers": service.tickers}

@app.get("/price/{symbol}", dependencies=[Depends(require_read_permission)])
def price_endpoint(symbol: str):
    try:
        price = get_price(symbol)
        return {"symbol": symbol, "price": price}
    except Exception as e:
        return {"error": str(e)}, 500

@app.get("/balances", dependencies=[Depends(require_read_permission)])
def balance_endpoint():
    """Get account balances"""
    try:
        balances = get_balances()
        return balances if balances else {}
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/balances/cached", dependencies=[Depends(require_read_permission)])
def get_cached_balances():
    """Get balances from cache (fast, no API call)"""
    cache = get_balance_cache()
    balances = cache.get_all_balances()
    
    if balances is None:
        return {
            "error": "Balance cache is empty or stale",
            "cache_info": cache.get_cache_info()
        }
    
    return {
        "balances": balances,
        "cache_info": cache.get_cache_info()
    }


@app.get("/balances/cached/{asset}", dependencies=[Depends(require_read_permission)])
def get_cached_asset_balance(asset: str):
    """Get balance for specific asset from cache"""
    cache = get_balance_cache()
    balance = cache.get_available_balance(asset)
    
    if balance is None:
        return {
            "error": f"Balance for {asset} not found or cache is stale",
            "cache_info": cache.get_cache_info()
        }
    
    return {
        "asset": asset,
        "available": str(balance),
        "cache_info": cache.get_cache_info()
    }

#Requires trade permission
@app.post("/monitoring/add-ticker", dependencies=[Depends(require_trade_permission), Depends(check_rate_limit)])
def add_ticker(request: TickerRequest):
    """Add a ticker to monitor"""
    service = get_monitoring_service()
    service.add_ticker(request.ticker)
    return {
        "message": f"Added ticker {request.ticker}",
        "tickers": service.tickers
    }

@app.post("/monitoring/remove-ticker", dependencies=[Depends(require_trade_permission), Depends(check_rate_limit)])
def remove_ticker(request: TickerRequest):
    """Remove a ticker from monitoring"""
    service = get_monitoring_service()
    service.remove_ticker(request.ticker)
    return {
        "message": f"Removed ticker {request.ticker}",
        "tickers": service.tickers
    }


@app.post("/monitoring/stop", dependencies=[Depends(require_trade_permission), Depends(check_rate_limit)])
def stop_monitoring():
    """Stop the monitoring service"""
    service = get_monitoring_service()
    service.stop()
    return {"message": "Monitoring stopped", "status": service.get_status()}


@app.post("/monitoring/start", dependencies=[Depends(require_trade_permission), Depends(check_rate_limit)])
def start_monitoring():
    """Start the monitoring service"""
    service = get_monitoring_service()
    service.start()
    return {"message": "Monitoring started", "status": service.get_status()}


@app.put("/monitoring/tickers", dependencies=[Depends(require_trade_permission), Depends(check_rate_limit)])
def update_tickers(request: UpdateTickersRequest):
    """Replace the entire list of monitored tickers"""
    service = get_monitoring_service()
    service.tickers = request.tickers
    return {
        "message": "Tickers updated",
        "tickers": service.tickers
    }

@app.post("/order", dependencies=[Depends(require_trade_permission), Depends(check_rate_limit)])
def place_order(
    request: OrderRequest
):
    trading: TradingService = TradingService()  
    """Place an order"""
    try:
        if request.side.lower() == "buy":
            result = trading.order_buy(request.symbol, request.quantity)
        elif request.side.lower() == "sell":
            result = trading.order_sell(request.symbol, request.quantity)
        else:
            raise HTTPException(status_code=400, detail="Side must be 'buy' or 'sell'")
        
        if telegram:
            telegram.send_order_notification(
                order_type="Market",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                order_id=result.id
            )
        return result.model_dump()
    except Exception as e:
        if telegram:
            telegram.send_error_notification(
                error_type="Order Failed",
                error_message=str(e),
                endpoint="POST /order"
            )
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/webhook/tradingview", dependencies=[Depends(require_webhook_permission)], response_model=WebhookResponse)
async def tradingview_webhook(
    alert: TradingViewAlert,
    request: Request,
    x_signature: Optional[str] = Header(None)
):
    """
    Receive and process TradingView webhook alerts
    
    TradingView Alert Message Format (JSON):
    {
        "action": "buy",
        "symbol": "SOL_USDC",
        "price": "150.00",
        "quantity": "10",
        "secret": "your_webhook_secret"
    }
    """
    try:
        webhook_logger.info(f"Received TradingView alert: {alert.action} {alert.symbol}")
        
        # Verify webhook secret (from payload)
        if WEBHOOK_SECRET and alert.secret != WEBHOOK_SECRET:
            webhook_logger.warning("Invalid webhook secret")
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        
        # Optional: Verify signature from header (if you implement it in TradingView)
        # body = await request.body()
        # if x_signature and not verify_webhook_signature(body.decode(), x_signature, WEBHOOK_SECRET):
        #     raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Initialize trading service
        trading = TradingService()
        
        # Process alert based on action
        result = await process_tradingview_alert(trading, alert)
        
        webhook_logger.info(f"Alert processed successfully: {result}")
        
        return WebhookResponse(
            success=True,
            message=f"Order executed: {alert.action} {alert.symbol}",
            order_id=result.id if result else None,
            details={
                "action": alert.action,
                "symbol": alert.symbol,
                "executed_quantity": result.executed_quantity if result else None,
                "status": result.status if result else None
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        webhook_logger.error(f"Error processing webhook: {e}", exc_info=True)
        return WebhookResponse(
            success=False,
            message=f"Error: {str(e)}",
            details={"error": str(e)}
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
            return trading.limit_buy(
                symbol=alert.symbol,
                price=alert.price,
                quantity=alert.quantity,
                **kwargs
            )
        else:
            # Market buy
            return trading.market_buy(
                symbol=alert.symbol,
                quantity=alert.quantity,
                **kwargs
            )
    
    elif alert.action == TradingViewAction.SELL:
        if alert.price and alert.price != "0":
            # Limit sell
            return trading.limit_sell(
                symbol=alert.symbol,
                price=alert.price,
                quantity=alert.quantity,
                **kwargs
            )
        else:
            # Market sell
            return trading.market_sell(
                symbol=alert.symbol,
                quantity=alert.quantity,
                **kwargs
            )
    
    elif alert.action in [TradingViewAction.CLOSE, TradingViewAction.CLOSE_LONG, TradingViewAction.CLOSE_SHORT]:
        # Cancel all open orders and close position
        webhook_logger.info(f"Closing position for {alert.symbol}")
        trading.cancel_all_orders(alert.symbol)
        
        # Get current position and close it
        # You'll need to implement position fetching and closing logic
        return None
    
    else:
        raise ValueError(f"Unknown action: {alert.action}")
