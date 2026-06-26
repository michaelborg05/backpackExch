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
# 4hr Swing — Profile A: EMA Cross RSI Pullback
# Ticks optimizer iter 3: score=182.36, 23T, 65% WR, 3.29x PF, +18.4% (60d, 5 symbols)
# 4hr: EMA bullish cross (hard) + RSI in 52-63 zone (dual range, both hard). Entry: ADX 22-40 + RSI 28-50.
# =============================================================================
_PROD_4HR_SWING_Simple = {
    "display_name": "prod_4hr_swing_A",
    "symbols": ["SOL_USDC", "ETH_USDC", "BTC_USDC", "XRP_USDC", "BNB_USDC"],
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
    # "trend" mode re-checks 4hr trend indicators on open positions; matches backtest defaults.
    "use_trend_invalidation_exit":      True,
    "trend_invalidation_indicators":    "trend",
    "min_position_age_for_trend_check": 0,
    # 4hr: EMA bullish cross (hard) + RSI in bullish zone 52-63 (dual range, both hard-stop)
    "trend_indicators": [
        {"type": "ema_cross", "params": {"hard_stop": True}},
        {"type": "rsi_range", "params": {"min": 48, "max": 63, "invert": True, "hard_stop": True}},
        {"type": "rsi_range", "params": {"min": 52, "max": 65, "invert": True, "hard_stop": True}},
    ],
    "min_indicators_required": 3,
    # 1hr: ADX 22-40 + RSI pulled back to 28-50 (dual range, both hard-stop)
    "entry_indicators": [
        {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 40}},
        {"type": "rsi_range",  "params": {"min": 30, "max": 52, "invert": True, "hard_stop": True}},
        {"type": "rsi_range",  "params": {"min": 28, "max": 50, "invert": True, "hard_stop": True}},
    ],
    "min_entry_indicators_required": 3,
}

# =============================================================================
# 4hr Swing — Profile B: EMA Cross ADX + Volume Entry
# Ticks optimizer iter 3: score=182.26, 20T, 65% WR, 3.79x PF, +16.0% (60d, 5 symbols)
# 4hr: EMA cross (hard) + ADX 20-32 (hard) + RSI 48-65. Entry: volume spike (hard) + RSI 28-50 + BB + EMA.
# =============================================================================
_PROD_4HR_EMA50Drop = {
    "display_name": "prod_4hr_ema50drop",
    "symbols": ["SOL_USDC", "ETH_USDC", "BTC_USDC", "XRP_USDC", "BNB_USDC"],
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
    "use_trend_invalidation_exit":      True,
    "trend_invalidation_indicators":    "trend",
    "min_position_age_for_trend_check": 0,
    # 4hr: EMA bullish cross (hard) + ADX trend strength 20-32 (hard) + RSI 48-65
    "trend_indicators": [
        {"type": "ema_cross",  "params": {"hard_stop": True}},
        {"type": "adx_regime", "params": {"min_adx": 20, "max_adx": 32, "hard_stop": True}},
        {"type": "rsi_range",  "params": {"min": 48, "max": 65, "invert": True}},
    ],
    "min_indicators_required": 3,
    # 1hr: volume spike 1.2-8x (hard) + RSI 28-50 + BB lower half + price near EMA20; 3 of 4 must pass
    "entry_indicators": [
        {"type": "volume_spike",   "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
        {"type": "rsi_range",      "params": {"min": 28, "max": 50, "invert": True}},
        {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.5}},
        {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 2.0}},
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

_PROD_MEAN_REV_SHORT = {
    
    **_MEAN_REV_SHORT_BASE,
    "display_name": "mrs_v15_optimised",
    "symbols": ["SOL_USDC", "ETH_USDC", "BTC_USDC", "XRP_USDC", "ZEC_USDC"],
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
    "_PROD_4HR_SWING_Simple":    _PROD_4HR_SWING_Simple,    #done
    "_PROD_4HR_EMA50Drop":    _PROD_4HR_EMA50Drop,          #done
    "_PROD_MEAN_REV_v3":       _PROD_MEAN_REV_v3,           #Done
    "prod_mean_rev_short": _PROD_MEAN_REV_SHORT,            #Done
    "prod_trend_short":    _PROD_TREND_SHORT,
}
