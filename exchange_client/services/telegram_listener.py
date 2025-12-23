import threading
import asyncio
import logging
from utils.logging import log_manager
from telegram import Update
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
        
        if text.lower() == "ping":
            await context.bot.send_message(
                chat_id=chat_id,
                text="pong"
            )

        else: 
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Echo: {text}"
            )


    async def _run_bot(self):
        app = ApplicationBuilder().token(self.token).build()

        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )

        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()
        

    def run(self):
        asyncio.run(self._run_bot())
