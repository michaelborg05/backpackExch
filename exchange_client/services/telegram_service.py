# services/telegram_hybrid.py
"""
Hybrid Telegram bot that automatically switches between:
- Polling mode (local development - no webhook URL)
- Webhook mode (production - with webhook URL)
"""
import logging
import asyncio
from typing import Optional
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
from services.profile_manager import get_profile_manager


class TelegramService:
    """
    Smart Telegram bot that auto-detects mode:
    - Polling if no webhook_url provided (local dev)
    - Webhook if webhook_url provided (production)
    """
    
    def __init__(
        self, 
        token: str, 
        allowed_chat_id: int, 
        webhook_url: Optional[str] = None
    ):
        """
        Args:
            token: Telegram bot token
            allowed_chat_id: Chat ID to listen to
            webhook_url: Webhook URL (None = polling mode)
        """
        self.token = token
        self.allowed_chat_id = allowed_chat_id
        self.webhook_url = webhook_url
        self.use_webhook = webhook_url is not None and webhook_url != ""
        
        self.logger = log_manager.get_logger("TelegramService")
        self.profile_manager = get_profile_manager()
        self.app: Optional[Application] = None
        self.bot: Optional[Bot] = None
        self._initialized = False

        # Silence telegram logs
        logging.getLogger("telegram").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)

    async def initialize(self):
        """Initialize bot - auto-detects polling vs webhook mode with timeout protection"""
        if self._initialized:
            self.logger.warning("Bot already initialized")
            return
        
        mode = "WEBHOOK" if self.use_webhook else "POLLING"
        self.logger.info(f"Initializing Telegram bot in {mode} mode...")
        
        try:
            # Build application with connection timeout
            self.logger.debug("Building Telegram application...")
            self.app = (
                ApplicationBuilder()
                .token(self.token)
                .connect_timeout(15.0)  # 15 second connection timeout
                .read_timeout(15.0)     # 15 second read timeout
                .build()
            )
            self.bot = self.app.bot
            
            # Initialize app (this calls bot.get_me() which can timeout)
            self.logger.debug("Initializing Telegram application...")
            await self.app.initialize()
            
            if self.use_webhook:
                # === WEBHOOK MODE (Production) ===
                self.logger.info(f"Setting webhook: {self.webhook_url}")
                
                webhook_info = await self.bot.get_webhook_info()
                
                if webhook_info.url != self.webhook_url:
                    await self.bot.set_webhook(
                        url=self.webhook_url,
                        allowed_updates=["message"],
                        drop_pending_updates=True
                    )
                    self.logger.info("✅ Webhook configured successfully")
                else:
                    self.logger.info("✅ Webhook already configured")
                    
            else:
                # === POLLING MODE (Local Development) ===
                self.logger.info("Starting polling mode for local development...")
                
                # Add message handler
                self.app.add_handler(
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, 
                        self._handle_message_polling
                    )
                )
                
                # Start polling
                await self.app.start()
                await self.app.updater.start_polling(drop_pending_updates=True)
                
                self.logger.info("✅ Polling mode active")
            
            self._initialized = True
            self.logger.info(f"Telegram bot initialization complete ({mode} mode)")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Telegram bot: {e}", exc_info=True)
            # Clean up partial initialization
            if self.app:
                try:
                    await self.app.shutdown()
                except:
                    pass
            self.app = None
            self.bot = None
            raise  # Re-raise to let caller handle
        
    async def shutdown(self):
        """Shutdown the bot"""
        if not self._initialized:
            return
        
        self.logger.info("Shutting down Telegram bot...")
        
        if not self.use_webhook and self.app and self.app.updater:
            # Stop polling
            await self.app.updater.stop()
        
        if self.app:
            await self.app.stop()
            await self.app.shutdown()
        
        self._initialized = False
        self.logger.info("Telegram bot shut down")

    async def _handle_message_polling(
        self, 
        update: Update, 
        context: ContextTypes.DEFAULT_TYPE
    ):
        """Handler for polling mode (local dev)"""
        if not update.message:
            return

        chat_id = update.message.chat_id

        # Ignore messages from other chats
        if chat_id != self.allowed_chat_id:
            self.logger.debug(f"Ignoring message from unauthorized chat: {chat_id}")
            return
        
        text = update.message.text or ""
        user = update.message.from_user.username or "Unknown"
        self.logger.info(f"[POLLING] Message from {user}: {text}")
        
        # Process command
        await self._handle_command(chat_id, text, context.bot)

    async def process_update(self, update_data: dict):
        """
        Process webhook update (webhook mode only).
        Called by FastAPI endpoint.
        
        IMPORTANT: Must respond quickly to avoid Telegram timeout (60s limit)
        """
        if not self._initialized:
            self.logger.warning("Bot not initialized")
            return
        
        if not self.use_webhook:
            self.logger.warning("process_update called but bot is in polling mode")
            return
        
        try:
            update = Update.de_json(update_data, self.bot)
            
            if not update or not update.message:
                return
            
            chat_id = update.message.chat_id
            
            if chat_id != self.allowed_chat_id:
                self.logger.debug(f"Ignoring message from unauthorized chat: {chat_id}")
                return
            
            text = update.message.text or ""
            user = update.message.from_user.username or "Unknown"
            self.logger.info(f"[WEBHOOK] Message from {user}: {text}")
            
            # ⭐ CRITICAL: Process command asynchronously to avoid webhook timeout
            # Don't await - let it run in background
            asyncio.create_task(self._handle_command(chat_id, text, self.bot))
            
            # Return immediately - Telegram gets quick response
            
        except Exception as e:
            self.logger.error(f"Error processing webhook update: {e}", exc_info=True)


    async def _handle_command(self, chat_id: int, text: str, bot: Bot):
        """Handle incoming text commands (works for both modes)"""
        try:
            match text.lower():
                case "ping":
                    await bot.send_message(
                        chat_id=chat_id,
                        text="🏓 Pong!"
                    )

                case "balance" | "b":
                    # Send "processing" message first
                    processing_msg = await bot.send_message(
                        chat_id=chat_id,
                        text="💰 Fetching balances..."
                    )
                    
                    try:
                        cache = get_portfolio_cache()
                        
                        if not self.profile_manager:
                            self.logger.warning("Profile manager not initialized")
                            balances = cache.print_portfolio_summary(profile_name="default")
                            balance_text = (
                                f"💰 <b>Current Balances:</b>\n\n{balances}"
                                if balances else "❌ No balance data available"
                            )
                            
                            # Delete "processing" message and send result
                            await bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                            await bot.send_message(
                                chat_id=chat_id,
                                text=balance_text,
                                parse_mode="HTML"
                            )
                        else:
                            profiles = self.profile_manager.get_all_profiles()
                            
                            # Delete "processing" message
                            await bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                            
                            # Send each profile's balance
                            for profile in profiles:
                                balances = cache.print_portfolio_summary(profile_name=profile.name)
                                balance_text = (
                                    f"💰 {balances}"
                                    if balances 
                                    else f"❌ No balance for {profile.name}"
                                )
                                await bot.send_message(
                                    chat_id=chat_id,
                                    text=balance_text,
                                    parse_mode="HTML"
                                )
                    
                    except Exception as e:
                        # Delete processing message and show error
                        try:
                            await bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                        except:
                            pass
                        
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"❌ Error fetching balances: {str(e)}"
                        )
                
                case "mode":
                    mode = "Webhook" if self.use_webhook else "Polling (Local)"
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"🤖 Bot Mode: <b>{mode}</b>",
                        parse_mode="HTML"
                    )
                            
                case _:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"Echo: {text}"
                    )
        
        except Exception as e:
            self.logger.error(f"Error in _handle_command: {e}", exc_info=True)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Error processing command: {str(e)}"
                )
            except:
                pass  # Failed to send error message
            
    async def send_message(
        self, 
        message: str, 
        priority: MessagePriority = MessagePriority.NORMAL, 
        parse_mode: str = "HTML"
    ) -> bool:
        """Send a message (works in both modes)"""
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
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Type:</b> {order_type}\n"
            f"<b>Symbol:</b> {symbol}\n"
            f"<b>Side:</b> {side.upper()}\n"
            f"<b>Quantity:</b> {quantity}\n"
            f"<b>Price:</b>{price_str}\n"
        )
        
        if order_id:
            message += f"<b>Order ID:</b> <code>{order_id}</code>\n"
        
        priority = MessagePriority.NORMAL if status == "executed" else MessagePriority.HIGH
        return await self.send_message(message, priority=priority)
    
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
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Message:</b> {error_message}\n"
        )
        
        if endpoint:
            message += f"<b>Endpoint:</b> {endpoint}\n"
        
        if details:
            message += f"\n<b>Details:</b>\n"
            for key, value in details.items():
                message += f"  • {key}: {value}\n"

        return await self.send_message(message, priority=MessagePriority.CRITICAL)
    
    def _get_priority_emoji(self, priority: MessagePriority) -> str:
        """Get emoji based on priority"""
        emoji_map = {
            MessagePriority.LOW: "ℹ️",
            MessagePriority.NORMAL: "",
            MessagePriority.HIGH: "⚠️",
            MessagePriority.CRITICAL: "🚨"
        }
        return emoji_map.get(priority, "")
    
    # === SYNC WRAPPERS ===
    
    def send_message_sync(
        self, 
        message: str, 
        priority: MessagePriority = MessagePriority.NORMAL, 
        parse_mode: str = "HTML"
    ) -> bool:
        """
        Synchronous wrapper for send_message.
        Works from any thread, including background monitoring threads.
        """
        try:
            import asyncio
            import threading
            
            # Try to get current event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context - create task
                asyncio.create_task(self.send_message(message, priority, parse_mode))
                return True
            except RuntimeError:
                # No running loop - we're in a sync context
                # Create new event loop in a separate thread
                result = [False]  # Use list to allow modification in thread
                
                def run_in_thread():
                    try:
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        try:
                            result[0] = new_loop.run_until_complete(
                                self.send_message(message, priority, parse_mode)
                            )
                        finally:
                            new_loop.close()
                    except Exception as e:
                        self.logger.error(f"Error in telegram thread: {e}")
                
                thread = threading.Thread(target=run_in_thread, daemon=True)
                thread.start()
                thread.join(timeout=5)  # Wait max 5 seconds
                return result[0]
                
        except Exception as e:
            self.logger.error(f"Error in send_message_sync: {e}")
            return False
            
    def send_error_notification_sync(
        self, 
        error_type: str,
        error_message: str,
        endpoint: Optional[str] = None,
        details: Optional[dict] = None
    ) -> bool:
        """Synchronous wrapper for send_error_notification"""
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(
                    self.send_error_notification(error_type, error_message, endpoint, details)
                )
                return True
            except RuntimeError:
                return asyncio.run(
                    self.send_error_notification(error_type, error_message, endpoint, details)
                )
        except Exception as e:
            self.logger.error(f"Error in send_error_notification_sync: {e}")
            return False


# Global instance
_telegram: Optional[TelegramService] = None


def get_telegram() -> Optional[TelegramService]:
    """Get the global Telegram instance"""
    return _telegram


def set_telegram(instance: TelegramService):
    """Set the global Telegram instance"""
    global _telegram
    _telegram = instance