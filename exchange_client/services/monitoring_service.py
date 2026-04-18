import json
import time
import threading
from typing import List,  Dict,Optional
from models.signal_validation import SignalValidationResult
from services.position_manager import get_position_manager
from utils.logging import log_manager
from utils.config import Config
from utils.constants import MessagePriority, OrderStatus
from utils.exceptions import InvalidQuantityError, InsufficientBalanceError, TradingException
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price, get_market_info, check_ticker
from api_builders.factory import get_adapter
from api_builders.atr_calculator import get_atr_calculator
from api_builders.dust_conversion import get_dust_converter
from cache.balance_cache import get_balance_cache
from cache.price_cache import get_price_cache
from cache.portfolio_cache import get_portfolio_cache
from cache.market_info_cache import get_market_info_cache
from models.balance import BalanceReader
from models.trading_profile import TradingProfile
from models.trading_signal import TradingSignal
from models.trade import OrderResponse
from services.telegram_service import get_telegram
from services.circuit_breaker import get_circuit_breaker
from services.profile_manager import get_profile_manager, load_profiles_from_db
from services.signal_generator import get_signal_generator, invalidate_all_signal_generators
from utils.position_calculator import get_position_size_calculator
from cache.trend_cache import initialize_trend_cache_with_db
from cache.trend_cache_warmup import warmup_trend_cache
import os
from utils.settings_helper import get_settings_helper
from db.utils import get_db_session
from db.crud import (
    get_open_positions,
    update_position_trailing_stop,
    close_invalid_position,
    update_high_low,
    get_active_orders,
    get_position,
)
from cache.symbol_cache import get_symbol_cache

