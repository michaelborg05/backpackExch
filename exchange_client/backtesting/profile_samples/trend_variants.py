

_TF_BASE = {
    "strategy_type": "trend_following",
    "entry_timeframe": "15",
    "take_profit_pct": 0.8,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 15,
    "min_signal_confidence": 70.0,
    "min_volume_ratio": 1.1,
    "use_trend_filter": True,
    "trend_timeframe": "60",
    "use_entry_filter": True,
    "max_position_hours": 12,
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
    "trend_indicators": [
        {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015,"hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95}},
        {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
        {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
    ],
    "min_indicators_required": 3,
    "entry_indicators": [
        {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
        {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.65}},
        {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 57,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
        {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
        {"type": "price_vs_vwap",   "params": {}},
        {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02,"max_slope_pct":0.25,"hard_stop": True}},
    ],
    "min_entry_indicators_required": 6,

}

TREND_VARIANTS = {

    # -------------------------------------------------------------------------
    # BASELINES — faithful reproductions of live profiles for comparison
    # -------------------------------------------------------------------------
    "tf_base_15m_trend": {
        **_TF_BASE,
    },

    "tf_v1_TSL": {
        **_TF_BASE,
        "trailing_stop_pct": 0.2,
        "arm_trailing_stop_pct": 0.45,
    },

    "tf_v2_RSIMomentum": {
        **_TF_BASE,
        "trend_indicators": [
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
    },

    "tf_v3_BBchange": {
        **_TF_BASE,
        "entry_indicators": [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.55,"hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 57,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02,"max_slope_pct":0.25,"hard_stop": True}},
            {"type": "rsi_momentum", "params": {"min_momentum": 0.5, "max_momentum": 3.0}},
        ],
        "min_entry_indicators_required": 7,

    },

    "tf_v3_BB_rsi": {
        **_TF_BASE,
        "entry_indicators": [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.55,"hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 57,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "rsi_momentum", "params": {"min_momentum": 0.5, "max_momentum": 3.0}},
        ],
        "min_entry_indicators_required": 6,

    },


    "tf_v4_TSL_mom_bb": {
        **_TF_BASE,
        "trailing_stop_pct": 0.2,
        "arm_trailing_stop_pct": 0.45,
        "trend_indicators": [
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
        "entry_indicators": [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.55,"hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 57,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02,"max_slope_pct":0.25,"hard_stop": True}},
            {"type": "rsi_momentum", "params": {"min_momentum": 0.5, "max_momentum": 3.0}},
        ],
        "min_entry_indicators_required": 7,

    },

    "tf_v5_15m_trend_adxhard": {
        **_TF_BASE,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015,"hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
    },

}




