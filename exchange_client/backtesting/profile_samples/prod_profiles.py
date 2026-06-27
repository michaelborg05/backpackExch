"""
backtesting/profile_samples/prod_profiles.py
=============================================
Exact replicas of live production profiles used for prod-vs-backtest comparison.

To add a profile: define a config dict below and add it to PROD_PROFILES.
To remove a profile: delete its entry from PROD_PROFILES (keep or delete the dict).
To change symbols for a profile: edit the "symbols" key inside that profile's dict.

Each config dict must include a "symbols" key listing which markets to run against.
All other keys are standard BacktestProfile fields — no runner changes needed.
"""

# =============================================================================
# 15m Trend Following (long)
# =============================================================================
_PROD_15M_TREND = {
    "display_name": "prod_15m_trend",
    "symbols": ["SOL_USDC", "ETH_USDC", "BTC_USDC", "HYPE_USDC", "BNB_USDC", "XRP_USDC"],
    "strategy_type": "trend_following",
    "entry_timeframe": "15",
    "trend_timeframe": "60",
    "take_profit_pct": 0.8,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 15,
    "min_signal_confidence": 70.0,
    "min_volume_ratio": 1.1,
    "use_trend_filter": True,
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
        {"type": "ema_slope",        "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
        {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
        {"type": "adx_regime",       "params": {"min_adx": 22, "max_adx": 60}},
        {"type": "rsi_overbought",   "params": {"min_value": 68, "lookback_candles": 5, "hard_stop": True}},
    ],
    "min_indicators_required": 3,
    "entry_indicators": [
        {"type": "price_vs_ema",     "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
        {"type": "reversal_candle",  "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
        {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.65}},
        {"type": "rsi_threshold",    "params": {"period": 14, "min_value": 57, "use_momentum": True, "early_threshold": 45, "hard_stop": True}},
        {"type": "rsi_overbought",   "params": {"min_value": 63, "hard_stop": True}},
        {"type": "price_vs_vwap",    "params": {}},
        {"type": "ema_slope",        "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
    ],
    "min_entry_indicators_required": 6,
}

# =============================================================================
# Exported from profile: 4hr_ema50drop
_4HR_v8 = {
    "display_name": "4hr_p3_v8_vol_pullbackAI",
    "symbols": ['BTC_USDC', 'ETH_USDC', 'SOL_USDC', 'XRP_USDC'],
    "strategy_type": "trend_following",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "take_profit_pct": 3.0,
    "stop_loss_pct": 2.0,
    "trailing_stop_pct": 1.2,
    "arm_trailing_stop_pct": 1.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 241,
    "min_signal_confidence": 74.0,
    "min_volume_ratio": 1.0,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 72,
    "use_market_regime_filter": False,
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "trend",
    "min_position_age_for_trend_check": 241,
    "trading_hours": [],
    "trend_indicators": [
        {"type": "ema_cross", "params": {"hard_stop": True}},
        {"type": "adx_regime", "params": {"min_adx": 20, "max_adx": 32, "hard_stop": True}},
        {"type": "rsi_range", "params": {"min": 48, "max": 65, "invert": True}},
    ],
    "min_indicators_required": 3,
    "entry_indicators": [
        {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 8, "hard_stop": True}},
        {"type": "rsi_range", "params": {"min": 28, "max": 50, "invert": True}},
        {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0, "max_pct_b": 0.5}},
        {"type": "price_vs_ema", "params": {"ema": 20, "min_gap_pct": -5, "max_gap_pct": 2}},
    ],
    "min_entry_indicators_required": 3,
}

# =============================================================================
# 4hr Swing — Profile B  (second swing profile — adjust if different from A)
# =============================================================================

# Exported from profile: 4h_v19_tight_pullback
_4hr_p3_v11_slope_relaxedAI = {
    "display_name": "4hr_p3_v11_slope_relaxedAI",
    "symbols": ['BNB_USDC', 'BTC_USDC', 'ETH_USDC', 'SOL_USDC', 'XRP_USDC', 'ZEC_USDC'],
    "strategy_type": "trend_following",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "take_profit_pct": 3.5,
    "stop_loss_pct": 2.0,
    "trailing_stop_pct": 0.6,
    "arm_trailing_stop_pct": 1.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 241,
    "min_signal_confidence": 74.0,
    "min_volume_ratio": 1.0,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 72,
    "use_market_regime_filter": False,
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "trend",
    "min_position_age_for_trend_check": 30,
    "trading_hours": [],
    "trend_indicators": [
        {"type": "ema_cross", "params": {"hard_stop": True}},
        {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
        {"type": "rsi_range", "params": {"min": 52, "max": 63, "invert": True, "hard_stop": True}},
    ],
    "min_indicators_required": 3,
    "entry_indicators": [
        {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 40}},
        {"type": "rsi_range", "params": {"min": 30, "max": 50, "invert": True, "hard_stop": True}},
        {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 8}},
    ],
    "min_entry_indicators_required": 3,
}


