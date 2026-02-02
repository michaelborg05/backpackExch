import time
import threading
from typing import List,  Dict,Optional
from utils.logging import log_manager
from utils.config import Config
from utils.constants import MessagePriority
from utils.exceptions import InvalidQuantityError, InsufficientBalanceError, TradingException
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price, get_market_info
from api_builders.trading_builder import TradingService
from api_builders.atr_calculator import get_atr_calculator
from api_builders.dust_conversion import get_dust_converter
from cache.balance_cache import get_balance_cache
from cache.price_cache import get_price_cache
from cache.portfolio_cache import get_portfolio_cache
from cache.market_info_cache import get_market_info_cache
from models.balance import BalanceReader
from models.trading_profile import TradingProfile
from models.trading_signal import TradingSignal
from services.telegram_service import get_telegram
from services.circuit_breaker import get_circuit_breaker
from services.profile_manager import get_profile_manager
from services.signal_generator import get_signal_generator
from utils.position_calculator import get_position_size_calculator
from cache.trend_cache import initialize_trend_cache_with_db
from cache.trend_cache_warmup import warmup_trend_cache

from db.utils import get_db_session
from db.crud import (
    get_open_positions,
    update_position_trailing_stop,
    close_invalid_position,
    update_high_low,
    get_active_symbols
)

