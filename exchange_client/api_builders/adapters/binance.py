"""BinanceAdapter — ExchangeAdapter implementation for Binance Spot.

Key differences from Backpack:
  - Symbols:    "SOLUSDT", "BTCUSDT" (no separator; USDC quote → USDT)
  - Auth reads: public endpoints need no signature; account/order endpoints
                require HMAC-SHA256 timestamp+signature in query string +
                X-MBX-APIKEY header
  - Auth writes: same HMAC-SHA256 scheme — params sent as query string on POST
  - klines:     uses Binance /api/v3/klines — fully supported
  - No dust conversion endpoint (Binance uses /sapi/v1/asset/dust but scoped
    to individual assets; left unimplemented for now)

Credentials stored in exchange_accounts:
  api_key → Binance API key
  secret  → Binance secret key (for HMAC-SHA256 signing)
  wallet_address → not used
"""
from typing import Optional, List, Dict, Any

from api_builders.adapters.base import ExchangeAdapter
from utils.endpoints import BinanceEndpoints
from utils.logging import log_manager
from services.client import api_request
from utils.constants import HttpMethod

# Canonical quote assets on Binance for each internal quote currency.
# Internal format is BASE_QUOTE (e.g. SOL_USDC).  Binance USDT pairs are the
# most liquid so we default there; USDC pairs exist too but have lower volume.
_QUOTE_MAP = {
    "USDC": "USDT",
    "USDT": "USDT",
    "USD":  "USDT",
    "BTC":  "BTC",
    "ETH":  "ETH",
    "BNB":  "BNB",
}

# Binance interval aliases match the system's native format already (1m, 5m, 15m, 1h, 4h, 1d …)
# so no mapping is needed for intervals.


def _to_binance_symbol(symbol: str) -> str:
    """Convert canonical symbol (e.g. "SOL_USDC", "SOL") to Binance format ("SOLUSDT").

    Rules:
      "SOL_USDC" → "SOLUSDT"   (strip underscore, map USDC→USDT)
      "BTC_USDT" → "BTCUSDT"
      "SOL"      → "SOLUSDT"   (bare base asset; append default quote USDT)
      "SOLUSDT"  → "SOLUSDT"   (already Binance format — returned unchanged)
    """
    if "_" in symbol:
        base, quote = symbol.split("_", 1)
        mapped_quote = _QUOTE_MAP.get(quote.upper(), quote.upper())
        return f"{base.upper()}{mapped_quote}"
    # Bare base asset or already concatenated
    # If it already looks like a Binance symbol (e.g. SOLUSDT) don't append again
    upper = symbol.upper()
    for suffix in ("USDT", "USDC", "BTC", "ETH", "BNB"):
        if upper.endswith(suffix) and len(upper) > len(suffix):
            return upper
    # Bare base — append default quote
    return f"{upper}USDT"


def _from_binance_symbol(binance_symbol: str) -> str:
    """Convert "SOLUSDT" back to canonical "SOL_USDC" (best-effort, USDT→USDC)."""
    for suffix in ("USDT", "USDC", "BTC", "ETH", "BNB"):
        if binance_symbol.upper().endswith(suffix):
            base = binance_symbol[: -len(suffix)]
            # Map USDT back to USDC to match the rest of the system
            canon_quote = "USDC" if suffix in ("USDT", "USDC") else suffix
            return f"{base}_{canon_quote}"
    return binance_symbol


def _avg_fill_price(fills: List[Dict]) -> Optional[str]:
    """Compute the weighted average fill price from a Binance fills list."""
    if not fills:
        return None
    total_qty = 0.0
    total_notional = 0.0
    for f in fills:
        qty = float(f.get("qty", 0))
        price = float(f.get("price", 0))
        total_qty += qty
        total_notional += qty * price
    if total_qty <= 0:
        return None
    return str(total_notional / total_qty)


