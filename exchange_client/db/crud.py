# db/crud.py
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal
from typing import Optional, List
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
        reason=reason,
        created_at=datetime.now(ZoneInfo("Australia/Sydney"))
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
        quantity=Decimal(trade.quantity),  # ⭐ Track quantity
        remaining_quantity=Decimal(trade.quantity),  # ⭐ Initially equals quantity
        entry_price=Decimal(trade.price),
        tp_price=tp_price,
        sl_price=sl_price,
        trailing_sl_price=trailing_sl_price,
        highest_price=highest_price or trade.price,  # Initialize with entry price
        status="OPEN",
        created_at=datetime.now(ZoneInfo("Australia/Sydney"))
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
    position.exit_price = sell_trade.price
    position.remaining_quantity = 0

    # Calculate profit
    position.profit = (position.exit_price - position.entry_price) * position.quantity 
    
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


def close_positions_fifo(
    db: Session,
    profile_name: str,
    symbol: str,
    sell_trade: Trade,
    reason: str = "MANUAL"
) -> List:
    """
    Close positions using FIFO matching
    
    Args:
        db: Database session
        profile_name: Trading profile name
        symbol: Symbol to close positions for
        sell_trade: Sell trade that closes positions
        reason: Reason for closing
    
    Returns:
        List of closed/partially closed positions
    """
    
    
    # Get open positions for this symbol, ordered by opened_at (FIFO)
    open_positions = (
        db.query(Position)
        .filter(
            Position.profile_name == profile_name,
            Position.symbol == symbol,
            Position.status == 'OPEN',
            Position.remaining_quantity > 0
        )
        .order_by(Position.created_at.asc())  # FIFO: oldest first
        .all()
    )
    
    if not open_positions:
        return []
    
    # Quantity to close
    remaining_to_close = Decimal(sell_trade.quantity)
    closed_positions = []
    
    for position in open_positions:
        if remaining_to_close <= 0:
            break
        
        # How much of this position can we close?
        close_qty = min(position.remaining_quantity, remaining_to_close)
        
        # Calculate profit for this portion
        entry_price = position.entry_price
        exit_price = Decimal(sell_trade.price)
        profit = (exit_price - entry_price) * position.quantity
        profit_pct = ((exit_price - entry_price) / entry_price) * 100
        
        # Update position
        position.remaining_quantity -= close_qty
        remaining_to_close -= close_qty
        
        if position.remaining_quantity <= Decimal('0.00000001'):  # Fully closed
            position.status = 'CLOSED'
            position.sell_trade_id = sell_trade.id
            position.exit_price = exit_price
            position.profit = profit
            position.closed_at = datetime.now(ZoneInfo("Australia/Sydney"))
            position.close_reason = reason
            
            closed_positions.append({
                'position_id': position.id,
                'status': 'FULLY_CLOSED',
                'closed_quantity': close_qty,
                'profit': profit,
                'profit_pct': profit_pct
            })
        else:  # Partially closed
            # For partial closes, you might want to create a separate record
            # or just track in the same position
            closed_positions.append({
                'position_id': position.id,
                'status': 'PARTIALLY_CLOSED',
                'closed_quantity': close_qty,
                'remaining_quantity': position.remaining_quantity,
                'profit': profit,
                'profit_pct': profit_pct
            })
    
    db.commit()
    
    return closed_positions


def get_open_position_quantity(
    db: Session,
    profile_name: str,
    symbol: str
) -> Decimal:
    """
    Get total open position quantity for a symbol
    
    Args:
        db: Database session
        profile_name: Profile name
        symbol: Symbol
    
    Returns:
        Total open quantity
    """
    
    result = (
        db.query(func.sum(Position.remaining_quantity))
        .filter(
            Position.profile_name == profile_name,
            Position.symbol == symbol,
            Position.status == 'OPEN'
        )
        .scalar()
    )
    
    return result or Decimal('0')


def get_open_positions_for_symbol(
    db: Session,
    profile_name: str,
    symbol: str
) -> List:
    """
    Get all open positions for a symbol (FIFO order)
    
    Args:
        db: Database session
        profile_name: Profile name
        symbol: Symbol
    
    Returns:
        List of open positions
    """
    
    return (
        db.query(Position)
        .filter(
            Position.profile_name == profile_name,
            Position.symbol == symbol,
            Position.status == 'OPEN',
            Position.remaining_quantity > 0
        )
        .order_by(Position.opened_at.asc())
        .all()
    )

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

