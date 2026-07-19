"""
backtesting/optimizers/tf_indicator_search.py
==============================================
Iterative indicator-combination search for TREND FOLLOWING profiles.

Strategy: 60m trend filter confirms uptrend is active; 15m entry filter
identifies a quality pullback entry within that trend.

Fixed exit: champion exit config from 4-iteration optimisation
  (rsi_overbought 68 hard-stop + ema_slope -0.02 hard-stop + rsi_threshold 44)

State files:
  backtesting/optimizers/tf_optimizer_state.json
  backtesting/optimizers/tf_optimizer_results.json

Usage:
  python backtesting/optimizers/tf_indicator_search.py
  python backtesting/optimizers/tf_indicator_search.py --reset
  python backtesting/optimizers/tf_indicator_search.py --days 40 --iteration 2
"""

import argparse
import copy
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.backtest_engine import BacktestEngine, BacktestProfile, BacktestResult
from db.utils import get_db_session

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STATE_FILE   = str(Path(__file__).resolve().parent / "tf_optimizer_state.json")
RESULTS_FILE = str(Path(__file__).resolve().parent / "tf_optimizer_results.json")
SYMBOLS      = ["SOL_USDC", "ETH_USDC", "BTC_USDC", "BNB_USDC", "XRP_USDC", "ZEC_USDC"]
SCAN_DAYS    = 40
MIN_TRADES   = 8   # minimum across all symbols to qualify

