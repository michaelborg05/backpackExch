"""ExchangeAdapter — abstract base class for exchange integrations.

Each exchange (Backpack, Bullet, …) implements this interface so that
all callers (api_builders, monitoring_service, signal_generator) can
work with any exchange without knowing which one they're talking to.

Design notes:
  - All methods that don't apply to a given exchange should return a sensible
    no-op value (empty list, None) rather than raising, unless a hard error
    is the only honest answer.
  - Symbol format is exchange-specific. Callers should use the profile's
    symbol directly and let the adapter translate if needed.
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any


class ExchangeAdapter(ABC):
    """Abstract base class for exchange adapters.

    Concrete subclasses: BackpackAdapter, BulletAdapter
    """

    exchange_type: str  # "backpack" | "bullet"

    # ── Market data ───────────────────────────────────────────────────────────

    @abstractmethod
    def get_ticker(self, symbol: str) -> Optional[float]:
        """Return the latest price for *symbol* as a float, or None on failure."""

    @abstractmethod
    def get_depth(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Return the order book for *symbol* (bids/asks), or None on failure."""

    @abstractmethod
    def get_klines(self, symbol: str, interval: str, start_time: int, limit: int = 100) -> List[Dict]:
        """Return OHLCV candle data as a list of dicts.

        Each dict must contain at minimum: open, high, low, close, volume.
        Returns [] if unavailable (e.g. Bullet has no klines endpoint).
        """

    @abstractmethod
    def get_markets(self) -> Optional[List[Dict]]:
        """Return all available trading pairs with their filter/rule data."""

    @abstractmethod
    def get_market_info(self, symbol: str) -> Optional[Dict]:
        """Return market rules for a single symbol (min qty, step size, etc.)."""

    # ── Account ───────────────────────────────────────────────────────────────

    @abstractmethod
    def get_balances(self) -> Optional[Dict[str, Any]]:
        """Return account balances as a dict keyed by asset symbol."""

    # ── Trading ───────────────────────────────────────────────────────────────

    @abstractmethod
    def execute_order(self, order: Any) -> Optional[Dict]:
        """Submit an order to the exchange.

        Args:
            order: Exchange-specific order request object or dict.

        Returns:
            Order response dict on success, None on failure.
        """

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> Optional[Dict]:
        """Cancel an open order.

        Returns:
            Cancellation response dict on success, None on failure.
        """

    @abstractmethod
    def get_open_orders(self, symbol: str) -> List[Dict]:
        """Return all open orders for *symbol*."""

    @abstractmethod
    def get_single_order(self, order_id: str, symbol: str) -> Optional[Dict]:
        """Return the current state of a single order by ID."""

    @abstractmethod
    def get_order_history(self, symbol: str = None, order_id: str = None) -> List[Dict]:
        """Return historical (filled/cancelled) orders.

        Both arguments are optional filters.
        """

    # ── Optional capabilities ─────────────────────────────────────────────────

    # ── High-level trading (called by monitoring_service) ────────────────────

    @abstractmethod
    def order_buy(self, symbol: str, quantity: str, price: str = "0",
                  source: str = "MANUAL", **kwargs) -> Optional[Any]:
        """Execute a market buy order and persist the position to the DB."""

    @abstractmethod
    def order_sell(self, symbol: str, quantity: str, price: str = "0",
                   source: str = "MANUAL", position_id: str = None,
                   reason_summary=None, validation_summary: str = None,
                   **kwargs) -> Optional[Any]:
        """Execute a market sell/close order and update the DB position."""

    @abstractmethod
    def process_limit_order(self, order: Any, position_id: Any = None) -> Optional[Any]:
        """Check and process a pending limit order (TP/SL).

        For exchanges that track limit orders natively this should query the
        exchange and return an order response when the order is filled.
        Returns None when the order is still open.
        """

    @abstractmethod
    def validate_balance_for_trade(self, sale_action: str, symbol: str) -> tuple:
        """Pre-flight balance check before placing an order.

        Returns:
            (is_valid: bool, error_message: str)
        """

    @abstractmethod
    async def process_tradingview_alert(self, alert: Any, profile_name: str,
                                        source: str = "WEBHOOK",
                                        reason_summary=None) -> Optional[Any]:
        """Process a TradingView webhook alert and execute the appropriate trade."""

    # ── Optional capabilities ─────────────────────────────────────────────────

    def convert_dust(self) -> Optional[Dict]:
        """Convert small balances to the quote asset.

        Default implementation returns None (not supported).
        Override in adapters that support it (e.g. Backpack).
        """
        return None

    def get_funding_rate(self, symbol: str = None) -> Optional[List[Dict]]:
        """Return funding rate(s) for perpetual markets.

        Default implementation returns None (not applicable to spot).
        Override in adapters that support it (e.g. Bullet).
        """
        return None

    def supports_klines(self) -> bool:
        """Return True if this exchange provides OHLCV candle data."""
        return True

    def supports_dust_conversion(self) -> bool:
        """Return True if this exchange supports dust conversion."""
        return False
