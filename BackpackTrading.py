import requests
import time
import random
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
base_url = "https://api.backpack.exchange"


def check_SOL_Price():
    """
    Make your API call here. Replace with your actual API endpoint and logic.
    """
    try:
        # Example API call - replace with your actual endpoint
        url = base_url + "/api/v1/ticker?symbol=SOL_USDC&interval=1d"
        headers = {
            "User-Agent": "Python-Script/1.0"
            # Add any required headers like API keys here
            # "Authorization": "Bearer YOUR_API_KEY"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        
        data = response.json()
        logging.info(f"API call successful. Status: {response.status_code}")
        
        # Process your data here
        
        print(f"Response data: {data.get('firstPrice','firstPrice not found')}")
        
        return True
        
    except requests.exceptions.RequestException as e:
        logging.error(f"API call failed: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return False

def main():
    """
    Main loop that continuously makes API calls with random delays
    """
    logging.info("Starting continuous API caller...")
    call_count = 0
    
    try:
        while True:
            call_count += 1
            logging.info(f"Making API call #{call_count}")
            
            # Make the API call
            success = check_SOL_Price()
            
            if success:
                logging.info("API call completed successfully")
            else:
                logging.warning("API call failed")
            
            # Generate random wait time between 30-180 seconds
            wait_time = random.randint(30, 180)
            logging.info(f"Waiting {wait_time} seconds until next call...")
            
            time.sleep(wait_time)
            
    except KeyboardInterrupt:
        logging.info("Script interrupted by user. Shutting down...")
    except Exception as e:
        logging.error(f"Unexpected error in main loop: {e}")

if __name__ == "__main__":
    main()