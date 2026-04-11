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
                     profile.api_key = wallet address (bullet1...)
                     profile.secret  = Ed25519 private key (base64)
        """
        self.profile = profile
        self.address = profile.api_key   # wallet address
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
        url = BulletEndpoints.balance(self.address)
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
        url = BulletEndpoints.account(self.address)
        try:
            return api_request(url)
        except Exception as e:
            self.logger.error(f"[Bullet] get_account() failed: {e}")
            return None

    # ── High-level trading (called by monitoring_service) ────────────────────

    def order_buy(self, symbol: str, quantity: str, price: str = "0",
                  source: str = "MANUAL", **kwargs) -> Optional[Any]:
        """Place a market buy on Bullet.

        Full implementation requires build_bullet_transaction() to be complete.
        See utils/auth.py for the implementation guide.
        """
        self.logger.warning(
            f"[Bullet] order_buy({symbol}) called but Bullet tx signing is not yet "
            "implemented. See utils/auth.py::build_bullet_transaction()."
        )
        return None

    def order_sell(self, symbol: str, quantity: str, price: str = "0",
                   source: str = "MANUAL", position_id: str = None,
                   reason_summary=None, validation_summary: str = None,
                   **kwargs) -> Optional[Any]:
        """Place a market sell/close on Bullet.

        Full implementation requires build_bullet_transaction() to be complete.
        """
        self.logger.warning(
            f"[Bullet] order_sell({symbol}) called but Bullet tx signing is not yet "
            "implemented. See utils/auth.py::build_bullet_transaction()."
        )
        return None

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
        """TradingView webhook not yet supported for Bullet (tx signing pending)."""
        self.logger.warning(
            "[Bullet] process_tradingview_alert called but Bullet tx signing is not yet implemented."
        )
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
            nonce = self._get_next_nonce()
            tx_b64 = build_bullet_transaction(
                private_key_b64=self.profile.secret,
                call_data=call_data,
                nonce=nonce,
            )
            url = BulletEndpoints.submit_tx()
            response = api_request(
                url,
                body={"transaction": tx_b64},
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
            nonce = self._get_next_nonce()
            tx_b64 = build_bullet_transaction(
                private_key_b64=self.profile.secret,
                call_data=call_data,
                nonce=nonce,
            )
            url = BulletEndpoints.submit_tx()
            response = api_request(
                url,
                body={"transaction": tx_b64},
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
        url = BulletEndpoints.open_orders(bullet_symbol, self.address)
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
        url = BulletEndpoints.single_order(bullet_symbol, self.address, order_id=order_id)
        try:
            return api_request(url)
        except Exception as e:
            self.logger.error(f"[Bullet] get_single_order({order_id}) failed: {e}")
            return None

    def get_order_history(self, symbol: str = None, order_id: str = None) -> List[Dict]:
        """Fetch order history from /fapi/v1/allOrders."""
        bullet_symbol = _to_bullet_symbol(symbol) if symbol else None
        url = BulletEndpoints.order_history(self.address, symbol=bullet_symbol, order_id=order_id)
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

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_place_order_call(self, order: Any) -> Dict:
        """Build the runtime call payload for a place_order transaction.

        TODO: fill in once the NewOrderArgs Borsh schema is confirmed.
        The /rollup/schema endpoint on mainnet/testnet has the full field list.
        """
        bullet_symbol = _to_bullet_symbol(getattr(order, "symbol", ""))
        return {
            "exchange": {
                "place_order": {
                    "symbol": bullet_symbol,
                    "side": getattr(order, "side", ""),
                    "order_type": getattr(order, "orderType", "LIMIT"),
                    "quantity": str(getattr(order, "quantity", "0")),
                    "price": str(getattr(order, "price", "0")),
                    "time_in_force": getattr(order, "timeInForce", "GTC"),
                }
            }
        }

    def _build_cancel_order_call(self, order_id: str, symbol: str) -> Dict:
        """Build the runtime call payload for a cancel_order transaction."""
        bullet_symbol = _to_bullet_symbol(symbol)
        return {
            "exchange": {
                "cancel_order": {
                    "symbol": bullet_symbol,
                    "order_id": order_id,
                }
            }
        }

    def _get_next_nonce(self) -> int:
        """Return a monotonically increasing nonce based on current timestamp (ms)."""
        import time
        return int(time.time() * 1000)
