"""BackpackAdapter — thin wrapper around the existing Backpack api_builders.

Delegates every call to the established builders so no Backpack-specific logic
is duplicated. Adding the adapter layer means the rest of the codebase can treat
Backpack and Bullet identically through the ExchangeAdapter interface.
"""
from typing import Optional, List, Dict, Any

from api_builders.adapters.base import ExchangeAdapter
from utils.logging import log_manager


class BackpackAdapter(ExchangeAdapter):
    """ExchangeAdapter implementation for Backpack (spot exchange)."""

    exchange_type = "backpack"

    def __init__(self, profile):
        """
        Args:
            profile: TradingProfile instance for this adapter.
        """
        self.profile = profile
        self.logger = log_manager.get_logger("BackpackAdapter")

    # ── Market data ───────────────────────────────────────────────────────────

    def get_ticker(self, symbol: str) -> Optional[float]:
        from api_builders.market_builder import get_price
        try:
            return get_price(symbol)
        except Exception as e:
            self.logger.error(f"[Backpack] get_ticker({symbol}) failed: {e}")
            return None

    def get_depth(self, symbol: str) -> Optional[Dict[str, Any]]:
        from services.client import api_request
        from utils.endpoints import BackpackEndpoints
        from utils.auth import build_auth_headers
        url = BackpackEndpoints.depth(symbol)
        headers = build_auth_headers(
            "backpack", self.profile, instruction="balanceQuery"
        )
        try:
            return api_request(url, headers)
        except Exception as e:
            self.logger.error(f"[Backpack] get_depth({symbol}) failed: {e}")
            return None

    def get_klines(self, symbol: str, interval: str, start_time: int, limit: int = 100) -> List[Dict]:
        """Fetch candles from Backpack.  Returns list of raw dicts (open/high/low/close/volume)."""
        from services.client import api_request
        from utils.endpoints import BackpackEndpoints
        url = BackpackEndpoints.klines(symbol, interval, start_time)
        try:
            data = api_request(url, timeout=10)
            return data if data else []
        except Exception as e:
            self.logger.error(f"[Backpack] get_klines({symbol}) failed: {e}")
            return []

    def get_markets(self) -> Optional[List[Dict]]:
        from api_builders.market_builder import get_all_markets
        try:
            return get_all_markets()
        except Exception as e:
            self.logger.error(f"[Backpack] get_markets() failed: {e}")
            return None

    def get_market_info(self, symbol: str) -> Optional[Dict]:
        from api_builders.market_builder import get_market_info
        try:
            return get_market_info(symbol)
        except Exception as e:
            self.logger.error(f"[Backpack] get_market_info({symbol}) failed: {e}")
            return None

    # ── Account ───────────────────────────────────────────────────────────────

    def get_balances(self) -> Optional[Dict[str, Any]]:
        from api_builders.account_builder import get_balances
        from models.balance import BalanceReader
        try:
            result = get_balances(profile=self.profile, update_cache=True)
            if isinstance(result, BalanceReader):
                return result.to_dict()
            return result
        except Exception as e:
            self.logger.error(f"[Backpack] get_balances() failed: {e}")
            return None

    # ── Trading ───────────────────────────────────────────────────────────────

    # ── High-level trading (called by monitoring_service) ────────────────────

    def order_buy(self, symbol: str, quantity: str, price: str = "0",
                  source: str = "MANUAL", **kwargs) -> Optional[Any]:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            return trading.order_buy(symbol=symbol, quantity=quantity,
                                     price=price, source=source, **kwargs)
        except Exception as e:
            self.logger.error(f"[Backpack] order_buy({symbol}) failed: {e}")
            return None

    def order_sell(self, symbol: str, quantity: str, price: str = "0",
                   source: str = "MANUAL", position_id: str = None,
                   **kwargs) -> Optional[Any]:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            return trading.order_sell(
                symbol=symbol, quantity=quantity, price=price, source=source,
                position_id=position_id, **kwargs
            )
        except Exception as e:
            self.logger.error(f"[Backpack] order_sell({symbol}) failed: {e}")
            return None

    def process_limit_order(self, order: Any, position_id: Any = None) -> Optional[Any]:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            return trading.process_limit_order(order=order, position_id=position_id)
        except Exception as e:
            self.logger.error(f"[Backpack] process_limit_order() failed: {e}")
            return None

    def place_maker_entry_order(self, symbol: str, quantity: str, limit_price: str,
                                is_long: bool, source: str = "MAKER_ENTRY") -> Optional[Any]:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            return trading.place_maker_entry_order(
                symbol=symbol, quantity=quantity, limit_price=limit_price,
                is_long=is_long, source=source,
            )
        except Exception as e:
            self.logger.error(f"[Backpack] place_maker_entry_order({symbol}) failed: {e}")
            return None

    def reconcile_entry_order(self, order: Any) -> dict:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            return trading.reconcile_entry_order(order)
        except Exception as e:
            self.logger.error(f"[Backpack] reconcile_entry_order() failed: {e}")
            return {"status": "resting", "position_id": None}

    def validate_balance_for_trade(self, sale_action: str, symbol: str) -> tuple:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            return trading.validate_balance_for_trade(sale_action=sale_action, symbol=symbol)
        except Exception as e:
            self.logger.error(f"[Backpack] validate_balance_for_trade() failed: {e}")
            return False, str(e)

    async def process_tradingview_alert(self, alert: Any, profile_name: str,
                                        source: str = "WEBHOOK") -> Optional[Any]:
        from api_builders.trading_builder import TradingService, process_tradingview_alert
        try:
            trading = TradingService(self.profile)
            return await process_tradingview_alert(
                trading, alert, profile_name=profile_name, source=source
            )
        except Exception as e:
            self.logger.error(f"[Backpack] process_tradingview_alert() failed: {e}")
            return None

    # ── Low-level trading ─────────────────────────────────────────────────────

    def execute_order(self, order: Any) -> Optional[Dict]:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            result = trading.ExecuteOrder(order)
            return result
        except Exception as e:
            self.logger.error(f"[Backpack] execute_order() failed: {e}")
            return None

    def cancel_order(self, order_id: str, symbol: str) -> Optional[Dict]:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            result = trading.cancel_order(order_id=order_id, symbol=symbol)
            return result
        except Exception as e:
            self.logger.error(f"[Backpack] cancel_order({order_id}) failed: {e}")
            return None

    def get_open_orders(self, symbol: str) -> List[Dict]:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            orders = trading.get_open_orders(symbol=symbol)
            return orders if orders else []
        except Exception as e:
            self.logger.error(f"[Backpack] get_open_orders({symbol}) failed: {e}")
            return []

    def get_single_order(self, order_id: str, symbol: str) -> Optional[Dict]:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            return trading.get_single_order(symbol=symbol, order_id=order_id)
        except Exception as e:
            self.logger.error(f"[Backpack] get_single_order({order_id}) failed: {e}")
            return None

    def get_order_history(self, symbol: str = None, order_id: str = None) -> List[Dict]:
        from api_builders.trading_builder import TradingService
        try:
            trading = TradingService(self.profile)
            result = trading.get_order_history(symbol=symbol, order_id=order_id)
            if result is None:
                return []
            return result if isinstance(result, list) else [result]
        except Exception as e:
            self.logger.error(f"[Backpack] get_order_history() failed: {e}")
            return []

    # ── Optional capabilities ─────────────────────────────────────────────────

    def convert_dust(self) -> Optional[Dict]:
        from api_builders.dust_conversion import get_dust_converter
        try:
            converter = get_dust_converter()
            return converter.convert_dust(self.profile)
        except Exception as e:
            self.logger.error(f"[Backpack] convert_dust() failed: {e}")
            return None

    def supports_dust_conversion(self) -> bool:
        return True

    def supports_klines(self) -> bool:
        return True
