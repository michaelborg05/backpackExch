from dataclasses import dataclass


@dataclass
class TradingProfile:
    name: str
    api_key: str
    secret: str
    max_risk_pct: float
    default_order_size_pct: float
