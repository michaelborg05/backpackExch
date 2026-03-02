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
    display_name = Column(String, unique=True, nullable=False, index=True)
    api_key = Column(String, nullable=False)
    secret = Column(String, nullable=False)
    
    # Position management
    take_profit_pct = Column(Numeric, nullable=True)
    stop_loss_pct = Column(Numeric, nullable=True)
    trailing_stop_pct = Column(Numeric, nullable=True)
    use_trailing_stop = Column(Boolean, default=False)
    arm_trailing_stop_pct = Column(Numeric, nullable=True)

    # Risk management
    max_risk_pct = Column(Numeric, default=0.25)
    default_order_size_usdc = Column(Numeric, default=50)
    max_position_size_pct = Column(Numeric, nullable=True)
    max_open_positions = Column(Numeric, nullable=True)
    max_portfolio_exposure_pct = Column(Numeric, nullable=True)
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
    adx = Column(Float, nullable=True)
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

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True)
    profile_name = Column(String, nullable=False, index=True)
    position_id = Column(Integer, ForeignKey('positions.id'), nullable=True, index=True)
    
    # Order details
    exchange_order_id = Column(String, unique=True, index=True)  # Backpack's order ID
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)  # BID/ASK
    exchange = Column(String, default="backpack")
    
    quantity = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8), nullable=True)  # NULL for market orders
    
    # Lifecycle
    status = Column(String, nullable=False, default="PENDING")  # PENDING, FILLED, PARTIALLY_FILLED, CANCELLED, REJECTED, EXPIRED
    purpose = Column(String, nullable=False)  # TAKE_PROFIT, STOP_LOSS, TRAILING_STOP, ENTRY
    
    # Execution tracking
    filled_quantity = Column(Numeric(20, 8), default=0)
    average_fill_price = Column(Numeric(20, 8), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    filled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    position = relationship("Position", backref="orders")
    trade_id = Column(Integer, ForeignKey('trades.id'), nullable=True)  # Link when filled
    
    __table_args__ = (
        CheckConstraint("side IN ('BID', 'ASK')", name="valid_order_side"),
        CheckConstraint("purpose IN ('TAKE_PROFIT', 'STOP_LOSS', 'TRAILING_STOP', 'ENTRY')", name="valid_order_purpose"),
        Index('ix_orders_status_profile', 'status', 'profile_name'),
    )

class TradeValidationResults(Base):
    __tablename__ = "trade_validation_results"

    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trades.id'), nullable=False)
    profile_name = Column(String, nullable=False)
    side = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    validation_summary = Column(String)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_trade_validation_results_trade', 'trade_id'),
    )
    
    def get_validation_result(self):
        """Parse validation_summary into structured object"""
        if self.validation_summary:
            import json
            from models.signal_validation import SignalValidationResult
            data = json.loads(self.validation_summary)
            return SignalValidationResult.from_dict(data)
        return None

# Add this to db/models.py

class Settings(Base):
    """
    Global and profile-specific settings storage.
    Replaces hardcoded config values with database-driven settings.
    
    Key features:
    - profile_name = '0' means applies to ALL profiles (global setting)
    - profile_name = 'specific_profile' means applies to that profile only
    - Settings can be updated without restarting the system (via cache refresh)
    """
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True)
    profile_name = Column(String, nullable=False, index=True, default='0')  # '0' = global, else specific profile
    setting_name = Column(String, nullable=False, index=True)
    value = Column(String, nullable=False)  # Store as string, parse on retrieval
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        # Ensure unique setting per profile
        UniqueConstraint('profile_name', 'setting_name', name='uq_settings_profile_name'),
        
    )
    
    def get_value_as_int(self) -> int:
        """Parse value as integer"""
        return int(self.value)
    
    def get_value_as_float(self) -> float:
        """Parse value as float"""
        return float(self.value)
    
    def get_value_as_bool(self) -> bool:
        """Parse value as boolean"""
        return self.value.lower() in ('true', '1', 'yes', 'on')
    
    def get_value_as_str(self) -> str:
        """Return value as string"""
        return self.value
    
# db/models.py

