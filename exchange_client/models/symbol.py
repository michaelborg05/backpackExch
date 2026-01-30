from pydantic import BaseModel
from typing import Optional

class SymbolConfigRequest(BaseModel):
    """Request model for symbol configuration"""
    order_size_usdc: float  # Required - fixed dollar amount per order
    max_position_size_pct: Optional[float] = None  # Max position as % of portfolio
    enabled: bool = True