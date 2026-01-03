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
from services.market_info_cache import get_market_info_cache
from services.portfolio_cache import get_portfolio_cache
from utils.config import Config
from utils.logging import log_manager
from utils.constants import TradeReason
from services.profile_manager import get_profile_manager
from utils.security import (
    require_read_permission,
    require_trade_permission,
    require_admin_permission,
    require_webhook_permission,
    check_rate_limit
)
from db.session import SessionLocal 
from db.crud import save_trade, open_position, close_position
from decimal import Decimal

db = SessionLocal()
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


@app.get("/balances/cached/{profile_name}/{asset}", dependencies=[Depends(require_read_permission)])
def get_cached_asset_balance(profile_name: str, asset: str):
    """Get balance for specific asset from cache"""
    cache = get_balance_cache()
    balance = cache.get_available_balance(profile_name=profile_name, asset=asset)

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
            result = trading.order_buy(request.symbol, request.quantity,source=TradeReason.API)
        elif request.side.lower() == "sell":
            result = trading.order_sell(request.symbol, request.quantity,source=TradeReason.API)
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
    request: Request
):
    """
    Receive and process TradingView webhook alerts
    
    Supports multiple profiles in single alert:
    {
        "action": "buy",
        "symbol": "SOL_USDC",
        "profile": "default,MB15m,aggressive",
        "secret": "your_webhook_secret"
    }
    """
    apiserver_logger.debug("Received TradingView webhook")
    
    try:
        # Authentication
        if alert.secret is None:
            apiserver_logger.warning("No webhook secret provided in alert")
            raise HTTPException(status_code=401, detail="Webhook secret required")
        if alert.secret != WEBHOOK_SECRET:
            apiserver_logger.warning("Invalid webhook secret")
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        
        apiserver_logger.info(f"Received TradingView alert: {alert.action} {alert.symbol}")
        
        # Get profile manager
        profile_manager = get_profile_manager()
        if profile_manager is None:
            apiserver_logger.error("Profile manager not initialized")
            raise HTTPException(
                status_code=503,
                detail="Profile manager not initialized. Server startup incomplete."
            )
        
        # Validate all profiles exist before processing any
        invalid_profiles = []
        for profile_name in alert.profiles:
            if not profile_manager.has_profile(profile_name):
                invalid_profiles.append(profile_name)
        
        if invalid_profiles:
            error_msg = f"Invalid profile(s): {', '.join(invalid_profiles)}"
            apiserver_logger.error(error_msg)
            raise HTTPException(status_code=400, detail=error_msg)
        
        apiserver_logger.info(
            f"Processing TradingView alert: {alert.action} {alert.symbol} "
            f"for profiles: {', '.join(alert.profiles)}"
        )
        
        # Notify via Telegram
        if telegram:
            profiles_str = ', '.join(alert.profiles)
            await telegram.send_message(
                f"📊 TradingView Alert\n"
                f"Action: {alert.action.upper()}\n"
                f"Symbol: {alert.symbol}\n"
                f"Price: {alert.current_price}\n"
                f"Profiles: {profiles_str}"
            )
        
        # Process alert for each profile
        results = []
        errors = []
        
        for profile_name in alert.profiles:
            try:
                profile = profile_manager.get(profile_name)
                
                # Override profile settings if provided in alert
                if alert.take_profit:
                    apiserver_logger.info(
                        f"[{profile_name}] Overriding take profit: "
                        f"{profile.take_profit_pct}% → {alert.take_profit}%"
                    )
                    profile.take_profit_pct = Decimal(alert.take_profit)
                
                if alert.trailing_stop_loss:
                    apiserver_logger.info(
                        f"[{profile_name}] Overriding trailing stop: "
                        f"{profile.trailing_stop_pct}% → {alert.trailing_stop_loss}%"
                    )
                    profile.trailing_stop_pct = Decimal(alert.trailing_stop_loss)
                
                if alert.stop_loss:
                    apiserver_logger.info(
                        f"[{profile_name}] Overriding stop loss: "
                        f"{profile.stop_loss_pct}% → {alert.stop_loss}%"
                    )
                    profile.stop_loss_pct = Decimal(alert.stop_loss)
                
                # Create trading service for this profile
                trading = TradingService(profile)
                
                # Process the alert
                result = await process_tradingview_alert(
                    trading, 
                    alert, 
                    source=TradeReason.WEBHOOK,
                    profile_name=profile_name
                )
                
                results.append({
                    "profile": profile_name,
                    "success": True,
                    "order_id": result.id if result else None,
                    "executed_quantity": result.executed_quantity if result else None,
                    "status": result.status if result else None
                })
                
                apiserver_logger.info(
                    f"[{profile_name}] Alert processed successfully: {result}"
                )
                
            except Exception as e:
                error_msg = f"[{profile_name}] Error: {str(e)}"
                apiserver_logger.error(error_msg, exc_info=True)
                
                results.append({
                    "profile": profile_name,
                    "success": False,
                    "error": str(e)
                })
                errors.append(error_msg)
        
        # Determine overall success
        successful_profiles = [r for r in results if r.get("success")]
        overall_success = len(successful_profiles) > 0
        
        # Send summary notification
        if telegram:
            success_count = len(successful_profiles)
            total_count = len(alert.profiles)
            
            if success_count == total_count:
                summary = f"✅ Alert Complete: {success_count}/{total_count} profiles succeeded\n"
            elif success_count > 0:
                summary = f"⚠️ Alert Partial Success: {success_count}/{total_count} profiles succeeded\n"
            else:
                summary = f"❌ Alert Failed: {success_count}/{total_count} profiles succeeded\n"
            summary += f"Symbol: {alert.symbol} | Action: {alert.action.upper()}\n\n"
            
            for result in results:
                profile_name = result['profile']
                if result['success']:
                    summary += f"✓ {profile_name}: Order {result.get('order_id', 'N/A')}\n"
                else:
                    summary += f"✗ {profile_name}: {result.get('error', 'Failed')}\n"
            
            await telegram.send_message(summary)
        
        # Build response message
        if overall_success:
            if errors:
                message = f"Partial success: {len(successful_profiles)}/{len(alert.profiles)} profiles executed"
            else:
                message = f"All {len(alert.profiles)} profile(s) executed successfully"
        else:
            message = "All profiles failed to execute"
        
        return WebhookResponse(
            success=overall_success,
            message=message,
            results=results,
            details={
                "action": alert.action,
                "symbol": alert.symbol,
                "profiles_attempted": alert.profiles,
                "successful_count": len(successful_profiles),
                "failed_count": len(errors)
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error processing webhook: {e}", exc_info=True)
        if telegram:
            await telegram.send_error_notification(
                error_type="Webhook Processing Error",
                error_message=str(e),
                endpoint=f"{request.method} {request.url.path}"
            )
        return WebhookResponse(
            success=False,
            message=f"Error: {str(e)}",
            results=[],
            details={"error": str(e)}
        )

@app.get("/portfolio/{profile_name}", dependencies=[Depends(require_read_permission)])
def get_portfolio(profile_name: str, quote_asset: str = "USDC"):
    """Get complete portfolio with values"""
    portfolio = get_portfolio_cache()
    return portfolio.get_portfolio_summary(quote_asset, profile_name=profile_name)

@app.get("/portfolio/{profile_name}/total", dependencies=[Depends(require_read_permission)])
def get_total_portfolio_value(profile_name: str, quote_asset: str = "USDC"):
    """Get total portfolio value"""
    portfolio = get_portfolio_cache()
    total = portfolio.get_total_value(quote_asset, profile_name=profile_name)

    return {
        "total_value": str(total),
        "quote_asset": quote_asset
    }

@app.get("/market/{symbol}", dependencies=[Depends(require_read_permission)])
def get_market_info_endpoint(symbol: str):
    """Get market info for a symbol"""
    cache = get_market_info_cache()
    market_info = cache.get_market_info(symbol)
    
    if market_info is None:
        # Try to fetch from API
        from api_builders.market_builder import get_market_info
        result = get_market_info(symbol)
        
        if result:
            market_info = cache.get_market_info(symbol)
        
        if market_info is None:
            raise HTTPException(
                status_code=404,
                detail=f"Market info for {symbol} not found"
            )
    
    return market_info.to_dict()


@app.get("/markets", dependencies=[Depends(require_read_permission)])
def get_all_markets_endpoint():
    """Get all market info"""
    cache = get_market_info_cache()
    markets = cache.get_all_markets()
    
    return {
        "markets": {symbol: info.to_dict() for symbol, info in markets.items()},
        "cache_info": cache.get_cache_info()
    }
