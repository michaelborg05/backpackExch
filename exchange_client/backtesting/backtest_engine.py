# backtesting/backtest_engine.py
"""
Backtesting engine for signal_generator / trend_cache profiles.

Architecture:
  - ReplayTrendCache   : Subclass of your real TrendCache that bypasses stale-checks
                         and suppresses all DB writes. Feeds data in from DB rows.
  - BacktestProfile    : Lightweight dict-based profile wrapper (mirrors TradingProfile)
  - BacktestEngine     : Core replay loop — runs is_bullish() on historical rows,
                         detects entry signals, simulates TP/SL/trailing-stop outcomes.
  - ParameterSweep     : Grid-search helper — varies one or more profile parameters
                         and compares result sets.
  - BacktestResult     : Rich result object with per-trade log + summary stats.

Usage:
    from backtesting.backtest_engine import BacktestEngine, ParameterSweep, BacktestProfile
    from datetime import datetime, timezone

    # Load a profile config dict (from YAML or hand-crafted)
    profile = BacktestProfile.from_dict("default", yaml_config["profiles"]["default"])

    engine = BacktestEngine(db_session=db, profile=profile)
    result = engine.run(
        symbol="SOL_USDC",
        start=datetime(2026, 2, 15, tzinfo=timezone.utc),
        end=datetime(2026, 2, 22, tzinfo=timezone.utc),
    )
    print(result.summary())

    # Parameter sweep
    sweep = ParameterSweep(db_session=db, base_profile=profile)
    results = sweep.run(
        symbol="SOL_USDC",
        param_grid={
            "min_signal_confidence": [65.0, 70.0, 75.0, 80.0],
            "min_volume_ratio":      [1.0, 1.1, 1.3, 1.5],
        }
    )
    sweep.print_comparison(results)
"""

from __future__ import annotations

import copy
import itertools
import time
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func

# ---------------------------------------------------------------------------
# Lazy imports — only resolve when engine runs (keeps this file importable
# in isolation for tests).
# ---------------------------------------------------------------------------


# Bars of history to replay into the cache *before* the requested window so
# that history-dependent indicators are live on the very first evaluated bar.
# 100 matches ReplayTrendCache's candle-history cap — feeding more is wasted.
WARMUP_BARS = 100


def _as_utc(ts: datetime) -> datetime:
    """Treat naive DB timestamps as UTC so they compare against the window."""
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def _tf_to_minutes(tf) -> int:
    """Minutes per bar for a timeframe label ('15', '240', '1D', 'D', '1W')."""
    s = str(tf).strip().upper()
    if s in ("1D", "D", "1440"):
        return 1440
    if s in ("1W", "W"):
        return 10080
    try:
        return int(s)
    except ValueError:
        raise ValueError(f"Unrecognised timeframe {tf!r}")


class TickDataUnavailable(RuntimeError):
    """Raised when tick mode was requested but the tick data can't support it.

    Silently degrading to candle fills answers a different question than the
    caller asked — candle mode fills stops at the exact stop price with no
    intra-bar path, which flatters stop-heavy strategies. Callers that genuinely
    don't care can pass on_missing_ticks="fallback".
    """


# ===========================================================================
# ReplayTrendCache
# ===========================================================================

