# =============================================================================
# MEAN REVERSION SHORT VARIANTS
# Mirror of the long mean reversion variants — fade overbought exhaustion.
#
# Structure:
#   - 1-2 trend indicators on 60m (EMA range gates — confirms overbought regime)
#   - Majority of signals on 15m (RSI exhaustion + price extension detection)
#
# Core short indicator: rsi_overbought_momentum
#   RSI must have peaked ABOVE overbought_threshold in the lookback window,
#   then dropped by min_drop points and currently be falling.
#   Direct mirror of rsi_reversal_momentum used in the long variants.
# =============================================================================

_MEAN_REV_SHORT_BASE = {
    "display_name": "mean_reversion_short_profile",
    "strategy_type": "mean_reversion_short",
    "entry_timeframe": "15",
    "take_profit_pct": 1.2,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 15,
    "min_signal_confidence": 75.0,
    "min_volume_ratio": 1.2,
    "use_trend_filter": False,
    "use_entry_filter": True,
    "max_position_hours": 4,
    "use_market_regime_filter": False,
    # "trading_hours": [
    #     {"day_of_week": 0, "start_time": "05:00", "end_time": "12:00", "enabled": True},
    #     {"day_of_week": 0, "start_time": "15:00", "end_time": "21:00", "enabled": True},
    #     {"day_of_week": 1, "start_time": "02:00", "end_time": "23:00", "enabled": True},
    #     {"day_of_week": 2, "start_time": "01:00", "end_time": "12:00", "enabled": True},
    #     {"day_of_week": 2, "start_time": "14:00", "end_time": "23:00", "enabled": True},
    #     {"day_of_week": 3, "start_time": "03:00", "end_time": "12:00", "enabled": True},
    #     {"day_of_week": 3, "start_time": "14:00", "end_time": "21:00", "enabled": True},
    #     {"day_of_week": 4, "start_time": "03:00", "end_time": "12:00", "enabled": True},
    #     {"day_of_week": 4, "start_time": "14:00", "end_time": "21:00", "enabled": True},
    # ],
    "entry_indicators": [
        # Core short momentum gate: RSI peaked OB then dropped sharply and is falling
        {"type": "rsi_overbought_momentum",  "params": {"lookback_candles": 5, "overbought_threshold": 68, "current_max": 65, "min_drop": 4.0, "require_sustained": True, "sustained_fall_mode": "net", "drop_required": True}},
        # Price stretched above VWAP
        {"type": "price_above_vwap",         "params": {"min_gap_pct": 0.5, "max_gap_pct": 8.0}},
        # Volume spike confirms distribution / buying climax
        {"type": "volume_spike",             "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
        # Price in upper portion of BB — near the upper band
        {"type": "bollinger_bands",          "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "max_pct_b": 1.10}},
        # Not deeply oversold — blocks shorts in a genuine downtrend that's already extended
        {"type": "rsi_overbought",           "params": {"max_value": 35,"side": "short"}},
    ],
    "min_entry_indicators_required": 4,
}

MEAN_REV_SHORT_VARIANTS = {

    "mrs_baseline": _MEAN_REV_SHORT_BASE,
    # -------------------------------------------------------------------------
    # V5: AVOID MIDDLE — TIGHT TP/SL — mirror of mr_v15_best_combined-avoidmiddle_v2
    # Same avoid-middle 60m gate logic as V4 but reverts to the tighter
    # 1.0/0.7 TP/SL ratio. Tests whether quicker exits beat the wider ratio.
    # Trailing stop also tightened back to 0.5/0.5.
    # -------------------------------------------------------------------------
    "mrs_v5_avoid_middle_tight": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 1.5, "max_gap_pct": 8.0}},
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 1.0}},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.5,
        "arm_trailing_stop_pct": 0.5,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 8, "overbought_threshold": 70,
                "current_max": 60, "min_drop": 3.0,
                "require_sustained": False, "sustained_fall_mode": "net",
                "drop_required": True,"hard_stop": True
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.70}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 0.5, "max_gap_pct": 12.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 58, "max": 70, "invert": False}},            
            {"type": "volume_spike",     "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 70.0,
        "min_volume_ratio": 0.7,
    },

    # -------------------------------------------------------------------------
    # V7: BEAR CLOSE + LOWER HIGH CONFIRMATION
    # Dual candle confirmation: requires bear_close on the signal candle
    # AND lower_high pattern across the last two closed candles.
    # Lower_high = buying exhaustion forming in real time (each rally peak lower).
    # Very selective — expect low trade count but high precision.
    # -------------------------------------------------------------------------
    "mrs_v7_dual_candle": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "max_position_hours": 4,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2, "max_gap_pct": 8.0},
             "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 1,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 6, "overbought_threshold": 65,
                "current_max": 55, "min_drop": 3.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True,"hard_stop": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.70}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 0.5, "max_gap_pct": 8.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 58, "max": 70, "invert": False}},            {"type": "volume_spike",     "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 0.9, "max_ratio": 8.0}},
            # Bear close: sellers dominated into the candle close
            {"type": "reversal_candle",  "params": {"pattern": "bear_close", "max_close_pct": 0.40, "max_rise_from_close_pct": 0.5}},
            # Lower high: each rally peak is lower — structural exhaustion
            {"type": "reversal_candle",  "params": {"pattern": "lower_high", "require_bear": False}},
        ],
        "min_entry_indicators_required": 5,
        "min_signal_confidence": 75.0,
    },

    # -------------------------------------------------------------------------
    # V8: EXTREME EXTENSION
    # Only fires when 60m price is VERY extended above EMA50 (2%+).
    # Targets violent snap-backs after euphoric pumps — particularly
    # relevant for HYPE and SUI which spike aggressively. Wider TP
    # to capture more of the full reversion move, wider SL to survive
    # the final squeeze before the top.
    # -------------------------------------------------------------------------
    "mrs_v8_extreme_extension": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 70, "min_drop": 4.0,
                "require_sustained": False,
                "drop_required": True
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 58, "max": 70, "invert": False}},            {"type": "volume_spike",     "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 78.0,
        "min_volume_ratio": 1.2,
    },

    "mrs_v10_extreme_rsi62-mod": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
            "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
            "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 70, "min_drop": 4.0,
                "require_sustained": False,
                "drop_required": True,
                "hard_stop": True
            }},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            # KEY CHANGE: floor raised from 58 to 62 — kills the 55-60 dead zone
            {"type": "rsi_range", "params": {"min": 62, "max": 75, "invert": False, "hard_stop": True}},
            #{"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 78.0,
        "min_volume_ratio": 1.2,
    },
    "mrs_v11_extreme_extension-mod": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 70, "min_drop": 4.0,
                "require_sustained": False,
                "drop_required": True,
                "hard_stop": True
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 58, "max": 70, "invert": False}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 78.0,
        "min_volume_ratio": 1.2,
    },
    "mrs_v12_vol_cap_rsi_zones": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
            "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
            "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 70, "min_drop": 4.0,
                "require_sustained": False,
                "drop_required": True
            }},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            # Block RSI 60-70 dead zone: require RSI < 60 OR RSI >= 70
            # Zone 1: still clearly overbought
            {"type": "rsi_range", "params": {"min": 70, "max": 100, "invert": False}},
            # Zone 2: already dropped below 60 (failing bounce entry)
            {"type": "rsi_range", "params": {"min": 45, "max": 60, "invert": False}},
            # Cap volume — blocks momentum entries, keeps exhaustion entries
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        "min_entry_indicators_required": 4,  # needs bb/vwap + vol cap + one rsi zone
        "min_signal_confidence": 78.0,
        "min_volume_ratio": 1.2,
    },    
    "mrs_v13_vol_cap_rsi_zones-mod": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
            "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
            "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 80, "min_drop": 4.0,
                "require_sustained": False,
                "drop_required": True
            }},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
            #{"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},

            #Group 1 - Price extension
            {"type": "bollinger_bands","indicator_group": "price_extension", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap","indicator_group": "price_extension", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            
            #Group 2 - RSI range
            # Block RSI 60-70 dead zone: require RSI < 60 OR RSI >= 70
            {"type": "rsi_range", "indicator_group": "rsi_zone","params": {"min": 70, "max": 100, "invert": False}},
            # Zone 2: already dropped below 60 (failing bounce entry)
            {"type": "rsi_range", "indicator_group": "rsi_zone","params": {"min": 45, "max": 60, "invert": False}},
            # Cap volume — blocks momentum entries, keeps exhaustion entries
        ],
        "min_entry_indicators_required": 4,  # needs bb/vwap + vol cap + one rsi zone
        "min_signal_confidence": 78.0,
        "min_volume_ratio": 1.2,
         "entry_indicator_groups": {
            "rsi_zone": {"require_all": False, "hard_stop": True},
            "price_extension": {"require_all": False, "hard_stop": True},
        },
   },    

}