
# =============================================================================
# RANGE TRADING VARIANTS  (based on 15m_MB profile)
# Fixes weakness: HTF trend gate was too permissive, vwap check was skippable
# =============================================================================

# Baseline — your current live config (reproduced for comparison)
_RANGE_BASE = {
    "display_name": "range_trading",
    "strategy_type": "range_trading",
    "trend_timeframe": "60",
    "entry_timeframe": "15",
    "take_profit_pct": 0.6,
    "stop_loss_pct": 0.52,
    "trailing_stop_pct": 0.3,
    "arm_trailing_stop_pct": 0.25,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 10,
    "min_signal_confidence": 65.0,
    "min_volume_ratio": 0.8,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 4,
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
    # Trend filter (60m)
    "trend_indicators": [
        {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
        {"type": "rsi_range",   "params": {"min": 35, "max": 60, "invert": True,"hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
        {"type": "adx_regime", "params": {"min_adx": 0, "max_adx": 24}},
    ],
    "min_indicators_required": 4,
    # Entry filter (15m)
    "entry_indicators": [
        {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False, "hard_stop": True,}},
        {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
        {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.05, "max_pct_b": 0.45, "hard_stop": True}},
        {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False,"max_drop_from_close_pct": 0.5}},
        {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55,"max_drop_from_close_pct": 0.5}},
        {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.2,"max_drop_from_close_pct": 0.5}},
    ],
    "min_entry_indicators_required": 5,
}

RANGE_VARIANTS = {

    # -------------------------------------------------------------------------
    # BASELINE — current live config (use for comparison)
    # -------------------------------------------------------------------------
    "range_baseline": _RANGE_BASE,
    
    "range_v1_25BB_modTPSL": {
        **_RANGE_BASE,
        "take_profit_pct": 0.6,
        "stop_loss_pct": 0.38,
        "trailing_stop_pct": 0.25,
        "arm_trailing_stop_pct": 0.25,
        # Entry filter (15m)
        "entry_indicators": [
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False, "hard_stop": True,}},
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.25, "max_pct_b": 0.45, "hard_stop": True}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False,"max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55,"max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.2,"max_drop_from_close_pct": 0.5}},
        ],
    },

    "range_v2_25BB": {
        **_RANGE_BASE,
        # Entry filter (15m)
        "entry_indicators": [
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False, "hard_stop": True,}},
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.25, "max_pct_b": 0.45, "hard_stop": True}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False,"max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55,"max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.2,"max_drop_from_close_pct": 0.5}},
        ],
    },

    "range_v3_newbb_Reversal": {
        **_RANGE_BASE,
        "entry_indicators": [
            {"type": "rsi_range",   "params": { "min_rsi": 35, "max_rsi": 62,"invert": True, "hard_stop": True,}},
            {"type": "price_below_vwap","params": {"min_gap_pct": 0.05, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.15, "max_pct_b": 0.45, "hard_stop": True}},
            {"type": "bb_width_regime", "params": {"required_direction": "not_expanding", "lookback": 4,"min_width": 0.02,"hard_stop": True}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False,"max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55,"max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.2,"max_drop_from_close_pct": 0.5}},
        ],
        "min_entry_indicators_required": 5,
    },

    "range_v4_newbb_bbmom": {
        **_RANGE_BASE,
        "entry_indicators": [
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False, "hard_stop": True,}},
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": 0.05, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.15, "max_pct_b": 0.45, "hard_stop": True}},
            {"type": "bb_width_regime", "params": {"required_direction": "not_expanding", "lookback": 4,"min_width": 0.02,"hard_stop": True}},
            {"type": "bb_pct_b_momentum", "params": {"lookback": 3, "required_direction": "not_rising", "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
    },

    "range_v5_newbb_bbmomTrend": {
        **_RANGE_BASE,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
            {"type": "rsi_range",   "params": {"min_rsi": 35, "max_rsi": 60, "invert": True,}},
            {"type": "bb_width_regime", "params": {"required_direction": "not_expanding", "lookback": 4,"min_width": 0.02,"hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 0, "max_adx": 24}},
        ],
        "min_indicators_required": 5,
        "entry_indicators": [
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False, "hard_stop": True,}},
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": 0.05, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.15, "max_pct_b": 0.45, "hard_stop": True}},
            {"type": "bb_width_regime", "params": {"required_direction": "not_expanding", "lookback": 4,"min_width": 0.02,"hard_stop": True}},
            {"type": "bb_pct_b_momentum", "params": {"lookback": 3, "required_direction": "not_rising", "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
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
#         "signal_cooldown_minutes": 10,
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