class ReplayTrendCache:
    """
    Mimics TrendCache but:
      1. Never talks to the database
      2. Never enforces a max_age staleness limit (data is historical)
      3. Exposes the same public API used by is_bullish() / signal_generator

    We deliberately *re-implement* the minimal surface rather than subclassing
    TrendCache so we don't accidentally trigger DB calls buried in __init__.
    """

    def __init__(self):
        self._cache: Dict[str, Any] = {}          # key → TrendData
        self._rsi_history: Dict[str, list] = {}   # key → [(ts, rsi), ...]
        self._ema_history: Dict[str, list] = {}   # key → [{ts, ema20, ema50}, ...]
        self._bb_history: Dict[str, list] = {}

    # ------------------------------------------------------------------
    # Feed one row into the cache (called by engine in timestamp order)
    # ------------------------------------------------------------------
        self._candle_history: Dict[str, list] = {}
    def feed(self, trend_data) -> bool:
        """
        Feed a TrendData object into the replay cache.
        Returns True if indicators changed (same logic as TrendCache).
        """
        key = f"{trend_data.symbol}_{trend_data.timeframe}"
        old = self._cache.get(key)

        indicators_changed = self._is_significant_change(old, trend_data)

        # Give the object a synthetic "fresh" timestamp so get() won't reject it.
        trend_data.timestamp = time.time()
        self._cache[key] = trend_data

        if indicators_changed:
            # RSI history
            hist = self._rsi_history.setdefault(key, [])
            hist.append((trend_data.timestamp, trend_data.rsi))
            if len(hist) > 15:          # keep more history for rsi_reversal_momentum
                self._rsi_history[key] = hist[-15:]

            # EMA history
            ehist = self._ema_history.setdefault(key, [])
            ehist.append({
                "timestamp": trend_data.timestamp,
                "ema20": trend_data.ema20,
                "ema50": trend_data.ema50,
            })
            if len(ehist) > 5:
                self._ema_history[key] = ehist[-5:]

            # Update BB history for lookback breach checks
            if trend_data.bb is not None and trend_data.bb.bb_lower is not None:
                bbhist = self._bb_history.setdefault(key, [])
                bbhist.append({
                    'timestamp': trend_data.timestamp,
                    'bb_lower':  trend_data.bb.bb_lower,
                    'bb_upper':  trend_data.bb.bb_upper,
                    'bb_basis':  trend_data.bb.bb_basis,
                    'price':     trend_data.prev_candle.prev_close,   # close price at this candle
                })
                if len(bbhist) > 15:          # keep more history for rsi_reversal_momentum
                    self._bb_history[key] = bbhist[-15:]
                            

            # Update closed candle OHLC history (for multi-candle reversal patterns)
            # prev_candle always holds the most recently *closed* bar from Pine.
            # We deduplicate on timestamp so re-fires of the same candle don't
            # double-append (Pine can send the same prev_candle across several
            # 15m bars before the next one closes).
            if trend_data.prev_candle is not None:
                pc = trend_data.prev_candle
                if (pc.prev_open is not None and pc.prev_high is not None
                        and pc.prev_low is not None and pc.prev_close is not None):
                    if key not in self._candle_history:
                        self._candle_history[key] = []

                    # Deduplicate: only append if close price differs from last entry
                    # (timestamp alone isn't reliable — Pine doesn't always send one)
                    last = self._candle_history[key][-1] if self._candle_history[key] else None
                    is_new_candle = (
                        last is None
                        or abs(last['close'] - pc.prev_close) > 0.0001
                        or abs(last['open']  - pc.prev_open)  > 0.0001
                    )
                    if is_new_candle:
                        self._candle_history[key].append({
                            'timestamp': trend_data.timestamp,
                            'open':  pc.prev_open,
                            'high':  pc.prev_high,
                            'low':   pc.prev_low,
                            'close': pc.prev_close,
                        })
                        # Keep last 100 candles — reversal patterns need <=3, the
                        # atr_regime indicator needs period+1 (15), and
                        # distance_from_high needs lookback_bars (e.g. 60 for a
                        # 10-day rolling high off 4h candles).
                        if len(self._candle_history[key]) > 100:
                            self._candle_history[key] = self._candle_history[key][-100:]
            


        return indicators_changed

    # ------------------------------------------------------------------
    # Public API mirroring TrendCache (used by is_bullish internals)
    # ------------------------------------------------------------------
    def get(self, symbol: str, timeframe: str):
        """Return cached TrendData — no staleness check in replay mode."""
        return self._cache.get(f"{symbol}_{timeframe}")

    def get_atr_pct(self, symbol: str, timeframe: str, period: int = 14):
        """ATR14 (% of close) from closed-candle history — same as prod TrendCache."""
        from services.indicators import atr_pct as _atr_pct
        candles = self._candle_history.get(f"{symbol}_{timeframe}", [])
        if len(candles) < period + 1:
            return None
        series = _atr_pct([c['high'] for c in candles],
                          [c['low'] for c in candles],
                          [c['close'] for c in candles], period=period)
        last = series[-1] if series else None
        return float(last) if last is not None else None

    def is_bullish(
        self,
        symbol: str,
        timeframe: str,
        indicators_config=None,
        min_indicators_required: int = 2,
        use_hard_stops: bool = True,
        groups_config: dict = None,
        price_mode: str = "both",
    ) -> tuple:
        """Delegates to _validate_timeframe_indicators exactly as TrendCache does.

        price_mode controls which candle price is used for live-price indicators:
          "both"  — try candle low first, then high; return True if either passes (default, closest to live)
          "low"   — candle low only (conservative long entry check)
          "high"  — candle high only (conservative short entry check)
          "close" — original behaviour (candle close only)
        """
        trend = self.get(symbol, timeframe)
        if trend is None:
            return False, f"No trend data for {symbol} {timeframe}"

        if indicators_config is None:
            indicators_config = [
                {"type": "ema_cross",      "params": {"fast": 20, "slow": 50}},
                {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 50}},
                {"type": "price_vs_vwap",  "params": {}},
            ]

        if price_mode == "both":
            ok, msg = self._validate_timeframe_indicators(
                symbol, timeframe, trend, indicators_config, min_indicators_required,
                use_hard_stops, groups_config=groups_config, price_mode="low",
            )
            if ok:
                return True, msg
            return self._validate_timeframe_indicators(
                symbol, timeframe, trend, indicators_config, min_indicators_required,
                use_hard_stops, groups_config=groups_config, price_mode="high",
            )

        return self._validate_timeframe_indicators(
            symbol, timeframe, trend, indicators_config, min_indicators_required, use_hard_stops,
            groups_config=groups_config, price_mode=price_mode,
        )

    # ------------------------------------------------------------------
    # Private helpers — exact copies from TrendCache (no DB calls here)
    # ------------------------------------------------------------------
    def _is_significant_change(self, old, new) -> bool:
        if old is None:
            return True
        EMA_THRESHOLD = 0.0001
        RSI_THRESHOLD = 0.1
        return (
            abs(new.ema20 - old.ema20) > EMA_THRESHOLD or
            abs(new.ema50 - old.ema50) > EMA_THRESHOLD or
            abs(new.rsi   - old.rsi)   > RSI_THRESHOLD
        )

    def _get_ema_slope(self, symbol: str, timeframe: str, ema_type: str = "ema20"):
        key = f"{symbol}_{timeframe}"
        hist = self._ema_history.get(key, [])
        if len(hist) < 2:
            return None, None
        current  = hist[-1][ema_type]
        previous = hist[-2][ema_type]
        slope_pct = ((current - previous) / previous) * 100 if previous else 0.0
        if slope_pct > 0.01:
            direction = "rising"
        elif slope_pct < -0.01:
            direction = "falling"
        else:
            direction = "flat"
        return slope_pct, direction

    def _get_rsi_momentum(self, symbol: str, timeframe: str, lookback: int = 2):
        key = f"{symbol}_{timeframe}"
        hist = self._rsi_history.get(key, [])
        if len(hist) < lookback + 1:
            return None, None
        rsi_values = [e[1] for e in hist]
        momentums = [rsi_values[-(i+1)] - rsi_values[-(i+2)] for i in range(lookback)]
        avg   = sum(momentums) / len(momentums)
        most_recent = momentums[0]
        if avg > 0 and most_recent <= 0:
            direction = "unstable"
        elif avg > 1:
            direction = "increasing"
        elif avg < -1:
            direction = "decreasing"
        else:
            direction = "stable"
        return avg, direction

    def _get_bb_width_trend(
        self, symbol: str, timeframe: str, lookback: int = 4,
        expand_threshold_pct: float = 0.08,   # 8% change per step = expanding
        contract_threshold_pct: float = 0.08, # 8% change per step = contracting
    ) -> Tuple[Optional[float], Optional[str], Optional[float]]:
        key = f"{symbol}_{timeframe}"
        history = self._bb_history.get(key, [])

        if len(history) < 2:
            return None, None, None

        window = history[-lookback:] if len(history) >= lookback else history

        widths = []
        for entry in window:
            basis = entry.get('bb_basis')
            upper = entry.get('bb_upper')
            lower = entry.get('bb_lower')
            if basis and basis > 0 and upper is not None and lower is not None:
                widths.append((upper - lower) / basis)

        if len(widths) < 2:
            return None, None, None

        avg_change    = (widths[-1] - widths[0]) / (len(widths) - 1)
        avg_width     = sum(widths) / len(widths)
        current_width = widths[-1]

        # Threshold scales with the typical width of this symbol/timeframe
        expand_threshold   =  avg_width * expand_threshold_pct
        contract_threshold = -avg_width * contract_threshold_pct

        if avg_change > expand_threshold:
            direction = "expanding"
        elif avg_change < contract_threshold:
            direction = "contracting"
        else:
            direction = "stable"

        return avg_change, direction, current_width

    def _get_pct_b_trend(
        self, symbol: str, timeframe: str, lookback: int = 4
    ) -> Tuple[Optional[float], Optional[str]]:
        """
        Is %B moving lower (price falling toward lower band) or higher?

        Measures the change in %B across the last N history entries.
        Used by bb_pct_b_momentum indicator on the 15m entry filter.

        For a range-trade long entry we want %B to be falling toward the lower
        band and then flattening/turning — not still in free-fall.

        direction values:
          "falling"  — %B dropping toward lower band  (good: dip forming)
          "rising"   — %B moving toward upper band    (bad: dip has reversed, chasing)
          "flat"     — %B stable                      (neutral)

        Returns:
            (total_change_over_window, direction)
            Returns (None, None) if insufficient history.
        """
        key = f"{symbol}_{timeframe}"
        history = self._bb_history.get(key, [])

        if len(history) < 2:
            return None, None

        window = history[-lookback:] if len(history) >= lookback else history

        pct_b_values = []
        for entry in window:
            upper = entry.get('bb_upper')
            lower = entry.get('bb_lower')
            price = entry.get('price')
            if upper is not None and lower is not None and price is not None:
                band_width = upper - lower
                if band_width > 0:
                    pct_b_values.append((price - lower) / band_width)

        if len(pct_b_values) < 2:
            return None, None

        # Total change from start to end of window
        total_change = pct_b_values[-1] - pct_b_values[0]

        if total_change < -0.08:
            direction = "falling"
        elif total_change > 0.08:
            direction = "rising"
        else:
            direction = "flat"

        return total_change, direction

    def _validate_timeframe_indicators(
        self,
        symbol: str,
        timeframe: str,
        trend,
        indicators: list,
        min_indicators_required: int,
        use_hard_stops: bool = True,
        groups_config: dict = None,
        price_mode: str = "close",
    ):
        """
        Full copy of TrendCache._validate_timeframe_indicators — all indicator
        types supported. Uses self._get_ema_slope / _get_rsi_momentum instead
        of the live cache versions.
        """
        results = []
        hard_stop_failures = []
        indicator_groups_list = []  # parallel to results: indicator_group per indicator

        # price_mode controls which candle price is used for indicators that compare
        # against live price (bollinger_bands, price_vs_vwap, price_vs_ema, etc.)
        # "close" = original behaviour; "low"/"high" = candle extremes; "both" handled by is_bullish
        _price_map = {"low": getattr(trend, "low", trend.price),
                      "high": getattr(trend, "high", trend.price)}
        current_price = _price_map.get(price_mode, trend.price)

        for indicator_config in indicators:
            indicator_type = indicator_config.get("type")
            params         = indicator_config.get("params", {})
            hard_stop      = params.get("hard_stop", False)
            indicator_group = indicator_config.get("indicator_group")
            is_bull        = False
            msg            = ""

            # --- backward compat ---
            if indicator_type == "ema_alignment":
                indicator_type = "ema_cross"

            # === INDICATORS ================================================

            if indicator_type == "ema_cross":
                use_slope     = params.get("use_slope", False)
                min_slope_pct = params.get("min_slope_pct", 0.01)
                if use_slope:
                    slope_pct, slope_dir = self._get_ema_slope(symbol, timeframe, "ema20")
                    if slope_pct is None:
                        is_bull = trend.ema20 > trend.ema50
                        msg = f"EMA cross: {'✓' if is_bull else '✗'} (no slope data)"
                    else:
                        is_bull = trend.ema20 > trend.ema50 and slope_pct >= min_slope_pct
                        msg = f"EMA cross: {'✓' if is_bull else '✗'} ({trend.ema20:.4f}/{trend.ema50:.4f} slope {slope_dir})"
                else:
                    is_bull = trend.ema20 > trend.ema50
                    msg = f"EMA cross: {'✓' if is_bull else '✗'} ({trend.ema20:.4f}/{trend.ema50:.4f})"

            elif indicator_type == "rsi_threshold":
                min_rsi        = params.get("min_value", 50)
                use_momentum   = params.get("use_momentum", True)
                early_threshold= params.get("early_threshold", 40)
                rsi = trend.rsi
                if use_momentum:
                    rsi_mom, rsi_dir = self._get_rsi_momentum(symbol, timeframe)
                    if rsi >= early_threshold and rsi < min_rsi:
                        if rsi_dir == "increasing" and rsi_mom is not None and rsi_mom >= 1.0:
                            is_bull = True
                            msg = f"RSI: ✓ {rsi:.1f} early entry (>{early_threshold} momentum +{rsi_mom:.1f})"
                        else:
                            is_bull = False
                            msg = f"RSI: ✗ {rsi:.1f} below {min_rsi}"
                    elif rsi >= min_rsi:
                        is_bull = (rsi_mom is None or rsi_mom >= 0)
                        msg = f"RSI: {'✓' if is_bull else '✗'} {rsi:.1f}>{min_rsi} momentum {rsi_dir}"
                    else:
                        is_bull = False
                        msg = f"RSI: ✗ {rsi:.1f}<{min_rsi}"
                else:
                    is_bull = rsi >= min_rsi
                    msg = f"RSI: {'✓' if is_bull else '✗'} {rsi:.1f}"

            elif indicator_type == "price_vs_vwap":
                is_bull = current_price > trend.vwap if trend.vwap else False
                msg     = f"Price vs VWAP: {'✓' if is_bull else '✗'} ({current_price:.4f}/{trend.vwap:.4f})"

            elif indicator_type == "price_vs_ema":
                ema_type    = params.get("ema", 20)
                min_gap_pct = params.get("min_gap_pct", 0.0)
                max_gap_pct = params.get("max_gap_pct", 0.0)
                ema_value   = trend.ema20 if ema_type == 20 else trend.ema50
                gap_pct     = ((current_price - ema_value) / ema_value) * 100
                is_bull     = gap_pct >= min_gap_pct
                if max_gap_pct > 0:
                    is_bull = is_bull and gap_pct <= max_gap_pct
                msg = f"Price vs EMA{ema_type}: {'✓' if is_bull else '✗'} ({gap_pct:+.2f}%)"

            elif indicator_type == "ema_slope":
                ema_type  = params.get("ema", 20)
                req_dir   = params.get("direction", "rising")
                min_slope = params.get("min_slope_pct", 0.01)
                max_slope = params.get("max_slope_pct", None)
                ema_name  = f"ema{ema_type}"
                slope_pct, _ = self._get_ema_slope(symbol, timeframe, ema_name)
                if slope_pct is None:
                    is_bull = False
                    msg     = f"EMA{ema_type} slope: ✗ (no data)"
                else:
                    if req_dir == "rising":
                        is_bull   = slope_pct > min_slope
                        direction = "rising" if is_bull else "flat/falling"
                    elif req_dir == "falling":
                        is_bull   = slope_pct < -min_slope
                        direction = "falling" if is_bull else "flat/rising"
                    elif req_dir == "not_falling":
                        is_bull   = slope_pct >= -min_slope
                        direction = "rising/flat" if is_bull else "falling"
                    elif req_dir == "not_rising":
                        is_bull   = slope_pct <= max_slope if max_slope is not None else slope_pct <= min_slope
                        direction = "flat/falling" if is_bull else "rising"
                    else:
                        is_bull   = abs(slope_pct) <= min_slope
                        direction = "flat"
                    if is_bull and max_slope is not None and slope_pct > max_slope:
                        is_bull   = False
                        direction = "too steep"
                    max_str = f", max {max_slope:+.3f}%" if max_slope is not None else ""
                    msg = f"EMA{ema_type} slope: {'✓' if is_bull else '✗'} ({direction} {slope_pct:+.3f}%{max_str})"

            elif indicator_type == "rsi_range":
                min_rsi  = params.get("min", 30)
                max_rsi  = params.get("max", 70)
                invert   = params.get("invert", False)
                mom_over = params.get("momentum_override_threshold", None)
                rsi_mom, rsi_dir = self._get_rsi_momentum(symbol, timeframe)
                in_range = min_rsi <= trend.rsi <= max_rsi
                if invert:
                    is_bull = in_range
                    msg = f"RSI range: {'✓' if is_bull else '✗'} (RSI {trend.rsi:.1f} {'in' if in_range else 'outside'} {min_rsi}-{max_rsi})"
                else:
                    is_bull = not in_range
                    if not is_bull and mom_over is not None and rsi_mom is not None:
                        if abs(rsi_mom) >= mom_over:
                            is_bull = rsi_mom > 0
                            msg = f"RSI range: momentum override {'✓' if is_bull else '✗'}"
                        else:
                            msg = f"RSI range: {'✓' if is_bull else '✗'} (RSI {trend.rsi:.1f} {'outside' if is_bull else 'in'} {min_rsi}-{max_rsi})"
                    else:
                        msg = f"RSI range: {'✓' if is_bull else '✗'} (RSI {trend.rsi:.1f} {'outside' if is_bull else 'in'} {min_rsi}-{max_rsi})"

            elif indicator_type == "ema_gap":
                min_gap_pct = params.get("min_gap_pct", 0.3)
                max_gap_pct = params.get("max_gap_pct", 0.3)
                mode        = params.get("mode", "min")
                gap_pct     = abs((trend.ema20 - trend.ema50) / trend.ema50) * 100 if trend.ema50 else 0
                is_bull     = gap_pct >= min_gap_pct if mode == "min" else gap_pct <= max_gap_pct
                msg         = f"EMA gap: {'✓' if is_bull else '✗'} ({gap_pct:.2f}%)"

            elif indicator_type == "rsi_oversold":
                max_value      = params.get("max_value", 35)
                require_rising = params.get("require_rising", True)
                min_momentum   = params.get("min_momentum", 0.5)
                is_oversold    = trend.rsi < max_value
                if require_rising:
                    rsi_mom, rsi_dir = self._get_rsi_momentum(symbol, timeframe)
                    is_turning_up = (
                        rsi_mom is not None and
                        rsi_dir == "increasing" and
                        rsi_mom >= min_momentum
                    )
                    is_bull = is_oversold and is_turning_up
                    msg = f"RSI oversold: {'✓' if is_bull else '✗'} (RSI {trend.rsi:.1f}, turning={is_turning_up})"
                else:
                    is_bull = is_oversold
                    msg = f"RSI oversold: {'✓' if is_bull else '✗'} (RSI {trend.rsi:.1f}<{max_value})"

            elif indicator_type == "rsi_overbought":
                """
                RSI extreme-zone block — works for both long and short entries.

                Long (default, side="long"):
                  Blocks if current RSI > min_value (overbought).
                  params: { side: "long", min_value: 70, lookback_candles: null }

                Short (side="short"):
                  Blocks if current RSI < max_value (oversold — bad time to short).
                  params: { side: "short", max_value: 30, lookback_candles: null }
                """
                side = params.get("side", "long")
                lookback_candles = params.get("lookback_candles", None)
                current_rsi = float(trend.rsi)

                if side == "short":
                    max_value = params.get("max_value", 30)
                    is_extreme = current_rsi < max_value

                    trough_in_lookback = False
                    trough_rsi_rounded = None
                    if lookback_candles is not None:
                        key = f"{symbol}_{timeframe}"
                        rsi_history = self._rsi_history.get(key, [])
                        if len(rsi_history) >= lookback_candles:
                            recent_rsi_values = [rsi for _, rsi in rsi_history[-lookback_candles:]]
                            trough_rsi = min(recent_rsi_values)
                            trough_in_lookback = trough_rsi < max_value
                            trough_rsi_rounded = round(trough_rsi, 2)

                    is_bull = not is_extreme and not trough_in_lookback

                    if is_extreme:
                        msg = f"RSI oversold block (short): ✗ (RSI {current_rsi:.1f} < {max_value})"
                    elif trough_in_lookback:
                        msg = (
                            f"RSI oversold block (short): ✗ "
                            f"(RSI {current_rsi:.1f} ok now, but troughed at "
                            f"{trough_rsi_rounded:.1f} < {max_value} "
                            f"in last {lookback_candles} candles)"
                        )
                    else:
                        lookback_note = (
                            f", trough {trough_rsi_rounded:.1f} in last {lookback_candles} ok"
                            if lookback_candles is not None and trough_rsi_rounded is not None
                            else ""
                        )
                        msg = f"RSI oversold block (short): ✓ (RSI {current_rsi:.1f}{lookback_note})"

                else:
                    # Long (default): block when RSI is overbought
                    min_value = params.get("min_value", 70)
                    is_overbought = current_rsi > min_value

                    peak_in_lookback = False
                    peak_rsi_rounded = None
                    if lookback_candles is not None:
                        key = f"{symbol}_{timeframe}"
                        rsi_history = self._rsi_history.get(key, [])
                        if len(rsi_history) >= lookback_candles:
                            recent_rsi_values = [rsi for _, rsi in rsi_history[-lookback_candles:]]
                            peak_rsi = max(recent_rsi_values)
                            peak_in_lookback = peak_rsi > min_value
                            peak_rsi_rounded = round(peak_rsi, 2)

                    is_bull = not is_overbought and not peak_in_lookback

                    if is_overbought:
                        msg = f"RSI overbought check: ✗ (RSI {current_rsi:.1f} > {min_value})"
                    elif peak_in_lookback:
                        msg = (
                            f"RSI overbought check: ✗ "
                            f"(RSI {current_rsi:.1f} ok now, but peaked at "
                            f"{peak_rsi_rounded:.1f} > {min_value} "
                            f"in last {lookback_candles} candles)"
                        )
                    else:
                        lookback_note = (
                            f", peak {peak_rsi_rounded:.1f} in last {lookback_candles} ok"
                            if lookback_candles is not None and peak_rsi_rounded is not None
                            else ""
                        )
                        msg = f"RSI overbought check: ✓ (RSI {current_rsi:.1f}{lookback_note})"

            elif indicator_type == "price_below_vwap":
                min_gap_pct = params.get("min_gap_pct", -1.0)
                max_gap_pct = params.get("max_gap_pct", -10.0)
                gap_pct     = ((current_price - trend.vwap) / trend.vwap) * 100 if trend.vwap else 0
                is_bull     = max_gap_pct <= gap_pct <= min_gap_pct
                msg         = f"Price below VWAP: {'✓' if is_bull else '✗'} ({gap_pct:+.2f}%)"

            elif indicator_type == "price_extended_below_ema":
                ema_type    = params.get("ema", 20)
                min_gap_pct = params.get("min_gap_pct", -2.0)
                max_gap_pct = params.get("max_gap_pct", -10.0)
                ema_value   = trend.ema20 if ema_type == 20 else trend.ema50
                gap_pct     = ((current_price - ema_value) / ema_value) * 100 if ema_value else 0
                is_bull     = max_gap_pct <= gap_pct <= min_gap_pct
                msg         = f"Price below EMA{ema_type}: {'✓' if is_bull else '✗'} ({gap_pct:+.2f}%)"

            elif indicator_type == "price_above_vwap":
                min_gap_pct = params.get("min_gap_pct", 1.0)
                max_gap_pct = params.get("max_gap_pct", 10.0)
                gap_pct     = ((current_price - trend.vwap) / trend.vwap) * 100 if trend.vwap else 0
                is_bull     = min_gap_pct <= gap_pct <= max_gap_pct
                msg         = f"Price above VWAP: {'✓' if is_bull else '✗'} ({gap_pct:+.2f}%)"

            elif indicator_type == "price_extended_above_ema":
                ema_type    = params.get("ema", 20)
                min_gap_pct = params.get("min_gap_pct", 2.0)
                max_gap_pct = params.get("max_gap_pct", 10.0)
                ema_value   = trend.ema20 if ema_type == 20 else trend.ema50
                gap_pct     = ((current_price - ema_value) / ema_value) * 100 if ema_value else 0
                is_bull     = min_gap_pct <= gap_pct <= max_gap_pct
                msg         = f"Price above EMA{ema_type}: {'✓' if is_bull else '✗'} ({gap_pct:+.2f}%)"

            elif indicator_type == "bollinger_bands":
                band          = params.get("band", "lower")
                mode          = params.get("mode", "touch")
                tolerance_pct = params.get("tolerance_pct", 0.5)
                max_pct_b     = params.get("max_pct_b", None)
                min_pct_b     = params.get("min_pct_b", None)
                lookback_candles = params.get("lookback_candles", 0)

                if trend.bb is None or trend.bb.bb_upper is None or trend.bb.bb_lower is None:
                    is_bull = False
                    msg = "Bollinger Bands: ✗ (no BB data)"
                else:
                    bb_lower   = trend.bb.bb_lower
                    bb_upper   = trend.bb.bb_upper
                    bb_basis   = trend.bb.bb_basis
                    band_width = bb_upper - bb_lower
                    pct_b      = (current_price - bb_lower) / band_width if band_width > 0 else None

                    if mode == "pct_b":
                        if pct_b is None:
                            is_bull, msg = False, "BB %B: ✗ (zero band width)"
                        else:
                            below_max = (max_pct_b is None) or (pct_b <= max_pct_b)
                            above_min = (min_pct_b is None) or (pct_b >= min_pct_b)
                            is_bull = below_max and above_min

                            # Build readable range string for the log message
                            if min_pct_b is not None and max_pct_b is not None:
                                range_str = f"need {min_pct_b:.2f}–{max_pct_b:.2f}"
                            elif min_pct_b is not None:
                                range_str = f"need >={min_pct_b:.2f}"
                            elif max_pct_b is not None:
                                range_str = f"need <={max_pct_b:.2f}"
                            else:
                                range_str = "no range set"

                            msg = (
                                f"BB %B ({band}): {'✓' if is_bull else '✗'} "
                                f"(%B={pct_b:.2f} - {range_str})"
                            )

                    elif mode == "touch":
                        target   = bb_lower if band == "lower" else bb_upper
                        dist_pct = abs((current_price - target) / target) * 100 if target else 0
                        is_bull = dist_pct <= tolerance_pct
                        msg = f"BB {band} touch: {'✓' if is_bull else '✗'} ({dist_pct:.2f}% from band)"
                    else:  # breach
                        if lookback_candles > 0:
                            # Lookback mode: did price breach the band in the last N candles?
                            bb_key = f"{symbol}_{timeframe}"
                            bb_hist = self._bb_history.get(bb_key, [])
                            window = bb_hist[-lookback_candles:] if bb_hist else []
                            
                            if not window:
                                is_bull = False
                                msg = (
                                    f"BB {band} breach (lookback {lookback_candles}): ✗ "
                                    f"(no BB history yet)"
                                )
                            elif band == "lower":
                                breached = any(entry['price'] <= entry['bb_lower'] for entry in window)
                                is_bull = breached
                                msg = (
                                    f"BB lower breach (lookback {lookback_candles}): "
                                    f"{'✓' if is_bull else '✗'} "
                                    f"({'breach found' if breached else 'no breach'} "
                                    f"in last {len(window)} candles)"
                                )
                            else:  # upper
                                breached = any(entry['price'] >= entry['bb_upper'] for entry in window)
                                is_bull = breached
                                msg = (
                                    f"BB upper breach (lookback {lookback_candles}): "
                                    f"{'✓' if is_bull else '✗'} "
                                    f"({'breach found' if breached else 'no breach'} "
                                    f"in last {len(window)} candles)"
                                )
                        elif band == "lower":
                            is_bull = current_price <= bb_lower
                            msg = f"BB lower breach: {'✓' if is_bull else '✗'}"
                        else:
                            is_bull = current_price < bb_upper
                            msg = f"BB upper breach: {'✓' if is_bull else '✗'}"





            elif indicator_type == "volume_spike":
                min_ratio = params.get("min_ratio", 1.5)
                max_ratio = params.get("max_ratio", 10.0)
                if trend.volume_ratio is None:
                    is_bull, msg = False, "Volume spike: ✗ (no data)"
                else:
                    is_bull = min_ratio <= trend.volume_ratio <= max_ratio
                    msg = f"Volume spike: {'✓' if is_bull else '✗'} ({trend.volume_ratio:.2f}x)"

            elif indicator_type == "reversal_candle":
                pattern        = params.get("pattern", "doji")
                min_body_pct   = params.get("min_body_pct", 0.1)
                max_body_pct   = params.get("max_body_pct", 0.35)
                min_close_pct  = params.get("min_close_pct", 0.6)   # for bull_close

                # ── Helper: derive candle metrics from an OHLC dict ──────────
                def _candle_metrics(o, h, l, c):
                    total  = h - l
                    body   = abs(c - o)
                    l_wick = min(o, c) - l
                    u_wick = h - max(o, c)
                    return total, body, l_wick, u_wick, c > o   # (range, body, lw, uw, is_bull)

                # ── Resolve which candles to use ─────────────────────────────
                # For history-based patterns we prefer _candle_history so both
                # candles are confirmed closed bars.  Single-candle patterns
                # always use trend.prev_candle (most up-to-date closed bar).

                ch_key   = f"{symbol}_{timeframe}"
                ch       = self._candle_history.get(ch_key, [])
                have_history = len(ch) >= 2

                # Most-recent closed candle (used by all single-candle patterns
                # and as the fallback for history-based ones)
                if trend.prev_candle is not None:
                    pc_o = trend.prev_candle.prev_open
                    pc_h = trend.prev_candle.prev_high
                    pc_l = trend.prev_candle.prev_low
                    pc_c = trend.prev_candle.prev_close
                else:
                    pc_o = pc_h = pc_l = pc_c = None

                # ── Single-candle patterns ────────────────────────────────────
                if pattern in ("hammer", "doji", "bull_close", "shooting_star", "bear_close"):
                    if pc_o is None:
                        is_bull = False
                        msg = (
                            f"Reversal candle ({pattern}): ✗ "
                            f"(no prev_candle OHLC — check Pine script)"
                        )
                    else:
                        total, body, l_wick, u_wick, is_bull = _candle_metrics(pc_o, pc_h, pc_l, pc_c)
                        if total == 0:
                            is_bull = False
                            msg = f"Reversal candle ({pattern}): ✗ (zero-range candle)"

                        elif pattern == "hammer":
                            # Long lower wick (>=2x body), small upper wick (<=0.3x body),
                            # body at least min_body_pct of total range.
                            body_pct       = body / total
                            lw_ratio       = l_wick / body if body > 0 else 0
                            uw_ratio       = u_wick / body if body > 0 else 999
                            is_bull = (lw_ratio >= 2.0 and uw_ratio <= 0.3
                                          and body_pct >= min_body_pct)
                            msg = (
                                f"Hammer: {'✓' if is_bull else '✗'} "
                                f"(lower_wick={lw_ratio:.1f}x body, "
                                f"upper_wick={uw_ratio:.1f}x body, "
                                f"body={body_pct:.1%} of range)"
                            )

                        elif pattern == "doji":
                            body_pct = body / total
                            is_bull = body_pct <= max_body_pct
                            msg = (
                                f"Doji: {'✓' if is_bull else '✗'} "
                                f"(body={body_pct:.1%} of range, max={max_body_pct:.1%})"
                            )

                        elif pattern == "bull_close":
                            # Candle closed in the upper portion of its range regardless
                            # of whether it was a red or green candle.
                            # close_position: 0.0 = closed at the low, 1.0 = at the high.
                            # Use case: in a range, small red candles that hold their
                            # upper half show buyers absorbing the sell pressure.
                            close_pos = (pc_c - pc_l) / total if total > 0 else 0
                            is_bull = close_pos >= min_close_pct
                            msg = (
                                f"Bull close: {'✓' if is_bull else '✗'} "
                                f"(closed at {close_pos:.1%} of range, "
                                f"need >={min_close_pct:.1%})"
                            )

                        elif pattern == "shooting_star":
                            body_pct       = body / total
                            uw_ratio       = u_wick / body if body > 0 else 0
                            lw_ratio       = l_wick / body if body > 0 else 999
                            is_bull = (uw_ratio >= 2.0 and lw_ratio <= 0.3
                                       and body_pct >= min_body_pct)
                            msg = (
                                f"Shooting star: {'✓' if is_bull else '✗'} "
                                f"(upper_wick={uw_ratio:.1f}x body, "
                                f"lower_wick={lw_ratio:.1f}x body, "
                                f"body={body_pct:.1%} of range)"
                            )

                        elif pattern == "bear_close":
                            max_close_pct = params.get("max_close_pct", 0.4)
                            close_pos = (pc_c - pc_l) / total if total > 0 else 0
                            is_bull = close_pos <= max_close_pct
                            msg = (
                                f"Bear close: {'✓' if is_bull else '✗'} "
                                f"(closed at {close_pos:.1%} of range, "
                                f"need <={max_close_pct:.1%})"
                            )

                # ── Two-closed-candle patterns ────────────────────────────────
                elif pattern in ("higher_low", "engulfing", "lower_high", "bear_engulfing"):

                    # Resolve the two closed candles.
                    # Prefer history (both confirmed), fall back to history[-1] +
                    # prev_candle if history only has one entry, and finally fall
                    # back to prev_candle + current_price (old behaviour for
                    # engulfing) so we degrade gracefully on first start.
                    if have_history:
                        c1 = ch[-2]   # older closed candle
                        c2 = ch[-1]   # most-recent closed candle
                        data_source = "history"
                    elif len(ch) == 1 and pc_o is not None:
                        # history has one entry; use prev_candle as c2
                        c1 = ch[-1]
                        c2 = {"open": pc_o, "high": pc_h, "low": pc_l, "close": pc_c}
                        data_source = "partial_history"
                    elif pc_o is not None:
                        # No history yet — fall back to prev_candle vs live price
                        # (only usable for engulfing; higher_low skips)
                        c1 = {"open": pc_o,    "high": pc_h,          "low": pc_l,
                              "close": pc_c}
                        c2 = {"open": pc_c,    "high": current_price,  "low": current_price,
                              "close": current_price}
                        data_source = "live_fallback"
                    else:
                        c1 = c2 = None
                        data_source = "no_data"

                    if c1 is None or c2 is None:
                        is_bull = False
                        msg = (
                            f"Reversal candle ({pattern}): ✗ "
                            f"(no candle data — check Pine script and allow cache to warm up)"
                        )

                    elif pattern == "higher_low":
                        # c2 (recent) low must be strictly above c1 (older) low.
                        # Both can be red — the signal is that the sell pressure is
                        # waning: each dip finds support at a higher level.
                        # Optional: require c2 to also be a bull candle for a
                        # stricter version (set require_bull: true in params).
                        require_bull = params.get("require_bull", False)

                        hl_ok   = c2["low"] > c1["low"]
                        bull_ok = (not require_bull) or (c2["close"] > c2["open"])

                        is_bull = hl_ok and bull_ok
                        msg = (
                            f"Higher low: {'✓' if is_bull else '✗'} "
                            f"(c2_low={c2['low']:.4f} vs c1_low={c1['low']:.4f}"
                            + (f", bull={bull_ok}" if require_bull else "")
                            + f") [{data_source}]"
                        )

                    elif pattern == "engulfing":
                        # Bullish engulfing (two confirmed closed candles):
                        #   c1 (older) was bearish, c2 (recent) is bullish and
                        #   its body fully contains c1's body.
                        # Skip live_fallback for this pattern — an unfinished
                        # candle can't confirm an engulf.
                        if data_source == "live_fallback":
                            is_bull = False
                            msg = (
                                "Bullish engulfing: ✗ "
                                "(candle history warming up — need 2 closed candles)"
                            )
                        else:
                            c2_total, c2_body, _, _, c2_bull = _candle_metrics(
                                c2["open"], c2["high"], c2["low"], c2["close"])
                            _, c1_body, _, _, c1_bull = _candle_metrics(
                                c1["open"], c1["high"], c1["low"], c1["close"])

                            c1_bear        = not c1_bull
                            c2_body_lo     = min(c2["open"], c2["close"])
                            c2_body_hi     = max(c2["open"], c2["close"])
                            c1_body_lo     = min(c1["open"], c1["close"])
                            c1_body_hi     = max(c1["open"], c1["close"])
                            engulfs        = (c2_body_lo <= c1_body_lo
                                              and c2_body_hi >= c1_body_hi)
                            body_pct       = c2_body / c2_total if c2_total > 0 else 0


                            is_bull = c2_bull and c1_bear and engulfs
                            msg = (
                                f"Bullish engulfing: {'✓' if is_bull else '✗'} "
                                f"(c2_bull={c2_bull}, c1_bear={c1_bear}, "
                                f"engulfs={engulfs}) [{data_source}]"
                            )

                    elif pattern == "lower_high":
                        require_bear = params.get("require_bear", False)
                        lh_ok   = c2["high"] < c1["high"]
                        bear_ok = (not require_bear) or (c2["close"] < c2["open"])
                        is_bull = lh_ok and bear_ok
                        msg = (
                            f"Lower high: {'✓' if is_bull else '✗'} "
                            f"(c2_high={c2['high']:.4f} vs c1_high={c1['high']:.4f}"
                            + (f", bear={bear_ok}" if require_bear else "")
                            + f") [{data_source}]"
                        )

                    elif pattern == "bear_engulfing":
                        if data_source == "live_fallback":
                            is_bull = False
                            msg = (
                                "Bearish engulfing: ✗ "
                                "(candle history warming up — need 2 closed candles)"
                            )
                        else:
                            c2_total, c2_body, _, _, c2_bull = _candle_metrics(
                                c2["open"], c2["high"], c2["low"], c2["close"])
                            _, c1_body, _, _, c1_bull = _candle_metrics(
                                c1["open"], c1["high"], c1["low"], c1["close"])
                            c2_bear        = not c2_bull
                            c2_body_lo     = min(c2["open"], c2["close"])
                            c2_body_hi     = max(c2["open"], c2["close"])
                            c1_body_lo     = min(c1["open"], c1["close"])
                            c1_body_hi     = max(c1["open"], c1["close"])
                            engulfs        = (c2_body_lo <= c1_body_lo
                                              and c2_body_hi >= c1_body_hi)
                            body_pct       = c2_body / c2_total if c2_total > 0 else 0
                            is_bull = c2_bear and c1_bull and engulfs
                            msg = (
                                f"Bearish engulfing: {'✓' if is_bull else '✗'} "
                                f"(c2_bear={c2_bear}, c1_bull={c1_bull}, "
                                f"engulfs={engulfs}) [{data_source}]"
                            )

                else:
                    is_bull = False
                    msg = (
                        f"Reversal candle: ✗ (unknown pattern '{pattern}' — "
                        f"use hammer | doji | bull_close | shooting_star | bear_close "
                        f"| higher_low | engulfing | lower_high | bear_engulfing)"
                    )

                max_drop_from_close_pct = params.get("max_drop_from_close_pct", None)
                if max_drop_from_close_pct is not None:
                    ref_close = None
                    if pattern in ("hammer", "doji", "bull_close") and pc_c is not None:
                        ref_close = pc_c
                    elif pattern in ("higher_low", "engulfing"):
                        try:
                            ref_close = c2["close"] if c2 is not None else pc_c
                        except (NameError, TypeError):
                            ref_close = pc_c
                    if ref_close is not None and ref_close > 0:
                        drop_pct = ((ref_close - current_price) / ref_close) * 100
                        if drop_pct > max_drop_from_close_pct:
                            prev_result = "✓" if is_bull else "✗"
                            is_bull = False
                            msg = (
                                f"Reversal candle ({pattern}): ✗ "
                                f"(pattern {prev_result} but price dropped "
                                f"{drop_pct:.2f}% from close, max {max_drop_from_close_pct:.2f}%)"
                            )

                max_rise_from_close_pct = params.get("max_rise_from_close_pct", None)
                if max_rise_from_close_pct is not None:
                    ref_close = None
                    if pattern in ("shooting_star", "bear_close") and pc_c is not None:
                        ref_close = pc_c
                    elif pattern in ("lower_high", "bear_engulfing"):
                        try:
                            ref_close = c2["close"] if c2 is not None else pc_c
                        except (NameError, TypeError):
                            ref_close = pc_c
                    if ref_close is not None and ref_close > 0:
                        rise_pct = ((current_price - ref_close) / ref_close) * 100
                        if rise_pct > max_rise_from_close_pct:
                            prev_result = "✓" if is_bull else "✗"
                            is_bull = False
                            msg = (
                                f"Reversal candle ({pattern}): ✗ "
                                f"(pattern {prev_result} but price rose "
                                f"{rise_pct:.2f}% from close, max {max_rise_from_close_pct:.2f}%)"
                            )

            elif indicator_type == "rsi_reversal_momentum":
                lookback_candles   = params.get("lookback_candles", 5)
                oversold_threshold = params.get("oversold_threshold", 30)
                current_min        = params.get("current_min", 35)
                jump_required      = params.get("jump_required", True)
                min_jump           = params.get("min_jump", 5.0)
                require_sustained  = params.get("require_sustained", True)
                # "strict" (default): each candle must be higher than the last (consecutive rise)
                # "net"             : current candle just needs to be above the candle 2 steps back
                #                     — allows a dip-then-higher-high recovery shape
                sustained_rise_mode = params.get("sustained_rise_mode", "strict")

                key_str   = f"{symbol}_{timeframe}"
                rsi_hist  = self._rsi_history.get(key_str, [])

                if len(rsi_hist) < lookback_candles:
                    is_bull = False
                    msg = f"RSI Reversal Momentum: ✗ (insufficient history {len(rsi_hist)}/{lookback_candles})"
                else:
                    current_rsi    = trend.rsi
                    recent         = rsi_hist[-lookback_candles:]
                    rsi_vals       = [r for _, r in recent]
                    touched_oversold = any(r < oversold_threshold for r in rsi_vals)
                    min_rsi_val    = min(rsi_vals)

                    if jump_required:
                        max_jump  = 0.0
                        jump_found = False
                        min_found  = False
                        for i in range(1, len(rsi_vals)):
                            if not min_found and rsi_vals[i-1] == min_rsi_val:
                                min_found = True
                            if min_found:
                                jmp = rsi_vals[i] - rsi_vals[i-1]
                                if jmp > max_jump:
                                    max_jump = jmp
                                if jmp >= min_jump:
                                    jump_found = True
                    else:
                        jump_found = True
                        max_jump   = 0.0

                    current_above_min = current_rsi >= current_min
                    
                    if require_sustained == True:
                        #If require sustained, look over last 2 candle gaps
                        rsi_mom, rsi_dir  = self._get_rsi_momentum(symbol, timeframe, lookback=2)
                    else:
                        #else just check previous jump
                        rsi_mom, rsi_dir  = self._get_rsi_momentum(symbol, timeframe, lookback=1)

                    currently_rising  = (rsi_mom is not None and rsi_mom > 2 and rsi_dir == "increasing") if jump_required else True

                    sustained_rise = True
                    if require_sustained and len(rsi_hist) >= 3:
                        last3 = [r for _, r in rsi_hist[-3:]]
                        if sustained_rise_mode == "net":
                            # Allow: consecutive up-up OR dip-then-higher-high (last3[2] > last3[0])
                            consecutive    = last3[1] > last3[0] and last3[2] > last3[1]
                            net_higher     = last3[2] > last3[0]
                            sustained_rise = consecutive or net_higher
                        else:
                            # "strict" (default): must be strictly consecutive up-up
                            sustained_rise = last3[1] > last3[0] and last3[2] > last3[1]

                    is_bull = touched_oversold and jump_found and current_above_min and currently_rising

                    if require_sustained:
                        is_bull = is_bull and sustained_rise

                    values = {
                        "touched_oversold":  touched_oversold,
                        "min_rsi":           min_rsi_val,
                        "jump_found":        jump_found,
                        "max_jump":          max_jump,
                        "current_rsi":       current_rsi,
                        "rsi_direction":     rsi_dir,
                        "sustained_rise":    sustained_rise,
                        "sustained_mode":    sustained_rise_mode,
                    }
                    msg = f"RSI Reversal Momentum: {'✓' if is_bull else '✗'} (RSI {min_rsi_val:.0f}→{current_rsi:.0f})"

            elif indicator_type == "rsi_overbought_momentum":
                lookback_candles     = params.get("lookback_candles", 5)
                overbought_threshold = params.get("overbought_threshold", 70)
                current_max          = params.get("current_max", 65)
                drop_required        = params.get("drop_required", True)
                min_drop             = params.get("min_drop", 5.0)
                require_sustained    = params.get("require_sustained", True)
                sustained_fall_mode  = params.get("sustained_fall_mode", "strict")

                key_str  = f"{symbol}_{timeframe}"
                rsi_hist = self._rsi_history.get(key_str, [])

                if len(rsi_hist) < lookback_candles:
                    is_bull = False
                    msg = f"RSI Overbought Momentum: ✗ (insufficient history {len(rsi_hist)}/{lookback_candles})"
                else:
                    current_rsi        = trend.rsi
                    recent             = rsi_hist[-lookback_candles:]
                    rsi_vals           = [r for _, r in recent]
                    touched_overbought = any(r > overbought_threshold for r in rsi_vals)
                    max_rsi_val        = max(rsi_vals)

                    if drop_required:
                        max_drop   = 0.0
                        drop_found = False
                        max_found  = False
                        for i in range(1, len(rsi_vals)):
                            if not max_found and rsi_vals[i-1] == max_rsi_val:
                                max_found = True
                            if max_found:
                                drp = rsi_vals[i-1] - rsi_vals[i]
                                if drp > max_drop:
                                    max_drop = drp
                                if drp >= min_drop:
                                    drop_found = True
                    else:
                        drop_found = True
                        max_drop   = 0.0

                    current_below_max = current_rsi <= current_max

                    if require_sustained:
                        rsi_mom, rsi_dir = self._get_rsi_momentum(symbol, timeframe, lookback=2)
                    else:
                        rsi_mom, rsi_dir = self._get_rsi_momentum(symbol, timeframe, lookback=1)

                    currently_falling = (rsi_mom is not None and rsi_mom < -2 and rsi_dir == "decreasing") if drop_required else True

                    sustained_fall = True
                    if require_sustained and len(rsi_hist) >= 3:
                        last3 = [r for _, r in rsi_hist[-3:]]
                        if sustained_fall_mode == "net":
                            consecutive    = last3[1] < last3[0] and last3[2] < last3[1]
                            net_lower      = last3[2] < last3[0]
                            sustained_fall = consecutive or net_lower
                        else:
                            sustained_fall = last3[1] < last3[0] and last3[2] < last3[1]

                    is_bull = touched_overbought and drop_found and current_below_max and currently_falling

                    if require_sustained:
                        is_bull = is_bull and sustained_fall

                    values = {
                        "touched_overbought": touched_overbought,
                        "max_rsi":            max_rsi_val,
                        "drop_found":         drop_found,
                        "max_drop":           max_drop,
                        "current_rsi":        current_rsi,
                        "rsi_direction":      rsi_dir,
                        "sustained_fall":     sustained_fall,
                        "sustained_mode":     sustained_fall_mode,
                    }
                    msg = f"RSI Overbought Momentum: {'✓' if is_bull else '✗'} (RSI {max_rsi_val:.0f}→{current_rsi:.0f})"

            elif indicator_type == "adx_regime":
                max_adx   = params.get("max_adx", 25)
                min_adx   = params.get("min_adx", 0)

                adx_value = getattr(trend, 'adx', None)
                if adx_value is None:
                    # ADX not yet in TrendData — fail gracefully rather than crash.
                    # Add 'adx: float = None' to your TrendData model and update
                    # the Pine webhook to send it.
                    is_bull = False
                    msg = "ADX regime: ✗ (no ADX data — add adx field to TrendData and Pine script)"
                else:
                    adx_value = float(adx_value)
                    below_max = adx_value <= max_adx
                    above_min = adx_value >= min_adx
                    is_bull = below_max and above_min

                    if is_bull:
                        msg = (
                            f"ADX regime: ✓ "
                            f"(ADX={adx_value:.1f} — ranging, need <={max_adx})"
                        )
                    else:
                        reason = f"ADX={adx_value:.1f} > {max_adx} (trending)" if not below_max else f"ADX={adx_value:.1f} < {min_adx} (dead)"
                        msg = f"ADX regime: ✗ ({reason})"

            elif indicator_type == "bb_width_regime":
                required_direction = params.get("required_direction", "not_expanding")
                lookback           = params.get("lookback", 4)
                expand_threshold_pct   = params.get("expand_threshold_pct", 0.08)
                contract_threshold_pct = params.get("contract_threshold_pct", 0.08)
                min_width          = params.get("min_width", None)

                width_change, width_direction, current_width = self._get_bb_width_trend(
                    symbol, timeframe, lookback,
                    expand_threshold_pct, contract_threshold_pct
                )

                if width_direction is None:
                    is_bull = False
                    msg = f"BB width regime: ✗ (insufficient BB history — need {lookback} candles)"
                elif min_width is not None and current_width < min_width:
                    is_bull = False
                    msg = (
                        f"BB width regime: ✗ "
                        f"(bands too narrow: width={current_width:.4f} < min_width={min_width})"
                    )
                else:
                    if required_direction == "not_expanding":
                        is_bull = width_direction != "expanding"
                    elif required_direction == "contracting":
                        is_bull = width_direction == "contracting"
                    elif required_direction == "stable":
                        is_bull = width_direction == "stable"
                    else:
                        is_bull = False

                    if is_bull:
                        msg = (
                            f"BB width regime: ✓ "
                            f"(bands {width_direction}, Δ={width_change:+.4f}/candle, "
                            f"width={current_width:.4f} — need {required_direction})"
                        )
                    else:
                        msg = (
                            f"BB width regime: ✗ "
                            f"(bands {width_direction}, Δ={width_change:+.4f}/candle, "
                            f"width={current_width:.4f} — need {required_direction})"
                        )

            elif indicator_type == "bb_pct_b_momentum":
                required_direction = params.get("required_direction", "not_rising")
                lookback           = params.get("lookback", 3)

                pct_b_change, pct_b_direction = self._get_pct_b_trend(symbol, timeframe, lookback)

                if pct_b_direction is None:
                    is_bull = False
                    msg = f"BB %B momentum: ✗ (insufficient BB history — need {lookback} candles)"
                else:
                    if required_direction == "not_rising":
                        is_bull = pct_b_direction != "rising"
                    elif required_direction == "falling":
                        is_bull = pct_b_direction == "falling"
                    elif required_direction == "flat":
                        is_bull = pct_b_direction == "flat"
                    else:
                        is_bull = False

                    direction_symbol = "↓" if pct_b_direction == "falling" else ("↑" if pct_b_direction == "rising" else "→")

                    if is_bull:
                        msg = (
                            f"BB %B momentum: ✓ "
                            f"(%B {direction_symbol} {pct_b_direction}, Δ={pct_b_change:+.3f} "
                            f"over {lookback} candles — need {required_direction})"
                        )
                    else:
                        msg = (
                            f"BB %B momentum: ✗ "
                            f"(%B {direction_symbol} {pct_b_direction}, Δ={pct_b_change:+.3f} "
                            f"over {lookback} candles — need {required_direction})"
                        )
			
            elif indicator_type == "rsi_momentum":
                min_momentum     = params.get("min_momentum", None)
                max_momentum     = params.get("max_momentum", None)
                lookback_candles = int(params.get("lookback_candles", 1))

                rsi_mom, rsi_dir = self._get_rsi_momentum(symbol, timeframe, lookback=lookback_candles)

                if rsi_mom is None:
                    is_bull = False
                    msg = f"RSI momentum: ✗ (insufficient RSI history)"
                else:
                    min_ok = (min_momentum is None) or (rsi_mom >= min_momentum)
                    max_ok = (max_momentum is None) or (rsi_mom <= max_momentum)
                    is_bull = min_ok and max_ok
                    arrow = "↑" if rsi_mom > 0 else ("↓" if rsi_mom < 0 else "→")
                    bound_str = (
                        f"{min_momentum:+.1f}.." if min_momentum is not None else ".."
                    ) + (f"{max_momentum:+.1f}" if max_momentum is not None else "")
                    msg = (
                        f"RSI momentum: {'✓' if is_bull else '✗'} "
                        f"{arrow}{rsi_mom:+.2f} [{rsi_dir}] "
                        f"(need {bound_str} over {lookback_candles} candle{'s' if lookback_candles != 1 else ''})"
                    )

            elif indicator_type == "atr_regime":
                # ATR14 (% of close) volatility gate on this timeframe. Skip when
                # ATR is above max_pct or below min_pct. Insufficient candle
                # history => pass (matches the old max_entry_atr_pct skip, which
                # only filtered once ATR was available). Use hard_stop:true so a
                # fail kills the whole signal and a pass adds one to the count
                # (offset by bumping min_*_indicators_required by one).
                max_pct = params.get("max_pct")
                min_pct = params.get("min_pct")
                period  = int(params.get("period", 14))
                atr_v = self.get_atr_pct(symbol, timeframe, period)
                if atr_v is None:
                    is_bull = True
                    msg = f"ATR regime: ✓ (n/a — <{period + 1} candles)"
                else:
                    below_max = (max_pct is None) or (atr_v <= float(max_pct))
                    above_min = (min_pct is None) or (atr_v >= float(min_pct))
                    is_bull = below_max and above_min
                    if is_bull:
                        msg = f"ATR regime: ✓ (ATR={atr_v:.2f}% in [{min_pct},{max_pct}])"
                    else:
                        reason = f"ATR={atr_v:.2f}% > {max_pct}" if not below_max else f"ATR={atr_v:.2f}% < {min_pct}"
                        msg = f"ATR regime: ✗ ({reason})"

            elif indicator_type == "distance_from_high":
                # Mirrors TrendCache.distance_from_high — bullish when price sits
                # between min/max % below the rolling high over the lookback
                # window. Default is the validated 7-day lookback (42 4h bars);
                # see the msg's "requested N but cache only holds M" note if
                # lookback_bars ever exceeds the candle-history retention cap.
                # params: { lookback_bars: 42, min_pct_below: 5.0, max_pct_below: 20.0 }
                lookback_bars = int(params.get("lookback_bars", 42))
                min_pct_below = float(params.get("min_pct_below", 5.0))
                max_pct_below = float(params.get("max_pct_below", 20.0))
                key = f"{symbol}_{timeframe}"
                candles = self._candle_history.get(key, [])
                window = candles[-lookback_bars:]
                min_needed = min(20, lookback_bars)
                if len(window) < min_needed:
                    is_bull = True
                    msg = f"Distance from high: ✓ (n/a — <{min_needed} candles)"
                else:
                    recent_high = max(c['high'] for c in window)
                    pct_below = (recent_high - current_price) / recent_high * 100
                    is_bull = min_pct_below <= pct_below <= max_pct_below
                    truncated = f", requested {lookback_bars} but cache only holds {len(window)}" if len(window) < lookback_bars else ""
                    msg = (f"Distance from high: {'✓' if is_bull else '✗'} "
                           f"({pct_below:.1f}% below {len(window)}-bar high {recent_high:.4f} "
                           f"— need {min_pct_below}-{max_pct_below}%{truncated})")

            else:
                is_bull = False
                msg = f"Unknown indicator type: {indicator_type}"

            results.append((is_bull, msg))
            indicator_groups_list.append(indicator_group)
            # Only ungrouped hard stops trigger an immediate fail here;
            # grouped indicators have their hard_stop evaluated at group level below.
            if hard_stop and not is_bull and indicator_group is None:
                hard_stop_failures.append(msg)

        if use_hard_stops and hard_stop_failures:
            details = ", ".join(msg for _, msg in results)
            return False, f"HARD STOP: {'; '.join(hard_stop_failures)} ({details})"

        # ── Group evaluation ─────────────────────────────────────────────────
        groups_config = groups_config or {}
        grouped: dict = {}  # group_id -> [(is_bull, msg)]
        ungrouped_results = []  # (is_bull, msg)

        for (is_bull, msg), grp in zip(results, indicator_groups_list):
            if grp:
                grouped.setdefault(grp, []).append((is_bull, msg))
            else:
                ungrouped_results.append((is_bull, msg))

        details = ", ".join(msg for _, msg in results)

        group_pass_results = []
        for group_id, members in grouped.items():
            cfg = groups_config.get(group_id, {"require_all": False, "hard_stop": False})
            group_passed = (
                all(is_bull for is_bull, _ in members)
                if cfg.get("require_all", False)
                else any(is_bull for is_bull, _ in members)
            )
            if use_hard_stops and cfg.get("hard_stop", False) and not group_passed:
                member_msgs = "; ".join(msg for _, msg in members)
                return False, f"GROUP HARD STOP [{group_id}]: {member_msgs} ({details})"
            group_pass_results.append(group_passed)

        ungrouped_pass_count = sum(1 for is_bull, _ in ungrouped_results if is_bull)
        group_pass_count = sum(1 for p in group_pass_results if p)
        total_passes = ungrouped_pass_count + group_pass_count
        total_units = len(ungrouped_results) + len(group_pass_results)

        if total_passes >= min_indicators_required:
            return True, f"{total_passes}/{total_units} bullish ({details})"
        else:
            return False, f"Only {total_passes}/{total_units} bullish, need {min_indicators_required} ({details})"


