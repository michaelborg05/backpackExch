# db/crud.py
from sqlalchemy.orm import Session
from sqlalchemy import func
from decimal import Decimal
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from db.models import Trade, Position, Order
from models.trade import OrderResponse, OrderHistoryResponse
from models.trading_profile import TradingProfile
from db.models import TradingProfileDB, CircuitBreakerConfig, CircuitBreakerEvent, DailyBalanceSnapshot, SymbolConfig

def save_trade(db: Session, order: OrderResponse, profile_name: str, reason: str = "MANUAL", reason_summary: List[str] = None) -> Trade:
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
        created_at=datetime.now(timezone.utc),
        reason_summary=reason_summary
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade

def save_limit_trade(db: Session, order: OrderHistoryResponse, profile_name: str, reason: str = "MANUAL", reason_summary: List[str] = None) -> Trade:
    """Save a limit trade to the database"""

    if order.price is None or order.price == "0":
        # Calculate average price from executed values
        unit_price = Decimal(order.executedQuoteQuantity) / Decimal(order.executedQuantity)
    else:
        unit_price = Decimal(str(order.price))

    trade = Trade(
        profile_name=profile_name,
        order_id=str(order.id),
        symbol=order.symbol,
        side=order.side.upper(),
        quantity=Decimal(str(order.executedQuantity)),
        price=Decimal(str(unit_price)),
        exchange="backpack",
        reason=reason,
        created_at=datetime.now(timezone.utc),
        reason_summary=reason_summary
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade

def save_order(db: Session, order: OrderResponse, profile_name: str, position_id: int, purpose: str = None) -> Trade:
    """Save an order to the database"""

    order = Order(
        profile_name=profile_name,
        exchange_order_id=str(order.id),
        symbol=order.symbol,
        side=order.side.upper(),
        position_id=position_id,
        quantity=Decimal(str(order.quantity)),
        price=Decimal(str(order.price)) if order.price is not None else Decimal('0'),
        status="New",
        exchange="backpack",
        purpose=purpose,
        filled_quantity=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order

def open_position(
    db: Session, 
    trade: Trade,  # Changed: accept Trade object, not OrderResponse
    tp_price: Optional[Decimal] = None,
    sl_price: Optional[Decimal] = None,
    trailing_sl_price: Optional[Decimal] = None,
    highest_price: Optional[Decimal] = None,       
    lowest_price: Optional[Decimal] = None
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
        lowest_price=lowest_price or trade.price,  # Initialize with entry price
        status="OPEN",
        created_at=datetime.now(timezone.utc)
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

def update_high_low(
    db: Session,
    position_id: int,
    highest_price: Decimal,
    lowest_price: Decimal
) -> Position:
    """Update position's trailing stop"""
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise ValueError(f"Position {position_id} not found")
    
    if highest_price > position.highest_price:
        position.highest_price = highest_price

    if lowest_price < position.lowest_price:
        position.lowest_price = lowest_price
    
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
    position.closed_at = datetime.now(timezone.utc)
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
    position.closed_at = datetime.now(timezone.utc)
    position.profit = None  # No profit calculation since we don't have sell details
    
    db.commit()
    db.refresh(position)
    return position

def close_limit_position(
    db: Session,
    position_id: int,
    reason: str
) -> Position:
    """Close a position that's invalid (no sell trade)"""
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise ValueError(f"Position {position_id} not found")
    
    position.status = "CLOSED"
    position.close_reason = reason
    position.closed_at = datetime.now(timezone.utc)
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
            position.closed_at = datetime.now(timezone.utc)
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
        .order_by(Position.created_at.asc())
        .all()
    )

def get_active_orders(db: Session, profile_name: str, symbol: str = None) -> List[Order]:
    """Get all open positions for a profile"""
    active_statuses = ["New", "PartiallyFilled", "TriggerPending"]

    query = db.query(Order).filter(
        Order.profile_name == profile_name,
        Order.status.in_(active_statuses)
    )

    if symbol:
        query = query.filter(Order.symbol == symbol)

    return query.all()

def update_order(db: Session, profile_name: str, exch_order_id: str, status: str) -> List[Order]:
    """Update an existing order"""

    order = db.query(Order).filter(
        Order.profile_name == profile_name,
        Order.exchange_order_id == exch_order_id
    ).first()

    if not order:
        raise ValueError(f"Order {exch_order_id} not found")

    if order.status == status:
        # Status already matching
        return order

    order.status = status

    db.commit()
    db.refresh(order)
    return order

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


def get_circuit_breaker_config(
    db: Session, 
    profile_name: str
) -> Optional[CircuitBreakerConfig]:
    """Get circuit breaker config for a profile"""
    return db.query(CircuitBreakerConfig).filter(
        CircuitBreakerConfig.profile_name == profile_name,
        CircuitBreakerConfig.is_active == True
    ).first()


def create_circuit_breaker_config(
    db: Session,
    profile_name: str,
    max_daily_profit_pct: Decimal = Decimal("5.0"),
    max_daily_loss_pct: Decimal = Decimal("2.0"),
    profit_lock_hours: int = 6,
    loss_lock_hours: int = 12
) -> CircuitBreakerConfig:
    """Create default circuit breaker config for a profile"""
    config = CircuitBreakerConfig(
        profile_name=profile_name,
        max_daily_profit_pct=max_daily_profit_pct,
        max_daily_loss_pct=max_daily_loss_pct,
        profit_lock_hours=profit_lock_hours,
        loss_lock_hours=loss_lock_hours
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_circuit_breaker_config(
    db: Session,
    profile_name: str,
    **updates
) -> CircuitBreakerConfig:
    """Update circuit breaker config"""
    config = get_circuit_breaker_config(db, profile_name)
    if not config:
        raise ValueError(f"Circuit breaker config not found for {profile_name}")
    
    for key, value in updates.items():
        if hasattr(config, key):
            setattr(config, key, value)
    
    db.commit()
    db.refresh(config)
    return config


# ===== Circuit Breaker Events =====

def get_active_circuit_breaker(
    db: Session, 
    profile_name: str
) -> Optional[CircuitBreakerEvent]:
    """Get active circuit breaker event for a profile"""
    now = datetime.now(timezone.utc)
    
    return db.query(CircuitBreakerEvent).filter(
        CircuitBreakerEvent.profile_name == profile_name,
        CircuitBreakerEvent.is_active == True,
        #CircuitBreakerEvent.reset_at > now  # Still locked
    ).first()


def create_circuit_breaker_event(
    db: Session,
    profile_name: str,
    reason: str,
    trigger_value_pct: Decimal,
    balance_at_trigger: Decimal,
    daily_start_balance: Decimal,
    lock_hours: int
) -> CircuitBreakerEvent:
    """Create a new circuit breaker trigger event"""
    now = datetime.now(timezone.utc)
    reset_time = now + timedelta(hours=lock_hours)
    
    event = CircuitBreakerEvent(
        profile_name=profile_name,
        reason=reason,
        trigger_value_pct=trigger_value_pct,
        balance_at_trigger=balance_at_trigger,
        daily_start_balance=daily_start_balance,
        triggered_at=now,
        reset_at=reset_time,
        is_active=True
    )
    
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def expire_circuit_breaker(
    db: Session,
    event_id: int
) -> CircuitBreakerEvent:
    """Mark a circuit breaker as expired/inactive"""
    event = db.query(CircuitBreakerEvent).filter(
        CircuitBreakerEvent.id == event_id
    ).first()
    
    if not event:
        raise ValueError(f"Circuit breaker event {event_id} not found")
    
    event.is_active = False
    db.commit()
    db.refresh(event)
    return event


def manually_reset_circuit_breaker(
    db: Session,
    profile_name: str
) -> Optional[CircuitBreakerEvent]:
    """Manually reset active circuit breaker"""
    event = get_active_circuit_breaker(db, profile_name)
    
    if not event:
        return None
    
    event.is_active = False
    event.manually_reset_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(event)
    return event


# ===== Daily Balance Snapshots =====

def get_current_daily_snapshot(
    db: Session,
    profile_name: str
) -> Optional[DailyBalanceSnapshot]:
    """Get the latest snapshot"""
    
    return db.query(DailyBalanceSnapshot).filter(
        DailyBalanceSnapshot.profile_name == profile_name
    ).order_by(DailyBalanceSnapshot.snapshot_date.desc()).first()


def create_daily_snapshot(
    db: Session,
    profile_name: str,
    starting_balance: Decimal
) -> DailyBalanceSnapshot:
    """Create a new daily snapshot"""
    snapshot = DailyBalanceSnapshot(
        profile_name=profile_name,
        snapshot_date=datetime.now(timezone.utc),
        starting_balance=starting_balance,
        highest_balance=starting_balance,
        lowest_balance=starting_balance,
        circuit_breaker_baseline=None
    )
    
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot

def update_daily_snapshot(
    db: Session,
    snapshot_id: int,
    current_balance: Decimal
) -> DailyBalanceSnapshot:
    """Update snapshot with current balance (track high/low)"""
    snapshot = db.query(DailyBalanceSnapshot).filter(
        DailyBalanceSnapshot.id == snapshot_id
    ).first()
    
    if not snapshot:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    
    # Update high/low
    if current_balance > (snapshot.highest_balance or 0):
        snapshot.highest_balance = current_balance
    
    if current_balance < (snapshot.lowest_balance or float('inf')):
        snapshot.lowest_balance = current_balance
    
    db.commit()
    db.refresh(snapshot)
    return snapshot


def finalize_daily_snapshot(
    db: Session,
    snapshot_id: int,
    ending_balance: Decimal
) -> DailyBalanceSnapshot:
    """Finalize a snapshot when 24h period ends"""
    snapshot = db.query(DailyBalanceSnapshot).filter(
        DailyBalanceSnapshot.id == snapshot_id
    ).first()
    
    if not snapshot:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    
    snapshot.ending_balance = ending_balance
    snapshot.pnl = ending_balance - snapshot.starting_balance
    snapshot.pnl_pct = (snapshot.pnl / snapshot.starting_balance) * 100
    
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_snapshot_history(
    db: Session,
    profile_name: str,
    limit: int = 30
) -> List[DailyBalanceSnapshot]:
    """Get historical snapshots"""
    return db.query(DailyBalanceSnapshot).filter(
        DailyBalanceSnapshot.profile_name == profile_name
    ).order_by(DailyBalanceSnapshot.snapshot_date.desc()).limit(limit).all()


def reset_circuit_breaker_baseline(
    db: Session,
    snapshot_id: int,
    new_baseline: Decimal
) -> DailyBalanceSnapshot:
    """
    Reset the circuit breaker baseline for a snapshot
    
    This updates circuit_breaker_baseline while keeping starting_balance intact
    for historical tracking. Used when profit limits expire to prevent re-triggering.
    
    Args:
        db: Database session
        snapshot_id: Snapshot to update
        new_baseline: New circuit breaker baseline
        
    Returns:
        Updated snapshot
    """
    snapshot = db.query(DailyBalanceSnapshot).filter(
        DailyBalanceSnapshot.id == snapshot_id
    ).first()
    
    if not snapshot:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    
    # Update circuit breaker baseline (starting_balance stays unchanged for historical tracking)
    snapshot.circuit_breaker_baseline = new_baseline
    
    # Also update highest/lowest if needed
    if new_baseline > (snapshot.highest_balance or 0):
        snapshot.highest_balance = new_baseline
    
    if new_baseline < (snapshot.lowest_balance or float('inf')):
        snapshot.lowest_balance = new_baseline
    
    db.commit()
    db.refresh(snapshot)
    
    return snapshot

def get_recently_expired_circuit_breaker(
    db: Session,
    profile_name: str,
    grace_period_seconds: int = 300  # 5 minutes
) -> Optional[CircuitBreakerEvent]:
    """
    Get a circuit breaker that recently expired but hasn't been marked inactive yet
    
    This catches breakers that expired between monitoring cycles so we can:
    1. Mark them as inactive
    2. Reset circuit_breaker_baseline for profit limits
    
    Args:
        db: Database session
        profile_name: Trading profile name
        grace_period_seconds: How far back to look for expired events (default 5 min)
        
    Returns:
        Recently expired breaker event, or None
    """
    now = datetime.now(timezone.utc)
    grace_period = timedelta(seconds=grace_period_seconds)
    
    return db.query(CircuitBreakerEvent).filter(
        CircuitBreakerEvent.profile_name == profile_name,
        CircuitBreakerEvent.is_active == True,  # Still marked active
        CircuitBreakerEvent.reset_at <= now,  # But already expired
        CircuitBreakerEvent.reset_at >= now - grace_period  # Within grace period
    ).order_by(CircuitBreakerEvent.reset_at.desc()).first()

# Add to db/crud.py

def get_symbol_config(db: Session, profile_name: str, symbol: str) -> Optional[SymbolConfig]:
    """Get symbol-specific configuration"""
    return db.query(SymbolConfig).filter(
        SymbolConfig.profile_name == profile_name,
        SymbolConfig.symbol == symbol,
        SymbolConfig.enabled == True
    ).first()


def upsert_symbol_config(
    db: Session,
    profile_name: str,
    symbol: str,
    order_size_usdc: float,  # Required
    max_position_size_pct: Optional[float] = None,
    enabled: bool = True
) -> SymbolConfig:
    """Create or update symbol configuration"""
    config = get_symbol_config(db, profile_name, symbol)

    if config:
        # Update existing
        config.order_size_usdc = Decimal(str(order_size_usdc))
        if max_position_size_pct is not None:
            config.max_position_size_pct = Decimal(str(max_position_size_pct))
        config.enabled = enabled
        config.updated_at = datetime.utcnow()
    else:
        # Create new
        config = SymbolConfig(
            profile_name=profile_name,
            symbol=symbol,
            order_size_usdc=Decimal(str(order_size_usdc)),
            max_position_size_pct=Decimal(str(max_position_size_pct)) if max_position_size_pct else None,
            enabled=enabled
        )
        db.add(config)

    db.commit()
    db.refresh(config)
    return config


def get_all_symbol_configs(db: Session, profile_name: str) -> List[SymbolConfig]:
    """Get all symbol configs for a profile"""
    return db.query(SymbolConfig).filter(
        SymbolConfig.profile_name == profile_name,
        SymbolConfig.enabled == True
    ).all()


def delete_symbol_config(db: Session, profile_name: str, symbol: str) -> bool:
    """Delete (disable) a symbol configuration"""
    config = get_symbol_config(db, profile_name, symbol)
    if config:
        config.enabled = False
        db.commit()
        return True
    return False

def get_active_symbols(db: Session) -> List[str]:
    """Get list of active symbols to monitor"""
    symbols = db.query(SymbolConfig.symbol).filter(SymbolConfig.enabled == True).distinct().all()
    return [s.symbol for s in symbols]

