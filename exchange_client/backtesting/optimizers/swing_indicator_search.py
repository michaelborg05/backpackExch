"""
backtesting/swing_indicator_search.py
=======================================
Iterative indicator-combination search for 4hr SWING profiles.

Designed for:
  - TREND timeframe: 240m (4hr) — confirms genuine bullish macro context
  - ENTRY timeframe:  60m (1hr) — confirms pullback / entry timing

Two scoring modes selectable at CLI:
  --mode tight   : Tight-pullback style  (TP 1.5–2%, SL 0.8–1.2%)
  --mode swing   : Full swing style      (TP 2.5–3.5%, SL 1.5–2%)
  (default: tight — this is the problem profile to fix)

State files:
  backtesting/swing_optimizer_state.json
  backtesting/swing_optimizer_results.json

Usage:
  python backtesting/swing_indicator_search.py
  python backtesting/swing_indicator_search.py --reset
  python backtesting/swing_indicator_search.py --mode swing
  python backtesting/swing_indicator_search.py --days 90
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

STATE_FILE   = str(Path(__file__).resolve().parent / "swing_optimizer_state.json")
RESULTS_FILE = str(Path(__file__).resolve().parent / "swing_optimizer_results.json")
SYMBOLS      = ["SOL_USDC", "ETH_USDC", "BTC_USDC", "XRP_USDC", "BNB_USDC"]
SCAN_DAYS    = 75
MIN_TRADES   = 8   # swing profiles fire less often — lower bar than MR

# Fixed base settings — 4hr/1hr swing
BASE_SETTINGS = {
    "strategy_type":            "trend_following",
    "entry_timeframe":          "60",
    "trend_timeframe":          "240",
    "take_profit_pct":          1.5,
    "stop_loss_pct":            1.0,
    "trailing_stop_pct":        0.7,
    "arm_trailing_stop_pct":    0.9,
    "use_trailing_stop":        True,
    "signal_cooldown_minutes":  60,
    "min_signal_confidence":    74.0,
    "min_volume_ratio":         1.0,
    "use_trend_filter":         True,
    "use_entry_filter":         True,
    "max_position_hours":       36,
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
# TP/SL combos
# ---------------------------------------------------------------------------

# Tight-pullback style: quick bounces, narrow TP/SL
TP_SL_TIGHT = [
    # (tp, sl, trailing, arm, use_trailing)
    (1.5, 1.0, 0.7, 0.9, True),   # v19 baseline
    (1.5, 0.8, 0.6, 0.8, True),   # tighter SL
    (1.5, 1.0, 0.0, 0.0, False),  # fixed TP
    (2.0, 1.0, 0.7, 1.0, True),   # wider TP
    (2.0, 1.0, 0.0, 0.0, False),  # wider fixed
    (2.0, 1.2, 0.8, 1.2, True),
    (1.5, 1.2, 0.7, 0.9, True),   # wider SL
    (1.5, 0.8, 0.0, 0.0, False),
    (2.0, 0.8, 0.5, 0.8, True),   # tight SL wide TP
    (1.2, 0.8, 0.5, 0.7, True),   # smaller target
    (1.8, 1.0, 0.6, 0.9, True),
    (2.5, 1.2, 0.8, 1.2, True),   # push wider — maybe tight SL is the issue
]

# Full-swing style: multi-day holds, bigger moves
TP_SL_SWING = [
    (3.0, 2.0, 1.2, 1.5, True),   # p3_base baseline
    (3.0, 2.0, 0.0, 0.0, False),  # fixed TP
    (2.5, 1.5, 1.0, 1.2, True),
    (3.5, 2.0, 1.3, 1.5, True),
    (3.0, 1.5, 1.0, 1.2, True),
    (3.5, 2.5, 0.0, 0.0, False),
    (2.5, 2.0, 1.0, 1.5, True),
    (4.0, 2.5, 0.0, 0.0, False),
    (3.0, 2.5, 1.2, 1.8, True),
    (2.5, 1.5, 0.0, 0.0, False),
]

# ---------------------------------------------------------------------------
# TREND TEMPLATES  (4hr / 240m)
# ────────────────────────────────────────────────────────────────────────────
# Goal: confirm a GENUINE BULLISH macro context — not just "EMA crossed once".
# The current v19 problem: it enters when 4hr trend is still weak/falling.
# ---------------------------------------------------------------------------

TREND_TEMPLATES = {

    # ── V19 baseline (what's currently running — the broken one) ───────────
    # Kept as reference to understand where the optimizer starts from.
    "T_v19_baseline": (
        [
            {"type": "rsi_range",     "params": {"min": 40, "max": 65, "invert": True, "hard_stop": True}},
            {"type": "adx_regime",    "params": {"min_adx": 14, "max_adx": 27}},
            {"type": "ema_cross",     "params": {"use_slope": False}, "hard_stop": True},
        ], 4),

    # ── EMA cross + RSI genuinely bullish + ADX confirmed ──────────────────
    # Tighter RSI window (50-63) — must be in the bullish momentum zone, not neutral.
    # ADX > 18 confirms real trend strength (filters the low-ADX choppy losses).
    "T_cross_rsi_bullish_adx": (
        [
            {"type": "ema_cross",  "params": {}, "hard_stop": True},
            {"type": "rsi_range",  "params": {"min": 50, "max": 63, "invert": True}},
            {"type": "adx_regime", "params": {"min_adx": 18, "max_adx": 30}},
        ], 3),

    # ── EMA cross + EMA20 slope rising + RSI not overbought ────────────────
    # EMA20 must be sloping up — catches false EMA crosses where momentum stalled.
    "T_cross_slope_rsob": (
        [
            {"type": "ema_cross",  "params": {}, "hard_stop": True},
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.005, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
        ], 3),

    # ── EMA cross + price within EMA50 band (not too extended) ─────────────
    # Price within -2% to +4% of EMA50: confirms pullback territory, not overbought surge.
    "T_cross_price_band_rsob": (
        [
            {"type": "ema_cross",    "params": {}, "hard_stop": True},
            {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": -3.0, "max_gap_pct": 4.0}},
            {"type": "rsi_overbought", "params": {"min_value": 63, "hard_stop": True}},
        ], 3),

    # ── EMA cross + RSI in [50-62] + price vs EMA50 band ──────────────────
    # Most complete baseline: cross + momentum zone + not extended
    "T_cross_rsi_band": (
        [
            {"type": "ema_cross",    "params": {}, "hard_stop": True},
            {"type": "rsi_range",    "params": {"min": 50, "max": 62, "invert": True}},
            {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": -3.5, "max_gap_pct": 3.5}},
        ], 3),

    # ── Strict: EMA cross + ADX > 20 (hard) + RSI 50-65 ───────────────────
    # Hard ADX stop: don't enter unless there's real trend power.
    "T_cross_adx_hard": (
        [
            {"type": "ema_cross",  "params": {}, "hard_stop": True},
            {"type": "adx_regime", "params": {"min_adx": 20, "max_adx": 32, "hard_stop": True}},
            {"type": "rsi_range",  "params": {"min": 48, "max": 65, "invert": True}},
        ], 3),

    # ── EMA slope only (no explicit cross check) + RSI + ADX ───────────────
    # Tests whether slope is better signal than cross for this timeframe.
    "T_slope_rsi_adx": (
        [
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.005, "hard_stop": True}},
            {"type": "rsi_range",      "params": {"min": 47, "max": 65, "invert": True}},
            {"type": "adx_regime",     "params": {"min_adx": 15, "max_adx": 30}},
        ], 3),

    # ── EMA cross + RSI not in danger zone + BB position ───────────────────
    # BB upper pct_b < 0.75: confirms price hasn't already surged to top of band.
    "T_cross_rsi_bb": (
        [
            {"type": "ema_cross",      "params": {}, "hard_stop": True},
            {"type": "rsi_overbought", "params": {"min_value": 63, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.75}},
        ], 3),

    # ── EMA cross + RSI overbought gate + slope ─────────────────────────────
    # Loose version: just need cross + slope + not overbought (catches more setups)
    "T_cross_slope_loose": (
        [
            {"type": "ema_cross",      "params": {}, "hard_stop": True},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.003}},
            {"type": "rsi_overbought", "params": {"min_value": 66, "hard_stop": True}},
        ], 2),

    # ── RSI in genuine bull zone [48-64] with EMA20>EMA50 ──────────────────
    # Tighter RSI zone is key diagnostic from trade data.
    # The failing trades had 4hr RSI 43-55 — this template requires RSI > 48.
    "T_rsi_bull_cross": (
        [
            {"type": "rsi_range",  "params": {"min": 48, "max": 64, "invert": True, "hard_stop": True}},
            {"type": "ema_cross",  "params": {}, "hard_stop": True},
        ], 2),

    # ── Full bullish stack: cross + slope + ADX + RSI range ─────────────────
    "T_full_bullish": (
        [
            {"type": "ema_cross",  "params": {}, "hard_stop": True},
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.005}},
            {"type": "adx_regime", "params": {"min_adx": 18, "max_adx": 32}},
            {"type": "rsi_range",  "params": {"min": 48, "max": 65, "invert": True}},
        ], 3),

    # ── EMA cross + price above EMA50 (soft) + RSI gate ────────────────────
    # Tests: price must be above EMA50 (confirms bull phase, not just crossed).
    "T_cross_price_above50": (
        [
            {"type": "ema_cross",               "params": {}, "hard_stop": True},
            {"type": "price_extended_above_ema", "params": {"ema": 50, "min_gap_pct": -0.5, "max_gap_pct": 5.0}},
            {"type": "rsi_overbought",           "params": {"min_value": 64, "hard_stop": True}},
        ], 3),

    # ── ADX-first: Only enter when trend has real momentum behind it ─────────
    # The biggest failure pattern: ADX 14-22 (very low) → no real trend = whipsaw.
    # This template makes ADX the primary hard gate.
    "T_adx_primary": (
        [
            {"type": "adx_regime", "params": {"min_adx": 20, "max_adx": 35, "hard_stop": True}},
            {"type": "ema_cross",  "params": {}, "hard_stop": True},
            {"type": "rsi_range",  "params": {"min": 45, "max": 65, "invert": True}},
        ], 3),

    # ── RSI reversal momentum on 4hr (recovering from a dip in the trend) ──
    # Looks for a 4hr RSI that was recently oversold but is now recovering.
    # This is the p3_base style — targets the "trend recovering from pullback" moment.
    "T_rsi_recovery": (
        [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6,
                "oversold_threshold": 40,
                "current_min": 36,
                "min_jump": 2.5,
                "require_sustained": False,
                "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 60, "hard_stop": True}},
        ], 2),

    # ── RSI recovery + EMA cross confirmation ──────────────────────────────
    "T_rsi_recovery_cross": (
        [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6,
                "oversold_threshold": 42,
                "current_min": 38,
                "min_jump": 2.0,
                "require_sustained": False,
                "hard_stop": True,
            }},
            {"type": "ema_cross",      "params": {}, "hard_stop": True},
            {"type": "rsi_overbought", "params": {"min_value": 60, "hard_stop": True}},
        ], 3),

    # ── Price band + ADX + RSI (no explicit cross check) ───────────────────
    # Tests whether explicit EMA cross is needed if RSI + price band + ADX agree.
    "T_band_adx_rsi": (
        [
            {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": -3.0, "max_gap_pct": 4.0}},
            {"type": "adx_regime",   "params": {"min_adx": 20, "max_adx": 32}},
            {"type": "rsi_range",    "params": {"min": 48, "max": 64, "invert": True}},
        ], 3),
}

# ---------------------------------------------------------------------------
# ENTRY TEMPLATES  (1hr / 60m)
# ────────────────────────────────────────────────────────────────────────────
# Goal: confirm a GENUINE PULLBACK in the 1hr timeframe.
# Current v19 problem: enters when 1hr RSI is 42-52 — not genuinely cooling.
# We want RSI to have pulled back meaningfully (35-50) AND price near/below EMA.
# ---------------------------------------------------------------------------

ENTRY_TEMPLATES = {

    # ── V19 baseline (what's running now) ───────────────────────────────────
    "E_v19_baseline": (
        [
            {"type": "rsi_range",      "params": {"min": 35, "max": 52, "invert": True, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.1, "max_pct_b": 0.58}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -4.0, "max_gap_pct": 2.5}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0, "hard_stop": True}},
        ], 3),

    # ── Tighter RSI ceiling (45 max) — real cooling required ───────────────
    # v19 allows up to RSI 52 — that's barely "cooling". This forces genuine dip.
    "E_rsi_tight_bb": (
        [
            {"type": "rsi_range",      "params": {"min": 30, "max": 48, "invert": True, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.55}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -4.0, "max_gap_pct": 1.5}},
        ], 3),

    # ── RSI range + price below EMA20 (hard pullback to value) ─────────────
    # Requires price to be below or at EMA20: confirmed dip, not just "near top".
    "E_rsi_below_ema": (
        [
            {"type": "rsi_range",    "params": {"min": 30, "max": 50, "invert": True, "hard_stop": True}},
            {"type": "price_vs_ema", "params": {"ema": 20, "min_gap_pct": -4.0, "max_gap_pct": 0.5}},
            {"type": "volume_spike", "params": {"min_ratio": 0.8, "max_ratio": 8.0}},
        ], 3),

    # ── RSI range + BB lower half + price near EMA20 ────────────────────────
    # BB lower 50% confirms price has retraced to bottom of recent range.
    "E_rsi_bb_lower": (
        [
            {"type": "rsi_range",      "params": {"min": 28, "max": 50, "invert": True, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.1, "max_pct_b": 0.50}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 1.0}},
        ], 3),

    # ── RSI overbought ceiling + BB + EMA (loose lower bound) ───────────────
    # Uses rsi_overbought as a simpler ceiling (not range), paired with BB.
    "E_rsob_bb_ema": (
        [
            {"type": "rsi_overbought", "params": {"min_value": 52, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.60}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -4.5, "max_gap_pct": 2.0}},
            {"type": "volume_spike",   "params": {"min_ratio": 0.8, "max_ratio": 8.0}},
        ], 3),

    # ── RSI reversal momentum on 1hr (RSI bottomed and starting up) ─────────
    # Waits for RSI to have formed a bottom and start recovering from the pullback.
    # More precise entry timing — catches the turn, not the fall.
    "E_rsi_turn_bb": (
        [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 5,
                "oversold_threshold": 45,
                "current_min": 30,
                "min_jump": 3.0,
                "require_sustained": True,
                "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.60}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 2.0}},
        ], 3),

    # ── RSI reversal momentum (loose) + RSI ceiling ─────────────────────────
    "E_rsi_turn_loose": (
        [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6,
                "oversold_threshold": 50,
                "current_min": 28,
                "min_jump": 2.5,
                "require_sustained": False,
                "hard_stop": True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 55, "hard_stop": True}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 2.0}},
        ], 3),

    # ── Reversal candle + RSI range (hammer or higher low at support) ────────
    # Candle confirmation makes this more precise at the cost of fewer signals.
    "E_candle_rsi_bb": (
        [
            {"type": "reversal_candle","params": {"pattern": "hammer", "min_body_pct": 0.07}},
            {"type": "rsi_range",      "params": {"min": 28, "max": 52, "invert": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.60}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 2.0}},
        ], 3),

    # ── Higher-low candle + RSI range (structural pullback bottom) ───────────
    "E_higher_low_rsi": (
        [
            {"type": "reversal_candle","params": {"pattern": "higher_low"}},
            {"type": "rsi_range",      "params": {"min": 30, "max": 52, "invert": True, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.65}},
        ], 3),

    # ── RSI range + EMA slope flat/rising (trend intact at entry TF) ─────────
    # 1hr EMA20 slope softly rising: the pullback hasn't broken the uptrend.
    "E_rsi_slope_check": (
        [
            {"type": "rsi_range",  "params": {"min": 30, "max": 50, "invert": True, "hard_stop": True}},
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.01}},
            {"type": "price_vs_ema","params": {"ema": 20, "min_gap_pct": -4.0, "max_gap_pct": 1.5}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.60}},
        ], 3),

    # ── Strict: RSI < 46, price ≤ EMA20+0.5%, BB lower half (all 3 agree) ──
    "E_strict_triple": (
        [
            {"type": "rsi_range",      "params": {"min": 28, "max": 46, "invert": True, "hard_stop": True}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -4.5, "max_gap_pct": 0.5}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.50}},
        ], 3),

    # ── Permissive: just RSI ceiling + BB band (looser than v19) ────────────
    # Tests: is it the TP/SL that matters more than filters?
    "E_permissive": (
        [
            {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.70}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 3.0}},
        ], 2),

    # ── ADX regime on 1hr (low ADX = trending or chop? test both sides) ─────
    # This profile suffers in low-ADX 4hr environments. Check if 1hr ADX helps.
    "E_adx_rsi_bb": (
        [
            {"type": "adx_regime",     "params": {"min_adx": 12, "max_adx": 28}},
            {"type": "rsi_range",      "params": {"min": 30, "max": 52, "invert": True, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.60}},
        ], 3),

    # ── Volume confirmation + RSI range (capitulation-then-dip) ─────────────
    # Higher volume on the pullback candle suggests selling exhaustion.
    "E_vol_rsi_bb": (
        [
            {"type": "volume_spike",   "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
            {"type": "rsi_range",      "params": {"min": 28, "max": 50, "invert": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.60}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 2.0}},
        ], 3),
}

# ---------------------------------------------------------------------------
# Variant generation
# ---------------------------------------------------------------------------

def build_variants_from_templates(mode: str = "tight") -> Dict[str, dict]:
    """Cross every trend template × every entry template."""
    tp_sl = TP_SL_TIGHT if mode == "tight" else TP_SL_SWING
    tp, sl, trl, arm, use_trl = tp_sl[0]  # baseline TP/SL for template cross

    variants = {}
    for t_name, (t_inds, t_min) in TREND_TEMPLATES.items():
        for e_name, (e_inds, e_min) in ENTRY_TEMPLATES.items():
            name = f"{t_name}__{e_name}"
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


def _mutate_indicator(ind: dict, rng: random.Random) -> dict:
    """Return a mutated copy of a single 4hr-swing indicator config."""
    ind = copy.deepcopy(ind)
    p = ind["params"]
    itype = ind["type"]

    if itype == "ema_cross":
        # Nothing meaningful to mutate on ema_cross itself — toggle hard_stop
        ind["hard_stop"] = rng.choice([True, True, False])

    elif itype == "ema_slope":
        p["min_slope_pct"] = rng.choice([0.002, 0.003, 0.005, 0.008, 0.010, 0.015])
        p["hard_stop"] = rng.choice([True, True, False])

    elif itype == "adx_regime":
        p["min_adx"] = rng.choice([14, 16, 18, 20, 22, 25])
        p["max_adx"] = rng.choice([26, 28, 30, 32, 35, 40])
        if p["max_adx"] <= p["min_adx"]:
            p["max_adx"] = p["min_adx"] + 10
        p["hard_stop"] = rng.choice([True, False, False])

    elif itype == "rsi_range":
        # For trend (4hr): want RSI in bullish zone 47-65
        # For entry (1hr): want RSI in pullback zone 28-52
        # Mutate around the current values
        cur_min = p.get("min", 40)
        cur_max = p.get("max", 60)
        if cur_max >= 55:  # trend template style
            p["min"] = rng.choice([45, 47, 48, 50, 52])
            p["max"] = rng.choice([60, 62, 63, 65, 67])
        else:  # entry template style
            p["min"] = rng.choice([25, 28, 30, 32, 35])
            p["max"] = rng.choice([44, 46, 48, 50, 52, 54])
        p["invert"] = True  # always want RSI IN the range
        p["hard_stop"] = rng.choice([True, True, False])

    elif itype == "rsi_overbought":
        # For trend: higher ceiling (60-70)
        # For entry: lower ceiling (48-58)
        cur = p.get("min_value", 63)
        if cur >= 58:
            p["min_value"] = rng.choice([60, 62, 63, 65, 67, 70])
        else:
            p["min_value"] = rng.choice([48, 50, 52, 54, 56, 58])
        p["hard_stop"] = True

    elif itype == "bollinger_bands" and p.get("mode") == "pct_b":
        band = p.get("band", "upper")
        if band == "upper":
            p["min_pct_b"] = rng.choice([0.0, 0.05, 0.1])
            p["max_pct_b"] = rng.choice([0.45, 0.50, 0.55, 0.60, 0.65, 0.70])
        else:  # lower
            p["min_pct_b"] = rng.choice([-0.1, -0.05, 0.0])
            p["max_pct_b"] = rng.choice([0.35, 0.40, 0.45, 0.50])

    elif itype == "price_vs_ema":
        ema = p.get("ema", 20)
        if ema == 50:  # trend-level check
            p["min_gap_pct"] = rng.choice([-4.0, -3.0, -2.5, -2.0])
            p["max_gap_pct"] = rng.choice([2.0, 3.0, 4.0, 5.0])
        else:  # entry-level check (EMA20)
            p["min_gap_pct"] = rng.choice([-5.0, -4.0, -3.0, -2.5])
            p["max_gap_pct"] = rng.choice([-0.5, 0.0, 0.5, 1.0, 1.5, 2.0])

    elif itype == "price_extended_above_ema":
        p["min_gap_pct"] = rng.choice([-1.0, -0.5, 0.0, 0.5])
        p["max_gap_pct"] = rng.choice([3.0, 4.0, 5.0, 6.0])

    elif itype == "volume_spike":
        p["min_ratio"] = rng.choice([0.8, 1.0, 1.2, 1.5])
        p["max_ratio"] = 8.0
        p["hard_stop"] = rng.choice([True, False, False])

    elif itype == "rsi_reversal_momentum":
        p["lookback_candles"]   = rng.choice([4, 5, 6, 8])
        p["oversold_threshold"] = rng.choice([38, 40, 42, 45, 48])
        p["current_min"]        = rng.choice([28, 30, 32, 35, 38])
        p["min_jump"]           = rng.choice([2.0, 2.5, 3.0, 4.0])
        p["require_sustained"]  = rng.choice([True, False, False])
        p["hard_stop"]          = True

    elif itype == "reversal_candle":
        p["pattern"] = rng.choice(["hammer", "hammer", "higher_low", "bull_close"])
        if p["pattern"] == "hammer":
            p["min_body_pct"] = rng.choice([0.06, 0.07, 0.08, 0.10])

    ind["params"] = {k: v for k, v in p.items() if v is not None}
    return ind


def generate_variants_random(n: int = 100, seed: int = None, mode: str = "tight") -> Dict[str, dict]:
    """Random mutation generator for swing profiles."""
    rng = random.Random(seed)
    variants = {}
    t_names = list(TREND_TEMPLATES.keys())
    e_names = list(ENTRY_TEMPLATES.keys())
    tp_sl = TP_SL_TIGHT if mode == "tight" else TP_SL_SWING

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

        t_min_var = max(1, min(t_min + rng.choice([-1, 0, 0, 1]), len(t_inds)))
        e_min_var = max(2, min(e_min + rng.choice([-1, 0, 0, 1]), len(e_inds)))

        tp, sl, trl, arm, use_trl = rng.choice(tp_sl)
        tp_tag = f"tp{int(tp*10)}sl{int(sl*10)}{'trl' if use_trl else 'fix'}"
        name = f"rand_{t_name[:12]}_{e_name[:12]}_{tp_tag}_s{seed or 0}_{attempts}"

        variants[name] = {
            **BASE_SETTINGS,
            "take_profit_pct":               tp,
            "stop_loss_pct":                 sl,
            "trailing_stop_pct":             trl,
            "arm_trailing_stop_pct":         arm,
            "use_trailing_stop":             use_trl,
            "trend_indicators":              t_inds,
            "min_indicators_required":       t_min_var,
            "entry_indicators":              e_inds,
            "min_entry_indicators_required": e_min_var,
        }

    return variants


def generate_variants_focused(top_results: list, n_per_winner: int = 8,
                              mode: str = "tight") -> Dict[str, dict]:
    """Focused mutations around prior top results."""
    variants = {}
    rng = random.Random(42)
    tp_sl = TP_SL_TIGHT if mode == "tight" else TP_SL_SWING

    for r in top_results:
        cfg    = r.get("config", {})
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

            name = f"foc_{base[:28]}_{action}_{attempt}"
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

        # TP/SL sweep on each winner's indicator combo
        for tp, sl, trl, arm, use_trl in tp_sl:
            tp_tag = f"tp{int(tp*10)}sl{int(sl*10)}{'trl' if use_trl else 'fix'}"
            name = f"foc_{base[:35]}_{tp_tag}"
            if name not in variants:
                variants[name] = {
                    **BASE_SETTINGS,
                    "take_profit_pct":               tp,
                    "stop_loss_pct":                 sl,
                    "trailing_stop_pct":             trl,
                    "arm_trailing_stop_pct":         arm,
                    "use_trailing_stop":             use_trl,
                    "trend_indicators":              t_inds,
                    "min_indicators_required":       t_min,
                    "entry_indicators":              e_inds,
                    "min_entry_indicators_required": e_min,
                }

    return variants


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_merged(trades: float, win_rate: float, total_pnl: float,
                 profit_factor: float, avg_pnl: float = 0.0) -> float:
    if trades < MIN_TRADES:
        return -999.0
    pf  = min(profit_factor, 6.0)
    wr  = win_rate
    pnl = min(total_pnl, 40.0)
    # avg_pnl matters most: positive avg_pnl is the primary objective
    return avg_pnl * 200 + pf * 0.35 + wr * 100 * 0.30 + pnl * 0.08


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
                f"| best: {best['name'][:50]} "
                f"sc={best['score']:.1f} t={best['trades']} "
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

    print(f"\n{'='*110}")
    print(f"  {title}")
    print(f"  {len(qualifying)} qualifying (≥{MIN_TRADES} trades) / {len(results)} total")
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
    print(f'\n    "{r["name"][:65]}": {{')
    print(f'        # Score={r["score"]:.2f} | Trades={r["trades"]} '
          f'| WR={r["win_rate"]:.0%} | PF={r["profit_factor"]:.2f}x | PnL={r["total_pnl"]:+.1f}%')
    for k in ["take_profit_pct", "stop_loss_pct", "trailing_stop_pct", "arm_trailing_stop_pct",
              "use_trailing_stop", "min_signal_confidence", "max_position_hours"]:
        if k in cfg:
            print(f'        "{k}": {cfg[k]},')
    print(f'        "trend_indicators": {json.dumps(cfg.get("trend_indicators", []), indent=8)},')
    print(f'        "min_indicators_required": {cfg.get("min_indicators_required", 2)},')
    print(f'        "entry_indicators": {json.dumps(cfg.get("entry_indicators", []), indent=8)},')
    print(f'        "min_entry_indicators_required": {cfg.get("min_entry_indicators_required", 3)},')
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
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="4hr/1hr swing indicator combination search")
    parser.add_argument("--iteration", type=int, default=None)
    parser.add_argument("--top-carry", type=int, default=8)
    parser.add_argument("--days",      type=int, default=SCAN_DAYS)
    parser.add_argument("--rand-n",    type=int, default=80)
    parser.add_argument("--mode",      default="tight", choices=["tight", "swing"],
                        help="tight=TP1.5/SL1.0, swing=TP3/SL2")
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
    print(f"\n{'#'*78}")
    print(f"  4HR/1HR SWING INDICATOR SEARCH — Iteration {iteration}  [{args.mode.upper()} mode]")
    print(f"  Window   : {start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')} ({args.days}d)")
    print(f"  Symbols  : {SYMBOLS}")
    print(f"  Templates: {n_trend} trend × {n_entry} entry = {n_trend*n_entry} base combos")
    print(f"  Timeframes: trend=240m, entry=60m")
    print(f"{'#'*78}\n")

    if iteration == 1:
        print("[Gen] Strategy: template cross-product (broad exploration)\n")
        variants = build_variants_from_templates(mode=args.mode)

    elif iteration == 2:
        print(f"[Gen] Strategy: random mutations ({args.rand_n} variants)\n")
        variants = generate_variants_random(n=args.rand_n, seed=iteration, mode=args.mode)

    else:
        prev_results = load_results()
        qualifying = sorted(
            [r for r in prev_results if r["score"] > -100],
            key=lambda x: x["score"], reverse=True
        )[:args.top_carry]

        if qualifying:
            print(f"[Gen] Strategy: focused mutations on top-{len(qualifying)} prior winners\n")
            variants = generate_variants_focused(qualifying, n_per_winner=10, mode=args.mode)
        else:
            print("[Gen] No qualifying prior results — random mutations\n")
            variants = generate_variants_random(n=args.rand_n, seed=iteration * 17, mode=args.mode)

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

    print_ranking(this_run,   f"THIS ITERATION ({iteration}) [{args.mode.upper()}] RESULTS",    top_n=20)
    ranked_all = print_ranking(all_results, f"ALL-TIME TOP [{args.mode.upper()}] (after iter {iteration})", top_n=30)

    qualifying_all = [r for r in ranked_all if r["score"] > -100]
    if qualifying_all:
        print(f"\n{'='*78}")
        print(f"  TOP-5 PASTE-READY ENTRIES")
        print(f"{'='*78}")
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
        print(f"\n[State]   → {STATE_FILE}")
        print(f"[Results] → {RESULTS_FILE}")

    print(f"\n[Done] Iteration {iteration} [{args.mode}].")
    qual_this = len([r for r in this_run if r["score"] > -100])
    print(f"  This run : {qual_this}/{len(this_run)} qualifying")
    print(f"  All-time : {len(qualifying_all)}/{len(all_results)} qualifying")
    if qualifying_all:
        b = qualifying_all[0]
        print(f"  Best: score={b['score']:.2f} t={b['trades']} "
              f"wr={b['win_rate']:.0%} pf={b['profit_factor']:.2f}x pnl={b['total_pnl']:+.1f}%")
        print(f"    {b['name']}")


if __name__ == "__main__":
    main()
