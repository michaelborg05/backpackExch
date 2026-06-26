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
    "exit_indicators": [
        # Exit short when price reverts within 0.5% of EMA50 on 60m (mean reversion complete)
        {"type": "price_extended_above_ema",
        "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 10.0}},
        # Also exit if RSI drops below 35 (already oversold — short has run its course)
        {"type": "rsi_overbought",
        "params": {"side": "short", "max_value": 35}},
    ],
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_exit_indicators_required": 1,
    "min_position_age_for_trend_check": 30,  # don't check first 30 mins
    "exit_timeframe": "60",
}

# =============================================================================
# SHARED CORES — avoids repeating entry/trend config across experiment variants
# =============================================================================

# V12 entry + trend config (most active, proven baseline)
_V12_CORE = {
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
            "require_sustained": False, "drop_required": True}},
        {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
        {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
        {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
        {"type": "rsi_range", "params": {"min": 70, "max": 100}},
        {"type": "rsi_range", "params": {"min": 45, "max": 60}},
        {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
    ],
    "min_entry_indicators_required": 4,
    "min_signal_confidence": 78.0,
    "min_volume_ratio": 1.2,
}

# V14 entry + trend config (ADX bimodal filter — blocks mid-trend entries)
_V14_CORE = {
    **_V12_CORE,
    "trend_indicators": [
        {"type": "price_extended_above_ema",
         "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
         "hard_stop": True},
        {"type": "adx_regime", "params": {"max_adx": 25}},          # ranging market
        {"type": "adx_regime", "params": {"min_adx": 45, "max_adx": 100}},  # exhausted trend
    ],
    "min_indicators_required": 2,  # price_extended + one ADX zone
}

# Shared exit configs for experiments
_EXIT_EMA20_AGE0 = {
    "exit_indicators": [
        {"type": "price_extended_above_ema", "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0}},
    ],
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_exit_indicators_required": 1,
    "min_position_age_for_trend_check": 0,
    "exit_timeframe": "60",
}

_EXIT_EMA20_AGE15 = {**_EXIT_EMA20_AGE0, "min_position_age_for_trend_check": 15}

_EXIT_EMA10_AGE15 = {
    "exit_indicators": [
        {"type": "price_extended_above_ema", "params": {"ema": 50, "min_gap_pct": 1.0, "max_gap_pct": 10.0}},
    ],
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_exit_indicators_required": 1,
    "min_position_age_for_trend_check": 15,
    "exit_timeframe": "60",
}

_EXIT_VWAP_AGE30 = {
    "exit_indicators": [
        # Exit when price drops to within 0% of VWAP (price crossed below VWAP — reversion complete)
        {"type": "price_above_vwap", "params": {"min_gap_pct": 0.0, "max_gap_pct": 20.0}},
    ],
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_exit_indicators_required": 1,
    "min_position_age_for_trend_check": 30,
    "exit_timeframe": "15",
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
    # -------------------------------------------------------------------------
    # V15: OPTIMISED CHAMPION (from systematic backtesting, 60-day validation)
    # Result: 119 trades, 77% win, 0.38% avg PnL, 44.63% total, 2.89x PF
    #
    # Key changes vs V12:
    # - ob_threshold lowered 72→68 + require_sustained=True: confirms real momentum turn
    # - min_drop raised 4→5: needs a larger drop before entry fires
    # - SL widened 0.7→0.9%: gives trades more breathing room, +6pp win rate
    # - 60m rsi_range(70) hard_stop: caps entries when 60m RSI already elevated (trends)
    # - EMA 2.0% age=0 exit: locks in gains as soon as price reverts toward EMA50
    # -------------------------------------------------------------------------
    "mrs_v15_optimised": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            # Gate 1: price must be extended ≥ 2% above 60m EMA50
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            # Gate 2: caps entries when 60m RSI is already elevated (≥70 = trending too hard)
            {"type": "rsi_range",
             "params": {"min": 70, "max": 100},
             "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 68,
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True}},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought",   "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            # OB zone (70-100): passes when RSI < 70 — price peaked OB, now just off the top
            {"type": "rsi_range",        "params": {"min": 70, "max": 100}},
            # Fallen zone (45-60): passes when RSI < 45 or > 60 — RSI has deeply reverted
            # These two zones are INDEPENDENT quality signals, not alternatives — both can fire
            # at RSI 60-69, contributing 2 separate points (best entry zone). Do NOT group them.
            {"type": "rsi_range",        "params": {"min": 45, "max": 60}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 78.0,
        "min_volume_ratio": 1.2,
        # Exit: leave when price reverts to within 2% of EMA50 (lock in gain early)
        "exit_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0}},
        ],
        "use_trend_invalidation_exit": True,
        "trend_invalidation_indicators": "exit",
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 0,
        "exit_timeframe": "60",
    },

    "mrs_v14_adx_regime": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            # Require price extended above EMA50 (same as V12)
            {"type": "price_extended_above_ema",
            "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
            "hard_stop": True},
            # Block mid-trend ADX zone (30-45): only allow ranging (<25) or exhausted (>45)
            {"type": "adx_regime",
            "params": {"max_adx": 25}},                 # ranging
            {"type": "adx_regime",
            "params": {"min_adx": 45, "max_adx": 100}}, # extreme/exhausted
        ],
        "min_indicators_required": 2,   # price_extended + one of the two ADX zones
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
   }

}