class TrendAnalysisLog(Base):
    """
    Longer-term storage (48-72h) for pattern analysis.
    Stores OHLC and Indicators as flat columns.
    """
    __tablename__ = "trend_analysis_log"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    timeframe = Column(String, nullable=False, index=True)
    
    # OHLC Data (from prev_candle)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    
    # Indicators
    rsi = Column(Float)
    ema20 = Column(Float)
    ema50 = Column(Float)
    vwap = Column(Float)
    bb_upper = Column(Float)
    bb_lower = Column(Float)
    bb_basis = Column(Float)
    volume = Column(Float)
    volume_ratio = Column(Float)
    volume_sma = Column(Float)
    adx = Column(Float, nullable=True)
    
    # Explicitly store the TV bar timestamp and the DB arrival time
    timestamp = Column(DateTime(timezone=True), index=True) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_trend_log_lookup', 'symbol', 'timeframe', 'timestamp'),
    )


"""
Database models for web dashboard user authentication.

Two new tables:
  - AppUser           : Web dashboard accounts (username, bcrypt password hash, role)
  - UserProfileMapping: Which trading profiles each user can access

Intentionally kept separate from the trading models so auth concerns
don't bleed into trading logic. Import alongside models.py in your
Alembic env.py or session setup.

Migration steps:
    1. Import this file in your Alembic env.py target_metadata
    2. Run: alembic revision --autogenerate -m "add app users"
    3. Run: alembic upgrade head

Or if you're not using Alembic yet, call Base.metadata.create_all(engine)
after importing both models.py and auth_models.py.
"""



class AppUser(Base):
    """
    Web dashboard user account.

    Roles:
        admin   – full access to all endpoints + user management
        viewer  – read-only access (no trade execution)

    Passwords are stored as bcrypt hashes (60-char string).
    NEVER store plaintext here.

    Usage:
        user = AppUser(username="michael", role="admin")
        user.set_password("my-secure-password")  # hashes automatically
        db.add(user)
        db.commit()
    """
    __tablename__ = "app_user"

    id           = Column(Integer, primary_key=True)
    username     = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)          # bcrypt hash
    display_name = Column(String(128), nullable=True)
    email        = Column(String(256), nullable=True, unique=True)
    role         = Column(String(32), nullable=False, default="viewer")   # admin | viewer
    is_active    = Column(Boolean, default=True, nullable=False)

    # Soft audit trail
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    profile_mappings = relationship(
        "UserProfileMapping",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'viewer')", name="valid_app_user_role"),
    )

    # ── Password helpers ─────────────────────────────────────────────
    def set_password(self, plain_password: str) -> None:
        """Hash and store a plaintext password using bcrypt."""
        import bcrypt
        self.password_hash = bcrypt.hashpw(
            plain_password.encode("utf-8"),
            bcrypt.gensalt(rounds=12)
        ).decode("utf-8")

    def verify_password(self, plain_password: str) -> bool:
        """
        Verify a plaintext password against the stored hash.
        Returns True if correct, False otherwise.
        bcrypt.checkpw is constant-time — safe against timing attacks.
        """
        import bcrypt
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                self.password_hash.encode("utf-8")
            )
        except Exception:
            return False

    # ── Convenience ──────────────────────────────────────────────────
    @property
    def accessible_profiles(self) -> list[str]:
        """Return list of profile_names this user can access."""
        return [m.profile_name for m in self.profile_mappings if m.is_active]

    def can_access_profile(self, profile_name: str) -> bool:
        return profile_name in self.accessible_profiles

    def __repr__(self):
        return f"<AppUser id={self.id} username={self.username!r} role={self.role!r}>"


class UserProfileMapping(Base):
    """
    Maps an AppUser to the trading profiles they can access.

    One user can be linked to many profiles.
    One profile can be linked to many users (e.g., two admins watching the same profile).

    Example rows:
        user_id=1, profile_name="default"
        user_id=1, profile_name="MB15m"
        user_id=1, profile_name="aggressive"
        user_id=2, profile_name="aggressive"   # second user, read-only on aggressive
    """
    __tablename__ = "app_user_mappings"

    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    profile_name = Column(String(128), nullable=False)   # matches TradingProfileDB.profile_name
    is_active    = Column(Boolean, default=True, nullable=False)

    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationship back to user
    user = relationship("AppUser", back_populates="profile_mappings")

    __table_args__ = (
        # A user can only be mapped to the same profile once
        UniqueConstraint("user_id", "profile_name", name="uq_user_profile"),
        Index("ix_user_profile_mappings_user", "user_id"),
        Index("ix_user_profile_mappings_profile", "profile_name"),
    )

    def __repr__(self):
        return (
            f"<UserProfileMapping user_id={self.user_id} "
            f"profile={self.profile_name!r} active={self.is_active}>"
        )