# ===========================================================================
# ReplayRegimeFilter
# ===========================================================================

class ReplayRegimeFilter:
    """
    Self-contained regime filter for backtesting.

    Mirrors the logic of cache/regime_filter.py but operates entirely on a
    ReplayTrendCache — no singleton caches, no DB calls, no live price feed.

    ATR-spike check is omitted: ATR ratio is not stored in TrendAnalysisLog.

    Returns:
        "SAFE"      — conditions safe for trend entries
        "CHOPPY"    — range / indecision (good for range trading, skip for trend)
        "HIGH_RISK" — dangerous for all entries
    """

    # --- thresholds (same as live RegimeFilter) ---
    CHOP_EMA_RANGE_PCT      = 0.5
    CHOP_RSI_NEUTRAL        = (45, 55)
    ADX_TRENDING_THRESHOLD  = 22
    RSI_PANIC               = 30
    RSI_EUPHORIA            = 78
    MIN_VOLUME_RATIO        = 0.4
    MIN_VOLUME_RATIO_CONFIRM= 0.5
    DISTRIBUTION_VOLUME     = 1.5
    WHIPSAW_THRESHOLD       = 1.0    # HTF EMA diff % to consider "strong uptrend"
    REVERSAL_THRESHOLD      = -0.8   # LTF EMA diff % to consider "strong bearish reversal"
    SUSTAINED_TREND_SPREAD_PCT = 2.0 # regime-TF EMA20/50 spread that blocks counter-trend entries

    SHORT_STRATEGIES = ("short_trend_following", "short_mean_reversion")
    COUNTER_TREND_STRATEGIES = ("mean_reversion", "short_mean_reversion", "short_trend_following")
    # Legacy variant-file strategy names → live StrategyType values. Without this,
    # e.g. "mean_reversion_short" falls into the trend_following branch and the
    # euphoria/choppy blocks strangle a short profile whose setup IS overbought.
    STRATEGY_ALIASES = {"mean_reversion_short": "short_mean_reversion"}

    def __init__(self, replay_cache: "ReplayTrendCache"):
        self._cache = replay_cache

    def can_trade(
        self,
        symbol: str,
        primary_tf: str,
        confirm_tf: str,
        strategy_type: str = "trend_following",
    ) -> Tuple[bool, str]:
        """
        Returns (allowed, reason).
        Logic mirrors RegimeFilter.can_trade() per strategy type.
        """
        strategy_type = self.STRATEGY_ALIASES.get(strategy_type, strategy_type)
        regime, reason = self._get_regime(symbol, primary_tf, confirm_tf, strategy_type)

        if strategy_type == "range_trading":
            if regime == "HIGH_RISK":
                return False, reason
            return True, reason  # SAFE and CHOPPY both allowed for range
        elif strategy_type in self.COUNTER_TREND_STRATEGIES:
            # Counter-trend strategies: chop is their habitat — only HIGH_RISK blocks
            if regime == "HIGH_RISK":
                return False, reason
            return True, reason
        else:
            # trend_following
            if regime == "SAFE":
                return True, reason
            return False, reason  # CHOPPY or HIGH_RISK both blocked

    def _get_regime(
        self,
        symbol: str,
        primary_tf: str,
        confirm_tf: str,
        strategy_type: str,
    ) -> Tuple[str, str]:
        primary = self._cache.get(symbol, primary_tf)
        confirm = self._cache.get(symbol, confirm_tf)

        if primary is None:
            return "SAFE", f"No {primary_tf}m data — regime check skipped"

        high_risk, risk_reason = self._check_high_risk(
            symbol, primary, confirm, primary_tf, strategy_type
        )
        if high_risk:
            return "HIGH_RISK", f"🚫 {risk_reason}"

        choppy, chop_reason = self._check_choppy(
            symbol, primary, confirm, primary_tf, confirm_tf
        )
        if choppy:
            prefix = (
                "✅ - Good for Range Trading profile - "
                if strategy_type == "range_trading"
                else "⚠️"
            )
            return "CHOPPY", f"{prefix} {chop_reason}"

        return "SAFE", "✅ Market conditions safe"

    def _check_high_risk(
        self,
        symbol: str,
        primary,
        confirm,
        primary_tf: str,
        strategy_type: str,
    ) -> Tuple[bool, Optional[str]]:
        rsi = primary.rsi
        price = primary.price
        is_short = strategy_type in self.SHORT_STRATEGIES

        # 1. RSI panic / euphoria (direction-aware, mirrors live RegimeFilter)
        if is_short:
            if rsi < 20:
                return True, f"Extreme oversold - RSI {rsi:.0f} too low for shorting (bounce risk)"
            rsi_mom, _ = self._cache._get_rsi_momentum(symbol, primary_tf)
            if rsi_mom is not None and rsi_mom < -12:
                return True, f"RSI already in free-fall ({rsi_mom:.1f}) - short entry too late"
        elif strategy_type in ("trend_following", "range_trading"):
            if rsi < self.RSI_PANIC:
                return True, f"Panic zone - RSI {rsi:.0f}"
        elif strategy_type == "mean_reversion":
            if rsi < 20:
                return True, f"Extreme panic - RSI {rsi:.0f}"
            rsi_mom, _ = self._cache._get_rsi_momentum(symbol, primary_tf)
            if rsi_mom is not None and rsi_mom < -10:
                return True, f"Free fall - RSI dropping {rsi_mom:.1f}"

        if strategy_type == "short_mean_reversion":
            # Overbought is the setup — only block extreme RSI still surging
            if rsi > 85:
                rsi_mom, _ = self._cache._get_rsi_momentum(symbol, primary_tf)
                if rsi_mom is not None and rsi_mom > 8:
                    return True, f"Extreme overbought with surge - RSI {rsi:.0f} climbing ({rsi_mom:+.1f})"
        elif strategy_type == "short_trend_following":
            if rsi > 80:
                rsi_mom, _ = self._cache._get_rsi_momentum(symbol, primary_tf)
                if rsi_mom is not None and rsi_mom > 10:
                    return True, f"Euphoria surge - RSI {rsi:.0f} climbing fast ({rsi_mom:+.1f})"
        elif rsi > self.RSI_EUPHORIA:
            return True, f"Euphoria zone - RSI {rsi:.0f}"

        # 2. Sustained-trend / whipsaw detection (mirrors live RegimeFilter)
        primary_diff = ((primary.ema20 - primary.ema50) / primary.ema50) * 100

        if is_short:
            # Sustained rally on the regime TF — don't short into strength
            if primary_diff > self.SUSTAINED_TREND_SPREAD_PCT:
                return True, (
                    f"Sustained {primary_tf}m rally - EMA20/50 spread "
                    f"{primary_diff:+.2f}% > {self.SUSTAINED_TREND_SPREAD_PCT}%"
                )
            if strategy_type == "short_trend_following" and confirm is not None:
                # Short squeeze forming: strong bearish HTF + bullish LTF recovery
                confirm_diff = ((confirm.ema20 - confirm.ema50) / confirm.ema50) * 100
                if primary_diff < -self.WHIPSAW_THRESHOLD:
                    if confirm_diff > abs(self.REVERSAL_THRESHOLD):
                        if price > confirm.ema20:
                            return True, (
                                f"Short squeeze risk "
                                f"(HTF {primary_diff:+.2f}%, LTF {confirm_diff:+.2f}%)"
                            )
        elif strategy_type == "mean_reversion":
            # Sustained downtrend on the regime TF — don't dip-buy a falling market
            if primary_diff < -self.SUSTAINED_TREND_SPREAD_PCT:
                return True, (
                    f"Sustained {primary_tf}m downtrend - EMA20/50 spread "
                    f"{primary_diff:+.2f}% < -{self.SUSTAINED_TREND_SPREAD_PCT}%"
                )
        elif strategy_type not in ("range_trading",):
            if confirm is not None:
                confirm_diff = ((confirm.ema20 - confirm.ema50) / confirm.ema50) * 100
                if primary_diff > self.WHIPSAW_THRESHOLD:
                    if confirm_diff < self.REVERSAL_THRESHOLD:
                        if price <= confirm.ema20:
                            return True, (
                                f"Whipsaw reversal "
                                f"(HTF {primary_diff:+.2f}%, LTF {confirm_diff:+.2f}%)"
                            )

        # 3. Distribution: high volume + below VWAP + RSI decreasing (long strategies only —
        #    for shorts, high-volume selling is confirmation, not risk)
        if not is_short and primary.volume_ratio is not None:
            if primary.volume_ratio > self.DISTRIBUTION_VOLUME:
                if primary.vwap and price < primary.vwap:
                    rsi_mom, rsi_dir = self._cache._get_rsi_momentum(symbol, primary_tf)
                    if rsi_dir == "decreasing":
                        return True, (
                            f"Distribution pattern - "
                            f"high volume ({primary.volume_ratio:.1f}x) selling below VWAP"
                        )

        return False, None

    def _check_choppy(
        self,
        symbol: str,
        primary,
        confirm,
        primary_tf: str,
        confirm_tf: str,
    ) -> Tuple[bool, str]:
        issues = []
        price = primary.price

        # 1. EMA compression
        ema_diff_pct = abs(((primary.ema20 - primary.ema50) / primary.ema50) * 100)
        _, ema20_slope_dir = self._cache._get_ema_slope(symbol, primary_tf, "ema20")
        adx_value = getattr(primary, "adx", None)
        adx_is_trending = (
            adx_value is not None and float(adx_value) > self.ADX_TRENDING_THRESHOLD
        )

        if ema_diff_pct < self.CHOP_EMA_RANGE_PCT:
            if ema20_slope_dir != "rising" and not adx_is_trending:
                issues.append(f"60m EMAs compressed ({ema_diff_pct:.2f}%)")

        if confirm is not None:
            confirm_ema_diff = abs(
                ((confirm.ema20 - confirm.ema50) / confirm.ema50) * 100
            )
            if (confirm_ema_diff < self.CHOP_EMA_RANGE_PCT
                    and ema_diff_pct < self.CHOP_EMA_RANGE_PCT):
                if not adx_is_trending and ema20_slope_dir != "rising":
                    issues.append(
                        f"Both TFs compressed "
                        f"(60m: {ema_diff_pct:.2f}%, {confirm_tf}m: {confirm_ema_diff:.2f}%)"
                    )

        # 2. RSI stuck neutral
        rsi_low, rsi_high = self.CHOP_RSI_NEUTRAL
        if rsi_low < primary.rsi < rsi_high:
            rsi_mom, _ = self._cache._get_rsi_momentum(symbol, primary_tf)
            if rsi_mom is not None and abs(rsi_mom) < 1.0:
                issues.append(f"RSI stuck neutral ({primary.rsi:.0f}, momentum {rsi_mom:+.1f})")

        # 3. Dead volume on both TFs
        if (primary.volume_ratio is not None and confirm is not None
                and confirm.volume_ratio is not None):
            if (primary.volume_ratio < self.MIN_VOLUME_RATIO
                    and confirm.volume_ratio < self.MIN_VOLUME_RATIO_CONFIRM):
                issues.append(
                    f"Both TFs dead volume "
                    f"(HTF: {primary.volume_ratio:.2f}x, LTF: {confirm.volume_ratio:.2f}x)"
                )

        # 4. Price stagnation
        price_ema20_gap = abs((price - primary.ema20) / primary.ema20) * 100
        price_ema50_gap = abs((price - primary.ema50) / primary.ema50) * 100
        if price_ema20_gap < 0.3 and price_ema50_gap < 0.5:
            issues.append(f"Price stagnant (EMA20: {price_ema20_gap:.2f}%, EMA50: {price_ema50_gap:.2f}%)")
            issues.append("Price stagnation detected")

        if len(issues) >= 2:
            return True, f"Choppy ({len(issues)} issues): {'; '.join(issues)}"
        return False, ""


