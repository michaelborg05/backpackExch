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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Lazy imports — only resolve when engine runs (keeps this file importable
# in isolation for tests).
# ---------------------------------------------------------------------------


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
                        # Keep last 6 candles — no pattern needs more than 3
                        if len(self._candle_history[key]) > 6:
                            self._candle_history[key] = self._candle_history[key][-6:]
            


        return indicators_changed

    # ------------------------------------------------------------------
    # Public API mirroring TrendCache (used by is_bullish internals)
    # ------------------------------------------------------------------
    def get(self, symbol: str, timeframe: str):
        """Return cached TrendData — no staleness check in replay mode."""
        return self._cache.get(f"{symbol}_{timeframe}")

    def is_bullish(
        self,
        symbol: str,
        timeframe: str,
        indicators_config=None,
        min_indicators_required: int = 2,
        return_structured: bool = False,
        use_hard_stops: bool = True,
    ):
        """
        Delegates to _validate_timeframe_indicators exactly as TrendCache does.
        We import and call the method directly to stay in sync.
        """
        trend = self.get(symbol, timeframe)
        if trend is None:
            if return_structured:
                return False, f"No trend data for {symbol} {timeframe}", []
            return False, f"No trend data for {symbol} {timeframe}"

        if indicators_config is None:
            indicators_config = [
                {"type": "ema_cross",      "params": {"fast": 20, "slow": 50}},
                {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 50}},
                {"type": "price_vs_vwap",  "params": {}},
            ]

        is_bull, summary, results = self._validate_timeframe_indicators(
            symbol, timeframe, trend, indicators_config, min_indicators_required, use_hard_stops
        )

        if return_structured:
            return is_bull, summary, results
        return is_bull, summary

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
    ) -> Tuple[Optional[float], Optional[str]]:
        key = f"{symbol}_{timeframe}"
        history = self._bb_history.get(key, [])

        if len(history) < 2:
            return None, None

        window = history[-lookback:] if len(history) >= lookback else history

        widths = []
        for entry in window:
            basis = entry.get('bb_basis')
            upper = entry.get('bb_upper')
            lower = entry.get('bb_lower')
            if basis and basis > 0 and upper is not None and lower is not None:
                widths.append((upper - lower) / basis)

        if len(widths) < 2:
            return None, None

        avg_change = (widths[-1] - widths[0]) / (len(widths) - 1)
        avg_width  = sum(widths) / len(widths)

        # Threshold scales with the typical width of this symbol/timeframe
        expand_threshold   =  avg_width * expand_threshold_pct
        contract_threshold = -avg_width * contract_threshold_pct

        if avg_change > expand_threshold:
            direction = "expanding"
        elif avg_change < contract_threshold:
            direction = "contracting"
        else:
            direction = "stable"

        return avg_change, direction

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
    ):
        """
        Full copy of TrendCache._validate_timeframe_indicators — all indicator
        types supported. Uses self._get_ema_slope / _get_rsi_momentum instead
        of the live cache versions.
        """
        from models.signal_validation import IndicatorResult

        results = []
        hard_stop_failures = []
        indicator_results  = []

        # Use the candle close as current price in replay (no live price cache)
        current_price = trend.price

        for indicator_config in indicators:
            indicator_type = indicator_config.get("type")
            params         = indicator_config.get("params", {})
            hard_stop      = params.get("hard_stop", False)
            is_bull        = False
            msg            = ""
            values         = {}

            # --- backward compat ---
            if indicator_type == "ema_alignment":
                indicator_type = "ema_cross"

            # === INDICATORS ================================================

            if indicator_type == "ema_cross":
                use_slope     = params.get("use_slope", False)
                min_slope_pct = params.get("min_slope_pct", 0.01)
                values["ema20"] = trend.ema20
                values["ema50"] = trend.ema50
                if use_slope:
                    slope_pct, slope_dir = self._get_ema_slope(symbol, timeframe, "ema20")
                    if slope_pct is None:
                        is_bull = trend.ema20 > trend.ema50
                        msg = f"EMA cross: {'✓' if is_bull else '✗'} (no slope data)"
                    else:
                        values["slope_pct"]       = slope_pct
                        values["slope_direction"] = slope_dir
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
                values["rsi"] = float(rsi)
                values["threshold"] = min_rsi
                if use_momentum:
                    rsi_mom, rsi_dir = self._get_rsi_momentum(symbol, timeframe)
                    values["momentum"]  = rsi_mom
                    values["direction"] = rsi_dir
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
                values  = {"price": current_price, "vwap": trend.vwap}
                msg     = f"Price vs VWAP: {'✓' if is_bull else '✗'} ({current_price:.4f}/{trend.vwap:.4f})"

            elif indicator_type == "price_vs_ema":
                ema_type    = params.get("ema", 20)
                min_gap_pct = params.get("min_gap_pct", 0.0)
                max_gap_pct = params.get("max_gap_pct", 0.0)
                ema_value   = trend.ema20 if ema_type == 20 else trend.ema50
                gap_pct     = ((current_price - ema_value) / ema_value) * 100
                values      = {"ema_value": ema_value, "gap_pct": gap_pct}
                is_bull     = gap_pct >= min_gap_pct
                if max_gap_pct > 0:
                    is_bull = is_bull and gap_pct <= max_gap_pct
                msg = f"Price vs EMA{ema_type}: {'✓' if is_bull else '✗'} ({gap_pct:+.2f}%)"

            elif indicator_type == "ema_slope":
                ema_type  = params.get("ema", 20)
                req_dir   = params.get("direction", "rising")
                min_slope = params.get("min_slope_pct", 0.01)
                ema_name  = f"ema{ema_type}"
                slope_pct, _ = self._get_ema_slope(symbol, timeframe, ema_name)
                if slope_pct is None:
                    is_bull = False
                    msg     = f"EMA{ema_type} slope: ✗ (no data)"
                    values["slope_pct"] = "NA"
                else:
                    values["slope_pct"] = float(slope_pct)
                    if req_dir == "rising":
                        is_bull   = slope_pct > min_slope
                        direction = "rising" if is_bull else "flat/falling"
                    elif req_dir == "not_falling":
                        is_bull   = slope_pct >= -min_slope
                        direction = "rising/flat" if is_bull else "falling"
                    else:
                        is_bull   = abs(slope_pct) <= min_slope
                        direction = "flat"
                    msg = f"EMA{ema_type} slope: {'✓' if is_bull else '✗'} ({direction} {slope_pct:+.3f}%)"

            elif indicator_type == "rsi_range":
                min_rsi  = params.get("min", 30)
                max_rsi  = params.get("max", 70)
                invert   = params.get("invert", False)
                mom_over = params.get("momentum_override_threshold", None)
                rsi_mom, rsi_dir = self._get_rsi_momentum(symbol, timeframe)
                in_range = min_rsi <= trend.rsi <= max_rsi
                values   = {"rsi": trend.rsi, "rsi_momentum": rsi_mom, "rsi_direction": rsi_dir, "within_range": in_range}
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
                values      = {"ema20": trend.ema20, "ema50": trend.ema50, "gap_pct": gap_pct}
                is_bull     = gap_pct >= min_gap_pct if mode == "min" else gap_pct <= max_gap_pct
                msg         = f"EMA gap: {'✓' if is_bull else '✗'} ({gap_pct:.2f}%)"

            elif indicator_type == "rsi_oversold":
                max_value      = params.get("max_value", 35)
                require_rising = params.get("require_rising", True)
                min_momentum   = params.get("min_momentum", 0.5)
                is_oversold    = trend.rsi < max_value
                values["rsi"] = trend.rsi
                if require_rising:
                    rsi_mom, rsi_dir = self._get_rsi_momentum(symbol, timeframe)
                    is_turning_up = (
                        rsi_mom is not None and
                        rsi_dir == "increasing" and
                        rsi_mom >= min_momentum
                    )
                    values.update({"rsi_momentum": rsi_mom, "rsi_direction": rsi_dir})
                    is_bull = is_oversold and is_turning_up
                    msg = f"RSI oversold: {'✓' if is_bull else '✗'} (RSI {trend.rsi:.1f}, turning={is_turning_up})"
                else:
                    is_bull = is_oversold
                    msg = f"RSI oversold: {'✓' if is_bull else '✗'} (RSI {trend.rsi:.1f}<{max_value})"

            elif indicator_type == "rsi_overbought":
                min_value   = params.get("min_value", 70)
                is_overbought = trend.rsi > min_value
                is_bull     = not is_overbought
                values["rsi"] = trend.rsi
                msg = f"RSI overbought: {'✓' if is_bull else '✗'} (RSI {trend.rsi:.1f})"

            elif indicator_type == "price_below_vwap":
                min_gap_pct = params.get("min_gap_pct", -1.0)
                max_gap_pct = params.get("max_gap_pct", -10.0)
                gap_pct     = ((current_price - trend.vwap) / trend.vwap) * 100 if trend.vwap else 0
                values      = {"price": current_price, "vwap": trend.vwap, "gap_pct": gap_pct}
                is_bull     = max_gap_pct <= gap_pct <= min_gap_pct
                msg         = f"Price below VWAP: {'✓' if is_bull else '✗'} ({gap_pct:+.2f}%)"

            elif indicator_type == "price_extended_below_ema":
                ema_type    = params.get("ema", 20)
                min_gap_pct = params.get("min_gap_pct", -2.0)
                max_gap_pct = params.get("max_gap_pct", -10.0)
                ema_value   = trend.ema20 if ema_type == 20 else trend.ema50
                gap_pct     = ((current_price - ema_value) / ema_value) * 100 if ema_value else 0
                values      = {"price": current_price, "ema": ema_value, "gap_pct": gap_pct}
                is_bull     = max_gap_pct <= gap_pct <= min_gap_pct
                msg         = f"Price below EMA{ema_type}: {'✓' if is_bull else '✗'} ({gap_pct:+.2f}%)"

            elif indicator_type == "bollinger_bands":
                band          = params.get("band", "lower")
                mode          = params.get("mode", "touch")
                tolerance_pct = params.get("tolerance_pct", 0.5)
                max_pct_b     = params.get("max_pct_b", 0.75)
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
                    values     = {"bb_lower": bb_lower, "bb_upper": bb_upper, "bb_basis": bb_basis,
                                  "price": current_price, "pct_b": round(pct_b, 4) if pct_b is not None else None}

                    if mode == "pct_b":
                        if pct_b is None:
                            is_bull, msg = False, "BB %B: ✗ (zero band width)"
                        else:
                            below_max = pct_b <= max_pct_b
                            above_min = (min_pct_b is None) or (pct_b >= min_pct_b)
                            is_bull = below_max and above_min

                            # Build readable range string for the log message
                            if min_pct_b is not None:
                                range_str = f"need {min_pct_b:.2f}–{max_pct_b:.2f}"
                            else:
                                range_str = f"need <={max_pct_b:.2f}"

                            msg = (
                                f"BB %B ({band}): {'✓' if is_bull else '✗'} "
                                f"(%B={pct_b:.2f} - {range_str})"
                            )

                    elif mode == "touch":
                        target   = bb_lower if band == "lower" else bb_upper
                        dist_pct = abs((current_price - target) / target) * 100 if target else 0
                        values["distance_pct"] = round(dist_pct, 4)
                        is_bull = dist_pct <= tolerance_pct
                        msg = f"BB {band} touch: {'✓' if is_bull else '✗'} ({dist_pct:.2f}% from band)"
                    else:  # breach
                        if lookback_candles > 0:
                            # Lookback mode: did price breach the band in the last N candles?
                            bb_key = f"{symbol}_{timeframe}"
                            bb_hist = self._bb_history.get(bb_key, [])
                            window = bb_hist[-lookback_candles:] if bb_hist else []
                            
                            values["lookback_candles"] = lookback_candles
                            values["history_candles"] = len(window)
                            
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
                    values["volume_ratio"] = None
                else:
                    is_bull = min_ratio <= trend.volume_ratio <= max_ratio
                    values["volume_ratio"] = trend.volume_ratio
                    msg = f"Volume spike: {'✓' if is_bull else '✗'} ({trend.volume_ratio:.2f}x)"

            elif indicator_type == "reversal_candle":
                pattern        = params.get("pattern", "doji")
                min_body_pct   = params.get("min_body_pct", 0.1)
                max_body_pct   = params.get("max_body_pct", 0.35)
                min_close_pct  = params.get("min_close_pct", 0.6)   # for bull_close

                values["pattern"] = pattern

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
                if pattern in ("hammer", "doji", "bull_close"):
                    if pc_o is None:
                        is_bull = False
                        msg = (
                            f"Reversal candle ({pattern}): ✗ "
                            f"(no prev_candle OHLC — check Pine script)"
                        )
                    else:
                        total, body, l_wick, u_wick, is_bull = _candle_metrics(pc_o, pc_h, pc_l, pc_c)
                        values.update({
                            "candle_open":  pc_o, "candle_high": pc_h,
                            "candle_low":   pc_l, "candle_close": pc_c,
                            "total_range":  round(total, 6),
                            "body_size":    round(body, 6),
                            "lower_wick":   round(l_wick, 6),
                            "upper_wick":   round(u_wick, 6),
                            "is_bull_candle": is_bull,
                        })

                        if total == 0:
                            is_bull = False
                            msg = f"Reversal candle ({pattern}): ✗ (zero-range candle)"

                        elif pattern == "hammer":
                            # Long lower wick (>=2x body), small upper wick (<=0.3x body),
                            # body at least min_body_pct of total range.
                            body_pct       = body / total
                            lw_ratio       = l_wick / body if body > 0 else 0
                            uw_ratio       = u_wick / body if body > 0 else 999
                            values["body_pct"]         = round(body_pct, 4)
                            values["lower_wick_ratio"] = round(lw_ratio, 4)
                            values["upper_wick_ratio"] = round(uw_ratio, 4)
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
                            values["body_pct"] = round(body_pct, 4)
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
                            values["close_position"] = round(close_pos, 4)
                            values["min_close_pct"]  = min_close_pct
                            is_bull = close_pos >= min_close_pct
                            msg = (
                                f"Bull close: {'✓' if is_bull else '✗'} "
                                f"(closed at {close_pos:.1%} of range, "
                                f"need >={min_close_pct:.1%})"
                            )

                # ── Two-closed-candle patterns ────────────────────────────────
                elif pattern in ("higher_low", "engulfing"):

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

                    values["data_source"] = data_source

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

                        values["c1_low"]       = c1["low"]
                        values["c2_low"]       = c2["low"]
                        values["higher_low"]   = hl_ok
                        values["require_bull"] = require_bull
                        values["c2_is_bull"]   = c2["close"] > c2["open"]

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

                            values.update({
                                "c1_open": c1["open"], "c1_close": c1["close"],
                                "c2_open": c2["open"], "c2_close": c2["close"],
                                "c1_bear": c1_bear,    "c2_bull":  c2_bull,
                                "engulfs": engulfs,    "body_pct": round(body_pct, 4),
                            })

                            is_bull = c2_bull and c1_bear and engulfs
                            msg = (
                                f"Bullish engulfing: {'✓' if is_bull else '✗'} "
                                f"(c2_bull={c2_bull}, c1_bear={c1_bear}, "
                                f"engulfs={engulfs}) [{data_source}]"
                            )

                else:
                    is_bull = False
                    msg = (
                        f"Reversal candle: ✗ (unknown pattern '{pattern}' — "
                        f"use hammer | doji | bull_close | higher_low | engulfing)"
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
                    rsi_mom, rsi_dir  = self._get_rsi_momentum(symbol, timeframe, lookback=2)
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

            
            elif indicator_type == "adx_regime":
                max_adx   = params.get("max_adx", 25)
                min_adx   = params.get("min_adx", 0)

                adx_value = getattr(trend, 'adx', None)
                values["adx"] = adx_value
                values["max_adx"] = max_adx
                values["min_adx"] = min_adx

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


                width_change, width_direction = self._get_bb_width_trend(
                    symbol, timeframe, lookback,
                    expand_threshold_pct, contract_threshold_pct
                )

                values["width_direction"] = width_direction
                values["width_change"]    = round(width_change, 6) if width_change is not None else None
                values["required"]        = required_direction
                values["lookback"]        = lookback

                if width_direction is None:
                    is_bull = False
                    msg = f"BB width regime: ✗ (insufficient BB history — need {lookback} candles)"
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
                            f"(bands {width_direction}, Δ={width_change:+.4f}/candle — "
                            f"need {required_direction})"
                        )
                    else:
                        msg = (
                            f"BB width regime: ✗ "
                            f"(bands {width_direction}, Δ={width_change:+.4f}/candle — "
                            f"need {required_direction})"
                        )

            elif indicator_type == "bb_pct_b_momentum":
                required_direction = params.get("required_direction", "not_rising")
                lookback           = params.get("lookback", 3)

                pct_b_change, pct_b_direction = self._get_pct_b_trend(symbol, timeframe, lookback)

                values["pct_b_direction"] = pct_b_direction
                values["pct_b_change"]    = round(pct_b_change, 4) if pct_b_change is not None else None
                values["required"]        = required_direction
                values["lookback"]        = lookback

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
			
            else:
                is_bull = False
                msg = f"Unknown indicator type: {indicator_type}"

            # -----------------------------------------------------------
            try:
                from models.signal_validation import IndicatorResult
                result_obj = IndicatorResult(
                    type=indicator_type,
                    is_bullish=is_bull,
                    config=params,
                    values=values,
                    message=msg,
                )
            except Exception:
                # Fallback if IndicatorResult import fails in isolated testing
                result_obj = type("IR", (), {"is_bullish": is_bull, "message": msg, "type": indicator_type})()

            indicator_results.append(result_obj)
            results.append((is_bull, msg))
            if hard_stop and not is_bull:
                hard_stop_failures.append(msg)

        # Hard stop check
        if use_hard_stops and hard_stop_failures:
            return False, f"HARD STOP: {'; '.join(hard_stop_failures)}", indicator_results

        bullish_count = sum(1 for r in indicator_results if r.is_bullish)
        total_count   = len(indicator_results)
        details       = ", ".join(r.message for r in indicator_results)

        if bullish_count >= min_indicators_required:
            return True, f"{bullish_count}/{total_count} bullish ({details})", indicator_results
        else:
            return False, f"Only {bullish_count}/{total_count} bullish, need {min_indicators_required} ({details})", indicator_results


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
        "signal_timeframe":           "15",
        "trend_timeframe":            "60",
        "entry_timeframe":            "15",
        "use_trend_filter":           True,
        "use_entry_filter":           True,
        "use_atr_filter":             False,
        "use_market_regime_filter":   False,
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

    # Snapshot of indicators at entry (for analysis)
    entry_details: Dict[str, Any]     = field(default_factory=dict)

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
        return {
            "entry_time":   self.entry_time.isoformat() if self.entry_time else None,
            "entry_price":  self.entry_price,
            "exit_time":    self.exit_time.isoformat()  if self.exit_time  else None,
            "exit_price":   self.exit_price,
            "exit_reason":  self.exit_reason,
            "pnl_pct":      round(self.pnl_pct, 4),
            "hold_minutes": round(self.hold_minutes, 1) if self.hold_minutes is not None else None,
            "won":          self.won,
            "confidence":   self.entry_details.get("confidence"),
            "volume_ratio": self.entry_details.get("volume_ratio"),
            "rsi_at_entry": self.entry_details.get("rsi"),
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
    signals_fired:   int = 0
    rows_processed:  int = 0
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
        ]
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for i, t in enumerate(self.trades, 1):
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
                })
        print(f"[CSV] Trade log saved → {filepath}")


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

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def run(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> BacktestResult:
        from db.models import TrendAnalysisLog

        result = BacktestResult(
            profile_name=self.profile.name,
            symbol=symbol,
            start=start,
            end=end,
            profile_params=self._profile_key_params(),
        )

        # Load all timeframes we need
        needed_timeframes = {self.profile.signal_timeframe}
        if self.profile.use_trend_filter:
            needed_timeframes.add(self.profile.trend_timeframe)
        if self.profile.use_entry_filter:
            needed_timeframes.add(self.profile.entry_timeframe)

        all_rows = (
            self.db.query(TrendAnalysisLog)
            .filter(
                TrendAnalysisLog.symbol    == symbol,
                TrendAnalysisLog.timeframe.in_(needed_timeframes),
                TrendAnalysisLog.timestamp >= start,
                TrendAnalysisLog.timestamp <= end,
            )
            .order_by(TrendAnalysisLog.timestamp)
            .all()
        )

        if not all_rows:
            print(f"[Backtest] No data for {symbol} in range {start} → {end}")
            return result

        # volume_ratio is stored directly in TrendAnalysisLog — no computation needed

        # Group into dict for quick lookup: {timeframe: [rows...]}
        by_tf: Dict[str, List] = {}
        for row in all_rows:
            by_tf.setdefault(row.timeframe, []).append(row)

        # Build entry_tf row index for fast "next N rows" lookup
        entry_tf_rows = by_tf.get(self.profile.entry_timeframe, [])

        cache     = ReplayTrendCache()
        open_pos  = None   # currently open simulated position (dict)
        cooldown_until: Optional[datetime] = None

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

            row_time = row.timestamp.replace(tzinfo=timezone.utc) if row.timestamp.tzinfo is None else row.timestamp

            # ---- Manage open position ----
            if open_pos is not None:
                exit_result = self._check_exit(open_pos, row)
                if exit_result:
                    pnl = (exit_result["price"] - open_pos["entry_price"]) / open_pos["entry_price"] * 100
                    open_pos["trade"].exit_price  = exit_result["price"]
                    open_pos["trade"].exit_time   = row_time
                    open_pos["trade"].exit_reason = exit_result["reason"]
                    open_pos["trade"].pnl_pct     = pnl
                    open_pos["trade"].won         = pnl > 0
                    open_pos = None
                else:
                    # Update trailing stop high-water mark
                    if self.profile.use_trailing_stop:
                        if row.high > open_pos["highest_price"]:
                            open_pos["highest_price"] = float(row.high)
                            arm_pct = float(self.profile.arm_trailing_stop_pct) / 100
                            if not open_pos["trailing_armed"]:
                                if open_pos["highest_price"] >= open_pos["entry_price"] * (1 + arm_pct):
                                    open_pos["trailing_armed"] = True
                    continue  # still in trade — skip signal logic

            # ---- Signal generation ----
            # Check cooldown
            cooldown_sec = getattr(self.profile, "signal_cooldown_seconds", 900)
            if cooldown_until and row_time < cooldown_until:
                continue

            # Run trend filter (HTF)
            if self.profile.use_trend_filter:
                trend_ok, _, _ = cache.is_bullish(
                    symbol,
                    self.profile.trend_timeframe,
                    indicators_config=self.profile.trend_indicators,
                    min_indicators_required=self.profile.min_indicators_required,
                    return_structured=True,
                )
                if not trend_ok:
                    if self.verbose:
                        print(f"[{row_time}] Trend filter failed")
                    continue

            # Run entry filter (execution TF)
            if self.profile.use_entry_filter:
                entry_ok, entry_reason, entry_indicators = cache.is_bullish(
                    symbol,
                    self.profile.entry_timeframe,
                    indicators_config=self.profile.entry_indicators,
                    min_indicators_required=self.profile.min_entry_indicators_required,
                    return_structured=True,
                )
                if not entry_ok:
                    if self.verbose:
                        print(f"[{row_time}] Entry filter failed: {entry_reason}")
                    continue
            else:
                entry_reason = "entry filter off"
                entry_indicators = []

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

            # Safety: RSI overbought check
            cached_trend = cache.get(symbol, self.profile.entry_timeframe)
            if cached_trend and cached_trend.rsi < 65:
                score += safety_weight
            elif cached_trend and cached_trend.rsi > 80:
                score -= 30

            confidence_pct = max(0.0, (score / max_conf) * 100) if max_conf > 0 else 0.0

            if confidence_pct < float(self.profile.min_signal_confidence):
                if self.verbose:
                    print(f"[{row_time}] Confidence too low: {confidence_pct:.1f}%")
                continue

            # SIGNAL — open position
            result.signals_fired += 1
            entry_price = float(row.close)

            trade = BacktestTrade(
                symbol=symbol,
                entry_time=row_time,
                entry_price=entry_price,
                entry_details={
                    "confidence": round(confidence_pct, 2),
                    "volume_ratio": volume_ratio,
                    "rsi": cached_trend.rsi if cached_trend else None,
                    "reason": entry_reason,
                },
            )
            result.trades.append(trade)

            tp_price = entry_price * (1 + float(self.profile.take_profit_pct) / 100)
            sl_price = entry_price * (1 - float(self.profile.stop_loss_pct)   / 100)

            open_pos = {
                "trade":           trade,
                "entry_price":     entry_price,
                "tp_price":        tp_price,
                "sl_price":        sl_price,
                "trailing_armed":  False,
                "highest_price":   entry_price,
                "entry_time":      row_time,
            }

            from datetime import timedelta
            cooldown_until = row_time + timedelta(seconds=cooldown_sec)

            if self.verbose:
                print(
                    f"[{row_time}] SIGNAL ✅ entry={entry_price:.4f} "
                    f"TP={tp_price:.4f} SL={sl_price:.4f} conf={confidence_pct:.1f}%"
                )

        # Force-close any lingering open position at end of window
        if open_pos is not None:
            last_row = entry_tf_rows[-1] if entry_tf_rows else all_rows[-1]
            last_price = float(last_row.close)
            last_time  = last_row.timestamp.replace(tzinfo=timezone.utc) \
                         if last_row.timestamp.tzinfo is None else last_row.timestamp
            pnl = (last_price - open_pos["entry_price"]) / open_pos["entry_price"] * 100
            open_pos["trade"].exit_price  = last_price
            open_pos["trade"].exit_time   = last_time
            open_pos["trade"].exit_reason = "end_of_window"
            open_pos["trade"].pnl_pct     = pnl
            open_pos["trade"].won         = pnl > 0

        return result

    # ------------------------------------------------------------------
    # Exit logic — returns {"price": float, "reason": str} or None
    # ------------------------------------------------------------------
    def _check_exit(self, pos: dict, row) -> Optional[dict]:
        high  = float(row.high)
        low   = float(row.low)
        close = float(row.close)

        # Stop loss check (uses candle low)
        if low <= pos["sl_price"]:
            return {"price": pos["sl_price"], "reason": "stop_loss", "candle_price": low}

        # Take profit check (uses candle high)
        if high >= pos["tp_price"]:
            return {"price": pos["tp_price"], "reason": "take_profit", "candle_price": high}

        # Trailing stop
        if self.profile.use_trailing_stop and pos["trailing_armed"]:
            trail_pct  = float(self.profile.trailing_stop_pct) / 100
            trail_sl   = pos["highest_price"] * (1 - trail_pct)
            if low <= trail_sl:
                return {"price": trail_sl, "reason": "trailing_stop", "candle_price": low}

        # Max position age (hours)
        max_hours = getattr(self.profile, "max_position_hours", None)
        if max_hours:
            row_time = row.timestamp.replace(tzinfo=timezone.utc) \
                       if row.timestamp.tzinfo is None else row.timestamp
            age_hours = (row_time - pos["entry_time"]).total_seconds() / 3600
            if age_hours >= max_hours:
                return {"price": float(row.close), "reason": "max_age", "candle_price": close}

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
        ]
        return {k: getattr(self.profile, k, None) for k in keys}


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