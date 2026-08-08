"""
backtesting/profile_samples/dip_buy_exit_tests.py
=================================================
Exit indicator variants for dip_buy profiles (v5 & v7).

Testing the hypothesis that current exits (RSI 55-59) are too early,
exiting when the bounce is just starting to recover. Three test directions:

1. Higher RSI threshold (60, 65) — wait for stronger confirmation
2. Higher EMA20 gap or switch to EMA50 — require more recovery height
3. 1D timeframe for exits — use daily candles instead of 4h

Each variant tests ONE hypothesis on BOTH profiles (v5_rsi_reversal_trail
and v7_deep_dip_satellite), keeping entry logic identical.

Backtesting window: last 14 days (to backfill fresh data), all symbols.
"""

from backtesting.profile_samples.dip_buy_variants import (
    _DIP_BUY_BASE,
    _RSI_REVERSAL_ENTRY,
    _DIST_HIGH_ENTRY,
)

# =============================================================================
# CURRENT BASELINES (from prod_profiles.py) — for reference
# =============================================================================

_DIP_V5_BASE = {
    **_DIP_BUY_BASE,
    "display_name": "dip_v5_rsi_reversal_trail",
    "entry_indicators": _RSI_REVERSAL_ENTRY,
    "min_entry_indicators_required": 2,
    "use_trailing_stop": True,
    "arm_trailing_stop_pct": 3.5,
    "trailing_stop_pct": 0.6,
    "symbols": ['BTC_USDC', 'DOGE_USDC', 'ETH_USDC', 'SEI_USDC', 'SOL_USDC', 'SUI_USDC', 'XRP_USDC', 'ZEC_USDC'],
}

_DIP_V7_BASE = {
    **_DIP_BUY_BASE,
    "display_name": "dip_v7_deep_dip_satellite",
    "entry_indicators": [
        {"type": "distance_from_high", "params": {"lookback_bars": 18, "min_pct_below": 12.0, "max_pct_below": 30.0, "hard_stop": True}},
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
    ],
    "min_entry_indicators_required": 2,
    "use_trailing_stop": True,
    "arm_trailing_stop_pct": 3.5,
    "trailing_stop_pct": 0.6,
    "symbols": ['BTC_USDC', 'ETH_USDC', 'SEI_USDC', 'SOL_USDC', 'SUI_USDC', 'XRP_USDC', 'ZEC_USDC'],
}

DIP_BUY_EXIT_TESTS = {
    # =========================================================================
    # BASELINE CONTROLS (current prod configs)
    # =========================================================================

    "exit_baseline_v5": {
        **_DIP_V5_BASE,
        "display_name": "exit_baseline_v5",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
        ],
        "min_exit_indicators_required": 1,
    },

    "exit_baseline_v7": {
        **_DIP_V7_BASE,
        "display_name": "exit_baseline_v7",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 59}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
        ],
        "min_exit_indicators_required": 1,
    },

    # =========================================================================
    # HYPOTHESIS 1: HIGHER RSI THRESHOLD (wait for stronger bounce confirmation)
    # =========================================================================

    "exit_rsi60_v5": {
        **_DIP_V5_BASE,
        "display_name": "exit_rsi60_v5",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 60}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
        ],
        "min_exit_indicators_required": 1,
    },

    "exit_rsi60_v7": {
        **_DIP_V7_BASE,
        "display_name": "exit_rsi60_v7",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 60}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
        ],
        "min_exit_indicators_required": 1,
    },

    "exit_rsi65_v5": {
        **_DIP_V5_BASE,
        "display_name": "exit_rsi65_v5",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 65}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
        ],
        "min_exit_indicators_required": 1,
    },

    "exit_rsi65_v7": {
        **_DIP_V7_BASE,
        "display_name": "exit_rsi65_v7",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 65}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
        ],
        "min_exit_indicators_required": 1,
    },

    # =========================================================================
    # HYPOTHESIS 2A: HIGHER EMA20 ALLOWANCE (require more height recovery)
    # =========================================================================

    "exit_ema20_higher_v5": {
        **_DIP_V5_BASE,
        "display_name": "exit_ema20_higher_v5",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": 0.005, "max_gap_pct": 99}},
        ],
        "min_exit_indicators_required": 1,
    },

    "exit_ema20_higher_v7": {
        **_DIP_V7_BASE,
        "display_name": "exit_ema20_higher_v7",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 59}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": 0.005, "max_gap_pct": 99}},
        ],
        "min_exit_indicators_required": 1,
    },

    # =========================================================================
    # HYPOTHESIS 2B: SWITCH TO EMA50 (higher, more stable level)
    # =========================================================================

    "exit_ema50_v5": {
        **_DIP_V5_BASE,
        "display_name": "exit_ema50_v5",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": 0.0, "max_gap_pct": 99}},
        ],
        "min_exit_indicators_required": 1,
    },

    "exit_ema50_v7": {
        **_DIP_V7_BASE,
        "display_name": "exit_ema50_v7",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 59}},
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": 0.0, "max_gap_pct": 99}},
        ],
        "min_exit_indicators_required": 1,
    },

    # =========================================================================
    # HYPOTHESIS 3: SWITCH TO 1D TIMEFRAME FOR EXITS (use daily close logic)
    # Change exit_timeframe to "1D" so exit indicators evaluate on daily bars
    # =========================================================================

    "exit_1d_v5": {
        **_DIP_V5_BASE,
        "display_name": "exit_1d_v5",
        "exit_timeframe": "1D",  # Changed from "240" (4h)
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
        ],
        "min_exit_indicators_required": 1,
    },

    "exit_1d_v7": {
        **_DIP_V7_BASE,
        "display_name": "exit_1d_v7",
        "exit_timeframe": "1D",  # Changed from "240" (4h)
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 59}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
        ],
        "min_exit_indicators_required": 1,
    },

    # =========================================================================
    # COMBINED: RSI65 + EMA50 (more conservative dual hypothesis)
    # =========================================================================

    "exit_combined_v5": {
        **_DIP_V5_BASE,
        "display_name": "exit_combined_v5",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 65}},
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": 0.0, "max_gap_pct": 99}},
        ],
        "min_exit_indicators_required": 1,
    },

    "exit_combined_v7": {
        **_DIP_V7_BASE,
        "display_name": "exit_combined_v7",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 65}},
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": 0.0, "max_gap_pct": 99}},
        ],
        "min_exit_indicators_required": 1,
    },
}
