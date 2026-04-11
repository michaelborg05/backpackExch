import logging
from pathlib import Path
from utils.config import Config

class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors to console output."""
    
    # ANSI Escape Codes for Colors
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: grey + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)
    
class LoggingManager:
    def __init__(self):
        config = Config()
        Path(config.log_location).parent.mkdir(parents=True, exist_ok=True)
        
        # Setup root logger that all others inherit from
        root = logging.getLogger()
        root.setLevel(config.log_level)
        root.handlers = []
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # All loggers write to same file
        file_handler = logging.FileHandler(config.log_location)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(ColoredFormatter())
        root.addHandler(console_handler)
    
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)

# Global instance
log_manager = LoggingManager()