# ===========================================================================
# ProfileOpenPositionCap
# ===========================================================================

class ProfileOpenPositionCap:
    """
    Shared state object passed across per-symbol engine runs to enforce a
    max total concurrent open positions across all symbols for a profile
    (mirrors production max_open_positions_per_profile).

    Since per-symbol backtest runs are simulated sequentially rather than
    interleaved in real time, this records each executed trade's open/close
    time interval as it goes, then counts how many recorded intervals are
    still open at a candidate entry time before allowing a new entry.

    CAVEAT (same class of approximation as the old cluster cap): because each
    symbol's full date range is simulated in one pass before the next symbol
    starts, whichever symbol runs first in the list gets unconditional
    priority — its own trades are never capped against symbols simulated
    later, even if they'd truly overlap in calendar time. Later symbols ARE
    capped against everything recorded so far. This makes the blocked-count
    a directional signal, not an exact concurrent-across-symbols simulation.
    A fully accurate version would require interleaving all symbols
    chronologically instead of running each one's full history sequentially.
    """

    def __init__(self, max_positions: int):
        self.max_positions = max_positions
        self._intervals: List[List[Optional[datetime]]] = []  # [open_time, close_time]
        self._blocked: int = 0

    def can_enter(self, entry_time: datetime) -> bool:
        open_count = sum(
            1 for (open_t, close_t) in self._intervals
            if open_t <= entry_time and (close_t is None or close_t > entry_time)
        )
        return open_count < self.max_positions

    def record_entry(self, entry_time: datetime) -> int:
        self._intervals.append([entry_time, None])
        return len(self._intervals) - 1

    def record_exit(self, idx: int, exit_time: datetime) -> None:
        self._intervals[idx][1] = exit_time

    def record_blocked(self) -> None:
        self._blocked += 1

    @property
    def blocked_count(self) -> int:
        return self._blocked


