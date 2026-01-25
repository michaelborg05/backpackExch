from enum import Enum
import enum

class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    DELETE = "DELETE"

# Enums
class Side(str, Enum):
    BID = "Bid"
    ASK = "Ask"


class OrderType(str, Enum):
    MARKET = "Market"
    LIMIT = "Limit"


class TimeInForce(str, Enum):
    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill


class SelfTradePrevention(str, Enum):
    REJECT_TAKER = "RejectTaker"
    REJECT_MAKER = "RejectMaker"
    REJECT_BOTH = "RejectBoth"


class OrderStatus(str, Enum):
    CANCELLED = "Cancelled"
    FILLED = "Filled"
    NEW = "New"


class SlippageToleranceType(str, Enum):
    TICK_SIZE = "TickSize"
    PERCENT = "Percent"


class MarketType(str, Enum):
    SPOT = "SPOT"
    PERP = "PERP"
    IPERP = "IPERP"
    DATED = "DATED"
    PREDICTION = "PREDICTION"
    RFQ = "RFQ"


class MessagePriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

class TradeReason(str, enum.Enum):
    """Reasons for trade execution"""
    MANUAL = "MANUAL"
    WEBHOOK = "WEBHOOK"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    STRATEGY = "STRATEGY"
    API = "API"
    TREND_INVALIDATION = "TREND_INVALIDATION"
    STALE_POSITION = "STALE_POSITION"
    
class PositionCloseReason(str, enum.Enum):
    """Reasons for position closure"""
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    MANUAL = "MANUAL"
    INVALID_POSITION = "INVALID_POSITION"  # Position exists but token was sold
    FORCE_CLOSE = "FORCE_CLOSE"
    TREND_INVALIDATION = "TREND_INVALIDATION"
    STALE_POSITION = "STALE_POSITION"
