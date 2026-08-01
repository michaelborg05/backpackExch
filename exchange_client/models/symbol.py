from pydantic import BaseModel

class SymbolConfigRequest(BaseModel):
    """Request model for symbol configuration"""
    order_size_usdc: float  # Required - fixed dollar amount per order
    max_position_size_pct: float  # Required - max position as % of portfolio
    enabled: bool = True