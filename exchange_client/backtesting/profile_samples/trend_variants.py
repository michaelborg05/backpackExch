

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
    "trend_indicators": [
        {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.001,"hard_stop": True}},
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
    "tf_baseline_default": {
        **_TF_BASE,
    },
    "tf_baseline_default_adjustedTSL": {
        **_TF_BASE,
        "take_profit_pct": 0.8,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.5,
        "arm_trailing_stop_pct": 0.65,
    },

    # -------------------------------------------------------------------------
    # V1: Lower RSI entry — drop from 52 to 44 to catch earlier in recovery
    # In Window A, RSI hit 42.9 at the best entry candle (06:18).
    # The baseline required 52 — meaning it would have missed by 9 points.
    # Dropping to 44 (early_threshold 40) would have caught the 06:33 candle
    # (RSI=44.5) with pct_b=0.99 and price just above EMA.
    # Trade-off: fires in mediocre 40-50 RSI chop too. Backtest required.
    # -------------------------------------------------------------------------
    "tf_v1_ai_profile": {
        **_TF_BASE,
        "take_profit_pct": 0.75,
        "stop_loss_pct": 0.6,
        "trailing_stop_pct": 0.5,
        "arm_trailing_stop_pct": 0.5,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.001,"hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "ema_gap",         "params": {"min_gap_pct": 0.15, "mode": "min"}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 2, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.9, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 68,"lookback_candles":6, "hard_stop": True}},
            {"type": "rsi_reversal_momentum",   "params": {"lookback_candles": 10, "oversold_threshold": 48, "current_min": 36, "min_jump": 3, "require_sustained": False,}},
            {"type": "rsi_range", "params": {"min": 50, "max": 67, "invert": True}},
            {"type": "reversal_candle", "params": {"pattern": "engulfing", "max_drop_from_close_pct": 0.6}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55, "max_drop_from_close_pct": 0.6}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.6}},
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02,"max_slope_pct":0.25,"hard_stop": True}},
        ],
        "min_entry_indicators_required": 7,
    },

    "tf_v2_defaultwithvolumelimit": {
        **_TF_BASE,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.001,"hard_stop": True}},
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
            {"type": "volume_spike", "params": {"min_ratio": 0.3, "max_ratio": 1.5, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 7,

   },

    "tf_v4_default_new": {
        **_TF_BASE,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.001,"hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.65}},
            {"type": "reversal_candle", "indicator_group": "grp_1","params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
            {"type": "rsi_threshold",  "indicator_group": "grp_1", "params": {"period": 14, "min_value": 57,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02,"max_slope_pct":0.25,"hard_stop": True}},
            {"type": "volume_spike", "params": {"min_ratio": 0.3, "max_ratio": 1.5, "hard_stop": True}},
        ],
        "entry_indicator_groups": {
            "grp_1": {"require_all": False, "hard_stop": True},
        },
        "min_entry_indicators_required": 6,

   },


    "tf_v3_ai_bbtight_vollimit": {
        **_TF_BASE,
        "take_profit_pct": 0.75,
        "stop_loss_pct": 0.6,
        "trailing_stop_pct": 0.5,
        "arm_trailing_stop_pct": 0.5,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.001,"hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "ema_gap",         "params": {"min_gap_pct": 0.15, "mode": "min"}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 2, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.5,"max_pct_b": 0.90, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 68,"lookback_candles":6, "hard_stop": True}},
            {"type": "rsi_reversal_momentum",   "params": {"lookback_candles": 10, "oversold_threshold": 48, "current_min": 36, "min_jump": 3, "require_sustained": False,}},
            {"type": "rsi_range", "params": {"min": 50, "max": 67, "invert": True}},
            {"type": "reversal_candle", "params": {"pattern": "engulfing", "max_drop_from_close_pct": 0.6}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55, "max_drop_from_close_pct": 0.6}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.6}},
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02,"max_slope_pct":0.25,"hard_stop": True}},
            {"type": "volume_spike", "params": {"min_ratio": 0.3, "max_ratio": 1.5, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 8,
    },

}




