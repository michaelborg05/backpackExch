from pydantic import BaseModel as PydanticBase
from typing import Optional as Opt, Any
 
 
class AIPromptCreate(PydanticBase):
    name: str
    strategy_type: Opt[str] = None
    profile_id: Opt[int] = None
    system_prompt: str
    is_active: bool = True
    is_default: bool = False
    notes: Opt[str] = None
 
 
class AIPromptUpdate(PydanticBase):
    name: Opt[str] = None
    strategy_type: Opt[str] = None
    profile_id: Opt[int] = None
    system_prompt: Opt[str] = None
    is_active: Opt[bool] = None
    is_default: Opt[bool] = None
    notes: Opt[str] = None