# db/models.py
from sqlalchemy import Column, Integer, String, Numeric, TIMESTAMP, ForeignKey, CheckConstraint, Boolean
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
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    profile_name = Column(String, index=True)
    order_id = Column(String, index=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    quantity = Column(Numeric, nullable=False)
    price = Column(Numeric, nullable=False)
    exchange = Column(String, default="backpack")
    reason = Column(String, default=TradeReason.MANUAL) 
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        CheckConstraint("side IN ('BID', 'ASK')", name="valid_side"),
    )


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    profile_name = Column(String, index=True)
    symbol = Column(String, nullable=False)
    buy_trade_id = Column(Integer, ForeignKey("trades.id"))
    sell_trade_id = Column(Integer, ForeignKey("trades.id"))
    tp_price = Column(Numeric, nullable=True)
    sl_price = Column(Numeric, nullable=True)
    trailing_sl_price = Column(Numeric, nullable=True)
    highest_price = Column(Numeric(precision=20, scale=8), nullable=True)
    profit = Column(Numeric(precision=20, scale=8), nullable=True)
    status = Column(String, nullable=False)
    status = Column(String, default="OPEN")  # OPEN or CLOSED
    close_reason = Column(String, nullable=True) 
    created_at = Column(TIMESTAMP, server_default=func.now())
    closed_at = Column(TIMESTAMP)

    buy_trade = relationship("Trade", foreign_keys=[buy_trade_id])
    sell_trade = relationship("Trade", foreign_keys=[sell_trade_id])

    __table_args__ = (
        CheckConstraint("status IN ('OPEN', 'CLOSED')", name="valid_status"),
    )
