# api_server.py
import asyncio
from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.responses import JSONResponse
from typing import Optional
from contextlib import asynccontextmanager
from models.webhook import TradingViewAlert, WebhookResponse
from models.ticker import TickerRequest, UpdateTickersRequest
from models.trade import OrderRequest
from models.webhook import TrendUpdateAlert, TrendData
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price
from api_builders.trading_builder import TradingService, process_tradingview_alert
from cache.trend_cache import get_trend_cache
from cache.atr_cache import get_atr_cache
from cache.market_info_cache import get_market_info_cache
from cache.portfolio_cache import get_portfolio_cache
from cache.balance_cache import get_balance_cache
from cache.regime_filter import get_regime_filter, MarketRegime
from services.monitoring_service import get_monitoring_service
from services.telegram_service import TelegramService, set_telegram, get_telegram
from services.circuit_breaker import get_circuit_breaker
from services.profile_manager import get_profile_manager
from services.signal_generator import get_signal_generator, get_all_signal_generators
from utils.config import Config
from utils.logging import log_manager
from utils.constants import TradeReason
from utils.security import (
    require_read_permission,
    require_trade_permission,
    require_admin_permission,
    require_webhook_permission,
    check_rate_limit
)
from db.session import SessionLocal 
from decimal import Decimal
from time import time

db = SessionLocal()
config = Config()
apiserver_logger = log_manager.get_logger("APIServer")

WEBHOOK_SECRET = config.webhook_secret if hasattr(config, 'webhook_secret') else None

# Global reference to monitoring service (injected from main.py)
telegram: Optional[TelegramService] = None

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
        trend_cache = get_trend_cache()
        atr_cache = get_atr_cache()
        circuit_breaker = get_circuit_breaker() 

        # Process alert for each profile
        results = []
        errors = []
        
        for profile_name in alert.profiles:
            try:
                # 1. CIRCUIT BREAKER CHECK (FIRST - before any other validation)
                can_trade, breaker_reason = circuit_breaker.check_circuit_breakers(
                    profile_name=profile_name,
                    alert_action=alert.action
                )
                
                if not can_trade:
                    apiserver_logger.warning(
                        f"[{profile_name}] 🚨 Circuit breaker blocked trade: {breaker_reason}"
                    )
                    
                    results.append({
                        "profile": profile_name,
                        "success": False,
                        "error": breaker_reason,
                        "error_type": "circuit_breaker"
                    })
                    errors.append(f"[{profile_name}] Circuit breaker active")
                    continue  # Skip this profile
                
                # Create trading service for this profile
                profile = profile_manager.get(profile_name)
                trading = TradingService(profile)
                trading_timeframe = getattr(profile, 'signal_timeframe', '15')
                trend_timeframe = getattr(profile, 'trend_timeframe', '60')  # Higher TF for trend

                if profile.use_market_regime_filter:
                    regime_filter = get_regime_filter()
                    #1. Add Regime check first - If market is not worth trading, exit early
                    can_trade, regime_reason = regime_filter.can_trade(
                        symbol=alert.symbol,
                        profile_name=profile.name,
                    primary_timeframe=trend_timeframe,  # Uses your 60m timeframe
                    confirm_timeframe=trading_timeframe  # Uses your 15m timeframe
                    )
                
                    if not can_trade:
                        # Log at debug level to avoid spam (most rejections will be UNCERTAIN regime)
                        apiserver_logger.debug(
                            f"{alert.symbol}: Market regime check failed - {regime_reason}"
                        )
                        results.append({
                            "profile": profile_name,
                            "success": False,
                            "error": regime_reason,
                            "error_type": "regime_error"
                        })
                        errors.append(f"[{profile_name}] {regime_reason}")
                        continue
                    

                # Pre-validate balance for orders
                # Only rejects if balance is 0 or below minimum/step size
                is_valid, balance_error = trading.validate_balance_for_trade(
                    sale_action=alert.action, 
                    symbol=alert.symbol,
                    profile_name=profile_name
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
                reasons = []

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
                        reasons.append(f"ATR filter: {reason}")
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
                        reasons.append(f"Trend filter: {reason}")
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
               
                # Process the alert
                result = await process_tradingview_alert(
                    trading, 
                    alert, 
                    source=TradeReason.WEBHOOK,
                    profile_name=profile_name,
                    reason_summary = reasons,
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
            trend_filtered  = sum(1 for r in results if r.get("error_type") == "trend_filter")
            no_balance      = sum(1 for r in results if r.get("error_type") == "insufficient_balance")
            atr_filtered    = sum(1 for r in results  if r.get("error_type") == "atr_filter")
            circuit_blocked = sum(1 for r in results  if r.get("error_type") == "circuit_breaker")
            regime_blocked  = sum(1 for r in results  if r.get("error_type") == "regime_error")

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
            if (no_balance + trend_filtered + atr_filtered + circuit_blocked + regime_blocked) < total_count:
            #if success_count > 0 or (trend_filtered > 0 and trend_filtered != total_count):
                await telegram.send_message(summary)
            else:
                apiserver_logger.error(f"Telegram alert: All profiles failed to execute\n {summary}")


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
    apiserver_logger.info(f"Received trend update: {alert}")
    
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
            "age_seconds": time() - (trend.timestamp or 0)
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

@app.get("/circuit-breaker/status")
async def get_circuit_breaker_status():
    """Get status of all circuit breakers"""
    circuit_breaker = get_circuit_breaker()
    return {
        "active_breakers": circuit_breaker.get_all_breakers(),
        "configuration": {
            "max_daily_profit_pct": str(circuit_breaker.max_daily_profit_pct),
            "max_daily_loss_pct": str(circuit_breaker.max_daily_loss_pct),
            "profit_lock_hours": circuit_breaker.profit_lock_hours,
            "loss_lock_hours": circuit_breaker.loss_lock_hours
        }
    }


@app.get("/circuit-breaker/daily-summary/{profile_name}")
async def get_daily_pnl_summary(profile_name: str):
    """Get daily PnL summary for a profile"""
    circuit_breaker = get_circuit_breaker()
    return circuit_breaker.get_daily_summary(profile_name)


@app.post("/circuit-breaker/reset/{profile_name}", dependencies=[Depends(require_admin_permission)])
async def reset_circuit_breaker(profile_name: str):
    """Manually reset a circuit breaker (admin only)"""
    circuit_breaker = get_circuit_breaker()
    success = circuit_breaker.force_reset_breaker(profile_name)
    
    if success:
        return {"message": f"Circuit breaker reset for {profile_name}"}
    else:
        raise HTTPException(
            status_code=404,
            detail=f"No active circuit breaker for {profile_name}"
        )


@app.get("/circuit-breaker/all-summaries")
async def get_all_daily_summaries():
    """Get daily PnL summary for all profiles"""
    profile_manager = get_profile_manager()
    circuit_breaker = get_circuit_breaker()
    
    summaries = {}
    for profile in profile_manager.get_all_profiles():
        summaries[profile.name] = circuit_breaker.get_daily_summary(profile.name)
    
    return summaries

@app.get("/signals/status/{profile_name}")
async def get_signal_status(profile_name: str):
    """Get signal generation status for a profile"""
    profile_manager = get_profile_manager()
    profile = profile_manager.get(profile_name)
    
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_name} not found")
    
    signal_gen = get_signal_generator(profile)
    
    return {
        "profile": profile_name,
        "enabled": getattr(profile, 'enable_signal_generation', False),
        "trading_timeframe": signal_gen.trading_timeframe,
        "trend_timeframe": signal_gen.trend_timeframe,
        "min_volume_ratio": signal_gen.min_volume_ratio,
        "min_confidence": signal_gen.min_confidence,
        "atr_filter_enabled": profile.use_atr_filter,
        "trend_filter_enabled": profile.use_trend_filter
    }


@app.post("/signals/scan/{profile_name}")
async def scan_for_signals(profile_name: str):
    """
    Manually trigger signal scan for a profile
    Returns signals without executing trades
    """
    profile_manager = get_profile_manager()
    profile = profile_manager.get(profile_name)
    
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_name} not found")
    
    signal_gen = get_signal_generator(profile)
    
    # Get monitored tickers
    monitoring = get_monitoring_service()
    symbols = monitoring.tickers
    
    # Generate signals
    signals = signal_gen.scan_symbols(symbols)
    
    return {
        "profile": profile_name,
        "symbols_scanned": len(symbols),
        "signals_found": len(signals),
        "signals": [signal.to_dict() for signal in signals]
    }


