from decimal import Decimal
from typing import Optional, Tuple
from models.trading_profile import TradingProfile

class PositionCalculator:
    """Calculate position prices based on entry price and profile settings"""
    
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