# ===========================================================================
# ConsecutiveSLBreaker
# ===========================================================================

class ConsecutiveSLBreaker:
    """
    Profile-wide consecutive stop-loss circuit breaker (mirrors the live
    CircuitBreakerService consecutive-SL breaker).

    After `max_consecutive` stop_loss exits in a row — across every symbol the
    profile trades — new entries are blocked for `lock_hours`. Any non-SL exit
    resets the streak, and triggering resets it too, so once the pause expires
    it takes a fresh full streak to re-trigger.

    Share one instance across all symbol runs for a profile (pass it into
    BacktestEngine.run via `sl_breaker`, same pattern as profile_cap).
    Blocking is recomputed chronologically from every close recorded so far,
    so it carries the same cross-symbol caveat as ProfileOpenPositionCap:
    symbols simulated later see earlier symbols' closes, but not vice versa.
    """

    def __init__(self, max_consecutive: int, lock_hours: float = 24.0):
        self.max_consecutive = max_consecutive
        self.lock_hours      = lock_hours
        self._closes: List[Tuple[datetime, str]] = []   # (close_time, exit_reason)
        self._blocked = 0

    def record_close(self, close_time: datetime, reason: str) -> None:
        self._closes.append((close_time, reason))

    def is_blocked(self, entry_time: datetime) -> bool:
        """Replay recorded closes in time order; True if entry_time falls in a pause window."""
        streak = 0
        lock_until: Optional[datetime] = None
        for close_time, reason in sorted(self._closes, key=lambda c: c[0]):
            if close_time >= entry_time:
                break
            if reason == "stop_loss":
                streak += 1
                if streak >= self.max_consecutive:
                    lock_until = close_time + timedelta(hours=self.lock_hours)
                    streak = 0
            else:
                streak = 0
        return bool(lock_until and entry_time < lock_until)

    def record_blocked(self) -> None:
        self._blocked += 1

    @property
    def blocked_count(self) -> int:
        return self._blocked


# ===========================================================================
# BacktestProfile
# ===========================================================================

class BacktestProfile:
    """
    Lightweight profile wrapper that mirrors the attributes signal_generator
    reads off TradingProfile, but is fully constructed from a plain dict
    (so it works without touching the database at all).
    """

    DEFAULTS = {
        "strategy_type":              "trend_following",
        "trend_timeframe":            "60",
        "entry_timeframe":            "15",
        "use_trend_filter":           True,
        "use_entry_filter":           True,
        "use_atr_filter":             False,
        "use_market_regime_filter":   False,
        # Regime check TF override (e.g. "240"). None = strategy-based default:
        # entry TF for mean reversion strategies, trend TF otherwise (mirrors SignalGenerator).
        "regime_timeframe":           None,
        "min_signal_confidence":      70.0,
        "min_volume_ratio":           1.1,
        "min_indicators_required":    2,
        "min_entry_indicators_required": 2,
        "take_profit_pct":            0.8,
        "stop_loss_pct":              0.7,
        "trailing_stop_pct":          0.5,
        "arm_trailing_stop_pct":      0.5,
        "use_trailing_stop":          True,
        "trend_indicators":           [],
        "entry_indicators":           [],
        "trend_indicator_groups":     None,
        "entry_indicator_groups":     None,
        "trading_hours":              None,
        "max_open_positions_per_profile": None,
        "max_position_hours":         None,
        # Fill realism — prod stop fills average ~0.2% beyond the stop price
        # (market order fires after price has already crossed the SL level).
        # taker_fee_pct defaults to 0 because prod's profit_pct is price-based
        # (fees excluded); set it per-side to model net PnL instead.
        "stop_loss_slippage_pct":     0.2,
        "taker_fee_pct":              0.0,
        # Consecutive stop-loss circuit breaker (mirrors live CircuitBreakerService):
        # after N straight stop_loss exits, block new entries for lock_hours.
        # None/0 disables.
        "max_consecutive_stop_losses": None,
        "consecutive_sl_lock_hours":   24,
        # Trend invalidation exit controls (mirrors production position_manager logic)
        "use_trend_invalidation_exit":        True,
        "trend_invalidation_indicators":      "trend",   # "trend" | "entry" | "exit"
        "min_position_age_for_trend_check":   0,         # minutes; 0 = check immediately
        "exit_indicators":                    None,
        "min_exit_indicators_required":       1,
        "exit_timeframe":                     None,
        # ATR-scaled exits (opt-in). When set, the stop / target are sized in
        # units of the entry-TF ATR14 instead of a fixed % of price, so a
        # high-volatility symbol gets a proportionally wider stop. Trailing
        # geometry scales with the resulting target. None = use the fixed pcts.
        "atr_stop_mult":              None,
        "atr_tp_mult":                None,
        "atr_floor_pct":              0.15,   # clamp: ignore implausibly calm ATR
        "atr_ceiling_pct":            2.0,    # clamp: cap freak-volatility stops
        # Volatility band for ENTRY (skip the trade, vs atr_stop_mult which
        # resizes the stop). None = no volatility gate.
        "max_entry_atr_pct":          None,
        "min_entry_atr_pct":          None,
    }

    def __init__(self, name: str, config: dict):
        self.name         = name
        self.display_name = config.get("display_name", name)
        merged            = {**self.DEFAULTS, **config}
        for k, v in merged.items():
            setattr(self, k, v)

    @classmethod
    def from_dict(cls, name: str, config: dict) -> "BacktestProfile":
        return cls(name, config)

    def copy_with(self, overrides: dict) -> "BacktestProfile":
        """Return a new profile with specific keys overridden."""
        base = {k: getattr(self, k) for k in self.DEFAULTS}
        base["display_name"] = self.display_name
        base.update(overrides)
        return BacktestProfile(self.name, base)


# ===========================================================================
# TrendData reconstruction from TrendAnalysisLog row
# ===========================================================================

def row_to_trend_data(row, prev_row=None):
    """
    Build a TrendData-compatible object from a TrendAnalysisLog ORM row.

    TrendData needs at minimum:
        .symbol, .timeframe, .price, .rsi, .ema20, .ema50,
        .vwap, .volume_ratio, .bb (with .bb_upper/.bb_lower/.bb_basis),
        .prev_candle (with .prev_open/.prev_high/.prev_low/.prev_close),
        .timestamp (set by ReplayTrendCache.feed())

    We create a simple namespace object rather than importing TrendData
    directly to keep this file usable in isolation / tests.
    """

    class _BB:
        def __init__(self, upper, lower, basis):
            self.bb_upper = upper
            self.bb_lower = lower
            self.bb_basis = basis

    class _PrevCandle:
        def __init__(self, o, h, lo, c):
            self.prev_open  = o
            self.prev_high  = h
            self.prev_low   = lo
            self.prev_close = c

    class _TrendData:
        pass
    td = _TrendData()
    td.symbol     = row.symbol
    td.timeframe  = row.timeframe
    td.price      = float(row.close)   # use closed candle close as "current price"
    td.rsi        = float(row.rsi)     if row.rsi    is not None else 50.0
    td.ema20      = float(row.ema20)   if row.ema20  is not None else float(row.close)
    td.ema50      = float(row.ema50)   if row.ema50  is not None else float(row.close)
    td.vwap       = float(row.vwap)    if row.vwap   is not None else float(row.close)
    td.volume_ratio = float(row.volume_ratio) if row.volume_ratio is not None else None
    td.adx          =float(row.adx)    if row.adx   is not None else None
    # Raw volume also available if needed
    td.volume = float(row.volume) if row.volume is not None else None

    # Bollinger Bands
    if row.bb_upper is not None and row.bb_lower is not None:
        td.bb = _BB(float(row.bb_upper), float(row.bb_lower),
                    float(row.bb_basis) if row.bb_basis is not None else None)
    else:
        td.bb = None

    # Previous candle (needed for reversal_candle indicator)
    # We use the *previous row* as the prev_candle for the current row.
    if prev_row is not None:
        td.prev_candle = _PrevCandle(
            float(prev_row.open), float(prev_row.high),
            float(prev_row.low),  float(prev_row.close)
        )
    else:
        # Fall back to the current row's own OHLC
        td.prev_candle = _PrevCandle(
            float(row.open), float(row.high), float(row.low), float(row.close)
        )

    # Raw OHLC stored directly too (used as fallback in reversal_candle handler)
    td.open  = float(row.open)
    td.high  = float(row.high)
    td.low   = float(row.low)
    td.close = float(row.close)

    td.timestamp          = None  # will be set by feed()
    td.indicators_changed = None  # let ReplayTrendCache decide

    return td





# ===========================================================================
# BacktestTrade  (single simulated trade record)
# ===========================================================================

@dataclass
class BacktestTrade:
    symbol:        str
    entry_time:    datetime
    entry_price:   float
    exit_time:     Optional[datetime] = None
    exit_price:    Optional[float]    = None
    exit_reason:   str                = ""
    pnl_pct:       float              = 0.0
    won:           bool               = False

    # Snapshot of indicators at entry / exit (for analysis)
    entry_details: Dict[str, Any]     = field(default_factory=dict)
    exit_details:  Dict[str, Any]     = field(default_factory=dict)

    @property
    def hold_minutes(self) -> Optional[float]:
        if self.entry_time and self.exit_time:
            return (self.exit_time - self.entry_time).total_seconds() / 60
        return None

    @property
    def outcome_icon(self) -> str:
        if self.exit_price is None:
            return "⏳"
        return "✅" if self.won else "❌"

    def to_dict(self) -> dict:
        d = self.entry_details
        e = self.exit_details
        return {
            "entry_time":   self.entry_time.isoformat() if self.entry_time else None,
            "entry_price":  self.entry_price,
            "exit_time":    self.exit_time.isoformat()  if self.exit_time  else None,
            "exit_price":   self.exit_price,
            "exit_reason":  self.exit_reason,
            "pnl_pct":      round(self.pnl_pct, 4),
            "hold_minutes": round(self.hold_minutes, 1) if self.hold_minutes is not None else None,
            "won":          self.won,
            "confidence":   d.get("confidence"),
            "volume_ratio": d.get("volume_ratio"),
            "rsi":          d.get("rsi"),
            "ema20":        d.get("ema20"),
            "ema50":        d.get("ema50"),
            "adx":          d.get("adx"),
            "vwap":         d.get("vwap"),
            "bb_pct_b":     d.get("bb_pct_b"),
            "htf_rsi":      d.get("htf_rsi"),
            "htf_ema20":    d.get("htf_ema20"),
            "htf_ema50":    d.get("htf_ema50"),
            "htf_adx":      d.get("htf_adx"),
            # Indicator snapshot at close (for diagnosing what went wrong)
            "exit_rsi":       e.get("rsi"),
            "exit_ema20":     e.get("ema20"),
            "exit_ema50":     e.get("ema50"),
            "exit_adx":       e.get("adx"),
            "exit_vwap":      e.get("vwap"),
            "exit_bb_pct_b":  e.get("bb_pct_b"),
            "exit_htf_rsi":   e.get("htf_rsi"),
            "exit_htf_ema20": e.get("htf_ema20"),
            "exit_htf_ema50": e.get("htf_ema50"),
            "exit_htf_adx":   e.get("htf_adx"),
        }


# ===========================================================================
# BacktestResult
# ===========================================================================

