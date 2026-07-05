# db/models.py
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, CheckConstraint, Boolean, Index, JSON, Float, UniqueConstraint, Text, text
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from utils.constants import TradeReason, PositionCloseReason, StrategyType, TradingType
from sqlalchemy.dialects.postgresql import JSONB


Base = declarative_base()

class TradingProfileDB(Base):
    """Database model for trading profiles"""
    __tablename__ = "trading_profiles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    display_name = Column(String, unique=True, nullable=False, index=True)
    
    # Position management
    take_profit_pct = Column(Numeric, nullable=True)
    stop_loss_pct = Column(Numeric, nullable=True)
    trailing_stop_pct = Column(Numeric, nullable=True)
    use_trailing_stop = Column(Boolean, default=False)
    arm_trailing_stop_pct = Column(Numeric, nullable=True)

    # Risk management
    default_order_size_usdc = Column(Numeric, default=50)
    max_position_size_pct = Column(Numeric, nullable=True)
    max_open_positions = Column(Numeric, nullable=True)
    max_portfolio_exposure_pct = Column(Numeric, nullable=True)
    leverage_multiplier = Column(Float, nullable=False, default=1.0, server_default=text("1.0"))

    trading_type =  Column(String, server_default="rules_live")
    strategy_type = Column(String, default=StrategyType.TREND_FOLLOWING.value)
    market_type = Column(String, default="SPOT", server_default=text("'SPOT'"))  # "SPOT" | "PERP"
    
    # Timing & Signal Generation
    signal_cooldown_minutes = Column(Integer, default=15)
    sl_cooldown_minutes = Column(Integer, nullable=True)   # per-profile override; None = use global setting
    tp_cooldown_minutes = Column(Integer, nullable=True)   # per-profile override; None = use global setting
    max_open_positions_per_profile = Column(Integer, nullable=True)   # total concurrent open positions across all symbols for this profile; None = no cap
    min_signal_confidence = Column(Float, default=72.0)
    min_volume_ratio = Column(Float, default=1.0)
    
    # Filter Toggles
    use_market_regime_filter = Column(Boolean, default=True)
    use_trend_filter = Column(Boolean, default=True)
    use_entry_filter = Column(Boolean, default=True)
    use_atr_filter = Column(Boolean, default=False)
    enable_signal_generation = Column(Boolean, default=False, server_default=text("false"))
    
    # Logic Settings
    trend_timeframe = Column(String, default="60")
    entry_timeframe = Column(String, default="15")
    min_indicators_required = Column(Integer, default=3)
    min_entry_indicators_required = Column(Integer, default=6)
    
    max_position_hours = Column(Integer, nullable=True)
    use_trend_invalidation_exit = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    trend_invalidation_indicators = Column(String(24),  nullable=False, server_default=text("'entry'"))
    min_position_age_for_trend_check = Column(Integer, nullable=True)

    # Indicator group configs: {"group_id": {"require_all": bool, "hard_stop": bool}}
    trend_indicator_groups = Column(JSONB, nullable=True)
    entry_indicator_groups = Column(JSONB, nullable=True)
    exit_indicator_groups = Column(JSONB, nullable=True)

    min_exit_indicators_required = Column(Integer, default=2, server_default=text("2"))
    exit_timeframe = Column(String, nullable=True)

    # Relationship to Indicators
    indicators = relationship("IndicatorDB", back_populates="profile", cascade="all, delete-orphan")
    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    account_id = Column(
        Integer,
        ForeignKey("exchange_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    account = relationship("ExchangeAccount", back_populates="profiles")

class IndicatorDB(Base):
    __tablename__ = "indicators"
    
    id = Column(Integer, primary_key=True)
    profile_id = Column(Integer, ForeignKey("trading_profiles.id", ondelete="CASCADE"))
    
    category = Column(String)  # 'trend', 'entry', or 'exit'
    indicator_type = Column(String)  # 'ema_slope', 'rsi_overbought', etc.
    
    # Store all YAML 'params' here as JSON
    params = Column(JSON, nullable=False) 
    
    is_hard_stop = Column(Boolean, default=True)
    enabled = Column(Boolean, default=True)
    indicator_group = Column(String(64), nullable=True)
    
    profile = relationship("TradingProfileDB", back_populates="indicators")

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    profile_name = Column(String, index=True)
    order_id = Column(String, index=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    direction = Column(String, nullable=True)  # "LONG" | "SHORT"
    quantity = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    exchange = Column(String, default="backpack")
    reason = Column(String, default=TradeReason.MANUAL, server_default=text("'MANUAL'"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    signal_snapshot = Column(JSON, nullable=True)

    __table_args__ = (
        CheckConstraint("side IN ('BID', 'ASK')", name="valid_side"),
        CheckConstraint("direction IN ('LONG', 'SHORT') OR direction IS NULL", name="valid_trade_direction"),
    )


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    profile_name = Column(String, index=True)
    symbol = Column(String, nullable=False)
    
    direction = Column(String, nullable=True, server_default=text("'LONG'"))  # "LONG" | "SHORT"

    quantity = Column(Numeric(20, 8), nullable=False, server_default=text("0"))  # Original quantity
    remaining_quantity = Column(Numeric(20, 8), nullable=False, server_default=text("0"))  # Amount still open

    entry_trade_id = Column(Integer, ForeignKey('trades.id'), nullable=True)
    exit_trade_id = Column(Integer, ForeignKey('trades.id'), nullable=True)

    entry_price = Column(Numeric(20, 8), nullable=False, server_default=text("0"))
    exit_price = Column(Numeric(20, 8), nullable=True)

    tp_price = Column(Numeric(20, 8), nullable=True)
    sl_price = Column(Numeric(20, 8), nullable=True)
    trailing_sl_price = Column(Numeric(20, 8), nullable=True)
    highest_price = Column(Numeric(20, 8), nullable=True)
    lowest_price = Column(Numeric(20, 8), nullable=True)

    trailing_stop_armed = Column(Boolean, default=False, server_default=text("false"))

    # ── NEW: links this position back to the AI signal that triggered it ──────
    # Null for non-AI-AGENT profiles. Set in monitoring_service._execute_signal()
    # after the buy order is confirmed. Used by _execute_close() to resolve the
    # AI outcome in ai_signal_log.
    ai_log_id = Column(
        Integer,
        ForeignKey("ai_signal_log.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment='FK to ai_signal_log — set for AI_AGENT profile positions only'
    )

    profit = Column(Numeric(20, 8), nullable=True)
    status = Column(String, default="OPEN")  # OPEN or CLOSED or PARTIALLY_CLOSED
    close_reason = Column(String, nullable=True, server_default=text("'MANUAL'")) 
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True))

    entry_trade = relationship("Trade", foreign_keys=[entry_trade_id])
    exit_trade = relationship("Trade", foreign_keys=[exit_trade_id])

    __table_args__ = (
        CheckConstraint("status IN ('OPEN', 'CLOSED')", name="valid_status"),
        CheckConstraint("direction IN ('LONG', 'SHORT') OR direction IS NULL", name="valid_position_direction"),
        Index('ix_positions_profile_symbol_status', 'profile_name', 'symbol', 'status'),
        Index('ix_positions_opened_at', 'created_at'),
    )


class CircuitBreakerConfig(Base):
    """Circuit breaker configuration per profile"""
    __tablename__ = "circuit_breaker_config"
    
    id = Column(Integer, primary_key=True)
    profile_name = Column(String, nullable=False)
    account_id = Column(
        Integer,
        ForeignKey("exchange_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    # Limits
    max_daily_profit_pct = Column(Numeric(5, 2), default=5.0)
    max_daily_loss_pct = Column(Numeric(5, 2), default=2.0)
    
    # Lock durations (in hours)
    profit_lock_hours = Column(Integer, default=6)
    loss_lock_hours = Column(Integer, default=12)
    
    # Tracking window (hours for rolling window)
    tracking_window_hours = Column(Integer, default=24)

    # Consecutive stop-loss breaker (per profile, not per account):
    # pause new entries after N straight STOP_LOSS closes. NULL/0 = disabled.
    max_consecutive_stop_losses = Column(Integer, nullable=True)
    consecutive_sl_lock_hours = Column(Integer, default=24, server_default=text("24"))

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CircuitBreakerEvent(Base):
    """Circuit breaker trigger events - persistent log"""
    __tablename__ = "circuit_breaker_events"
    
    id = Column(Integer, primary_key=True)
    profile_name = Column(String, nullable=False, index=True)
    account_id = Column(
        Integer,
        ForeignKey("exchange_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    
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
    account_id = Column(
        Integer,
        ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Informational only — the canonical profile name for this account at creation time
    profile_name = Column(String, nullable=True, index=True)

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
        # Uniqueness enforced via partial index in migration (account_id + date)
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
    
    # Live price at time of signal (distinct from prev_candle close)
    price = Column(Float)

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


class AISignalLog(Base):
    """
    Logs every AI agent entry decision alongside the rule-based system decision
    made at the same moment. Used for shadow/paper comparison (Option C).

    Lifecycle:
      1. Row inserted at signal time with ai_decision + rules_decision.
      2. OutcomeResolver fills outcome_* columns once SL or TP is hit.
      3. signal_analytics.py queries this table for comparison reports.

    signal_source values:
      'SHADOW'  – both systems evaluated; only rules decision goes live
      'AI_LIVE' – AI decision promoted to live execution (future)
    """
    __tablename__ = "ai_signal_log"

    id = Column(Integer, primary_key=True)
    pair              = Column(String(20),  nullable=False, index=True)
    profile_name      = Column(String(50),  nullable=False, index=True)
    signal_source     = Column(String(10),  nullable=False, server_default="SHADOW")  # SHADOW | AI_LIVE
    candle_time       = Column(DateTime(timezone=True), nullable=False)
    timeframe         = Column(String(5),   nullable=False)
    timestamp         = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # ── 60m gate results ───────────────────────────────────────────────
    gate_60m_passed   = Column(Boolean, nullable=False)
    gate_60m_data     = Column(JSONB)   # RSI, trend direction, strength etc.

    # ── AI agent decision ──────────────────────────────────────────────
    ai_decision             = Column(String(10))   # ENTER | SKIP | WAIT
    ai_confidence           = Column(Numeric(4, 3))
    ai_reasoning            = Column(Text)
    ai_risk_flags           = Column(JSONB)
    ai_entry_price          = Column(Numeric(20, 8))
    ai_stop_loss            = Column(Numeric(20, 8))
    ai_take_profit          = Column(Numeric(20, 8))
    ai_position_size_pct    = Column(Numeric(5, 2))  # AI-suggested sizing (% of portfolio)

    # ── Rule-based system decision at the same moment ──────────────────
    rules_decision    = Column(String(10))          # ENTER | SKIP
    rules_entry_price = Column(Numeric(20, 8))

    # ── Outcome (filled in by OutcomeResolver after trade resolves) ────
    outcome_resolved      = Column(Boolean, server_default=text("false"), nullable=False, index=True)
    outcome_result        = Column(String(10))          # WIN | LOSS | BREAKEVEN | MISSED
    outcome_pnl_pct       = Column(Numeric(8, 4))
    outcome_exit_price    = Column(Numeric(20, 8))
    outcome_exit_time     = Column(DateTime(timezone=True))
    outcome_candles_held  = Column(Integer)

    # ── Raw context snapshot (for replay / debugging) ──────────────────
    context_snapshot  = Column(JSONB)

    __table_args__ = (
        CheckConstraint(
            "ai_decision IN ('ENTER', 'SKIP', 'WAIT')",
            name="valid_ai_decision"
        ),
        CheckConstraint(
            "rules_decision IN ('ENTER', 'SKIP')",
            name="valid_rules_decision"
        ),
        CheckConstraint(
            "outcome_result IN ('WIN', 'LOSS', 'BREAKEVEN', 'MISSED') OR outcome_result IS NULL",
            name="valid_outcome_result"
        ),
        Index('ix_ai_signal_log_pair_time',    'pair', 'timestamp'),
        Index('ix_ai_signal_log_unresolved',   'outcome_resolved', 'ai_decision'),
    )

    def __repr__(self):
        return (
            f"<AISignalLog id={self.id} pair={self.pair!r} "
            f"ai={self.ai_decision} rules={self.rules_decision} "
            f"outcome={self.outcome_result!r}>"
        )


class AIVsRulesStats(Base):
    """
    Materialised weekly comparison stats between the AI agent and the
    rule-based system. Populated by signal_analytics.weekly_summary_upsert().

    Keeps a rolling history so you can chart improvement over time.
    """
    __tablename__ = "ai_vs_rules_stats"

    id           = Column(Integer, primary_key=True)
    computed_at  = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end   = Column(DateTime(timezone=True), nullable=False)
    pair         = Column(String(20), nullable=False, index=True)
    profile_name = Column(String(50), nullable=False)

    # ── AI performance ─────────────────────────────────────────────────
    ai_total_signals      = Column(Integer)
    ai_entries_taken      = Column(Integer)
    ai_win_rate           = Column(Numeric(5, 2))
    ai_avg_rr             = Column(Numeric(6, 3))
    ai_avg_confidence     = Column(Numeric(4, 3))
    ai_skipped_correct    = Column(Integer)   # SKIP and price moved against
    ai_skipped_wrong      = Column(Integer)   # SKIP but would have been a win

    # ── Rule-based performance (same period) ───────────────────────────
    rules_total_signals   = Column(Integer)
    rules_win_rate        = Column(Numeric(5, 2))
    rules_avg_rr          = Column(Numeric(6, 3))

    # ── Delta (positive = AI better) ──────────────────────────────────
    win_rate_delta        = Column(Numeric(5, 2))
    rr_delta              = Column(Numeric(6, 3))

    __table_args__ = (
        Index('ix_ai_stats_pair_period', 'pair', 'period_start'),
    )

    def __repr__(self):
        return (
            f"<AIVsRulesStats pair={self.pair!r} "
            f"period={self.period_start} "
            f"wr_delta={self.win_rate_delta}>"
        )

class AIPrompt(Base):
    """
    Versioned, DB-backed system prompts for the AI signal agent.

    Resolution priority in ai_signal_handler (highest → lowest):
      1. Profile-specific   (profile_id matches AND strategy_type matches, is_active=True)
      2. Profile-only       (profile_id matches, is_active=True)
      3. Strategy-type only (strategy_type matches, is_active=True)
      4. Global default     (is_default=True, is_active=True)
      5. Hardcoded fallback in AISignalHandler (safety net — should never reach here)

    Only ONE prompt per (strategy_type, profile_id) combination should have
    is_default=True. The /ai-prompts/{id}/set-default endpoint enforces this.
    """
    __tablename__ = "ai_prompts"

    id            = Column(Integer, primary_key=True)
    name          = Column(String(128), nullable=False)
    strategy_type = Column(String(64),  nullable=True)   # None = applies to all strategies
    profile_id    = Column(Integer, ForeignKey("trading_profiles.id", ondelete="SET NULL"), nullable=True)
    system_prompt = Column(Text, nullable=False)
    is_active     = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_default    = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    version       = Column(Integer, nullable=False, server_default=text("1"))
    notes         = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    profile = relationship("TradingProfileDB", foreign_keys=[profile_id])

    __table_args__ = (
        Index('ix_ai_prompts_strategy_type', 'strategy_type'),
        Index('ix_ai_prompts_profile_id',    'profile_id'),
        Index('ix_ai_prompts_is_default',    'is_default'),
    )

    def __repr__(self):
        return (
            f"<AIPrompt id={self.id} name={self.name!r} "
            f"strategy={self.strategy_type!r} default={self.is_default}>"
        )


class ConfigAuditLog(Base):
    """
    Append-only audit trail for all configuration changes made via the UI or API.

    Records what changed, when, who changed it, and full before/after JSON snapshots.
    This lets you correlate config changes (indicators, prompts, profile settings)
    against bot performance on any given day.

    type values:    indicator | ai_prompt | profile | symbol_config
    subtype values: trend | entry | exit | mean_reversion | system | range | swing | …
    action values:  create | update | delete | toggle | set_default
    """
    __tablename__ = "config_audit_log"

    id          = Column(Integer, primary_key=True)
    changed_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    type        = Column(String(32),  nullable=False)   # indicator | ai_prompt | profile | symbol_config
    subtype     = Column(String(64),  nullable=True)    # trend | entry | mean_reversion | system …
    action      = Column(String(16),  nullable=False)   # create | update | delete | toggle | set_default

    entity_id   = Column(Integer,     nullable=True)    # PK of the affected row (NULL if deleted)
    entity_name = Column(String(256), nullable=True)    # Human-readable label for the UI

    changed_by  = Column(String(64),  nullable=False, default="web_ui")

    before      = Column(JSONB, nullable=True)           # Snapshot of state BEFORE change
    after       = Column(JSONB, nullable=True)           # Snapshot of state AFTER change

    __table_args__ = (
        Index('ix_audit_changed_at',   'changed_at'),
        Index('ix_audit_type_subtype', 'type', 'subtype'),
        Index('ix_audit_entity',       'entity_id', 'type'),
    )

    def __repr__(self):
        return (
            f"<ConfigAuditLog id={self.id} type={self.type!r} "
            f"action={self.action!r} entity={self.entity_name!r} "
            f"at={self.changed_at}>"
        )

class MonitoredSymbol(Base):
    """Global allowlist of symbols the system actively monitors for trend data."""
    __tablename__ = "monitored_symbols"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, unique=True, nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProfileTradingHours(Base):
    """
    Allowed trading windows per profile, per day of week (UTC).

    If no enabled rows exist for a profile on the current day, the profile
    is considered outside its trading hours and signal generation is skipped.
    If the table has no rows at all for a profile, all hours are permitted.
    """
    __tablename__ = "profile_trading_hours"

    id = Column(Integer, primary_key=True)
    profile_id = Column(
        Integer,
        ForeignKey("trading_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_of_week = Column(Integer, nullable=False)   # 0=Monday … 6=Sunday
    start_time = Column(String(5), nullable=False)  # "HH:MM" UTC
    end_time = Column(String(5), nullable=False)    # "HH:MM" UTC
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExchangeAccount(Base):
    __tablename__ = "exchange_accounts"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)       # e.g. "main_account"
    exchange_type = Column(String, nullable=False, default="backpack")  # "backpack" | "bullet"
    api_key = Column(String, nullable=False)                 # Encrypted (Backpack: API key, Bullet: delegate address)
    secret = Column(String, nullable=False)                  # Encrypted (Backpack: secret, Bullet: Ed25519 private key)
    wallet_address = Column(String, nullable=True)          # Encrypted (Bullet: wallet address - Use main wallet for read operations)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    profiles = relationship("TradingProfileDB", back_populates="account")


class WebhookPriceTick(Base):
    __tablename__ = "webhook_price_ticks"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    price = Column(Numeric, nullable=False)