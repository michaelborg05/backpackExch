# db/models.py
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, CheckConstraint, Boolean, Index, JSON, Float, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from utils.constants import TradeReason, PositionCloseReason



Base = declarative_base()

class TradingProfileDB(Base):
    """Database model for trading profiles"""
    __tablename__ = "trading_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    api_key = Column(String, nullable=False)
    secret = Column(String, nullable=False)
    
    # Position management
    take_profit_pct = Column(Numeric, nullable=True)
    stop_loss_pct = Column(Numeric, nullable=True)
    trailing_stop_pct = Column(Numeric, nullable=True)
    use_trailing_stop = Column(Boolean, default=False)
    
    # Risk management
    max_risk_pct = Column(Numeric, default=0.25)
    default_order_size_pct = Column(Numeric, default=5)
    max_position_size = Column(Numeric, nullable=True)
    
    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    profile_name = Column(String, index=True)
    order_id = Column(String, index=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    exchange = Column(String, default="backpack")
    reason = Column(String, default=TradeReason.MANUAL) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    reason_summary = Column(JSON, nullable=True)

    __table_args__ = (
        CheckConstraint("side IN ('BID', 'ASK')", name="valid_side"),
    )


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    profile_name = Column(String, index=True)
    symbol = Column(String, nullable=False)
    
    quantity = Column(Numeric(20, 8), nullable=False)  # Original quantity
    remaining_quantity = Column(Numeric(20, 8), nullable=False)  # Amount still open
    
    buy_trade_id = Column(Integer, ForeignKey('trades.id'), nullable=False)
    sell_trade_id = Column(Integer, ForeignKey('trades.id'), nullable=True)
    
    entry_price = Column(Numeric(20, 8), nullable=False)
    exit_price = Column(Numeric(20, 8), nullable=True)

    tp_price = Column(Numeric(20, 8), nullable=True)
    sl_price = Column(Numeric(20, 8), nullable=True)
    trailing_sl_price = Column(Numeric(20, 8), nullable=True)
    highest_price = Column(Numeric(20, 8), nullable=True)
    lowest_price = Column(Numeric(20, 8), nullable=True)

    trailing_stop_armed = Column(Boolean, default=False)
        
    profit = Column(Numeric(20, 8), nullable=True)
    status = Column(String, nullable=False)
    status = Column(String, default="OPEN")  # OPEN or CLOSED or PARTIALLY_CLOSED
    close_reason = Column(String, nullable=True) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True))

    buy_trade = relationship("Trade", foreign_keys=[buy_trade_id])
    sell_trade = relationship("Trade", foreign_keys=[sell_trade_id])

    __table_args__ = (
        CheckConstraint("status IN ('OPEN', 'CLOSED')", name="valid_status"),
        Index('ix_positions_profile_symbol_status', 'profile_name', 'symbol', 'status'),
        Index('ix_positions_opened_at', 'created_at'),
    )


class CircuitBreakerConfig(Base):
    """Circuit breaker configuration per profile"""
    __tablename__ = "circuit_breaker_config"
    
    id = Column(Integer, primary_key=True)
    profile_name = Column(String, nullable=False)
    
    # Limits
    max_daily_profit_pct = Column(Numeric(5, 2), default=5.0)
    max_daily_loss_pct = Column(Numeric(5, 2), default=2.0)
    
    # Lock durations (in hours)
    profit_lock_hours = Column(Integer, default=6)
    loss_lock_hours = Column(Integer, default=12)
    
    # Tracking window (hours for rolling window)
    tracking_window_hours = Column(Integer, default=24)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CircuitBreakerEvent(Base):
    """Circuit breaker trigger events - persistent log"""
    __tablename__ = "circuit_breaker_events"
    
    id = Column(Integer, primary_key=True)
    profile_name = Column(String, nullable=False, index=True)
    
    reason = Column(String, nullable=False)  # PROFIT_LIMIT, LOSS_LIMIT
    trigger_value_pct = Column(Numeric(10, 4), nullable=True)  # Actual % when triggered
    
    # Balance snapshot at trigger time
    balance_at_trigger = Column(Numeric(20, 8), nullable=True)
    daily_start_balance = Column(Numeric(20, 8), nullable=True)
    
    triggered_at = Column(DateTime(timezone=True), nullable=False, index=True)
    reset_at = Column(DateTime(timezone=True), nullable=False)
    manually_reset_at = Column(DateTime(timezone=True), nullable=True)
    
    is_active = Column(Boolean, default=True)  # False if expired or manually reset
    
    __table_args__ = (
        Index('ix_circuit_events_active', 'profile_name', 'is_active'),
    )