@app.get("/signals/check/{profile_name}/{symbol}")
async def check_signal_for_symbol(profile_name: str, symbol: str):
    """
    Check if there's a signal for a specific symbol
    Useful for debugging why a signal was/wasn't generated
    """
    profile_manager = get_profile_manager()
    profile = profile_manager.get(profile_name)
    
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_name} not found")
    
    signal_gen = get_signal_generator(profile)
    
    # Generate signal
    signal = signal_gen.generate_signal(symbol)
    
    if signal:
        return {
            "has_signal": True,
            "signal": signal.to_dict()
        }
    else:
        return {
            "has_signal": False,
            "message": f"No signal generated for {symbol}",
            "note": "Check logs for detailed reasons"
        }


@app.get("/signals/history")
async def get_signal_history():
    """
    Get recent signal execution history
    (You'd need to implement signal history tracking in monitoring_service)
    """
    # TODO: Implement signal history tracking
    return {
        "message": "Signal history tracking not yet implemented",
        "suggestion": "Check trades table with source='SIGNAL_*'"
    }


@app.post("/signals/test/{profile_name}/{symbol}")
async def test_signal_execution(
    profile_name: str, 
    symbol: str,
    dry_run: bool = True
):
    """
    Test signal execution without actually placing order
    Useful for debugging
    """
    profile_manager = get_profile_manager()
    profile = profile_manager.get(profile_name)
    
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_name} not found")
    
    signal_gen = get_signal_generator(profile)
    signal = signal_gen.generate_signal(symbol)
    
    if not signal:
        return {
            "success": False,
            "message": f"No signal generated for {symbol}"
        }
    
    # Check circuit breakers
    circuit_breaker = get_circuit_breaker()
    can_trade, breaker_reason = circuit_breaker.check_circuit_breakers(
        profile_name=profile_name,
        alert_action="buy"
    )
    
    if not can_trade:
        return {
            "success": False,
            "message": f"Circuit breaker blocked: {breaker_reason}",
            "signal": signal.to_dict()
        }
    
    if dry_run:
        return {
            "success": True,
            "message": "Signal validation passed (dry run)",
            "signal": signal.to_dict(),
            "would_execute": True
        }
    else:
        # Actually execute (use with caution!)
        from api_builders.trading_builder import TradingService
        
        trading = TradingService(profile)
        
        try:
            result = trading.order_buy(
                symbol=signal.symbol,
                quantity="MAX",
                source=f"TEST_SIGNAL_{signal.strength.name}",
                profile_name=profile_name
            )
            
            return {
                "success": True,
                "message": "Signal executed",
                "signal": signal.to_dict(),
                "order": result.model_dump()
            }
        
        except Exception as e:
            return {
                "success": False,
                "message": f"Execution failed: {str(e)}",
                "signal": signal.to_dict()
            }