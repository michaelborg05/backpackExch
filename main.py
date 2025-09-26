import time
import random
from utils.logging import log_manager
from datetime import datetime
from config import Config
from api.client import get_prices, get_balances
from pathlib import Path

project_root = Path(__file__).parent
config = Config()
main_logger = log_manager.get_logger("main")

def main():
    # Setup
    main_logger.info("App starting...")

    main_logger.info(f"Debug mode is {'on' if config.debug_mode else 'off'}")
    main_logger.info(f"Log level set to {config.log_level}")

    """
    Main loop that continuously makes API calls with random delays
    """
    main_logger.info("Starting continuous API caller...")
    call_count = 0
    
    try:
        while True:
            call_count += 1
            main_logger.info(f"Beginning loop #{call_count}")
            get_prices("SOL_USDC")
            #get_prices("ETH_USDC")
            balances = get_balances()
            # Generate random wait time between 30-180 seconds
            main_logger.info(balances.summary())
            wait_time = random.randint(30, 180)
            main_logger.info(f"Waiting {wait_time} seconds until next call...")
            
            time.sleep(wait_time)
            
    except KeyboardInterrupt:
        main_logger.info("Script interrupted by user. Shutting down...")
    except Exception as e:
        main_logger.error(f"Unexpected error in main loop: {e}")

if __name__ == "__main__":
    main()


