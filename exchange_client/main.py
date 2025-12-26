import uvicorn
from services.api_server import app, set_monitoring_service
from services.monitoring_service import MonitoringService
from utils.logging import log_manager
from utils.config import Config
from pathlib import Path
from services.telegram_listener import TelegramListener, get_telegram_listener, init_telegram_listener
import time

project_root = Path(__file__).parent
config = Config()
main_logger = log_manager.get_logger("main")


if __name__ == "__main__":
    main_logger.info("Starting application...")
    
    # Initialize and start monitoring service
    monitoring = MonitoringService()

    # Inject monitoring service into FastAPI app
    set_monitoring_service(monitoring)
    
    # Start monitoring
    monitoring.start()

    #Initialize and start Telegram listener
    if config.telegram_bot_token:
        telegram = init_telegram_listener(
                token=config.telegram_bot_token,
                chat_id=config.chat_group_id
            )
            
        # Send startup notification
        telegram.send_message_sync("🚀 Bot started successfully!")        
    else: 
        main_logger.warning("No TELEGRAM_BOT_TOKEN found in configuration; Telegram listener will not start.")  

    try:
        # Start FastAPI server (this blocks)
        
        
        main_logger.info(f"Starting API server on port {config.port}...")

        uvicorn.run(app, host="0.0.0.0", port=config.port)
    except KeyboardInterrupt:
        main_logger.info("Application interrupted by user")
    finally:
        # Cleanup
        main_logger.info("Shutting down monitoring service...")
        monitoring.stop()
        main_logger.info("Application shutdown complete")




