from typing import Optional
from pydantic import BaseModel


class SignalSnapshot(BaseModel):
    timeframe: str
    price: Optional[float] = None
    rsi: Optional[float] = None
    rsi_direction: Optional[str] = None
    rsi_delta: Optional[float] = None
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    ema20_slope: Optional[float] = None
    ema20_direction: Optional[str] = None
    volume_ratio: Optional[float] = None
    adx: Optional[float] = None
    bb_pct_b: Optional[float] = None
    score: Optional[float] = None  # entry signals only

    @classmethod
    def build(cls, trend, timeframe: str, ema20_slope, ema20_dir, rsi_delta, rsi_dir, pct_b=None, score=None) -> "SignalSnapshot":
        return cls(
            timeframe=timeframe,
            price=float(trend.price) if trend else None,
            rsi=round(float(trend.rsi), 1) if trend else None,
            rsi_direction=rsi_dir,
            rsi_delta=round(rsi_delta, 2) if rsi_delta is not None else None,
            ema20=round(float(trend.ema20), 4) if trend else None,
            ema50=round(float(trend.ema50), 4) if trend else None,
            ema20_slope=round(ema20_slope, 4) if ema20_slope is not None else None,
            ema20_direction=ema20_dir,
            volume_ratio=round(float(trend.volume_ratio), 2) if trend and trend.volume_ratio else None,
            adx=round(float(trend.adx), 1) if trend and trend.adx else None,
            bb_pct_b=round(pct_b, 3) if pct_b is not None else None,
            score=round(score, 1) if score is not None else None,
        )
