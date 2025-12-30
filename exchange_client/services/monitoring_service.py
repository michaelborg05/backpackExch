import time
import threading
from typing import List,  Dict,Optional
from utils.logging import log_manager
from utils.config import Config
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price
from services.balance_cache import get_balance_cache
from services.price_cache import get_price_cache
from services.portfolio_cache import get_portfolio_cache
from services.market_info_cache import get_market_info_cache
from api_builders.market_builder import get_market_info

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
        
        try:
            while self.is_running:
                self.call_count += 1
                self.logger.debug(f"Beginning loop #{self.call_count}")
                
                # Monitor prices for all tickers
                self._monitor_prices()
                
                # Get account balances
                self._monitor_balances()
                
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
        """Monitor account balances"""
        try:
            balances = get_balances(source="MonitoringService")
            if balances:
                self.logger.debug(balances.summary())
                # Update cache with latest balances
                # Assuming balances has a method to convert to dict
                balance_dict = self._convert_balances_to_dict(balances)
                self.balance_cache.update(balance_dict)
                portfolio = get_portfolio_cache()
                portfolio_summary =  portfolio.print_portfolio_summary()

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


def set_monitoring_service(service: MonitoringService):
    """Set the monitoring service instance (called from main.py)"""
    global _monitoring_service
    _monitoring_service = service

def get_monitoring_service() -> MonitoringService:
    """Get the monitoring service instance"""
    if _monitoring_service is None:
        return None
    return _monitoring_service

