import time
import threading
from typing import List, Optional
from utils.logging import log_manager
from utils.config import Config
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price


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
        
    def start(self):
        """Start the monitoring loop in a background thread"""
        if self.is_running:
            self.logger.warning("Monitoring service is already running")
            return
        
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
            "interval": self.config.monitor_delay_interval
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
                get_price(ticker)
            except Exception as e:
                self.logger.error(f"Error getting price for {ticker}: {e}")
    
    def _monitor_balances(self):
        """Monitor account balances"""
        try:
            balances = get_balances(source="GUI")
            if balances:
                self.logger.info(balances.summary())
        except Exception as e:
            self.logger.error(f"Error getting balances: {e}")
