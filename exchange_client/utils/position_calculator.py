from cache.balance_cache import get_balance_cache
from cache.price_cache import get_price_cache
from db.utils import get_db_session
from db.crud import get_symbol_config, get_open_positions
from decimal import Decimal
from typing import Optional, Tuple
from models.trading_profile import TradingProfile
from utils.logging import log_manager

class PositionCalculator:
    """Calculate position prices based on entry price and profile settings"""

    def __init__(self):
        self.logger = log_manager.get_logger("PositionCalculator")
        self.balance_cache = get_balance_cache()
        self.price_cache = get_price_cache()

    @staticmethod
    def calculate_position_prices(
        entry_price: Decimal,
        side: str,  # "BUY" or "SELL"
        profile: TradingProfile
    ) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
        """
        Calculate TP, SL, and trailing SL prices based on entry and profile settings
        
        Args:
            entry_price: Entry price of the trade
            side: Trade side ("BID" or "ASK")
            profile: Trading profile with percentage settings
            
        Returns:
            Tuple of (tp_price, sl_price, trailing_sl_price)
        """
        tp_price = None
        sl_price = None
        trailing_sl_price = None
        
        if side == "BID":
            # Long position
            if profile.take_profit_pct:
                tp_price = entry_price * (Decimal("1") + profile.take_profit_pct / Decimal("100"))
            
            if profile.stop_loss_pct:
                sl_price = entry_price * (Decimal("1") - profile.stop_loss_pct / Decimal("100"))
            
            if profile.use_trailing_stop and profile.trailing_stop_pct:
                trailing_sl_price = entry_price * (Decimal("1") - profile.trailing_stop_pct / Decimal("100"))
        
        else:  # "ASK"
            # Short position
            if profile.take_profit_pct:
                tp_price = entry_price * (Decimal("1") - profile.take_profit_pct / Decimal("100"))
            
            if profile.stop_loss_pct:
                sl_price = entry_price * (Decimal("1") + profile.stop_loss_pct / Decimal("100"))
            
            if profile.use_trailing_stop and profile.trailing_stop_pct:
                trailing_sl_price = entry_price * (Decimal("1") + profile.trailing_stop_pct / Decimal("100"))
        
        return tp_price, sl_price, trailing_sl_price
    
    @staticmethod
    def update_trailing_stop(
        current_price: Decimal,
        highest_price: Decimal,
        trailing_sl_price: Decimal,
        trailing_stop_pct: Decimal,
        side: str
    ) -> Tuple[Decimal, Decimal]:
        """
        Update trailing stop and highest price
        
        Args:
            current_price: Current market price
            highest_price: Highest price seen so far
            trailing_sl_price: Current trailing stop price
            trailing_stop_pct: Trailing stop percentage
            side: Trade side ("BUY" or "SELL")
            
        Returns:
            Tuple of (new_highest_price, new_trailing_sl_price)
        """
        if side == "BID":
            # Long position - trail up
            if current_price > highest_price:
                new_highest = current_price
                new_trailing_sl = current_price * (Decimal("1") - trailing_stop_pct / Decimal("100"))
                return new_highest, new_trailing_sl
        else:
            # Short position - trail down
            if current_price < highest_price:
                new_highest = current_price
                new_trailing_sl = current_price * (Decimal("1") + trailing_stop_pct / Decimal("100"))
                return new_highest, new_trailing_sl
        
        return highest_price, trailing_sl_price

    def calculate_buy_quantity(
        self,
        symbol: str,
        profile: TradingProfile,
        quote_asset: str = "USDC"
    ) -> Tuple[Optional[Decimal], str]:
        """
        Calculate buy quantity for a symbol
        
        Returns:
            (quantity, reason) - quantity in base asset, reason for the calculation
        """
        # Get current price
        price = self.price_cache.get_price(symbol)
        if not price:
            return None, f"Price not available for {symbol}"
        
        # Get portfolio value for position sizing
        from cache.portfolio_cache import get_portfolio_cache
        portfolio_cache = get_portfolio_cache()
        total_portfolio_value = portfolio_cache.get_total_value(quote_asset=quote_asset, profile_name=profile.name)
        
        # Check for symbol-specific override
        with get_db_session() as db:
            symbol_config = get_symbol_config(db, profile.name, symbol)
            
            # Calculate target order size in USDC (always fixed amount)
            if symbol_config and symbol_config.order_size_usdc:
                # Use symbol-specific dollar amount
                order_size_usdc = Decimal(str(symbol_config.order_size_usdc))
                reason = f"Symbol override: ${order_size_usdc}"
            else:
                # Use profile default dollar amount
                order_size_usdc = Decimal(str(profile.default_order_size_usdc))
                reason = f"Profile default: ${order_size_usdc}"
            
            # Check against max position size (as % of portfolio)
            max_position_pct = self._get_max_position_pct(symbol, profile, symbol_config)
            max_position_value = (total_portfolio_value * max_position_pct) / Decimal("100")
            
            existing_position_value = self._get_existing_position_value(db, profile.name, symbol, price)
            
            remaining_capacity = max_position_value - existing_position_value
            if remaining_capacity <= 0:
                return None, (
                    f"Max position size reached "
                    f"(${existing_position_value:.2f} / ${max_position_value:.2f} "
                    f"[{max_position_pct}% of ${total_portfolio_value:.2f}])"
                )
            
            # Cap order size to remaining capacity
            if order_size_usdc > remaining_capacity:
                order_size_usdc = remaining_capacity
                reason += (
                    f" (capped to remaining capacity ${remaining_capacity:.2f}, "
                    f"max position: {max_position_pct}% of portfolio)"
                )
            
            # Check against available balance
            available = self.balance_cache.get_available_balance(profile.name, quote_asset)
            if available and order_size_usdc > available:
                order_size_usdc = available * Decimal("0.999")  # 0.1% buffer
                reason += f" (limited by available balance ${available:.2f})"
            
            from db.crud import get_open_positions_for_symbol

            # Check max open positions
            open_positions = get_open_positions_for_symbol(db, profile.name, symbol)
            if open_positions and len(open_positions) >= profile.max_open_positions:
                return None, f"Max open positions reached for symbol {symbol} ({len(open_positions)}/{profile.max_open_positions})"

            if order_size_usdc < 5:
                return None, f"USDC amount too low: {order_size_usdc})"

            # Convert USDC to base quantity
            quantity = order_size_usdc / price
            
            self.logger.info(
                f"[{profile.name}] {symbol} position size: "
                f"{quantity:.6f} @ ${price:.4f} = ${order_size_usdc:.2f} - {reason}"
            )
            
            return quantity, reason
    
    def _get_max_position_pct(
        self,
        symbol: str,
        profile: TradingProfile,
        symbol_config = None
    ) -> Decimal:
        """Get max position size as % of portfolio (symbol override or profile default)"""
        if symbol_config and symbol_config.max_position_size_pct:
            return Decimal(str(symbol_config.max_position_size_pct))
        return Decimal(str(profile.max_position_size_pct))
    
    def _get_existing_position_value(
        self,
        db,
        profile_name: str,
        symbol: str,
        current_price: Decimal
    ) -> Decimal:
        """Calculate current value of existing positions for this symbol"""
        from db.crud import get_open_positions_for_symbol

        positions = get_open_positions_for_symbol(db, profile_name, symbol)
        if not positions:
            return Decimal("0")

        return sum(Decimal(str(p.remaining_quantity)) * current_price for p in positions)


# Global instance
_calculator = None

def get_position_size_calculator():
    global _calculator
    if _calculator is None:
        _calculator = PositionCalculator()
    return _calculator