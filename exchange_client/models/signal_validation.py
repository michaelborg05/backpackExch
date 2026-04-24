from typing import Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class IndicatorResult:
    type: str
    is_bullish: bool
    config: Dict[str, Any]
    values: Dict[str, Any]
    message: str

    def to_dict(self) -> dict:
        return asdict(self)