# Fixed base settings — trend following specific
BASE_SETTINGS = {
    "strategy_type":            "trend_following",
    "entry_timeframe":          "15",
    "trend_timeframe":          "60",
    "take_profit_pct":          0.8,
    "stop_loss_pct":            0.6,
    "trailing_stop_pct":        0.3,
    "arm_trailing_stop_pct":    0.4,
    "use_trailing_stop":        True,
    "signal_cooldown_minutes":  15,
    "min_signal_confidence":    70.0,
    "min_volume_ratio":         1.1,
    "use_trend_filter":         True,
    "use_entry_filter":         True,
    "max_position_hours":       12,
    "use_market_regime_filter": True,
    # Champion exit config — locked in from 4-iteration exit optimisation
    "trend_invalidation_indicators": "exit",
    "exit_indicators": [
        {"type": "rsi_overbought", "params": {"min_value": 68, "hard_stop": True}},
        {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
        {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
    ],
    "min_exit_indicators_required": 1,
    "min_position_age_for_trend_check": 15,
    "trading_hours": [
        {"day_of_week": 0, "start_time": "05:00", "end_time": "12:00", "enabled": True},
        {"day_of_week": 0, "start_time": "15:00", "end_time": "21:00", "enabled": True},
        {"day_of_week": 1, "start_time": "02:00", "end_time": "23:00", "enabled": True},
        {"day_of_week": 2, "start_time": "01:00", "end_time": "12:00", "enabled": True},
        {"day_of_week": 2, "start_time": "14:00", "end_time": "23:00", "enabled": True},
        {"day_of_week": 3, "start_time": "03:00", "end_time": "12:00", "enabled": True},
        {"day_of_week": 3, "start_time": "14:00", "end_time": "21:00", "enabled": True},
        {"day_of_week": 4, "start_time": "03:00", "end_time": "12:00", "enabled": True},
        {"day_of_week": 4, "start_time": "14:00", "end_time": "21:00", "enabled": True},
    ],
}

# ---------------------------------------------------------------------------
# TREND TEMPLATES  (60m — confirming an uptrend is active)
#
# Logic: EMA alignment, trend strength (ADX), RSI zone, price position.
# rsi_overbought acts as a ceiling gate (passes when RSI < min_value).
# adx_regime: min_adx ensures genuine trend; max_adx caps extreme volatility.
# ---------------------------------------------------------------------------

TREND_TEMPLATES = {

    # ── Baseline: champion from 4-iteration exit optimisation ─────────────────
    # EMA20>EMA50 cross + BB broad pct_b gate + ADX≥28 hard-stop + RSI<60 ceiling
    "T_champion_baseline": (
        [
            {"type": "ema_cross",      "params": {}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",     "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ], 4),

    # ── EMA cross + ADX only (minimal, most permissive) ──────────────────────
    "T_emacross_adx28": (
        [
            {"type": "ema_cross",  "params": {}},
            {"type": "adx_regime", "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
        ], 2),

    # ── EMA cross + stronger ADX floor (32) ─────────────────────────────────
    "T_emacross_adx32": (
        [
            {"type": "ema_cross",  "params": {}},
            {"type": "adx_regime", "params": {"min_adx": 32, "max_adx": 65, "hard_stop": True}},
        ], 2),

    # ── EMA cross + ADX + RSI not overbought (65 ceiling) ────────────────────
    "T_emacross_adx28_rsi65": (
        [
            {"type": "ema_cross",      "params": {}},
            {"type": "adx_regime",     "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── EMA cross + RSI in healthy trend zone 45–70 ──────────────────────────
    # RSI in 45-70 = uptrend in play, not overbought, not rolling over.
    "T_emacross_rsirange_4570": (
        [
            {"type": "ema_cross",  "params": {}},
            {"type": "rsi_range",  "params": {"min": 45, "max": 70, "invert": True}},
            {"type": "adx_regime", "params": {"min_adx": 25, "max_adx": 65}},
        ], 3),

    # ── EMA cross + RSI in range 50–68 (stricter: must be in established trend)
    "T_emacross_rsirange_5068": (
        [
            {"type": "ema_cross",  "params": {}},
            {"type": "rsi_range",  "params": {"min": 50, "max": 68, "invert": True}},
            {"type": "adx_regime", "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
        ], 3),

    # ── EMA slope rising + ADX (no cross required — slope confirms momentum) ─
    "T_emaslope_adx28": (
        [
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
        ], 2),

    # ── EMA slope (steeper: 0.025%) + ADX ────────────────────────────────────
    "T_emaslope_steep_adx30": (
        [
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.025, "hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 30, "max_adx": 65, "hard_stop": True}},
        ], 2),

    # ── EMA cross + EMA slope (double EMA confirmation) ──────────────────────
    "T_emacross_emaslope": (
        [
            {"type": "ema_cross",      "params": {}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
            {"type": "adx_regime",     "params": {"min_adx": 25, "max_adx": 65}},
        ], 3),

    # ── EMA cross + BB price in upper half (price holding above midline) ──────
    # pct_b 0.5-1.0: price is in the upper half of the BB — trend is dominant.
    "T_emacross_bb_upper": (
        [
            {"type": "ema_cross",      "params": {}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": 0.5, "max_pct_b": 1.1}},
            {"type": "adx_regime",     "params": {"min_adx": 25, "max_adx": 65}},
        ], 3),

    # ── EMA cross + BB expanding (trend is developing, bands widening) ────────
    # Expanding BB = price is moving directionally, not in a range.
    "T_emacross_bb_expanding": (
        [
            {"type": "ema_cross",      "params": {}},
            {"type": "bb_width_regime","params": {"required_direction": "expanding", "lookback": 3}},
            {"type": "adx_regime",     "params": {"min_adx": 25, "max_adx": 65}},
        ], 3),

    # ── EMA cross + price above VWAP (macro sentiment bullish) ───────────────
    "T_emacross_vwap": (
        [
            {"type": "ema_cross",    "params": {}},
            {"type": "price_vs_vwap","params": {}},
            {"type": "adx_regime",   "params": {"min_adx": 25, "max_adx": 65}},
        ], 3),

    # ── EMA cross + price above VWAP + ADX hard-stop ─────────────────────────
    "T_emacross_vwap_adx28": (
        [
            {"type": "ema_cross",    "params": {}},
            {"type": "price_vs_vwap","params": {}},
            {"type": "adx_regime",   "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
        ], 3),

    # ── EMA cross + RSI momentum positive (RSI is rising, not just in range) ─
    "T_emacross_rsimom": (
        [
            {"type": "ema_cross",    "params": {}},
            {"type": "rsi_momentum", "params": {"min_momentum": 0.0}},
            {"type": "adx_regime",   "params": {"min_adx": 25, "max_adx": 65}},
        ], 3),

    # ── EMA gap (EMAs well-separated) + ADX ──────────────────────────────────
    # EMA20 is at least 0.3% above EMA50 — confirms trend has been running.
    "T_emagap_adx28": (
        [
            {"type": "ema_gap",    "params": {"min_gap_pct": 0.3, "mode": "min"}},
            {"type": "adx_regime", "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "ema_cross",  "params": {}},
        ], 3),

    # ── EMA cross + RSI threshold ≥50 (RSI shows bullish bias) ───────────────
    "T_emacross_rsi50": (
        [
            {"type": "ema_cross",    "params": {}},
            {"type": "rsi_threshold","params": {"period": 14, "min_value": 50, "use_momentum": False}},
            {"type": "adx_regime",   "params": {"min_adx": 25, "max_adx": 65}},
        ], 3),

    # ── EMA cross + price extended above EMA (strong trend pullback entry zone)
    # price_extended_above_ema: price is 0.1–1.5% above EMA20 (in the trend zone
    # but not wildly overextended — good for pullback entries).
    "T_emacross_price_aboveema": (
        [
            {"type": "ema_cross",               "params": {}},
            {"type": "price_extended_above_ema","params": {"ema": 20, "min_gap_pct": 0.1, "max_gap_pct": 2.0}},
            {"type": "adx_regime",              "params": {"min_adx": 25, "max_adx": 65}},
        ], 3),

    # ── Multi-signal: EMA cross + ADX + RSI not overbought + slope ───────────
    "T_multi_emacross_adx_rsi_slope": (
        [
            {"type": "ema_cross",      "params": {}},
            {"type": "adx_regime",     "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ], 4),

    # ── EMA cross + BB pct_b not overbought (below 0.85) + ADX ──────────────
    # Prevents entries when price is near the upper BB (overextended condition).
    "T_emacross_bb_notoverext": (
        [
            {"type": "ema_cross",      "params": {}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": -0.05, "max_pct_b": 0.85}},
            {"type": "adx_regime",     "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
        ], 3),

    # ── EMA slope + RSI momentum + BB pct_b (all-momentum filter) ────────────
    "T_slope_rsimom_bb": (
        [
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "rsi_momentum",   "params": {"min_momentum": 0.5}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": 0.3, "max_pct_b": 0.95}},
        ], 3),

    # ── Looser ADX (22) — catches earlier trend stages ────────────────────────
    "T_emacross_adx22_rsi60": (
        [
            {"type": "ema_cross",      "params": {}},
            {"type": "adx_regime",     "params": {"min_adx": 22, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ], 3),
}


# ---------------------------------------------------------------------------
# ENTRY TEMPLATES  (15m — identifying a quality pullback entry in the trend)
#
# Logic: price has pulled back within the trend — we want to enter on RSI
# recovery, EMA pullback, or other short-term reversal signals.
# ---------------------------------------------------------------------------

ENTRY_TEMPLATES = {

    # ── Baseline: champion entry from prior optimisation ──────────────────────
    # rsi_reversal_momentum (sustained) is the binding filter. All other
    # indicators in this set have been confirmed to add context.
    "E_champion_revmom": (
        [
            {"type": "price_vs_ema",          "params": {"ema": 20, "min_gap_pct": 0.0, "max_gap_pct": 2.5}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38,
                "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": 0.05, "max_pct_b": 0.6}},
            {"type": "rsi_threshold",         "params": {"period": 14, "min_value": 52,
                "use_momentum": False, "early_threshold": 37, "hard_stop": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",         "params": {}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
        ], 5),

    # ── Revmom only (minimal — just the binding filter + RSI ceiling) ─────────
    "E_revmom_minimal": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38,
                "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
        ], 2),

    # ── Revmom + EMA slope only ───────────────────────────────────────────────
    "E_revmom_emaslope": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38,
                "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── Revmom + pullback to EMA20 (price near EMA20 after pullback) ──────────
    "E_revmom_ema_pullback": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38,
                "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "price_vs_ema",          "params": {"ema": 20, "min_gap_pct": -1.0, "max_gap_pct": 1.5}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── Revmom + BB lower-mid zone (price pulled back into lower half of BB) ──
    "E_revmom_bb_pullback": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38,
                "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": 0.05, "max_pct_b": 0.55}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── Revmom + price above VWAP (macro bullish on entry TF) ────────────────
    "E_revmom_vwap": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38,
                "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "price_vs_vwap",         "params": {}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── Revmom + volume (entry has volume confirmation) ───────────────────────
    "E_revmom_vol": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38,
                "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── Revmom (looser oversold: 42, smaller jump: 4) ─────────────────────────
    # Captures milder RSI dips than the champion — more signals, lower bar.
    "E_revmom_loose": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 42,
                "current_min": 45, "min_jump": 4.0, "require_sustained": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.01, "hard_stop": True}},
        ], 3),

    # ── Revmom (strict: oversold 35, jump 6) ─────────────────────────────────
    "E_revmom_strict": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 35,
                "current_min": 48, "min_jump": 6.0, "require_sustained": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
        ], 2),

    # ── RSI threshold entry (simpler: RSI just needs to be above 50) ──────────
    # No reversal momentum required — just RSI at bullish level + EMA slope.
    "E_rsi_threshold_slope": (
        [
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 50,
                "use_momentum": True, "early_threshold": 45, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",  "params": {}},
        ], 3),

    # ── RSI in healthy zone 45–65 (on entry TF) + EMA slope ──────────────────
    # rsi_range invert=True: RSI must be IN the range 45-65.
    # This is a pullback entry: RSI hasn't gone too low, still in trend zone.
    "E_rsirange_4565_slope": (
        [
            {"type": "rsi_range",  "params": {"min": 45, "max": 65, "invert": True}},
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "price_vs_vwap","params": {}},
        ], 3),

    # ── RSI in pullback zone 40–58 + revmom ───────────────────────────────────
    # RSI has pulled back from the 60s into 40-58 — classic pullback entry zone.
    "E_rsirange_4058_revmom": (
        [
            {"type": "rsi_range",             "params": {"min": 40, "max": 58, "invert": True}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 4, "oversold_threshold": 40,
                "current_min": 43, "min_jump": 3.0, "require_sustained": False}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.01, "hard_stop": True}},
        ], 3),

    # ── Price pulled back to EMA20 + RSI not too low + slope ─────────────────
    # Classic pullback-to-EMA entry: price retraces to EMA20 in an uptrend.
    "E_ema_pullback_rsi": (
        [
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 0.8}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 45,
                "use_momentum": False, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.01, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
        ], 4),

    # ── EMA pullback + BB mid zone + revmom ───────────────────────────────────
    "E_ema_pullback_bb_revmom": (
        [
            {"type": "price_vs_ema",          "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "bollinger_bands",        "params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": 0.1, "max_pct_b": 0.65}},
            {"type": "rsi_reversal_momentum",  "params": {"lookback_candles": 5, "oversold_threshold": 40,
                "current_min": 44, "min_jump": 4.0, "require_sustained": False}},
            {"type": "rsi_overbought",         "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── Volume spike + EMA slope + RSI threshold (momentum breakout entry) ───
    # Entry fires when volume elevates during an RSI bounce within the trend.
    "E_vol_slope_rsi": (
        [
            {"type": "volume_spike",   "params": {"min_ratio": 1.3, "max_ratio": 8.0}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 48,
                "use_momentum": True, "early_threshold": 43, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── RSI momentum positive + EMA slope + BB not overbought ────────────────
    # RSI is actively rising + EMA still going up + price not at top of bands.
    "E_rsimom_slope_bb": (
        [
            {"type": "rsi_momentum",   "params": {"min_momentum": 0.5, "max_momentum": 8.0}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": 0.1, "max_pct_b": 0.7}},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── Higher low candle + revmom (structural pullback in trend) ─────────────
    # Higher low: price made a higher low vs prior candle — sell pressure ending.
    "E_higherlow_revmom": (
        [
            {"type": "reversal_candle",       "params": {"pattern": "higher_low"}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 5, "oversold_threshold": 40,
                "current_min": 44, "min_jump": 4.0, "require_sustained": False}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.01, "hard_stop": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── Bull close candle + RSI threshold + slope ─────────────────────────────
    "E_bullclose_rsi_slope": (
        [
            {"type": "reversal_candle","params": {"pattern": "bull_close", "min_close_pct": 0.55,
                "require_bull": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 48,
                "use_momentum": False, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.01, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── BB pct_b momentum rising + RSI slope + EMA slope (breakout entry) ────
    # bb_pct_b_momentum rising = price moving toward upper BB = momentum in direction.
    "E_pctb_rising_slope": (
        [
            {"type": "bb_pct_b_momentum","params": {"required_direction": "rising", "lookback": 3}},
            {"type": "ema_slope",        "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "rsi_threshold",    "params": {"period": 14, "min_value": 48,
                "use_momentum": True, "early_threshold": 43, "hard_stop": True}},
            {"type": "rsi_overbought",   "params": {"min_value": 68, "hard_stop": True}},
        ], 3),

    # ── Revmom no-sustained (looser timing, allow brief dips in RSI recovery)
    "E_revmom_nosustain_slope": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38,
                "current_min": 45, "min_jump": 5.0, "require_sustained": False}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",         "params": {}},
        ], 3),

    # ── Revmom + ema_slope + price_vs_vwap (three-condition quality gate) ─────
    "E_revmom_slope_vwap": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38,
                "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising",
                "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "price_vs_vwap",         "params": {}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
        ], 4),
}


# ---------------------------------------------------------------------------
# Variant generation
# ---------------------------------------------------------------------------

def build_variants_from_templates() -> Dict[str, dict]:
    """Cross every trend template with every entry template."""
    variants = {}
    for t_name, (t_inds, t_min) in TREND_TEMPLATES.items():
        for e_name, (e_inds, e_min) in ENTRY_TEMPLATES.items():
            name = f"{t_name}__{e_name}"
            variants[name] = {
                **BASE_SETTINGS,
                "trend_indicators":              t_inds,
                "min_indicators_required":       t_min,
                "entry_indicators":              e_inds,
                "min_entry_indicators_required": e_min,
            }
    return variants


def _mutate_indicator(ind: dict, rng: random.Random) -> dict:
    """Return a mutated copy of a single trend-following indicator config."""
    ind = copy.deepcopy(ind)
    p = ind["params"]
    itype = ind["type"]

    if itype == "ema_cross":
        pass  # no params to mutate — it's just EMA20>EMA50

    elif itype == "ema_slope":
        p["ema"]           = rng.choice([20, 20, 50])
        p["direction"]     = "rising"
        p["min_slope_pct"] = rng.choice([0.01, 0.015, 0.02, 0.025, 0.03])
        p["hard_stop"]     = True

    elif itype == "ema_gap":
        p["min_gap_pct"] = rng.choice([0.15, 0.2, 0.3, 0.4, 0.5])
        p["mode"]        = "min"

    elif itype == "adx_regime":
        p["min_adx"]  = rng.choice([22, 25, 28, 30, 32])
        p["max_adx"]  = rng.choice([60, 65, 70])
        p["hard_stop"] = rng.choice([True, True, False])

    elif itype == "rsi_overbought":
        p["min_value"] = rng.choice([55, 58, 60, 63, 65, 68])
        if "lookback_candles" in p:
            p["lookback_candles"] = rng.choice([3, 5, 7])
        p["hard_stop"] = True

    elif itype == "rsi_range":
        p["min"] = rng.choice([40, 43, 45, 48, 50])
        p["max"] = rng.choice([60, 63, 65, 68, 70])
        p["invert"] = True

    elif itype == "rsi_threshold":
        p["min_value"]      = rng.choice([45, 48, 50, 52, 55])
        p["use_momentum"]   = rng.choice([True, False])
        p["early_threshold"]= rng.choice([35, 37, 40, 43])
        p["hard_stop"]      = True

    elif itype == "rsi_momentum":
        p["min_momentum"] = rng.choice([0.0, 0.3, 0.5, 1.0])
        p["max_momentum"] = rng.choice([5.0, 8.0, 10.0])

    elif itype == "rsi_reversal_momentum":
        p["lookback_candles"]   = rng.choice([4, 5, 6, 7, 8])
        p["oversold_threshold"] = rng.choice([35, 38, 40, 42, 45])
        p["current_min"]        = rng.choice([42, 44, 45, 47, 48])
        p["min_jump"]           = rng.choice([3.0, 4.0, 5.0, 6.0])
        p["require_sustained"]  = rng.choice([True, True, False])
        p["hard_stop"]          = True

    elif itype == "bollinger_bands" and p.get("mode") == "pct_b":
        p["min_pct_b"] = rng.choice([-0.05, 0.0, 0.05, 0.1, 0.2])
        p["max_pct_b"] = rng.choice([0.5, 0.6, 0.7, 0.8, 0.9, 0.95])

    elif itype == "bb_width_regime":
        p["required_direction"] = rng.choice(["expanding", "not_expanding"])
        p["lookback"]           = rng.choice([3, 4, 5])

    elif itype == "bb_pct_b_momentum":
        p["required_direction"] = "rising"
        p["lookback"]           = rng.choice([2, 3, 4])

    elif itype == "price_vs_ema":
        p["ema"]         = rng.choice([20, 20, 50])
        p["min_gap_pct"] = rng.choice([-1.0, -0.5, 0.0])
        p["max_gap_pct"] = rng.choice([1.0, 1.5, 2.0, 2.5])

    elif itype == "price_vs_vwap":
        pass  # no params

    elif itype == "price_extended_above_ema":
        p["ema"]         = rng.choice([20, 20, 50])
        p["min_gap_pct"] = rng.choice([0.0, 0.1, 0.2, 0.3])
        p["max_gap_pct"] = rng.choice([1.0, 1.5, 2.0, 3.0])

    elif itype == "volume_spike":
        p["min_ratio"] = rng.choice([1.1, 1.2, 1.3, 1.5, 1.8])
        p["max_ratio"] = 8.0

    elif itype == "reversal_candle":
        p["pattern"] = rng.choice(["higher_low", "bull_close", "hammer"])
        if p["pattern"] == "bull_close":
            p["min_close_pct"] = rng.choice([0.50, 0.55, 0.60])
            p["require_bull"]  = True

    ind["params"] = {k: v for k, v in p.items() if v is not None}
    return ind


def generate_variants_random(n: int = 120, seed: int = None) -> Dict[str, dict]:
    """Random mutation generator for trend following."""
    rng = random.Random(seed)
    variants = {}
    t_names = list(TREND_TEMPLATES.keys())
    e_names = list(ENTRY_TEMPLATES.keys())

    # TP/SL combos — kept near the champion 0.8/0.6 but also explore wider
    tp_sl_trailing = [
        (0.8, 0.6, 0.3, 0.4, True),   # champion
        (0.8, 0.5, 0.3, 0.4, True),   # tighter SL
        (1.0, 0.6, 0.4, 0.5, True),   # wider TP
        (0.8, 0.6, 0.0, 0.0, False),  # no trailing stop
        (1.0, 0.7, 0.4, 0.5, True),
        (1.2, 0.7, 0.5, 0.6, True),
        (0.8, 0.6, 0.25, 0.35, True),
        (0.9, 0.6, 0.35, 0.45, True),
    ]

    attempts = 0
    while len(variants) < n and attempts < n * 10:
        attempts += 1
        t_name = rng.choice(t_names)
        e_name = rng.choice(e_names)
        t_inds_orig, t_min = TREND_TEMPLATES[t_name]
        e_inds_orig, e_min = ENTRY_TEMPLATES[e_name]

        t_inds = copy.deepcopy(t_inds_orig)
        for _ in range(rng.randint(1, 2)):
            idx = rng.randrange(len(t_inds))
            t_inds[idx] = _mutate_indicator(t_inds[idx], rng)

        e_inds = copy.deepcopy(e_inds_orig)
        for _ in range(rng.randint(1, 2)):
            idx = rng.randrange(len(e_inds))
            e_inds[idx] = _mutate_indicator(e_inds[idx], rng)

        t_min_var = t_min + rng.choice([-1, 0, 0, 1])
        t_min_var = max(1, min(t_min_var, len(t_inds)))
        e_min_var = e_min + rng.choice([-1, 0, 0, 1])
        e_min_var = max(2, min(e_min_var, len(e_inds)))

        tp, sl, trl, arm, use_trl = rng.choice(tp_sl_trailing)
        tp_tag = f"tp{int(tp*10)}sl{int(sl*10)}{'trl' if use_trl else 'fix'}"
        name = f"rand_{t_name[:12]}_{e_name[:12]}_{tp_tag}_s{seed or 0}_{attempts}"

        variants[name] = {
            **BASE_SETTINGS,
            "take_profit_pct":       tp,
            "stop_loss_pct":         sl,
            "trailing_stop_pct":     trl,
            "arm_trailing_stop_pct": arm,
            "use_trailing_stop":     use_trl,
            "trend_indicators":              t_inds,
            "min_indicators_required":       t_min_var,
            "entry_indicators":              e_inds,
            "min_entry_indicators_required": e_min_var,
        }

    return variants


def generate_variants_focused(top_results: list, n_per_winner: int = 10) -> Dict[str, dict]:
    """Focused mutations around prior top results."""
    variants = {}
    rng = random.Random(42)

    for r in top_results:
        cfg   = r.get("config", {})
        t_inds = copy.deepcopy(cfg.get("trend_indicators", []))
        e_inds = copy.deepcopy(cfg.get("entry_indicators", []))
        t_min  = cfg.get("min_indicators_required", 2)
        e_min  = cfg.get("min_entry_indicators_required", 3)
        base   = r.get("name", "top")

        for attempt in range(n_per_winner * 3):
            new_t = copy.deepcopy(t_inds)
            new_e = copy.deepcopy(e_inds)
            new_t_min = t_min
            new_e_min = e_min

            action = rng.choice(["toggle_t_hs", "toggle_e_hs", "mutate_t",
                                  "mutate_e", "quorum", "mutate_both"])

            if action == "toggle_t_hs" and new_t:
                i = rng.randrange(len(new_t))
                new_t[i]["params"]["hard_stop"] = not new_t[i]["params"].get("hard_stop", False)

            elif action == "toggle_e_hs" and new_e:
                i = rng.randrange(len(new_e))
                new_e[i]["params"]["hard_stop"] = not new_e[i]["params"].get("hard_stop", False)

            elif action == "mutate_t" and new_t:
                i = rng.randrange(len(new_t))
                new_t[i] = _mutate_indicator(new_t[i], rng)

            elif action == "mutate_e" and new_e:
                i = rng.randrange(len(new_e))
                new_e[i] = _mutate_indicator(new_e[i], rng)

            elif action == "quorum":
                new_t_min = max(1, t_min + rng.choice([-1, 1]))
                new_e_min = max(2, e_min + rng.choice([-1, 1]))

            elif action == "mutate_both":
                if new_t:
                    i = rng.randrange(len(new_t))
                    new_t[i] = _mutate_indicator(new_t[i], rng)
                if new_e:
                    i = rng.randrange(len(new_e))
                    new_e[i] = _mutate_indicator(new_e[i], rng)

            name = f"foc_{base[:30]}_{action}_{attempt}"
            if name not in variants:
                variants[name] = {
                    **BASE_SETTINGS,
                    "trend_indicators":              new_t,
                    "min_indicators_required":       new_t_min,
                    "entry_indicators":              new_e,
                    "min_entry_indicators_required": new_e_min,
                }
                if len(variants) >= len(top_results) * n_per_winner * 2:
                    return variants

        # TP/SL sweep on each winner's indicators
        tp_sl_combos = [
            (0.8, 0.6, 0.3,  0.4,  True),
            (0.8, 0.5, 0.3,  0.4,  True),
            (1.0, 0.6, 0.4,  0.5,  True),
            (1.0, 0.7, 0.4,  0.5,  True),
            (1.2, 0.7, 0.5,  0.6,  True),
            (0.8, 0.6, 0.0,  0.0,  False),
            (1.0, 0.65, 0.4, 0.5,  True),
            (0.9, 0.6,  0.3, 0.45, True),
        ]
        for tp, sl, trl, arm, use_trl in tp_sl_combos:
            tp_tag = f"tp{int(tp*10)}sl{int(sl*10)}{'trl' if use_trl else 'fix'}"
            name = f"foc_{base[:35]}_{tp_tag}"
            if name not in variants:
                variants[name] = {
                    **BASE_SETTINGS,
                    "take_profit_pct":       tp,
                    "stop_loss_pct":         sl,
                    "trailing_stop_pct":     trl,
                    "arm_trailing_stop_pct": arm,
                    "use_trailing_stop":     use_trl,
                    "trend_indicators":              t_inds,
                    "min_indicators_required":       t_min,
                    "entry_indicators":              e_inds,
                    "min_entry_indicators_required": e_min,
                }

    return variants


# ---------------------------------------------------------------------------
# Scoring & aggregation
# ---------------------------------------------------------------------------

def score_merged(trades: float, win_rate: float, total_pnl: float,
                 profit_factor: float, avg_pnl: float = 0.0) -> float:
    """
    Scoring for trend following:
    - avg_pnl is the primary objective (quality per trade)
    - profit factor shows risk/reward ratio
    - win rate matters for consistency
    - minimum trade count gate prevents over-fitting
    """
    if trades < MIN_TRADES:
        return -999.0
    pf  = min(profit_factor, 6.0)
    wr  = win_rate
    pnl = min(total_pnl, 30.0)
    return avg_pnl * 200 + pf * 0.35 + wr * 100 * 0.30 + pnl * 0.10


def merge_symbol_results(sym_results: List[BacktestResult], name: str, config: dict) -> dict:
    all_trades = []
    signals_total = 0
    for r in sym_results:
        all_trades.extend(r.trades)
        signals_total += r.signals_fired

    closed    = [t for t in all_trades if t.exit_price is not None]
    wins      = sum(1 for t in closed if t.won)
    win_rate  = wins / len(closed) if closed else 0.0
    total_pnl = sum(t.pnl_pct for t in closed)
    avg_pnl   = total_pnl / len(closed) if closed else 0.0
    gross_win  = sum(t.pnl_pct for t in closed if t.pnl_pct > 0)
    gross_loss = abs(sum(t.pnl_pct for t in closed if t.pnl_pct < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    pf_stored = round(pf, 4) if pf != float("inf") else 9999

    sc = score_merged(len(closed), win_rate, total_pnl, pf, avg_pnl)
    return {
        "name":          name,
        "trades":        len(closed),
        "signals":       signals_total,
        "win_rate":      round(win_rate, 4),
        "avg_pnl":       round(avg_pnl, 4),
        "total_pnl":     round(total_pnl, 4),
        "profit_factor": pf_stored,
        "score":         round(sc, 3),
        "config":        config,
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_variants(db, variants: Dict[str, dict], start: datetime, end: datetime) -> List[dict]:
    total = len(variants) * len(SYMBOLS)
    done  = 0
    all_results = []

    print(f"  {len(variants)} variants × {len(SYMBOLS)} symbols = {total} backtests\n")

    for name, config in variants.items():
        sym_results = []
        for sym in SYMBOLS:
            profile = BacktestProfile.from_dict(name, config)
            engine  = BacktestEngine(db, profile)
            r       = engine.run(symbol=sym, start=start, end=end)
            sym_results.append(r)
            done += 1

        merged = merge_symbol_results(sym_results, name, config)
        all_results.append(merged)

        if done % max(1, total // 20) == 0 or done == total:
            best = max(all_results, key=lambda x: x["score"])
            print(
                f"  [{done/total:5.1%}] {done}/{total} "
                f"| best: {best['name'][:40]} "
                f"sc={best['score']:.1f} trades={best['trades']} "
                f"pf={best['profit_factor']:.2f}x wr={best['win_rate']:.0%} "
                f"avg={best['avg_pnl']:.2f}%",
                flush=True,
            )

    return all_results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_ranking(results: List[dict], title: str, top_n: int = 30):
    ranked = sorted(results, key=lambda x: x["score"], reverse=True)
    qualifying = [r for r in ranked if r["score"] > -100]

    print(f"\n{'='*110}")
    print(f"  {title}")
    print(f"  {len(qualifying)} qualifying (≥{MIN_TRADES} trades) out of {len(results)} total")
    print(f"{'='*110}")
    print(f"{'Rank':<5} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} {'ProfFact':>9} {'Score':>7}  Name")
    print("-"*110)
    for rank, r in enumerate(qualifying[:top_n], 1):
        print(
            f"{rank:<5} {r['trades']:>7} {r['win_rate']:>6.1%} "
            f"{r['avg_pnl']:>7.2f}% {r['total_pnl']:>9.2f}% "
            f"{r['profit_factor']:>9.2f}x {r['score']:>7.2f}  {r['name']}"
        )
    if not qualifying:
        print("  (no variants hit MIN_TRADES — filters may be too restrictive)")
    print("="*110)
    return ranked


def print_snippet(r: dict):
    cfg = r["config"]
    print(f'\n    "{r["name"][:60]}": {{')
    print(f'        # Score={r["score"]:.2f} | Trades={r["trades"]} '
          f'| WR={r["win_rate"]:.0%} | PF={r["profit_factor"]:.2f}x | AvgPnL={r["avg_pnl"]:+.2f}%')
    for k in ["take_profit_pct","stop_loss_pct","trailing_stop_pct","arm_trailing_stop_pct"]:
        if k in cfg:
            print(f'        "{k}": {cfg[k]},')
    print(f'        "trend_indicators": {json.dumps(cfg.get("trend_indicators",[]), indent=8)},')
    print(f'        "min_indicators_required": {cfg.get("min_indicators_required",2)},')
    print(f'        "entry_indicators": {json.dumps(cfg.get("entry_indicators",[]), indent=8)},')
    print(f'        "min_entry_indicators_required": {cfg.get("min_entry_indicators_required",3)},')
    print(f'        # exit indicators: locked to champion RSI68 exit set')
    print(f'    }},')


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"iteration": 0, "tried_names": [], "all_time_best": []}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_results() -> List[dict]:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return []


def save_results(results: List[dict]):
    clean = [{k: v for k, v in r.items()} for r in results]
    with open(RESULTS_FILE, "w") as f:
        json.dump(clean, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Trend following indicator combination search")
    parser.add_argument("--iteration", type=int, default=None)
    parser.add_argument("--top-carry", type=int, default=10)
    parser.add_argument("--days",      type=int, default=SCAN_DAYS)
    parser.add_argument("--rand-n",    type=int, default=120)
    parser.add_argument("--reset",     action="store_true")
    parser.add_argument("--no-save",   action="store_true")
    args = parser.parse_args()

    if args.reset:
        for f in [STATE_FILE, RESULTS_FILE]:
            if os.path.exists(f):
                os.remove(f)
        print("[Reset] State cleared.\n")

    state     = load_state()
    iteration = args.iteration if args.iteration is not None else state["iteration"] + 1
    state["iteration"] = iteration

    end   = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.days)

    n_trend = len(TREND_TEMPLATES)
    n_entry = len(ENTRY_TEMPLATES)
    print(f"\n{'#'*75}")
    print(f"  TREND FOLLOWING INDICATOR SEARCH — Iteration {iteration}")
    print(f"  Window  : {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')} ({args.days}d)")
    print(f"  Symbols : {SYMBOLS}")
    print(f"  Templates: {n_trend} trend × {n_entry} entry = {n_trend*n_entry} base combos")
    print(f"  Exit: locked to champion RSI68 exit set")
    print(f"{'#'*75}\n")

    if iteration == 1:
        print("[Gen] Strategy: full template cross-product (broad exploration)\n")
        variants = build_variants_from_templates()

    elif iteration == 2:
        print(f"[Gen] Strategy: random mutations ({args.rand_n} variants)\n")
        variants = generate_variants_random(n=args.rand_n, seed=iteration)

    else:
        prev_results = load_results()
        qualifying = sorted(
            [r for r in prev_results if r["score"] > -100],
            key=lambda x: x["score"], reverse=True
        )[:args.top_carry]

        if qualifying:
            print(f"[Gen] Strategy: focused mutations on top-{len(qualifying)} prior winners\n")
            variants = generate_variants_focused(qualifying, n_per_winner=10)
        else:
            print("[Gen] No qualifying prior results — random mutations\n")
            variants = generate_variants_random(n=args.rand_n, seed=iteration * 17)

    tried = set(state.get("tried_names", []))
    new_variants = {k: v for k, v in variants.items() if k not in tried}
    skipped = len(variants) - len(new_variants)
    print(f"[Gen] {len(variants)} generated | {skipped} already tried | {len(new_variants)} new\n")

    if not new_variants:
        print("Nothing new — run with --iteration 2 or --reset.")
        return

    with get_db_session() as db:
        this_run = run_variants(db, new_variants, start, end)

    prev_all  = load_results()
    prev_map  = {r["name"]: r for r in prev_all}
    for r in this_run:
        prev_map[r["name"]] = r
    all_results = list(prev_map.values())

    print_ranking(this_run,   f"THIS ITERATION ({iteration}) RESULTS",                      top_n=20)
    ranked_all = print_ranking(all_results, f"ALL-TIME TOP (after iteration {iteration})",   top_n=30)

    qualifying_all = [r for r in ranked_all if r["score"] > -100]
    if qualifying_all:
        print(f"\n{'='*75}")
        print(f"  TOP-5 PASTE-READY ENTRIES")
        print(f"{'='*75}")
        for r in qualifying_all[:5]:
            print_snippet(r)

    if not args.no_save:
        state["tried_names"] = list(tried | set(new_variants.keys()))
        state["all_time_best"] = [
            {k: v for k, v in r.items() if k != "config"}
            for r in qualifying_all[:20]
        ]
        save_state(state)
        save_results(all_results)
        print(f"\n[State] → {STATE_FILE}")
        print(f"[Results] → {RESULTS_FILE}")

    print(f"\n[Done] Iteration {iteration}.")
    qual_this = len([r for r in this_run if r["score"] > -100])
    print(f"  This run : {qual_this}/{len(this_run)} qualifying variants")
    print(f"  All-time : {len(qualifying_all)}/{len(all_results)} qualifying variants")
    if qualifying_all:
        b = qualifying_all[0]
        print(f"  Best so far: score={b['score']:.2f} trades={b['trades']} "
              f"wr={b['win_rate']:.0%} pf={b['profit_factor']:.2f}x avg={b['avg_pnl']:+.2f}%")
        print(f"    {b['name']}")


if __name__ == "__main__":
    main()