# Exported from profile: profile3
_4hr_v13 = {
    "display_name": "4hr_p3_v13_wide_rsi_trendAI",
    "symbols": ['BNB_USDC', 'BTC_USDC', 'ETH_USDC'],
    "strategy_type": "trend_following",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "take_profit_pct": 3.0,
    "stop_loss_pct": 2.0,
    "trailing_stop_pct": 0.6,
    "arm_trailing_stop_pct": 1.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 241,
    "min_signal_confidence": 74.0,
    "min_volume_ratio": 0.9,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 72,
    "use_market_regime_filter": False,
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "trend",
    "min_position_age_for_trend_check": 5,
    "trading_hours": [],
    "trend_indicators": [
        {"type": "ema_cross", "params": {"hard_stop": True}},
        {"type": "rsi_range", "params": {"min": 48, "max": 65, "invert": True, "hard_stop": True}},
    ],
    "min_indicators_required": 2,
    "entry_indicators": [
        {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 40}},
        {"type": "rsi_range", "params": {"min": 30, "max": 50, "invert": True, "hard_stop": True}},
        {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 8}},
    ],
    "min_entry_indicators_required": 3,
}
# =============================================================================
# Mean Reversion (long, 15m entry / 60m trend)
# =============================================================================
_PROD_MEAN_REV_v3 = {
    "display_name": "prod_mean_rev",
    "symbols": ["SOL_USDC", "ETH_USDC", "BTC_USDC", "ZEC_USDC", "XRP_USDC", "BNB_USDC"],
    "strategy_type": "mean_reversion",
    "entry_timeframe": "15",
    "trend_timeframe": "60",
    "take_profit_pct": 1.0,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.4,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 20,
    "min_signal_confidence": 66.0,
    "min_volume_ratio": 1.0,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 6,
    "use_market_regime_filter": False,
    "trend_indicators": [
        # EMA50 displacement OR proximity — same OR group logic as before
        {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
        {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": 0.5,  "max_gap_pct": -0.5}},
        # Hard block: HTF RSI must be genuinely oversold (<38)
        # This is the single most impactful filter from backtest analysis
        {"type": "rsi_overbought", "params": {"min_value": 38, "hard_stop": True}},
    ],
    "min_indicators_required": 2,  # 1 EMA condition + the RSI gate
    "entry_indicators": [
        {"type": "rsi_reversal_momentum", "params": {
            "lookback_candles": 8, "oversold_threshold": 30, "current_min": 30,
            "min_jump": 3.0, "require_sustained": False,
            "sustained_rise_mode": "net", "hard_stop": True,
        }},
        {"type": "price_below_vwap",  "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
        {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
        {"type": "rsi_overbought",    "params": {"min_value": 40}},
        # Tighter volume floor: skip the 0.8-1.0 dead zone
        {"type": "volume_spike",      "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
    ],
    "min_entry_indicators_required": 4,
}

# =============================================================================
# Mean Reversion Short (15m)
# =============================================================================
_PROD_MEAN_REV_SHORT = {
    "display_name": "prod_mean_rev_short",
    "symbols": ["SOL_USDC", "ETH_USDC", "BTC_USDC", "XRP_USDC", "ZEC_USDC"],
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
    "use_trend_filter": True,
    "trend_timeframe": "60",
    "use_entry_filter": True,
    "max_position_hours": 4,
    "use_market_regime_filter": False,
    "trend_indicators": [
        {"type": "price_extended_above_ema", "params": {"ema": 50, "min_gap_pct": 1.5, "max_gap_pct": 8.0}},
        {"type": "price_extended_above_ema", "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 1.0}},
    ],
    "min_indicators_required": 1,
    "entry_indicators": [
        {"type": "rsi_overbought_momentum", "params": {"lookback_candles": 5, "overbought_threshold": 68, "current_max": 65, "min_drop": 4.0, "require_sustained": True, "sustained_fall_mode": "net", "drop_required": True}},
        {"type": "price_above_vwap",        "params": {"min_gap_pct": 0.5, "max_gap_pct": 8.0}},
        {"type": "volume_spike",            "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
        {"type": "bollinger_bands",         "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "max_pct_b": 1.10}},
        {"type": "rsi_overbought",          "params": {"max_value": 35, "side": "short"}},
    ],
    "min_entry_indicators_required": 4,
}

# =============================================================================
# Trend Following Short (15m entry / 60m trend)
# =============================================================================
_PROD_TREND_SHORT = {
    "display_name": "prod_trend_short",
    "symbols": ["ETH_USDC", "BNB_USDC", "ZEC_USDC"],
    "strategy_type": "short_trend_following",
    "entry_timeframe": "15",
    "trend_timeframe": "60",
    "take_profit_pct": 0.8,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 15,
    "min_signal_confidence": 70.0,
    "min_volume_ratio": 1.1,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 12,
    "use_market_regime_filter": False,
    "trend_indicators": [
        {"type": "ema_slope",       "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.015, "hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 1.05}},
        {"type": "adx_regime",      "params": {"min_adx": 22, "max_adx": 60}},
        {"type": "rsi_overbought",  "params": {"max_value": 32, "lookback_candles": 5, "hard_stop": True, "side": "short"}},
    ],
    "min_indicators_required": 3,
    "entry_indicators": [
        {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 0.5}},
        {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.35, "max_pct_b": 0.95}},
        {"type": "rsi_threshold",   "params": {"period": 14, "max_value": 43, "use_momentum": True, "early_threshold": 55, "hard_stop": True}},
        {"type": "rsi_overbought",  "params": {"max_value": 37, "hard_stop": True, "side": "short"}},
        {"type": "price_vs_vwap",   "params": {}},
        {"type": "ema_slope",       "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
    ],
    "min_entry_indicators_required": 5,
}

# =============================================================================
# Exported prod profile set — one entry per live profile
# =============================================================================
PROD_PROFILES = {
    "prod_15m_trend":      _PROD_15M_TREND,
    "4HR_v8":    _4HR_v8,
    "4hr_V11":    _4hr_p3_v11_slope_relaxedAI,
    "4hr_v13": _4hr_v13,
    "_PROD_MEAN_REV_v3":       _PROD_MEAN_REV_v3,
    "prod_mean_rev_short": _PROD_MEAN_REV_SHORT,
    "prod_trend_short":    _PROD_TREND_SHORT,
}
