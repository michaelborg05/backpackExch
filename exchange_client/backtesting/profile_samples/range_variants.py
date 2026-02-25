
# =============================================================================
# RANGE TRADING VARIANTS  (based on 15m_MB profile)
# Fixes weakness: HTF trend gate was too permissive, vwap check was skippable
# =============================================================================

# Baseline — your current live config (reproduced for comparison)
_RANGE_BASE = {
    "display_name": "range_trading",
    "strategy_type": "range_trading",
    "signal_timeframe": "15",
    "trend_timeframe": "60",
    "entry_timeframe": "15",
    "take_profit_pct": 0.5,
    "stop_loss_pct": 0.45,
    "trailing_stop_pct": 0.3,
    "arm_trailing_stop_pct": 0.25,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 600,
    "min_signal_confidence": 65.0,
    "min_volume_ratio": 0.8,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 4,
    "use_market_regime_filter": False,
    # Trend filter (60m)
    "trend_indicators": [
        {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
        {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 40, "use_momentum": False}},
        {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
    ],
    "min_indicators_required": 3,
    # Entry filter (15m)
    "entry_indicators": [
        {"type": "rsi_oversold",    "params": {"max_value": 48, "require_rising": True, "min_momentum": 1, "hard_stop": True}},
        {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.30}},
        {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 4.0}},
        {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
        {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
    ],
    "min_entry_indicators_required": 4,
}

RANGE_VARIANTS = {

    # -------------------------------------------------------------------------
    # BASELINE — current live config (use for comparison)
    # -------------------------------------------------------------------------
    "range_baseline": _RANGE_BASE,

    # -------------------------------------------------------------------------
    # V1: Stronger HTF gate — fix the SOL downtrend problem
    # Change: 60m RSI minimum raised from 40→45, AND make it a hard_stop.
    # Rationale: SOL 60m RSI was 33.2 when trade fired. A hard_stop at 45
    # would have killed this trade outright. Slightly stricter but ranges
    # only form in neutral-to-mild trending markets.
    # -------------------------------------------------------------------------
    "range_v1_htf_rsi_hardstop": {
        **_RANGE_BASE,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 45, "use_momentum": False, "hard_stop": True}},  # raised+hardstop
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
    },

    # -------------------------------------------------------------------------
    # V2: Add 60m BB position gate — block when 60m is already near lower band
    # Rationale: SOL 60m pct_b=0.12 — price was near the LOWER band of the HTF.
    # That means the HTF is in a downswing. For range trading you want to see
    # HTF in the MID band (0.25–0.75), not hugging the lower band.
    # -------------------------------------------------------------------------
    "range_v2_htf_bb_midrange": {
        **_RANGE_BASE,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 40, "use_momentum": False}},
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
            # NEW: block if HTF is near its own lower band (downtrend on HTF)
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20, "hard_stop": True}},
        ],
        "min_indicators_required": 3,  # still 3/5, but the new BB lower hard_stop blocks downtrends
    },

    # -------------------------------------------------------------------------
    # V3: Make vwap a hard_stop — SOL was actually ABOVE vwap when it fired
    # Rationale: price_below_vwap was one of the indicators that FAILED, but
    # since only 4/6 were needed, the trade still fired. Making it a hard_stop
    # means range entries MUST be below vwap (which is the whole point of a
    # range dip buy).
    # -------------------------------------------------------------------------
    "range_v3_vwap_hardstop": {
        **_RANGE_BASE,
        "entry_indicators": [
            {"type": "rsi_oversold",    "params": {"max_value": 48, "require_rising": True, "min_momentum": 1, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},  # NOW HARD STOP
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.30}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 4.0}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V4: Tighter BB lower requirement — only trade at TRUE range lows
    # Rationale: SOL pct_b was 0.13 — just inside the 0.30 threshold.
    # Tightening to 0.20 means we only enter when price is in the bottom 20%
    # of the band — a more convincing range-low signal.
    # -------------------------------------------------------------------------
    "range_v4_tighter_bb": {
        **_RANGE_BASE,
        "entry_indicators": [
            {"type": "rsi_oversold",    "params": {"max_value": 48, "require_rising": True, "min_momentum": 1, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20}},  # tightened 0.30→0.20
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 4.0}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V5: Add EMA proximity gate — block if EMA20 is too far above price
    # Rationale: SOL EMA20 was 83.15 vs price 82.77 = 0.46% above. That's
    # fine for range. But the 60m EMA20 was 83.93 — 1.4% above. We check
    # on 15m: if the fast EMA is significantly above price, we're in a
    # downmove not a range.
    # "max_gap_pct: 1.0" means block if price is >1% below EMA20 (falling knife)
    # -------------------------------------------------------------------------
    "range_v5_ema_proximity": {
        **_RANGE_BASE,
        "entry_indicators": [
            {"type": "rsi_oversold",    "params": {"max_value": 48, "require_rising": True, "min_momentum": 1, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.30}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 4.0}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
            # NEW: price must not be more than 1% below EMA20 (blocks falling knife entries)
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.0, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V6: Kitchen sink — all of V1+V3+V4 combined (strictest)
    # Use to find the upper bound of precision (may have very few signals)
    # -------------------------------------------------------------------------
    "range_v6_strict": {
        **_RANGE_BASE,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 45, "use_momentum": False, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_oversold",    "params": {"max_value": 48, "require_rising": True, "min_momentum": 1, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.2, "max_ratio": 4.0}},  # slightly higher volume threshold
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.0, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 68.0,
    },

    # -------------------------------------------------------------------------
    # V7: Relax entry — lower bar to catch more dips (opposite direction test)
    # Lower pct_b threshold and RSI threshold to see if we get MORE trades
    # (with likely lower win rate — useful to understand the trade-off curve)
    # -------------------------------------------------------------------------
    "range_v7_loose": {
        **_RANGE_BASE,
        "entry_indicators": [
            {"type": "rsi_oversold",    "params": {"max_value": 52, "require_rising": True, "min_momentum": 0.5, "hard_stop": True}},  # looser RSI
            {"type": "price_below_vwap","params": {"min_gap_pct": 0.0, "max_gap_pct": -3.0}},   # allows at/near vwap
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.45}},  # wider
            {"type": "volume_spike",    "params": {"min_ratio": 0.8, "max_ratio": 5.0}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.35}},
            {"type": "rsi_overbought",  "params": {"min_value": 60, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,  # only need 3/6
        "min_signal_confidence": 60.0,
    },
}

# RANGE_VARIANTS = {
#     "range_v2_htf_bb_midrange": {
#         **_RANGE_BASE,
#         "take_profit_pct": 0.5,
#         "stop_loss_pct": 0.45,
#         "trailing_stop_pct": 0.3,
#         "arm_trailing_stop_pct": 0.25,
#         "use_trailing_stop": True,
#         "signal_cooldown_seconds": 600,
#         "min_signal_confidence": 65.0,
#         "min_volume_ratio": 0.8,
#         "use_trend_filter": False,
#         "trend_indicators": [
#             {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
#             {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 40, "use_momentum": False}},
#             {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
#             {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
#             # NEW: block if HTF is near its own lower band (downtrend on HTF)
#             {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20, "hard_stop": True}},
#         ],
#         "min_indicators_required": 3,  # still 3/5, but the new BB lower hard_stop blocks downtrends
#     }
# }
