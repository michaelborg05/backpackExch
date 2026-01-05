import time
import threading
from typing import List,  Dict,Optional
from utils.logging import log_manager
from utils.config import Config
from utils.constants import MessagePriority
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price
from api_builders.trading_builder import TradingService
from models.balance import BalanceReader
from services.balance_cache import get_balance_cache
from services.price_cache import get_price_cache
from services.portfolio_cache import get_portfolio_cache
from services.market_info_cache import get_market_info_cache
from services.telegram_service import get_telegram
from api_builders.market_builder import get_market_info
from services.profile_manager import get_profile_manager
from db.utils import get_db_session
from db.crud import (
    get_open_positions,
    update_position_trailing_stop,
    close_position,
    get_profile_by_name,
    save_trade
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
        self.tickers = tickers or ["SOL_USDC", "ETH_USDC", "HYPE_USDC", "MON_USDC"]
        self.is_running = False
        self.thread = None
        self.call_count = 0
        self.balance_cache = get_balance_cache()  # Get cache instance
        self.price_cache = get_price_cache()    # Get price cache instance
        self.market_info_cache = get_market_info_cache()
        self._markets_initialized = False

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
                self.logger.debug(f"Beginning loop #{self.call_count}")
                
                # Monitor prices for all tickers
                self._monitor_prices()
                
                # Get account balances
                self._monitor_balances()

                # Monitor open balances and check for SL/TP/Trailing SL
                self._monitor_open_positions()

                # Validate positions periodically (less frequently)
                if validation_counter >= validation_interval:
                    self.logger.info("Running position validation...")
                    self._validate_open_positions()
                    validation_counter = 0

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
        
        profile_manager = get_profile_manager()
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

                    # TAKE PROFIT
                    if position.tp_price and price >= float(position.tp_price):
                        self.logger.info(f"TP hit for {symbol} @ {price} [{profile.name}]")
                        self._send_telegram(f"🎯 TP hit for {symbol} @ {price} [{profile.name}]")
                        self._execute_close(db, position, profile, reason="TAKE_PROFIT")
                        continue

                    # STOP LOSS
                    if position.sl_price and price <= float(position.sl_price):
                        self.logger.info(f"SL hit for {symbol} @ {price} [{profile.name}]")
                        self._send_telegram(f"🛑 SL hit for {symbol} @ {price} [{profile.name}]")
                        self._execute_close(db, position, profile, reason="STOP_LOSS")
                        continue

                    # TRAILING STOP LOGIC
                    if profile.use_trailing_stop and position.trailing_sl_price:
                        highest = float(position.highest_price or 0)

                        if price > highest:
                            new_high = price
                            trailing_pct = float(profile.trailing_stop_pct)
                            new_trailing_sl = new_high * (1 - trailing_pct / 100)

                            update_position_trailing_stop(
                                db,
                                position.id,
                                highest_price=new_high,
                                trailing_sl_price=new_trailing_sl,
                            )

                            self.logger.debug(
                                f"Updated trailing SL for {symbol}: {new_trailing_sl:.4f} [{profile.name}]"
                            )
                        elif price <= float(position.trailing_sl_price):
                            self.logger.info(f"Trailing SL hit for {symbol} @ {price} [{profile.name}]")
                            self._send_telegram(f"📉 Trailing SL hit for {symbol} @ {price} [{profile.name}]")
                            self._execute_close(db, position, profile, reason="TRAILING_STOP")

    def _validate_open_positions(self):
        """
        Validate open positions against cached balances.
        Close positions where the token has been sold but position wasn't updated.
        """
        from db.utils import get_db_session
        from db.crud import close_invalid_position

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
                    
                    # Get the buy trade to check quantity
                    buy_trade = position.buy_trade
                    if not buy_trade:
                        self.logger.warning(f"Position {position.id} has no buy_trade, skipping")
                        expected_quantity = 0.01
                    else:
                        expected_quantity = float(buy_trade.quantity)

                    # Check if balance is insufficient
                    if balance_info is None:
                        current_balance = 0
                    else:
                        current_balance = float(balance_info.get('available', 0))
                    
                    # If balance is zero or less than 1% of expected, position is invalid
                    if current_balance < (expected_quantity * 0.01):  # 1% threshold
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

    def _execute_close(self, db, position, profile, reason: str):
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
            
            # Get the quantity from the buy trade
            if not position.buy_trade:
                self.logger.warning(f"Position {position.id} has no buy_trade, Closing with MAX")
                quantity = "MAX"
            else:
                quantity = str(position.buy_trade.quantity)

            symbol = position.symbol
            
            self.logger.info(
                f"Executing close order: {symbol} x {quantity} "
                f"[{profile.name}] Reason: {reason}"
            )
            
            # Execute sell order with "MAX" to ensure we sell everything
            result = trading.order_sell(
                symbol=symbol,
                quantity="MAX",  # Use MAX to sell all available
                source=reason,
                profile_name=profile.name
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
                
                # Send detailed notification
                self._send_telegram(
                    f"✅ Position Closed [{profile.name}]\n"
                    f"Symbol: {symbol}\n"
                    f"Reason: {reason}\n"
                    f"Entry: ${entry_price:.4f}\n"
                    f"Exit: ${exit_price:.4f}\n"
                    f"Quantity: {quantity_sold:.4f}\n"
                    f"P/L: ${profit:.2f} ({profit_pct:+.2f}%)",
                    MessagePriority.HIGH
                )
                
                # Note: Position will be closed automatically by TradingService.ExecuteOrder
                # which calls close_position() for SELL orders
                
            else:
                self.logger.error(f"Close order failed for {symbol} [{profile.name}]")
                self._send_telegram(
                    f"❌ Failed to close position for {symbol} [{profile.name}]",
                    MessagePriority.HIGH
                )
                
        except Exception as e:
            self.logger.error(
                f"Error executing close order for {position.symbol} [{profile.name}]: {e}",
                exc_info=True
            )
            self._send_telegram(
                f"❌ Error closing position for {position.symbol} [{profile.name}]: {str(e)}",
                MessagePriority.HIGH
            )    
    
    def _send_telegram(self, message: str, priority: MessagePriority = MessagePriority.NORMAL):
        """Helper to send Telegram messages from sync context"""
        try:
            telegram = get_telegram()
            if telegram and telegram._initialized:
                telegram.send_message_sync(message, priority)
        except Exception as e:
            self.logger.debug(f"Could not send Telegram message: {e}")

def set_monitoring_service(service: MonitoringService):
    """Set the monitoring service instance (called from main.py)"""
    global _monitoring_service
    _monitoring_service = service

def get_monitoring_service() -> MonitoringService:
    """Get the monitoring service instance"""
    if _monitoring_service is None:
        return None
    return _monitoring_service

