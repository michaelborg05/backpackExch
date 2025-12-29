# api_server.py
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.responses import JSONResponse
from typing import Optional
from services.monitoring_service import get_monitoring_service
from contextlib import asynccontextmanager
from models.webhook import TradingViewAlert, WebhookResponse
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price
from models.ticker import TickerRequest, UpdateTickersRequest
from models.trade import OrderRequest
from api_builders.trading_builder import TradingService, process_tradingview_alert
from services.balance_cache import get_balance_cache
from services.telegram_listener import TelegramListener, set_telegram_listener
from services.portfolio_cache import get_portfolio_cache
from utils.config import Config
from utils.logging import log_manager
from utils.security import (
    require_read_permission,
    require_trade_permission,
    require_admin_permission,
    require_webhook_permission,
    check_rate_limit
)

config = Config()
apiserver_logger = log_manager.get_logger("APIServer")

WEBHOOK_SECRET = config.webhook_secret if hasattr(config, 'webhook_secret') else None

# Global reference to monitoring service (injected from main.py)
# Global reference to Telegram listener
telegram: Optional[TelegramListener] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events - runs on startup and shutdown"""
    global telegram
    
    # Startup
    apiserver_logger.info("Starting API server lifespan...")    
    # Initialize Telegram if configured
    if config.telegram_bot_token and config.chat_group_id and config.telegram_enabled == True:
        apiserver_logger.info("Initializing Telegram bot...")
        telegram = TelegramListener(
            token=config.telegram_bot_token,
            allowed_chat_id=config.chat_group_id
        )
        set_telegram_listener(telegram)
        
        # Start the bot
        await telegram.start()
        
        # Send startup notification
        await telegram.send_message("🚀 API Started")
    else:
        apiserver_logger.warning("Telegram not configured - skipping")
    
    yield  # Application runs here
    
    # Shutdown
    apiserver_logger.info("Shutting down...")
    
    if telegram:
        await telegram.send_message("🛑 API Shutting Down")
        await telegram.stop()

app = FastAPI(title="Trading API", lifespan=lifespan)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Catches ALL HTTPExceptions across the entire app
    Sends Telegram notification automatically
    """
    # Send Telegram notification for errors
    if telegram and exc.status_code >= 400:
        await telegram.send_error_notification(
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

# Public endpoints (no auth)
@app.get("/health")
def health_check():
    """Public health check"""
    return {
        "status": "healthy",
        "telegram": telegram is not None and telegram._running
    }

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
    if service is None:
        raise HTTPException(
                status_code=503, 
                detail="Monitoring service not initialized"
            )
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
async def place_order(
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
            await telegram.send_order_notification(
                order_type="Market",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                order_id=result.id
            )
        return result.model_dump()
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

#@app.post("/webhook/tradingview", dependencies=[Depends(require_webhook_permission)], response_model=WebhookResponse)
@app.post("/webhook/tradingview", response_model=WebhookResponse)
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
    apiserver_logger.debug("Received TradingView webhook")
    try:
        if alert.secret is None:
            apiserver_logger.warning("No webhook secret provided in alert")
            raise HTTPException(status_code=401, detail="Webhook secret required")
        if alert.secret != WEBHOOK_SECRET:
            apiserver_logger.warning("Invalid webhook secret")
            raise HTTPException(status_code=401, detail="Invalid webhook secret")   
        
        apiserver_logger.info(f"Received TradingView alert: {alert.action} {alert.symbol}")
        
        # Verify webhook secret (from payload)
        if WEBHOOK_SECRET and alert.secret != WEBHOOK_SECRET:
            apiserver_logger.warning("Invalid webhook secret")
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        
        
        # Initialize trading service
        trading = TradingService()
        
        # Process alert based on action
        if telegram:
            await telegram.send_message(f"Processing TradingView alert: {alert.action} {alert.symbol}"  )

        result = await process_tradingview_alert(trading, alert)

        apiserver_logger.info(f"Alert processed successfully: {result}")
        
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
        apiserver_logger.error(f"Error processing webhook: {e}", exc_info=True)
        if telegram:
            await telegram.send_error_notification(
                error_type=f"Error processing webhook",
                error_message=str(e),
                endpoint=f"{request.method} {request.url.path}"
            )
        return WebhookResponse(
            success=False,
            message=f"Error: {str(e)}",
            details={"error": str(e)}
        )
        


@app.get("/portfolio", dependencies=[Depends(require_read_permission)])
def get_portfolio(quote_asset: str = "USDC"):
    """Get complete portfolio with values"""
    portfolio = get_portfolio_cache()
    return portfolio.get_portfolio_summary(quote_asset)

@app.get("/portfolio/total", dependencies=[Depends(require_read_permission)])
def get_total_portfolio_value(quote_asset: str = "USDC"):
    """Get total portfolio value"""
    portfolio = get_portfolio_cache()
    total = portfolio.get_total_value(quote_asset)
    
    return {
        "total_value": str(total),
        "quote_asset": quote_asset
    }


