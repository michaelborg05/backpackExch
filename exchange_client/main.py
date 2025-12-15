import time
import random
from utils.logging import log_manager
from datetime import datetime
from utils.config import Config
from api_builders.account_builder import get_balances
from api_builders.market_builder import get_price
from pathlib import Path

project_root = Path(__file__).parent
config = Config()
main_logger = log_manager.get_logger("main")

def main():
    # Setup
    main_logger.debug("App starting...")

    main_logger.debug(f"Debug mode is {'on' if config.debug_mode else 'off'}")
    main_logger.debug(f"Log level set to {config.log_level}")

    """
    Main loop that continuously makes API calls with random delays
    """
    main_logger.debug("Starting continuous API caller...")
    call_count = 0
    tickers = ["SOL_USDC","ETH_USDC","HYPE_USDC"]   # Comma-separated list of tickers

    try:
        while True:
            call_count += 1
            main_logger.debug(f"Beginning loop #{call_count}")
            for ticker in tickers:
                get_price(ticker)
            #get_prices("ETH_USDC")
            balances = get_balances()
            # Generate random wait time between 30-180 seconds
            if balances:
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


