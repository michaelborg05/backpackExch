from services.api_server import get_event_loop
from utils.logging import log_manager
from services.telegram_listener import get_telegram_listener
import asyncio

logger = log_manager.get_logger("send_telegram_message_sync")


def send_telegram_message_sync( message: str):
    telegram = get_telegram_listener()
    loop = get_event_loop()

    if not loop or not telegram:
        logger.warning("Telegram or event loop not available")
        return


    try:
        future = asyncio.run_coroutine_threadsafe(
            telegram.send_message(message),
            loop
        )
        # Optional: wait briefly or handle exceptions
        future.add_done_callback(_handle_result)
    except Exception as e:
        logger.error(f"Failed to dispatch telegram message: {e}")


def _handle_result(future):
    try:
        future.result()
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
