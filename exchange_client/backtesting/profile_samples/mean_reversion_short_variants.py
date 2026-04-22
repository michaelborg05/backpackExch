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
    "signal_timeframe": "15",
    "entry_timeframe": "15",
    "take_profit_pct": 1.0,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 900,
    "min_signal_confidence": 75.0,
    "min_volume_ratio": 1.2,
    "use_trend_filter": False,
    "use_entry_filter": True,
    "max_position_hours": 4,
    "use_market_regime_filter": False,
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
        {"type": "rsi_overbought",           "params": {"min_value": 44}},
    ],
    "min_entry_indicators_required": 4,
}

MEAN_REV_SHORT_VARIANTS = {

    "mrs_baseline": _MEAN_REV_SHORT_BASE,

    # -------------------------------------------------------------------------
    # V1: REGIME GATED — mirror of mr_v14_regime_gated
    # 60m price extended ABOVE EMA50 confirms overbought regime before
    # firing the 15m exhaustion entry. Keeps shorts out of sideways chop
    # where any pump is just random noise without regime confirmation.
    # -------------------------------------------------------------------------
    "mrs_v1_regime_gated": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {
                "type": "price_extended_above_ema",
                "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 4.5},
                "hard_stop": True,
            },
        ],
        "min_indicators_required": 1,
        "entry_indicators": [
            {"type": "volume_spike",             "params": {"min_ratio": 1, "max_ratio": 8.0}},
            {"type": "bollinger_bands",          "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.75}},
            {"type": "rsi_overbought_momentum",  "params": {"lookback_candles": 6, "overbought_threshold": 62, "current_max": 60, "min_drop": 3.0, "require_sustained": True, "sustained_fall_mode": "net", "drop_required": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": 0.7, "max_gap_pct": 8.0}},
            {"type": "reversal_candle",          "params": {"pattern": "bear_close", "max_close_pct": 0.40, "max_rise_from_close_pct": 0.6}},
            {"type": "price_above_vwap",         "params": {"min_gap_pct": 0.5, "max_gap_pct": 8.0}},
        ],
        "min_entry_indicators_required": 4,
    },

    "mrs_v2_regime_gated_mod": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {
                "type": "price_extended_above_ema",
                "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 4.5},
                "hard_stop": True,
            },
        ],
        "min_indicators_required": 1,
        "entry_indicators": [
            {"type": "volume_spike",             "params": {"min_ratio": 1, "max_ratio": 8.0}},
            {"type": "bollinger_bands",          "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.75}},
            {"type": "rsi_overbought_momentum",  "params": {"lookback_candles": 6, "overbought_threshold": 62, "current_max": 65, "min_drop": 3.0, "require_sustained": True, "sustained_fall_mode": "net", "drop_required": True, "hard_stop": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": 0.7, "max_gap_pct": 8.0}},
            {"type": "reversal_candle",          "params": {"pattern": "bear_close", "max_close_pct": 0.40, "max_rise_from_close_pct": 0.6}},
            {"type": "price_above_vwap",         "params": {"min_gap_pct": 0.5, "max_gap_pct": 8.0}},
        ],
        "min_entry_indicators_required": 4,
    },


    # -------------------------------------------------------------------------
    # V3: BEST COMBINED (LOOSER RSI) — mirror of mr_v15_best_combined
    # Looser RSI params to catch gradual distribution (slow grind up) as well
    # as sharp spike rejections. Wider SL absorbs the final squeeze before
    # the reversal. This is the starting "kitchen sink" variant — run it
    # first to establish a baseline trade count and win rate.
    # -------------------------------------------------------------------------
    "mrs_v3_best_combined": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 4.0},
             "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 0.8,
        "stop_loss_pct": 1.0,
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 8, "overbought_threshold": 70,
                "current_max": 68, "min_drop": 3.0,
                "require_sustained": False, "sustained_fall_mode": "net",
                "drop_required": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.70}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 0.5, "max_gap_pct": 12.0}},
            {"type": "rsi_overbought",   "params": {"min_value": 44}},
            {"type": "volume_spike",     "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 70.0,
        "min_volume_ratio": 0.7,
    },

    # -------------------------------------------------------------------------
    # V4: AVOID MIDDLE — mirror of mr_v15_best_combined-avoidmiddle
    # Two 60m trend gates to skip the ambiguous mid-range EMA zone.
    # Only fires when 60m price is clearly extended above EMA50 — either
    # in the strongly extended zone (>1.5%) OR just cleanly clear of it
    # (0.5–1.0%). Avoids wasted shorts when price is hugging the EMA
    # without conviction, where reversions tend to be shallow.
    # -------------------------------------------------------------------------
    "mrs_v4_avoid_middle": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 1.5, "max_gap_pct": 5.0}},  # strongly extended
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 1.0}},  # cleanly above EMA
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 0.8,
        "stop_loss_pct": 1.0,
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 8, "overbought_threshold": 70,
                "current_max": 68, "min_drop": 3.0,
                "require_sustained": False, "sustained_fall_mode": "net",
                "drop_required": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.70}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 0.5, "max_gap_pct": 12.0}},
            {"type": "rsi_overbought",   "params": {"min_value": 44}},
            {"type": "volume_spike",     "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 70.0,
        "min_volume_ratio": 0.7,
    },

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
             "params": {"ema": 50, "min_gap_pct": 1.5, "max_gap_pct": 5.0}},
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 1.0}},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.5,
        "arm_trailing_stop_pct": 0.5,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 8, "overbought_threshold": 70,
                "current_max": 68, "min_drop": 3.0,
                "require_sustained": False, "sustained_fall_mode": "net",
                "drop_required": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.70}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 0.5, "max_gap_pct": 12.0}},
            {"type": "rsi_overbought",   "params": {"min_value": 44}},
            {"type": "volume_spike",     "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 70.0,
        "min_volume_ratio": 0.7,
    },

    # -------------------------------------------------------------------------
    # V6: BEARISH CANDLE CONFIRMATION
    # Adds a shooting_star or bear_close candle gate on top of V3 logic.
    # Higher precision, lower trade count. The candle pattern confirms the
    # 15m bar itself rejected at the highs before entry — not just RSI rolling
    # over. Best for filtering out fakeout pumps that reclaim quickly.
    # -------------------------------------------------------------------------
    "mrs_v6_bearish_candle": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 4.0},
             "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 0.8,
        "stop_loss_pct": 1.0,
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 6, "overbought_threshold": 65,
                "current_max": 63, "min_drop": 3.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.75}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 0.5, "max_gap_pct": 8.0}},
            {"type": "rsi_overbought",   "params": {"min_value": 44}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
            # Shooting star: long upper wick = buyers were rejected hard at the highs
            {"type": "reversal_candle",  "params": {"pattern": "shooting_star", "min_body_pct": 0.08, "max_rise_from_close_pct": 0.5}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 75.0,
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
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 4.0},
             "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 0.8,
        "stop_loss_pct": 1.0,
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 6, "overbought_threshold": 65,
                "current_max": 63, "min_drop": 3.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.70}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 0.5, "max_gap_pct": 8.0}},
            {"type": "rsi_overbought",   "params": {"min_value": 44}},
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
        "take_profit_pct": 1.5,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 72,
                "current_max": 70, "min_drop": 4.0,
                "require_sustained": False,
                "drop_required": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought",   "params": {"min_value": 44}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 78.0,
        "min_volume_ratio": 1.2,
    },

    # -------------------------------------------------------------------------
    # V9: EMA SLOPE GATED
    # Adds a 60m EMA20 falling slope check as the second trend indicator.
    # The idea: price extended above EMA50 AND EMA20 is now rolling over
    # confirms that the momentum has already turned at the higher timeframe,
    # not just stretched. Catches tops earlier than waiting for RSI to fully
    # roll on the 15m. Run alongside V3 to compare signal timing.
    # -------------------------------------------------------------------------
    "mrs_v9_ema_slope_gated": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 5.0},
             "hard_stop": True},
            # EMA20 must be flat or falling on the 60m — momentum turning
            {"type": "ema_slope",
             "params": {"ema": 20, "direction": "not_rising", "min_slope_pct": 0.01}},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 0.8,
        "stop_loss_pct": 1.0,
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 6, "overbought_threshold": 65,
                "current_max": 63, "min_drop": 3.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.72}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 0.5, "max_gap_pct": 8.0}},
            {"type": "rsi_overbought",   "params": {"min_value": 44}},
            {"type": "volume_spike",     "params": {"min_ratio": 0.8, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 72.0,
        "min_volume_ratio": 0.8,
    },

    # -------------------------------------------------------------------------
    # V10: RSI LOOKBACK GATE (COOLING PEAK)
    # Uses rsi_overbought with lookback_candles to catch post-peak cooling —
    # RSI hit overbought territory in the last N candles but has since come
    # back below the threshold. No momentum indicator needed; the lookback
    # handles timing. Simplest possible signal stack: 3 strong indicators.
    # Useful as a counterpoint to V3 to see if simpler = better on shorts.
    # -------------------------------------------------------------------------
    "mrs_v10_rsi_lookback_simple": {
        **_MEAN_REV_SHORT_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 4.0},
             "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.5,
        "arm_trailing_stop_pct": 0.5,
        "entry_indicators": [
            # lookback_candles: RSI was overbought in last 5 candles (post-peak cooling)
            {"type": "rsi_overbought",   "params": {"min_value": 65, "lookback_candles": 5, "hard_stop": True}},
            # Current RSI has pulled back but isn't oversold (still in reversion window)
            {"type": "rsi_overbought",   "params": {"min_value": 44}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 0.5, "max_gap_pct": 8.0}},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.65}},
            {"type": "volume_spike",     "params": {"min_ratio": 0.8, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 70.0,
        "min_volume_ratio": 0.8,
    },
}