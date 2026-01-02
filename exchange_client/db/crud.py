# db/crud.py
from sqlalchemy.orm import Session
from decimal import Decimal
from typing import Optional
from datetime import datetime
from zoneinfo import ZoneInfo
from db.models import Trade, Position
from models.trade import OrderResponse
from models.trading_profile import TradingProfile
from db.models import TradingProfileDB

def save_trade(db: Session, order: OrderResponse, profile_name: str, reason: str = "MANUAL") -> Trade:
    """Save a trade to the database"""
    
    if order.price is None or order.price == "0":
        # Calculate average price from executed values
        unit_price = Decimal(order.executed_quote_quantity) / Decimal(order.executed_quantity)
    else:
        unit_price = Decimal(str(order.price))

    trade = Trade(
        profile_name=profile_name,
        order_id=str(order.id),
        symbol=order.symbol,
        side=order.side.upper(),
        quantity=Decimal(str(order.executed_quantity)),
        price=Decimal(str(unit_price)),
        exchange="backpack",
        reason=reason
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade

def open_position(
    db: Session, 
    trade: Trade,  # Changed: accept Trade object, not OrderResponse
    tp_price: Optional[Decimal] = None,
    sl_price: Optional[Decimal] = None,
    trailing_sl_price: Optional[Decimal] = None,
    highest_price: Optional[Decimal] = None        
) -> Position:
    """Open a new position"""
    position = Position(
        profile_name=trade.profile_name,
        symbol=trade.symbol,
        buy_trade_id=trade.id,  # Use database Trade ID
        tp_price=tp_price,
        sl_price=sl_price,
        trailing_sl_price=trailing_sl_price,
        highest_price=highest_price or trade.price,  # Initialize with entry price
        status="OPEN"
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return position

def update_position_trailing_stop(
    db: Session,
    position_id: int,
    highest_price: Decimal,
    trailing_sl_price: Decimal
) -> Position:
    """Update position's trailing stop"""
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise ValueError(f"Position {position_id} not found")
    
    position.highest_price = highest_price
    position.trailing_sl_price = trailing_sl_price
    
    db.commit()
    db.refresh(position)
    return position

def close_position(
    db: Session,
    position_id: int,
    sell_trade: Trade,
    reason: str = "MANUAL"
) -> Position:
    """Close an existing position"""
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise ValueError(f"Position {position_id} not found")
    
    position.sell_trade_id = sell_trade.id
    position.status = "CLOSED"
    position.close_reason = reason
    position.closed_at = datetime.now(ZoneInfo("Australia/Sydney"))

    # Calculate profit
    buy_trade = position.buy_trade
    
    if buy_trade and sell_trade:
        buy_value = buy_trade.quantity * buy_trade.price
        sell_value = sell_trade.quantity * sell_trade.price
        position.profit = sell_value - buy_value
    
    db.commit()
    db.refresh(position)
    return position

def get_open_positions(db: Session, profile_name: str, symbol: Optional[str] = None):
    """Get all open positions for a profile"""
    query = db.query(Position).filter(
        Position.profile_name == profile_name,
        Position.status == "OPEN"
    )
    if symbol:
        query = query.filter(Position.symbol == symbol)
    return query.all()

def get_open_position_for_symbol(
    db: Session, 
    profile_name: str, 
    symbol: str
) -> Optional[Position]:
    """Get the open position for a specific symbol"""
    return db.query(Position).filter(
        Position.profile_name == profile_name,
        Position.symbol == symbol,
        Position.status == "OPEN"
    ).first()

def close_invalid_position(
    db: Session,
    position_id: int,
    reason: str = "INVALID_POSITION"
) -> Position:
    """Close a position that's invalid (no sell trade)"""
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise ValueError(f"Position {position_id} not found")
    
    position.status = "CLOSED"
    position.close_reason = reason
    position.closed_at = datetime.now(ZoneInfo("Australia/Sydney"))
    position.profit = None  # No profit calculation since we don't have sell details
    
    db.commit()
    db.refresh(position)
    return position

def get_profile_by_name(db: Session, name: str) -> Optional[TradingProfileDB]:
    """Get a trading profile by name"""
    return db.query(TradingProfileDB).filter(
        TradingProfileDB.name == name,
        TradingProfileDB.is_active == True
    ).first()

def get_all_profiles(db: Session) -> list[TradingProfileDB]:
    """Get all active trading profiles"""
    return db.query(TradingProfileDB).filter(
        TradingProfileDB.is_active == True
    ).all()

def create_profile(db: Session, profile: TradingProfile) -> TradingProfileDB:
    """Create a new trading profile"""
    db_profile = TradingProfileDB(
        name=profile.name,
        api_key=profile.api_key,
        secret=profile.secret,
        take_profit_pct=profile.take_profit_pct,
        stop_loss_pct=profile.stop_loss_pct,
        trailing_stop_pct=profile.trailing_stop_pct,
        use_trailing_stop=profile.use_trailing_stop,
        max_risk_pct=profile.max_risk_pct,
        default_order_size_pct=profile.default_order_size_pct,
        max_position_size=profile.max_position_size
    )
    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return db_profile

def update_profile(db: Session, name: str, profile: TradingProfile) -> TradingProfileDB:
    """Update an existing profile"""
    db_profile = get_profile_by_name(db, name)
    if not db_profile:
        raise ValueError(f"Profile '{name}' not found")
    
    # Update fields
    for key, value in profile.model_dump(exclude_none=True).items():
        setattr(db_profile, key, value)
    
    db.commit()
    db.refresh(db_profile)
    return db_profile

def delete_profile(db: Session, name: str) -> bool:
    """Soft delete a profile"""
    db_profile = get_profile_by_name(db, name)
    if not db_profile:
        return False
    
    db_profile.is_active = False
    db.commit()
    return True

def db_profile_to_pydantic(db_profile: TradingProfileDB) -> TradingProfile:
    """Convert database profile to Pydantic model"""
    return TradingProfile(
        name=db_profile.name,
        api_key=db_profile.api_key,
        secret=db_profile.secret,
        take_profit_pct=db_profile.take_profit_pct,
        stop_loss_pct=db_profile.stop_loss_pct,
        trailing_stop_pct=db_profile.trailing_stop_pct,
        use_trailing_stop=db_profile.use_trailing_stop,
        max_risk_pct=db_profile.max_risk_pct,
        default_order_size_pct=db_profile.default_order_size_pct,
        max_position_size=db_profile.max_position_size
    )