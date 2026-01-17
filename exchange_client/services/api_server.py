# api_server.py
import asyncio
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
from cache.atr_cache import get_atr_cache
from cache.balance_cache import get_balance_cache
from services.telegram_service import TelegramService, set_telegram, get_telegram
from cache.market_info_cache import get_market_info_cache
from cache.portfolio_cache import get_portfolio_cache
from models.webhook import TrendUpdateAlert, TrendData
from services.trend_service import get_trend_cache
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
from time import time

db = SessionLocal()
config = Config()
apiserver_logger = log_manager.get_logger("APIServer")

WEBHOOK_SECRET = config.webhook_secret if hasattr(config, 'webhook_secret') else None

# Global reference to monitoring service (injected from main.py)
telegram: Optional[TelegramService] = None

def validate_balance_for_trade(
    alert: TradingViewAlert,
    profile_name: str,
    balance_cache,
    market_info_cache
) -> tuple[bool, Optional[str]]:
    """
    Validate that profile has sufficient balance before attempting trade
    Only rejects if balance is zero or below market minimum quantity
    
    Args:
        alert: TradingView alert data
        profile_name: Name of trading profile
        balance_cache: BalanceCache instance
        market_info_cache: MarketInfoCache instance
        
    Returns:
        (is_valid, error_message) tuple
    """
    
    # Parse symbol to get base asset
    #If sell, get first token, if buy get 2nd token
    try:
        if alert.action.upper() == "SELL":
            base_asset = alert.symbol.split('_')[0]
        else:
            base_asset = alert.symbol.split('_')[1]
    except Exception:
        return True, None  # Let trading_builder handle invalid symbols
    
    # Get cached balance
    available = balance_cache.get_available_balance(
        profile_name=profile_name,
        asset=base_asset
    )
    
    # If no balance data, let it proceed (will fail later with proper error)
    if available is None:
        apiserver_logger.debug(
            f"[{profile_name}] No cached balance for {base_asset}, proceeding with trade"
        )
        return True, None
    
    # Check if balance is zero
    if available <= 0:
        error_msg = f"No available balance for {base_asset}"
        apiserver_logger.warning(f"[{profile_name}] {error_msg}")
        return False, error_msg

    #if base_asset is USDC (i.e. its a buy), reject if USDC balance below $5 
    if base_asset == "USDC" and available < 5:
        error_msg = f"Balance for {base_asset} below $5"
        apiserver_logger.warning(f"[{profile_name}] {error_msg}")
        return False, error_msg

    #If buy order and already passed above checks, return true and continue
    if alert.action.upper() == "BUY":
        return True, None
    
    # Get market info to check minimum quantity
    market_info = market_info_cache.get_market_info(alert.symbol)
    
    if market_info is None:
        # No market info - let trading_builder handle it
        apiserver_logger.debug(
            f"[{profile_name}] No market info for {alert.symbol}, proceeding with trade"
        )
        return True, None
    
    # Check if available balance is below minimum quantity
    # This prevents trades that will definitely fail due to market rules
    if available < market_info.min_quantity:
        error_msg = (
            f"Balance too low for {base_asset}. "
            f"Available: {available}, Minimum: {market_info.min_quantity}"
        )
        apiserver_logger.warning(f"[{profile_name}] {error_msg}")
        return False, error_msg
    
    # Check if balance would round to zero due to step size
    rounded = market_info.round_quantity(available)
    if rounded == 0:
        error_msg = (
            f"Balance too small for {base_asset}. "
            f"Available: {available} rounds to 0 (step size: {market_info.step_size})"
        )
        apiserver_logger.warning(f"[{profile_name}] {error_msg}")
        return False, error_msg
    
    # Balance is sufficient - let trading_builder adjust if needed
    return True, None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events - runs on startup and shutdown"""
    global telegram
    
    # Startup
    apiserver_logger.info("Starting API server lifespan...")
    
    # Initialize Telegram if configured
    if config.telegram_bot_token and config.chat_group_id and config.telegram_enabled:
        webhook_url = getattr(config, 'telegram_webhook_url', None)
        apiserver_logger.info("Initializing Telegram bot...")
        
        telegram = TelegramService(
            token=config.telegram_bot_token,
            allowed_chat_id=config.chat_group_id,
            webhook_url=webhook_url
        )
        set_telegram(telegram)
        
        # Try to initialize with retry logic
        max_retries = 3
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                apiserver_logger.info(f"Telegram initialization attempt {attempt + 1}/{max_retries}...")
                await asyncio.wait_for(telegram.initialize(), timeout=30.0)
                
                # Send startup notification
                mode = "Webhook" if telegram.use_webhook else "Polling (Local)"
                await telegram.send_message(f"🚀 API Started ({mode} mode)")
                apiserver_logger.info("Telegram bot initialized successfully")
                break
                
            except asyncio.TimeoutError:
                apiserver_logger.warning(
                    f"Telegram initialization timed out (attempt {attempt + 1}/{max_retries})"
                )
                if attempt < max_retries - 1:
                    apiserver_logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    apiserver_logger.error(
                        "Telegram initialization failed after all retries. "
                        "Bot will be disabled but API will continue."
                    )
                    telegram = None  # Disable Telegram
                    
            except Exception as e:
                apiserver_logger.error(f"Error initializing Telegram: {e}", exc_info=True)
                if attempt < max_retries - 1:
                    apiserver_logger.info(f"Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                else:
                    apiserver_logger.error(
                        "Telegram initialization failed after all retries. "
                        "Bot will be disabled but API will continue."
                    )
                    telegram = None  # Disable Telegram
    else:
        apiserver_logger.warning("Telegram not configured - skipping")
    
    yield  # Application runs here
    
    # Shutdown
    apiserver_logger.info("Shutting down...")
    
    if telegram and telegram._initialized:
        try:
            await asyncio.wait_for(
                telegram.send_message("🛑 API Shutting Down"),
                timeout=5.0
            )
            await asyncio.wait_for(telegram.shutdown(), timeout=10.0)
        except asyncio.TimeoutError:
            apiserver_logger.warning("Telegram shutdown timed out")
        except Exception as e:
            apiserver_logger.error(f"Error during Telegram shutdown: {e}")
    
    apiserver_logger.info("API server shutdown complete")


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
        "telegram": telegram is not None and telegram._initialized
    }

@app.get("/webhook/test")
def test_webhook():
    """Test endpoint to verify webhook is accessible"""
    """Public test endpoint"""
    return {
        "status": "ok",
        "message": "Webhook endpoint is accessible",        
    }

@app.post("/telegram/webhook")
async def telegram_webhook_endpoint(request: Request):
    """
    Receives updates from Telegram via webhook.
    This is the endpoint you configure in Telegram.
    
    CRITICAL: Returns immediately to avoid Telegram timeout (60s limit)
    """
    if not telegram:
        raise HTTPException(status_code=503, detail="Telegram not configured")
    
    try:
        # Get the JSON data from Telegram
        update_data = await request.json()
        
        # ⭐ Process update asynchronously - don't await!
        # This allows us to return {"ok": True} immediately
        asyncio.create_task(telegram.process_update(update_data))
        
        # Return immediately - Telegram requires response within 60 seconds
        return {"ok": True}
    
    except Exception as e:
        apiserver_logger.error(f"Error in Telegram webhook endpoint: {e}", exc_info=True)
        # Still return ok to Telegram even if we had an error
        # (otherwise Telegram will retry repeatedly)
        return {"ok": True}
    
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
    """Place an order"""
    try:
        # Pre-validate balance for SELL orders only if balance is unusable
        if request.side.lower() == "sell":
            try:
                base_asset = request.symbol.split('_')[0]
                balance_cache = get_balance_cache()
                market_info_cache = get_market_info_cache()
                
                available = balance_cache.get_available_balance(
                    profile_name="default",  # Adjust if you support profile in OrderRequest
                    asset=base_asset
                )
                
                # Only reject if balance is zero
                if available is not None and available <= 0:
                    error_msg = f"No available balance for {base_asset}"
                    apiserver_logger.warning(error_msg)
                    raise HTTPException(
                        status_code=400,
                        detail=error_msg
                    )
                
                # Check against market minimum if we have both balance and market info
                if available is not None:
                    market_info = market_info_cache.get_market_info(request.symbol)
                    
                    if market_info is not None:
                        # Check if below minimum quantity
                        if available < market_info.min_quantity:
                            error_msg = (
                                f"Balance too low for {base_asset}. "
                                f"Available: {available}, Minimum: {market_info.min_quantity}"
                            )
                            apiserver_logger.warning(error_msg)
                            raise HTTPException(
                                status_code=400,
                                detail=error_msg
                            )
                        
                        # Check if would round to zero
                        rounded = market_info.round_quantity(available)
                        if rounded == 0:
                            error_msg = (
                                f"Balance too small for {base_asset}. "
                                f"Available: {available} rounds to 0 (step size: {market_info.step_size})"
                            )
                            apiserver_logger.warning(error_msg)
                            raise HTTPException(
                                status_code=400,
                                detail=error_msg
                            )
                
            except HTTPException:
                raise
            except Exception as e:
                # If validation fails for any reason, let trading_builder handle it
                apiserver_logger.debug(f"Balance pre-validation failed: {e}")
        
        # Proceed with trade - trading_builder will adjust quantity if needed
        trading = TradingService()  

        if request.side.lower() == "buy":
            result = trading.order_buy(
                request.symbol, 
                request.quantity,
                source=TradeReason.API
            )
        elif request.side.lower() == "sell":
            result = trading.order_sell(
                request.symbol, 
                request.quantity,
                source=TradeReason.API
            )
        else:
            raise HTTPException(
                status_code=400, 
                detail="Side must be 'buy' or 'sell'"
            )
        
        if telegram:
            await telegram.send_order_notification(
                order_type="Market",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                order_id=result.id
            )

        return result.model_dump()
    
    except HTTPException:
        raise
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
        
        # Get caches for pre-validation
        balance_cache = get_balance_cache()
        market_info_cache = get_market_info_cache()
        trend_cache = get_trend_cache()
        atr_cache = get_atr_cache()

        # Process alert for each profile
        results = []
        errors = []
        
        for profile_name in alert.profiles:
            try:
                # Pre-validate balance for SELL orders
                # Only rejects if balance is 0 or below minimum/step size
                is_valid, balance_error = validate_balance_for_trade(
                    alert, 
                    profile_name, 
                    balance_cache,
                    market_info_cache
                )
                
                if not is_valid:
                    # Skip this profile - balance unusable
                    apiserver_logger.warning(
                        f"[{profile_name}] Skipping trade: {balance_error}"
                    )
                    
                    results.append({
                        "profile": profile_name,
                        "success": False,
                        "error": balance_error,
                        "error_type": "insufficient_balance"
                    })
                    errors.append(f"[{profile_name}] {balance_error}")
                    continue
                
                # Balance check passed, proceed with trade
                profile = profile_manager.get(profile_name)

                # If buy order and use_atr_filter true, check volatility
                if alert.action.lower() == "buy" and profile.use_atr_filter:  # New profile setting
                    apiserver_logger.debug(
                        f"[{profile_name}] Checking ATR filter: "
                        f"timeframe={profile.atr_timeframe}, "
                        f"threshold={profile.atr_threshold}"
                    )
                    
                    is_volatile, reason = atr_cache.is_volatile(
                        symbol=alert.symbol,
                        timeframe=profile.atr_timeframe,
                        threshold=profile.atr_threshold
                    )
                    
                    if profile.atr_filter_mode == "require_high" and not is_volatile:
                        apiserver_logger.info(
                            f"[{profile_name}] ⊘ Skipping BUY - ATR too low: {reason}"
                        )
                        results.append({
                            "profile": profile_name,
                            "success": False,
                            "error": f"ATR filter: {reason}",
                            "error_type": "atr_filter"
                        })
                        errors.append(f"[{profile_name}] ATR filter blocked trade")
                        continue
                    
                    elif profile.atr_filter_mode == "require_low" and is_volatile:
                        apiserver_logger.info(
                            f"[{profile_name}] ⊘ Skipping BUY - ATR too high: {reason}"
                        )
                        results.append({
                            "profile": profile_name,
                            "success": False,
                            "error": f"ATR filter: {reason}",
                            "error_type": "atr_filter"
                        })
                        errors.append(f"[{profile_name}] ATR filter blocked trade")
                        continue
                    
                    else:
                        apiserver_logger.info(
                            f"[{profile_name}] ✓ ATR check passed: {reason}"
                        )

                if alert.action.lower() == "buy" and profile.use_trend_filter:
                    apiserver_logger.debug(
                        f"[{profile_name}] Checking trend filter: {profile.get_trend_config_summary()}"
                    )
                    
                    is_bullish, reason = trend_cache.is_bullish(
                        symbol=alert.symbol,
                        timeframe=profile.trend_timeframe,
                        indicators_config=profile.trend_indicators,
                        min_indicators_required=profile.min_indicators_required
                    )
                    
                    if not is_bullish:
                        apiserver_logger.info(
                            f"[{profile_name}] ⊘ Skipping BUY - Trend filter: {reason}"
                        )
                        results.append({
                            "profile": profile_name,
                            "success": False,
                            "error": f"Trend not bullish: {reason}",
                            "error_type": "trend_filter"
                        })
                        errors.append(f"[{profile_name}] Trend filter blocked trade")
                        continue  # Skip this profile
                    else:
                        apiserver_logger.info(
                            f"[{profile_name}] ✓ Trend check passed: {reason}"
                        )
                  
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
                
                executed_price = None
                try:
                    executed_price = float(result.executed_quote_quantity) / float(result.executed_quantity)
                    if executed_price < 1:
                        executed_price = round(executed_price, 6)
                    else:
                        executed_price = round(executed_price, 2)   
                except (ValueError, ZeroDivisionError):
                    executed_price = None
                
                results.append({
                    "profile": profile_name,
                    "success": True,
                    "order_id": result.id if result else None,
                    "executed_quantity": result.executed_quantity if result else None,
                    "executed_price": executed_price,
                    "status": result.status if result else None,
                    "profit": result.profit if result else None
                })
                
                apiserver_logger.info(
                    f"[{profile_name}] Alert processed successfully: {result}"
                )
                
            except Exception as e:
                error_msg = f"[{profile_name}] Error: {str(e)}"
                apiserver_logger.error(error_msg, exc_info=True)
                
                # Check if it's a trading exception with error type
                error_type = "unknown"
                if hasattr(e, 'error_type'):
                    error_type = e.error_type
                
                results.append({
                    "profile": profile_name,
                    "success": False,
                    "error": str(e),
                    "error_type": error_type
                })
                errors.append(error_msg)
        
        # Determine overall success
        successful_profiles = [r for r in results if r.get("success")]
        overall_success = len(successful_profiles) > 0
        
        # Send summary notification
        if telegram:
            success_count = len(successful_profiles)
            total_count = len(alert.profiles)

            # Count different types of failures
            trend_filtered = sum(1 for r in results if r.get("error_type") == "trend_filter")
            no_balance = sum(1 for r in results if r.get("error_type") == "insufficient_balance")

            action_icon = "📈" if alert.action.lower() == "buy" else "🏁"
            if success_count == total_count:
                success_icon = "✅"
            elif success_count > 0:
                success_icon = "⚠️"
            else:
                success_icon = "❌"

            summary = ( 
                f"{action_icon}{success_icon} TradingView Alert\n" 
                f"Action: {alert.action.upper()}\n"
                f"Symbol: {alert.symbol}\n"
                f"Price: {alert.current_price}\n"
                f"{success_icon} {success_count}/{total_count} profiles succeeded\n"
            )

            for result in results:
                profile_name = result['profile']
                if result['success']:
                    if result.get('profit') is not None:
                        profit = float(result.get('profit', '0.0'))
                        icon = "🎯" if profit >= 0 else "🛑"
                        summary += f"✓ {profile_name}: {icon} ${profit:2f}\n"
                    else:
                        summary += f"✓ {profile_name}: Price: ${result.get('executed_price', 'N/A')}\n"
                else:
                    error_type = result.get('error_type', 'unknown')
                    if error_type == 'insufficient_balance':
                        summary += f"⊘ {profile_name}: No balance\n"
                    elif error_type == 'trend_filter':
                        summary += f"⊘ {profile_name}: Trend bearish\n"
                    else:
                        summary += f"✗ {profile_name}: {result.get('error', 'Failed')}\n"

            # Only send if at least one profile succeeded OR if failures aren't just balance/trend issues
            if (no_balance + trend_filtered) < total_count:
            #if success_count > 0 or (trend_filtered > 0 and trend_filtered != total_count):
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
                "failed_count": len(errors),
                "trend_filtered_count": trend_filtered if 'trend_filtered' in locals() else 0
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

@app.post("/webhook/tradingview/trend")
async def tradingview_trend_webhook(alert: TrendUpdateAlert):
    """
    Receive trend updates from TradingView
    
    This endpoint receives periodic updates (e.g., every 5min) with
    trend indicator values (EMA, RSI, VWAP) for multiple symbols
    """
    try:
        # Validate secret
        if alert.secret != WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        
        apiserver_logger.info(
            f"Received trend update for {len(alert.trends)} symbol(s)"
        )
        
        # Update trend cache
        trend_cache = get_trend_cache()
        
        for trend_data in alert.trends:
            trend_cache.update(trend_data)
        
        return {
            "success": True,
            "message": f"Updated trends for {len(alert.trends)} symbol(s)",
            "cache_info": trend_cache.get_cache_info()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error processing trend update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trend/{symbol}/{timeframe}")
async def get_trend_status(symbol: str, timeframe: str):
    """Get current trend status for a symbol"""
    trend_cache = get_trend_cache()
    trend = trend_cache.get(symbol, timeframe)
    
    if not trend:
        raise HTTPException(
            status_code=404, 
            detail=f"No trend data for {symbol} ({timeframe})"
        )
    
    is_bullish, reason = trend_cache.is_bullish(symbol, timeframe)
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "is_bullish": is_bullish,
        "reason": reason,
        "data": {
            "ema20": trend.ema20,
            "ema50": trend.ema50,
            "rsi": trend.rsi,
            "vwap": trend.vwap,
            "price": trend.price,
            "age_seconds": time.time() - (trend.timestamp or 0)
        }
    }

@app.get("/atr/{symbol}/{timeframe}")
async def get_atr_status(symbol: str, timeframe: str):
    """Get current ATR status for a symbol"""
    atr_cache = get_atr_cache()
    atr_data = atr_cache.get(symbol, timeframe)
    
    if not atr_data:
        raise HTTPException(
            status_code=404,
            detail=f"No ATR data for {symbol} ({timeframe})"
        )
    
    is_volatile, reason = atr_cache.is_volatile(symbol, timeframe)
    
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "atr": str(atr_data.atr),
        "atr_sma": str(atr_data.atr_sma),
        "ratio": str(atr_data.get_ratio()),
        "is_volatile": is_volatile,
        "reason": reason,
        "timestamp": atr_data.timestamp.isoformat()
    }

@app.get("/atr/all")
async def get_all_atr():
    """Get all ATR data from cache"""
    atr_cache = get_atr_cache()
    return atr_cache.get_cache_info()