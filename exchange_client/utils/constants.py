from enum import Enum
import enum

class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    DELETE = "DELETE"

# Enums
class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class Side(str, Enum):
    BID = "Bid"
    ASK = "Ask"

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
    EXPIRED = "Expired"
    PARTIALLY_FILLED = "PartiallyFilled"
    TRIGGER_PENDING = "TriggerPending"
    TRIGGER_FAILED = "TriggerFailed"


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

class OrderStatus(str,enum.Enum):
    FILLED = "Filled"
    CANCELLED = "Cancelled"
    EXPIRED = "Expired"
    NEW = "New"
    PARTIALLY_FILLED = "PartiallyFilled"
    TRIGGER_PENDING = "TriggerPending"
    TRIGGER_FAILED = "TriggerFailed"

class ExpiryReason(str, Enum):
    ACCOUNT_TRADING_SUSPENDED = "AccountTradingSuspended"
    BORROW_REQUIRES_LEND_REDEEM = "BorrowRequiresLendRedeem"
    FILL_OR_KILL = "FillOrKill"
    INSUFFICIENT_BORROWABLE_QUANTITY = "InsufficientBorrowableQuantity"
    INSUFFICIENT_FUNDS = "InsufficientFunds"
    INSUFFICIENT_LIQUIDITY = "InsufficientLiquidity"
    INVALID_PRICE = "InvalidPrice"
    INVALID_QUANTITY = "InvalidQuantity"
    IMMEDIATE_OR_CANCEL = "ImmediateOrCancel"
    INSUFFICIENT_MARGIN = "InsufficientMargin"
    LIQUIDATION = "Liquidation"
    NEGATIVE_EQUITY = "NegativeEquity"
    POST_ONLY_MODE = "PostOnlyMode"
    POST_ONLY_TAKER = "PostOnlyTaker"
    PRICE_OUT_OF_BOUNDS = "PriceOutOfBounds"
    REDUCE_ONLY_NOT_REDUCED = "ReduceOnlyNotReduced"
    SELF_TRADE_PREVENTION = "SelfTradePrevention"
    STOP_WITHOUT_POSITION = "StopWithoutPosition"
    PRICE_IMPACT = "PriceImpact"
    UNKNOWN = "Unknown"
    USER_PERMISSIONS = "UserPermissions"
    MAX_STOP_ORDERS_PER_POSITION = "MaxStopOrdersPerPosition"
    POSITION_LIMIT = "PositionLimit"
    SLIPPAGE_TOLERANCE_EXCEEDED = "SlippageToleranceExceeded"

class SystemOrderType(str, Enum):
    COLLATERAL_CONVERSION = "CollateralConversion"
    FUTURE_EXPIRY = "FutureExpiry"
    LIQUIDATE_POSITION_ON_ADL = "LiquidatePositionOnAdl"
    LIQUIDATE_POSITION_ON_BOOK = "LiquidatePositionOnBook"
    LIQUIDATE_POSITION_ON_BACKSTOP = "LiquidatePositionOnBackstop"
    ORDER_BOOK_CLOSED = "OrderBookClosed"

class MarketRegime(Enum):
    """Market regime classification"""
    SAFE = "safe"               # ✅ Safe to trade
    CHOPPY = "choppy"           # ⚠️ Whipsaw risk - wait for clarity
    HIGH_RISK = "high_risk"     # 🚫 Dangerous - don't trade
    EXPANDING = "expanding"     # 🚀 Strong momentum - best entries

class TrendState(Enum):
    """Trend health state for each timeframe"""
    EXPANDING = "expanding"     # Trend strengthening
    HEALTHY = "healthy"         # Trend stable
    DECAYING = "decaying"       # Trend weakening
    BROKEN = "broken"          # Trend failed

class StrategyType(Enum):
    """Trading strategy types"""
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"

