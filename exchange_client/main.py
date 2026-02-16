import uvicorn
from services.api_server import app
from services.monitoring_service import MonitoringService, set_monitoring_service
from utils.logging import log_manager
from utils.config import Config
from pathlib import Path
from services.profile_manager import load_profiles, set_profile_manager  
from cache.settings_cache import initialize_settings_cache

project_root = Path(__file__).parent
config = Config()
main_logger = log_manager.get_logger("main")


if __name__ == "__main__":
    main_logger.info("Starting application...")

    main_logger.info("Loading settings cache...")
    settings_cache = initialize_settings_cache(refresh_interval=900)
    # Load and set profile manager 
    main_logger.info("Loading trading profiles...")
    profile_manager = load_profiles()
    set_profile_manager(profile_manager)  
    main_logger.info(f"Loaded {len(profile_manager._profiles)} trading profiles")

    # Initialize and start monitoring service
    monitoring = MonitoringService()
    # Inject monitoring service into FastAPI app
    set_monitoring_service(monitoring)
    # Start monitoring
    profile_manager = load_profiles()

    monitoring.start()

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




