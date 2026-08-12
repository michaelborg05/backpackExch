# services/telegram_hybrid.py
"""
Hybrid Telegram bot that automatically switches between:
- Polling mode (local development - no webhook URL)
- Webhook mode (production - with webhook URL)
"""
import logging
import asyncio
import time
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
from cache.portfolio_cache import get_portfolio_cache
from cache.price_cache import get_price_cache
from services.profile_manager import get_profile_manager
from db.utils import get_db_session
from db.crud import get_active_symbols, get_open_positions


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

        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._shutting_down = False

    async def initialize(self):
        """Initialize bot - auto-detects polling vs webhook mode with timeout protection"""
        if self._initialized:
            self.logger.warning("Bot already initialized")
            return
        
        # Store reference to the main event loop
        self._main_loop = asyncio.get_running_loop()

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
        self._shutting_down = True

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
        self._main_loop = None
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
            # Commands are a single word, optionally followed by an argument
            # ("why btc"), so match on the verb and keep the rest as the arg.
            command, _, arg = text.strip().lower().partition(" ")
            arg = arg.strip()

            match command:
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
                    
                    msg = self.get_balance_data()

                    # Delete "processing" message and send result
                    await bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                    await bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                        parse_mode="HTML"
                    )
                
                case "mode":
                    mode = "Webhook" if self.use_webhook else "Polling (Local)"
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"🤖 Bot Mode: <b>{mode}</b>",
                        parse_mode="HTML"
                    )
                case "positions" | "p":
                    # Send "processing" message first
                    processing_msg = await bot.send_message(
                        chat_id=chat_id,
                        text="💰 Fetching positions..."
                    )
                    
                    msg = self.get_position_data()
                    await bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                    await bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                        parse_mode="HTML"
                    )

                case "summary" | "s":
                    # Send "processing" message first
                    processing_msg = await bot.send_message(
                        chat_id=chat_id,
                        text="📊 Building snapshot..."
                    )
                    msg = self.get_snapshot_data()
                    await bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                    await bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                        parse_mode="HTML"
                    )

                    msg = self.get_regime_data()
                    await bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                        parse_mode="HTML"
                    )

                case "why" | "w" | "blockers":
                    processing_msg = await bot.send_message(
                        chat_id=chat_id,
                        text="🧭 Checking blockers..."
                    )
                    msg = self.get_blocker_data(symbol_filter=arg or None)
                    safe_msg = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    await bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                    for chunk in self._chunk_message(safe_msg):
                        await bot.send_message(
                            chat_id=chat_id,
                            text=chunk,
                            parse_mode="HTML"
                        )

                case "trends" | "t":
                    # Full per-indicator dump (the old 'summary' output)
                    processing_msg = await bot.send_message(
                        chat_id=chat_id,
                        text="📈 Fetching trends..."
                    )
                    msg = self.get_summary_data()
                    safe_msg = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    await bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                    for chunk in self._chunk_message(safe_msg):
                        await bot.send_message(
                            chat_id=chat_id,
                            text=chunk,
                            parse_mode="HTML"
                        )

                case "help" | "h" | "commands":
                    await bot.send_message(
                        chat_id=chat_id,
                        text=self.get_help_text(),
                        parse_mode="HTML"
                    )

                case "exits" | "e" :
                    from services.reentry_manager import get_reentry_manager

                    processing_msg = await bot.send_message(
                        chat_id=chat_id,
                        text="💰 Fetching recent trans..."
                    )
                    
                    try:
                        
                        reentry_mgr = get_reentry_manager()
                        if not self.profile_manager:
                            self.logger.warning("Profile manager not initialized")
                            reentry_text = (
                                f"no profiles found"
                            )
                            
                            # Delete "processing" message and send result
                            await bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                            await bot.send_message(
                                chat_id=chat_id,
                                text=reentry_text,
                                parse_mode="HTML"
                            )
                        else:
                            profiles = self.profile_manager.get_all_profiles()
                            
                            # Delete "processing" message
                            await bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                            
                            # Collect exit summaries, skipping profiles with no exits
                            profile_summaries = []
                            for profile in profiles:
                                summary = reentry_mgr.get_recent_exits_summary(profile.name, hours=24)
                                if summary['total_exits'] > 0:
                                    profile_summaries.append((profile.display_name, summary))

                            # Sort so the busiest profiles show up first
                            profile_summaries.sort(key=lambda p: p[1]['total_exits'], reverse=True)

                            total_exits = sum(s['total_exits'] for _, s in profile_summaries)
                            summary_text = f"=== Recent Exits (24h) ===\nTotal: {total_exits} exits across {len(profile_summaries)} profile(s)"

                            if not profile_summaries:
                                summary_text += "\n\nNo exits in the last 24h"
                            else:
                                for display_name, summary in profile_summaries:
                                    summary_text += f"\n\n<b>{display_name}</b>"
                                    summary_text += f"\n  Total: {summary['total_exits']}"
                                    for reason, count in summary['by_reason'].items():
                                        summary_text += f"\n    {reason}: {count}"

                            await bot.send_message(
                                chat_id=chat_id,
                                text=summary_text,
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
                            text=f"❌ Error fetching trans: {str(e)}"
                        )

                case _:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"Unknown command: {text}\n\n{self.get_help_text()}",
                        parse_mode="HTML"
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
            #import html
            #safe_text = html.escape(message)
            safe_text = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            emoji = self._get_priority_emoji(priority)
            formatted_message = f"{emoji} {safe_text}"

            await self.bot.send_message(
                chat_id=self.allowed_chat_id,
                text=formatted_message,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to send message: {e}")
            self.logger.error(f"Failed original message: {message}")
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
        Thread-safe synchronous wrapper for send_message.
        Schedules the coroutine on the MAIN event loop (where bot was initialized).
        """
        if not self._initialized or self._shutting_down:
            self.logger.debug("Telegram not ready - skipping message")
            return False
        
        if not self._main_loop:
            self.logger.warning("Main event loop not available")
            return False
        
        try:
            # Schedule the coroutine on the main event loop (thread-safe)
            future = asyncio.run_coroutine_threadsafe(
                self.send_message(message, priority, parse_mode),
                self._main_loop
            )
            
            # Wait for result with timeout
            result = future.result(timeout=5.0)
            return result
            
        except TimeoutError:
            self.logger.warning("Telegram send timed out (5s)")
            return False
        except RuntimeError as e:
            if "Event loop is closed" in str(e):
                self.logger.debug("Event loop closed - skipping message")
                self._shutting_down = True  # Mark as shutting down
            else:
                self.logger.error(f"Runtime error in send_message_sync: {e}")
            return False
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
        """Thread-safe synchronous wrapper for send_error_notification"""
        if not self._initialized or self._shutting_down:
            return False
        
        if not self._main_loop:
            return False
        
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.send_error_notification(error_type, error_message, endpoint, details),
                self._main_loop
            )
            
            result = future.result(timeout=5.0)
            return result
            
        except TimeoutError:
            self.logger.warning("Error notification send timed out")
            return False
        except Exception as e:
            self.logger.error(f"Error in send_error_notification_sync: {e}")
            return False

    def get_regime_data(self):
        from cache.regime_filter import get_regime_filter
        try:
            regime_filter = get_regime_filter()
            with get_db_session() as db:
                db_tickers = get_active_symbols(db)
            if db_tickers:
                regime_summary = regime_filter.get_regime_summary(db_tickers)
                msg = f"📊 Regime Summary\n"
                msg = f"🌐 *Market Regime Report*\n"
                msg += f"✅ Safe: {regime_summary['safe']} | "
                msg += f"⚠️ choppy: {regime_summary['choppy']} | "
                msg += f"🚫 High Risk: {regime_summary['high_risk']}\n"
                msg += "─" * 15 + "\n"
                
                details = regime_summary.get('details', {})
                if details.get('safe'):
                    msg += "\n🟢 *TRADE READY (safe)*\n"
                    for item in details['safe']:
                        msg += f"• {item['symbol']}\n"

                # Show High Risk (Protection)
                if details.get('high_risk'):
                    msg += "\n🚫 *HALTED (High Risk)*\n"
                    for item in details['high_risk']:
                        # Your 'reason' string explains the filter (e.g., 'Low Volume' or 'High Volatility')
                        msg += f"• {item['symbol']}: _{item['reason']}_\n"

                # Optional: Only show Uncertain if there are few items, to avoid a massive wall of text
                if details.get('choppy'):
                    msg += "\n🟡 choppy\n"
                    for item in details['choppy']:
                        # Your 'reason' string explains the filter (e.g., 'Low Volume' or 'High Volatility')
                        msg += f"• {item['symbol']}: _{item['reason']}_\n"
            else:
                msg += "❌Unable to retrieve tickers from db"
            return msg
        
        except Exception as e:
            # Delete processing message and show error
            return f"❌ Error fetching regime data: {str(e)}"
            

    @staticmethod
    def _chunk_message(text: str, limit: int = 3500):
        """Split a long message on line boundaries (Telegram caps at 4096 chars)."""
        chunks, current = [], ""
        for line in text.split("\n"):
            if len(current) + len(line) + 1 > limit and current:
                chunks.append(current)
                current = ""
            current += line + "\n"
        if current.strip():
            chunks.append(current)
        return chunks or [text]

    @staticmethod
    def _age_text(timestamp) -> str:
        """'2m ago' style age for a unix timestamp."""
        if not timestamp:
            return "never"
        age = max(0, time.time() - timestamp)
        if age < 90:
            return f"{age:.0f}s ago"
        if age < 5400:
            return f"{age / 60:.0f}m ago"
        return f"{age / 3600:.1f}h ago"

    def get_help_text(self) -> str:
        return (
            "<b>Commands</b>\n"
            "• <b>s</b> / summary — market snapshot (price vs EMA50, RSI, ADX) + regime\n"
            "• <b>w</b> / why [symbol] — what blocked each profile on the last scan\n"
            "• <b>t</b> / trends — full per-indicator dump\n"
            "• <b>p</b> / positions — open positions\n"
            "• <b>b</b> / balance — balances per account\n"
            "• <b>e</b> / exits — exits in the last 24h\n"
            "• ping, mode, help"
        )

    def get_blocker_data(self, symbol_filter: Optional[str] = None) -> str:
        """Summarise why each profile isn't trading, from the last scan.

        Reads only what the scan already recorded in memory — no re-evaluation,
        no exchange or DB calls — so it reflects the most recent real cycle.
        """
        from services.signal_diagnostics import (
            get_signal_diagnostics, strip_trailing_details, STAGE_EMOJI,
        )

        try:
            diagnostics = get_signal_diagnostics()
            last_update = diagnostics.last_update()

            if last_update is None:
                return (
                    "🧭 No scan results recorded yet.\n"
                    "The monitoring loop populates this on its next signal check."
                )

            # ── Single-symbol drill-down: full reason per profile ──────────────
            if symbol_filter:
                symbol = symbol_filter.upper()
                if "_" not in symbol:
                    symbol = f"{symbol}_USDC"

                outcomes = diagnostics.for_symbol(symbol)
                if not outcomes:
                    return f"🧭 No scan record for {symbol} (not monitored, or not scanned yet)"

                msg = f"🧭 {symbol} — last scan {self._age_text(last_update)}\n"
                for outcome in outcomes:
                    emoji = STAGE_EMOJI.get(outcome.stage, "•")
                    tf = f" [{outcome.timeframe}]" if outcome.timeframe else ""
                    reason = outcome.reason
                    # Drop the trailing full-indicator dump — the failing ones
                    # are already named up front in a hard stop.
                    if "HARD STOP:" in reason:
                        reason = strip_trailing_details(
                            reason.split("HARD STOP:", 1)[1]
                        ).strip()
                    msg += f"\n<b>{outcome.display_name}</b>{tf}\n  {emoji} {reason[:300]}\n"
                return msg

            # ── Rollup: group each profile's symbols by what blocked them ─────
            msg = f"🧭 <b>Signal blockers</b> — last scan {self._age_text(last_update)}\n"

            grouped = diagnostics.by_profile()
            for display_name in sorted(grouped):
                outcomes = grouped[display_name]
                ready = [o for o in outcomes if o.passed]

                causes: dict = {}
                for outcome in outcomes:
                    if outcome.passed:
                        continue
                    causes.setdefault(outcome.cause(), []).append(
                        outcome.symbol.replace("_USDC", "")
                    )

                msg += (
                    f"\n<b>{display_name}</b> — "
                    f"{len(ready)}/{len(outcomes)} ready\n"
                )
                if ready:
                    msg += "  🎯 " + ", ".join(
                        o.symbol.replace("_USDC", "") for o in ready
                    ) + "\n"

                # Biggest blockers first — that's the one worth acting on
                for cause, symbols in sorted(
                    causes.items(), key=lambda kv: len(kv[1]), reverse=True
                ):
                    stage_emoji = "✗"
                    for outcome in outcomes:
                        if not outcome.passed and outcome.cause() == cause:
                            stage_emoji = STAGE_EMOJI.get(outcome.stage, "✗")
                            break
                    msg += (
                        f"  {stage_emoji} {cause} ×{len(symbols)}: "
                        f"{', '.join(sorted(symbols))}\n"
                    )

            msg += "\n<i>'why BTC' for the full reason per profile</i>"
            return msg

        except Exception as e:
            self.logger.error(f"Error in get_blocker_data: {e}", exc_info=True)
            return f"❌ Error building blocker summary: {str(e)}"

    def get_snapshot_data(self) -> str:
        """One line per symbol: where price sits vs EMA50, RSI and ADX per timeframe."""
        from cache.trend_cache import get_trend_cache

        try:
            trend_cache = get_trend_cache()

            with get_db_session() as db:
                symbols = sorted(get_active_symbols(db))

            if not symbols:
                return "❌ Unable to retrieve tickers from db"

            price_cache = get_price_cache()

            def pct_vs_ema50(trend, price) -> str:
                """Signed % of price above/below that timeframe's EMA50, width 5."""
                if trend is None or price is None or not trend.ema50:
                    return "    —"
                pct = (price - float(trend.ema50)) / float(trend.ema50) * 100
                return f"{pct:+5.1f}"

            def value(raw) -> str:
                """Integer indicator reading, width 3."""
                return f"{float(raw):3.0f}" if raw is not None else "  —"

            rows = ["SYM     1D%   1h% RSI ADX  15m"]
            for symbol in symbols:
                d1 = trend_cache.get(symbol, "1D")
                h1 = trend_cache.get(symbol, "60")
                m15 = trend_cache.get(symbol, "15")

                # Live price where available; a cached entry's own price is the
                # fallback (better than printing nothing for a quiet symbol).
                live = price_cache.get_price(symbol)
                price = float(live) if live else None

                def tf_price(trend):
                    if price is not None:
                        return price
                    return float(trend.price) if trend else None

                base = symbol.replace("_USDC", "")[:5]
                rows.append(
                    f"{base:<5} "
                    f"{pct_vs_ema50(d1, tf_price(d1))} "
                    f"{pct_vs_ema50(h1, tf_price(h1))} "
                    f"{value(h1.rsi if h1 else None)} "
                    f"{value(h1.adx if h1 is not None else None)}  "
                    f"{value(m15.rsi if m15 else None)}"
                )

            table = "\n".join(rows).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return (
                "📊 <b>Market Snapshot</b>\n"
                f"<pre>{table}</pre>\n"
                "<i>1D%/1h% = price vs EMA50 on that timeframe. "
                "RSI/ADX = 60m, 15m = 15m RSI. — = no cached data.</i>"
            )

        except Exception as e:
            self.logger.error(f"Error in get_snapshot_data: {e}", exc_info=True)
            return f"❌ Error building snapshot: {str(e)}"

    def get_summary_data(self):
        from cache.trend_cache import get_trend_cache
        try:
            
            trend_cache = get_trend_cache()

            # Loop through all Trend cache entries
            cached_keys = list(trend_cache._cache.keys())
            
            if not cached_keys:
                msg = "No cached trends available"
            else:
                msg = "📈 Current Trends:\n"
                for key in cached_keys:
                    # Split the key back into components
                    # Using rsplit allows for symbols with underscores if they exist
                    symbol, timeframe = key.rsplit('_', 1)
                    if timeframe=='240':
                        continue 
                    # Call your is_bullish method
                    # This will use your configured indicator logic (EMA, RSI, VWAP)
                    is_bullish, reason = trend_cache.is_bullish(symbol, timeframe)
                
                    status_emoji = "🟢" if is_bullish else "🔴"
                    msg += f"{status_emoji} {symbol} ({timeframe}): {reason} \n\n"

            return msg

        except Exception as e:
            # Delete processing message and show error
            return f"❌ Error fetching balances: {str(e)}"

    def get_balance_data(self):
        """Return balance text grouped by exchange account (no double-counting)."""
        try:
            from cache.balance_cache import get_balance_cache
            from cache.price_cache import get_price_cache
            from services.circuit_breaker import get_circuit_breaker
            from decimal import Decimal

            balance_cache = get_balance_cache()
            price_cache = get_price_cache()
            circuit_breaker = get_circuit_breaker()

            if not self.profile_manager:
                self.logger.warning("Profile manager not initialized")
                return "❌ Profile manager not available"

            profiles = self.profile_manager.get_all_profiles()
            balance_text = ""
            grand_total = Decimal("0")
            seen_accounts: set = set()

            for profile in profiles:
                account_id = getattr(profile, 'account_id', None)
                dedup_key = account_id if account_id else profile.name

                if dedup_key in seen_accounts:
                    continue
                seen_accounts.add(dedup_key)

                # Label: use account name if available, else profile display name
                label = profile.display_name
                if account_id:
                    # Try to get the account name from DB
                    try:
                        with get_db_session() as db:
                            from db.models import ExchangeAccount
                            acct = db.query(ExchangeAccount).filter(
                                ExchangeAccount.id == account_id
                            ).first()
                            if acct:
                                label = acct.name
                    except Exception:
                        pass

                account_key = f"account_{account_id}" if account_id else profile.name
                balances = balance_cache.get_account_balances(account_key)

                # Fall back to profile-keyed lookup if account key isn't populated yet
                if not balances:
                    balances = balance_cache.get_profile_balances(profile.name)

                if not balances:
                    balance_text += f"❌ No balance data for <b>{label}</b>\n"
                    continue

                # Compute total value
                total_value = Decimal("0")
                asset_lines = []
                DUST = Decimal("0.0001")

                for asset, info in balances.items():
                    avail  = Decimal(info.get("available", "0"))
                    locked = Decimal(info.get("locked",    "0"))
                    staked = Decimal(info.get("staked",    "0"))
                    qty = avail + locked + staked
                    if qty < DUST:
                        continue
                    price = Decimal("1") if asset == "USDC" else (price_cache.get_price(f"{asset}_USDC") or Decimal("0"))
                    val = round(qty * price, 2)
                    if val < Decimal("0.01"):
                        continue
                    total_value += val
                    asset_lines.append(f" - {asset}: {qty} → ${val}")

                limit_summary = circuit_breaker.get_daily_summary(profile.name)
                if limit_summary:
                    status = f"⛔ {limit_summary['hours_remaining']}hrs left" if limit_summary.get('circuit_breaker_active') else "✅"
                    header = f"\n💰 <b>{label}\nTotal: ${round(total_value, 2)}</b> ({limit_summary['daily_pnl_pct']}) {status}\n"
                else:
                    header = f"\n💰 <b>{label}\nTotal: ${round(total_value, 2)}</b>\n"

                balance_text += header + "\n".join(asset_lines) + "\n"
                grand_total += total_value

            if len(seen_accounts) > 1:
                balance_text += f"\n<b>━━━━━━━━━━━━━━━━━━━━\nAll Accounts: ${round(grand_total, 2)}</b>\n"

        except Exception as e:
            balance_text = f"❌ Error fetching balances: {str(e)}"

        return balance_text or "❌ No balance data available"

    def get_position_data(self):
        """Fetch position data from the exchange, showing only profiles with open positions."""
        profiles = self.profile_manager.get_all_profiles()
        msg = ""
        total_positions = 0
        profiles_with_positions = 0
        try:
            for profile in profiles:
                with get_db_session() as db:
                    open_positions = get_open_positions(db, profile.name)
                if open_positions is None or len(open_positions) == 0:
                    continue

                profiles_with_positions += 1
                total_positions += len(open_positions)
                msg += f"<b>[{profile.display_name}]</b>\n"

                for position in open_positions:
                    symbol = position.symbol
                    price_cache = get_price_cache()    # Get price cache instance
                    price = float(price_cache.get_price(symbol))
                    entry_price = float(position.entry_price)
                    is_short = getattr(position, 'direction', 'LONG').upper() == 'SHORT'
                    if is_short:
                        profit_pct = ((entry_price - price) / entry_price) * 100
                    else:
                        profit_pct = ((price - entry_price) / entry_price) * 100
                    emoji = "🟢" if profit_pct >= 0 else "🔴"
                    trail = "*" if position.trailing_stop_armed else ""
                    msg += (
                        f"{emoji} {symbol}: ${entry_price:.4f}->${price:.4f}{trail} "
                        f"({profit_pct:+.2f}%)\n"
                    )

                msg += "\n"

            if total_positions == 0:
                return "✅ No open positions across any profile"

            header = f"📊 <b>{total_positions} open position(s) across {profiles_with_positions} profile(s)</b>\n\n"
            return header + msg
        except Exception as e:
            self.logger.error(f"Error in get_position_data: {e}")
            return "Error in get_position_data"
# Global instance
_telegram: Optional[TelegramService] = None


def get_telegram() -> Optional[TelegramService]:
    """Get the global Telegram instance"""
    return _telegram


def set_telegram(instance: TelegramService):
    """Set the global Telegram instance"""
    global _telegram
    _telegram = instance