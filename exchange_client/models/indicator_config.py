from pydantic import BaseModel
from typing import Any

class IndicatorCreate(BaseModel):
    category: str           # 'trend' | 'entry' | 'exit'
    indicator_type: str
    params: dict[str, Any]
    is_hard_stop: bool = True
    enabled: bool = True

class IndicatorUpdate(BaseModel):
    """Full replace — all fields required (id/profile_id are path params)."""
    category: str
    indicator_type: str
    params: dict[str, Any]
    is_hard_stop: bool
    enabled: bool

class IndicatorOut(BaseModel):
    id: int
    profile_id: int
    category: str
    indicator_type: str
    params: dict[str, Any]
    is_hard_stop: bool
    enabled: bool

    class Config:
        from_attributes = True