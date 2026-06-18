"""
backtesting/mr_indicator_search.py
====================================
Iterative indicator-combination search for MEAN REVERSION profiles.

Logic is fundamentally different from trend_following search:
  - Trend filter (60m): looks for OVERSOLD / DISPLACED price (below EMA50)
  - Entry filter (15m): looks for REVERSAL signals (RSI bounce, candles, BB lower)

State files are separate from the trend search:
  backtesting/mr_optimizer_state.json
  backtesting/mr_optimizer_results.json

Usage:
  python backtesting/mr_indicator_search.py
  python backtesting/mr_indicator_search.py --reset
  python backtesting/mr_indicator_search.py --days 45
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

STATE_FILE   = str(Path(__file__).resolve().parent / "mr_optimizer_state.json")
RESULTS_FILE = str(Path(__file__).resolve().parent / "mr_optimizer_results.json")
SYMBOLS      = ["SOL_USDC", "ETH_USDC", "BTC_USDC", "HYPE_USDC", "BNB_USDC", "XRP_USDC"]
SCAN_DAYS    = 60
MIN_TRADES   = 6

# Fixed base settings — mean reversion specific
BASE_SETTINGS = {
    "strategy_type":            "mean_reversion",
    "entry_timeframe":          "15",
    "trend_timeframe":          "60",
    "take_profit_pct":          1.0,
    "stop_loss_pct":            0.7,
    "trailing_stop_pct":        0.5,
    "arm_trailing_stop_pct":    0.5,
    "use_trailing_stop":        True,
    "signal_cooldown_minutes":  20,
    "min_signal_confidence":    66.0,
    "min_volume_ratio":         1.0,
    "use_trend_filter":         True,
    "use_entry_filter":         True,
    "max_position_hours":       6,
    "use_market_regime_filter": False,
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
# TREND TEMPLATES  (60m — looking for oversold / displaced conditions)
# ---------------------------------------------------------------------------
# Each template: (indicators_list, min_required)
# Core logic: price must be meaningfully below EMA50 AND HTF RSI must be low.
# rsi_overbought(min_value=X) acts as a ceiling gate: passes when RSI < X.

TREND_TEMPLATES = {

    # ── V3 baseline: extended OR near EMA50 + RSI<38 gate ──────────────────
    # This replicates the v3 structure exactly as the starting point.
    "T_v3_baseline": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct":  0.5, "max_gap_pct": -0.5}},
            {"type": "rsi_overbought",           "params": {"min_value": 38, "hard_stop": True}},
        ], 2),

    # ── Extended displacement only (1.5–3%) + RSI<38 ───────────────────────
    "T_disp_rsi38": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
            {"type": "rsi_overbought",           "params": {"min_value": 38, "hard_stop": True}},
        ], 2),

    # ── Wider displacement window (1.0–4%) + RSI<38 ────────────────────────
    "T_disp_wide_rsi38": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.0, "max_gap_pct": -4.0}},
            {"type": "rsi_overbought",           "params": {"min_value": 38, "hard_stop": True}},
        ], 2),

    # ── Deeper displacement only (2–5%) + RSI<38 ───────────────────────────
    "T_disp_deep_rsi38": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -2.0, "max_gap_pct": -5.0}},
            {"type": "rsi_overbought",           "params": {"min_value": 38, "hard_stop": True}},
        ], 2),

    # ── Stricter RSI gate (<35) + standard displacement ────────────────────
    "T_disp_rsi35": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.5}},
            {"type": "rsi_overbought",           "params": {"min_value": 35, "hard_stop": True}},
        ], 2),

    # ── Looser RSI gate (<42) — catches less-extreme oversold ──────────────
    "T_disp_rsi42": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.0, "max_gap_pct": -3.0}},
            {"type": "rsi_overbought",           "params": {"min_value": 42, "hard_stop": True}},
        ], 2),

    # ── Displacement + 60m BB near/below lower band + RSI gate ─────────────
    # Confirms price is below lower Bollinger on the higher timeframe too.
    "T_disp_bb_rsi38": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.2, "max_pct_b": 0.2}},
            {"type": "rsi_overbought",           "params": {"min_value": 38, "hard_stop": True}},
        ], 2),

    # ── Displacement + ADX gate + RSI gate ─────────────────────────────────
    # ADX confirms the move is real (not slow drift). Blocks entries in pure chop.
    "T_disp_adx_rsi38": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
            {"type": "adx_regime",               "params": {"min_adx": 20, "max_adx": 65}},
            {"type": "rsi_overbought",           "params": {"min_value": 38, "hard_stop": True}},
        ], 2),

    # ── rsi_oversold indicator (RSI turning up from oversold) + displacement
    # More nuanced than rsi_overbought gate: confirms RSI was oversold AND is now rising.
    "T_disp_rsioversold": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.0, "max_gap_pct": -4.0}},
            {"type": "rsi_oversold",             "params": {"max_value": 40, "require_rising": False}},
        ], 2),

    # ── rsi_oversold (turning up) + displacement — strict version ──────────
    "T_disp_rsioversold_turn": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.5}},
            {"type": "rsi_oversold",             "params": {"max_value": 38, "require_rising": True, "min_momentum": 0.3}},
        ], 2),

    # ── rsi_range (invert=True) — RSI must be IN range 20-45 ───────────────
    # Tighter band than the simple ceiling gate; also blocks if RSI too low (< 20).
    "T_disp_rsirange": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.5}},
            {"type": "rsi_range",                "params": {"min": 20, "max": 45, "invert": True}},
        ], 2),

    # ── EMA20 displacement (shallower, -0.5% to -2%) + RSI<40 ──────────────
    # Catches shallower pullbacks where price hasn't fallen as far from EMA50.
    "T_ema20_disp_rsi40": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": -2.5}},
            {"type": "rsi_overbought",           "params": {"min_value": 40, "hard_stop": True}},
        ], 2),

    # ── 60m price below VWAP + EMA50 displacement + RSI gate ───────────────
    # price_below_vwap on the 60m confirms macro bearish context for the bounce.
    "T_disp_vwap_rsi38": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
            {"type": "price_below_vwap",         "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "rsi_overbought",           "params": {"min_value": 38, "hard_stop": True}},
        ], 2),

    # ── CREATIVE: 60m BB lower band as primary signal (no EMA displacement) ─
    # When 60m price is near/below lower BB, that IS the oversold context.
    # Simpler and more universal — captures squeeze-and-bounce patterns too.
    "T_bb_lower_rsi40": (
        [
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": -0.3, "max_pct_b": 0.15}},
            {"type": "rsi_overbought",  "params": {"min_value": 40, "hard_stop": True}},
        ], 2),

    # ── CREATIVE: 60m BB lower band (tighter) + displacement combo ──────────
    "T_bb_tight_disp": (
        [
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": -0.3, "max_pct_b": 0.10}},
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.0, "max_gap_pct": -5.0}},
            {"type": "rsi_overbought",           "params": {"min_value": 42, "hard_stop": True}},
        ], 2),

    # ── CREATIVE: Price below BOTH EMA20 and EMA50 ──────────────────────────
    # Double stacked: short-term AND medium-term trend both below price.
    # More selective setup — only fires when both EMAs are overhead.
    "T_dual_ema_below": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -4.0}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.3, "max_gap_pct": -3.0}},
            {"type": "rsi_overbought",           "params": {"min_value": 40, "hard_stop": True}},
        ], 2),

    # ── CREATIVE: Displacement + BB expanding (confirming real volatile move)
    # bb_width_regime "expanding" = BB bands are widening = real momentum.
    # Differentiates genuine selloffs from slow drift below EMA.
    "T_disp_bb_expanding": (
        [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -4.0}},
            {"type": "bb_width_regime",          "params": {"required_direction": "expanding", "lookback": 3}},
            {"type": "rsi_overbought",           "params": {"min_value": 42, "hard_stop": True}},
        ], 2),

    # ── CREATIVE: rsi_oversold turning up + ADX (no displacement required) ──
    # Different structural logic: confirms via RSI momentum + real trend strength.
    # Catches bounces where price hasn't fallen far from EMA but RSI is crushed.
    "T_rsioversold_adx": (
        [
            {"type": "rsi_oversold", "params": {"max_value": 38, "require_rising": True, "min_momentum": 0.3}},
            {"type": "adx_regime",   "params": {"min_adx": 18, "max_adx": 65}},
        ], 2),

    # ── CREATIVE: rsi_range (RSI in 18-42 zone) + ADX + displacement ────────
    # Tighter oversold window with both a floor (>18, not in free fall) and
    # ceiling (<42, not yet recovering) + trend strength + price confirmation.
    "T_rsirange_adx_disp": (
        [
            {"type": "rsi_range",                "params": {"min": 18, "max": 42, "invert": True}},
            {"type": "adx_regime",               "params": {"min_adx": 18, "max_adx": 65}},
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.0, "max_gap_pct": -5.0}},
        ], 2),

    # ── CREATIVE: 60m BB lower band + VWAP below (deeper bearish context) ───
    "T_bb_vwap_rsi": (
        [
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": -0.3, "max_pct_b": 0.20}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "rsi_overbought",   "params": {"min_value": 40, "hard_stop": True}},
        ], 2),
}

# ---------------------------------------------------------------------------
# ENTRY TEMPLATES  (15m — looking for reversal confirmation signals)
# ---------------------------------------------------------------------------

ENTRY_TEMPLATES = {

    # ── V3 baseline entry ────────────────────────────────────────────────────
    "E_v3_baseline": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 3.0, "require_sustained": False,
                "sustained_rise_mode": "net", "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",        "params": {"min_value": 40}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 4),

    # ── Strict reversal momentum ─────────────────────────────────────────────
    # Higher min_jump: needs a bigger RSI bounce to confirm exhaustion/turn.
    "E_revmom_strict": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 28,
                "current_min": 32, "min_jump": 5.0, "require_sustained": False, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.25}},
            {"type": "rsi_overbought",        "params": {"min_value": 42, "hard_stop": True}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
        ], 4),

    # ── Loose reversal momentum (catches earlier in move) ───────────────────
    "E_revmom_loose": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 10, "oversold_threshold": 35,
                "current_min": 28, "min_jump": 2.5, "require_sustained": False, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.3, "max_gap_pct": -10.0}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.40}},
            {"type": "rsi_overbought",        "params": {"min_value": 45}},
            {"type": "volume_spike",          "params": {"min_ratio": 0.8, "max_ratio": 8.0}},
        ], 3),

    # ── Reversal momentum + bull_close candle (confirms the bounce candle) ──
    "E_revmom_bull_close": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 3.0, "hard_stop": True}},
            {"type": "reversal_candle",       "params": {"pattern": "bull_close", "min_close_pct": 0.45,
                "require_bull": True, "max_drop_from_close_pct": 0.6}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",        "params": {"min_value": 42, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 4),

    # ── Reversal momentum + hammer candle ───────────────────────────────────
    "E_revmom_hammer": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 28, "min_jump": 3.0, "hard_stop": True}},
            {"type": "reversal_candle",       "params": {"pattern": "hammer", "min_body_pct": 0.08,
                "max_drop_from_close_pct": 0.5}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",        "params": {"min_value": 42, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 4),

    # ── Reversal momentum + engulfing candle ────────────────────────────────
    "E_revmom_engulf": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 3.0, "hard_stop": True}},
            {"type": "reversal_candle",       "params": {"pattern": "engulfing"}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35}},
            {"type": "rsi_overbought",        "params": {"min_value": 42, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 4),

    # ── Candle-only entry (no reversal momentum — entry on candle + volume) ─
    "E_candle_vol": (
        [
            {"type": "reversal_candle",  "params": {"pattern": "bull_close", "min_close_pct": 0.50,
                "require_bull": True}},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.25}},
            {"type": "rsi_overbought",   "params": {"min_value": 42, "hard_stop": True}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.3, "max_ratio": 8.0, "hard_stop": True}},
        ], 4),

    # ── Tight BB (only near/below lower band) + reversal momentum ───────────
    "E_revmom_tight_bb": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 3.0, "hard_stop": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b",
                "min_pct_b": -0.1, "max_pct_b": 0.15}},
            {"type": "rsi_overbought",        "params": {"min_value": 42, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 4),

    # ── High volume requirement (capitulation candle logic) ──────────────────
    "E_revmom_bigvol": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 4, "oversold_threshold": 32,
                "current_min": 28, "min_jump": 4.0, "require_sustained": False, "hard_stop": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",        "params": {"min_value": 42, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.5, "max_ratio": 8.0, "hard_stop": True}},
        ], 4),

    # ── rsi_oversold on 15m entry (RSI currently oversold, not just bouncing)
    "E_rsi_oversold_base": (
        [
            {"type": "rsi_oversold",     "params": {"max_value": 35, "require_rising": False}},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",   "params": {"min_value": 42, "hard_stop": True}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 3),

    # ── rsi_oversold turning up + reversal momentum (double confirmation) ───
    "E_rsi_oversold_turn": (
        [
            {"type": "rsi_oversold",          "params": {"max_value": 38, "require_rising": True, "min_momentum": 0.5}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 2.5, "hard_stop": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35}},
            {"type": "rsi_overbought",        "params": {"min_value": 45, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.3, "max_gap_pct": -10.0}},
        ], 3),

    # ── 15m price_extended_below_ema20 + reversal momentum ──────────────────
    # Confirms entry-TF displacement matches the setup-TF displacement.
    "E_revmom_ema20ext": (
        [
            {"type": "rsi_reversal_momentum",    "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 3.0, "hard_stop": True}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.3, "max_gap_pct": -3.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",           "params": {"min_value": 40, "hard_stop": True}},
            {"type": "price_below_vwap",         "params": {"min_gap_pct": -0.3, "max_gap_pct": -10.0}},
            {"type": "volume_spike",             "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 4),

    # ── rsi_range (RSI in 20-45 oversold zone) + reversal momentum ──────────
    "E_rsirange_revmom": (
        [
            {"type": "rsi_range",             "params": {"min": 20, "max": 45, "invert": True}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 28, "min_jump": 3.0, "hard_stop": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.3, "max_gap_pct": -10.0}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 3),

    # ── No VWAP gate (some bounces happen above VWAP on 15m after deep flush)
    "E_revmom_no_vwap": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 3.0, "hard_stop": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",        "params": {"min_value": 40, "hard_stop": True}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 3),

    # ── CREATIVE: BB lower band TOUCH mode (price AT/below band, not just near)
    # Mode "touch" fires when price <= lower_band * (1 + tolerance/100).
    # More precise than pct_b: enters right as price hits the band.
    "E_bb_touch_revmom": (
        [
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "touch", "tolerance_pct": 0.5}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 28, "min_jump": 2.5, "hard_stop": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 42, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.3, "max_gap_pct": -10.0}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 3),

    # ── CREATIVE: 15m RSI in oversold zone + reversal candle (no revmom) ────
    # rsi_range with invert=True catches RSI between 20-42 (genuinely oversold).
    # Combines with candle confirmation — different angle from reversal momentum.
    "E_rsirange_candle": (
        [
            {"type": "rsi_range",        "params": {"min": 20, "max": 42, "invert": True}},
            {"type": "reversal_candle",  "params": {"pattern": "bull_close", "min_close_pct": 0.45,
                "require_bull": True}},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.30}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
        ], 3),

    # ── CREATIVE: Double oversold confirmation (rsi_oversold turning up + revmom)
    # Two independent RSI reversal signals must agree. Higher conviction,
    # fewer signals but should have higher accuracy.
    "E_multi_oversold": (
        [
            {"type": "rsi_oversold",          "params": {"max_value": 35, "require_rising": True,
                "min_momentum": 0.5}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 2.5, "hard_stop": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35}},
            {"type": "rsi_overbought",        "params": {"min_value": 45, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.3, "max_gap_pct": -10.0}},
        ], 3),

    # ── CREATIVE: Higher-low candle + reversal momentum ─────────────────────
    # higher_low pattern (price makes a higher low vs prior candle) is the
    # earliest structural sign that selling pressure is ending. Combine with
    # reversal momentum to ensure RSI is also turning.
    "E_higher_low_revmom": (
        [
            {"type": "reversal_candle",       "params": {"pattern": "higher_low"}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 28, "min_jump": 2.5, "hard_stop": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35}},
            {"type": "rsi_overbought",        "params": {"min_value": 42, "hard_stop": True}},
            {"type": "price_below_vwap",      "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",          "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ], 3),

    # ── CREATIVE: Loose entry — wide BB, minimal volume, just revmom + rsi ──
    # Tests whether the high-quality trend filter (from trend template) can
    # carry a very permissive entry filter. Lets the HTF setup do the work.
    "E_revmom_permissive": (
        [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 10, "oversold_threshold": 38,
                "current_min": 25, "min_jump": 2.0, "hard_stop": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.50}},
            {"type": "rsi_overbought",        "params": {"min_value": 50, "hard_stop": True}},
        ], 2),
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
    """Return a mutated copy of a single mean-reversion indicator config."""
    ind = copy.deepcopy(ind)
    p = ind["params"]
    itype = ind["type"]

    if itype == "price_extended_below_ema":
        ema = p.get("ema", 50)
        if ema == 50:
            min_choices = [-1.0, -1.5, -2.0, -2.5]
            max_choices = [-2.5, -3.0, -3.5, -4.0, -5.0]
        else:
            min_choices = [-0.3, -0.5, -0.8, -1.0]
            max_choices = [-1.5, -2.0, -2.5, -3.0]
        p["min_gap_pct"] = rng.choice(min_choices)
        p["max_gap_pct"] = rng.choice(max_choices)
        # Ensure max < min (deeper displacement)
        if p["max_gap_pct"] >= p["min_gap_pct"]:
            p["max_gap_pct"] = p["min_gap_pct"] - 1.0

    elif itype == "rsi_overbought":
        p["min_value"] = rng.choice([33, 35, 38, 40, 42, 45])
        p["hard_stop"] = True

    elif itype == "rsi_oversold":
        p["max_value"] = rng.choice([30, 33, 35, 38, 40, 42])
        p["require_rising"] = rng.choice([True, True, False])
        if p["require_rising"]:
            p["min_momentum"] = rng.choice([0.3, 0.5, 0.8])

    elif itype == "rsi_range":
        p["min"] = rng.choice([15, 18, 20, 22, 25])
        p["max"] = rng.choice([38, 40, 42, 45, 48])
        p["invert"] = True  # for MR, always want RSI IN the range

    elif itype == "rsi_reversal_momentum":
        p["lookback_candles"]    = rng.choice([4, 6, 8, 10, 12])
        p["oversold_threshold"]  = rng.choice([25, 28, 30, 32, 35])
        p["current_min"]         = rng.choice([25, 28, 30, 32, 35])
        p["min_jump"]            = rng.choice([2.0, 2.5, 3.0, 4.0, 5.0])
        p["require_sustained"]   = rng.choice([False, False, True])
        p["hard_stop"]           = True

    elif itype == "bollinger_bands" and p.get("mode") == "pct_b":
        p["min_pct_b"] = rng.choice([-0.2, -0.1, -0.05, 0.0])
        p["max_pct_b"] = rng.choice([0.15, 0.20, 0.25, 0.30, 0.35, 0.40])

    elif itype == "volume_spike":
        p["min_ratio"] = rng.choice([0.8, 1.0, 1.1, 1.2, 1.5, 1.8])
        p["max_ratio"] = 8.0
        p["hard_stop"] = rng.choice([True, False, False])

    elif itype == "price_below_vwap":
        p["min_gap_pct"] = rng.choice([-0.2, -0.3, -0.5, -0.8])
        p["max_gap_pct"] = rng.choice([-5.0, -8.0, -10.0])

    elif itype == "reversal_candle":
        available = ["bull_close", "bull_close", "hammer", "engulfing", "higher_low"]
        p["pattern"] = rng.choice(available)
        if p["pattern"] == "bull_close":
            p["min_close_pct"]         = rng.choice([0.40, 0.45, 0.50, 0.55])
            p["require_bull"]          = True
            p["max_drop_from_close_pct"] = rng.choice([0.4, 0.5, 0.6, 0.8])
        elif p["pattern"] == "hammer":
            p["min_body_pct"]          = rng.choice([0.06, 0.08, 0.10])
            p["max_drop_from_close_pct"] = rng.choice([0.4, 0.5, 0.7])

    elif itype == "adx_regime":
        p["min_adx"]  = rng.choice([15, 18, 20, 22, 25])
        p["max_adx"]  = rng.choice([50, 55, 60, 65])
        p["hard_stop"] = rng.choice([True, False, False])

    ind["params"] = {k: v for k, v in p.items() if v is not None}
    return ind


def generate_variants_random(n: int = 100, seed: int = None) -> Dict[str, dict]:
    """Random mutation generator for mean reversion."""
    rng = random.Random(seed)
    variants = {}
    t_names = list(TREND_TEMPLATES.keys())
    e_names = list(ENTRY_TEMPLATES.keys())

    # TP/SL combos — mean reversion focused (tighter, faster exits)
    tp_sl_trailing = [
        # (tp, sl, trailing, arm, use_trailing)
        (1.0, 0.7, 0.5, 0.5, True),   # v3/v9 baseline
        (1.0, 0.6, 0.4, 0.5, True),   # tighter SL
        (1.2, 0.7, 0.5, 0.6, True),   # higher TP
        (1.2, 0.8, 0.5, 0.7, True),
        (0.8, 0.6, 0.3, 0.4, True),   # smaller TP/SL
        (1.0, 0.7, 0.0, 0.0, False),  # fixed TP/SL only
        (1.2, 0.8, 0.0, 0.0, False),
        (1.5, 0.8, 0.0, 0.0, False),  # stretch TP
        (1.5, 1.0, 0.0, 0.0, False),  # wide TP/SL
        (1.5, 0.8, 0.5, 0.8, True),
        (0.8, 0.5, 0.3, 0.4, True),   # quick TP
        (1.0, 0.8, 0.4, 0.6, True),
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
        for _ in range(rng.randint(1, 3)):
            idx = rng.randrange(len(e_inds))
            e_inds[idx] = _mutate_indicator(e_inds[idx], rng)

        t_min_var = t_min + rng.choice([-1, 0, 0, 1])
        t_min_var = max(1, min(t_min_var, len(t_inds)))
        e_min_var = e_min + rng.choice([-1, 0, 0, 1])
        e_min_var = max(2, min(e_min_var, len(e_inds)))

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

        # TP/SL sweep on each winner's indicators
        tp_sl_combos = [
            (1.0, 0.7, 0.5, 0.5, True),
            (1.0, 0.6, 0.4, 0.5, True),
            (1.2, 0.7, 0.5, 0.6, True),
            (0.8, 0.6, 0.3, 0.4, True),
            (1.0, 0.7, 0.0, 0.0, False),
            (1.2, 0.8, 0.0, 0.0, False),
            (1.5, 0.8, 0.0, 0.0, False),
            (1.5, 0.8, 0.5, 0.8, True),
            (1.2, 0.8, 0.5, 0.7, True),
            (0.8, 0.5, 0.3, 0.4, True),
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
    if trades < MIN_TRADES:
        return -999.0
    pf  = min(profit_factor, 6.0)
    wr  = win_rate
    pnl = min(total_pnl, 30.0)
    # avg_pnl is the primary objective (net of fees matters most for MR)
    return avg_pnl * 200 + pf * 0.30 + wr * 100 * 0.25 + pnl * 0.10


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
    print(f"  {len(qualifying)} qualifying (≥{MIN_TRADES} trades) out of {len(results)} total")
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
        print("  (no variants hit MIN_TRADES — filters may be too restrictive)")
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
    clean = [{k: v for k, v in r.items()} for r in results]
    with open(RESULTS_FILE, "w") as f:
        json.dump(clean, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Mean reversion indicator combination search")
    parser.add_argument("--iteration", type=int, default=None)
    parser.add_argument("--top-carry", type=int, default=8)
    parser.add_argument("--days",      type=int, default=SCAN_DAYS)
    parser.add_argument("--rand-n",    type=int, default=80)
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

    n_trend  = len(TREND_TEMPLATES)
    n_entry  = len(ENTRY_TEMPLATES)
    print(f"\n{'#'*72}")
    print(f"  MEAN REVERSION INDICATOR SEARCH — Iteration {iteration}")
    print(f"  Window  : {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')} ({args.days}d)")
    print(f"  Symbols : {SYMBOLS}")
    print(f"  Templates: {n_trend} trend × {n_entry} entry = {n_trend*n_entry} base combos")
    print(f"{'#'*72}\n")

    if iteration == 1:
        print("[Gen] Strategy: template cross-product (broad exploration)\n")
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

    print_ranking(this_run,   f"THIS ITERATION ({iteration}) RESULTS",                     top_n=20)
    ranked_all = print_ranking(all_results, f"ALL-TIME TOP RESULTS (after iteration {iteration})", top_n=30)

    qualifying_all = [r for r in ranked_all if r["score"] > -100]
    if qualifying_all:
        print(f"\n{'='*72}")
        print(f"  TOP-3 PASTE-READY ENTRIES")
        print(f"{'='*72}")
        for r in qualifying_all[:3]:
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
              f"wr={b['win_rate']:.0%} pf={b['profit_factor']:.2f}x pnl={b['total_pnl']:+.1f}%")
        print(f"    {b['name']}")


if __name__ == "__main__":
    main()
