# services/telegram_listener.py (fixed version)
from re import match
import threading
import asyncio
import logging
from typing import Optional, Callable
from telegram import Bot, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters
)

from utils.logging import log_manager
from utils.constants import MessagePriority
from services.portfolio_cache import get_portfolio_cache


class TelegramListener:
    def __init__(self, token: str, allowed_chat_id: int):
        self.token = token
        self.allowed_chat_id = allowed_chat_id
        self.logger = log_manager.get_logger("TelegramListener")

        self.app: Optional[Application] = None
        self.bot: Optional[Bot] = None
        self._running = False

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

        # Silence telegram polling chatter
        logging.getLogger("telegram").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)


    async def start(self):
        """Initialize and start the bot"""
        if self._running:
            self.logger.warning("Bot already running")
            return
        
        self.logger.info("Initializing Telegram bot...")
        self.app = ApplicationBuilder().token(self.token).build()
        self.bot = self.app.bot
        
        # Add message handler
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
        
        # Initialize app
        await self.app.initialize()
        await self.app.start()
        
        self._running = True
        self.logger.info("Telegram bot started successfully")
        
        # Start polling (non-blocking)
        await self.app.updater.start_polling()

    async def stop(self):
        """Stop the bot gracefully"""
        if not self._running:
            return
        
        self.logger.info("Stopping Telegram bot...")
        
        if self.app and self.app.updater:
            await self.app.updater.stop()
        if self.app:
            await self.app.stop()
            await self.app.shutdown()
        
        self._running = False
        self.logger.info("Telegram bot stopped")



    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return

        chat_id = update.message.chat_id

        # 🚫 Ignore messages from other chats
        if chat_id != self.allowed_chat_id:
            return
        
        text = update.message.text or ""
        user = update.message.from_user.username or "Unknown"
        self.logger.info(f"Received message from {user} in chat {chat_id}: {text}")
        
        match text.lower():
            case "ping":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="🏓 Pong!"
                )

            case "balance" | "b":
                cache = get_portfolio_cache()
                balances = cache.print_portfolio_summary(profile_name="default")
                
                if balances:
                    balance_text = "💰 <b>Current Balances:</b>\n\n"
                    balance_text += balances
                else:
                    balance_text = "❌ No balance data available"

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=balance_text,
                    parse_mode="HTML"
                )
                    
            case _:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Echo: {text}"
                )

    async def send_message(self, message: str, priority: MessagePriority = MessagePriority.NORMAL, parse_mode: str = "HTML") -> bool:
        """Send a message (async)"""
        if not self.bot:
            self.logger.warning("Bot not initialized yet")
            return False
        
        try:
            emoji = self._get_priority_emoji(priority)
            formatted_message = f"{emoji} {message}"
            await self.bot.send_message(
                chat_id=self.allowed_chat_id,
                text=formatted_message,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to send message: {e}")
            return False
    
    async def send_order_notification(
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
        return self.send_message(message, priority=priority)
    
    async def send_error_notification(
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

        priority = MessagePriority.CRITICAL
        return await self.send_message(message, priority=priority)
    
    async def send_webhook_notification(
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
        return await self.send_message(message, priority=priority)
    
    def _get_priority_emoji(self, priority: MessagePriority) -> str:
        """Get emoji based on priority"""
        emoji_map = {
            MessagePriority.LOW: "ℹ️",
            MessagePriority.NORMAL: "📌",
            MessagePriority.HIGH: "⚠️",
            MessagePriority.CRITICAL: "🚨"
        }
        return emoji_map.get(priority, "📌")


# Global instance
_telegram_listener: Optional[TelegramListener] = None


def get_telegram_listener() -> Optional[TelegramListener]:
    """Get the global Telegram listener instance"""
    return _telegram_listener


def set_telegram_listener(listener: TelegramListener):
    """Set the global Telegram listener instance"""
    global _telegram_listener
    _telegram_listener = listener

