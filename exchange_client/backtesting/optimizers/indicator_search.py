"""
backtesting/indicator_search.py
================================
Iterative indicator-combination search for trend-following profiles.

Each run generates ~100–150 variants (or focused mutations on prior best),
tests them across all symbols, persists state, and prints ranked results.

State is stored in:
  backtesting/optimizer_state.json   — iteration counter + all-time best names
  backtesting/optimizer_results.json — full result records across all iterations

Usage:
  python backtesting/indicator_search.py              # auto-increments iteration
  python backtesting/indicator_search.py --iteration 1   # force broad pass
  python backtesting/indicator_search.py --days 21       # wider window
  python backtesting/indicator_search.py --reset         # clear state and restart
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

STATE_FILE   = str(Path(__file__).resolve().parent / "optimizer_state.json")
RESULTS_FILE = str(Path(__file__).resolve().parent / "optimizer_results.json")
SYMBOLS      = ["SOL_USDC", "ETH_USDC", "BTC_USDC", "HYPE_USDC", "BNB_USDC", "XRP_USDC"]
SCAN_DAYS    = 60
MIN_TRADES   = 6   # minimum total trades across all symbols to qualify

# Non-indicator settings held fixed each iteration (vary these in optimizer.py instead)
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
# Trend filter templates  (60m)
# ---------------------------------------------------------------------------
# Each template is a (indicators_list, min_required) tuple.
# The name key is used to label variants.

TREND_TEMPLATES = {

    "T_ema_adx_rsob":  (
        [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",    "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought","params": {"min_value": 68, "lookback_candles": 5, "hard_stop": True}},
        ], 3),

    "T_ema_adx_hard_rsob": (
        [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",    "params": {"min_adx": 22, "max_adx": 60, "hard_stop": True}},
            {"type": "rsi_overbought","params": {"min_value": 68, "lookback_candles": 5, "hard_stop": True}},
        ], 4),

    "T_ema_loose_adx_rsob": (
        [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.010}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.10, "max_pct_b": 0.95}},
            {"type": "adx_regime",    "params": {"min_adx": 20, "max_adx": 65}},
            {"type": "rsi_overbought","params": {"min_value": 70, "hard_stop": True}},
        ], 2),

    "T_ema_steep_adx_rsob": (
        [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.020, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.90}},
            {"type": "adx_regime",    "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought","params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    "T_rsimom_adx_rsob": (
        [
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.0, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",    "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought","params": {"min_value": 68, "lookback_candles": 5, "hard_stop": True}},
        ], 3),

    "T_rsimom_adx_hard": (
        [
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.0, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",    "params": {"min_adx": 22, "max_adx": 60, "hard_stop": True}},
            {"type": "rsi_overbought","params": {"min_value": 68, "lookback_candles": 5, "hard_stop": True}},
        ], 4),

    "T_emacross_adx_rsob": (
        [
            {"type": "ema_cross",     "params": {}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",    "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought","params": {"min_value": 68, "lookback_candles": 5, "hard_stop": True}},
        ], 3),

    "T_ema_nobb_adx_rsob": (
        [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "adx_regime",    "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought","params": {"min_value": 68, "lookback_candles": 5, "hard_stop": True}},
        ], 2),

    "T_ema_bb_rsob_loose": (
        [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.010, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.10, "max_pct_b": 1.00}},
            {"type": "rsi_overbought","params": {"min_value": 75, "hard_stop": True}},
        ], 2),

    "T_ema_rsimom_bb_rsob": (
        [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.010, "hard_stop": True}},
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.0}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "rsi_overbought","params": {"min_value": 68, "lookback_candles": 5, "hard_stop": True}},
        ], 3),

    # --- Breakout-focused trend templates (no rsi_overbought block) ---
    # For breakout continuation: price may be in 55–70 RSI zone (not blocking it)
    "T_emacross_adx_slope": (
        [
            {"type": "ema_cross",  "params": {}},
            {"type": "adx_regime", "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
        ], 3),

    "T_emacross_adx_strict": (
        [
            {"type": "ema_cross",  "params": {}},
            {"type": "adx_regime", "params": {"min_adx": 30, "max_adx": 65, "hard_stop": True}},
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
        ], 3),

    # Regime filter: 60m BB not expanding = market not already in extended surge
    "T_emacross_adx_regime": (
        [
            {"type": "ema_cross",       "params": {}},
            {"type": "adx_regime",      "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "bb_width_regime", "params": {"required_direction": "not_expanding", "lookback": 4}},
        ], 4),
}

# ---------------------------------------------------------------------------
# Entry filter templates  (15m)
# ---------------------------------------------------------------------------

ENTRY_TEMPLATES = {

    "E_base": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.65}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 57, "use_momentum": True, "early_threshold": 45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
        ], 6),

    "E_rsi50_loose_bb": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.0, "max_gap_pct": 2.0}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.00, "max_pct_b": 0.75}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 50, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ], 5),

    "E_rsi55_bb_tight": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.55, "hard_stop": True}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 43, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "max_slope_pct": 0.25, "hard_stop": True}},
        ], 5),

    "E_rsi57_bb_rsimom": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.55, "hard_stop": True}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 57, "use_momentum": True, "early_threshold": 45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "rsi_momentum",    "params": {"min_momentum": 0.5, "max_momentum": 3.0}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
        ], 7),

    "E_no_reversal": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.65}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 57, "use_momentum": True, "early_threshold": 45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
        ], 5),

    "E_reversal_higher_low": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low"}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.00, "max_pct_b": 0.70}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 50, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ], 5),

    "E_reversal_engulf": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "engulfing"}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.00, "max_pct_b": 0.70}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 50, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ], 5),

    "E_rev_mom": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 5, "oversold_threshold": 35, "current_min": 40, "min_jump": 4.0}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.00, "max_pct_b": 0.70}},
            {"type": "rsi_overbought",  "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ], 4),

    "E_rev_mom_strict": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38, "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.60}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 50, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
        ], 5),

    "E_loose_quorum": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.0, "max_gap_pct": 2.5}},
            {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.06}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.80}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 50, "use_momentum": True, "early_threshold": 38}},
            {"type": "rsi_overbought",  "params": {"min_value": 70, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.010, "hard_stop": True}},
        ], 4),

    "E_no_vwap": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.65}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 57, "use_momentum": True, "early_threshold": 45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
        ], 5),

    "E_rsimom_bb_wide": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.00, "max_pct_b": 0.75}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 43, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 65, "hard_stop": True}},
            {"type": "rsi_momentum",    "params": {"min_momentum": 0.5, "max_momentum": 4.0}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ], 5),

    "E_bull_close": (
        [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.65}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 50, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ], 5),

    # --- Breakout-focused entry templates ---
    # These look for momentum continuation, NOT oversold bounces.

    # RSI crosses 50 with acceleration + volume spike (basic breakout)
    "E_bkout_rsi_vol": (
        [
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 50, "use_momentum": True, "early_threshold": 46, "hard_stop": True}},
            {"type": "rsi_momentum",   "params": {"min_momentum": 1.0, "max_momentum": 8.0}},
            {"type": "rsi_overbought", "params": {"min_value": 72, "hard_stop": True}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.3}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "price_vs_vwap",  "params": {}},
        ], 4),

    # BB pct_b rising (price moving toward upper band) + volume + RSI>55
    "E_bkout_pctb_vol": (
        [
            {"type": "rsi_threshold",     "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 50, "hard_stop": True}},
            {"type": "rsi_momentum",      "params": {"min_momentum": 1.5, "max_momentum": 8.0}},
            {"type": "rsi_overbought",    "params": {"min_value": 72, "hard_stop": True}},
            {"type": "bb_pct_b_momentum", "params": {"required_direction": "rising", "lookback": 3}},
            {"type": "volume_spike",      "params": {"min_ratio": 1.5}},
            {"type": "ema_slope",         "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "price_vs_vwap",     "params": {}},
        ], 5),

    # Steep EMA slope (trend accelerating) + RSI>55 momentum + volume
    "E_bkout_steep_vol": (
        [
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 50, "hard_stop": True}},
            {"type": "rsi_momentum",   "params": {"min_momentum": 1.0, "max_momentum": 8.0}},
            {"type": "rsi_overbought", "params": {"min_value": 72, "hard_stop": True}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.5}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.03, "hard_stop": True}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -0.3, "max_gap_pct": 1.5}},
            {"type": "price_vs_vwap",  "params": {}},
        ], 5),
}

# ---------------------------------------------------------------------------
# Variant generation
# ---------------------------------------------------------------------------

def build_variants_from_templates() -> Dict[str, dict]:
    """Cross every trend template with every entry template = 10×13 = 130 variants."""
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
    """Return a shallow-mutated copy of a single indicator config."""
    ind = copy.deepcopy(ind)
    p = ind["params"]
    itype = ind["type"]

    if itype == "ema_slope":
        choices = [0.008, 0.010, 0.012, 0.015, 0.018, 0.020, 0.025]
        cur = p.get("min_slope_pct", 0.015)
        p["min_slope_pct"] = rng.choice([c for c in choices if c != cur])
        if "max_slope_pct" in p:
            p["max_slope_pct"] = rng.choice([0.20, 0.25, 0.30, None])
        p["hard_stop"] = rng.choice([True, True, False])   # 2/3 chance hard stop

    elif itype == "adx_regime":
        p["min_adx"] = rng.choice([18, 20, 22, 25, 28])
        p["max_adx"] = rng.choice([55, 60, 65])
        p["hard_stop"] = rng.choice([True, False, False])

    elif itype == "rsi_overbought":
        p["min_value"] = rng.choice([60, 63, 65, 68, 70, 72, 75])
        p["lookback_candles"] = rng.choice([None, 3, 5, 7])
        p["hard_stop"] = True

    elif itype == "bollinger_bands" and p.get("mode") == "pct_b":
        p["min_pct_b"] = rng.choice([-0.10, -0.05, 0.00, 0.05])
        p["max_pct_b"] = rng.choice([0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90, 0.95])
        p["hard_stop"] = rng.choice([True, False])

    elif itype == "rsi_threshold":
        p["min_value"] = rng.choice([48, 50, 52, 55, 57, 60])
        p["early_threshold"] = p["min_value"] - rng.choice([10, 12, 15])
        p["use_momentum"] = rng.choice([True, True, False])

    elif itype == "rsi_momentum":
        p["min_momentum"] = rng.choice([0.0, 0.3, 0.5, 0.8, 1.0])
        p["max_momentum"] = rng.choice([2.5, 3.0, 4.0, None])

    elif itype == "rsi_reversal_momentum":
        p["oversold_threshold"] = rng.choice([30, 33, 35, 38])
        p["current_min"] = rng.choice([38, 40, 42, 45])
        p["min_jump"] = rng.choice([3.0, 4.0, 5.0, 6.0])

    elif itype == "reversal_candle":
        available = ["hammer", "hammer", "bull_close", "higher_low", "engulfing"]
        p["pattern"] = rng.choice(available)
        if p["pattern"] == "hammer":
            p["min_body_pct"] = rng.choice([0.06, 0.07, 0.08, 0.10])
            p["max_drop_from_close_pct"] = rng.choice([None, 0.3, 0.5, 0.8])

    elif itype == "price_vs_ema":
        p["min_gap_pct"] = rng.choice([-1.0, -0.5, 0.0])
        p["max_gap_pct"] = rng.choice([1.0, 1.5, 2.0, 2.5])

    # Remove None values from params (JSON can't serialize them cleanly)
    ind["params"] = {k: v for k, v in p.items() if v is not None}
    return ind


def generate_variants_random(n: int = 100, seed: int = None) -> Dict[str, dict]:
    """
    Random mutation generator: start from random template pairs and apply
    mutations to individual indicators. Also explores TP/SL/trailing combos.
    Produces `n` novel variants.
    """
    rng = random.Random(seed)
    variants = {}
    t_names = list(TREND_TEMPLATES.keys())
    e_names = list(ENTRY_TEMPLATES.keys())

    # TP/SL combos — includes breakout-friendly high-TP options (arm trailing high)
    tp_sl_trailing = [
        # (tp, sl, trailing, arm, use_trailing)
        (1.0, 0.6, 0.4, 0.5, True),
        (1.2, 0.6, 0.4, 0.6, True),
        (1.2, 0.7, 0.4, 0.6, True),
        (1.0, 0.6, 0.0, 0.0, False),   # fixed TP/SL only
        (1.2, 0.6, 0.0, 0.0, False),
        (1.5, 0.7, 0.0, 0.0, False),
        (0.8, 0.5, 0.3, 0.4, True),
        (1.0, 0.5, 0.3, 0.5, True),
        (1.2, 0.8, 0.5, 0.6, True),
        (0.8, 0.6, 0.3, 0.4, True),    # original (baseline)
        # Breakout-oriented: high TP, arm trailing only after significant gain
        (1.2, 0.7, 0.5, 0.8, True),
        (1.5, 0.8, 0.5, 1.0, True),
        (1.5, 0.8, 0.0, 0.0, False),
        (2.0, 1.0, 0.0, 0.0, False),
    ]

    attempts = 0
    while len(variants) < n and attempts < n * 10:
        attempts += 1
        t_name = rng.choice(t_names)
        e_name = rng.choice(e_names)
        t_inds_orig, t_min = TREND_TEMPLATES[t_name]
        e_inds_orig, e_min = ENTRY_TEMPLATES[e_name]

        # Mutate 1-2 trend indicators
        t_inds = copy.deepcopy(t_inds_orig)
        for _ in range(rng.randint(1, 2)):
            idx = rng.randrange(len(t_inds))
            t_inds[idx] = _mutate_indicator(t_inds[idx], rng)

        # Mutate 1-3 entry indicators
        e_inds = copy.deepcopy(e_inds_orig)
        for _ in range(rng.randint(1, 3)):
            idx = rng.randrange(len(e_inds))
            e_inds[idx] = _mutate_indicator(e_inds[idx], rng)

        # Occasionally vary quorum
        t_min_var = t_min + rng.choice([-1, 0, 0, 1])
        t_min_var = max(2, min(t_min_var, len(t_inds)))
        e_min_var = e_min + rng.choice([-1, 0, 0, 1])
        e_min_var = max(3, min(e_min_var, len(e_inds)))

        # Pick a TP/SL/trailing combo
        tp, sl, trl, arm, use_trl = rng.choice(tp_sl_trailing)
        tp_tag = f"tp{int(tp*10)}sl{int(sl*10)}{'trl' if use_trl else 'fix'}"

        name = f"rand_{t_name[:10]}_{e_name[:10]}_{tp_tag}_s{seed or 0}_{attempts}"

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


def generate_variants_focused(top_results: list, n_per_winner: int = 8) -> Dict[str, dict]:
    """
    Focused mutations around the top-N results from previous iterations.
    For each winner: toggle hard_stops, shift thresholds, swap quorum.
    """
    variants = {}
    rng = random.Random(42)

    for r in top_results:
        cfg = r.get("config", {})
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

            action = rng.choice(["toggle_t_hs", "toggle_e_hs", "mutate_t", "mutate_e", "quorum", "mutate_both"])

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
                new_t_min = max(2, t_min + rng.choice([-1, 1]))
                new_e_min = max(3, e_min + rng.choice([-1, 1]))

            elif action == "mutate_both":
                if new_t:
                    new_t[rng.randrange(len(new_t))] = _mutate_indicator(new_t[rng.randrange(len(new_t))], rng)
                if new_e:
                    new_e[rng.randrange(len(new_e))] = _mutate_indicator(new_e[rng.randrange(len(new_e))], rng)

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

        # Systematically try better TP/SL ratios on each winner's indicator combo
        tp_sl_combos = [
            (1.0, 0.6, 0.4, 0.5, True),
            (1.2, 0.6, 0.4, 0.6, True),
            (1.0, 0.6, 0.0, 0.0, False),
            (1.2, 0.6, 0.0, 0.0, False),
            (1.5, 0.7, 0.0, 0.0, False),
            (1.2, 0.8, 0.5, 0.6, True),
            (1.0, 0.5, 0.3, 0.5, True),
            (1.2, 0.7, 0.5, 0.8, True),
            (1.5, 0.8, 0.5, 1.0, True),
            (1.5, 0.8, 0.0, 0.0, False),
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

def score_merged(trades: float, win_rate: float, total_pnl: float, profit_factor: float, avg_pnl: float = 0.0) -> float:
    if trades < MIN_TRADES:
        return -999.0
    pf  = min(profit_factor, 6.0)
    wr  = win_rate
    pnl = min(total_pnl, 30.0)
    # Heavy weight on avg_pnl: 0.20% → +40pts; 0.10% → +20pts; -0.1% → -20pts
    return avg_pnl * 200 + pf * 0.30 + wr * 100 * 0.25 + pnl * 0.10


def merge_symbol_results(sym_results: List[BacktestResult], name: str, config: dict) -> dict:
    all_trades = []
    signals_total = 0
    for r in sym_results:
        all_trades.extend(r.trades)
        signals_total += r.signals_fired

    closed = [t for t in all_trades if t.exit_price is not None]
    wins   = sum(1 for t in closed if t.won)

    win_rate = wins / len(closed) if closed else 0.0
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

    for i, (name, config) in enumerate(variants.items()):
        sym_results = []
        for sym in SYMBOLS:
            profile = BacktestProfile.from_dict(name, config)
            engine  = BacktestEngine(db, profile)
            r       = engine.run(symbol=sym, start=start, end=end)
            sym_results.append(r)
            done += 1

        merged = merge_symbol_results(sym_results, name, config)
        all_results.append(merged)

        # Progress line every 5%
        if done % max(1, total // 20) == 0 or done == total:
            best = max(all_results, key=lambda x: x["score"])
            print(
                f"  [{done/total:5.1%}] {done}/{total} "
                f"| best: {best['name'][:45]} "
                f"sc={best['score']:.1f} trades={best['trades']} "
                f"pf={best['profit_factor']:.2f}x wr={best['win_rate']:.0%}",
                flush=True,
            )

    return all_results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_ranking(results: List[dict], title: str, top_n: int = 30):
    ranked = sorted(results, key=lambda x: x["score"], reverse=True)
    qualifying = [r for r in ranked if r["score"] > -100]

    print(f"\n{'='*105}")
    print(f"  {title}")
    print(f"  {len(qualifying)} qualifying (≥{MIN_TRADES} trades) out of {len(results)} total variants")
    print(f"{'='*105}")
    print(f"{'Rank':<5} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} {'ProfFact':>9} {'Score':>7}  Name")
    print("-"*105)
    for rank, r in enumerate(qualifying[:top_n], 1):
        print(
            f"{rank:<5} {r['trades']:>7} {r['win_rate']:>6.1%} "
            f"{r['avg_pnl']:>7.2f}% {r['total_pnl']:>9.2f}% "
            f"{r['profit_factor']:>9.2f}x {r['score']:>7.2f}  {r['name']}"
        )
    if not qualifying:
        print("  (no variants hit MIN_TRADES — filters are too restrictive)")
    print("="*105)
    return ranked


def print_snippet(r: dict):
    cfg = r["config"]
    print(f'\n    "{r["name"][:60]}": {{')
    print(f'        # Score={r["score"]:.2f} | Trades={r["trades"]} '
          f'| WR={r["win_rate"]:.0%} | PF={r["profit_factor"]:.2f}x | PnL={r["total_pnl"]:+.1f}%')
    for k in ["take_profit_pct","stop_loss_pct","trailing_stop_pct","arm_trailing_stop_pct",
              "min_signal_confidence","min_volume_ratio","max_position_hours"]:
        if k in cfg:
            print(f'        "{k}": {cfg[k]},')
    print(f'        "trend_indicators": {json.dumps(cfg.get("trend_indicators",[]), indent=8)},')
    print(f'        "min_indicators_required": {cfg.get("min_indicators_required",2)},')
    print(f'        "entry_indicators": {json.dumps(cfg.get("entry_indicators",[]), indent=8)},')
    print(f'        "min_entry_indicators_required": {cfg.get("min_entry_indicators_required",3)},')
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
    # Strip non-serialisable items
    clean = []
    for r in results:
        rc = {k: v for k, v in r.items()}
        clean.append(rc)
    with open(RESULTS_FILE, "w") as f:
        json.dump(clean, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", type=int, default=None)
    parser.add_argument("--top-carry", type=int, default=8,
                        help="Top-N results to focus mutations on (iterations 3+)")
    parser.add_argument("--days",      type=int, default=SCAN_DAYS)
    parser.add_argument("--rand-n",    type=int, default=80,
                        help="Number of random variants to generate per iteration (iter 2)")
    parser.add_argument("--reset",     action="store_true",
                        help="Clear all saved state and start from scratch")
    parser.add_argument("--no-save",   action="store_true")
    args = parser.parse_args()

    if args.reset:
        for f in [STATE_FILE, RESULTS_FILE]:
            if os.path.exists(f):
                os.remove(f)
        print("[Reset] State cleared. Starting fresh.\n")

    state = load_state()
    iteration = args.iteration if args.iteration is not None else state["iteration"] + 1
    state["iteration"] = iteration

    end   = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.days)

    print(f"\n{'#'*72}")
    print(f"  INDICATOR COMBINATION SEARCH — Iteration {iteration}")
    print(f"  Window : {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')} ({args.days}d)")
    print(f"  Symbols: {SYMBOLS}")
    print(f"{'#'*72}\n")

    # ── Select generation strategy ────────────────────────────────────────
    if iteration == 1:
        print("[Gen] Strategy: template cross-product (broad exploration)\n")
        variants = build_variants_from_templates()

    elif iteration == 2:
        print(f"[Gen] Strategy: random mutations of templates ({args.rand_n} variants)\n")
        variants = generate_variants_random(n=args.rand_n, seed=iteration)

    else:
        prev_results = load_results()
        qualifying = sorted(
            [r for r in prev_results if r["score"] > -100],
            key=lambda x: x["score"], reverse=True
        )[:args.top_carry]

        if qualifying:
            print(f"[Gen] Strategy: focused mutations around top-{len(qualifying)} prior winners\n")
            variants = generate_variants_focused(qualifying, n_per_winner=10)
        else:
            print("[Gen] No qualifying prior results — falling back to random mutations\n")
            variants = generate_variants_random(n=args.rand_n, seed=iteration * 17)

    # Remove already-tried names
    tried = set(state.get("tried_names", []))
    new_variants = {k: v for k, v in variants.items() if k not in tried}
    skipped = len(variants) - len(new_variants)
    print(f"[Gen] {len(variants)} generated | {skipped} already tried | {len(new_variants)} new\n")

    if not new_variants:
        print("Nothing new to try — run with --iteration 2 or --reset to explore more.")
        return

    # ── Run backtests ─────────────────────────────────────────────────────
    with get_db_session() as db:
        this_run = run_variants(db, new_variants, start, end)

    # ── Merge with all-time ───────────────────────────────────────────────
    prev_all = load_results()
    prev_map  = {r["name"]: r for r in prev_all}
    for r in this_run:
        prev_map[r["name"]] = r
    all_results = list(prev_map.values())

    # ── Print rankings ────────────────────────────────────────────────────
    print_ranking(this_run,   f"THIS ITERATION ({iteration}) RESULTS",                     top_n=20)
    ranked_all = print_ranking(all_results, f"ALL-TIME TOP RESULTS (after iteration {iteration})", top_n=30)

    qualifying_all = [r for r in ranked_all if r["score"] > -100]
    if qualifying_all:
        print(f"\n{'='*72}")
        print(f"  TOP-3 PASTE-READY ENTRIES")
        print(f"{'='*72}")
        for r in qualifying_all[:3]:
            print_snippet(r)

    # ── Save state ────────────────────────────────────────────────────────
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
              f"wr={b['win_rate']:.0%} pf={b['profit_factor']:.2f}x pnl={b['total_pnl']:+.1f}%")
        print(f"    {b['name']}")


if __name__ == "__main__":
    main()
