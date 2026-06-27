
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
    "max_cluster_entries": 2,
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

    # =========================================================================
    # COMPARISON VARIANTS — for exit criteria + trading hours analysis only
    # =========================================================================
    "range_r19_no_hours": {
        **_RANGE_BASE,
        "take_profit_pct": 0.9,
        "stop_loss_pct": 0.42,
        "trailing_stop_pct": 0.35,
        "arm_trailing_stop_pct": 0.50,
        "use_market_regime_filter": False,
        "trading_hours": None,
        "trend_indicators": [
            {"type": "rsi_range",       "params": {"min": 34, "max": 66, "invert": True, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
            {"type": "ema_gap",         "params": {"mode": "max", "max_gap_pct": 0.8, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_threshold",    "params": {"period": 14, "min_value": 34, "use_momentum": False, "hard_stop": True}},
            {"type": "rsi_overbought",   "params": {"min_value": 66, "hard_stop": True}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.10, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.42, "hard_stop": True}},
            {"type": "bb_width_regime",  "params": {"required_direction": "not_expanding", "lookback": 4, "min_width": 0.02, "hard_stop": True}},
            {"type": "bb_pct_b_momentum","params": {"lookback": 3, "required_direction": "not_rising", "hard_stop": True}},
            {"type": "reversal_candle",  "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle",  "params": {"pattern": "bull_close", "min_close_pct": 0.55, "max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle",  "params": {"pattern": "doji", "max_body_pct": 0.2, "max_drop_from_close_pct": 0.5}},
        ],
        "min_entry_indicators_required": 6,
    },

    # r19 + trend invalidation completely OFF (rely only on TP/SL/trailing/time)
    "range_r19_no_ti": {
        **_RANGE_BASE,
        "take_profit_pct": 0.9,
        "stop_loss_pct": 0.42,
        "trailing_stop_pct": 0.35,
        "arm_trailing_stop_pct": 0.50,
        "use_market_regime_filter": False,
        "use_trend_invalidation_exit": False,
        "trend_indicators": [
            {"type": "rsi_range",       "params": {"min": 34, "max": 66, "invert": True, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
            {"type": "ema_gap",         "params": {"mode": "max", "max_gap_pct": 0.8, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_threshold",    "params": {"period": 14, "min_value": 34, "use_momentum": False, "hard_stop": True}},
            {"type": "rsi_overbought",   "params": {"min_value": 66, "hard_stop": True}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.10, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.42, "hard_stop": True}},
            {"type": "bb_width_regime",  "params": {"required_direction": "not_expanding", "lookback": 4, "min_width": 0.02, "hard_stop": True}},
            {"type": "bb_pct_b_momentum","params": {"lookback": 3, "required_direction": "not_rising", "hard_stop": True}},
            {"type": "reversal_candle",  "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle",  "params": {"pattern": "bull_close", "min_close_pct": 0.55, "max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle",  "params": {"pattern": "doji", "max_body_pct": 0.2, "max_drop_from_close_pct": 0.5}},
        ],
        "min_entry_indicators_required": 6,
    },

    # r19 + dedicated exit indicators: only exit if range premise is CLEARLY broken
    # EMA gap > 1.5% = market trending hard; RSI < 28 or > 72 = panic/euphoria
    # (more lenient than entry conditions — gives the trade room to breathe)
    "range_r19_exit_inds": {
        **_RANGE_BASE,
        "take_profit_pct": 0.9,
        "stop_loss_pct": 0.42,
        "trailing_stop_pct": 0.35,
        "arm_trailing_stop_pct": 0.50,
        "use_market_regime_filter": False,
        "use_trend_invalidation_exit": True,
        "trend_invalidation_indicators": "exit",
        "min_position_age_for_trend_check": 0,
        "exit_timeframe": "60",
        "exit_indicators": [
            {"type": "ema_gap",   "params": {"mode": "max", "max_gap_pct": 1.5, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 28, "max": 72, "invert": True, "hard_stop": True}},
        ],
        "min_exit_indicators_required": 2,
        "trend_indicators": [
            {"type": "rsi_range",       "params": {"min": 34, "max": 66, "invert": True, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
            {"type": "ema_gap",         "params": {"mode": "max", "max_gap_pct": 0.8, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_threshold",    "params": {"period": 14, "min_value": 34, "use_momentum": False, "hard_stop": True}},
            {"type": "rsi_overbought",   "params": {"min_value": 66, "hard_stop": True}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.10, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.42, "hard_stop": True}},
            {"type": "bb_width_regime",  "params": {"required_direction": "not_expanding", "lookback": 4, "min_width": 0.02, "hard_stop": True}},
            {"type": "bb_pct_b_momentum","params": {"lookback": 3, "required_direction": "not_rising", "hard_stop": True}},
            {"type": "reversal_candle",  "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle",  "params": {"pattern": "bull_close", "min_close_pct": 0.55, "max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle",  "params": {"pattern": "doji", "max_body_pct": 0.2, "max_drop_from_close_pct": 0.5}},
        ],
        "min_entry_indicators_required": 6,
    },

    # =========================================================================
    # NEW: range_r19_no_adx — 5-iteration optimised champion
    #
    # Cross-symbol (6 symbols, 60d): 84T 49% WR +0.10% avg 1.51x PF
    # On SOL+ZEC+BNB only:          ~49T 57% WR +0.22% avg ~2.0x PF
    #
    # Key changes vs original:
    #  - ADX removed (ema_gap alone captures ranging more cleanly)
    #  - ema_slope removed from trend (directional — wrong for range trading)
    #  - RSI neutral zone widened: 35-60 → 34-66
    #  - R:R fixed to 2:1 (TP 0.9% / SL 0.42%, was 0.6%/0.52% ≈ 1.15:1)
    #  - Trailing stop arm raised: 0.25% → 0.50%
    #  - Added ema_gap max 0.8%: EMA compression gate (60m EMAs must be tight)
    #  - Added bb_pct_b_momentum: blocks entry when BB %B still drifting down
    #  - Added bb_width_regime: confirms bands not actively expanding
    # =========================================================================
    "range_r19_no_adx": {
        **_RANGE_BASE,
        "take_profit_pct": 0.9,
        "stop_loss_pct": 0.42,
        "trailing_stop_pct": 0.35,
        "arm_trailing_stop_pct": 0.50,
        "use_market_regime_filter": False,
        "trend_indicators": [
            {"type": "rsi_range",       "params": {"min": 34, "max": 66, "invert": True, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
            {"type": "ema_gap",         "params": {"mode": "max", "max_gap_pct": 0.8, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_threshold",    "params": {"period": 14, "min_value": 34, "use_momentum": False, "hard_stop": True}},
            {"type": "rsi_overbought",   "params": {"min_value": 66, "hard_stop": True}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.10, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.42, "hard_stop": True}},
            {"type": "bb_width_regime",  "params": {"required_direction": "not_expanding", "lookback": 4, "min_width": 0.02, "hard_stop": True}},
            {"type": "bb_pct_b_momentum","params": {"lookback": 3, "required_direction": "not_rising", "hard_stop": True}},
            {"type": "reversal_candle",  "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle",  "params": {"pattern": "bull_close", "min_close_pct": 0.55, "max_drop_from_close_pct": 0.5}},
            {"type": "reversal_candle",  "params": {"pattern": "doji", "max_body_pct": 0.2, "max_drop_from_close_pct": 0.5}},
        ],
        "min_entry_indicators_required": 6,
    },

}
