from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class IndicatorResult(BaseModel):
    indicator_type: str
    passed: bool
    value1: str = None
    value2: str = None
    threshold: str = None
    details: str  # The human-readable part (e.g., "88.01 vs 87.43")
    params: Dict[str, Any] # Store the YAML params used

class TimeframeSummary(BaseModel):
    timeframe: str
    passed: bool
    score: str  # e.g., "4/5"
    indicators: List[IndicatorResult]

