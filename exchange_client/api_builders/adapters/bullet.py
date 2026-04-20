"""BulletAdapter — ExchangeAdapter implementation for Bullet Exchange.

Bullet is a perpetuals DEX built on a Solana L2.
Key differences from Backpack:
  - Symbols:    "SOL-USD" not "SOL_USDC"
  - Auth reads: wallet address passed as ?address= query param, no headers
  - Auth writes: Borsh-serialised Ed25519-signed tx posted to /tx/submit
  - No klines:  Bullet has no candle endpoint — ATR falls back to CoinGecko
  - Positions:  tracked natively on-chain; read from /fapi/v3/account
  - No dust conversion endpoint

Credentials stored in exchange_accounts:
  api_key → wallet address (bech32, e.g. "bullet1abc...")
  secret  → Ed25519 private key (base64-encoded 32-byte seed)
"""
from typing import Optional, List, Dict, Any

from api_builders.adapters.base import ExchangeAdapter
from utils.endpoints import BulletEndpoints
from utils.logging import log_manager
from services.client import api_request
from utils.constants import HttpMethod

# Mapping: internal base symbol → Bullet perpetual symbol
# Add more as Bullet lists new markets.
SYMBOL_MAP: Dict[str, str] = {
    "SOL":  "SOL-USD",
    "BTC":  "BTC-USD",
    "ETH":  "ETH-USD",
    "PAXG": "PAXG-USD",
    "HYPE": "HYPE-USD",
    "TAO":  "TAO-USD",
    "XRP":  "XRP-USD",
    "ZEC":  "ZEC-USD",
}

# Reverse map for response parsing
REVERSE_SYMBOL_MAP: Dict[str, str] = {v: k for k, v in SYMBOL_MAP.items()}

# CoinGecko coin IDs for ATR fallback (no klines on Bullet)
COINGECKO_IDS: Dict[str, str] = {
    "SOL": "solana",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "PAXG": "pax-gold",
    "XRP": "ripple",
    "ZEC": "zcash",
}


def _to_bullet_symbol(symbol: str) -> str:
    """Convert internal symbol (e.g. "SOL") or Backpack pair (e.g. "SOL_USDC") to Bullet format."""
    # Already in Bullet format
    if "-" in symbol:
        return symbol
    # Backpack format SOL_USDC → extract base
    base = symbol.split("_")[0] if "_" in symbol else symbol
    return SYMBOL_MAP.get(base.upper(), f"{base.upper()}-USD")


