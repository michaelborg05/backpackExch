import time
import random
from utils.logging import setup_logger
from datetime import datetime
from config import Config
from api.client import check_price
from pathlib import Path
from api.endpoints import APIEndpoints

project_root = Path(__file__).parent

def main():
    # Setup
    config = Config()
    logger = setup_logger(config.log_location, config.log_level)

    logger.info(f"Debug mode is {'on' if config.debug_mode else 'off'}")
    logger.info(f"Log level set to {config.log_level}")

    """
    Main loop that continuously makes API calls with random delays
    """
    logger.info("Starting continuous API caller...")
    call_count = 0
    
    try:
        while True:
            call_count += 1
            logger.info(f"Making API call #{call_count}")
            url = APIEndpoints.backpack_ticker("SOL_USDC")
            # Make the API call
            success = check_price(url)
            
            if success:
                logger.info("API call completed successfully")
            else:
                logger.warning("API call failed")
            
            # Generate random wait time between 30-180 seconds
            wait_time = random.randint(30, 180)
            logger.info(f"Waiting {wait_time} seconds until next call...")
            
            time.sleep(wait_time)
            
    except KeyboardInterrupt:
        logger.info("Script interrupted by user. Shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")

if __name__ == "__main__":
    main()


