import logging
import sys
from datetime import datetime

def setup_logger(log_location: str,level: str = "INFO") -> logging.Logger:
    """
    Setup logger with consistent formatting
    
    Args:
        REMOVED name: Logger name
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        REMOVED log_file: Optional log file path
        
    Returns:
        Configured logger instance
    """

    logger = logging.getLogger(log_location)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Clear existing handlers
    logger.handlers = []
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger


#def log_price_update(logger: logging.Logger, symbol: str, price: float, change: Optional[float] = None):
#    """Log price update with consistent format"""
#    change_str = f" (change: {change:+.4f})" if change else ""
#    logger.info(f"{symbol} price update: ${price:.4f}{change_str}")