@dataclass
class BacktestResult:
    profile_name:    str
    symbol:          str
    start:           datetime
    end:             datetime
    trades:          List[BacktestTrade] = field(default_factory=list)
    signals_fired:    int = 0
    regime_blocked:   int = 0
    profile_cap_blocked: int = 0
    sl_breaker_blocked:  int = 0
    rows_processed:   int = 0
    profile_params:  Dict[str, Any] = field(default_factory=dict)

    # ---- computed properties ------------------------------------------------

    @property
    def total_trades(self) -> int:
        return len([t for t in self.trades if t.exit_price is not None])

    @property
    def win_rate(self) -> float:
        closed = [t for t in self.trades if t.exit_price is not None]
        if not closed:
            return 0.0
        return sum(1 for t in closed if t.won) / len(closed)

    @property
    def avg_pnl_pct(self) -> float:
        closed = [t for t in self.trades if t.exit_price is not None]
        if not closed:
            return 0.0
        return sum(t.pnl_pct for t in closed) / len(closed)

    @property
    def total_pnl_pct(self) -> float:
        return sum(t.pnl_pct for t in self.trades if t.exit_price is not None)

    @property
    def max_drawdown_pct(self) -> float:
        """Largest single losing trade as a proxy for drawdown."""
        losses = [t.pnl_pct for t in self.trades if t.exit_price is not None and not t.won]
        return min(losses) if losses else 0.0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl_pct for t in self.trades if t.exit_price is not None and t.pnl_pct > 0)
        gross_loss   = abs(sum(t.pnl_pct for t in self.trades if t.exit_price is not None and t.pnl_pct < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")

    @property
    def exit_reason_breakdown(self) -> Dict[str, int]:
        reasons: Dict[str, int] = {}
        for t in self.trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        return reasons

    def summary(self) -> str:
        lines = [
            f"{'='*60}",
            f"Backtest: {self.profile_name} | {self.symbol}",
            f"Period  : {self.start.date()} → {self.end.date()}",
            f"Rows    : {self.rows_processed}",
            f"Signals : {self.signals_fired}",
            f"Regime⛔ : {self.regime_blocked}",
            f"ProfileCap⛔: {self.profile_cap_blocked}",
            f"SLBreaker⛔: {self.sl_breaker_blocked}",
            f"Trades  : {self.total_trades}",
            f"Win rate: {self.win_rate:.1%}",
            f"Avg P&L : {self.avg_pnl_pct:+.2f}%",
            f"Total   : {self.total_pnl_pct:+.2f}%",
            f"Max loss: {self.max_drawdown_pct:+.2f}%",
            f"Prof Fct: {self.profit_factor:.2f}x",
            f"Exits   : {self.exit_reason_breakdown}",
        ]
        if self.profile_params:
            lines.append(f"Params  : {self.profile_params}")
        lines.append("="*60)
        return "\n".join(lines)

    def trade_log(self, show_indicators: bool = True) -> str:
        """
        Per-trade breakdown table. Call after summary() for the full picture.

            print(result.summary())
            print(result.trade_log())

        show_indicators: include confidence / RSI / volume columns captured at entry
        """
        closed = [t for t in self.trades if t.exit_price is not None]
        open_t = [t for t in self.trades if t.exit_price is None]

        if not closed and not open_t:
            return "  (no trades in period)"

        # Build header
        base_hdr = (
            f"  {'#':>3}  {'Entry':>14}  {'Exit':>14}  "
            f"{'Buy':>9}  {'Sell':>9}  {'PnL%':>6}  {'Hold':>5}  {'Exit reason':<15}"
        )
        ind_hdr = f"  {'Conf':>5}  {'Vol':>5}  {'RSI':>5}" if show_indicators else ""
        header  = base_hdr + ind_hdr
        sep     = "  " + "─" * (len(header) - 2)

        lines = [header, sep]

        for i, t in enumerate(closed, 1):
            entry_s = t.entry_time.strftime("%m-%d %H:%M") if t.entry_time else "—"
            exit_s  = t.exit_time.strftime("%m-%d %H:%M")  if t.exit_time  else "—"
            hold_s  = f"{t.hold_minutes:.0f}m"             if t.hold_minutes is not None else "—"
            line = (
                f"  {i:>3}{t.outcome_icon} "
                f"{entry_s:>14}  {exit_s:>14}  "
                f"{t.entry_price:>9.4f}  {t.exit_price:>9.4f}  "
                f"{t.pnl_pct:>+6.2f}%  {hold_s:>5}  {t.exit_reason:<15}"
            )
            if show_indicators:
                conf = t.entry_details.get("confidence")
                vol  = t.entry_details.get("volume_ratio")
                rsi  = t.entry_details.get("rsi")
                line += (
                    f"  {f'{conf:.0f}%' if conf is not None else '—':>5}"
                    f"  {f'{vol:.1f}x' if vol is not None else '—':>5}"
                    f"  {f'{rsi:.0f}' if rsi is not None else '—':>5}"
                )
            lines.append(line)

        if open_t:
            for t in open_t:
                entry_s = t.entry_time.strftime("%m-%d %H:%M") if t.entry_time else "—"
                lines.append(
                    f"  ⏳   {entry_s:>14}  {'(still open)':>14}  "
                    f"{t.entry_price:>9.4f}  {'—':>9}  {'—':>7}  {'—':>5}  open"
                )

        # Footer totals row
        wins   = sum(1 for t in closed if t.won)
        losses = len(closed) - wins
        lines.append(sep)
        lines.append(
            f"  {'':>3}   {'':>14}  {'':>14}  "
            f"{'':>9}  {'':>9}  "
            f"{self.total_pnl_pct:>+6.2f}%  {'':>5}  "
            f"{wins}W / {losses}L  (signals fired: {self.signals_fired})"
        )
        return "\n".join(lines)

    def to_csv(self, filepath: str):
        """Export per-trade detail to CSV for spreadsheet cross-checking."""
        import csv
        fields = [
            "profile", "symbol", "trade_num", "outcome",
            "entry_time", "exit_time", "hold_minutes",
            "entry_price", "exit_price", "pnl_pct",
            "exit_reason", "confidence", "volume_ratio", "rsi_at_entry",
            # Indicator snapshot at close (for diagnosing what went wrong)
            "exit_rsi", "exit_ema20", "exit_ema50", "exit_adx", "exit_vwap", "exit_bb_pct_b",
            "exit_htf_rsi", "exit_htf_ema20", "exit_htf_ema50", "exit_htf_adx",
        ]
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for i, t in enumerate(self.trades, 1):
                e = t.exit_details
                writer.writerow({
                    "profile":       self.profile_name,
                    "symbol":        self.symbol,
                    "trade_num":     i,
                    "outcome":       "WIN" if t.won else ("OPEN" if t.exit_price is None else "LOSS"),
                    "entry_time":    t.entry_time.isoformat() if t.entry_time else "",
                    "exit_time":     t.exit_time.isoformat()  if t.exit_time  else "",
                    "hold_minutes":  round(t.hold_minutes, 1) if t.hold_minutes else "",
                    "entry_price":   t.entry_price,
                    "exit_price":    t.exit_price or "",
                    "pnl_pct":       round(t.pnl_pct, 4),
                    "exit_reason":   t.exit_reason,
                    "confidence":    t.entry_details.get("confidence", ""),
                    "volume_ratio":  t.entry_details.get("volume_ratio", ""),
                    "rsi_at_entry":  t.entry_details.get("rsi", ""),
                    "exit_rsi":      e.get("rsi", ""),
                    "exit_ema20":    e.get("ema20", ""),
                    "exit_ema50":    e.get("ema50", ""),
                    "exit_adx":      e.get("adx", ""),
                    "exit_vwap":     e.get("vwap", ""),
                    "exit_bb_pct_b": e.get("bb_pct_b", ""),
                    "exit_htf_rsi":  e.get("htf_rsi", ""),
                    "exit_htf_ema20":e.get("htf_ema20", ""),
                    "exit_htf_ema50":e.get("htf_ema50", ""),
                    "exit_htf_adx":  e.get("htf_adx", ""),
                })
        print(f"[CSV] Trade log saved → {filepath}")


def _exit_cooldown_mins(
    reason: str,
    default_mins: int,
    tp_mins: int,
    sl_mins: int,
) -> int:
    """Return cooldown duration matching prod ReEntryManager logic."""
    if reason == "take_profit":
        return tp_mins
    if reason in ("stop_loss", "trend_invalidation"):
        # Trend invalidation is a signal-failure exit like a stop loss - trigger conditions failed
        return sl_mins
    return default_mins


# ===========================================================================
# BacktestEngine
# ===========================================================================

class BacktestEngine:
    """
    Core replay engine.

    Steps per timeframe row:
      1. Feed row into ReplayTrendCache
      3. For every HTF row (trend_timeframe), also feed it so trend filter has data
      4. When entry_timeframe row arrives → run is_bullish() checks
      5. If signal passes confidence threshold → open a simulated position
      6. For every subsequent entry_tf row → check TP / SL / trailing stop
      7. Force-close any open position at end of window

    Multi-timeframe support:
      The engine maintains a *shared* ReplayTrendCache keyed by (symbol, timeframe).
      All timeframes are loaded together and fed in strict timestamp order.
    """

    def __init__(self, db_session, profile: BacktestProfile, verbose: bool = False):
        self.db      = db_session
        self.profile = profile
        self.verbose = verbose
        self._tag    = f"[{profile.name}]"

    # ------------------------------------------------------------------
    # Trading hours filter
    # ------------------------------------------------------------------
    def _is_within_trading_hours(self, row_time: datetime) -> bool:
        """Return True if row_time falls within any enabled trading window."""
        hours = getattr(self.profile, "trading_hours", None)
        if not hours:
            return True

        today = row_time.weekday()  # 0=Mon … 6=Sun
        current_minutes = row_time.hour * 60 + row_time.minute

        for window in hours:
            if not window.get("enabled", True):
                continue
            if window.get("day_of_week") != today:
                continue
            try:
                sh, sm = map(int, window["start_time"].split(":"))
                eh, em = map(int, window["end_time"].split(":"))
            except (KeyError, ValueError, AttributeError):
                continue
            start_m = sh * 60 + sm
            end_m   = eh * 60 + em
            if start_m <= end_m:
                if start_m <= current_minutes < end_m:
                    return True
            else:  # window spans midnight
                if current_minutes >= start_m or current_minutes < end_m:
                    return True

        return False

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def run(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        price_mode: str = "auto",
        price_source: str = "candle",  # "candle" | "ticks"
        data_source: str = "log",      # "log"/"shadow" both read trend_analysis_log —
                                       # kept as synonyms for back-compat with existing
                                       # scripts/CLI flags from before the 2026-07 cutover,
                                       # when they were two different tables.
        shadow_source: Optional[str] = None,  # e.g. "binance:USDT"; None = most rows
        tick_source: str = "webhook",  # "webhook" = webhook_price_ticks (~2min sample, ~60d)
                                       # "path1m"  = price_path_shadow expanded to O/H/L/C
                                       #             (60 points per 15m bar, full history)
        profile_cap: Optional["ProfileOpenPositionCap"] = None,
        sl_breaker: Optional["ConsecutiveSLBreaker"] = None,
        on_missing_ticks: str = "error",  # "error" | "fallback" — what to do when
                                          # price_source="ticks" but the ticks can't
                                          # cover the window. Default raises so a run
                                          # never silently changes its fill model.
    ) -> BacktestResult:
        from db.models import TrendAnalysisLog

        if data_source not in ("log", "shadow"):
            raise ValueError(f"data_source must be 'log' or 'shadow', got {data_source!r}")
        if on_missing_ticks not in ("error", "fallback"):
            raise ValueError(
                f"on_missing_ticks must be 'error' or 'fallback', got {on_missing_ticks!r}"
            )
        CandleModel = TrendAnalysisLog

        is_short = "short" in getattr(self.profile, "strategy_type", "")

        # Resolve profile-wide open-position cap: caller can pass a shared one
        # (multi-symbol run) or we create a local one from the profile setting
        # (single-symbol run).
        max_open_per_profile = getattr(self.profile, "max_open_positions_per_profile", None)
        effective_cap: Optional[ProfileOpenPositionCap] = profile_cap or (
            ProfileOpenPositionCap(max_open_per_profile)
            if max_open_per_profile else None
        )

        # Resolve consecutive-SL breaker the same way: shared across symbols
        # when passed in, otherwise local (per-symbol streaks only).
        max_consec_sl = getattr(self.profile, "max_consecutive_stop_losses", None)
        effective_sl_breaker: Optional[ConsecutiveSLBreaker] = sl_breaker or (
            ConsecutiveSLBreaker(
                int(max_consec_sl),
                float(getattr(self.profile, "consecutive_sl_lock_hours", 24) or 24),
            )
            if max_consec_sl else None
        )

        # Strategy-aware price mode:
        #   mean_reversion: signals fire mid-candle when price hits the extreme (low),
        #                   so evaluate indicators and enter at candle low.
        #   trend_following / others: signals fire at candle close, so use close.
        # Callers can override by passing price_mode explicitly.
        if price_mode == "auto":
            strategy_type = getattr(self.profile, "strategy_type", "trend_following")
            if "mean_reversion" in strategy_type:
                price_mode = "low"
            else:
                price_mode = "close"

        # Minutes per entry candle — used to compute candle time windows for ticks
        entry_tf_minutes = int(self.profile.entry_timeframe)

        # Pre-load price ticks if requested
        tick_times: List[float] = []    # epoch seconds, sorted
        tick_prices: List[float] = []
        if price_source == "ticks":
            if tick_source == "path1m":
                tick_times, tick_prices, ticks_available = self._load_price_path(symbol, start, end,
                                                                                 shadow_source)
            else:
                tick_times, tick_prices, ticks_available = self._load_price_ticks(symbol, start, end)
            # Ticks only exist from when webhook collection started. A long
            # backtest can therefore be "tick mode" while ticks cover only the
            # tail of the window, silently mixing fill models across the run.
            # Require the ticks to actually span the window before trusting them.
            shortfall = None
            if ticks_available and tick_times:
                covered = (tick_times[-1] - tick_times[0])
                wanted = (end - start).total_seconds()
                if wanted > 0 and covered / wanted < 0.9:
                    shortfall = (f"price ticks cover only {covered / wanted:.0%} of the "
                                 f"window — mixing fill models across the run")
                    ticks_available = False
            elif not ticks_available:
                shortfall = "no price ticks found for this symbol/window"

            if not ticks_available:
                table = ("price_path_shadow" if tick_source == "path1m"
                         else "webhook_price_ticks")
                detail = (f"{symbol} {start.date()}→{end.date()}: {shortfall} "
                          f"(tick_source={tick_source!r}, table={table})")
                if on_missing_ticks == "error":
                    raise TickDataUnavailable(
                        f"Tick mode requested but unusable — {detail}. "
                        f"Backfill {table}, pick another --tick-source, or re-run with "
                        f"price_source='candle' / --allow-candle-fallback to accept "
                        f"candle fills."
                    )
                print(f"[Backtest] WARNING: falling back to CANDLE fills — {detail}")
                price_source = "candle"
            else:
                print(f"[Backtest] Loaded {len(tick_times):,} price ticks for {symbol} ({price_source} mode)")

        result = BacktestResult(
            profile_name=self.profile.name,
            symbol=symbol,
            start=start,
            end=end,
            profile_params=self._profile_key_params(),
        )

        # Load all timeframes we need
        needed_timeframes = {self.profile.entry_timeframe}
        if self.profile.use_trend_filter:
            needed_timeframes.add(self.profile.trend_timeframe)
        regime_primary_tf, regime_confirm_tf = self._regime_timeframes()
        if getattr(self.profile, "use_market_regime_filter", False):
            needed_timeframes.add(regime_primary_tf)
            needed_timeframes.add(regime_confirm_tf)

        # trend_analysis_log carries a provenance `source` column (e.g.
        # "binance:USDT" vs "binance:USDC") — disambiguate so a mixed table
        # never silently interleaves two different quotes into one series.
        src = shadow_source
        if src is None:
            # Default to whichever source has the most rows for this symbol.
            src_row = (
                self.db.query(CandleModel.source, func.count(CandleModel.id))
                .filter(CandleModel.symbol == symbol,
                        CandleModel.timestamp >= start,
                        CandleModel.timestamp <= end)
                .group_by(CandleModel.source)
                .order_by(func.count(CandleModel.id).desc())
                .first()
            )
            src = src_row[0] if src_row else None

        # Pull WARMUP_BARS of extra history per timeframe so history-dependent
        # indicators (distance_from_high, atr_regime, rsi_reversal_momentum...)
        # are fully primed on the first bar we actually evaluate. Without this
        # the opening days of every window run with those indicators reporting
        # "n/a" — and several of them PASS when short of history, so a hard-stop
        # entry gate silently disappears at the start of the run.
        # Queried per timeframe so a 1D trend filter doesn't drag 100 days of
        # 15m candles along with it.
        all_rows = []
        warmup_from: Dict[str, datetime] = {}
        for tf in needed_timeframes:
            tf_start = start - timedelta(minutes=_tf_to_minutes(tf) * WARMUP_BARS)
            warmup_from[tf] = tf_start
            _q = (
                self.db.query(CandleModel)
                .filter(
                    CandleModel.symbol    == symbol,
                    CandleModel.timeframe == tf,
                    CandleModel.timestamp >= tf_start,
                    CandleModel.timestamp <= end,
                )
            )
            if src:
                _q = _q.filter(CandleModel.source == src)
            all_rows.extend(_q.all())
        all_rows.sort(key=lambda r: (r.timestamp, r.timeframe))

        if not all_rows:
            print(f"[Backtest] No data for {symbol} in range {start} → {end}")
            return result

        # Warn when the warmup itself is short — results near the window start
        # are then still running on partial history.
        for tf in sorted(needed_timeframes):
            got = sum(1 for r in all_rows
                      if r.timeframe == tf and _as_utc(r.timestamp) < start)
            if got < WARMUP_BARS:
                print(f"[Backtest] {symbol} {tf}: only {got}/{WARMUP_BARS} warmup bars "
                      f"available before {start:%Y-%m-%d} — history-dependent "
                      f"indicators may report n/a early in the run")

        # volume_ratio is stored directly in TrendAnalysisLog — no computation needed

        # Group into dict for quick lookup: {timeframe: [rows...]}
        by_tf: Dict[str, List] = {}
        for row in all_rows:
            by_tf.setdefault(row.timeframe, []).append(row)

        # Build entry_tf row index for fast "next N rows" lookup
        entry_tf_rows = by_tf.get(self.profile.entry_timeframe, [])

        cache     = ReplayTrendCache()
        regime_filter = (
            ReplayRegimeFilter(cache)
            if getattr(self.profile, "use_market_regime_filter", False)
            else None
        )
        open_pos  = None   # currently open simulated position (dict)
        # Two independent cooldown timers (mirrors prod behaviour):
        #   fire_cooldown_until  — set at entry; prevents re-signalling too soon after a buy
        #   reentry_cooldown_until — set at close; reason-based post-trade wait (ReEntryManager)
        # A new signal is blocked if *either* timer is still active.
        fire_cooldown_until:    Optional[datetime] = None
        reentry_cooldown_until: Optional[datetime] = None

        fire_cooldown_mins = getattr(self.profile, "signal_cooldown_minutes", 15)

        # Load re-entry cooldown durations from DB settings (mirrors ReEntryManager logic)
        cooldown_default_mins = 15
        cooldown_tp_mins      = 35
        cooldown_sl_mins      = 35
        try:
            from db.models import Settings as _Settings
            rows_settings = (
                self.db.query(_Settings)
                .filter(_Settings.profile_name == '0',
                        _Settings.setting_name.in_([
                            'cooldown_default_mins',
                            'cooldown_take_profit_mins',
                            'cooldown_stop_loss_mins',
                        ]))
                .all()
            )
            for s in rows_settings:
                if s.setting_name == 'cooldown_default_mins':
                    cooldown_default_mins = int(s.value)
                elif s.setting_name == 'cooldown_take_profit_mins':
                    cooldown_tp_mins = int(s.value)
                elif s.setting_name == 'cooldown_stop_loss_mins':
                    cooldown_sl_mins = int(s.value)
        except Exception:
            pass  # fall through to defaults

        # Per-profile overrides take priority over global settings (mirrors ReEntryManager logic)
        profile_sl_cooldown = getattr(self.profile, "sl_cooldown_minutes", None)
        profile_tp_cooldown = getattr(self.profile, "tp_cooldown_minutes", None)
        if profile_sl_cooldown is not None:
            cooldown_sl_mins = profile_sl_cooldown
        if profile_tp_cooldown is not None:
            cooldown_tp_mins = profile_tp_cooldown

        # Rolling ATR14 on the entry timeframe, maintained as we replay rows.
        # Used only when the profile opts in via atr_stop_mult / atr_tp_mult.
        atr_trs: List[float] = []
        atr_prev_close: Optional[float] = None
        atr_pct: Optional[float] = None

        # We replay ALL rows in timestamp order, feeding each timeframe into cache.
        for idx, row in enumerate(all_rows):
            prev_same_tf = self._find_prev_same_tf(all_rows, idx)
            td = row_to_trend_data(row, prev_same_tf)

            # Use volume_ratio directly from TrendAnalysisLog column
            td.volume_ratio = float(row.volume_ratio) if row.volume_ratio is not None else None

            cache.feed(td)
            result.rows_processed += 1

            # Only run signal logic on entry_timeframe candles
            if row.timeframe != self.profile.entry_timeframe:
                continue

            # Update rolling ATR14 (entry-TF) BEFORE any entry this candle, so the
            # ATR used to size a stop never includes the candle we enter on.
            # Runs during warmup too, so ATR is already valid on the first
            # tradeable bar rather than 14 bars into the window.
            if row.high is not None and row.low is not None and row.close is not None:
                _h, _l, _c = float(row.high), float(row.low), float(row.close)
                tr = (_h - _l) if atr_prev_close is None else max(
                    _h - _l, abs(_h - atr_prev_close), abs(_l - atr_prev_close)
                )
                atr_trs.append(tr)
                atr_prev_close = _c
                if len(atr_trs) >= 14 and _c:
                    atr_pct = (sum(atr_trs[-14:]) / 14) / _c * 100

            row_time = _as_utc(row.timestamp)

            # Warmup bars prime the cache and ATR only — no signals, no fills.
            if row_time < start:
                continue

            # ---- Manage open position ----
            if open_pos is not None:
                if price_source == "ticks":
                    candle_start_ts = row_time.timestamp()
                    candle_end_ts   = candle_start_ts + entry_tf_minutes * 60
                    candle_ticks    = self._get_candle_ticks(tick_times, tick_prices, candle_start_ts, candle_end_ts)
                    if candle_ticks:
                        exit_result = self._check_exit_from_prices(open_pos, candle_ticks)
                        if exit_result is None:
                            # Tick path skips _check_exit, so run the stale check here
                            exit_result = self._check_stale_exit(open_pos, row, row_time)
                    else:
                        exit_result = self._check_exit(open_pos, row)  # fallback: no ticks for this candle
                else:
                    exit_result = self._check_exit(open_pos, row)

                if exit_result:
                    pnl = self._net_pnl(open_pos["entry_price"], exit_result["price"], is_short)
                    open_pos["trade"].exit_price   = exit_result["price"]
                    open_pos["trade"].exit_time    = row_time
                    open_pos["trade"].exit_reason  = exit_result["reason"]
                    open_pos["trade"].pnl_pct      = pnl
                    open_pos["trade"].won          = pnl > 0
                    open_pos["trade"].exit_details = self._indicator_snapshot(cache, symbol, price=exit_result["price"])
                    if effective_cap and open_pos["cap_idx"] is not None:
                        effective_cap.record_exit(open_pos["cap_idx"], row_time)
                    if effective_sl_breaker:
                        effective_sl_breaker.record_close(row_time, exit_result["reason"])
                    reentry_cooldown_until = row_time + timedelta(minutes=_exit_cooldown_mins(
                        exit_result["reason"], cooldown_default_mins, cooldown_tp_mins, cooldown_sl_mins
                    ))
                    open_pos = None
                else:
                    # Candle mode: update trailing stop water mark from candle high/low.
                    # Tick mode: water mark is updated inside _check_exit_from_prices above.
                    if price_source == "candle" and self.profile.use_trailing_stop:
                        arm_pct = float(open_pos.get("eff_arm_pct", self.profile.arm_trailing_stop_pct)) / 100
                        if is_short:
                            if float(row.low) < open_pos["lowest_price"]:
                                open_pos["lowest_price"] = float(row.low)
                                if not open_pos["trailing_armed"]:
                                    if open_pos["lowest_price"] <= open_pos["entry_price"] * (1 - arm_pct):
                                        open_pos["trailing_armed"] = True
                        else:
                            if row.high > open_pos["highest_price"]:
                                open_pos["highest_price"] = float(row.high)
                                if not open_pos["trailing_armed"]:
                                    if open_pos["highest_price"] >= open_pos["entry_price"] * (1 + arm_pct):
                                        open_pos["trailing_armed"] = True

                    # Trend invalidation: exit if the chosen indicator set flips negative
                    use_ti = getattr(self.profile, "use_trend_invalidation_exit", True)
                    if use_ti:
                        min_age_mins = getattr(self.profile, "min_position_age_for_trend_check", 0)
                        position_age_mins = (row_time - open_pos["entry_time"]).total_seconds() / 60
                        if position_age_mins >= min_age_mins:
                            # Mirrors PositionManager._check_trend_invalidation. Keep the
                            # two in step — they are separate implementations of the same
                            # rule, and drift here shows up as prod/backtest exit mismatch.
                            ti_mode = getattr(self.profile, "trend_invalidation_indicators", "trend")
                            if ti_mode == "exit":
                                exit_inds = getattr(self.profile, "exit_indicators", None)
                                if exit_inds:
                                    ti_inds = exit_inds
                                    ti_min  = getattr(self.profile, "min_exit_indicators_required", 2)
                                    ti_tf   = getattr(self.profile, "exit_timeframe", None) or self.profile.entry_timeframe
                                else:
                                    # No exit set configured — prod falls back to the entry
                                    # set at one below the entry threshold.
                                    ti_inds = getattr(self.profile, "entry_indicators", None)
                                    ti_min  = max(1, self.profile.min_entry_indicators_required - 1)
                                    ti_tf   = self.profile.entry_timeframe
                            elif ti_mode == "entry":
                                ti_inds = getattr(self.profile, "entry_indicators", None)
                                ti_min  = max(1, self.profile.min_entry_indicators_required - 1)
                                ti_tf   = self.profile.entry_timeframe
                            elif ti_mode == "mean_reversion":
                                # Prod builds a synthetic rsi_reversal_momentum check from
                                # the global mean_rever_* settings. Defaults match the DB.
                                ti_inds = [{
                                    "type": "rsi_reversal_momentum",
                                    "params": {
                                        "lookback_candles": int(getattr(
                                            self.profile, "mean_rever_rsi_lookback_candles", 4)),
                                        "oversold_threshold": 60,
                                        "current_min": float(getattr(
                                            self.profile, "mean_rever_rsi_inval_threshold", 34)),
                                        "min_jump": 1,
                                        "require_sustained": False,
                                        "jump_required": False,
                                    },
                                }]
                                ti_min = 1
                                ti_tf  = self.profile.entry_timeframe
                            elif getattr(self.profile, "use_trend_filter", True):  # "trend"
                                ti_inds = self.profile.trend_indicators
                                # Prod drops the bar by one for invalidation: a position is
                                # only closed once the trend is *materially* worse than the
                                # bar that opened it, not merely one indicator short.
                                ti_min  = max(1, self.profile.min_indicators_required - 1)
                                ti_tf   = self.profile.trend_timeframe
                            else:
                                # trend mode with the trend filter off — nothing to check.
                                ti_inds, ti_min, ti_tf = None, 1, self.profile.trend_timeframe

                            if ti_inds:
                                trend_still_ok, ti_reason = cache.is_bullish(
                                    symbol,
                                    ti_tf,
                                    indicators_config=ti_inds,
                                    min_indicators_required=ti_min,
                                    # Invalidation scores every indicator instead of
                                    # bailing on the first hard-stop failure — one
                                    # hard-stop miss is not enough to close a position.
                                    use_hard_stops=False,
                                    groups_config=getattr(self.profile, "trend_indicator_groups", None),
                                    price_mode="close",
                                )
                                if not trend_still_ok:
                                    exit_price = float(row.close)
                                    pnl = self._net_pnl(open_pos["entry_price"], exit_price, is_short)
                                    open_pos["trade"].exit_price   = exit_price
                                    open_pos["trade"].exit_time    = row_time
                                    open_pos["trade"].exit_reason  = "trend_invalidation"
                                    open_pos["trade"].pnl_pct      = pnl
                                    open_pos["trade"].won          = pnl > 0
                                    open_pos["trade"].exit_details = self._indicator_snapshot(cache, symbol, price=exit_price)
                                    if effective_cap and open_pos["cap_idx"] is not None:
                                        effective_cap.record_exit(open_pos["cap_idx"], row_time)
                                    if effective_sl_breaker:
                                        effective_sl_breaker.record_close(row_time, "trend_invalidation")
                                    reentry_cooldown_until = row_time + timedelta(minutes=_exit_cooldown_mins(
                                        "trend_invalidation", cooldown_default_mins, cooldown_tp_mins, cooldown_sl_mins
                                    ))
                                    if self.verbose:
                                        print(f"{self._tag}[{row_time}] TREND_INVALIDATION ({ti_mode}) exit @ {exit_price:.4f} pnl={pnl:+.2f}% — {ti_reason}")
                                    open_pos = None
                                    continue

                    continue  # still in trade — skip signal logic

            # ---- Signal generation ----
            # Check trading hours
            if not self._is_within_trading_hours(row_time):
                if self.verbose:
                    print(f"[{row_time}] Outside trading hours — skipping")
                continue

            # Check cooldowns (fire cooldown OR re-entry cooldown blocks the next signal)
            if fire_cooldown_until and row_time < fire_cooldown_until:
                continue
            if reentry_cooldown_until and row_time < reentry_cooldown_until:
                continue

            # Consecutive-SL circuit breaker: profile paused after N straight stop losses
            if effective_sl_breaker and effective_sl_breaker.is_blocked(row_time):
                result.sl_breaker_blocked += 1
                effective_sl_breaker.record_blocked()
                if self.verbose:
                    print(f"{self._tag}[{row_time}] Consecutive-SL breaker active — skipping {symbol}")
                continue

            # Run market regime filter
            if regime_filter is not None:
                strategy_type = getattr(self.profile, "strategy_type", "trend_following")
                regime_ok, regime_reason = regime_filter.can_trade(
                    symbol,
                    regime_primary_tf,
                    regime_confirm_tf,
                    strategy_type=strategy_type,
                )
                if not regime_ok:
                    result.regime_blocked += 1
                    if self.verbose:
                        print(f"[{row_time}] Regime filter blocked: {regime_reason}")
                    continue

            # Run trend filter (HTF)
            # Always use close for the trend timeframe: when the 15m signal fires,
            # the HTF context is the last *completed* 60m candle, not its intra-candle wick.
            if self.profile.use_trend_filter:
                trend_ok, trend_reason = cache.is_bullish(
                    symbol,
                    self.profile.trend_timeframe,
                    indicators_config=self.profile.trend_indicators,
                    min_indicators_required=self.profile.min_indicators_required,
                    groups_config=getattr(self.profile, "trend_indicator_groups", None),
                    price_mode="close",
                )
                if not trend_ok:
                    if self.verbose:
                        print(f"{self._tag}[{row_time}] Trend filter failed: {trend_reason}")
                    continue

            # Run entry filter (execution TF)
            # For MR: check conditions against candle low (conditions are met at the wick
            # when the mid-candle webhook fires). Entry price is still at close — see below.
            if self.profile.use_entry_filter:
                entry_ok, entry_reason = cache.is_bullish(
                    symbol,
                    self.profile.entry_timeframe,
                    indicators_config=self.profile.entry_indicators,
                    min_indicators_required=self.profile.min_entry_indicators_required,
                    groups_config=getattr(self.profile, "entry_indicator_groups", None),
                    price_mode=price_mode,
                )
                if not entry_ok:
                    if self.verbose:
                        print(f"{self._tag}[{row_time}] Entry filter failed: {entry_reason}")
                    continue
            else:
                entry_reason = "entry filter off"

            # Volume check
            volume_ratio = float(row.volume_ratio) if row.volume_ratio is not None else None
            min_vol      = float(self.profile.min_volume_ratio)
            vol_score    = 1.0 if (volume_ratio and volume_ratio >= min_vol) else 0.3

            # Confidence score (simplified — mirrors signal_generator logic)
            trend_weight  = 40.0 if self.profile.use_trend_filter  else 0.0
            entry_weight  = 35.0 if self.profile.use_entry_filter   else 0.0
            volume_weight = 15.0
            safety_weight = 10.0
            max_conf      = trend_weight + entry_weight + volume_weight + safety_weight

            score = trend_weight + entry_weight + (volume_weight * vol_score)

            # Safety: RSI check (direction-aware)
            cached_trend = cache.get(symbol, self.profile.entry_timeframe)
            cached_htf   = cache.get(symbol, self.profile.trend_timeframe)
            if is_short:
                # For shorts: elevated RSI is confirmation; very low RSI is a warning
                if cached_trend and cached_trend.rsi > 55:
                    score += safety_weight
                elif cached_trend and cached_trend.rsi < 35:
                    score -= 30
            else:
                if cached_trend and cached_trend.rsi < 65:
                    score += safety_weight
                elif cached_trend and cached_trend.rsi > 80:
                    score -= 30

            confidence_pct = max(0.0, (score / max_conf) * 100) if max_conf > 0 else 0.0

            if confidence_pct < float(self.profile.min_signal_confidence):
                if self.verbose:
                    print(f"[{row_time}] Confidence too low: {confidence_pct:.1f}%")
                continue

            # Volatility ceiling/floor: skip the entry entirely when entry-TF ATR14
            # is outside the tradeable band. Distinct from atr_stop_mult — this
            # removes the trade rather than trying to survive it with a wider stop.
            max_entry_atr = getattr(self.profile, "max_entry_atr_pct", None)
            min_entry_atr = getattr(self.profile, "min_entry_atr_pct", None)
            if atr_pct is not None:
                if max_entry_atr and atr_pct > float(max_entry_atr):
                    if self.verbose:
                        print(f"{self._tag}[{row_time}] ATR {atr_pct:.2f}% > ceiling {max_entry_atr}% — skipping")
                    continue
                if min_entry_atr and atr_pct < float(min_entry_atr):
                    continue

            # SIGNAL — open position
            result.signals_fired += 1

            # Profile cap: skip if the profile already has max_open_positions_per_profile open
            if effective_cap and not effective_cap.can_enter(row_time):
                result.profile_cap_blocked += 1
                effective_cap.record_blocked()
                if self.verbose:
                    print(f"{self._tag}[{row_time}] Profile cap ({effective_cap.max_positions}) reached — skipping {symbol}")
                continue

            # Determine entry price and (for tick mode) which ticks remain after entry.
            if price_source == "ticks":
                candle_start_ts  = row_time.timestamp()
                candle_end_ts    = candle_start_ts + entry_tf_minutes * 60
                entry_candle_ticks = self._get_candle_ticks(tick_times, tick_prices, candle_start_ts, candle_end_ts)
                entry_price, entry_tick_idx = self._find_entry_tick(
                    entry_candle_ticks, float(row.close), price_mode
                )
            else:
                # Candle mode: always enter at candle close.
                # price_mode controls WHEN the signal condition is checked (e.g. candle low
                # for MR), but entry itself is at the candle close.
                entry_price        = float(row.close)
                entry_candle_ticks = []
                entry_tick_idx     = -1

            trade = BacktestTrade(
                symbol=symbol,
                entry_time=row_time,
                entry_price=entry_price,
                entry_details={
                    "confidence":    round(confidence_pct, 2),
                    "volume_ratio":  volume_ratio,
                    "reason":        entry_reason,
                    **self._indicator_snapshot(cache, symbol, price=entry_price),
                },
            )
            result.trades.append(trade)
            cap_idx = effective_cap.record_entry(row_time) if effective_cap else None

            # --- ATR-scaled TP/SL (opt-in) -------------------------------------
            # atr_stop_mult / atr_tp_mult express the stop and target in units of
            # the entry-TF ATR14 instead of a fixed % of price, so a high-vol
            # symbol gets a proportionally wider stop. Falls back to the fixed
            # pcts when the profile does not opt in or ATR is not yet available.
            eff_tp_pct = float(self.profile.take_profit_pct)
            eff_sl_pct = float(self.profile.stop_loss_pct)
            eff_trail_pct = float(self.profile.trailing_stop_pct)
            eff_arm_pct   = float(self.profile.arm_trailing_stop_pct)

            atr_sl_mult = getattr(self.profile, "atr_stop_mult", None)
            atr_tp_mult = getattr(self.profile, "atr_tp_mult", None)
            if atr_pct and (atr_sl_mult or atr_tp_mult):
                # Clamp ATR% so a single freak candle cannot produce an absurd stop.
                clamped_atr = min(max(atr_pct, float(getattr(self.profile, "atr_floor_pct", 0.15) or 0.15)),
                                  float(getattr(self.profile, "atr_ceiling_pct", 2.0) or 2.0))
                if atr_sl_mult:
                    eff_sl_pct = clamped_atr * float(atr_sl_mult)
                if atr_tp_mult:
                    eff_tp_pct = clamped_atr * float(atr_tp_mult)
                # Keep trailing geometry proportional to the (new) target.
                base_tp = float(self.profile.take_profit_pct) or 1.0
                eff_trail_pct = float(self.profile.trailing_stop_pct) * (eff_tp_pct / base_tp)
                eff_arm_pct   = float(self.profile.arm_trailing_stop_pct) * (eff_tp_pct / base_tp)

            if is_short:
                tp_price = entry_price * (1 - eff_tp_pct / 100)
                sl_price = entry_price * (1 + eff_sl_pct / 100)
            else:
                tp_price = entry_price * (1 + eff_tp_pct / 100)
                sl_price = entry_price * (1 - eff_sl_pct / 100)

            trade.entry_details["atr_pct"]    = round(atr_pct, 4) if atr_pct else None
            trade.entry_details["eff_tp_pct"] = round(eff_tp_pct, 4)
            trade.entry_details["eff_sl_pct"] = round(eff_sl_pct, 4)

            open_pos = {
                "trade":           trade,
                "entry_price":     entry_price,
                "tp_price":        tp_price,
                "sl_price":        sl_price,
                "eff_tp_pct":      eff_tp_pct,
                "eff_sl_pct":      eff_sl_pct,
                "eff_trail_pct":   eff_trail_pct,
                "eff_arm_pct":     eff_arm_pct,
                "trailing_armed":  False,
                "highest_price":   entry_price,  # long trailing high-water mark
                "lowest_price":    entry_price,  # short trailing low-water mark
                "entry_time":      row_time,
                "is_short":        is_short,
                "cap_idx":         cap_idx,
            }

            # Fire cooldown: block re-signalling the same symbol too soon after a buy
            fire_cooldown_until = row_time + timedelta(minutes=fire_cooldown_mins)

            if self.verbose:
                print(
                    f"{self._tag}[{row_time}] SIGNAL ✅ entry={entry_price:.4f} "
                    f"TP={tp_price:.4f} SL={sl_price:.4f} conf={confidence_pct:.1f}%"
                )

            # Tick mode: immediately check remaining ticks in the entry candle for exit.
            # This handles the realistic case where TP/SL is hit within the same candle
            # that the signal fired — particularly common for MR entries on volatile candles.
            if price_source == "ticks" and entry_tick_idx >= 0 and entry_candle_ticks:
                remaining = entry_candle_ticks[entry_tick_idx + 1:]
                if remaining:
                    same_candle_exit = self._check_exit_from_prices(open_pos, remaining)
                    if same_candle_exit:
                        sx_price = same_candle_exit["price"]
                        pnl = self._net_pnl(entry_price, sx_price, is_short)
                        trade.exit_price   = sx_price
                        trade.exit_time    = row_time  # same candle; exact minute unknown
                        trade.exit_reason  = same_candle_exit["reason"]
                        trade.pnl_pct      = pnl
                        trade.won          = pnl > 0
                        trade.exit_details = self._indicator_snapshot(cache, symbol, price=sx_price)
                        if effective_cap and open_pos["cap_idx"] is not None:
                            effective_cap.record_exit(open_pos["cap_idx"], row_time)
                        if effective_sl_breaker:
                            effective_sl_breaker.record_close(row_time, same_candle_exit["reason"])
                        reentry_cooldown_until = row_time + timedelta(minutes=_exit_cooldown_mins(
                            same_candle_exit["reason"], cooldown_default_mins, cooldown_tp_mins, cooldown_sl_mins
                        ))
                        open_pos = None
                        if self.verbose:
                            print(f"{self._tag}[{row_time}] SAME-CANDLE EXIT {same_candle_exit['reason']} @ {sx_price:.4f} pnl={pnl:+.2f}%")

        # Force-close any lingering open position at end of window
        if open_pos is not None:
            if price_source == "ticks" and tick_prices:
                last_price = tick_prices[-1]
                last_time  = end
            else:
                last_row   = entry_tf_rows[-1] if entry_tf_rows else all_rows[-1]
                last_price = float(last_row.close)
                last_time  = last_row.timestamp.replace(tzinfo=timezone.utc) \
                             if last_row.timestamp.tzinfo is None else last_row.timestamp
            pnl = self._net_pnl(open_pos["entry_price"], last_price, is_short)
            open_pos["trade"].exit_price   = last_price
            open_pos["trade"].exit_time    = last_time
            open_pos["trade"].exit_reason  = "end_of_window"
            open_pos["trade"].pnl_pct      = pnl
            if effective_cap and open_pos["cap_idx"] is not None:
                effective_cap.record_exit(open_pos["cap_idx"], last_time)
            open_pos["trade"].won          = pnl > 0
            open_pos["trade"].exit_details = self._indicator_snapshot(cache, symbol, price=last_price)

        return result

    # ------------------------------------------------------------------
    # Indicator snapshot — shared by entry and exit trade records so
    # post-mortem analysis can compare "why it fired" vs "why it closed"
    # ------------------------------------------------------------------
    def _indicator_snapshot(self, cache, symbol: str, price: Optional[float] = None) -> Dict[str, Any]:
        cached_ltf = cache.get(symbol, self.profile.entry_timeframe)
        cached_htf = cache.get(symbol, self.profile.trend_timeframe)

        bb_pct_b = None
        if price is not None and cached_ltf and cached_ltf.bb is not None:
            bb = cached_ltf.bb
            if bb.bb_upper is not None and bb.bb_lower is not None:
                bw = bb.bb_upper - bb.bb_lower
                if bw > 0:
                    bb_pct_b = round((price - bb.bb_lower) / bw, 3)

        return {
            "rsi":       cached_ltf.rsi   if cached_ltf else None,
            "ema20":     cached_ltf.ema20 if cached_ltf else None,
            "ema50":     cached_ltf.ema50 if cached_ltf else None,
            "adx":       cached_ltf.adx   if cached_ltf else None,
            "vwap":      cached_ltf.vwap  if cached_ltf else None,
            "bb_pct_b":  bb_pct_b,
            "htf_rsi":   cached_htf.rsi   if cached_htf else None,
            "htf_ema20": cached_htf.ema20 if cached_htf else None,
            "htf_ema50": cached_htf.ema50 if cached_htf else None,
            "htf_adx":   cached_htf.adx   if cached_htf else None,
        }

    # ------------------------------------------------------------------
    # PnL / fill helpers
    # ------------------------------------------------------------------
    def _net_pnl(self, entry_price: float, exit_price: float, is_short: bool) -> float:
        """Percent PnL net of per-side taker fees (taker_fee_pct, default 0)."""
        if is_short:
            gross = (entry_price - exit_price) / entry_price * 100
        else:
            gross = (exit_price - entry_price) / entry_price * 100
        return gross - 2.0 * float(getattr(self.profile, "taker_fee_pct", 0.0) or 0.0)

    def _slipped_sl_fill(self, pos: dict) -> float:
        """
        Stop-loss fill price including slippage. Prod fires a market order after
        price has already crossed the SL level, so fills land past the stop
        (measured avg ~0.2% on bullet_shorts_v15AI, Jun 30 – Jul 5 2026).
        """
        slip = float(getattr(self.profile, "stop_loss_slippage_pct", 0.0) or 0.0) / 100
        if pos.get("is_short", False):
            return pos["sl_price"] * (1 + slip)
        return pos["sl_price"] * (1 - slip)

    # ------------------------------------------------------------------
    # Exit logic — returns {"price": float, "reason": str} or None
    # ------------------------------------------------------------------
    def _check_exit(self, pos: dict, row) -> Optional[dict]:
        high  = float(row.high)
        low   = float(row.low)
        close = float(row.close)
        is_short = pos.get("is_short", False)

        if is_short:
            # Stop loss: price rose above SL
            if high >= pos["sl_price"]:
                return {"price": self._slipped_sl_fill(pos), "reason": "stop_loss", "candle_price": high}
            # Take profit: price fell to TP
            if low <= pos["tp_price"]:
                return {"price": pos["tp_price"], "reason": "take_profit", "candle_price": low}
            # Trailing stop: trail above the lowest seen price
            if self.profile.use_trailing_stop and pos["trailing_armed"]:
                trail_pct = float(pos.get("eff_trail_pct", self.profile.trailing_stop_pct)) / 100
                trail_sl  = pos["lowest_price"] * (1 + trail_pct)
                if high >= trail_sl:
                    return {"price": trail_sl, "reason": "trailing_stop", "candle_price": high}
        else:
            # Stop loss: price fell below SL
            if low <= pos["sl_price"]:
                return {"price": self._slipped_sl_fill(pos), "reason": "stop_loss", "candle_price": low}
            # Take profit: price rose to TP
            if high >= pos["tp_price"]:
                return {"price": pos["tp_price"], "reason": "take_profit", "candle_price": high}
            # Trailing stop: trail below the highest seen price
            if self.profile.use_trailing_stop and pos["trailing_armed"]:
                trail_pct = float(pos.get("eff_trail_pct", self.profile.trailing_stop_pct)) / 100
                trail_sl  = pos["highest_price"] * (1 - trail_pct)
                if low <= trail_sl:
                    return {"price": trail_sl, "reason": "trailing_stop", "candle_price": low}

        row_time = row.timestamp.replace(tzinfo=timezone.utc) \
                   if row.timestamp.tzinfo is None else row.timestamp
        return self._check_stale_exit(pos, row, row_time)

    def _check_stale_exit(self, pos: dict, row, row_time: datetime) -> Optional[dict]:
        """
        Stale-position exit — mirrors prod PositionManager._check_stale_position:
        after max_position_hours, exit only if the trade has made <=50% progress
        toward TP; a trade that is running is left to trail / hit TP.
        (Prod computes progress long-only; here it is direction-aware.)
        """
        max_hours = getattr(self.profile, "max_position_hours", None)
        if not max_hours:
            return None
        age_hours = (row_time - pos["entry_time"]).total_seconds() / 3600
        if age_hours < max_hours:
            return None

        close = float(row.close)
        if pos.get("is_short", False):
            profit_pct = (pos["entry_price"] - close) / pos["entry_price"] * 100
        else:
            profit_pct = (close - pos["entry_price"]) / pos["entry_price"] * 100
        progress_pct = profit_pct / float(pos.get("eff_tp_pct", self.profile.take_profit_pct)) * 100
        if progress_pct > 50:
            return None
        return {"price": close, "reason": "stale_position", "candle_price": close}

    # ------------------------------------------------------------------
    # Tick-based helpers
    # ------------------------------------------------------------------

    # Expanding 1m OHLC into a path is the same work for every variant run
    # against the same symbol/window, and run() is called once per variant per
    # symbol — 130+ times in a full sweep. Cache the expanded path so it is
    # built once. Keyed on the query, so correctness is unaffected.
    _PATH_CACHE: dict = {}
    _PATH_CACHE_MAX = 8

    def _load_price_path(
        self, symbol: str, start: datetime, end: datetime,
        shadow_source: Optional[str] = None,
    ) -> Tuple[List[float], List[float], bool]:
        """Build an intra-candle price path from stored 1m OHLC.

        Each 1m bar becomes four points (O/H/L/C, adverse extreme first), giving
        60 points per 15m candle versus ~7.5 from the webhook tick sample — and
        unlike the webhook ticks this backfills for years, which is what makes a
        realistic fill model possible on long backtests.
        """
        from db.models import PricePathShadow
        from services.candle_fetcher import expand_bar_to_path

        key = (symbol, start, end, shadow_source)
        hit = BacktestEngine._PATH_CACHE.get(key)
        if hit is not None:
            return hit

        q = (
            self.db.query(PricePathShadow.timestamp, PricePathShadow.open,
                          PricePathShadow.high, PricePathShadow.low,
                          PricePathShadow.close)
            .filter(
                PricePathShadow.symbol == symbol,
                PricePathShadow.timestamp >= start,
                PricePathShadow.timestamp <= end,
            )
        )
        if shadow_source:
            q = q.filter(PricePathShadow.source == shadow_source)
        rows = q.order_by(PricePathShadow.timestamp).all()
        if not rows:
            BacktestEngine._PATH_CACHE[key] = ([], [], False)
            return [], [], False

        times: List[float] = []
        prices: List[float] = []
        for ts, o, h, l, c in rows:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            for t, p in expand_bar_to_path(ts, float(o), float(h), float(l), float(c)):
                times.append(t)
                prices.append(p)

        if len(BacktestEngine._PATH_CACHE) >= BacktestEngine._PATH_CACHE_MAX:
            BacktestEngine._PATH_CACHE.pop(next(iter(BacktestEngine._PATH_CACHE)))
        BacktestEngine._PATH_CACHE[key] = (times, prices, True)
        return times, prices, True

    def _load_price_ticks(
        self, symbol: str, start: datetime, end: datetime
    ) -> Tuple[List[float], List[float], bool]:
        """
        Load webhook_price_ticks for symbol in [start, end], sorted by timestamp.
        Returns (tick_times_epoch, tick_prices, available).
        """
        from db.models import WebhookPriceTick
        rows = (
            self.db.query(WebhookPriceTick.timestamp, WebhookPriceTick.price)
            .filter(
                WebhookPriceTick.symbol    == symbol,
                WebhookPriceTick.timestamp >= start,
                WebhookPriceTick.timestamp <= end,
            )
            .order_by(WebhookPriceTick.timestamp)
            .all()
        )
        if not rows:
            return [], [], False
        tick_times, tick_prices = [], []
        for r in rows:
            ts = r.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            tick_times.append(ts.timestamp())
            tick_prices.append(float(r.price))
        return tick_times, tick_prices, True

    @staticmethod
    def _get_candle_ticks(
        tick_times: List[float], tick_prices: List[float],
        start_ts: float, end_ts: float,
    ) -> List[float]:
        """Return tick prices that fall within [start_ts, end_ts) (epoch seconds)."""
        lo = bisect_left(tick_times, start_ts)
        hi = bisect_left(tick_times, end_ts)   # exclusive upper bound
        return tick_prices[lo:hi]

    @staticmethod
    def _find_entry_tick(
        candle_ticks: List[float], close_price: float, price_mode: str
    ) -> Tuple[float, int]:
        """
        Choose which tick within the candle represents the realistic entry.

        MR / price_mode="low":
          Signals fire on the way DOWN when price first crosses the trigger level.
          We model this as the first tick that's at or below the candle close —
          i.e. the moment during the candle where price reached the level that
          the close price settled at, before any subsequent bounce.
          This places entry earlier and higher than the candle close, matching
          how live MR trades fill.

        Trend / price_mode="close":
          Enter at the last tick of the candle (candle close equivalent).

        Returns (entry_price, index_into_candle_ticks).
        index=-1 means no ticks available (caller should fall back to row.close).
        """
        if not candle_ticks:
            return close_price, -1

        if price_mode == "low":
            # First tick that's at or below the candle close = "on the way down"
            for i, price in enumerate(candle_ticks):
                if price <= close_price:
                    return price, i
            # All ticks stayed above close (unusual — price never dipped to close level)
            # Fall back to last tick
            return candle_ticks[-1], len(candle_ticks) - 1

        # Trend / default: last tick ≈ candle close
        return candle_ticks[-1], len(candle_ticks) - 1

    def _check_exit_from_prices(
        self, pos: dict, prices: List[float]
    ) -> Optional[dict]:
        """
        Iterate tick prices in chronological order.
        Updates trailing stop water mark as a side effect (mutates pos).
        Returns {"price": float, "reason": str} on first trigger, else None.
        """
        is_short  = pos.get("is_short", False)
        use_ts    = self.profile.use_trailing_stop
        arm_pct   = float(pos.get("eff_arm_pct", self.profile.arm_trailing_stop_pct)) / 100
        trail_pct = float(pos.get("eff_trail_pct", self.profile.trailing_stop_pct)) / 100

        for price in prices:
            # --- update water mark ---
            if use_ts:
                if is_short:
                    if price < pos["lowest_price"]:
                        pos["lowest_price"] = price
                        if not pos["trailing_armed"] and price <= pos["entry_price"] * (1 - arm_pct):
                            pos["trailing_armed"] = True
                else:
                    if price > pos["highest_price"]:
                        pos["highest_price"] = price
                        if not pos["trailing_armed"] and price >= pos["entry_price"] * (1 + arm_pct):
                            pos["trailing_armed"] = True

            # --- check exits ---
            if is_short:
                if price >= pos["sl_price"]:
                    return {"price": self._slipped_sl_fill(pos), "reason": "stop_loss"}
                if price <= pos["tp_price"]:
                    return {"price": pos["tp_price"], "reason": "take_profit"}
                if use_ts and pos["trailing_armed"]:
                    trail_sl = pos["lowest_price"] * (1 + trail_pct)
                    if price >= trail_sl:
                        return {"price": trail_sl, "reason": "trailing_stop"}
            else:
                if price <= pos["sl_price"]:
                    return {"price": self._slipped_sl_fill(pos), "reason": "stop_loss"}
                if price >= pos["tp_price"]:
                    return {"price": pos["tp_price"], "reason": "take_profit"}
                if use_ts and pos["trailing_armed"]:
                    trail_sl = pos["highest_price"] * (1 - trail_pct)
                    if price <= trail_sl:
                        return {"price": trail_sl, "reason": "trailing_stop"}

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _find_prev_same_tf(self, rows: list, idx: int):
        """Return the previous row with the same timeframe, or None."""
        current_tf = rows[idx].timeframe
        for i in range(idx - 1, -1, -1):
            if rows[i].timeframe == current_tf:
                return rows[i]
        return None

    def _profile_key_params(self) -> dict:
        keys = [
            "min_signal_confidence", "min_volume_ratio",
            "take_profit_pct", "stop_loss_pct",
            "trailing_stop_pct", "arm_trailing_stop_pct",
            "use_trailing_stop", "min_indicators_required",
            "min_entry_indicators_required",
            "stop_loss_slippage_pct", "taker_fee_pct",
            "max_consecutive_stop_losses",
            "use_market_regime_filter", "regime_timeframe",
        ]
        return {k: getattr(self.profile, k, None) for k in keys}

    def _regime_timeframes(self) -> Tuple[str, str]:
        """
        (primary, confirm) timeframes for the regime filter — mirrors
        SignalGenerator: entry TF for mean reversion strategies, trend TF
        otherwise; profile.regime_timeframe overrides the primary.
        """
        strategy = getattr(self.profile, "strategy_type", "trend_following")
        strategy = ReplayRegimeFilter.STRATEGY_ALIASES.get(strategy, strategy)
        if strategy in ("mean_reversion", "short_mean_reversion"):
            primary = self.profile.entry_timeframe
            confirm = self.profile.entry_timeframe
        else:
            primary = self.profile.trend_timeframe
            confirm = self.profile.entry_timeframe
        override = getattr(self.profile, "regime_timeframe", None)
        if override:
            primary = str(override)
        return primary, confirm


# ===========================================================================
# ParameterSweep
# ===========================================================================

class ParameterSweep:
    """
    Grid-search across profile parameter combinations.

    Example usage:
        sweep = ParameterSweep(db_session=db, base_profile=profile)
        results = sweep.run(
            symbol="SOL_USDC",
            start=datetime(2026, 2, 15, tzinfo=timezone.utc),
            end=datetime(2026, 2, 22, tzinfo=timezone.utc),
            param_grid={
                "min_signal_confidence": [65.0, 70.0, 75.0, 80.0],
                "min_volume_ratio":      [1.0, 1.1, 1.3],
            },
        )
        sweep.print_comparison(results)
    """

    def __init__(self, db_session, base_profile: BacktestProfile, verbose: bool = False):
        self.db           = db_session
        self.base_profile = base_profile
        self.verbose      = verbose

    def run(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        param_grid: Dict[str, List[Any]],
    ) -> List[BacktestResult]:
        keys   = list(param_grid.keys())
        values = list(param_grid.values())
        combos = list(itertools.product(*values))

        print(f"[Sweep] Running {len(combos)} combinations for {symbol}")
        results = []

        for combo in combos:
            overrides = dict(zip(keys, combo))
            profile   = self.base_profile.copy_with(overrides)
            engine    = BacktestEngine(self.db, profile, verbose=self.verbose)
            result    = engine.run(symbol, start, end)
            result.profile_params = overrides
            results.append(result)

        return results

    @staticmethod
    def print_comparison(results: List[BacktestResult], top_n: int = 10):
        """Print a ranked table of sweep results sorted by total P&L."""
        # Sort by profit_factor, then total_pnl_pct
        ranked = sorted(results, key=lambda r: (r.profit_factor, r.total_pnl_pct), reverse=True)

        header = (
            f"{'Rank':<5} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} "
            f"{'TotalPnL':>10} {'ProfFact':>9} {'Params'}"
        )
        print("\n" + "="*90)
        print("PARAMETER SWEEP RESULTS (ranked by profit factor)")
        print("="*90)
        print(header)
        print("-"*90)

        for rank, r in enumerate(ranked[:top_n], start=1):
            print(
                f"{rank:<5} {r.total_trades:>7} {r.win_rate:>6.1%} "
                f"{r.avg_pnl_pct:>7.2f}% {r.total_pnl_pct:>9.2f}% "
                f"{r.profit_factor:>9.2f}x  {r.profile_params}"
            )

        print("="*90)

    @staticmethod
    def to_csv(results: List[BacktestResult], filepath: str):
        """Export all sweep results to CSV for further analysis."""
        import csv

        if not results:
            return

        # Collect all param keys
        param_keys = sorted(set(k for r in results for k in r.profile_params))
        field_names = (
            ["profile", "symbol", "trades", "win_rate", "avg_pnl_pct",
             "total_pnl_pct", "max_drawdown", "profit_factor", "signals"]
            + param_keys
        )

        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=field_names)
            writer.writeheader()
            for r in results:
                row = {
                    "profile":        r.profile_name,
                    "symbol":         r.symbol,
                    "trades":         r.total_trades,
                    "win_rate":       round(r.win_rate, 4),
                    "avg_pnl_pct":    round(r.avg_pnl_pct, 4),
                    "total_pnl_pct":  round(r.total_pnl_pct, 4),
                    "max_drawdown":   round(r.max_drawdown_pct, 4),
                    "profit_factor":  round(r.profit_factor, 4),
                    "signals":        r.signals_fired,
                }
                row.update(r.profile_params)
                writer.writerow(row)

        print(f"[Sweep] CSV saved to {filepath}")