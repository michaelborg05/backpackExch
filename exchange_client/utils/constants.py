from enum import Enum

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