# api_server.py
import asyncio
from fastapi import FastAPI, HTTPException, Header, Request, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Optional
from contextlib import asynccontextmanager
from models.webhook import TradingViewAlert, WebhookResponse
from models.ticker import TickerRequest, UpdateTickersRequest
from models.trade import OrderRequest
from models.webhook import TrendUpdateAlert, TrendData
from models.symbol import SymbolConfigRequest
from models.ai_prompt import AIPromptCreate, AIPromptUpdate
from models.indicator_config import IndicatorCreate, IndicatorUpdate, IndicatorOut
from models.trading_profile import CircuitBreakerUpdateRequest, ProfileCredentialsRequest, ProfileCreateRequest, ProfileUpdateRequest
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price
from api_builders.factory import get_adapter
from cache.trend_cache import get_trend_cache
from cache.atr_cache import get_atr_cache
from cache.market_info_cache import get_market_info_cache
from cache.portfolio_cache import get_portfolio_cache
from cache.balance_cache import get_balance_cache
from cache.regime_filter import get_regime_filter
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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from services.dashboard_auth import auth_router, get_dashboard_user

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
    # 1. Define conditions for skipping the Telegram alert
    is_auth_error = exc.status_code in [401, 403]
    is_auth_path = request.url.path.startswith("/auth") or request.url.path == "/"
    
    # 2. Only send Telegram notification if it's NOT a common auth/redirect error
    should_notify = telegram and exc.status_code >= 400
    
    if is_auth_error and is_auth_path:
        should_notify = False

    if should_notify:
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
    """
    Get live account balances from the exchange.
    Deduplicates by exchange account — profiles sharing an account are only
    queried once.  Returns a flat array of asset rows with USD values.
    """
    try:
        from cache.price_cache import get_price_cache
        price_cache = get_price_cache()

        profile_manager = get_profile_manager()
        if not profile_manager:
            raise HTTPException(status_code=503, detail="Profile manager not ready")

        # Fetch balances, deduplicating per account
        all_balances = get_balances(update_cache=True)  # Dict[profile_name, BalanceReader]

        # Collapse to unique accounts (first profile per account_id wins)
        seen_accounts: set = set()
        merged: dict = {}  # asset → {available, locked, staked}

        profiles = profile_manager.get_all_profiles()
        for profile in profiles:
            account_id = getattr(profile, 'account_id', None)
            dedup_key = account_id if account_id else profile.name
            if dedup_key in seen_accounts:
                continue
            seen_accounts.add(dedup_key)
            reader = all_balances.get(profile.name)
            if not reader:
                continue
            for symbol, ab in reader._balances.items():
                if symbol not in merged:
                    merged[symbol] = {"available": ab.available, "locked": ab.locked, "staked": ab.staked}
                else:
                    merged[symbol]["available"] += ab.available
                    merged[symbol]["locked"]    += ab.locked
                    merged[symbol]["staked"]    += ab.staked

        result = []
        for asset, bal in sorted(merged.items()):
            free = float(bal["available"])
            locked = float(bal["locked"])
            total = free + locked + float(bal["staked"])
            if total < 0.0001:
                continue
            if asset == "USDC":
                price = 1.0
            else:
                raw = price_cache.get_price(f"{asset}_USDC")
                price = float(raw) if raw else 0.0
            usd_value   = round(total  * price, 2)
            locked_usd  = round(locked * price, 2)
            result.append({
                "asset":      asset,
                "free":       free,
                "locked":     locked,
                "total":      total,
                "price":      price,
                "usd_value":  usd_value,
                "locked_usd": locked_usd,
            })

        result.sort(key=lambda x: x["usd_value"], reverse=True)
        return {"balances": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/balances/cached", dependencies=[Depends(require_read_permission)])
def get_cached_balances():
    """
    Get balances from cache (fast, no API call).
    Returns per-account entries (no duplicates across profiles sharing an account).
    """
    from cache.price_cache import get_price_cache
    cache = get_balance_cache()
    price_cache = get_price_cache()

    accounts = cache.get_all_accounts()

    if not accounts:
        return {
            "error": "Balance cache is empty or stale",
            "cache_info": cache.get_cache_info()
        }

    # Flatten all accounts into a single deduplicated asset list
    merged: dict = {}
    for _account_key, balances in accounts.items():
        for asset, info in balances.items():
            if asset not in merged:
                from decimal import Decimal
                merged[asset] = {
                    "available": Decimal(info.get("available", "0")),
                    "locked":    Decimal(info.get("locked",    "0")),
                    "staked":    Decimal(info.get("staked",    "0")),
                }
            else:
                from decimal import Decimal
                merged[asset]["available"] += Decimal(info.get("available", "0"))
                merged[asset]["locked"]    += Decimal(info.get("locked",    "0"))
                merged[asset]["staked"]    += Decimal(info.get("staked",    "0"))

    result = []
    for asset, bal in sorted(merged.items()):
        free   = float(bal["available"])
        locked = float(bal["locked"])
        total  = free + locked + float(bal["staked"])
        if total < 0.0001:
            continue
        price = 1.0 if asset == "USDC" else float(price_cache.get_price(f"{asset}_USDC") or 0)
        result.append({
            "asset":      asset,
            "free":       free,
            "locked":     locked,
            "total":      total,
            "price":      price,
            "usd_value":  round(total  * price, 2),
            "locked_usd": round(locked * price, 2),
        })

    result.sort(key=lambda x: x["usd_value"], reverse=True)
    return {
        "balances":   result,
        "cache_info": cache.get_cache_info(),
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
        # Proceed with trade - adapter routes to correct exchange
        profile_manager = get_profile_manager()
        profile = profile_manager.get(request.profile_name)
        adapter = get_adapter(profile)

        if request.side.lower() == "buy":
            result = adapter.order_buy(
                request.symbol,
                request.quantity,
                source=TradeReason.API
            )
        elif request.side.lower() == "sell":
            result = adapter.order_sell(
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
            id = result.id if result else None
            await telegram.send_order_notification(
                order_type="Market",
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                order_id=id
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
    Receive and process TradingView webhook alerts with intelligent position sizing
    
    Supports multiple profiles in single alert:
    {
        "action": "buy",
        "symbol": "SOL_USDC",
        "profile": "default,MB15m,aggressive",
        "secret": "your_webhook_secret"
    }
    Position sizing priority:
    1. Explicit quantity in alert (if provided)
    2. Symbol-specific config from database
    3. Profile defaults
    4. Balance constraints
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
        
        # Get caches and services
        trend_cache = get_trend_cache()
        atr_cache = get_atr_cache()
        circuit_breaker = get_circuit_breaker() 
        
        # Import position size calculator
        from utils.position_calculator import get_position_size_calculator
        position_calculator = get_position_size_calculator()

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
                
                profile = profile_manager.get(profile_name)
                adapter = get_adapter(profile)
                trading_timeframe = getattr(profile, 'signal_timeframe', '15')
                trend_timeframe = getattr(profile, 'trend_timeframe', '60')  # Higher TF for trend

                #2. Market Regime filter
                if profile.use_market_regime_filter:
                    regime_filter = get_regime_filter()
                    #1. Add Regime check first - If market is not worth trading, exit early
                    can_trade, regime_reason = regime_filter.can_trade(
                        symbol=alert.symbol,
                        profile_name=profile.name,
                    primary_timeframe=trend_timeframe,  # Uses your 60m timeframe
                    confirm_timeframe=trading_timeframe,  # Uses your 15m timeframe
                    strategy_type=profile.strategy_type
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
                    

                # 3. Pre-validate balance for orders
                # Only rejects if balance is 0 or below minimum/step size
                is_valid, balance_error = adapter.validate_balance_for_trade(
                    sale_action=alert.action,
                    symbol=alert.symbol
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
                
                # 4. BUY ORDER SPECIFIC CHECKS
                if alert.action.lower() == "buy":
                    # 5. Check ATR filter if enabled
                    if profile.use_atr_filter:
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
                    
                    # 6. Check trend filter if enabled
                    if profile.use_trend_filter:
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
                            continue
                        else:
                            reasons.append(f"Trend filter: {reason}")
                            apiserver_logger.info(
                                f"[{profile_name}] ✓ Trend check passed: {reason}"
                            )
                    
                    # 7. CALCULATE POSITION SIZE (if not explicitly provided)
                    if not alert.quantity or alert.quantity.upper() == "AUTO":
                        quantity, size_reason = position_calculator.calculate_buy_quantity(
                            symbol=alert.symbol,
                            profile=profile,
                            quote_asset="USDC"
                        )
                        
                        if quantity is None:
                            apiserver_logger.warning(
                                f"[{profile_name}] Cannot calculate position size: {size_reason}"
                            )
                            results.append({
                                "profile": profile_name,
                                "success": False,
                                "error": size_reason,
                                "error_type": "position_sizing"
                            })
                            errors.append(f"[{profile_name}] {size_reason}")
                            continue
                        
                        # Update alert with calculated quantity
                        alert.quantity = str(quantity)
                        apiserver_logger.info(
                            f"[{profile_name}] Calculated position size: {quantity:.6f} - {size_reason}"
                        )
                                                        
                # . OVERRIDE PROFILE SETTINGS IF PROVIDED IN ALERT
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
                result = await adapter.process_tradingview_alert(
                    alert,
                    profile_name=profile_name,
                    source=TradeReason.WEBHOOK,
                    reason_summary=reasons,
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
            sizing_failed   = sum(1 for r in results  if r.get("error_type") == "position_sizing")

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
                        summary += f"✓ {profile_name}: {icon} ${profit:.2f}\n"
                    else:
                        summary += f"✓ {profile_name}: Price: ${result.get('executed_price', 'N/A')}\n"
                else:
                    error_type = result.get('error_type', 'unknown')
                    if error_type == 'insufficient_balance':
                        summary += f"⊘ {profile_name}: No balance\n"
                    elif error_type == 'trend_filter':
                        summary += f"⊘ {profile_name}: Trend bearish\n"
                    elif error_type == 'position_sizing':
                        summary += f"⊘ {profile_name}: Position limit\n"
                    else:
                        summary += f"✗ {profile_name}: {result.get('error', 'Failed')}\n"

            # Only send if at least one profile succeeded OR if failures aren't just balance/trend issues
            if (no_balance + trend_filtered + atr_filtered + circuit_blocked + regime_blocked) < total_count:
            #if success_count > 0 or (trend_filtered > 0 and trend_filtered != total_count):
                await telegram.send_message(summary)
            else:
                apiserver_logger.debug(f"Telegram alert: All profiles filtered\n {summary}")


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
                "trend_filtered_count": trend_filtered if 'trend_filtered' in locals() else 0,
                "sizing_failed_count": sizing_failed if 'sizing_failed' in locals() else 0
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
    return portfolio.get_portfolio_summary(profile_name=profile_name, quote_asset=quote_asset)


@app.get("/positions", dependencies=[Depends(require_read_permission)])
async def get_user_open_positions(
    current_user=Depends(get_dashboard_user),
):
    """
    Return all open DB positions across every profile the logged-in user can access.
    Enriches each row with live mark price and unrealised PnL from the price cache.
    """
    from db.crud import get_open_positions
    from db.utils import get_db_session
    from cache.price_cache import get_price_cache

    price_cache = get_price_cache()
    result = []

    with get_db_session() as db:
        for profile_name in current_user.profiles:
            positions = get_open_positions(db, profile_name)
            for pos in positions:
                raw_mark = price_cache.get_price(pos.symbol)
                try:
                    mark = float(raw_mark) if raw_mark is not None else None
                    entry = float(pos.entry_price)
                    qty = float(pos.remaining_quantity or pos.quantity)
                    unrealised_pnl = round((mark - entry) * qty, 4) if mark is not None else None
                    pnl_pct = round(((mark - entry) / entry) * 100, 3) if mark and entry else None
                except (TypeError, ValueError, ZeroDivisionError):
                    mark = None
                    unrealised_pnl = None
                    pnl_pct = None

                result.append({
                    "profile_name":       profile_name,
                    "symbol":             pos.symbol,
                    "side":               "long",
                    "quantity":           str(pos.remaining_quantity or pos.quantity),
                    "entry_price":        str(pos.entry_price),
                    "mark_price":         mark,
                    "unrealised_pnl":     unrealised_pnl,
                    "pnl_pct":            pnl_pct,
                    "tp_price":           str(pos.tp_price) if pos.tp_price else None,
                    "sl_price":           str(pos.sl_price) if pos.sl_price else None,
                    "trailing_sl_price":  str(pos.trailing_sl_price) if pos.trailing_sl_price else None,
                    "trailing_stop_armed": pos.trailing_stop_armed,
                    "created_at":         pos.created_at.isoformat() if pos.created_at else None,
                })

    return result

@app.get("/portfolio/{profile_name}/total", dependencies=[Depends(require_read_permission)])
def get_total_portfolio_value(profile_name: str, quote_asset: str = "USDC"):
    """Get total portfolio value"""
    portfolio = get_portfolio_cache()
    total = portfolio.get_total_value(profile_name=profile_name,quote_asset=quote_asset)

    return {
        "total_value": str(total),
        "quote_asset": quote_asset
    }

@app.get("/accounts/{account_id}/portfolio", dependencies=[Depends(require_read_permission)])
def get_account_portfolio(account_id: int, quote_asset: str = "USDC"):
    """
    Get portfolio value for an exchange account.
    Reads the balance cache keyed by account (no double-counting across profiles).
    Positions are aggregated from all profiles linked to this account.
    """
    from cache.balance_cache import get_balance_cache
    from cache.price_cache import get_price_cache
    from cache.portfolio_cache import get_portfolio_cache
    from decimal import Decimal

    cache = get_balance_cache()
    price_cache = get_price_cache()
    account_key = f"account_{account_id}"
    balances = cache.get_account_balances(account_key)

    if not balances:
        # Fall back to first profile for this account
        pm = get_profile_manager()
        if pm:
            canonical = pm.get_canonical_profile_for_account(account_id)
            if canonical:
                balances = cache.get_profile_balances(canonical.name)

    if not balances:
        return {
            "account_id": account_id,
            "total_value": "0",
            "assets": [],
            "error": "No balance data cached for this account"
        }

    DUST = Decimal("0.0001")
    assets = []
    total_value = Decimal("0")

    for asset, info in balances.items():
        avail  = Decimal(info.get("available", "0"))
        locked = Decimal(info.get("locked",    "0"))
        staked = Decimal(info.get("staked",    "0"))
        total_qty = avail + locked + staked
        if total_qty < DUST:
            continue
        price = Decimal("1") if asset == quote_asset else (price_cache.get_price(f"{asset}_{quote_asset}") or Decimal("0"))
        val = round(total_qty * price, 2)
        if val < Decimal("0.01"):
            continue
        assets.append({
            "asset":       asset,
            "total":       str(total_qty),
            "price":       str(price),
            "total_value": str(val),
        })
        total_value += val

    assets.sort(key=lambda x: Decimal(x["total_value"]), reverse=True)
    return {
        "account_id":  account_id,
        "total_value": str(round(total_value, 2)),
        "asset_count": len(assets),
        "assets":      assets,
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
async def tradingview_trend_webhook(alert: TrendUpdateAlert, background_tasks: BackgroundTasks):
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

        # Add the work to the background queue
        background_tasks.add_task(sync_trend_updates, alert.trends)
        
        return {"success": True, "message": "Processing in background"}        
        # Update trend cache
        # trend_cache = get_trend_cache()
        
        # for trend_data in alert.trends:
        #     trend_cache.update(trend_data)
        
        # return {
        #     "success": True,
        #     "message": f"Updated trends for {len(alert.trends)} symbol(s)",
        #     "cache_info": trend_cache.get_cache_info()
        # }
        
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error processing trend update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

def sync_trend_updates(trends):
    trend_cache = get_trend_cache()
    for trend_data in trends:
        trend_cache.update(trend_data)

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
    from db.crud import get_active_symbols
    from db.utils import get_db_session
    with get_db_session() as db:
        db_tickers = get_active_symbols(db)
    symbols = db_tickers if db_tickers else ["SOL_USDC", "ETH_USDC", "HYPE_USDC", "BTC_USDC"]

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
        try:
            adapter = get_adapter(profile)
            result = adapter.order_buy(
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
        


@app.post("/config/symbol/{profile_name}/{symbol}", dependencies=[Depends(require_admin_permission)])
async def set_symbol_config(
    profile_name: str,
    symbol: str,
    config: SymbolConfigRequest
):
    """
    Set symbol-specific trading configuration
    
    Example:
    POST /config/symbol/default/SOL_USDC
    {
        "order_size_usdc": 150.0,
        "max_position_size_pct": 15.0
    }
    """
    from db.utils import get_db_session
    from db.crud import upsert_symbol_config
    from cache.symbol_cache import get_symbol_cache

    # Validate profile exists
    profile_manager = get_profile_manager()
    if not profile_manager.has_profile(profile_name):
        raise HTTPException(status_code=404, detail=f"Profile {profile_name} not found")

    try:
        with get_db_session() as db:
            symbol_config = upsert_symbol_config(
                db,
                profile_name=profile_name,
                symbol=symbol,
                order_size_usdc=config.order_size_usdc,
                max_position_size_pct=config.max_position_size_pct,
                enabled=config.enabled
            )
            get_symbol_cache().refresh(db)

            return {
                "success": True,
                "message": f"Symbol config updated for {symbol}",
                "config": {
                    "profile": profile_name,
                    "symbol": symbol,
                    "order_size_usdc": str(symbol_config.order_size_usdc),
                    "max_position_size_pct": str(symbol_config.max_position_size_pct) if symbol_config.max_position_size_pct else None,
                    "enabled": symbol_config.enabled
                }
            }
    
    except Exception as e:
        apiserver_logger.error(f"Error setting symbol config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/config/symbol/{profile_name}/{symbol}", dependencies=[Depends(require_read_permission)])
async def get_symbol_config_endpoint(profile_name: str, symbol: str):
    """Get symbol-specific configuration"""
    from db.utils import get_db_session
    from db.crud import get_symbol_config
    
    try:
        with get_db_session() as db:
            config = get_symbol_config(db, profile_name, symbol)
            
            if not config:
                raise HTTPException(
                    status_code=404,
                    detail=f"No config found for {symbol} in profile {profile_name}"
                )
            
            return {
                "profile": profile_name,
                "symbol": symbol,
                "order_size_usdc": str(config.order_size_usdc),
                "max_position_size_pct": str(config.max_position_size_pct) if config.max_position_size_pct else None,
                "enabled": config.enabled,
                "created_at": config.created_at.isoformat(),
                "updated_at": config.updated_at.isoformat()
            }
    
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error getting symbol config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/config/symbols/{profile_name}", dependencies=[Depends(require_read_permission)])
async def get_all_symbol_configs(profile_name: str):
    """Get all symbol configurations for a profile"""
    from db.utils import get_db_session
    from db.crud import get_all_symbol_configs
    
    # Validate profile exists
    profile_manager = get_profile_manager()
    if not profile_manager.has_profile(profile_name):
        raise HTTPException(status_code=404, detail=f"Profile {profile_name} not found")
    
    try:
        with get_db_session() as db:
            configs = get_all_symbol_configs(db, profile_name)
            
            return {
                "profile": profile_name,
                "configs": [
                    {
                        "symbol": c.symbol,
                        "order_size_usdc": str(c.order_size_usdc),
                        "max_position_size_pct": str(c.max_position_size_pct) if c.max_position_size_pct else None,
                        "enabled": c.enabled,
                        "updated_at": c.updated_at.isoformat()
                    }
                    for c in configs
                ]
            }
    
    except Exception as e:
        apiserver_logger.error(f"Error getting symbol configs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/config/symbol/{profile_name}/{symbol}", dependencies=[Depends(require_admin_permission)])
async def delete_symbol_config_endpoint(profile_name: str, symbol: str):
    """Delete (disable) symbol-specific configuration"""
    from db.utils import get_db_session
    from db.crud import delete_symbol_config
    from cache.symbol_cache import get_symbol_cache

    try:
        with get_db_session() as db:
            success = delete_symbol_config(db, profile_name, symbol)

            if not success:
                raise HTTPException(
                    status_code=404,
                    detail=f"No config found for {symbol} in profile {profile_name}"
                )

            get_symbol_cache().refresh(db)

            return {
                "success": True,
                "message": f"Symbol config deleted for {symbol}"
            }
    
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error deleting symbol config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/config/symbol/{profile_name}/{symbol}/test", dependencies=[Depends(require_read_permission)])
async def test_position_sizing(profile_name: str, symbol: str):
    """
    Test position sizing calculation without executing trade
    Useful for debugging and configuration
    """
    from utils.position_calculator import get_position_size_calculator
    from cache.price_cache import get_price_cache
    
    # Validate profile exists
    profile_manager = get_profile_manager()
    profile = profile_manager.get(profile_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile {profile_name} not found")
    
    try:
        calculator = get_position_size_calculator()
        quantity, reason = calculator.calculate_buy_quantity(
            symbol=symbol,
            profile=profile,
            quote_asset="USDC"
        )
        
        # Get current price for value calculation
        price_cache = get_price_cache()
        price = price_cache.get_price(symbol)
        
        if quantity and price:
            value = float(quantity) * float(price)
            return {
                "success": True,
                "symbol": symbol,
                "profile": profile_name,
                "calculated_quantity": str(quantity),
                "current_price": str(price),
                "order_value_usdc": round(value, 2),
                "reason": reason
            }
        else:
            return {
                "success": False,
                "symbol": symbol,
                "profile": profile_name,
                "error": reason,
                "current_price": str(price) if price else "N/A"
            }
    
    except Exception as e:
        apiserver_logger.error(f"Error testing position sizing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _ind_profile_or_404(db, profile_name: str):
    from db.models import TradingProfileDB
    prof = db.query(TradingProfileDB).filter(
        TradingProfileDB.name == profile_name,
        TradingProfileDB.is_active == True
    ).first()
    if not prof:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")
    return prof

def _ind_or_404(db, indicator_id: int, profile_id: int):
    from db.models import IndicatorDB
    ind = db.query(IndicatorDB).filter(
        IndicatorDB.id == indicator_id,
        IndicatorDB.profile_id == profile_id
    ).first()
    if not ind:
        raise HTTPException(status_code=404, detail=f"Indicator {indicator_id} not found")
    return ind


@app.get("/indicators/{profile_name}", dependencies=[Depends(require_read_permission)])
async def list_indicators(profile_name: str, category: Optional[str] = None):
    """
    List all indicators for a profile.
    Optionally filter by category: ?category=trend or ?category=entry
    """
    from db.utils import get_db_session
    from db.models import IndicatorDB

    try:
        with get_db_session() as db:
            prof = _ind_profile_or_404(db, profile_name)
            q = db.query(IndicatorDB).filter(IndicatorDB.profile_id == prof.id)
            if category:
                q = q.filter(IndicatorDB.category == category)
            indicators = q.order_by(IndicatorDB.category, IndicatorDB.id).all()
            return [IndicatorOut.model_validate(i) for i in indicators]
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error listing indicators: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/indicators/{profile_name}", dependencies=[Depends(require_admin_permission)])
async def create_indicator(profile_name: str, body: IndicatorCreate):
    """Add a new indicator to a profile."""
    from db.utils import get_db_session
    from db.models import IndicatorDB
    from services.profile_manager import get_profile_manager, refresh_profiles_from_db

    try:
        with get_db_session() as db:
            prof = _ind_profile_or_404(db, profile_name)
            ind = IndicatorDB(
                profile_id=prof.id,
                category=body.category,
                indicator_type=body.indicator_type,
                params=body.params,
                is_hard_stop=body.is_hard_stop,
                enabled=body.enabled,
            )
            db.add(ind)
            
            from services.audit import write_audit, snapshot_indicator
            write_audit(
                db=db,
                type="indicator",
                subtype=body.category,            # "trend" | "entry" | "exit"
                action="create",
                entity_id=ind.id,
                entity_name=f"{ind.indicator_type} ({profile_name})",
                before=None,
                after=snapshot_indicator(ind),
            )            
            db.commit()
            db.refresh(ind)
            apiserver_logger.info(
                f"Created indicator [{body.indicator_type}] ({body.category}) "
                f"for profile '{profile_name}' (id={ind.id})"
            )

            refresh_profiles_from_db()
            return IndicatorOut.model_validate(ind)
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error creating indicator: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/indicators/{profile_name}/{indicator_id}", dependencies=[Depends(require_admin_permission)])
async def update_indicator(profile_name: str, indicator_id: int, body: IndicatorUpdate):
    """
    Full replace of an indicator row — overwrites category, indicator_type,
    params, is_hard_stop, and enabled. Keeps the same id and profile_id.
    """
    from db.utils import get_db_session
    from services.profile_manager import get_profile_manager, refresh_profiles_from_db

    try:
        with get_db_session() as db:
            prof = _ind_profile_or_404(db, profile_name)
            ind = _ind_or_404(db, indicator_id, prof.id)

            from services.audit import write_audit, snapshot_indicator
            before_snap = snapshot_indicator(ind)

            ind.category       = body.category
            ind.indicator_type = body.indicator_type
            ind.params         = body.params
            ind.is_hard_stop   = body.is_hard_stop
            ind.enabled        = body.enabled

            write_audit(
                db=db,
                type="indicator",
                subtype=body.category,
                action="update",
                entity_id=ind.id,
                entity_name=f"{ind.indicator_type} ({profile_name})",
                before=before_snap,
                after=snapshot_indicator(ind),
            )

            db.commit()
            db.refresh(ind)
            apiserver_logger.info(
                f"Updated indicator id={indicator_id} [{body.indicator_type}] "
                f"for profile '{profile_name}'"
            )
            refresh_profiles_from_db()
            return IndicatorOut.model_validate(ind)
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error updating indicator: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/indicators/{profile_name}/{indicator_id}/toggle", dependencies=[Depends(require_admin_permission)])
async def toggle_indicator(profile_name: str, indicator_id: int):
    """Quick enable/disable toggle without a full PUT."""
    from db.utils import get_db_session
    from services.profile_manager import get_profile_manager, refresh_profiles_from_db

    try:
        with get_db_session() as db:
            prof = _ind_profile_or_404(db, profile_name)
            ind = _ind_or_404(db, indicator_id, prof.id)

            from services.audit import write_audit, snapshot_indicator
            before_snap = snapshot_indicator(ind)

            ind.enabled = not ind.enabled

            write_audit(
                db=db,
                type="indicator",
                subtype=ind.category,
                action="toggle",
                entity_id=ind.id,
                entity_name=f"{ind.indicator_type} ({profile_name})",
                before=before_snap,
                after=snapshot_indicator(ind),
            )

            db.commit()
            db.refresh(ind)
            apiserver_logger.info(
                f"Toggled indicator id={indicator_id} enabled={ind.enabled} "
                f"for profile '{profile_name}'"
            )
            refresh_profiles_from_db()
            return IndicatorOut.model_validate(ind)
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error toggling indicator: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/indicators/{profile_name}/{indicator_id}", dependencies=[Depends(require_admin_permission)])
async def delete_indicator(profile_name: str, indicator_id: int):
    """Permanently delete an indicator."""
    from db.utils import get_db_session
    from services.profile_manager import get_profile_manager, refresh_profiles_from_db

    try:
        with get_db_session() as db:
            prof = _ind_profile_or_404(db, profile_name)
            ind = _ind_or_404(db, indicator_id, prof.id)

            from services.audit import write_audit, snapshot_indicator
            write_audit(
                db=db,
                type="indicator",
                subtype=ind.category,
                action="delete",
                entity_id=ind.id,
                entity_name=f"{ind.indicator_type} ({profile_name})",
                before=snapshot_indicator(ind),
                after=None,
            )
            db.delete(ind)
            db.commit()
            apiserver_logger.info(
                f"Deleted indicator id={indicator_id} for profile '{profile_name}'"
            )
            refresh_profiles_from_db()
            return {"success": True, "message": f"Indicator {indicator_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error deleting indicator: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))




# ── AI Monitor ────────────────────────────────────────────────────────────────

@app.get("/ai-monitor/report/{profile_name}", dependencies=[Depends(require_read_permission)])
async def get_ai_monitor_report(profile_name: str, days: int = 30):
    """
    Returns AI vs rules-based signal comparison report for the dashboard.

    Queries ai_signal_log for all resolved signals in the last N days,
    computes per-pair win rates, R:R, confidence stats, and skip accuracy,
    then returns the shape expected by the AI Monitor panel in index.html.

    Query params:
        days  - lookback window (default 30)
    """
    from db.utils import get_db_session
    from db.models import AISignalLog
    from sqlalchemy import func, case, and_
    from datetime import datetime, timedelta, timezone

    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        with get_db_session() as session:

            # ── 1. Per-pair aggregated stats ──────────────────────────────────
            rows = session.query(
                AISignalLog.pair,

                # AI stats
                func.count(AISignalLog.id).label("total"),
                func.count(
                    case((AISignalLog.ai_decision == "ENTER", 1))
                ).label("ai_entries"),
                func.count(
                    case((and_(AISignalLog.ai_decision == "ENTER",
                               AISignalLog.outcome_result == "WIN"), 1))
                ).label("ai_wins"),
                func.count(
                    case((and_(AISignalLog.ai_decision == "ENTER",
                               AISignalLog.outcome_result == "LOSS"), 1))
                ).label("ai_losses"),
                func.avg(
                    case((and_(AISignalLog.ai_decision == "ENTER",
                               AISignalLog.outcome_resolved == True),
                          AISignalLog.outcome_pnl_pct))
                ).label("ai_avg_pnl"),
                func.avg(
                    case((AISignalLog.ai_decision == "ENTER",
                          AISignalLog.ai_confidence))
                ).label("ai_avg_conf"),

                # High-confidence AI stats (conf > 0.75)
                func.count(
                    case((and_(AISignalLog.ai_decision == "ENTER",
                               AISignalLog.ai_confidence > 0.75,
                               AISignalLog.outcome_result == "WIN"), 1))
                ).label("hc_wins"),
                func.count(
                    case((and_(AISignalLog.ai_decision == "ENTER",
                               AISignalLog.ai_confidence > 0.75), 1))
                ).label("hc_entries"),

                # Skip accuracy: AI=SKIP, rules=ENTER → how many were losses?
                func.count(
                    case((and_(AISignalLog.ai_decision == "SKIP",
                               AISignalLog.rules_decision == "ENTER"), 1))
                ).label("ai_skips_over_rules"),
                func.count(
                    case((and_(AISignalLog.ai_decision == "SKIP",
                               AISignalLog.rules_decision == "ENTER",
                               AISignalLog.outcome_result == "LOSS"), 1))
                ).label("ai_skips_correct"),

                # Rules stats
                func.count(
                    case((AISignalLog.rules_decision == "ENTER", 1))
                ).label("rules_entries"),
                func.count(
                    case((and_(AISignalLog.rules_decision == "ENTER",
                               AISignalLog.outcome_result == "WIN"), 1))
                ).label("rules_wins"),
                func.count(
                    case((and_(AISignalLog.rules_decision == "ENTER",
                               AISignalLog.outcome_result == "LOSS"), 1))
                ).label("rules_losses"),
                func.avg(
                    case((and_(AISignalLog.rules_decision == "ENTER",
                               AISignalLog.outcome_resolved == True),
                          AISignalLog.outcome_pnl_pct))
                ).label("rules_avg_pnl"),

            ).filter(
                AISignalLog.profile_name == profile_name,
                AISignalLog.timestamp >= since,
                AISignalLog.outcome_resolved == True,
            ).group_by(AISignalLog.pair).all()

            # ── 2. Avg R:R per pair (win_avg / abs(loss_avg)) ─────────────────
            rr_rows = session.query(
                AISignalLog.pair,
                func.avg(
                    case((and_(AISignalLog.ai_decision == "ENTER",
                               AISignalLog.outcome_result == "WIN"),
                          AISignalLog.outcome_pnl_pct))
                ).label("ai_avg_win"),
                func.avg(
                    case((and_(AISignalLog.ai_decision == "ENTER",
                               AISignalLog.outcome_result == "LOSS"),
                          AISignalLog.outcome_pnl_pct))
                ).label("ai_avg_loss"),
                func.avg(
                    case((and_(AISignalLog.rules_decision == "ENTER",
                               AISignalLog.outcome_result == "WIN"),
                          AISignalLog.outcome_pnl_pct))
                ).label("rules_avg_win"),
                func.avg(
                    case((and_(AISignalLog.rules_decision == "ENTER",
                               AISignalLog.outcome_result == "LOSS"),
                          AISignalLog.outcome_pnl_pct))
                ).label("rules_avg_loss"),
            ).filter(
                AISignalLog.profile_name == profile_name,
                AISignalLog.timestamp >= since,
                AISignalLog.outcome_resolved == True,
            ).group_by(AISignalLog.pair).all()

            rr_map = {r.pair: r for r in rr_rows}

            # ── 3. Recent signals (last 50, unresolved or resolved) ───────────
            recent = session.query(AISignalLog).filter(
                AISignalLog.profile_name == profile_name,
                AISignalLog.timestamp >= since,
            ).order_by(AISignalLog.timestamp.desc()).limit(50).all()

            # ── 4. Build per-pair stat objects ────────────────────────────────
            stats = []
            pairs = []

            for r in rows:
                rr = rr_map.get(r.pair)

                ai_entries  = int(r.ai_entries    or 0)
                ai_wins     = int(r.ai_wins       or 0)
                ai_losses   = int(r.ai_losses     or 0)
                hc_wins     = int(r.hc_wins       or 0)
                hc_entries  = int(r.hc_entries    or 0)
                skips       = int(r.ai_skips_over_rules or 0)
                skips_right = int(r.ai_skips_correct    or 0)

                rules_entries = int(r.rules_entries or 0)
                rules_wins    = int(r.rules_wins    or 0)

                ai_wr    = round(ai_wins    / ai_entries    * 100, 1) if ai_entries    else 0.0
                rules_wr = round(rules_wins / rules_entries * 100, 1) if rules_entries else 0.0
                hc_wr    = round(hc_wins    / hc_entries    * 100, 1) if hc_entries    else None
                skip_acc = round(skips_right / skips * 100, 1)        if skips         else None

                # R:R = avg_win / abs(avg_loss)
                def _rr(avg_win, avg_loss):
                    if avg_win is None or avg_loss is None or float(avg_loss) == 0:
                        return 0.0
                    return round(float(avg_win) / abs(float(avg_loss)), 2)

                ai_rr    = _rr(rr.ai_avg_win,    rr.ai_avg_loss)    if rr else 0.0
                rules_rr = _rr(rr.rules_avg_win, rr.rules_avg_loss) if rr else 0.0

                pairs.append(r.pair)
                stats.append({
                    "pair": r.pair,
                    "ai": {
                        "total":        int(r.total or 0),
                        "entries":      ai_entries,
                        "win_rate":     ai_wr,
                        "avg_rr":       ai_rr,
                        "avg_pnl":      round(float(r.ai_avg_pnl), 3) if r.ai_avg_pnl else 0.0,
                        "avg_conf":     round(float(r.ai_avg_conf), 3) if r.ai_avg_conf else None,
                        "hc_win_rate":  hc_wr,
                        "skip_acc":     skip_acc,
                    },
                    "rules": {
                        "total":        int(r.total or 0),
                        "entries":      rules_entries,
                        "win_rate":     rules_wr,
                        "avg_rr":       rules_rr,
                        "avg_pnl":      round(float(r.rules_avg_pnl), 3) if r.rules_avg_pnl else 0.0,
                    },
                })

            # ── 5. Verdict ────────────────────────────────────────────────────
            verdict, recommendation = _ai_generate_verdict(stats)

            # ── 6. Recent signals payload ─────────────────────────────────────
            recent_payload = [
                {
                    "id":             sig.id,
                    "time":           sig.timestamp.strftime("%H:%M") if sig.timestamp else "—",
                    "pair":           sig.pair,
                    "ai_decision":    sig.ai_decision,
                    "rules_decision": sig.rules_decision,
                    "ai_confidence":  float(sig.ai_confidence) if sig.ai_confidence else None,
                    "outcome":        sig.outcome_result,
                    "pnl_pct":        float(sig.outcome_pnl_pct) if sig.outcome_pnl_pct else None,
                    "reasoning":      sig.ai_reasoning or "",
                    "risk_flags":     sig.ai_risk_flags or [],
                }
                for sig in recent
            ]

            return {
                "profile_name":    profile_name,
                "period_days":     days,
                "generated_at":    datetime.now(timezone.utc).isoformat(),
                "verdict":         verdict,
                "recommendation":  recommendation,
                "pairs":           pairs,
                "stats":           stats,
                "recent_signals":  recent_payload,
            }

    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error building AI monitor report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ai-monitor/signals/{profile_name}", dependencies=[Depends(require_read_permission)])
async def get_ai_signal_log(
    profile_name: str,
    days: int = 7,
    pair: Optional[str] = None,
    decision: Optional[str] = None,
    outcome: Optional[str] = None,
    limit: int = 100,
):
    """
    Paginated signal log with optional filters.
    Useful for drilling into specific pairs or outcomes from the dashboard.

    Query params:
        days      - lookback window (default 7)
        pair      - filter by pair e.g. SOL_USDC
        decision  - filter ai_decision: ENTER | SKIP | WAIT
        outcome   - filter outcome_result: WIN | LOSS | BREAKEVEN
        limit     - max rows returned (default 100, max 500)
    """
    from db.utils import get_db_session
    from db.models import AISignalLog
    from datetime import datetime, timedelta, timezone

    limit = min(limit, 500)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        with get_db_session() as session:
            q = session.query(AISignalLog).filter(
                AISignalLog.profile_name == profile_name,
                AISignalLog.timestamp    >= since,
            )
            if pair:
                q = q.filter(AISignalLog.pair == pair.upper())
            if decision:
                q = q.filter(AISignalLog.ai_decision == decision.upper())
            if outcome:
                q = q.filter(AISignalLog.outcome_result == outcome.upper())

            sigs = q.order_by(AISignalLog.timestamp.desc()).limit(limit).all()

            return {
                "profile_name": profile_name,
                "filters": {"days": days, "pair": pair, "decision": decision, "outcome": outcome},
                "count": len(sigs),
                "signals": [
                    {
                        "id":               sig.id,
                        "pair":             sig.pair,
                        "timestamp":        sig.timestamp.isoformat() if sig.timestamp else None,
                        "candle_time":      sig.candle_time.isoformat() if sig.candle_time else None,
                        "ai_decision":      sig.ai_decision,
                        "ai_confidence":    float(sig.ai_confidence)   if sig.ai_confidence   else None,
                        "ai_reasoning":     sig.ai_reasoning,
                        "ai_risk_flags":    sig.ai_risk_flags or [],
                        "ai_entry_price":   float(sig.ai_entry_price)  if sig.ai_entry_price  else None,
                        "ai_stop_loss":     float(sig.ai_stop_loss)    if sig.ai_stop_loss    else None,
                        "ai_take_profit":   float(sig.ai_take_profit)  if sig.ai_take_profit  else None,
                        "ai_pos_size_pct":  float(sig.ai_position_size_pct) if sig.ai_position_size_pct else None,
                        "rules_decision":   sig.rules_decision,
                        "rules_entry_price":float(sig.rules_entry_price) if sig.rules_entry_price else None,
                        "gate_60m_data":    sig.gate_60m_data,
                        "outcome_resolved": sig.outcome_resolved,
                        "outcome_result":   sig.outcome_result,
                        "outcome_pnl_pct":  float(sig.outcome_pnl_pct) if sig.outcome_pnl_pct else None,
                        "outcome_exit_price":float(sig.outcome_exit_price) if sig.outcome_exit_price else None,
                        "outcome_candles_held": sig.outcome_candles_held,
                    }
                    for sig in sigs
                ],
            }

    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error fetching AI signal log: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ai-monitor/resolve-outcomes/{profile_name}", dependencies=[Depends(require_admin_permission)])
async def trigger_outcome_resolution(profile_name: str, background_tasks: BackgroundTasks):
    """
    Manually trigger OutcomeResolver for a profile.
    Normally runs on a schedule — this lets you force a resolution pass
    from the dashboard or for testing.
    """
    from services.ai_signal_handler import get_ai_signal_handler

    async def _run():
        try:
            from db.utils import get_db_session
            from db.models import AISignalLog
            from datetime import datetime, timezone
            from cache.price_cache import get_price_cache

            price_cache = get_price_cache()

            def _fetch_candles(pair, from_time):
                # Adapt to however you query historical OHLCV in your system.
                # trend_cache stores recent candle history, so we use that as a fallback.
                trend_cache = get_trend_cache()
                key = f"{pair}_15"
                return trend_cache._candle_history.get(key, [])

            with get_db_session() as session:
                pending = session.query(AISignalLog).filter(
                    AISignalLog.profile_name    == profile_name,
                    AISignalLog.outcome_resolved == False,
                    AISignalLog.ai_decision      == "ENTER",
                ).order_by(AISignalLog.candle_time.asc()).limit(100).all()

                resolved = 0
                for sig in pending:
                    if not sig.ai_entry_price or not sig.ai_stop_loss or not sig.ai_take_profit:
                        continue
                    candles = _fetch_candles(sig.pair, sig.candle_time)
                    entry = float(sig.ai_entry_price)
                    sl    = float(sig.ai_stop_loss)
                    tp    = float(sig.ai_take_profit)

                    for i, c in enumerate(candles):
                        lo = float(c.get("low",  entry))
                        hi = float(c.get("high", entry))
                        if lo <= sl:
                            pnl = round((sl - entry) / entry * 100, 4)
                            sig.outcome_resolved     = True
                            sig.outcome_result       = "LOSS"
                            sig.outcome_pnl_pct      = pnl
                            sig.outcome_exit_price   = sl
                            sig.outcome_candles_held = i + 1
                            resolved += 1
                            break
                        if hi >= tp:
                            pnl = round((tp - entry) / entry * 100, 4)
                            sig.outcome_resolved     = True
                            sig.outcome_result       = "WIN"
                            sig.outcome_pnl_pct      = pnl
                            sig.outcome_exit_price   = tp
                            sig.outcome_candles_held = i + 1
                            resolved += 1
                            break

                session.commit()
                apiserver_logger.info(
                    f"[AI Outcome Resolver] {profile_name}: resolved {resolved}/{len(pending)} pending signals"
                )

        except Exception as e:
            apiserver_logger.error(f"Outcome resolution error: {e}", exc_info=True)

    background_tasks.add_task(_run)
    return {"message": "Outcome resolution started in background", "profile": profile_name}


def _ai_generate_verdict(stats: list) -> tuple[str, str]:
    """
    Generates a plain-English verdict + recommendation from per-pair stats.
    Mirrors the logic in signal_analytics.py but runs inline in the API.
    """
    if not stats:
        return (
            "No resolved AI signals yet.",
            "Deploy an AI_AGENT profile and let it run in shadow mode for 2–4 weeks to collect data."
        )

    # Only consider pairs with enough data to be meaningful
    qualified = [
        s for s in stats
        if s["ai"]["entries"] >= 5 and s["rules"]["entries"] >= 5
    ]

    if not qualified:
        total_entries = sum(s["ai"]["entries"] for s in stats)
        return (
            f"Collecting data — {total_entries} AI entry signal(s) resolved so far.",
            "Need at least 5 resolved AI entries per pair before comparison is meaningful. Keep running in shadow mode."
        )

    avg_wr_delta = sum(
        s["ai"]["win_rate"] - s["rules"]["win_rate"] for s in qualified
    ) / len(qualified)

    avg_rr_delta = sum(
        s["ai"]["avg_rr"] - s["rules"]["avg_rr"] for s in qualified
    ) / len(qualified)

    n = len(qualified)

    if avg_wr_delta > 5 and avg_rr_delta > 0.1:
        verdict = (
            f"AI entry agent outperforming rule-based system: "
            f"+{avg_wr_delta:.1f}% win rate, +{avg_rr_delta:.2f} avg R:R across {n} pair(s)."
        )
        recommendation = (
            "Consider promoting AI profile to live trading with 10–20% of normal position size. "
            "Monitor for 2 more weeks before full allocation."
        )
    elif avg_wr_delta > 5:
        verdict = (
            f"AI shows higher win rate (+{avg_wr_delta:.1f}%) but similar R:R. "
            "May be taking more selective entries."
        )
        recommendation = (
            "Promising. Review whether AI is being too conservative on sizing. "
            "Check high-confidence trades specifically."
        )
    elif avg_wr_delta < -5:
        verdict = (
            f"Rule-based system outperforming AI by {abs(avg_wr_delta):.1f}% win rate across {n} pair(s)."
        )
        recommendation = (
            "Review AI reasoning logs for losing trades. "
            "Consider refining the system prompt with specific failure patterns observed."
        )
    else:
        verdict = (
            f"Systems performing similarly (win rate delta: {avg_wr_delta:+.1f}%, "
            f"R:R delta: {avg_rr_delta:+.2f}) across {n} pair(s)."
        )
        recommendation = (
            "Check skip accuracy — if AI correctly identifies losers, it may add value "
            "even at similar win rates. Extend data collection period."
        )

    return verdict, recommendation

@app.get("/ai-prompts", dependencies=[Depends(require_read_permission)])
async def list_ai_prompts(
    strategy_type: Optional[str] = None,
    profile_id: Optional[int] = None,
    is_active: Optional[bool] = None,
):
    """List all AI prompts, with optional filters."""
    from db.utils import get_db_session
    from db.models import AIPrompt
 
    try:
        with get_db_session() as db:
            q = db.query(AIPrompt)
            if strategy_type is not None:
                q = q.filter(AIPrompt.strategy_type == strategy_type)
            if profile_id is not None:
                q = q.filter(AIPrompt.profile_id == profile_id)
            if is_active is not None:
                q = q.filter(AIPrompt.is_active == is_active)
            prompts = q.order_by(AIPrompt.strategy_type, AIPrompt.id).all()
            return [
                {
                    "id":            p.id,
                    "name":          p.name,
                    "strategy_type": p.strategy_type,
                    "profile_id":    p.profile_id,
                    "is_active":     p.is_active,
                    "is_default":    p.is_default,
                    "version":       p.version,
                    "notes":         p.notes,
                    "system_prompt": p.system_prompt,
                    "created_at":    p.created_at.isoformat() if p.created_at else None,
                    "updated_at":    p.updated_at.isoformat() if p.updated_at else None,
                }
                for p in prompts
            ]
    except Exception as e:
        apiserver_logger.error(f"Error listing AI prompts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
 
 
@app.get("/ai-prompts/{prompt_id}", dependencies=[Depends(require_read_permission)])
async def get_ai_prompt(prompt_id: int):
    """Get a single AI prompt by ID."""
    from db.utils import get_db_session
    from db.models import AIPrompt
 
    try:
        with get_db_session() as db:
            p = db.query(AIPrompt).filter(AIPrompt.id == prompt_id).first()
            if not p:
                raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")
            return {
                "id":            p.id,
                "name":          p.name,
                "strategy_type": p.strategy_type,
                "profile_id":    p.profile_id,
                "is_active":     p.is_active,
                "is_default":    p.is_default,
                "version":       p.version,
                "notes":         p.notes,
                "system_prompt": p.system_prompt,
                "created_at":    p.created_at.isoformat() if p.created_at else None,
                "updated_at":    p.updated_at.isoformat() if p.updated_at else None,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
 
 
@app.post("/ai-prompts", dependencies=[Depends(require_admin_permission)])
async def create_ai_prompt(body: AIPromptCreate):
    """Create a new AI prompt."""
    from db.utils import get_db_session
    from db.models import AIPrompt
    from services.audit import write_audit, snapshot_ai_prompt
 
    try:
        with get_db_session() as db:
            p = AIPrompt(
                name=body.name,
                strategy_type=body.strategy_type,
                profile_id=body.profile_id,
                system_prompt=body.system_prompt,
                is_active=body.is_active,
                is_default=body.is_default,
                notes=body.notes,
                version=1,
            )
            db.add(p)
            db.flush()
 
            write_audit(
                db=db,
                type="ai_prompt",
                subtype=body.strategy_type or "global",
                action="create",
                entity_id=p.id,
                entity_name=body.name,
                before=None,
                after=snapshot_ai_prompt(p),
            )
 
            db.commit()
            db.refresh(p)
            apiserver_logger.info(f"Created AI prompt '{p.name}' (id={p.id})")
 
            # Invalidate prompt cache so next signal call picks up the new prompt
            from services.ai_signal_handler import get_ai_signal_handler
            get_ai_signal_handler().reload_prompt(body.strategy_type, body.profile_id)
 
            return {"id": p.id, "name": p.name, "version": p.version}
    except Exception as e:
        apiserver_logger.error(f"Error creating AI prompt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
 
 
@app.put("/ai-prompts/{prompt_id}", dependencies=[Depends(require_admin_permission)])
async def update_ai_prompt(prompt_id: int, body: AIPromptUpdate):
    """
    Update an AI prompt. Increments version automatically.
    Partial updates are supported — only non-None fields are changed.
    """
    from db.utils import get_db_session
    from db.models import AIPrompt
    from services.audit import write_audit, snapshot_ai_prompt
 
    try:
        with get_db_session() as db:
            p = db.query(AIPrompt).filter(AIPrompt.id == prompt_id).first()
            if not p:
                raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")
 
            before = snapshot_ai_prompt(p)
            old_strategy = p.strategy_type
            old_profile_id = p.profile_id
 
            if body.name          is not None: p.name          = body.name
            if body.strategy_type is not None: p.strategy_type = body.strategy_type
            if body.profile_id    is not None: p.profile_id    = body.profile_id
            if body.system_prompt is not None: p.system_prompt = body.system_prompt
            if body.is_active     is not None: p.is_active     = body.is_active
            if body.is_default    is not None: p.is_default    = body.is_default
            if body.notes         is not None: p.notes         = body.notes
 
            p.version += 1
 
            write_audit(
                db=db,
                type="ai_prompt",
                subtype=p.strategy_type or "global",
                action="update",
                entity_id=p.id,
                entity_name=p.name,
                before=before,
                after=snapshot_ai_prompt(p),
            )
 
            db.commit()
            db.refresh(p)
            apiserver_logger.info(f"Updated AI prompt id={prompt_id} to version {p.version}")
 
            # Invalidate cache for old and new keys (strategy/profile may have changed)
            from services.ai_signal_handler import get_ai_signal_handler
            handler = get_ai_signal_handler()
            handler.reload_prompt(old_strategy, old_profile_id)
            if (p.strategy_type, p.profile_id) != (old_strategy, old_profile_id):
                handler.reload_prompt(p.strategy_type, p.profile_id)
 
            return {"id": p.id, "name": p.name, "version": p.version}
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error updating AI prompt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
 
 
@app.delete("/ai-prompts/{prompt_id}", dependencies=[Depends(require_admin_permission)])
async def delete_ai_prompt(prompt_id: int):
    """Delete an AI prompt. Cannot delete the last active default prompt."""
    from db.utils import get_db_session
    from db.models import AIPrompt
    from services.audit import write_audit, snapshot_ai_prompt
 
    try:
        with get_db_session() as db:
            p = db.query(AIPrompt).filter(AIPrompt.id == prompt_id).first()
            if not p:
                raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")
 
            # Guard: refuse to delete the last active global default
            if p.is_default and p.profile_id is None and p.strategy_type is None:
                other_defaults = (
                    db.query(AIPrompt)
                    .filter(
                        AIPrompt.is_default == True,
                        AIPrompt.is_active == True,
                        AIPrompt.id != prompt_id,
                        AIPrompt.profile_id == None,
                        AIPrompt.strategy_type == None,
                    )
                    .count()
                )
                if other_defaults == 0:
                    raise HTTPException(
                        status_code=400,
                        detail="Cannot delete the last active global default prompt. "
                               "Set another prompt as default first."
                    )
 
            before = snapshot_ai_prompt(p)
            strategy_type = p.strategy_type
            profile_id    = p.profile_id
 
            write_audit(
                db=db,
                type="ai_prompt",
                subtype=strategy_type or "global",
                action="delete",
                entity_id=p.id,
                entity_name=p.name,
                before=before,
                after=None,
            )
 
            db.delete(p)
            db.commit()
            apiserver_logger.info(f"Deleted AI prompt id={prompt_id}")
 
            from services.ai_signal_handler import get_ai_signal_handler
            get_ai_signal_handler().reload_prompt(strategy_type, profile_id)
 
            return {"success": True, "message": f"Prompt {prompt_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error deleting AI prompt: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
 
 
@app.post("/ai-prompts/{prompt_id}/set-default", dependencies=[Depends(require_admin_permission)])
async def set_ai_prompt_default(prompt_id: int):
    """
    Set a prompt as the default for its (strategy_type, profile_id) scope.
    Clears is_default on any other prompt in the same scope first.
    """
    from db.utils import get_db_session
    from db.models import AIPrompt
    from services.audit import write_audit, snapshot_ai_prompt
 
    try:
        with get_db_session() as db:
            p = db.query(AIPrompt).filter(AIPrompt.id == prompt_id).first()
            if not p:
                raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")
 
            # Clear existing defaults in the same scope
            db.query(AIPrompt).filter(
                AIPrompt.strategy_type == p.strategy_type,
                AIPrompt.profile_id    == p.profile_id,
                AIPrompt.id            != prompt_id,
                AIPrompt.is_default    == True,
            ).update({"is_default": False})
 
            before = snapshot_ai_prompt(p)
            p.is_default = True
 
            write_audit(
                db=db,
                type="ai_prompt",
                subtype=p.strategy_type or "global",
                action="set_default",
                entity_id=p.id,
                entity_name=p.name,
                before=before,
                after=snapshot_ai_prompt(p),
            )
 
            db.commit()
            db.refresh(p)
            apiserver_logger.info(f"Set AI prompt id={prompt_id} as default")

            from services.ai_signal_handler import get_ai_signal_handler
            get_ai_signal_handler().reload_prompt(p.strategy_type, p.profile_id)
 
            return {"success": True, "id": p.id, "name": p.name}
    except HTTPException:
        raise
    except Exception as e:
        apiserver_logger.error(f"Error setting prompt default: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
 
 
@app.post("/ai-prompts/{prompt_id}/reload-cache", dependencies=[Depends(require_admin_permission)])
async def reload_prompt_cache(prompt_id: int):
    """Force the in-memory prompt cache to refresh for this prompt's scope."""
    from db.utils import get_db_session
    from db.models import AIPrompt
 
    try:
        with get_db_session() as db:
            p = db.query(AIPrompt).filter(AIPrompt.id == prompt_id).first()
            if not p:
                raise HTTPException(status_code=404, detail=f"Prompt {prompt_id} not found")
            
            from services.ai_signal_handler import get_ai_signal_handler
            get_ai_signal_handler().reload_prompt(p.strategy_type, p.profile_id)
            return {"success": True, "message": f"Cache refreshed for strategy={p.strategy_type} profile_id={p.profile_id}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
 

# ---------------------------------------------------------------------------
# GET /profiles  — list all profiles (active + inactive)
# ---------------------------------------------------------------------------
@app.get("/profiles", dependencies=[Depends(require_read_permission)])
async def list_profiles():
    """
    Return all trading profiles with their full DB config.
    API key/secret are returned as hints only (last 6 chars).
    """
    from db.utils import get_db_session
    from db.models import TradingProfileDB, CircuitBreakerConfig

    with get_db_session() as db:
        profiles = db.query(TradingProfileDB).order_by(TradingProfileDB.name).all()
        result = []
        for p in profiles:
            cb = db.query(CircuitBreakerConfig).filter(
                CircuitBreakerConfig.profile_name == p.name
            ).first()
            result.append(_serialize_profile(p, cb))
        return result


# ---------------------------------------------------------------------------
# GET /profiles/{profile_name}
# ---------------------------------------------------------------------------
@app.get("/profiles/{profile_name}", dependencies=[Depends(require_read_permission)])
async def get_profile_detail(profile_name: str):
    from db.utils import get_db_session
    from db.models import TradingProfileDB, CircuitBreakerConfig

    with get_db_session() as db:
        p = db.query(TradingProfileDB).filter(
            TradingProfileDB.name == profile_name
        ).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")

        cb = db.query(CircuitBreakerConfig).filter(
            CircuitBreakerConfig.profile_name == profile_name
        ).first()
        return _serialize_profile(p, cb)


# ---------------------------------------------------------------------------
# POST /profiles  — create new profile
# ---------------------------------------------------------------------------
@app.post("/profiles", dependencies=[Depends(require_admin_permission)])
async def create_profile_endpoint(body: ProfileCreateRequest, current_user=Depends(get_dashboard_user)):
    from db.utils import get_db_session
    from db.models import TradingProfileDB, CircuitBreakerConfig, ExchangeAccount
    from services.audit import write_audit
    from services.profile_manager import get_profile_manager, refresh_profiles_from_db

    with get_db_session() as db:
        # Validate profile name is unique
        existing = db.query(TradingProfileDB).filter(
            TradingProfileDB.name == body.name
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Profile '{body.name}' already exists")

        # Resolve exchange account — must exist and be active
        account = db.query(ExchangeAccount).filter(
            ExchangeAccount.id == body.account_id,
            ExchangeAccount.is_active == True,
        ).first()
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Exchange account {body.account_id} not found or inactive"
            )

        p = TradingProfileDB(
            name=body.name,
            display_name=body.display_name,
            account_id=body.account_id,
            trading_type=body.trading_type,
            strategy_type=body.strategy_type,
            take_profit_pct=body.take_profit_pct,
            stop_loss_pct=body.stop_loss_pct,
            trailing_stop_pct=body.trailing_stop_pct,
            arm_trailing_stop_pct=body.arm_trailing_stop_pct,
            use_trailing_stop=body.use_trailing_stop,
            default_order_size_usdc=body.default_order_size_usdc,
            max_position_size_pct=body.max_position_size_pct,
            max_open_positions=body.max_open_positions,
            max_portfolio_exposure_pct=body.max_portfolio_exposure_pct,
            signal_timeframe=body.signal_timeframe,
            signal_cooldown_seconds=body.signal_cooldown_seconds,
            min_signal_confidence=body.min_signal_confidence,
            min_volume_ratio=body.min_volume_ratio,
            trend_timeframe=body.trend_timeframe,
            entry_timeframe=body.entry_timeframe,
            use_market_regime_filter=body.use_market_regime_filter,
            use_trend_filter=body.use_trend_filter,
            use_entry_filter=body.use_entry_filter,
            use_atr_filter=body.use_atr_filter,
            min_indicators_required=body.min_indicators_required,
            min_entry_indicators_required=body.min_entry_indicators_required,
            is_active=body.is_active,
        )
        db.add(p)
        db.flush()

        # Default circuit breaker config
        cb = CircuitBreakerConfig(
            profile_name=p.name,
            max_daily_profit_pct=Decimal("5.0"),
            max_daily_loss_pct=Decimal("3.0"),
            profit_lock_hours=6,
            loss_lock_hours=12,
            is_active=True,
        )
        db.add(cb)

        write_audit(
            db=db,
            type="profile",
            subtype="create",
            action="create",
            entity_id=p.id,
            entity_name=p.name,
            before=None,
            after={
                "name":          p.name,
                "display_name":  p.display_name,
                "account_id":    p.account_id,
                "account_name":  account.name,
                "strategy_type": p.strategy_type,
                "trading_type":  p.trading_type,
            },
        )

        from db.models import UserProfileMapping #, SymbolConfig
        usermapping = UserProfileMapping(
            user_id = current_user.user_id,
            profile_name = body.name,
            is_active = body.is_active,
        )
        db.add(usermapping)
        db.commit()
        db.refresh(p)

        apiserver_logger.info(
            f"Created profile '{p.name}' (id={p.id}) "
            f"linked to exchange account '{account.name}' (id={account.id})"
        )
        
        #Refresh profile data
        refresh_profiles_from_db()
        return {
            "id":           p.id,
            "name":         p.name,
            "account_id":   p.account_id,
            "account_name": account.name,
            "message":      f"Profile '{p.name}' created",
        }


# ---------------------------------------------------------------------------
# PUT /profiles/{profile_name}  — partial update
# ---------------------------------------------------------------------------
@app.put("/profiles/{profile_name}", dependencies=[Depends(require_admin_permission)])
async def update_profile_endpoint(profile_name: str, body: ProfileUpdateRequest):
    from db.utils import get_db_session
    from db.models import TradingProfileDB
    from services.audit import write_audit
    from services.profile_manager import get_profile_manager, refresh_profiles_from_db

    _EDITABLE = [
        "display_name", "trading_type", "strategy_type",
        "take_profit_pct", "stop_loss_pct", "trailing_stop_pct",
        "arm_trailing_stop_pct", "use_trailing_stop",
        "default_order_size_usdc", "max_position_size_pct",
        "max_open_positions", "max_portfolio_exposure_pct",
        "signal_timeframe", "signal_cooldown_seconds",
        "min_signal_confidence", "min_volume_ratio",
        "trend_timeframe", "entry_timeframe",
        "use_market_regime_filter", "use_trend_filter",
        "use_entry_filter", "use_atr_filter",
        "min_indicators_required", "min_entry_indicators_required",
        "use_trend_invalidation_exit", "trend_invalidation_indicators",
        "min_position_age_for_trend_check", "max_position_hours",
        "is_active",
    ]

    with get_db_session() as db:
        p = db.query(TradingProfileDB).filter(TradingProfileDB.name == profile_name).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")

        before = {k: _safe_val(getattr(p, k, None)) for k in _EDITABLE}
        changes = {}

        for field in _EDITABLE:
            val = getattr(body, field, None)
            if val is not None:
                setattr(p, field, val)
                changes[field] = val

        if not changes:
            return {"message": "No changes provided"}

        write_audit(
            db=db,
            type="profile",
            subtype="update",
            action="update",
            entity_id=p.id,
            entity_name=p.name,
            before={k: before[k] for k in changes},
            after=changes,
        )

        db.commit()
        db.refresh(p)

        # refresh profiles in cache
        refresh_profiles_from_db()

        apiserver_logger.info(f"Updated profile '{profile_name}': {list(changes.keys())}")
        return {"name": p.name, "updated_fields": list(changes.keys())}


def _safe_val(v):
    from decimal import Decimal
    return float(v) if isinstance(v, Decimal) else v

# ---------------------------------------------------------------------------
# PUT /profiles/{profile_name}/credentials  — update API key/secret
# ---------------------------------------------------------------------------
@app.put("/profiles/{profile_name}/credentials", dependencies=[Depends(require_admin_permission)])
async def update_profile_credentials(profile_name: str, body: ProfileCredentialsRequest):
    from db.utils import get_db_session
    from db.models import TradingProfileDB, ExchangeAccount
    from utils.db_secrets import encrypt_secret
    from services.audit import write_audit
    from services.profile_manager import get_profile_manager, refresh_profiles_from_db

    with get_db_session() as db:
        p = db.query(TradingProfileDB).filter(TradingProfileDB.name == profile_name).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")
        if not p.account_id:
            raise HTTPException(status_code=400, detail=f"Profile '{profile_name}' has no linked exchange account")

        account = db.query(ExchangeAccount).filter(ExchangeAccount.id == p.account_id).first()
        if not account:
            raise HTTPException(status_code=404, detail="Linked exchange account not found")

        account.api_key = encrypt_secret(body.raw_api_key)
        account.secret = encrypt_secret(body.raw_secret)

        write_audit(
            db=db, type="profile", subtype="credentials", action="update",
            entity_id=p.id, entity_name=p.name,
            before={"api_key": "***", "secret": "***"},
            after={"api_key": "***updated***", "secret": "***updated***"},
        )
        db.commit()

        # Force profile reload so new credentials are used immediately
        refresh_profiles_from_db()

        return {"message": f"Credentials updated for '{profile_name}' (via exchange account {account.name})"}


# ---------------------------------------------------------------------------
# DELETE /profiles/{profile_name}  — soft-deactivate
# ---------------------------------------------------------------------------
@app.delete("/profiles/{profile_name}", dependencies=[Depends(require_admin_permission)])
async def deactivate_profile_endpoint(profile_name: str):
    from db.utils import get_db_session
    from db.models import TradingProfileDB
    from services.audit import write_audit
    from services.profile_manager import get_profile_manager, refresh_profiles_from_db

    with get_db_session() as db:
        p = db.query(TradingProfileDB).filter(TradingProfileDB.name == profile_name).first()
        if not p:
            raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")

        # Safety: block deactivation if open positions exist
        from db.crud import get_open_positions
        open_pos = get_open_positions(db, profile_name)
        if open_pos:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot deactivate profile with {len(open_pos)} open position(s). Close them first."
            )

        before = {"is_active": p.is_active}
        p.is_active = False

        write_audit(
            db=db, type="profile", subtype="deactivate", action="delete",
            entity_id=p.id, entity_name=p.name,
            before=before, after={"is_active": False},
        )
        db.commit()

        refresh_profiles_from_db()

        return {"message": f"Profile '{profile_name}' deactivated"}


# ---------------------------------------------------------------------------
# GET /profiles/{profile_name}/circuit-breaker
# ---------------------------------------------------------------------------
@app.get("/profiles/{profile_name}/circuit-breaker", dependencies=[Depends(require_read_permission)])
async def get_profile_cb_config(profile_name: str):
    from db.utils import get_db_session
    from db.models import CircuitBreakerConfig

    with get_db_session() as db:
        cb = db.query(CircuitBreakerConfig).filter(
            CircuitBreakerConfig.profile_name == profile_name
        ).first()
        if not cb:
            raise HTTPException(status_code=404, detail=f"No circuit breaker config for '{profile_name}'")
        return _serialize_cb(cb)


# ---------------------------------------------------------------------------
# PUT /profiles/{profile_name}/circuit-breaker
# ---------------------------------------------------------------------------
@app.put("/profiles/{profile_name}/circuit-breaker", dependencies=[Depends(require_admin_permission)])
async def update_profile_cb_config(profile_name: str, body: CircuitBreakerUpdateRequest):
    from db.utils import get_db_session
    from db.models import CircuitBreakerConfig
    from services.audit import write_audit

    with get_db_session() as db:
        cb = db.query(CircuitBreakerConfig).filter(
            CircuitBreakerConfig.profile_name == profile_name
        ).first()
        if not cb:
            # Auto-create if missing
            cb = CircuitBreakerConfig(
                profile_name=profile_name,
                max_daily_profit_pct=Decimal("5.0"),
                max_daily_loss_pct=Decimal("3.0"),
                profit_lock_hours=6,
                loss_lock_hours=12,
                is_active=True,
            )
            db.add(cb)
            db.flush()

        before = _serialize_cb(cb)
        changes = {}

        for field in ["max_daily_profit_pct", "max_daily_loss_pct",
                      "profit_lock_hours", "loss_lock_hours", "is_active"]:
            val = getattr(body, field, None)
            if val is not None:
                setattr(cb, field, val)
                changes[field] = val

        write_audit(
            db=db, type="profile", subtype="circuit_breaker", action="update",
            entity_id=cb.id, entity_name=f"CB:{profile_name}",
            before={k: before[k] for k in changes}, after=changes,
        )
        db.commit()
        db.refresh(cb)
        get_circuit_breaker().invalidate_config_cache(profile_name)
        return _serialize_cb(cb)

@app.get("/exchange-accounts", dependencies=[Depends(require_read_permission)])
async def list_exchange_accounts():
    """Return all active exchange accounts for dropdowns."""
    from db.utils import get_db_session
    from db.models import ExchangeAccount
 
    with get_db_session() as db:
        accounts = (
            db.query(ExchangeAccount)
            .filter(ExchangeAccount.is_active == True)
            .order_by(ExchangeAccount.name)
            .all()
        )
        return [
            {
                "id":   a.id,
                "name": a.name,
            }
            for a in accounts
        ]
 
# ---------------------------------------------------------------------------
# Helper serialisers (add as module-level functions in api_server.py)
# ---------------------------------------------------------------------------

def _serialize_profile(p, cb=None) -> dict:
    """Serialise TradingProfileDB to a safe dict (no raw keys)."""
    from utils.db_secrets import resolve_secret
    raw_key = None
    try:
        if p.account:
            raw_key = resolve_secret(p.account.api_key)
    except Exception:
        pass

    return {
        "id":                          p.id,
        "name":                        p.name,
        "display_name":                p.display_name,
        "is_active":                   p.is_active,
        "key_hint":                    f"...{raw_key[-6:]}" if raw_key else None,

        # Strategy
        "trading_type":                p.trading_type,
        "strategy_type":               p.strategy_type,

        # Risk
        "take_profit_pct":             float(p.take_profit_pct)       if p.take_profit_pct       else None,
        "stop_loss_pct":               float(p.stop_loss_pct)         if p.stop_loss_pct         else None,
        "trailing_stop_pct":           float(p.trailing_stop_pct)     if p.trailing_stop_pct     else None,
        "arm_trailing_stop_pct":       float(p.arm_trailing_stop_pct) if p.arm_trailing_stop_pct else None,
        "use_trailing_stop":           bool(p.use_trailing_stop),

        # Sizing
        "default_order_size_usdc":     float(p.default_order_size_usdc)     if p.default_order_size_usdc     else 100.0,
        "max_position_size_pct":       float(p.max_position_size_pct)       if p.max_position_size_pct       else None,
        "max_open_positions":          int(p.max_open_positions)            if p.max_open_positions            else 5,
        "max_portfolio_exposure_pct":  float(p.max_portfolio_exposure_pct)  if p.max_portfolio_exposure_pct  else 80.0,

        # Signal
        "signal_timeframe":            p.signal_timeframe,
        "signal_cooldown_seconds":     p.signal_cooldown_seconds,
        "min_signal_confidence":       float(p.min_signal_confidence) if p.min_signal_confidence else 72.0,
        "min_volume_ratio":            float(p.min_volume_ratio)      if p.min_volume_ratio      else 1.0,

        # Timeframes
        "trend_timeframe":             p.trend_timeframe,
        "entry_timeframe":             p.entry_timeframe,

        # Filters
        "use_market_regime_filter":    bool(p.use_market_regime_filter),
        "use_trend_filter":            bool(p.use_trend_filter),
        "use_entry_filter":            bool(p.use_entry_filter),
        "use_atr_filter":              bool(p.use_atr_filter),

        # Indicator thresholds
        "min_indicators_required":     p.min_indicators_required,
        "min_entry_indicators_required": p.min_entry_indicators_required,

        # Exit logic
        "use_trend_invalidation_exit":          bool(p.use_trend_invalidation_exit) if p.use_trend_invalidation_exit is not None else False,
        "trend_invalidation_indicators":        p.trend_invalidation_indicators if p.trend_invalidation_indicators else None,
        "min_position_age_for_trend_check":     p.min_position_age_for_trend_check if p.min_position_age_for_trend_check else None,
        "max_position_hours":                   p.max_position_hours if p.max_position_hours else None,

        # Circuit breaker (embedded)
        "circuit_breaker":             _serialize_cb(cb) if cb else None,

        # Account linkage
        "account_id":                  p.account_id,

        # Timestamps
        "created_at":                  p.created_at.isoformat() if p.created_at else None,
        "updated_at":                  p.updated_at.isoformat() if p.updated_at else None,
    }


def _serialize_cb(cb) -> dict:
    if not cb:
        return {}
    return {
        "id":                   cb.id,
        "profile_name":         cb.profile_name,
        "max_daily_profit_pct": float(cb.max_daily_profit_pct) if cb.max_daily_profit_pct else 5.0,
        "max_daily_loss_pct":   float(cb.max_daily_loss_pct)   if cb.max_daily_loss_pct   else 3.0,
        "profit_lock_hours":    cb.profit_lock_hours,
        "loss_lock_hours":      cb.loss_lock_hours,
        "is_active":            bool(cb.is_active),
    }

# ══════════════════════════════════════════════════════════════════════════════
# Config Audit Log — read-only endpoints
# ══════════════════════════════════════════════════════════════════════════════
 
@app.get("/audit-log", dependencies=[Depends(require_read_permission)])
async def get_audit_log(
    type: Optional[str] = None,
    subtype: Optional[str] = None,
    action: Optional[str] = None,
    entity_id: Optional[int] = None,
    days: int = 30,
    limit: int = 200,
):
    """
    Query the config audit log with optional filters.
 
    Returns newest-first. Max 200 rows per call.
    Use `days` to restrict the time window (default: last 30 days).
    """
    from db.utils import get_db_session
    from db.models import ConfigAuditLog
    from datetime import timedelta
 
    try:
        with get_db_session() as db:
            from datetime import datetime, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            q = (
                db.query(ConfigAuditLog)
                .filter(ConfigAuditLog.changed_at >= cutoff)
            )
            if type:      q = q.filter(ConfigAuditLog.type    == type)
            if subtype:   q = q.filter(ConfigAuditLog.subtype == subtype)
            if action:    q = q.filter(ConfigAuditLog.action  == action)
            if entity_id: q = q.filter(ConfigAuditLog.entity_id == entity_id)
 
            rows = (
                q.order_by(ConfigAuditLog.changed_at.desc())
                .limit(min(limit, 500))
                .all()
            )
            return [
                {
                    "id":          r.id,
                    "changed_at":  r.changed_at.isoformat() if r.changed_at else None,
                    "type":        r.type,
                    "subtype":     r.subtype,
                    "action":      r.action,
                    "entity_id":   r.entity_id,
                    "entity_name": r.entity_name,
                    "changed_by":  r.changed_by,
                    "before":      r.before,
                    "after":       r.after,
                }
                for r in rows
            ]
    except Exception as e:
        apiserver_logger.error(f"Error querying audit log: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
 
app.include_router(auth_router)

# Mount static files directory
app.mount("/web", StaticFiles(directory="web"), name="web")

@app.get("/")
async def serve_dashboard():
    return FileResponse("web/index.html")