class BinanceAdapter(ExchangeAdapter):
    """ExchangeAdapter implementation for Binance Spot exchange."""

    exchange_type = "binance"

    def __init__(self, profile):
        """
        Args:
            profile: TradingProfile instance.
                     profile.api_key → Binance API key (X-MBX-APIKEY header)
                     profile.secret  → Binance secret key (HMAC-SHA256 signing)
        """
        self.profile = profile
        self.logger = log_manager.get_logger("BinanceAdapter")
        # Per-instance cache for exchange info (filters, step sizes)
        self._exchange_info_cache: Optional[Dict[str, Dict]] = None

    # ── Symbol conversion ─────────────────────────────────────────────────────

    def to_exchange_symbol(self, symbol: str) -> str:
        return _to_binance_symbol(symbol)

    # ── Auth helpers ──────────────────────────────────────────────────────────

    def _signed_url(self, base_url: str, params: Dict[str, Any] = None) -> tuple:
        """Return (signed_url, headers) for an authenticated Binance request."""
        from utils.auth import build_binance_signed_request
        return build_binance_signed_request(
            base_url=base_url,
            params=params or {},
            api_key=self.profile.api_key,
            secret=self.profile.secret,
        )

    def _api_key_header(self) -> Dict[str, str]:
        return {"X-MBX-APIKEY": self.profile.api_key}

    # ── Market data ───────────────────────────────────────────────────────────

    def get_ticker(self, symbol: str) -> Optional[float]:
        binance_symbol = _to_binance_symbol(symbol)
        url = BinanceEndpoints.ticker(binance_symbol)
        try:
            data = api_request(url)
            if data:
                return float(data.get("price", 0) or 0)
        except Exception as e:
            self.logger.error(f"[Binance] get_ticker({symbol}) failed: {e}")
        return None

    def get_depth(self, symbol: str) -> Optional[Dict[str, Any]]:
        binance_symbol = _to_binance_symbol(symbol)
        url = BinanceEndpoints.depth(binance_symbol)
        try:
            return api_request(url)
        except Exception as e:
            self.logger.error(f"[Binance] get_depth({symbol}) failed: {e}")
            return None

    def get_klines(self, symbol: str, interval: str, start_time: int, limit: int = 100) -> List[Dict]:
        """Fetch OHLCV candles from Binance.

        start_time is expected in seconds (as used throughout the system).
        Binance klines use milliseconds — converted internally.
        Returns list of dicts with open/high/low/close/volume keys.
        """
        binance_symbol = _to_binance_symbol(symbol)
        start_time_ms = start_time * 1000 if start_time else None
        url = BinanceEndpoints.klines(binance_symbol, interval, start_time_ms, limit)
        try:
            data = api_request(url, timeout=10)
            if not data or not isinstance(data, list):
                return []
            # Binance klines: [open_time, open, high, low, close, volume, ...]
            candles = []
            for row in data:
                if len(row) >= 6:
                    candles.append({
                        "open":   str(row[1]),
                        "high":   str(row[2]),
                        "low":    str(row[3]),
                        "close":  str(row[4]),
                        "volume": str(row[5]),
                    })
            return candles
        except Exception as e:
            self.logger.error(f"[Binance] get_klines({symbol}) failed: {e}")
            return []

    def get_markets(self) -> Optional[List[Dict]]:
        """Fetch all markets from Binance /api/v3/exchangeInfo."""
        url = BinanceEndpoints.exchange_info()
        try:
            data = api_request(url, timeout=15)
            if not data:
                return None
            result = []
            for s in data.get("symbols", []):
                base = s.get("baseAsset", "")
                quote = s.get("quoteAsset", "")
                canonical_quote = "USDC" if quote in ("USDT", "USDC") else quote
                result.append({
                    "symbol":      s.get("symbol"),
                    "baseSymbol":  base,
                    "quoteSymbol": canonical_quote,
                    "filters":     s.get("filters", []),
                    "orderTypes":  s.get("orderTypes", []),
                    "status":      s.get("status"),
                    "_raw":        s,
                })
            return result
        except Exception as e:
            self.logger.error(f"[Binance] get_markets() failed: {e}")
            return None

    def get_market_info(self, symbol: str) -> Optional[Dict]:
        binance_symbol = _to_binance_symbol(symbol)
        self._ensure_exchange_info_cache()
        return self._exchange_info_cache.get(binance_symbol)

    # ── Account ───────────────────────────────────────────────────────────────

    def get_balances(self) -> Optional[Dict[str, Any]]:
        """Fetch Binance spot account balances.

        Returns {asset: {available, locked, total}} matching the BalanceReader shape.
        Only assets with a non-zero balance are included.
        """
        url, headers = self._signed_url(BinanceEndpoints.account())
        try:
            data = api_request(url, headers=headers)
            if not data:
                return None
            result = {}
            for b in data.get("balances", []):
                asset = b.get("asset", "")
                free = str(b.get("free", "0"))
                locked = str(b.get("locked", "0"))
                total = str(float(free) + float(locked))
                if float(total) > 0:
                    result[asset] = {
                        "available": free,
                        "locked":    locked,
                        "total":     total,
                    }
            return result
        except Exception as e:
            self.logger.error(f"[Binance] get_balances() failed: {e}")
            return None

    # ── High-level trading (called by monitoring_service) ────────────────────

    def order_buy(self, symbol: str, quantity: str, price: str = "0",
                  source: str = "MANUAL", **kwargs) -> Optional[Any]:
        """Execute a market BUY on Binance and persist to DB."""
        position_id = kwargs.get("position_id")
        binance_symbol = _to_binance_symbol(symbol)
        rounded_qty = self._round_quantity(binance_symbol, float(quantity))
        return self._submit_market_order(
            binance_symbol=binance_symbol,
            original_symbol=symbol,
            side="BUY",
            quantity=rounded_qty,
            source=source,
            position_id=position_id,
            signal_snapshot=kwargs.get("signal_snapshot"),
        )

    def order_sell(self, symbol: str, quantity: str, price: str = "0",
                   source: str = "MANUAL", position_id: str = None,
                   **kwargs) -> Optional[Any]:
        """Execute a market SELL on Binance and persist to DB."""
        binance_symbol = _to_binance_symbol(symbol)
        rounded_qty = self._round_quantity(binance_symbol, float(quantity))
        return self._submit_market_order(
            binance_symbol=binance_symbol,
            original_symbol=symbol,
            side="SELL",
            quantity=rounded_qty,
            source=source,
            position_id=position_id,
            signal_snapshot=kwargs.get("signal_snapshot"),
        )

    def validate_balance_for_trade(self, sale_action: str, symbol: str) -> tuple:
        """Check balance before placing an order on Binance."""
        from cache.balance_cache import get_balance_cache
        cache = get_balance_cache()
        try:
            if sale_action.upper() in ("BUY", "BID"):
                # Need quote asset (USDT)
                quote_asset = _to_binance_symbol(symbol)[-4:]  # last 4 chars: USDT/USDC
                if quote_asset not in ("USDT", "USDC"):
                    quote_asset = "USDT"
                available = cache.get_available_balance(
                    profile_name=self.profile.name, asset=quote_asset
                )
                # Also try USDC since that's the canonical quote in the system
                if available is None or float(available) <= 0:
                    available = cache.get_available_balance(
                        profile_name=self.profile.name, asset="USDC"
                    )
                if available is None or float(available) <= 0:
                    return False, f"No {quote_asset} balance available"
                return True, ""
            else:
                # Selling requires holding the base asset
                base_asset = symbol.split("_")[0].split("-")[0].upper()
                available = cache.get_available_balance(
                    profile_name=self.profile.name, asset=base_asset
                )
                if available is None or float(available) <= 0:
                    return False, f"No {base_asset} balance available to sell"
                return True, ""
        except Exception as e:
            return False, f"Balance check error: {e}"

    async def process_tradingview_alert(self, alert: Any, profile_name: str,
                                        source: str = "WEBHOOK") -> Optional[Any]:
        """Handle a TradingView webhook alert for a Binance profile."""
        action = getattr(alert, "action", None) or (alert.get("action") if isinstance(alert, dict) else None)
        symbol = getattr(alert, "symbol", None) or (alert.get("symbol") if isinstance(alert, dict) else None)
        quantity = str(getattr(alert, "quantity", None) or (alert.get("quantity") if isinstance(alert, dict) else "0"))

        if not action or not symbol:
            self.logger.warning("[Binance] process_tradingview_alert: missing action/symbol")
            return None

        action_upper = action.upper()
        if action_upper in ("BUY", "LONG"):
            return self.order_buy(symbol=symbol, quantity=quantity, source=source)
        elif action_upper in ("SELL", "SHORT", "CLOSE"):
            return self.order_sell(symbol=symbol, quantity=quantity, source=source)
        else:
            self.logger.warning(f"[Binance] process_tradingview_alert: unknown action {action!r}")
            return None

    def process_limit_order(self, order: Any, position_id: Any = None) -> Optional[Any]:
        """Check whether a resting limit/stop order has been filled on Binance."""
        symbol = getattr(order, "symbol", "") or ""
        order_id = str(getattr(order, "exchange_order_id", "") or "")
        if not order_id:
            return None
        try:
            return self.get_single_order(order_id=order_id, symbol=symbol)
        except Exception as e:
            self.logger.error(f"[Binance] process_limit_order() failed: {e}")
            return None

    # ── Low-level trading ─────────────────────────────────────────────────────

    def execute_order(self, order: Any) -> Optional[Dict]:
        """Submit a single order to Binance POST /api/v3/order."""
        binance_symbol = _to_binance_symbol(getattr(order, "symbol", ""))
        side = str(getattr(order, "side", "BUY")).upper()
        # Map internal Side enum values ("Bid"/"Ask") to Binance ("BUY"/"SELL")
        if side in ("BID", "BUY"):
            side = "BUY"
        elif side in ("ASK", "SELL"):
            side = "SELL"

        order_type = str(getattr(order, "order_type", "MARKET")).upper()
        quantity = str(getattr(order, "quantity", "0"))

        params: Dict[str, Any] = {
            "symbol":   binance_symbol,
            "side":     side,
            "type":     order_type,
            "quantity": quantity,
        }

        price = getattr(order, "price", None)
        if price and str(price) not in ("0", "0.0", ""):
            params["price"] = str(price)
            if order_type == "LIMIT":
                params["timeInForce"] = "GTC"

        # Optional stop-trigger price for STOP_LOSS / TAKE_PROFIT orders
        stop_price = getattr(order, "stop_price", None)
        if stop_price:
            params["stopPrice"] = str(stop_price)

        url, headers = self._signed_url(BinanceEndpoints.order(), params)
        try:
            return api_request(url, headers=headers, requestType=HttpMethod.POST)
        except Exception as e:
            self.logger.error(f"[Binance] execute_order({binance_symbol}) failed: {e}")
            return None

    def cancel_order(self, order_id: str, symbol: str) -> Optional[Dict]:
        binance_symbol = _to_binance_symbol(symbol)
        params = {"symbol": binance_symbol, "orderId": order_id}
        url, headers = self._signed_url(BinanceEndpoints.order(), params)
        try:
            return api_request(url, headers=headers, requestType=HttpMethod.DELETE)
        except Exception as e:
            self.logger.error(f"[Binance] cancel_order({order_id}, {symbol}) failed: {e}")
            return None

    def get_open_orders(self, symbol: str) -> List[Dict]:
        binance_symbol = _to_binance_symbol(symbol)
        params = {"symbol": binance_symbol}
        url, headers = self._signed_url(BinanceEndpoints.open_orders(), params)
        try:
            data = api_request(url, headers=headers)
            return data if isinstance(data, list) else []
        except Exception as e:
            self.logger.error(f"[Binance] get_open_orders({symbol}) failed: {e}")
            return []

    def get_single_order(self, order_id: str, symbol: str) -> Optional[Dict]:
        binance_symbol = _to_binance_symbol(symbol)
        params = {"symbol": binance_symbol, "orderId": order_id}
        url, headers = self._signed_url(BinanceEndpoints.order(), params)
        try:
            return api_request(url, headers=headers)
        except Exception as e:
            self.logger.error(f"[Binance] get_single_order({order_id}) failed: {e}")
            return None

    def get_order_history(self, symbol: str = None, order_id: str = None) -> List[Dict]:
        if not symbol:
            self.logger.warning("[Binance] get_order_history: symbol required for Binance allOrders")
            return []
        binance_symbol = _to_binance_symbol(symbol)
        params: Dict[str, Any] = {"symbol": binance_symbol}
        if order_id:
            params["orderId"] = order_id
        url, headers = self._signed_url(BinanceEndpoints.all_orders(binance_symbol), params)
        try:
            data = api_request(url, headers=headers)
            if not data:
                return []
            return data if isinstance(data, list) else []
        except Exception as e:
            self.logger.error(f"[Binance] get_order_history({symbol}) failed: {e}")
            return []

    # ── Optional capabilities ─────────────────────────────────────────────────

    def supports_klines(self) -> bool:
        return True

    def supports_dust_conversion(self) -> bool:
        return False

    # ── Internal order execution ──────────────────────────────────────────────

    def _submit_market_order(
        self,
        binance_symbol: str,
        original_symbol: str,
        side: str,
        quantity: str,
        source: str,
        position_id: Optional[str],
        signal_snapshot: Optional[dict] = None,
    ) -> Optional[Any]:
        """Place a MARKET order on Binance, parse the response, and persist to DB."""
        from db.session import SessionLocal
        from db.crud import save_trade, open_position, close_position
        from utils.position_calculator import PositionCalculator

        # 1. Place order
        params: Dict[str, Any] = {
            "symbol":   binance_symbol,
            "side":     side,
            "type":     "MARKET",
            "quantity": quantity,
        }
        url, headers = self._signed_url(BinanceEndpoints.order(), params)
        try:
            raw = api_request(url, headers=headers, requestType=HttpMethod.POST)
        except Exception as e:
            self.logger.error(f"[Binance] market order {side} {binance_symbol} failed: {e}")
            return None

        # 2. Parse into OrderResponse
        order_response = self._parse_order_response(raw, side, original_symbol, quantity)
        if order_response is None:
            self.logger.error(f"[Binance] Could not parse order response: {raw}")
            return None

        # 3. Persist to DB
        db = None
        try:
            db = SessionLocal()
            is_opening = position_id is None
            direction = "LONG" if side == "BUY" else "SHORT"
            adapter_side = "Bid" if side == "BUY" else "Ask"

            # Normalise side to system enum value
            order_response.side = adapter_side

            saved_trade = save_trade(
                db, order_response, self.profile.name, source,
                signal_snapshot=signal_snapshot,
                direction=direction if is_opening else None,
            )
            self.logger.info(f"[Binance] Trade saved: ID {saved_trade.id}")

            if is_opening:
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
                    f"[Binance] Position opened: ID {position.id}, "
                    f"TP: {tp_price}, SL: {sl_price}"
                )
            else:
                from db.crud import close_positions_fifo
                closed = close_positions_fifo(
                    db=db,
                    profile_name=self.profile.name,
                    symbol=original_symbol,
                    sell_trade=saved_trade,
                )
                if closed:
                    self.logger.info(
                        f"[Binance] Position closed: {[p['position_id'] for p in closed]}"
                    )

        except Exception as e:
            self.logger.error(f"[Binance] DB persistence failed: {e}", exc_info=True)
        finally:
            if db:
                db.close()

        return order_response

    def _parse_order_response(
        self,
        raw: Any,
        side: str,
        original_symbol: str,
        fallback_qty: str,
    ) -> Optional[Any]:
        """Parse a Binance POST /api/v3/order response into an OrderResponse."""
        from models.trade import OrderResponse
        import time

        if not isinstance(raw, dict):
            return None

        order_id = str(raw.get("orderId", "0"))
        executed_qty = str(raw.get("executedQty") or fallback_qty)
        cumulative_quote = str(raw.get("cummulativeQuoteQty") or "0")

        # Use fills to get weighted average price; fall back to field or price cache
        fills = raw.get("fills", [])
        exec_price = _avg_fill_price(fills)
        if exec_price is None:
            exec_price = raw.get("price") or raw.get("avgPrice")
        if not exec_price or float(exec_price) == 0:
            # Fall back to price cache for zero-price market orders
            from cache.price_cache import get_price_cache
            pc = get_price_cache()
            cached = (
                pc.get_price(original_symbol)
                or pc.get_price(_to_binance_symbol(original_symbol))
            )
            exec_price = str(cached) if cached else "0"
        else:
            exec_price = str(exec_price)

        # Recalculate quote notional if not provided
        if float(cumulative_quote) == 0 and float(exec_price) > 0:
            cumulative_quote = str(float(executed_qty) * float(exec_price))

        status_raw = str(raw.get("status", "FILLED")).upper()
        status_map = {
            "FILLED":            "Filled",
            "PARTIALLY_FILLED":  "PartiallyFilled",
            "NEW":               "Open",
            "CANCELED":          "Cancelled",
            "EXPIRED":           "Expired",
        }
        status = status_map.get(status_raw, "Filled")

        try:
            return OrderResponse(**{
                "id":                    order_id,
                "orderType":             "Market",
                "symbol":                original_symbol,
                "side":                  "Bid" if side == "BUY" else "Ask",
                "status":                status,
                "executedQuantity":      executed_qty,
                "executedQuoteQuantity": cumulative_quote,
                "price":                 exec_price,
                "createdAt":             raw.get("transactTime", int(time.time() * 1000)),
            })
        except Exception as e:
            self.logger.error(f"[Binance] OrderResponse construction failed: {e}")
            return None

    # ── Exchange info / market filter cache ───────────────────────────────────

    def _ensure_exchange_info_cache(self):
        """Populate per-symbol filter cache from /api/v3/exchangeInfo (once per instance)."""
        if self._exchange_info_cache is not None:
            return
        self._exchange_info_cache = {}
        url = BinanceEndpoints.exchange_info()
        try:
            data = api_request(url, timeout=15)
            if not data:
                return
            for s in data.get("symbols", []):
                sym = s.get("symbol", "")
                self._exchange_info_cache[sym] = {
                    "symbol":     sym,
                    "baseSymbol": s.get("baseAsset", ""),
                    "quoteSymbol": s.get("quoteAsset", ""),
                    "filters":    s.get("filters", []),
                    "orderTypes": s.get("orderTypes", []),
                    "status":     s.get("status"),
                    "_raw":       s,
                }
        except Exception as e:
            self.logger.warning(f"[Binance] _ensure_exchange_info_cache failed: {e}")

    def _get_lot_size_filter(self, binance_symbol: str) -> Dict[str, Any]:
        """Return the LOT_SIZE filter for binance_symbol, or safe defaults."""
        self._ensure_exchange_info_cache()
        info = self._exchange_info_cache.get(binance_symbol, {})
        for f in info.get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                return f
        return {"stepSize": "0.001", "minQty": "0.001", "maxQty": "999999"}

    def _round_quantity(self, binance_symbol: str, qty: float) -> str:
        """Round quantity down to the exchange's LOT_SIZE stepSize."""
        from decimal import Decimal
        f = self._get_lot_size_filter(binance_symbol)
        step = Decimal(str(f.get("stepSize", "0.001")))
        if step <= 0:
            return str(qty)
        q = Decimal(str(qty))
        rounded = (q // step) * step
        places = max(0, -step.as_tuple().exponent)
        return f"{rounded:.{places}f}"
