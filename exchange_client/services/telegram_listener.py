from re import match
import threading
import asyncio
import logging
from utils.logging import log_manager
from telegram import Update
from utils.constants import MessagePriority
from typing import Optional, Callable
from telegram import Bot
from services.balance_cache import get_balance_cache
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters
)


class TelegramListener(threading.Thread):
    def __init__(self, token: str, allowed_chat_id: int):
        super().__init__(daemon=True)
        self.token = token
        self.allowed_chat_id = allowed_chat_id
        self.telegram_logger = log_manager.get_logger("TelegramListener")

        # ADD THESE THREE LINES:
        self.bot: Optional[Bot] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.message_callback: Optional[Callable] = None

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

        # Silence telegram polling chatter
        logging.getLogger("telegram").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return

        chat_id = update.message.chat_id

        # 🚫 Ignore messages from other chats
        if chat_id != self.allowed_chat_id:
            return
        
        text = update.message.text or ""
        user = update.message.from_user.username
        self.telegram_logger.info(f"Received message from {user} in chat {chat_id}: {text}")
        match text.lower():
            case "ping":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="pong"
                )

            case "balance":
                cache = get_balance_cache()
                balances = cache.get_all_balances()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Current Balances:\n" + "\n".join(
                        f"{asset}: {data['available']} available, {data['locked']} locked"
                        for asset, data in balances.items()
                    )
                )
            case _:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Echo: {text}"
                )


    async def _run_bot(self):
        app = ApplicationBuilder().token(self.token).build()

        self.bot = app.bot
        self.loop = asyncio.get_event_loop()

        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        self.telegram_logger.info("Telegram bot started and listening...")
        await asyncio.Event().wait()


    def run(self):
        asyncio.run(self._run_bot())

    def send_message_sync(
        self, 
        message: str, 
        priority: MessagePriority = MessagePriority.NORMAL,
        parse_mode: str = "HTML"
    ) -> bool:
        """Send a message from any thread"""
        if not self.bot or not self.loop:
            self.telegram_logger.warning("Bot not initialized yet")
            return False
        
        try:
            emoji = self._get_priority_emoji(priority)
            formatted_message = f"{emoji} {message}"
            
            future = asyncio.run_coroutine_threadsafe(
                self._send_message_async(formatted_message, parse_mode),
                self.loop
            )
            
            future.result(timeout=5)
            return True
            
        except Exception as e:
            self.telegram_logger.error(f"Failed to send message: {e}")
            return False
    
    async def _send_message_async(self, message: str, parse_mode: str):
        """Internal async method to send message"""
        await self.bot.send_message(
            chat_id=self.allowed_chat_id,
            text=message,
            parse_mode=parse_mode
        )
    
    def send_order_notification(
        self, 
        order_type: str,
        symbol: str, 
        side: str,
        quantity: str,
        price: Optional[str] = None,
        order_id: Optional[str] = None,
        status: str = "executed"
    ) -> bool:
        """Send order execution notification"""
        price_str = f" @ ${price}" if price else " (Market)"
        side_emoji = "🟢" if side.lower() in ["bid", "buy"] else "🔴"
        
        message = (
            f"<b>{side_emoji} Order {status.upper()}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Type:</b> {order_type}\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Side:</b> {side.upper()}\n"
            f"<b>Quantity:</b> {quantity}\n"
            f"<b>Price:</b>{price_str}\n"
        )
        
        if order_id:
            message += f"<b>Order ID:</b> <code>{order_id}</code>\n"
        
        priority = MessagePriority.NORMAL if status == "executed" else MessagePriority.HIGH
        return self.send_message_sync(message, priority=priority)
    
    def send_error_notification(
        self, 
        error_type: str,
        error_message: str,
        endpoint: Optional[str] = None,
        details: Optional[dict] = None
    ) -> bool:
        """Send error notification"""
        message = (
            f"<b>⚠️ ERROR: {error_type}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Message:</b> {error_message}\n"
        )
        
        if endpoint:
            message += f"<b>Endpoint:</b> {endpoint}\n"
        
        if details:
            message += f"\n<b>Details:</b>\n"
            for key, value in details.items():
                message += f"  • {key}: {value}\n"
        
        return self.send_message_sync(message, priority=MessagePriority.HIGH)
    
    def send_webhook_notification(
        self,
        source: str,
        action: str,
        symbol: str,
        success: bool,
        details: Optional[str] = None
    ) -> bool:
        """Send webhook received notification"""
        status_emoji = "✅" if success else "❌"
        
        message = (
            f"<b>{status_emoji} Webhook Received</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Source:</b> {source}\n"
            f"<b>Action:</b> {action.upper()}\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Status:</b> {'Success' if success else 'Failed'}\n"
        )
        
        if details:
            message += f"\n{details}"
        
        priority = MessagePriority.NORMAL if success else MessagePriority.HIGH
        return self.send_message_sync(message, priority=priority)
    
    def _get_priority_emoji(self, priority: MessagePriority) -> str:
        """Get emoji based on priority"""
        emoji_map = {
            MessagePriority.LOW: "ℹ️",
            MessagePriority.NORMAL: "📌",
            MessagePriority.HIGH: "⚠️",
            MessagePriority.CRITICAL: "🚨"
        }
        return emoji_map.get(priority, "📌")
    
_telegram_listener: Optional[TelegramListener] = None

def get_telegram_listener() -> Optional[TelegramListener]:
    """Get the global Telegram listener instance"""
    return _telegram_listener


def init_telegram_listener(token: str, chat_id: int) -> TelegramListener:
    """Initialize and start the Telegram listener"""
    global _telegram_listener
    _telegram_listener = TelegramListener(token, chat_id)
    _telegram_listener.start()
    return _telegram_listener