class BulletAdapter(ExchangeAdapter):
    """ExchangeAdapter implementation for Bullet (perpetuals DEX)."""

    exchange_type = "bullet"

    def __init__(self, profile):
        """
        Args:
            profile: TradingProfile instance.
                     profile.wallet_address = main wallet address — used for all read operations
                                              (balance, open orders, order history, account)
                     profile.api_key        = delegate wallet address — used for signing write txs
                     profile.secret         = Ed25519 private key of the delegate (base64-encoded seed)
        """
        self.profile = profile
        # Reads use the main wallet. Fall back to api_key for backward compat.
        self.read_address = profile.wallet_address or profile.api_key
        # Writes are signed by the delegate keypair.
        self.delegate_address = profile.api_key
        self.logger = log_manager.get_logger("BulletAdapter")

    # ── Market data ───────────────────────────────────────────────────────────

    def get_ticker(self, symbol: str) -> Optional[float]:
        """Fetch current mark price from Bullet /fapi/v1/ticker/price."""
        bullet_symbol = _to_bullet_symbol(symbol)
        url = BulletEndpoints.ticker(bullet_symbol)
        try:
            data = api_request(url)
            if data and isinstance(data, list) and data:
                return float(data[0].get("price", 0) or 0)
            if data and isinstance(data, dict):
                return float(data.get("price", 0) or 0)
        except Exception as e:
            self.logger.error(f"[Bullet] get_ticker({symbol}) failed: {e}")
        return None

    def get_depth(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch order book from Bullet /fapi/v1/depth."""
        bullet_symbol = _to_bullet_symbol(symbol)
        url = BulletEndpoints.depth(bullet_symbol)
        try:
            return api_request(url)
        except Exception as e:
            self.logger.error(f"[Bullet] get_depth({symbol}) failed: {e}")
            return None

    def get_klines(self, symbol: str, interval: str, start_time: int, limit: int = 100) -> List[Dict]:
        """Bullet has no klines endpoint — falls back to CoinGecko OHLC.

        Returns candle dicts with open/high/low/close/volume keys.
        Volume is not available from CoinGecko OHLC so it is set to 0.
        Returns [] if the coin is not in the CoinGecko map.
        """
        base = symbol.split("_")[0].split("-")[0].upper()
        coin_id = COINGECKO_IDS.get(base)
        if not coin_id:
            self.logger.warning(
                f"[Bullet] No CoinGecko ID for {symbol} — cannot fetch klines fallback"
            )
            return []

        # days=1 gives hourly OHLC; days=7 gives daily OHLC — pick based on interval
        interval_lower = interval.lower()
        if "d" in interval_lower:
            days = 30
        elif "h" in interval_lower:
            days = 7
        else:
            days = 1

        url = BulletEndpoints.coingecko_ohlc(coin_id, days)
        try:
            data = api_request(url)
            if not data or not isinstance(data, list):
                return []
            # CoinGecko OHLC format: [timestamp_ms, open, high, low, close]
            candles = []
            for row in data[-limit:]:
                if len(row) >= 5:
                    candles.append({
                        "open":   str(row[1]),
                        "high":   str(row[2]),
                        "low":    str(row[3]),
                        "close":  str(row[4]),
                        "volume": "0",  # not available from CoinGecko OHLC endpoint
                    })
            return candles
        except Exception as e:
            self.logger.error(f"[Bullet] get_klines fallback failed for {symbol}: {e}")
            return []

    def get_markets(self) -> Optional[List[Dict]]:
        """Fetch all markets from Bullet /fapi/v1/exchangeInfo and normalise to Backpack-like format."""
        url = BulletEndpoints.exchange_info()
        try:
            data = api_request(url)
            if not data:
                return None
            symbols = data.get("symbols", [])
            # Normalise each market to a common dict shape used by market_info_cache
            result = []
            for s in symbols:
                result.append({
                    "symbol": s.get("symbol"),          # "SOL-USD"
                    "baseSymbol": s.get("baseAsset"),   # "SOL"
                    "quoteSymbol": "USD",
                    "filters": s.get("filters", []),
                    "orderTypes": s.get("orderTypes", []),
                    "status": s.get("status"),
                    "_raw": s,                          # keep original for adapter-specific use
                })
            return result
        except Exception as e:
            self.logger.error(f"[Bullet] get_markets() failed: {e}")
            return None

    def get_market_info(self, symbol: str) -> Optional[Dict]:
        """Return market info for a single symbol by fetching exchangeInfo and filtering."""
        bullet_symbol = _to_bullet_symbol(symbol)
        markets = self.get_markets()
        if not markets:
            return None
        for m in markets:
            if m.get("symbol") == bullet_symbol:
                return m
        self.logger.warning(f"[Bullet] Market info not found for {bullet_symbol}")
        return None

    # ── Account ───────────────────────────────────────────────────────────────

    def get_balances(self) -> Optional[Dict[str, Any]]:
        """Fetch account balances from Bullet /fapi/v3/balance.

        Bullet returns a list of asset balance objects.
        We normalise to {asset: {available, locked, total}} to match BalanceReader expectations.
        """
        url = BulletEndpoints.balance(self.read_address)
        try:
            data = api_request(url)
            if not data:
                return None
            # Bullet balance format (TBC — adapt once endpoint is confirmed working):
            # [{"asset": "USDC", "balance": "1000.00", "availableBalance": "900.00"}, ...]
            if isinstance(data, list):
                result = {}
                for item in data:
                    asset = item.get("asset", "")
                    total = str(item.get("balance", "0"))
                    available = str(item.get("availableBalance", total))
                    locked = str(float(total) - float(available))
                    result[asset] = {
                        "available": available,
                        "locked": locked,
                        "total": total,
                    }
                return result
            return data
        except Exception as e:
            self.logger.error(f"[Bullet] get_balances() failed: {e}")
            return None

    def get_account(self) -> Optional[Dict]:
        """Fetch full account state (positions, PnL) from /fapi/v3/account."""
        url = BulletEndpoints.account(self.read_address)
        try:
            return api_request(url)
        except Exception as e:
            self.logger.error(f"[Bullet] get_account() failed: {e}")
            return None

    # ── High-level trading (called by monitoring_service) ────────────────────

    def order_buy(self, symbol: str, quantity: str, price: str = "0",
                  source: str = "MANUAL", **kwargs) -> Optional[Any]:
        """Place a market-equivalent BUY on Bullet (IOC bid at +2% slippage).

        Attaches on-chain TP/SL from the profile if take_profit_pct / stop_loss_pct
        are configured, so the exchange enforces them without relying on monitoring.
        """
        bullet_symbol = _to_bullet_symbol(symbol)
        tick_size, step_size, _ = self._get_market_filters(bullet_symbol)
        entry_price = self._get_aggressive_price(symbol, side="BID")
        rounded_price = self._round_price(entry_price, tick_size)
        rounded_qty   = self._round_quantity(float(quantity), step_size)
        tpsl = self._build_tpsl(float(rounded_price), side="BID", tick_size=tick_size)

        from types import SimpleNamespace
        order_ns = SimpleNamespace(
            symbol=bullet_symbol,
            side="Bid",
            orderType="IOC",
            quantity=rounded_qty,
            price=rounded_price,
            reduce_only=False,
            pending_tpsl_pair=tpsl,
        )
        return self._submit_market_order(
            order_ns=order_ns,
            source=source,
            position_id=None,
            reason_summary=kwargs.get("reason_summary"),
            validation_summary=kwargs.get("validation_summary"),
        )

    def order_sell(self, symbol: str, quantity: str, price: str = "0",
                   source: str = "MANUAL", position_id: str = None,
                   reason_summary=None, validation_summary: str = None,
                   **kwargs) -> Optional[Any]:
        """Place a market-equivalent SELL/CLOSE on Bullet (IOC ask at -2% slippage)."""
        bullet_symbol = _to_bullet_symbol(symbol)
        tick_size, step_size, _ = self._get_market_filters(bullet_symbol)
        entry_price = self._get_aggressive_price(symbol, side="ASK")
        rounded_price = self._round_price(entry_price, tick_size)
        rounded_qty   = self._round_quantity(float(quantity), step_size)

        from types import SimpleNamespace
        order_ns = SimpleNamespace(
            symbol=bullet_symbol,
            side="Ask",
            orderType="IOC",
            quantity=rounded_qty,
            price=rounded_price,
            reduce_only=position_id is not None,
        )
        return self._submit_market_order(
            order_ns=order_ns,
            source=source,
            position_id=position_id,
            reason_summary=reason_summary,
            validation_summary=validation_summary,
        )

    def validate_balance_for_trade(self, sale_action: str, symbol: str) -> tuple:
        """Check account balance before placing an order on Bullet.

        Reads from the balance cache (populated by get_balances()).
        Bullet uses USDC as universal collateral — BUY checks USDC, SELL checks position.
        """
        from cache.balance_cache import get_balance_cache
        cache = get_balance_cache()
        try:
            if sale_action.upper() in ("BUY", "BID"):
                available = cache.get_available_balance(
                    profile_name=self.profile.name, asset="USDC"
                )
                if available is None or float(available) <= 0:
                    return False, "No USDC collateral available"
                return True, ""
            else:
                # For perps, selling means closing a long — always allowed if position exists
                return True, ""
        except Exception as e:
            return False, f"Balance check error: {e}"

    async def process_tradingview_alert(self, alert: Any, profile_name: str,
                                        source: str = "WEBHOOK",
                                        reason_summary=None) -> Optional[Any]:
        """Handle a TradingView webhook alert for a Bullet profile."""
        action = getattr(alert, "action", None) or (alert.get("action") if isinstance(alert, dict) else None)
        symbol = getattr(alert, "symbol", None) or (alert.get("symbol") if isinstance(alert, dict) else None)
        quantity = str(getattr(alert, "quantity", None) or (alert.get("quantity") if isinstance(alert, dict) else "0"))

        if not action or not symbol:
            self.logger.warning(f"[Bullet] process_tradingview_alert: missing action/symbol in alert")
            return None

        action_upper = action.upper()
        if action_upper in ("BUY", "LONG"):
            return self.order_buy(symbol=symbol, quantity=quantity, source=source, reason_summary=reason_summary)
        elif action_upper in ("SELL", "SHORT", "CLOSE"):
            return self.order_sell(symbol=symbol, quantity=quantity, source=source, reason_summary=reason_summary)
        else:
            self.logger.warning(f"[Bullet] process_tradingview_alert: unknown action {action!r}")
            return None

    def process_limit_order(self, order: Any, position_id: Any = None) -> Optional[Any]:
        """Check status of a pending limit order on Bullet.

        Bullet supports STOP and STOP_MARKET natively. Query /fapi/v1/openOrder
        to check if filled, then update the DB position accordingly.
        Full implementation pending.
        """
        bullet_symbol = _to_bullet_symbol(getattr(order, "symbol", ""))
        order_id = str(getattr(order, "exchange_order_id", "") or "")
        if not order_id:
            return None
        try:
            result = self.get_single_order(order_id=order_id, symbol=bullet_symbol)
            # If get_single_order returns None the order is no longer open (filled/cancelled)
            return result
        except Exception as e:
            self.logger.error(f"[Bullet] process_limit_order() failed: {e}")
            return None

    # ── Low-level trading ─────────────────────────────────────────────────────

    def execute_order(self, order: Any) -> Optional[Dict]:
        """Submit an order to Bullet via POST /tx/submit.

        Requires building and signing a Borsh-serialised transaction.
        See utils/auth.py::build_bullet_transaction() for implementation guide.
        """
        from utils.auth import build_bullet_transaction
        try:
            # Translate order fields to Bullet's NewOrderArgs structure
            call_data = self._build_place_order_call(order)
            tx_b64 = build_bullet_transaction(
                private_key_b64=self.profile.secret,
                call_data=call_data,
            )
            url = BulletEndpoints.submit_tx()
            response = api_request(
                url,
                body={"body": tx_b64},
                requestType=HttpMethod.POST,
            )
            return response
        except NotImplementedError:
            self.logger.error(
                "[Bullet] execute_order: transaction signing not yet implemented. "
                "See utils/auth.py::build_bullet_transaction() to complete."
            )
            return None
        except Exception as e:
            self.logger.error(f"[Bullet] execute_order() failed: {e}")
            return None

    def cancel_order(self, order_id: str, symbol: str) -> Optional[Dict]:
        """Cancel an order on Bullet via POST /tx/submit with a cancel instruction."""
        from utils.auth import build_bullet_transaction
        try:
            call_data = self._build_cancel_order_call(order_id, symbol)
            tx_b64 = build_bullet_transaction(
                private_key_b64=self.profile.secret,
                call_data=call_data,
            )
            url = BulletEndpoints.submit_tx()
            response = api_request(
                url,
                body={"body": tx_b64},
                requestType=HttpMethod.POST,
            )
            return response
        except NotImplementedError:
            self.logger.error(
                "[Bullet] cancel_order: transaction signing not yet implemented."
            )
            return None
        except Exception as e:
            self.logger.error(f"[Bullet] cancel_order({order_id}) failed: {e}")
            return None

    def get_open_orders(self, symbol: str) -> List[Dict]:
        """Fetch open orders from /fapi/v1/openOrders."""
        bullet_symbol = _to_bullet_symbol(symbol)
        url = BulletEndpoints.open_orders(bullet_symbol, self.read_address)
        try:
            data = api_request(url)
            if not data:
                return []
            return data if isinstance(data, list) else []
        except Exception as e:
            self.logger.error(f"[Bullet] get_open_orders({symbol}) failed: {e}")
            return []

    def get_single_order(self, order_id: str, symbol: str) -> Optional[Dict]:
        """Fetch a single open order from /fapi/v1/openOrder."""
        bullet_symbol = _to_bullet_symbol(symbol)
        url = BulletEndpoints.single_order(bullet_symbol, self.read_address, order_id=order_id)
        try:
            return api_request(url)
        except Exception as e:
            self.logger.error(f"[Bullet] get_single_order({order_id}) failed: {e}")
            return None

    def get_order_history(self, symbol: str = None, order_id: str = None) -> List[Dict]:
        """Fetch order history from /fapi/v1/allOrders."""
        bullet_symbol = _to_bullet_symbol(symbol) if symbol else None
        url = BulletEndpoints.order_history(self.read_address, symbol=bullet_symbol, order_id=order_id)
        try:
            data = api_request(url)
            if not data:
                return []
            # Bullet returns {"data": [...], "nextCursor": ...}
            if isinstance(data, dict):
                return data.get("data", [])
            return data if isinstance(data, list) else []
        except Exception as e:
            self.logger.error(f"[Bullet] get_order_history() failed: {e}")
            return []

    def get_user_trades(self, symbol: str, limit: int = 10) -> List[Dict]:
        """Fetch recent fills from /fapi/v1/userTrades for a symbol.

        Returns trades newest-first if the API supports it, otherwise the caller
        should take the last item from the list. Each fill contains at minimum:
          price, qty (or quantity), side, time (or timestamp).
        """
        bullet_symbol = _to_bullet_symbol(symbol)
        url = BulletEndpoints.user_trades(self.read_address, symbol=bullet_symbol)
        try:
            data = api_request(url)
            if not data:
                return []
            trades = data if isinstance(data, list) else data.get("data", [])
            return trades[:limit]
        except Exception as e:
            self.logger.error(f"[Bullet] get_user_trades({symbol}) failed: {e}")
            return []

    def get_latest_close_price(self, symbol: str, opened_at=None) -> Optional[float]:
        """Return the fill price of the most recent closing trade for symbol.

        Looks through userTrades for the most recent ASK (sell/close) fill placed
        after `opened_at` (a datetime or epoch-ms int). Returns None if not found.
        """
        trades = self.get_user_trades(symbol, limit=20)
        if not trades:
            return None

        import time as _time
        opened_ms = None
        if opened_at is not None:
            if hasattr(opened_at, "timestamp"):
                opened_ms = int(opened_at.timestamp() * 1000)
            else:
                opened_ms = int(opened_at)

        # Bullet trade fields: side "Ask"/"Bid", price, qty/quantity, time/timestamp
        for trade in trades:
            side = str(trade.get("side", "")).lower()
            if side not in ("ask", "sell"):
                continue
            trade_time = trade.get("time") or trade.get("timestamp") or trade.get("tradeTime") or 0
            if opened_ms and int(trade_time) < opened_ms:
                continue
            price = trade.get("price") or trade.get("avgPrice")
            if price:
                return float(price)
        return None

    # ── Optional capabilities ─────────────────────────────────────────────────

    def get_funding_rate(self, symbol: str = None) -> Optional[List[Dict]]:
        """Fetch funding rates from /fapi/v1/fundingRate."""
        bullet_symbol = _to_bullet_symbol(symbol) if symbol else None
        url = BulletEndpoints.funding_rate(bullet_symbol)
        try:
            data = api_request(url)
            if not data:
                return None
            return data if isinstance(data, list) else [data]
        except Exception as e:
            self.logger.error(f"[Bullet] get_funding_rate() failed: {e}")
            return None

    def supports_klines(self) -> bool:
        """Bullet has no native klines — falls back to CoinGecko."""
        return False  # native klines don't exist; fallback is attempted but not guaranteed

    def supports_dust_conversion(self) -> bool:
        return False

    # ── Internal order execution helpers ─────────────────────────────────────

    def _submit_market_order(
        self,
        order_ns: Any,
        source: str,
        position_id: Optional[str],
        reason_summary,
        validation_summary: Optional[str],
    ) -> Optional[Any]:
        """Submit a signed Bullet order tx, persist to DB, open/close position.

        Mirrors the logic in trading_builder.ProcessMarketOrder so that Bullet
        trades are recorded identically to Backpack trades.
        """
        from utils.auth import build_bullet_transaction
        from db.session import SessionLocal
        from db.crud import (
            save_trade, open_position, close_position,
            add_validation_result,
        )
        from utils.position_calculator import PositionCalculator

        # 1. Build and sign the transaction
        try:
            call_data = self._build_place_order_call(order_ns)
            tx_b64 = build_bullet_transaction(
                private_key_b64=self.profile.secret,
                call_data=call_data,
            )
        except Exception as e:
            self.logger.error(f"[Bullet] tx build failed for {order_ns.symbol}: {e}")
            return None

        # 2. Submit to Bullet
        position_already_flat = False
        try:
            url = BulletEndpoints.submit_tx()
            raw = api_request(url, body={"body": tx_b64}, requestType=HttpMethod.POST)
        except Exception as e:
            err_str = str(e)
            if "size_must_be_positive" in err_str or "size must be greater than zero" in err_str.lower():
                # Position is already flat on exchange (closed by on-chain TP/SL or externally).
                # Try to get the actual fill price from userTrades; fall back to price cache.
                self.logger.warning(
                    f"[Bullet] {order_ns.symbol} already flat on exchange — "
                    "looking up actual fill price to record P&L"
                )
                position_already_flat = True
                actual_price = self.get_latest_close_price(order_ns.symbol)
                if actual_price:
                    self.logger.info(
                        f"[Bullet] Found actual close fill for {order_ns.symbol} @ {actual_price}"
                    )
                    order_ns.price = str(actual_price)
                raw = None
            else:
                self.logger.error(f"[Bullet] /tx/submit failed for {order_ns.symbol}: {e}")
                return None

        # 3. Parse the exchange response into a common OrderResponse
        order_response = self._parse_order_response(raw, order_ns)
        if order_response is None:
            if position_already_flat:
                self.logger.error(
                    f"[Bullet] Could not synthesise close response for {order_ns.symbol} — skipping P&L record"
                )
            else:
                self.logger.error(
                    f"[Bullet] Could not parse /tx/submit response for {order_ns.symbol}: {raw}"
                )
            return None

        # 4. Persist to DB (same path as ProcessMarketOrder)
        db = None
        try:
            db = SessionLocal()
            side_upper = order_response.side.upper()
            is_opening = position_id is None
            is_long_entry = side_upper == "BID" and is_opening
            is_short_entry = side_upper == "ASK" and is_opening
            direction = "LONG" if side_upper == "BID" else "SHORT"

            saved_trade = save_trade(
                db, order_response, self.profile.name, source,
                reason_summary=reason_summary,
                direction=direction if is_opening else None,
            )
            self.logger.info(f"[Bullet] Trade saved: ID {saved_trade.id}")

            if validation_summary:
                add_validation_result(db, saved_trade, validation_summary=validation_summary)

            if is_long_entry or is_short_entry:
                tp_price, sl_price, trailing_sl_price = PositionCalculator.calculate_position_prices(
                    entry_price=saved_trade.price,
                    side=saved_trade.side,
                    profile=self.profile,
                )
                position = open_position(
                    db=db,
                    trade=saved_trade,
                    tp_price=tp_price,
                    sl_price=sl_price,
                    trailing_sl_price=trailing_sl_price,
                    highest_price=saved_trade.price,
                    lowest_price=saved_trade.price,
                    direction=direction,
                )
                self.logger.info(
                    f"[Bullet] Position opened: ID {position.id}, "
                    f"TP: {tp_price}, SL: {sl_price}"
                )
                # Note: Bullet TP/SL managed by monitoring loop (no resting limit order placed)

            elif position_id is not None:
                # Closing a position
                from db.crud import close_positions_fifo
                closed = close_positions_fifo(
                    db=db,
                    profile_name=self.profile.name,
                    symbol=order_ns.symbol,
                    closed_trade=saved_trade,
                )
                if closed:
                    self.logger.info(
                        f"[Bullet] Position closed: {[p.id for p in closed]}"
                    )

        except Exception as e:
            self.logger.error(f"[Bullet] DB persistence failed: {e}", exc_info=True)
        finally:
            if db:
                db.close()

        return order_response

    def _parse_order_response(self, raw: Any, order_ns: Any) -> Optional[Any]:
        """Parse a Bullet /tx/submit response into an OrderResponse.

        Handles three response shapes:
          1. Bullet native: {id, events:[...], receipt:{result:'successful'}, status:'submitted'}
          2. Binance FAPI-style: {orderId, executedQty, ...}
          3. Synthetic fallback using price cache
        """
        from models.trade import OrderResponse
        import time

        # --- Case 1: Bullet native tx response with events array ---
        if isinstance(raw, dict) and "events" in raw and isinstance(raw.get("events"), list):
            receipt = raw.get("receipt", {})
            if receipt.get("result") != "successful":
                self.logger.error(
                    f"[Bullet] tx result was not successful: {receipt.get('result')}"
                )
                return None
            tx_id = str(raw.get("id", "bullet-unknown"))
            # Find our Trade event (the taker side — is_maker=False)
            exec_price = None
            exec_qty = None
            order_id = str(order_ns.__dict__.get("order_id", tx_id))
            for event in raw["events"]:
                val = event.get("value", {})
                trade = val.get("trade") or val.get("place_order")
                if not trade:
                    continue
                if event.get("key") == "Exchange/Trade" and not trade.get("is_maker", True):
                    exec_price = str(trade.get("price", order_ns.price))
                    exec_qty = str(trade.get("size", order_ns.quantity))
                    order_id = str(trade.get("order_id", tx_id))
                    break
                if event.get("key") == "Exchange/PlaceOrder" and exec_price is None:
                    # Use PlaceOrder as fallback if no Trade event found
                    exec_price = str(trade.get("price", order_ns.price))
                    exec_qty = str(trade.get("size", order_ns.quantity))
                    order_id = str(trade.get("order_id", tx_id))

            if exec_price is None:
                exec_price = str(order_ns.price)
                exec_qty = str(order_ns.quantity)

            executed_quote = str(float(exec_qty) * float(exec_price))
            self.logger.info(
                f"[Bullet] tx {tx_id} filled: qty={exec_qty} @ {exec_price}"
            )
            return OrderResponse(**{
                "id": order_id,
                "orderType": "Market",
                "symbol": order_ns.symbol,
                "side": order_ns.side,
                "status": "Filled",
                "executedQuantity": exec_qty,
                "executedQuoteQuantity": executed_quote,
                "price": exec_price,
                "createdAt": int(time.time() * 1000),
            })

        # --- Case 2: Binance FAPI-style fill (orderId + executedQty present) ---
        if isinstance(raw, dict) and ("orderId" in raw or "id" in raw):
            try:
                order_id = str(raw.get("orderId") or raw.get("id", "0"))
                executed_qty = str(raw.get("executedQty") or raw.get("executedQuantity") or order_ns.quantity)
                exec_price = str(raw.get("avgPrice") or raw.get("price") or order_ns.price)
                executed_quote = str(float(executed_qty) * float(exec_price))
                return OrderResponse(**{
                    "id": order_id,
                    "orderType": "Market",
                    "symbol": order_ns.symbol,
                    "side": order_ns.side,
                    "status": "Filled",
                    "executedQuantity": executed_qty,
                    "executedQuoteQuantity": executed_quote,
                    "price": exec_price,
                    "createdAt": raw.get("time", int(time.time() * 1000)),
                })
            except Exception as e:
                self.logger.warning(f"[Bullet] FAPI parse failed, trying synthetic: {e}")

        # --- Case 3: Synthetic fallback using price cache ---
        try:
            from cache.price_cache import get_price_cache
            tx_id = (
                raw.get("hash") or raw.get("txHash") or raw.get("txId") or "bullet-unknown"
                if isinstance(raw, dict) else "bullet-unknown"
            )
            price_cache = get_price_cache()
            base = order_ns.symbol.split("-")[0]
            current_price = (
                price_cache.get_price(order_ns.symbol)
                or price_cache.get_price(f"{base}_USDC")
                or price_cache.get_price(base)
                or float(order_ns.price)
            )
            executed_qty = str(order_ns.quantity)
            executed_quote = str(float(executed_qty) * float(current_price))
            self.logger.info(
                f"[Bullet] Synthetic OrderResponse: tx={tx_id}, "
                f"qty={executed_qty}, price={current_price}"
            )
            return OrderResponse(**{
                "id": str(tx_id),
                "orderType": "Market",
                "symbol": order_ns.symbol,
                "side": order_ns.side,
                "status": "Filled",
                "executedQuantity": executed_qty,
                "executedQuoteQuantity": executed_quote,
                "price": str(current_price),
                "createdAt": int(time.time() * 1000),
            })
        except Exception as e:
            self.logger.error(f"[Bullet] Synthetic OrderResponse failed: {e}")
            return None

    def _build_tpsl(self, entry_price: float, side: str, tick_size=None) -> Optional[Dict]:
        """Build pending_tpsl_pair dict from profile TP/SL percentages.

        Returns None if neither take_profit_pct nor stop_loss_pct is set.
        Uses Mark price as the trigger condition (same as Bullet UI default).
        TP/SL orders are IOC market-like so they fill immediately on trigger.
        """
        if side == "BID":  # long
            tp_mult = 1 + float(self.profile.take_profit_pct or 0) / 100
            sl_mult = 1 - float(self.profile.stop_loss_pct or 0) / 100
        else:  # short / ask
            tp_mult = 1 - float(self.profile.take_profit_pct or 0) / 100
            sl_mult = 1 + float(self.profile.stop_loss_pct or 0) / 100

        tp_leg = None
        sl_leg = None

        # TP/SL prices must also be multiples of tick size
        if tick_size is None:
            tick_size = 0.01  # safe default (SOL tick); caller should pass the real value

        def _round_to_tick(price: float) -> float:
            from decimal import Decimal
            t = Decimal(str(tick_size))
            p = Decimal(str(price))
            if t <= 0:
                return price
            return float((p // t) * t)

        if self.profile.take_profit_pct:
            tp_price = _round_to_tick(entry_price * tp_mult)
            tp_leg = {
                "trigger_price": tp_price,
                "order_price": tp_price,
                "price_condition": "Mark",
                "order_type": "IOC",
            }

        if self.profile.stop_loss_pct:
            sl_price = _round_to_tick(entry_price * sl_mult)
            sl_leg = {
                "trigger_price": sl_price,
                "order_price": sl_price,
                "price_condition": "Mark",
                "order_type": "IOC",
            }

        if not tp_leg and not sl_leg:
            return None

        return {
            "tp": tp_leg,
            "sl": sl_leg,
            "dynamic_size": False,
        }

    def _get_aggressive_price(self, symbol: str, side: str) -> float:
        """Return a price with 0.5% slippage for IOC market-equivalent orders.

        BID (buy):  price = current * 1.005  (ensures fill at market or better)
        ASK (sell): price = current * 0.995  (ensures fill at market or better)
        """
        from cache.price_cache import get_price_cache
        cache = get_price_cache()
        base = symbol.split("_")[0].split("-")[0]
        # Price cache keys are Backpack-format (e.g. "ETH_USDC"); try full symbol first,
        # then fall back to bare base in case a non-Backpack key was stored.
        current = cache.get_price(symbol) or cache.get_price(f"{base}_USDC") or cache.get_price(base)
        if not current:
            self.logger.warning(
                f"[Bullet] No cached price for {symbol} ({base}), using 0 — order may fail"
            )
            return 0.0
        return float(current) * (1.005 if side == "BID" else 0.995)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_place_order_call(self, order: Any) -> Dict:
        """Build the call_data dict for build_bullet_transaction (place_orders action).

        market_id is looked up from Bullet exchangeInfo by symbol.
        """
        bullet_symbol = _to_bullet_symbol(getattr(order, "symbol", ""))
        market_id = self._get_market_id(bullet_symbol)

        side = getattr(order, "side", "Bid")
        # Normalise: Backpack uses "Bid"/"Ask", Bullet Borsh uses BID/ASK — handled inside auth.py
        order_type = getattr(order, "orderType", "LIMIT")

        return {
            "action": "place_orders",
            "market_id": market_id,
            "orders": [{
                "price": str(getattr(order, "price", "0")),
                "size": str(getattr(order, "quantity", "0")),
                "side": side,
                "order_type": order_type,
                "reduce_only": getattr(order, "reduce_only", False),
                "client_order_id": None,
                "pending_tpsl_pair": getattr(order, "pending_tpsl_pair", None),
            }],
            "replace": False,
            "sub_account_index": 0,
        }

    def _build_cancel_order_call(self, order_id: str, symbol: str) -> Dict:
        """Build the call_data dict for build_bullet_transaction (cancel_orders action).

        order_id must be the numeric u64 order ID from /fapi/v1/openOrders — NOT the
        tx hash (0x...) returned by /tx/submit.  Use get_open_orders() to find the
        numeric orderId for a position before cancelling.
        """
        bullet_symbol = _to_bullet_symbol(symbol)
        market_id = self._get_market_id(bullet_symbol)

        # Parse order_id — Bullet order IDs are numeric u64, not hex tx hashes
        try:
            numeric_id = int(order_id, 16) if str(order_id).startswith("0x") else int(order_id)
        except (ValueError, TypeError):
            raise ValueError(
                f"[Bullet] cancel_order: order_id must be a numeric u64 (got {order_id!r}). "
                "Use get_open_orders() to find the numeric orderId — the 0x tx hash "
                "returned by /tx/submit is NOT the order ID."
            )

        return {
            "action": "cancel_orders",
            "market_id": market_id,
            "orders": [{
                "order_id": numeric_id,
                "client_order_id": None,
            }],
        }

    def _get_market_id(self, bullet_symbol: str) -> int:
        """Return the u32 market index for bullet_symbol from Bullet exchangeInfo.

        Bullet market_id is the position (0-indexed) of the symbol in the
        exchangeInfo symbols array.  Results are cached per-adapter instance.
        """
        self._ensure_exchange_info_cache()
        market_id = self._market_id_cache.get(bullet_symbol, 0)
        if bullet_symbol not in self._market_id_cache:
            self.logger.warning(
                f"[Bullet] market_id not found for {bullet_symbol}, defaulting to 0"
            )
        return market_id

    def _get_market_filters(self, bullet_symbol: str):
        """Return (tick_size, step_size, min_qty) as Decimal for the given symbol."""
        from decimal import Decimal
        self._ensure_exchange_info_cache()
        return self._market_filters_cache.get(
            bullet_symbol,
            (Decimal("0.01"), Decimal("0.01"), Decimal("0.01")),  # safe defaults
        )

    def _ensure_exchange_info_cache(self):
        """Populate market_id and filter caches from exchangeInfo (once per adapter instance)."""
        if hasattr(self, "_market_id_cache"):
            return
        from decimal import Decimal
        self._market_id_cache: Dict[str, int] = {}
        self._market_filters_cache: Dict[str, tuple] = {}
        url = BulletEndpoints.exchange_info()
        try:
            data = api_request(url)
            if not data:
                return
            for s in data.get("symbols", []):
                sym = s.get("symbol", "")
                # marketId is provided directly — use it (u16 per schema)
                self._market_id_cache[sym] = int(s.get("marketId", 0))

                # Parse Binance-style filter array
                tick_size = Decimal("0.01")
                step_size = Decimal("0.01")
                min_qty   = Decimal("0.01")
                for f in s.get("filters", []):
                    ft = f.get("filterType", "")
                    if ft == "PRICE_FILTER" and f.get("tickSize"):
                        tick_size = Decimal(str(f["tickSize"]))
                    elif ft == "LOT_SIZE":
                        if f.get("stepSize"):
                            step_size = Decimal(str(f["stepSize"]))
                        if f.get("minQty"):
                            min_qty = Decimal(str(f["minQty"]))
                self._market_filters_cache[sym] = (tick_size, step_size, min_qty)
        except Exception as e:
            self.logger.warning(f"[Bullet] _ensure_exchange_info_cache failed: {e}")

    def _round_price(self, price: float, tick_size) -> str:
        """Round price down to nearest tick size."""
        from decimal import Decimal
        p = Decimal(str(price))
        t = Decimal(str(tick_size))
        if t <= 0:
            return str(p)
        rounded = (p // t) * t
        # Format with same decimal places as tick_size
        places = max(0, -t.as_tuple().exponent)
        return f"{rounded:.{places}f}"

    def _round_quantity(self, qty: float, step_size) -> str:
        """Round quantity down to nearest step size."""
        from decimal import Decimal
        q = Decimal(str(qty))
        s = Decimal(str(step_size))
        if s <= 0:
            return str(q)
        rounded = (q // s) * s
        places = max(0, -s.as_tuple().exponent)
        return f"{rounded:.{places}f}"

    def _get_next_nonce(self) -> int:
        """Return a monotonically increasing nonce based on current timestamp (ms)."""
        import time
        return int(time.time() * 1000)