class DailyBalanceSnapshot(Base):
    """Daily balance snapshots for tracking rolling 24h performance"""
    __tablename__ = "daily_balance_snapshots"
    
    id = Column(Integer, primary_key=True)
    profile_name = Column(String, nullable=False, index=True)
    
    snapshot_date = Column(DateTime(timezone=True), nullable=False, index=True)  # Start of 24h period
    starting_balance = Column(Numeric(20, 8), nullable=False)
    
    circuit_breaker_baseline = Column(Numeric(20, 8), nullable=True)
    
    # Optional: track high/low during the period
    highest_balance = Column(Numeric(20, 8), nullable=True)
    lowest_balance = Column(Numeric(20, 8), nullable=True)
    
    # End of period summary (updated when period ends)
    ending_balance = Column(Numeric(20, 8), nullable=True)
    pnl = Column(Numeric(20, 8), nullable=True)
    pnl_pct = Column(Numeric(10, 4), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('ix_snapshots_profile_date', 'profile_name', 'snapshot_date'),
        # Prevent duplicate snapshots for same profile/date
        CheckConstraint('snapshot_date IS NOT NULL', name='valid_snapshot_date'),
    )

class SymbolConfig(Base):
    """Symbol-specific trading configuration per profile"""
    __tablename__ = "symbol_configs"

    id = Column(Integer, primary_key=True)
    profile_name = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)

    # Position sizing
    order_size_usdc = Column(Numeric(20, 2), nullable=True)  # Fixed dollar amount per order

    # Position limits (as % of total portfolio value)
    max_position_size_pct = Column(Numeric(5, 2), nullable=True)  # Max position as % of portfolio (0-100)

    # Control flags
    enabled = Column(Boolean, default=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Ensure unique symbol per profile
        Index('ix_symbol_configs_profile_symbol', 'profile_name', 'symbol', unique=True),
        # Check that order size is specified
        CheckConstraint(
            'order_size_usdc IS NOT NULL',
            name='check_order_size_specified'
        ),
    )

class TrendHistory(Base):
    """
    Stores trend indicator snapshots for cache warmup after deployments.
    Keeps last N entries per symbol/timeframe to rebuild historical context.
    """
    __tablename__ = "trend_history"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, index=True)
    
    # Core indicators (store as JSON for flexibility)
    trend_data = Column(JSON, nullable=False)
    
    # Denormalized for easier querying
    price = Column(Float, nullable=False)
    rsi = Column(Float, nullable=False)
    ema20 = Column(Float, nullable=False)
    ema50 = Column(Float, nullable=False)
    vwap = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    
    # Tracking
    indicators_changed = Column(Boolean, default=True)  # Was this a significant change?
    data_timestamp = Column(DateTime(timezone=True), nullable=False)  # When data was generated
    created_at = Column(DateTime(timezone=True), server_default=func.now())  # When saved to DB
    
    __table_args__ = (
        # Composite index for efficient lookups
        Index('ix_trend_history_symbol_timeframe_timestamp', 'symbol', 'timeframe', 'data_timestamp'),
        # Prevent exact duplicates
        UniqueConstraint('symbol', 'timeframe', 'data_timestamp', name='uq_trend_history_entry'),
    )
