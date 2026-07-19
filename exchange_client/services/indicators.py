"""Indicator implementations validated against TradingView.

Every function here was checked against the TV values already stored in
trend_analysis_log (15m, ~2150 candles/symbol, SOL/BTC/ETH/XRP, Jul 2026).
Median absolute error vs TV:

    ema          0.0000%     standard, k = 2/(n+1)
    bollinger    0.0000%     SMA20 +/- 2 * population stdev
    rsi          0.0053%     Wilder's smoothing
    adx          0.0133%     Wilder's with RMA smoothing
    vwap         0.0098%     session-anchored, UTC midnight reset, (H+L+C)/3
    volume_sma   0.0000%     SMA20 of volume

Do not "improve" these implementations without re-running Tools/validate_indicators.py.
Two specifics that are load-bearing:

  * VWAP MUST be session-anchored. Rolling variants were 20-40x worse
    (rolling-96 0.38%, rolling-20 0.27%) — on a ~0.35%/trade edge with
    price_vs_vwap as an entry gate that is the size of the entire edge.

  * RSI and ADX are Wilder recursions: they drift when candles are missing.
    Feed them contiguous data. ADX gates at 22/25/30, and the observed p95
    error on gappy data was 1.4-3.5%, which is enough to flip a gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Sequence

Num = Optional[float]


def ema(values: Sequence[float], period: int, seed: Optional[float] = None) -> List[Num]:
    """Standard EMA, k = 2/(period+1). Seeded with the SMA of the first `period`."""
    out: List[Num] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    cur = seed if seed is not None else sum(values[:period]) / period
    out[period - 1] = cur
    for i in range(period, len(values)):
        cur = values[i] * k + cur * (1 - k)
        out[i] = cur
    return out


def sma(values: Sequence[float], period: int) -> List[Num]:
    out: List[Num] = [None] * len(values)
    if len(values) < period:
        return out
    run = sum(values[:period])
    out[period - 1] = run / period
    for i in range(period, len(values)):
        run += values[i] - values[i - period]
        out[i] = run / period
    return out


def rsi(closes: Sequence[float], period: int = 14) -> List[Num]:
    """Wilder's RSI — matches TradingView ta.rsi."""
    out: List[Num] = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
        period: int = 14) -> List[Num]:
    """Wilder's ADX with RMA smoothing — matches TradingView ta.adx."""
    n = len(closes)
    out: List[Num] = [None] * n
    if n < period * 2 + 1:
        return out

    trs: List[float] = []
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))

    atr = sum(trs[:period]) / period
    s_plus = sum(plus_dm[:period]) / period
    s_minus = sum(minus_dm[:period]) / period

    dx_seen = 0
    adx_val: Optional[float] = None
    dx_sum = 0.0
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        s_plus = (s_plus * (period - 1) + plus_dm[i]) / period
        s_minus = (s_minus * (period - 1) + minus_dm[i]) / period
        if atr == 0:
            continue
        pdi = 100 * s_plus / atr
        ndi = 100 * s_minus / atr
        dx = 100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) else 0.0
        dx_seen += 1
        if dx_seen < period:
            dx_sum += dx
        elif dx_seen == period:
            dx_sum += dx
            adx_val = dx_sum / period
            out[i + 1] = adx_val
        else:
            adx_val = (adx_val * (period - 1) + dx) / period
            out[i + 1] = adx_val
    return out


def atr_pct(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
            period: int = 14) -> List[Num]:
    """ATR as a percentage of close — the form the profiles gate on."""
    n = len(closes)
    out: List[Num] = [None] * n
    trs: List[float] = []
    for i in range(n):
        if i == 0:
            trs.append(highs[i] - lows[i])
            continue
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
        if i + 1 >= period and closes[i]:
            out[i] = (sum(trs[i - period + 1:i + 1]) / period) / closes[i] * 100
    return out


def bollinger(closes: Sequence[float], period: int = 20, mult: float = 2.0):
    """SMA basis with population-stdev bands. Returns (basis, upper, lower)."""
    n = len(closes)
    basis: List[Num] = [None] * n
    upper: List[Num] = [None] * n
    lower: List[Num] = [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        m = sum(window) / period
        var = sum((x - m) ** 2 for x in window) / period  # population, not sample
        sd = var ** 0.5
        basis[i], upper[i], lower[i] = m, m + mult * sd, m - mult * sd
    return basis, upper, lower


def vwap_session(times: Sequence[datetime], highs: Sequence[float], lows: Sequence[float],
                 closes: Sequence[float], volumes: Sequence[float]) -> List[Num]:
    """Session-anchored VWAP on typical price, reset at UTC midnight.

    This anchoring is required — see module docstring.
    """
    out: List[Num] = []
    cum_pv = cum_v = 0.0
    current_day = None
    for t, h, l, c, v in zip(times, highs, lows, closes, volumes):
        if v is None:
            out.append(None)
            continue
        ts = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        day = ts.astimezone(timezone.utc).date()
        if day != current_day:
            current_day, cum_pv, cum_v = day, 0.0, 0.0
        tp = (h + l + c) / 3
        cum_pv += tp * v
        cum_v += v
        out.append(cum_pv / cum_v if cum_v else None)
    return out


def volume_metrics(volumes: Sequence[float], period: int = 20):
    """Returns (volume_sma, volume_ratio). ratio = volume / SMA20(volume)."""
    vs = sma(volumes, period)
    ratio: List[Num] = [
        (v / s if s else None) if s is not None else None
        for v, s in zip(volumes, vs)
    ]
    return vs, ratio