class MonitoringService:
    """Service for monitoring market prices and account balances"""
    
    def __init__(self):
        """
        Initialize monitoring service
        """
        self.config = Config()
        self.logger = log_manager.get_logger("MonitoringService")
        self.settings = get_settings_helper()
        #self.tickers = tickers or ["SOL_USDC", "ETH_USDC", "HYPE_USDC", "SUI_USDC"]
        self._symbol_cache = get_symbol_cache()

        with get_db_session() as db:
                self._symbol_cache.refresh(db)
                trend_cache = initialize_trend_cache_with_db()
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

        self.circuit_breaker = get_circuit_breaker()
        self._circuit_breaker_counter = 0

        self.dust_converter = get_dust_converter()
        self._dust_conversion_counter = 0

        self._signal_check_counter = 0

        self._last_signals: Dict[str, float] = {}  # Track last signal time per symbol

        self._trend_invalidation_counter = 0
        self.position_validation_counter = 0
        self._profile_refresh_counter = 0

    @property
    def tickers(self) -> list:
        return self._symbol_cache.get_all_symbols()

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
    
        try:
            while self.is_running:
                self.call_count += 1
                self.position_validation_counter += 1
                self._atr_update_counter += 1
                self._circuit_breaker_counter += 1 
                self._dust_conversion_counter += 1
                self._signal_check_counter += 1
                self._trend_invalidation_counter += 1
                self._profile_refresh_counter += 1
                self.logger.debug(f"Beginning loop #{self.call_count}")

                    
                # Monitor prices for all tickers
                self._monitor_prices()
                
                # Get account balances
                self._monitor_balances()

                if self._circuit_breaker_counter >= self.settings.circuit_breaker_interval:
                    self._monitor_circuit_breakers()
                    self._circuit_breaker_counter = 0

                #monitor open orders
                self._monitor_orders()

                # Monitor open balances and check for SL/TP/Trailing SL
                self._monitor_open_positions()

                # Update ATR periodically (less frequently than prices)
                if self._atr_update_counter >= self.settings.atr_update_interval:
                    self._monitor_atr()
                    self._atr_update_counter = 0

                # Validate positions periodically (less frequently)
                if self.position_validation_counter >= self.settings.position_validation_interval:
                    self.logger.info("Running position validation...")
                    self._validate_open_positions()
                    self.position_validation_counter = 0

                if self._dust_conversion_counter >= self.settings.dust_conversion_interval:
                    self._convert_dust()
                    self._dust_conversion_counter = 0

                if self._signal_check_counter >= self.settings.signal_check_interval:
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
        from utils.endpoints import APIEndpoints
        for ticker in self.tickers:
            try:
                url = APIEndpoints.backpack_ticker(ticker, "1d")
                tk = check_ticker(url)
                if tk and tk.last_price:
                    print(tk.simple_summary())
                    self.price_cache.update_ticker(
                        ticker,
                        str(tk.last_price),
                        change_percent=tk.price_change_percent,
                        high=tk.high,
                        low=tk.low,
                        volume=tk.volume,
                    )
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

    def _monitor_orders(self):
        # Check active orders 
        profile_manager = get_profile_manager()

        if profile_manager is None:
            self.logger.error("Profile manager not initialized. Skipping open position monitoring.")
            return 
        
        # Use the context manager - session is automatically closed
        profiles = profile_manager._profiles.values()
        for profile in profiles:
            with get_db_session() as db:
                #get open orders from DB
                open_orders = get_active_orders(db, profile.name)

                adapter = get_adapter(profile)

                for order in open_orders:
                    order_response = adapter.process_limit_order(order=order, position_id=order.position_id)
                    
                    if order_response and order_response.status == OrderStatus.FILLED:
                        entry_price = order_response.entry_price if order_response.entry_price  else "N/A"
                        exit_price = order_response.exit_price if order_response.exit_price  else  "N/A"
                        icon = "🟢" if order.purpose == "TAKE_PROFIT" else "🛑"
                        self._send_telegram(
                            f"{icon} Position Closed [{profile.display_name if profile.display_name else profile.name}]\n"
                            f"Symbol: {order_response.symbol}\n"
                            f"Reason: {order.purpose}\n"
                            f"Entry: ${entry_price}\n"
                            f"Exit: ${exit_price}\n"
                            f"Quantity: {order_response.executedQuantity:.4f}\n"
                            f"P/L: ${order_response.profit:.2f}",
                            MessagePriority.NORMAL
                        )
                        # ← NEW: resolve the AI signal outcome if this position was
                        # opened from an AI_AGENT signal
                        position = get_position(db, order.position_id)
                        if position.ai_log_id is not None:
                            from db.crud_ai import resolve_ai_signal_outcome
                            from datetime import datetime, timezone
                            resolve_ai_signal_outcome(
                                db=db,
                                ai_log_id=position.ai_log_id,
                                exit_price=exit_price,
                                entry_price=entry_price,
                                close_reason=order.purpose,
                                closed_at=datetime.now(timezone.utc),
                            )

                    #else:
                    #    self.logger.warning(f"Order {order.exchange_order_id} not filled.")

    def close_open_order(self):
        """Close an open order."""
        pass

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
                    is_long = (position.direction or "LONG") != "SHORT"

                    # Calculate current profit percentage (direction-aware)
                    if is_long:
                        profit_pct = ((price - entry_price) / entry_price) * 100
                    else:
                        profit_pct = ((entry_price - price) / entry_price) * 100

                    # TAKE PROFIT (direction-aware)
                    if position.tp_price:
                        tp = float(position.tp_price)
                        tp_hit = (is_long and price >= tp) or (not is_long and price <= tp)
                        if tp_hit:
                            self.logger.info(f"TP hit for {symbol} @ {price} [{profile.name}]")
                            #self._send_telegram(f"🎯 TP hit for {symbol} @ {price} [{profile.name}]")
                            self._execute_close(db, position, profile, reason="TAKE_PROFIT")
                            continue

                    # STOP LOSS (direction-aware)
                    if position.sl_price:
                        sl = float(position.sl_price)
                        sl_hit = (is_long and price <= sl) or (not is_long and price >= sl)
                        if sl_hit:
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
                                # Set initial trailing stop loss price at arm threshold (direction-aware)
                                trailing_pct = float(profile.trailing_stop_pct)
                                if is_long:
                                    position.trailing_sl_price = max(
                                        float(price) * (1 - trailing_pct / 100),
                                        float(position.entry_price) * 1.0005  # +0.05%
                                    )
                                else:
                                    position.trailing_sl_price = min(
                                        float(price) * (1 + trailing_pct / 100),
                                        float(position.entry_price) * 0.9995  # -0.05%
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
                            trailing_pct = float(profile.trailing_stop_pct)

                            if is_long:
                                # Long: trail up — watermark is highest_price
                                watermark = float(position.highest_price or 0)
                                if price > watermark:
                                    new_watermark = price
                                    new_trailing_sl = max(
                                        float(price) * (1 - trailing_pct / 100),
                                        float(position.entry_price) * 1.0005  # +0.05%
                                    )
                                    update_position_trailing_stop(
                                        db, position.id,
                                        highest_price=new_watermark,
                                        trailing_sl_price=new_trailing_sl,
                                    )
                                    self.logger.debug(
                                        f"Updated trailing SL for {symbol}: {new_trailing_sl:.4f} "
                                        f"(profit: {profit_pct:.2f}%) [{profile.name}]"
                                    )
                                elif price <= float(position.trailing_sl_price):
                                    self.logger.info(
                                        f"Trailing SL hit for {symbol} @ {price} "
                                        f"(profit: {profit_pct:.2f}%) [{profile.name}]"
                                    )
                                    self._execute_close(db, position, profile, reason="TRAILING_STOP")
                            else:
                                # Short: trail down — watermark is lowest_price
                                watermark = float(position.lowest_price or float('inf'))
                                if price < watermark:
                                    new_watermark = price
                                    new_trailing_sl = min(
                                        float(price) * (1 + trailing_pct / 100),
                                        float(position.entry_price) * 0.9995  # -0.05%
                                    )
                                    update_position_trailing_stop(
                                        db, position.id,
                                        highest_price=new_watermark,  # reusing column for lowest watermark
                                        trailing_sl_price=new_trailing_sl,
                                    )
                                    self.logger.debug(
                                        f"Updated trailing SL for {symbol}: {new_trailing_sl:.4f} "
                                        f"(profit: {profit_pct:.2f}%) [{profile.name}]"
                                    )
                                elif price >= float(position.trailing_sl_price):
                                    self.logger.info(
                                        f"Trailing SL hit for {symbol} @ {price} "
                                        f"(profit: {profit_pct:.2f}%) [{profile.name}]"
                                    )
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

                    if self._trend_invalidation_counter >= self.settings.trend_invalidation_interval:
                        self._trend_invalidation_counter = 0
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
        Validate open positions against the exchange.
        Close positions where the token has been closed externally but our DB wasn't updated.
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

                is_perp = getattr(profile, "market_type", "SPOT") == "PERP"

                if is_perp:
                    # For perp profiles, validate against live exchange positions
                    self._validate_perp_positions(db, profile, open_positions)
                else:
                    # For spot profiles, validate against cached wallet balances
                    self._validate_spot_positions(db, profile, open_positions, balance_cache)

    def _validate_perp_positions(self, db, profile, open_positions):
        """Validate perp positions by querying the exchange account for live open positions."""
        try:
            adapter = get_adapter(profile)
            account_data = adapter.get_account()
        except Exception as e:
            self.logger.warning(f"Could not fetch account data for {profile.name}: {e}")
            return

        if not account_data:
            self.logger.warning(f"Empty account response for {profile.name}, skipping perp validation")
            return

        # Build a set of symbols with non-zero size on the exchange
        # Bullet /fapi/v3/account returns {"positions": [{"symbol": "SOL-USD", "positionAmt": "0.33", ...}]}
        exchange_positions = account_data.get("positions", [])
        live_symbols = set()
        for ep in exchange_positions:
            amt = float(ep.get("positionAmt", 0) or ep.get("size", 0) or 0)
            if abs(amt) > 0:
                live_symbols.add(ep.get("symbol", ""))

        for position in open_positions:
            symbol = position.symbol  # e.g. "SOL-USD"
            if symbol not in live_symbols:
                self.logger.warning(
                    f"INVALID POSITION DETECTED: {symbol} for {profile.name}. "
                    f"No live perp position found on exchange."
                )
                close_invalid_position(db, position.id, reason="INVALID_POSITION")
                self.logger.info(
                    f"Closed invalid position {position.id} for {symbol} - "
                    f"position closed externally on exchange"
                )
                self._send_telegram(
                    f"⚠️ Closed invalid position for {symbol} - position closed externally on exchange"
                )

    def _validate_spot_positions(self, db, profile, open_positions, balance_cache):
        """Validate spot positions against cached wallet balances."""
        cached_balances = balance_cache.get_profile_balances(profile.name)

        if not cached_balances:
            self.logger.warning(f"No cached balances for profile {profile.name}, skipping validation")
            return

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
                current_balance = float(balance_info.get('available', 0)) + float(balance_info.get('locked', 0))

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

    def _execute_close(self, db, position, profile, reason: str, reason_summary: list[str] = None):
        """
        Execute a close order for a position.

        Args:
            db            : Database session
            position      : Position object to close
            profile       : TradingProfile for this position
            reason        : TAKE_PROFIT | STOP_LOSS | TRAILING_STOP | TREND_INVALIDATION | ...
            reason_summary: Optional list of reason strings for trade record
        """
        try:
            adapter = get_adapter(profile)
            symbol = position.symbol
            validation_summary = ""
            # If stop loss, analyse market conditions and record in db for review later
#            if reason=="STOP_LOSS":
            validation_summary = self.record_market_validation_info(symbol, profile)

            quantity = str(position.remaining_quantity)

            self.logger.info(
                f"Executing close order: {symbol} x {quantity} "
                f"[{profile.name}] Reason: {reason}"
            )

            result = adapter.order_sell(
                symbol=symbol,
                quantity=quantity,
                source=reason,
                profile_name=profile.name,
                position_id=str(position.id),
                reason_summary=reason_summary,
                validation_summary=validation_summary
            )
            
            if result:
                self.logger.info(
                    f"Close order executed successfully: {result.id} "
                    f"[{profile.name}] Quantity: {result.executed_quantity}"
                )
                
                # Calculate profit/loss (direction-aware)
                entry_price = float(position.entry_trade.price)
                exit_price = float(result.executed_quote_quantity) / float(result.executed_quantity)
                quantity_sold = float(result.executed_quantity)
                is_long = (position.direction or "LONG") != "SHORT"
                if is_long:
                    profit = (exit_price - entry_price) * quantity_sold
                    profit_pct = ((exit_price - entry_price) / entry_price) * 100
                else:
                    profit = (entry_price - exit_price) * quantity_sold
                    profit_pct = ((entry_price - exit_price) / entry_price) * 100

                # ← NEW: resolve the AI signal outcome if this position was
                # opened from an AI_AGENT signal
                if position.ai_log_id is not None:
                    from db.crud_ai import resolve_ai_signal_outcome
                    from datetime import datetime, timezone
                    resolve_ai_signal_outcome(
                        db=db,
                        ai_log_id=position.ai_log_id,
                        exit_price=exit_price,
                        entry_price=entry_price,
                        close_reason=reason,
                        closed_at=datetime.now(timezone.utc),
                    )

                icon = "🟢" if profit_pct >= 0 else "🛑"
                
                # Send detailed notification
                self._send_telegram(
                    f"{icon} Position Closed [{profile.display_name if profile.display_name else profile.name}]\n"
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
                    f"❌ Failed to close position for {symbol} [{profile.display_name if profile.display_name else profile.name}]",
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
                    f"⚠️ Closed invalid position for {position.symbol} [{profile.display_name if profile.display_name else profile.name}] - "
                    f"quantity too small or already sold",
                    MessagePriority.NORMAL
                )
            else:
                # Some other quantity issue
                self._send_telegram(
                    f"❌ Invalid quantity for {position.symbol} [{profile.display_name if profile.display_name else profile.name}]: {e.message}",
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
                f"⚠️ Closed invalid position for {position.symbol} [{profile.display_name if profile.display_name else profile.name}] - "
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
                f"❌ Error closing position for {position.symbol} [{profile.display_name if profile.display_name else profile.name}]: {e.message}",
                MessagePriority.HIGH
            )
        
        except Exception as e:
            # Handle unexpected errors
            self.logger.error(
                f"Unexpected error executing close order for {position.symbol} [{profile.name}]: {e}",
                exc_info=True
            )
            self._send_telegram(
                f"❌ Unexpected error closing position for {position.symbol} [{profile.display_name if profile.display_name else profile.name}]: {str(e)}",
                MessagePriority.HIGH
            )

    def record_market_validation_info(self, symbol: str, profile) -> str:
        """
        Record market validation information from the order response.
        Add to db table with trend and entry info to understand more on why Stop loss was hit
        """
        from models.signal_validation import ValidationGroup, MarketContext
        from utils.constants import TradeSide
        from cache.trend_cache import get_trend_cache

        validation = SignalValidationResult(
            timestamp=time.time(),
            symbol=symbol,
            signal_timeframe="15",
            strategy_type=profile.strategy_type.value,
            order_type=TradeSide.SELL,
            score=0.0,
            score_components=0,
            market_context=MarketContext(),
            trend_validation=ValidationGroup(enabled=profile.use_trend_filter),
            entry_validation=ValidationGroup(enabled=profile.use_entry_filter)
        )
        trend_cache = get_trend_cache()
        
        if profile.use_trend_filter:
            indicators_config = getattr(profile, 'trend_indicators', None)
            min_required = getattr(profile, 'min_indicators_required', 2)

            is_bullish, trend_reason, indicator_results = trend_cache.is_bullish(
                symbol=symbol,
                timeframe="60",
                indicators_config=indicators_config,
                min_indicators_required=min_required,
                return_structured=True
            )

            validation.trend_validation.timeframe = "60"
            validation.trend_validation.passed = is_bullish
            validation.trend_validation.indicators = indicator_results
            validation.trend_validation.indicators_total = len(indicator_results)
            validation.trend_validation.indicators_passed = sum(
                1 for ind in indicator_results if ind.is_bullish
            )
            validation.trend_validation.summary = trend_reason

        if profile.use_entry_filter:

            entry_indicators_config = getattr(profile, 'entry_indicators', None)
            min_required = getattr(profile, 'min_entry_indicators_required', 2)

            if entry_indicators_config is not None:
                is_bullish, entry_reason, entry_indicators = trend_cache.is_bullish(
                    symbol=symbol,
                    timeframe="15",
                    indicators_config=entry_indicators_config,
                    min_indicators_required=min_required,
                    return_structured=True
                )

                validation.entry_validation.timeframe = profile.entry_timeframe
                validation.entry_validation.passed = is_bullish
                validation.entry_validation.indicators = entry_indicators
                validation.entry_validation.indicators_total = len(entry_indicators)
                validation.entry_validation.indicators_passed = sum(
                    1 for ind in entry_indicators if ind.is_bullish
                )
                validation.entry_validation.summary = entry_reason

        parts = []
        if validation.trend_validation.enabled:
            icon = "✅" if validation.trend_validation.passed else "❌"
            parts.append(f"{icon} Trend ({validation.trend_validation.timeframe}m): "
                        f"{validation.trend_validation.indicators_passed}/{validation.trend_validation.indicators_total}")
        if validation.entry_validation.enabled:
            icon = "✅" if validation.entry_validation.passed else "❌"
            parts.append(f"{icon} Entry ({validation.entry_validation.timeframe}m): "
                        f"{validation.entry_validation.indicators_passed}/{validation.entry_validation.indicators_total}")
        
        validation.human_readable = " | ".join(parts)
        validation.overall_passed = True

        validation_details=validation.to_json()

        return validation_details

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
            
            #fail safe to convert 
            safe_msg = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            # Use the thread-safe sync wrapper
            success = telegram.send_message_sync(safe_msg, priority)

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
        Convert dust to USDC for all active Backpack exchange accounts
        Runs periodically (default: every 6 hours)
        """
        try:
            self.logger.info("🧹 Starting periodic dust conversion...")

            results = self.dust_converter.convert_dust_all_accounts()

            # Count successes and log summary
            successful = sum(1 for r in results.values() if r is not None)
            total = len(results)

            if successful > 0:
                self.logger.info(
                    f"✅ Dust conversion complete: {successful}/{total} accounts"
                )

                # Send Telegram notification with summary
                self._send_telegram(
                    f"🧹 Dust conversion complete\n"
                    f"Converted dust for {successful}/{total} accounts",
                    MessagePriority.NORMAL
                )
            else:
                self.logger.info("No dust to convert for any account")

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
            return None

        #retrieve list of tickers for this profile
        profile_tickers = self._symbol_cache.get_symbols_for_profile(profile.name)

        symbols_to_scan: list[str] = []
        #Filter symbols list down before moving to signal generator to reduce wasted effort of checking for signals on symbols that are blocked already
        for ticker in profile_tickers:
            # Check cooldown (don't signal same symbol too frequently)
            cooldown_key = f"{profile.name}_{ticker}"
            last_signal_time = self._last_signals.get(cooldown_key, 0)
            cooldown_seconds = getattr(profile, 'signal_cooldown_seconds', 300)  # 5 min default
            
            if time.time() - last_signal_time < cooldown_seconds:
                remaining = cooldown_seconds - (time.time() - last_signal_time)
                self.logger.info(
                    f"[{profile.name}]  - skipping scan of {ticker} - still in cooldown "
                    f"({remaining:.0f}s remaining)"
                )
                continue

            #check buy quantity. If none, dont bother scanning this symbol
            quantity, size_reason = self.position_calculator.calculate_buy_quantity(
                symbol=ticker,
                profile=profile,
                quote_asset="USDC"
            )

            if quantity is None:
                self.logger.info(
                    f"[{profile.name}] Skipping scan of {ticker}: {size_reason}"
                )
                continue

            symbols_to_scan.append(ticker)
        

        signal_gen = get_signal_generator(profile)

        # Scan all monitored tickers
        signals = signal_gen.scan_symbols(symbols_to_scan)
        
        if not signals:
            self.logger.debug(f"[{profile.name}] No signals generated")
            return
        
        self.logger.info(
            f"[{profile.name}] Generated {len(signals)} signal(s)"
        )
        
        # Process each signal
        for signal in signals:
            try:
                
                # Execute trade
                self._execute_signal(signal, profile)
                
                # Update last signal time
                cooldown_key = f"{profile.name}_{signal.symbol}"

                self._last_signals[cooldown_key] = time.time()
                
            except Exception as e:
                self.logger.error(
                    f"[{profile.name}] Error executing signal for {signal.symbol}: {e}",
                    exc_info=True
                )
    
    def _execute_signal(self, signal: TradingSignal, profile: TradingProfile, trading=None):
        """Execute a trading signal"""
        adapter = get_adapter(profile)

        is_long_signal = signal.action in ("BUY", "LONG")
        is_short_signal = signal.action in ("SELL", "SHORT")

        if not is_long_signal and not is_short_signal:
            self.logger.debug(f"[{profile.name}] Ignoring unrecognised signal action: {signal.action}")
            return
        
        self.logger.info(
            f"[{profile.name}] 🎯 EXECUTING SIGNAL: {signal.symbol} "
            f"({signal.strength.name}, {signal.confidence:.1f}%) {signal.action.value}"
        )
        
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

            # Apply BB position scalar from signal (1.0 = no change, <1.0 = reduce size)
            # This is applied AFTER all portfolio/balance/cap checks so those constraints
            # are always enforced against the full intended size first.
            from decimal import Decimal
            scalar = Decimal(str(getattr(signal, 'position_size_scalar', 1.0)))
            if scalar != Decimal("1.0"):
                original_quantity = quantity
                quantity = quantity * scalar
                self.logger.info(
                    f"[{profile.name}] BB scalar {float(scalar):.2f}x applied: "
                    f"{float(original_quantity):.6f} → {float(quantity):.6f}"
                )
                # Re-check minimum after scaling — a large scalar reduction could bring
                # the USDC value below the exchange minimum
                price = self.price_cache.get_price(signal.symbol)
                if price and quantity * price < Decimal("5"):
                    self.logger.warning(
                        f"[{profile.name}] Order too small after BB scalar "
                        f"(${float(quantity * price):.2f}), skipping"
                    )
                    return

            # Execute market order (direction-aware)
            order_kwargs = dict(
                symbol=signal.symbol,
                quantity=str(quantity),
                source=f"SIGNAL_{signal.strength.name}",
                profile_name=profile.name,
                reason_summary=signal.reasons,
                validation_summary=signal.validation_details,
            )
            if is_long_signal:
                result = adapter.order_buy(**order_kwargs)
            else:
                # SHORT: open via order_sell with no position_id (entry, not close)
                result = adapter.order_sell(**order_kwargs)
            
            if result:

                executed_price = float(result.executed_quote_quantity) / float(result.executed_quantity)

                self.logger.info(
                    f"[{profile.name}] ✅ Signal executed: {result.id}, "
                    f"Qty: {result.executed_quantity}, "
                    f"Price: ${executed_price:.4f}"
                )

                # ← NEW: if this signal came from the AI agent, stamp the
                # ai_log_id onto the freshly-opened position so we can
                # resolve the outcome when it closes.
                ai_log_id = getattr(signal, 'ai_log_id', None)
                if ai_log_id is not None:
                    self._stamp_ai_log_id_on_position(
                        symbol=signal.symbol,
                        profile_name=profile.name,
                        ai_log_id=ai_log_id,
                    )

                self._send_telegram(
                    f"🎯 Signal Trade Executed [{profile.display_name if profile.display_name else profile.name}]\n"
                    f"Symbol: {signal.symbol}\n"
                    f"Strength: {signal.strength.name} ({signal.confidence:.0f}%)\n"
                    f"Price: ${executed_price:.4f}\n"
                    f"Quantity: {result.executed_quantity}"
                    + (f" (BB scalar: {float(scalar):.2f}x)" if scalar != Decimal("1.0") else "") + "\n"
                    f"Reasons:\n" + "\n".join(f"  {r}" for r in signal.reasons),
                    MessagePriority.NORMAL
                )
            
        except Exception as e:
            self.logger.error(
                f"[{profile.name}] Failed to execute signal: {e}",
                exc_info=True
            )
            
            self._send_telegram(
                f"❌ Signal execution failed [{profile.display_name if profile.display_name else profile.name}]\n"
                f"Symbol: {signal.symbol}\n"
                f"Error: {str(e)}",
                MessagePriority.HIGH
            )


    # ← NEW helper — called right after order_buy fills
    def _stamp_ai_log_id_on_position(
        self,
        symbol: str,
        profile_name: str,
        ai_log_id: int,
    ) -> None:
        """
        Find the freshly-opened OPEN position for this symbol/profile and
        write ai_log_id onto it.

        We query for the most-recently-created OPEN position rather than
        relying on a position_id returned from order_buy, which avoids
        needing to change TradingService's return contract.
        """
        try:
            from db.models import Position
            with get_db_session() as db:
                position = (
                    db.query(Position)
                    .filter(
                        Position.profile_name == profile_name,
                        Position.symbol == symbol,
                        Position.status == "OPEN",
                        Position.ai_log_id.is_(None),   # don't overwrite if already set
                    )
                    .order_by(Position.created_at.desc())
                    .first()
                )
                if position:
                    position.ai_log_id = ai_log_id
                    db.commit()
                    self.logger.info(
                        f"[{profile_name}] Stamped ai_log_id={ai_log_id} "
                        f"onto position id={position.id} ({symbol})"
                    )
                else:
                    self.logger.warning(
                        f"[{profile_name}] Could not find open position for {symbol} "
                        f"to stamp ai_log_id={ai_log_id}"
                    )
        except Exception as e:
            self.logger.error(
                f"Failed to stamp ai_log_id={ai_log_id} onto position: {e}",
                exc_info=True
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