class MonitoringService:
    """Service for monitoring market prices and account balances"""
    
    def __init__(self, tickers: Optional[List[str]] = None):
        """
        Initialize monitoring service
        
        Args:
            tickers: List of tickers to monitor (e.g., ["SOL_USDC", "BTC_USDC"])
        """
        self.config = Config()
        self.logger = log_manager.get_logger("MonitoringService")
        #self.tickers = tickers or ["SOL_USDC", "ETH_USDC", "HYPE_USDC", "SUI_USDC"]
        with get_db_session() as db:
                db_tickers = get_active_symbols(db)
                # Fallback to a hardcoded list ONLY if the DB is empty
                self.tickers = db_tickers if db_tickers else ["SOL_USDC", "ETH_USDC", "HYPE_USDC", "SUI_USDC"]

                trend_cache = initialize_trend_cache_with_db(
                    db,
                    persist_to_db=True
                )
                # Warm up from database
                try:
                    stats = warmup_trend_cache(db, trend_cache)
                    self.logger.info(f"Cache warmed up: {stats['symbols_loaded']} symbols, "
                            f"{stats['total_snapshots_replayed']} snapshots")
                except Exception as e:
                    self.logger.error(f"Error warming up cache: {e}")   

        self.is_running = False
        self.thread = None
        self.call_count = 0
        self.balance_cache = get_balance_cache()  # Get cache instance
        self.price_cache = get_price_cache()    # Get price cache instance
        self.position_calculator = get_position_size_calculator()

        self.market_info_cache = get_market_info_cache()
        self._markets_initialized = False

        self.atr_calculator = get_atr_calculator()
        self._atr_update_counter = 0
        self._atr_update_interval = 5  # Update ATR every 5 cycles (e.g., every 2.5 min if cycle is 30s)

        self.circuit_breaker = get_circuit_breaker()
        self._circuit_breaker_counter = 0
        self._circuit_breaker_interval = 2  # Check every 2 cycles (e.g., every 60s if cycle is 30s)

        self.dust_converter = get_dust_converter()
        self._dust_conversion_counter = 0
        self._dust_conversion_interval = 2880  # Convert dust every 2880 cycles (24 hours if cycle is 30s)

        self._signal_check_counter = 0
        self._signal_check_interval = 10  # Check for signals every 10 cycles (5 min if cycle is 30s)
        self._last_signals: Dict[str, float] = {}  # Track last signal time per symbol


    def start(self):
        """Start the monitoring loop in a background thread"""
        if self.is_running:
            self.logger.warning("Monitoring service is already running")
            return
        
        # Initialize market info on first start
        if not self._markets_initialized:
            self._initialize_market_info()
        
        self.is_running = True
        self.thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.thread.start()
        self.logger.info("Monitoring service started")
        
    def stop(self):
        """Stop the monitoring loop"""
        if not self.is_running:
            self.logger.warning("Monitoring service is not running")
            return
        
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.logger.info("Monitoring service stopped")
        
    def add_ticker(self, ticker: str):
        """Add a ticker to monitor"""
        if ticker not in self.tickers:
            self.tickers.append(ticker)
            self.logger.info(f"Added ticker: {ticker}")
        
    def remove_ticker(self, ticker: str):
        """Remove a ticker from monitoring"""
        if ticker in self.tickers:
            self.tickers.remove(ticker)
            self.logger.info(f"Removed ticker: {ticker}")
        
    def get_status(self) -> dict:
        """Get current monitoring status"""
        return {
            "is_running": self.is_running,
            "call_count": self.call_count,
            "tickers": self.tickers,
            "interval": self.config.monitor_delay_interval,
             "balance_cache": self.balance_cache.get_cache_info()
        }
    
    def _monitoring_loop(self):
        """Internal monitoring loop - runs in background thread"""
        self.logger.debug("Monitoring loop starting...")
        self.logger.debug(f"Log level set to {self.config.log_level}")
        validation_counter = 0
        validation_interval = 10  # Run validation every 10 cycles (e.g., every 5 min if cycle is 30s)
    
        try:
            while self.is_running:
                self.call_count += 1
                validation_counter += 1
                self._atr_update_counter += 1
                self._circuit_breaker_counter += 1 
                self._dust_conversion_counter += 1
                self._signal_check_counter += 1
                self.logger.debug(f"Beginning loop #{self.call_count}")
                
                # Monitor prices for all tickers
                self._monitor_prices()
                
                # Get account balances
                self._monitor_balances()

                if self._circuit_breaker_counter >= self._circuit_breaker_interval:
                    self._monitor_circuit_breakers()
                    self._circuit_breaker_counter = 0

                # Monitor open balances and check for SL/TP/Trailing SL
                self._monitor_open_positions()

                # Update ATR periodically (less frequently than prices)
                if self._atr_update_counter >= self._atr_update_interval:
                    self._monitor_atr()
                    self._atr_update_counter = 0

                # Validate positions periodically (less frequently)
                if validation_counter >= validation_interval:
                    self.logger.info("Running position validation...")
                    self._validate_open_positions()
                    validation_counter = 0

                if self._dust_conversion_counter >= self._dust_conversion_interval:
                    self._convert_dust()
                    self._dust_conversion_counter = 0

                if self._signal_check_counter >= self._signal_check_interval:
                    self._check_signals()
                    self._signal_check_counter = 0

                # Wait before next iteration
                if self.is_running:  # Check again before sleeping
                    self.logger.info(
                        f"Waiting {self.config.monitor_delay_interval} seconds until next call..."
                    )
                    time.sleep(self.config.monitor_delay_interval)

        except KeyboardInterrupt:
            self.logger.info("Monitoring loop interrupted by user")
        except Exception as e:
            self.logger.error(f"Unexpected error in monitoring loop: {e}", exc_info=True)
            self.is_running = False
    
    def _monitor_prices(self):
        """Monitor prices for all tickers"""
        for ticker in self.tickers:
            try:
                price = get_price(ticker)
                if price:
                    # Update price cache
                    self.price_cache.update_price(ticker, price)
            except Exception as e:
                self.logger.error(f"Error getting price for {ticker}: {e}")
    
    def _monitor_balances(self):
        """Monitor account balances for all profiles and update cache"""
        try:
            # Get balances for ALL profiles and update cache in one call
            all_balances = get_balances(source="MonitoringService", update_cache=True)
            
            if all_balances:
                # Log summary for each profile
                for profile_name, balances in all_balances.items():
                    if isinstance(balances, BalanceReader):
                        self.logger.debug(f"[{profile_name}] {balances.summary()}")
                
                    # Print portfolio summary
                    portfolio = get_portfolio_cache()
                    portfolio_summary = portfolio.print_portfolio_summary(profile_name=profile_name)
                    if portfolio_summary:
                        self.logger.info(portfolio_summary)
                    
        except Exception as e:
            self.logger.error(f"Error getting balances: {e}")



    def _convert_balances_to_dict(self, balances) -> Dict[str, Dict]:
        """
        Convert balance object to dict format for cache
        Adjust this based on your actual balance object structure
        """
        # Example - adjust based on your actual balance object
        if hasattr(balances, 'to_dict'):
            return balances.to_dict()
        
        # Or if it's already a dict-like object
        result = {}
        for asset, balance in balances.items():
            result[asset] = {
                "available": str(balance.available) if hasattr(balance, 'available') else "0",
                "locked": str(balance.locked) if hasattr(balance, 'locked') else "0",
                "staked": str(balance.staked) if hasattr(balance, 'staked') else "0"
            }
        return result

    def _initialize_market_info(self):
        """Initialize market info cache for all monitored tickers"""
        self.logger.info("Initializing market info...")
        try:
            # Fetch market info for each ticker
            for ticker in self.tickers:
                get_market_info(ticker)
            
            self._markets_initialized = True
            self.logger.info(f"Market info initialized for {len(self.tickers)} tickers")
        except Exception as e:
            self.logger.error(f"Error initializing market info: {e}")

    def _monitor_open_positions(self):
        """Check open positions for TP / SL / trailing SL conditions"""
        from services.position_manager import get_position_manager

        profile_manager = get_profile_manager()
        position_manager = get_position_manager()

        if profile_manager is None:
            self.logger.error("Profile manager not initialized. Skipping open position monitoring.")
            return 
        
        # Use the context manager - session is automatically closed
        with get_db_session() as db:
            profiles = profile_manager._profiles.values()
            for profile in profiles:
                open_positions = get_open_positions(db, profile.name)

                for position in open_positions:
                    symbol = position.symbol
                    price = self.price_cache.get_price(symbol)

                    if not price:
                        continue

                    price = float(price)
                    entry_price = float(position.entry_price)

                    # Calculate current profit percentage
                    profit_pct = ((price - entry_price) / entry_price) * 100

                    # TAKE PROFIT
                    if position.tp_price and price >= float(position.tp_price):
                        self.logger.info(f"TP hit for {symbol} @ {price} [{profile.name}]")
                        #self._send_telegram(f"🎯 TP hit for {symbol} @ {price} [{profile.name}]")
                        self._execute_close(db, position, profile, reason="TAKE_PROFIT")
                        continue

                    # STOP LOSS
                    if position.sl_price and price <= float(position.sl_price):
                        self.logger.info(f"SL hit for {symbol} @ {price} [{profile.name}]")
                        #self._send_telegram(f"🛑 SL hit for {symbol} @ {price} [{profile.name}]")
                        self._execute_close(db, position, profile, reason="STOP_LOSS")
                        continue

                    # TRAILING STOP LOGIC with ARM THRESHOLD
                    if profile.use_trailing_stop:
                        # Get the arm threshold (default to 50% of TP if not specified)
                        arm_threshold_pct = float(getattr(
                            profile, 
                            'arm_trailing_stop_pct', 
                            float(profile.take_profit_pct) * 0.5
                        ))
                        
                        # Check if trailing stop should be armed
                        # Once armed, it stays armed for the life of the position
                        if not position.trailing_stop_armed and profit_pct >= arm_threshold_pct:
                            # ARM the trailing stop for the first time
                            position.trailing_stop_armed = True
                            if position.trailing_sl_price is None:
                                # Set initial Trailing stop loss price to arm threshold
                                trailing_pct = float(profile.trailing_stop_pct)
                                position.trailing_sl_price = max(
                                    float(price) * (1 - trailing_pct / 100),
                                    float(position.entry_price) * 1.0005  # +0.05%
                                )
                            db.commit()
                            
                            self.logger.info(
                                f"🎣 Trailing stop ARMED for {symbol} at {profit_pct:.2f}% profit "
                                f"(threshold: {arm_threshold_pct:.2f}%) [{profile.name}]"
                            )
                            #self._send_telegram(
                            #    f"🎣 Trailing stop ARMED for {symbol} at {profit_pct:.2f}% profit [{profile.name}]",
                            #    MessagePriority.NORMAL
                            #)
                        
                        # Only process trailing stop logic if it's been armed
                        if position.trailing_stop_armed:
                            highest = float(position.highest_price or 0)

                            # Update highest price and trailing stop if new high
                            if price > highest:
                                new_high = price
                                trailing_pct = float(profile.trailing_stop_pct)
                                new_trailing_sl = max(float(price) * (1 - trailing_pct / 100), float(position.entry_price) * 1.0005)  # +0.05%

                                update_position_trailing_stop(
                                    db,
                                    position.id,
                                    highest_price=new_high,
                                    trailing_sl_price=new_trailing_sl,
                                )

                                self.logger.debug(
                                    f"Updated trailing SL for {symbol}: {new_trailing_sl:.4f} "
                                    f"(profit: {profit_pct:.2f}%) [{profile.name}]"
                                )
                            
                            # Check if trailing stop was hit
                            elif price <= float(position.trailing_sl_price):
                                self.logger.info(
                                    f"Trailing SL hit for {symbol} @ {price} "
                                    f"(profit: {profit_pct:.2f}%) [{profile.name}]"
                                )
                                #self._send_telegram(
                                #    f"📉 Trailing SL hit for {symbol} @ {price} "
                                #    f"(profit: {profit_pct:+.2f}%) [{profile.name}]"
                                #)
                                self._execute_close(db, position, profile, reason="TRAILING_STOP")
                        else:
                            # Trailing stop not armed yet - log if price is close
                            remaining_to_arm = arm_threshold_pct - profit_pct
                            if remaining_to_arm < 0.2:  # Log when within 0.2% of arming
                                self.logger.debug(
                                    f"Trailing SL not armed for {symbol}: "
                                    f"need {arm_threshold_pct:.2f}% profit, "
                                    f"current: {profit_pct:.2f}% [{profile.name}]"
                                )

                    #Price monitoring
                    if position.lowest_price > price or position.highest_price < price:
                        update_high_low(
                            db,
                            position.id,
                            highest_price=price,
                            lowest_price=price,
                        )

                    # Trend Invalidation Check for long running trades
                    should_exit, exit_reason = position_manager.should_exit_position(
                        position=position,
                        profile=profile,
                        current_price=price
                    )
                    
                    if should_exit:
                        self.logger.info(
                            f"Position exit: {symbol} @ {price} "
                            f"(profit: {profit_pct:+.2f}%) [{profile.name}] - {exit_reason}"
                        )
                        
                        # Extract reason type (TREND_INVALIDATION or STALE_POSITION)
                        reason_type = exit_reason.split(':')[0]
                        
                        self._execute_close(
                            db, 
                            position, 
                            profile, 
                            reason=reason_type,
                            reason_summary=[exit_reason],
                        )
                        continue

            
    def _validate_open_positions(self):
        """
        Validate open positions against cached balances.
        Close positions where the token has been sold but position wasn't updated.
        """

        profile_manager = get_profile_manager()
        if profile_manager is None:
            self.logger.error("Profile manager not initialized. Skipping validation.")
            return

        balance_cache = get_balance_cache()

        with get_db_session() as db:
            profiles = profile_manager._profiles.values()
            
            for profile in profiles:
                open_positions = get_open_positions(db, profile.name)
                if open_positions is None or len(open_positions) == 0:
                    continue
                # Get cached balances for this profile
                cached_balances = balance_cache.get_profile_balances(profile.name)
                
                if not cached_balances:
                    self.logger.warning(f"No cached balances for profile {profile.name}, skipping validation")
                    continue
                
                for position in open_positions:
                    symbol = position.symbol
                    # Extract base asset (e.g., "SOL" from "SOL_USDC")
                    base_asset = symbol.split('_')[0]
                    
                    # Check if we still hold this token (from cache)
                    balance_info = cached_balances.get(base_asset)
                    
                    expected_quantity = str(position.remaining_quantity)

                    # Check if balance is insufficient
                    if balance_info is None:
                        current_balance = 0
                    else:
                        current_balance = float(balance_info.get('available', 0))
                    
                    # If balance is zero or less than 1% of expected, position is invalid
                    if current_balance < (float(expected_quantity) * 0.01):  # 1% threshold
                        self.logger.warning(
                            f"INVALID POSITION DETECTED: {symbol} for {profile.name}. "
                            f"Expected {expected_quantity}, but balance is {current_balance}"
                        )
                        
                        # Close the invalid position
                        close_invalid_position(db, position.id, reason="INVALID_POSITION")
                        
                        self.logger.info(
                            f"Closed invalid position {position.id} for {symbol} - "
                            f"token was sold externally"
                        )
                        self._send_telegram(
                            f"⚠️ Closed invalid position for {symbol} - token was sold externally"
                        )
                        # Optional: Send notification
                        # send_telegram_message_sync(
                        #     f"⚠️ Closed invalid position for {symbol} - token was sold externally"
                        # )

    def _execute_close(self, db, position, profile, reason: str, reason_summary: list[str] = None):
        """
        Execute a close order for a position
        
        Args:
            db: Database session
            position: Position object to close
            profile: TradingProfile for this position
            reason: Reason for closing (TAKE_PROFIT, STOP_LOSS, TRAILING_STOP)
        """
        try:
            # Create TradingService instance for this profile
            trading = TradingService(profile)
            symbol = position.symbol
            
            quantity = str(position.remaining_quantity)
            
            self.logger.info(
                f"Executing close order: {symbol} x {quantity} "
                f"[{profile.name}] Reason: {reason}"
            )
            
            # Execute sell order with "MAX" to ensure we sell everything
            result = trading.order_sell(
                symbol=symbol,
                quantity=quantity,  # Use MAX to sell all available
                source=reason,
                profile_name=profile.name,
                position_id=str(position.id),
                reason_summary=reason_summary,
            )
            
            if result:
                self.logger.info(
                    f"Close order executed successfully: {result.id} "
                    f"[{profile.name}] Quantity: {result.executed_quantity}"
                )
                
                # Calculate profit/loss
                entry_price = float(position.buy_trade.price)
                exit_price = float(result.executed_quote_quantity) / float(result.executed_quantity)
                quantity_sold = float(result.executed_quantity)
                profit = (exit_price - entry_price) * quantity_sold
                profit_pct = ((exit_price - entry_price) / entry_price) * 100

                icon = "🟢" if profit_pct >= 0 else "🛑"
                
                # Send detailed notification
                self._send_telegram(
                    f"{icon} Position Closed [{profile.name}]\n"
                    f"Symbol: {symbol}\n"
                    f"Reason: {reason}\n"
                    f"Entry: ${entry_price:.4f}\n"
                    f"Exit: ${exit_price:.4f}\n"
                    f"Quantity: {quantity_sold:.4f}\n"
                    f"P/L: ${profit:.2f} ({profit_pct:+.2f}%)",
                    MessagePriority.NORMAL
                )
                
                # Note: Position will be closed automatically by TradingService.ExecuteOrder
                # which calls close_position() for SELL orders
                
            else:
                self.logger.error(f"Close order failed for {symbol} [{profile.name}]")
                self._send_telegram(
                    f"❌ Failed to close position for {symbol} [{profile.name}]",
                    MessagePriority.HIGH
                )

        except InvalidQuantityError as e:
            # Handle invalid quantity - likely position has already been closed externally
            self.logger.warning(
                f"Invalid quantity when closing {position.symbol} [{profile.name}]: {e.message}. "
                f"Details: {e.details}"
            )
            
            # Check if quantity rounded to zero - indicates position is already gone
            if e.details.get('quantity') == 0 or e.details.get('original_quantity', 0) < 0.01:
                self.logger.info(
                    f"Closing invalid position {position.id} - quantity too small or already sold"
                )
                close_invalid_position(db, position.id, reason="INVALID_QUANTITY")
                
                self._send_telegram(
                    f"⚠️ Closed invalid position for {position.symbol} [{profile.name}] - "
                    f"quantity too small or already sold",
                    MessagePriority.NORMAL
                )
            else:
                # Some other quantity issue
                self._send_telegram(
                    f"❌ Invalid quantity for {position.symbol} [{profile.name}]: {e.message}",
                    MessagePriority.HIGH
                )
        
        except InsufficientBalanceError as e:
            # Handle insufficient balance
            self.logger.warning(
                f"Insufficient balance when closing {position.symbol} [{profile.name}]: {e.message}. "
                f"Details: {e.details}"
            )
            
            # Close the position as it's invalid
            close_invalid_position(db, position.id, reason="INSUFFICIENT_BALANCE")
            
            self._send_telegram(
                f"⚠️ Closed invalid position for {position.symbol} [{profile.name}] - "
                f"insufficient balance (likely sold externally)",
                MessagePriority.NORMAL
            )
        
        except TradingException as e:
            # Handle other trading exceptions
            self.logger.error(
                f"Trading error when closing {position.symbol} [{profile.name}]: {e.message}. "
                f"Type: {e.error_type}, Details: {e.details}",
                exc_info=True
            )
            self._send_telegram(
                f"❌ Error closing position for {position.symbol} [{profile.name}]: {e.message}",
                MessagePriority.HIGH
            )
        
        except Exception as e:
            # Handle unexpected errors
            self.logger.error(
                f"Unexpected error executing close order for {position.symbol} [{profile.name}]: {e}",
                exc_info=True
            )
            self._send_telegram(
                f"❌ Unexpected error closing position for {position.symbol} [{profile.name}]: {str(e)}",
                MessagePriority.HIGH
            )
    def _monitor_atr(self):
        """Monitor ATR for all tickers"""
        try:
            # Update ATR for all monitored tickers
            # You can specify different timeframes for different profiles
            profile_manager = get_profile_manager()

            atr_timeframes = {
                profile.atr_timeframe
                for profile in profile_manager.get_all_profiles()
                if profile.use_atr_filter
            }
 
            for timeframe in atr_timeframes:
                results = self.atr_calculator.update_multiple(
                    symbols=self.tickers,
                    timeframe=timeframe
                )

                for symbol, atr_data in results.items():
                    if not atr_data:
                        self.logger.warning(
                            f"Failed to update ATR for {symbol} [{timeframe}]"
                        )
                        continue

                    ratio = atr_data.get_ratio()
                    volatile = atr_data.is_volatile()

                    self.logger.info(
                        f"ATR[{timeframe}] {symbol}: "
                        f"{atr_data.atr:.6f} "
                        f"(SMA: {atr_data.atr_sma:.6f}, "
                        f"Ratio: {ratio:.2f}, "
                        f"Volatile: {'YES' if volatile else 'NO'})"
                    )
                     
        except Exception as e:
            self.logger.error(f"Error monitoring ATR: {e}", exc_info=True)

    def _send_telegram(self, message: str, priority: MessagePriority = MessagePriority.NORMAL):
        """
        Helper to send Telegram messages from sync monitoring thread.
        Uses thread-safe scheduling to main event loop.
        """
        # Don't send if monitoring is stopped
        if not self.is_running:
            return
        
        try:
            telegram = get_telegram()
            if not telegram:
                return
            
            if not telegram._initialized:
                self.logger.debug("Telegram not initialized - skipping message")
                return
            
            # Use the thread-safe sync wrapper
            success = telegram.send_message_sync(message, priority)
            
            if not success:
                # Only log if we're still running (not shutting down)
                if self.is_running and telegram._initialized:
                    self.logger.debug(f"Failed to send Telegram message (may be shutting down)")
                    
        except Exception as e:
            # Catch any unexpected errors
            if self.is_running:
                self.logger.debug(f"Could not send Telegram message: {e}")

    def _monitor_circuit_breakers(self):
        """
        Monitor circuit breakers for all profiles
        Proactively checks PnL limits and triggers breakers if needed
        """
        try:
            # Check all profiles and trigger breakers if limits exceeded
            self.circuit_breaker.monitor_all_profiles()
            
            # Get active breakers for logging (only log if there are any active)
            active_breakers = self.circuit_breaker.get_all_breakers()
            
            # Only log active breakers once per monitoring cycle to avoid spam
            if active_breakers:
                for profile_name, breaker_info in active_breakers.items():
                    # Log at INFO level only when first triggered or every ~5 minutes
                    # Otherwise it's just noise
                    time_remaining = breaker_info['time_remaining_seconds']
                    
                    # Log less frequently for active breakers (every ~5 min)
                    # Assuming 30s cycles and checking every 2 cycles = 60s
                    # So this logs roughly every 5 checks = ~5 minutes
                    if time_remaining % 300 < 60:  # Within 60s of 5-min boundary
                        self.logger.info(
                            f"🚨 [{profile_name}] Circuit breaker active: "
                            f"{breaker_info['reason']} "
                            f"({time_remaining}s remaining)"
                        )
            
        except Exception as e:
            self.logger.error(f"Error monitoring circuit breakers: {e}", exc_info=True)
            
    def _convert_dust(self):
        """
        Convert dust to USDC for all profiles
        Runs periodically (default: every 6 hours)
        """
        try:
            self.logger.info("🧹 Starting periodic dust conversion...")
            
            # Convert dust for all profiles
            results = self.dust_converter.convert_dust_all_profiles()
            
            # Count successes and log summary
            successful = sum(1 for r in results.values() if r is not None)
            total = len(results)
            
            if successful > 0:
                self.logger.info(
                    f"✅ Dust conversion complete: {successful}/{total} profiles"
                )
                
                # Send Telegram notification with summary
                self._send_telegram(
                    f"🧹 Dust conversion complete\n"
                    f"Converted dust for {successful}/{total} profiles",
                    MessagePriority.NORMAL
                )
            else:
                self.logger.info("No dust to convert for any profile")
            
            # Refresh balances after conversion to update cache
            if successful > 0:
                self.logger.debug("Refreshing balances after dust conversion...")
                self._monitor_balances()
            
        except Exception as e:
            self.logger.error(f"Error converting dust: {e}", exc_info=True)
            self._send_telegram(
                f"❌ Error during dust conversion: {str(e)}",
                MessagePriority.HIGH
            )


    def _check_signals(self):
        """
        Check for trading signals and execute trades
        Only processes signals from profiles with signal generation enabled
        """
        try:
            profile_manager = get_profile_manager()
            if profile_manager is None:
                self.logger.error("Profile manager not initialized")
                return
            
            # Get all profiles that have signal generation enabled
            signal_profiles = [
                profile for profile in profile_manager.get_all_profiles()
                if getattr(profile, 'enable_signal_generation', False)
            ]
            
            if not signal_profiles:
                self.logger.debug("No profiles with signal generation enabled")
                return
            
            self.logger.info(f"Checking signals for {len(signal_profiles)} profile(s)...")
            
            for profile in signal_profiles:
                try:
                    self._process_signals_for_profile(profile)
                except Exception as e:
                    self.logger.error(
                        f"Error processing signals for {profile.name}: {e}",
                        exc_info=True
                    )
        
        except Exception as e:
            self.logger.error(f"Error checking signals: {e}", exc_info=True)
    
    def _process_signals_for_profile(self, profile: TradingProfile):
        """Process trading signals for a specific profile"""
        
        from services.signal_generator import get_signal_generator
        
        signal_gen = get_signal_generator(profile)
        
        # Scan all monitored tickers
        signals = signal_gen.scan_symbols(self.tickers)
        
        if not signals:
            self.logger.debug(f"[{profile.name}] No signals generated")
            return
        
        self.logger.info(
            f"[{profile.name}] Generated {len(signals)} signal(s)"
        )
        
        # Process each signal
        for signal in signals:
            try:
                
                # Check cooldown (don't signal same symbol too frequently)
                cooldown_key = f"{profile.name}_{signal.symbol}"
                last_signal_time = self._last_signals.get(cooldown_key, 0)
                cooldown_seconds = getattr(profile, 'signal_cooldown_seconds', 300)  # 5 min default
                
                if time.time() - last_signal_time < cooldown_seconds:
                    remaining = cooldown_seconds - (time.time() - last_signal_time)
                    self.logger.info(
                        f"[{profile.name}] {signal.symbol} on cooldown "
                        f"({remaining:.0f}s remaining)"
                    )
                    continue
                
                # Check circuit breakers
                circuit_breaker = get_circuit_breaker()
                can_trade, breaker_reason = circuit_breaker.check_circuit_breakers(
                    profile_name=profile.name,
                    alert_action="buy"
                )
                
                if not can_trade:
                    self.logger.warning(
                        f"[{profile.name}] 🚨 Circuit breaker blocked signal: {breaker_reason}"
                    )
                    continue
                
                # Execute trade
                self._execute_signal(signal, profile)
                
                # Update last signal time
                self._last_signals[cooldown_key] = time.time()
                
            except Exception as e:
                self.logger.error(
                    f"[{profile.name}] Error executing signal for {signal.symbol}: {e}",
                    exc_info=True
                )
    
    def _execute_signal(self, signal: TradingSignal, profile: TradingProfile):
        """Execute a trading signal"""
        from api_builders.trading_builder import TradingService
        
        if signal.action != "BUY":
            self.logger.debug(f"[{profile.name}] Ignoring non-BUY signal")
            return
        
        self.logger.info(
            f"[{profile.name}] 🎯 EXECUTING SIGNAL: {signal.symbol} "
            f"({signal.strength.name}, {signal.confidence:.1f}%)"
        )
        
        # Create trading service
        trading = TradingService(profile)
        
        try:

            quantity, size_reason = self.position_calculator.calculate_buy_quantity(
                symbol=signal.symbol,
                profile=profile,
                quote_asset="USDC"
            )
            
            if quantity is None:
                self.logger.warning(
                    f"[{profile.name}] Cannot calculate position size: {size_reason}"
                )
                return

            self.logger.info(
                f"[{profile.name}] Calculated position size: {quantity:.6f} - {size_reason}"
            )
                                                
            # Execute market buy
            result = trading.order_buy(
                symbol=signal.symbol,
                quantity=str(quantity),  # Use profile's default order size
                source=f"SIGNAL_{signal.strength.name}",
                profile_name=profile.name,
                reason_summary=signal.reasons
            )
            
            if result:
                self.logger.info(
                    f"[{profile.name}] ✅ Signal executed: {result.id}, "
                    f"Qty: {result.executed_quantity}, "
                    f"Price: ${float(result.executed_quote_quantity)/float(result.executed_quantity):.4f}"
                )
                
                # Send Telegram notification
                executed_price = float(result.executed_quote_quantity) / float(result.executed_quantity)
                
                self._send_telegram(
                    f"🎯 Signal Trade Executed [{profile.name}]\n"
                    f"Symbol: {signal.symbol}\n"
                    f"Strength: {signal.strength.name} ({signal.confidence:.0f}%)\n"
                    f"Price: ${executed_price:.4f}\n"
                    f"Quantity: {result.executed_quantity}\n"
                    f"Reasons:\n" + "\n".join(f"  {r}" for r in signal.reasons),
                    MessagePriority.NORMAL
                )
            
        except Exception as e:
            self.logger.error(
                f"[{profile.name}] Failed to execute signal: {e}",
                exc_info=True
            )
            
            self._send_telegram(
                f"❌ Signal execution failed [{profile.name}]\n"
                f"Symbol: {signal.symbol}\n"
                f"Error: {str(e)}",
                MessagePriority.HIGH
            )

def set_monitoring_service(service: MonitoringService):
    """Set the monitoring service instance (called from main.py)"""
    global _monitoring_service
    _monitoring_service = service

def get_monitoring_service() -> MonitoringService:
    """Get the monitoring service instance"""
    if _monitoring_service is None:
        return None
    return _monitoring_service



