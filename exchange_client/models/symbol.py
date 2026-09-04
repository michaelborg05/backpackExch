from typing import List, Optional

from pydantic import BaseModel

class SymbolConfigRequest(BaseModel):
    """Request model for symbol configuration"""
    order_size_usdc: float  # Required - fixed dollar amount per order
    max_position_size_pct: float  # Required - max position as % of portfolio
    enabled: bool = True


class BulkSymbolConfigRequest(BaseModel):
    """Request model for updating several symbol configs at once.

    Only the fields that are supplied are applied — anything left unset keeps
    its current per-symbol value, so you can push one order size across a
    dozen symbols without flattening their max position sizes.
    """
    symbols: List[str]
    order_size_usdc: Optional[float] = None
    max_position_size_pct: Optional[float] = None
    enabled: Optional[bool] = None
