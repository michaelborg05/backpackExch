import logging
from pathlib import Path
from utils.config import Config

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
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)
    
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)

# Global instance
log_manager = LoggingManager()