# =============================================================================
# EXPERIMENTAL BATCH — Exit Indicator & Filter Optimization
#
# Goal: 0.20%+ avg PnL, 60-80 trades over 60 days
# All built on V12 or V14 entry+trend config (only exit/filter varies per group)
#
# Group A: Exit timing on V12 base (isolates exit indicator variable)
# Group B: V14 (ADX bimodal) with exit variations
# Group C: Entry filter experiments
# =============================================================================

MEAN_REV_SHORT_EXPERIMENTS = {

    # ----- GROUP A: Exit indicator timing on V12 base -------------------------

    # Control: V12 with NO trend invalidation exit (pure TP/SL/trailing)
    # Tells us whether exit indicators help or hurt V12's raw performance
    "mrs_v20_no_exit": {
        **_V12_CORE,
        "use_trend_invalidation_exit": False,
    },

    # EMA 2.0% exit, age=0 — most aggressive early exit
    # Mirrors the old backtester "trend" mode default (fired on any reversion past 2%)
    # Expect: high win rate, lower avg PnL (exits before TP)
    "mrs_v21_ema20_age0": {
        **_V12_CORE,
        **_EXIT_EMA20_AGE0,
    },

    # EMA 2.0% exit, age=15 — same but gives 15 min to develop before checking
    # Avoids false exits on immediate post-entry noise
    "mrs_v22_ema20_age15": {
        **_V12_CORE,
        **_EXIT_EMA20_AGE15,
    },

    # EMA 1.0% exit, age=15 — waits for more complete reversion (price < 1% above EMA)
    # Expect: better avg PnL than v21, slightly lower win rate
    "mrs_v23_ema10_age15": {
        **_V12_CORE,
        **_EXIT_EMA10_AGE15,
    },

    # VWAP exit, age=30 — exit when price drops back below VWAP (reversion complete)
    # More semantic: "mean reversion happened when price is no longer above VWAP"
    "mrs_v24_vwap_age30": {
        **_V12_CORE,
        **_EXIT_VWAP_AGE30,
    },

    # ----- GROUP B: V14 (ADX bimodal) + exit variations -----------------------

    # V14 with NO exit — baseline for ADX-filtered entries (pure TP/SL)
    "mrs_v25_v14_no_exit": {
        **_V14_CORE,
        "use_trend_invalidation_exit": False,
    },

    # V14 + aggressive EMA 2.0% exit — best of both worlds hypothesis
    # ADX filter cuts bad entries, early exit locks in reversion gains
    "mrs_v26_v14_ema20_age0": {
        **_V14_CORE,
        **_EXIT_EMA20_AGE0,
    },

    # V14 + EMA 2.0% exit with 15 min grace period
    "mrs_v27_v14_ema20_age15": {
        **_V14_CORE,
        **_EXIT_EMA20_AGE15,
    },

    # ----- GROUP C: Entry filter experiments ----------------------------------

    # V12 + 60m RSI must be >= 75 (hard_stop) — only allow true exhaustion entries
    # Blocks borderline "RSI 68-74" entries where trend may still be building
    # + aggressive EMA exit to lock in gains
    "mrs_v28_htf_rsi75": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range",
             "params": {"min": 75, "max": 100},
             "hard_stop": True},
        ],
        "min_indicators_required": 2,
        **_EXIT_EMA20_AGE0,
    },

    # V12 OB zone only — removes the 45-60 RSI zone, only allows RSI 70-100 entries
    "mrs_v29_ob_zone_only": {
        **_V12_CORE,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 70, "min_drop": 4.0,
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # ==========================================================================
    # ROUND 2 — HTF RSI gate sensitivity + V28 TP/SL optimisation
    # ==========================================================================

    # RSI gate sensitivity sweep (all with EMA 2.0% exit + age=0 like V28)
    # Goal: find sweet spot between trade volume and entry quality

    # RSI ≥ 72 — slightly looser than V28 (75), expect ~155 trades, ~0.22% avg
    "mrs_v30_htf_rsi72": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 72, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        **_EXIT_EMA20_AGE0,
    },

    # RSI ≥ 70 — matches 60m RSI "overbought" threshold, expect ~165 trades, ~0.21% avg
    "mrs_v31_htf_rsi70": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        **_EXIT_EMA20_AGE0,
    },

    # RSI ≥ 68 — very loose, effectively a soft floor
    "mrs_v32_htf_rsi68": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 68, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        **_EXIT_EMA20_AGE0,
    },

    # V28 TP/SL experiments — test if exhaustion entries can run further
    # V28 base: RSI≥75 hard_stop + EMA 2.0% exit age=0, TP=1.2%, SL=0.7%

    # Wider TP — capture bigger reversion moves on exhaustion entries
    "mrs_v33_v28_tp15": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 75, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.5,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        **_EXIT_EMA20_AGE0,
    },

    # Wider SL — more breathing room for exhaustion plays that need time to develop
    "mrs_v34_v28_sl09": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 75, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        **_EXIT_EMA20_AGE0,
    },

    # Best combo hypothesis: RSI≥72 gate (more trades than V28) + wider TP=1.5%
    "mrs_v35_rsi72_tp15": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 72, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.5,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        **_EXIT_EMA20_AGE0,
    },

    # ==========================================================================
    # ROUND 3 — Tighten RSI cap + combine with SL/TP optimisation
    #
    # Key finding: rsi_range in trend_indicators acts as an UPPER CAP on 60m RSI
    # for short strategies. min=70 blocks entries when 60m RSI ≥ 70, which
    # filters out June 15-style strongly trending entries.
    # V31 (cap<70): 115 trades, 69% win, 0.32% avg — best so far.
    # V34 (V28+SL0.9%): 137 trades, 70% win, 0.26% avg — best win rate.
    # ==========================================================================

    # Tighter RSI cap: only allow entries when 60m RSI < 67
    # Hypothesis: even better quality at the cost of fewer trades (~85 expected)
    "mrs_v36_rsi_cap67": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 67, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        **_EXIT_EMA20_AGE0,
    },

    # Even tighter: 60m RSI < 65
    "mrs_v37_rsi_cap65": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 65, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        **_EXIT_EMA20_AGE0,
    },

    # V31 (cap<70) + wider SL=0.9% — gives trades more breathing room
    # V34 showed SL widening boosted win rate by 6pp; apply same to best entry filter
    "mrs_v38_rsi70_sl09": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        **_EXIT_EMA20_AGE0,
    },

    # V31 + wider TP=1.4% (mild increase — test if exhaustion entries run further)
    "mrs_v39_rsi70_tp14": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.4,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        **_EXIT_EMA20_AGE0,
    },

    # RSI cap 67 + wider SL=0.9%
    "mrs_v40_rsi67_sl09": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 67, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        **_EXIT_EMA20_AGE0,
    },

    # ==========================================================================
    # ROUND 4 — SL fine-tuning + entry indicator stress tests on V38's config
    # V38 baseline: cap<70 + SL=0.9% + EMA2.0% exit + age=0
    # 115 trades, 74% win, 0.33% avg PnL, 2.46x profit factor
    # ==========================================================================

    # SL = 0.8% — between original 0.7% and winning 0.9%, test if there's a sweet spot
    "mrs_v41_rsi70_sl08": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.8,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        **_EXIT_EMA20_AGE0,
    },

    # SL = 1.0% — wider still; check if win rate improves more or losses get too costly
    "mrs_v42_rsi70_sl10": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 1.0,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        **_EXIT_EMA20_AGE0,
    },

    # V38 with NO exit indicators — does EMA exit help or is pure TP/SL better?
    "mrs_v43_rsi70_sl09_noexit": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "use_trend_invalidation_exit": False,
    },

    # V38 + stronger RSI drop required (min_drop 4→5) — only enter on bigger momentum shift
    "mrs_v44_rsi70_sl09_drop5": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 70, "min_drop": 5.0,   # was 4.0
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # V38 + tighter BB gate (0.90 pct_b vs 0.85) — price must be closer to BB upper
    "mrs_v45_rsi70_sl09_bb90": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 70, "min_drop": 4.0,
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.90}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # ==========================================================================
    # ROUND 5 — RSI momentum entry parameter tuning
    # V44 baseline: cap<70 + SL=0.9% + min_drop=5.0 + EMA2.0% exit
    # 114 trades, 75% win, 0.34% avg PnL, 2.55x profit factor
    # Testing: min_drop, overbought_threshold, lookback_candles, volume cap
    # ==========================================================================

    # V44 + min_drop=6.0 (even stronger momentum shift needed before entry)
    "mrs_v46_drop6": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 70, "min_drop": 6.0,
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # Lower overbought_threshold to 70 (wider net: RSI just needs to peak at 70, not 72)
    "mrs_v47_ob70_drop5": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 70,  # was 72
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # Higher overbought_threshold to 75 (stricter: RSI must peak at 75+)
    "mrs_v48_ob75_drop5": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 75,  # was 72
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # V44 + longer lookback (8 candles instead of 5) — catches peaks further back
    "mrs_v49_lookback8_drop5": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 8, "overbought_threshold": 72,  # was 5
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # V44 + volume cap loosened (1.0-3.0 vs 1.2-2.4)
    "mrs_v50_vol_loose": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.0, "max_ratio": 3.0}},  # was 1.2-2.4
        ],
        **_EXIT_EMA20_AGE0,
    },

    # ==========================================================================
    # ROUND 6 — Final V47 tuning: current_max, sustained drop, trailing stop
    # V47 baseline: ob=70, drop=5, cap<70, SL=0.9%
    # 117 trades, 76% win, 0.35% avg PnL, 41.21% total, 2.68x
    # ==========================================================================

    # V47 + current_max=65 — RSI must fall to 65 or below at entry
    # Tests whether requiring a deeper pullback before entry improves quality
    "mrs_v51_ob70_drop5_max65": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 70,
                "current_max": 65, "min_drop": 5.0,   # was current_max=70
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # V47 + require_sustained=True — RSI must consistently fall (no counter-bounces)
    "mrs_v52_ob70_sustained": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 70,
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": True, "sustained_fall_mode": "net",   # was False
                "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # V47 with tighter trailing stop (0.5/0.5 vs 0.6/0.6) — lock in gains faster
    "mrs_v53_ob70_trail05": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.5,         # was 0.6
        "arm_trailing_stop_pct": 0.5,     # was 0.6
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 70,
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # V47 with only the OB RSI zone (remove 45-60 zone)
    "mrs_v54_ob70_ob_zone_only": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 70,
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": False, "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},   # OB zone only
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # ==========================================================================
    # ROUND 7 — Final V52 validation: drop size, lookback, ob threshold
    # V52 baseline: ob=70, drop=5, sustained=True(net), cap<70, SL=0.9%
    # 118 trades, 76% win, 0.36% avg PnL, 42.37% total, 2.74x
    # ==========================================================================

    # V52 + min_drop=4.0 (less drop required) — wider net, check quality vs quantity
    "mrs_v55_ob70_drop4_sustained": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 70,
                "current_max": 70, "min_drop": 4.0,   # was 5.0
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # V52 + min_drop=6.0 (stronger drop needed) — higher bar for entry
    "mrs_v56_ob70_drop6_sustained": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 70,
                "current_max": 70, "min_drop": 6.0,   # was 5.0
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # V52 + lookback=7 (see peaks further back in time)
    "mrs_v57_ob70_lookback7_sustained": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 7, "overbought_threshold": 70,  # was 5
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # V52 with ob=68
    "mrs_v58_ob68_drop5_sustained": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 68,  # was 70
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # ob=65 — test if trend continues improving below 68
    "mrs_v59_ob65_drop5_sustained": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 65,
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # ob=63 — floor test
    "mrs_v60_ob63_drop5_sustained": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 63,
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        **_EXIT_EMA20_AGE0,
    },

    # V58 + no exit indicators — does EMA exit still help at this quality level?
    "mrs_v61_ob68_no_exit": {
        **_V12_CORE,
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}, "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 68,
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought", "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 70, "max": 100}},
            {"type": "rsi_range", "params": {"min": 45, "max": 60}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        "use_trend_invalidation_exit": False,
    },
}