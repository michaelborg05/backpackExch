_SWING_BASE = {
    "strategy_type": "trend_following",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "take_profit_pct": 3,
    "stop_loss_pct": 2,
    "trailing_stop_pct": 1,
    "arm_trailing_stop_pct": 1.0,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 241,
    "min_signal_confidence": 74.0,
    "min_volume_ratio": 1.3,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 72,
    "use_market_regime_filter": False,
    # Trend invalidation exit — mirrors production position_manager behaviour.
    # mode "trend": re-check 4hr trend indicators (catches big structural reversals).
    # mode "entry": re-check 1hr entry conditions (faster but noisier).
    # mode "exit":  use dedicated exit_indicators (most targeted).
    "use_trend_invalidation_exit":      True,
    "trend_invalidation_indicators":    "entry",  # default: 4hr trend indicators
    "min_position_age_for_trend_check": 241,        # minutes; 0 = check immediately
    # Exit indicators: "has the trade broken down?" rather than "can I enter?"
    # These are used when trend_invalidation_indicators="exit".
    "exit_indicators": [
        # RSI drops back below 48 → 1hr momentum is gone
        {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 45, "use_momentum": False, "hard_stop": True}},
        # Price closes below 1hr EMA20 → short-term structure broken
        {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -100.0, "max_gap_pct": 0.0, "hard_stop": True}},
        # BB %B drops below 0.35 → price retreating to lower half of bands
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35, "hard_stop": True}},
    ],
    "min_exit_indicators_required": 2,
    "exit_timeframe": "60",
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
    "trend_indicators": [
        {"type": "rsi_reversal_momentum", "params": {
            "lookback_candles":    6,
            "oversold_threshold":  36,
            "current_min":         34,
            "min_jump":            2.5,
            "require_sustained":   True,
            "sustained_rise_mode": "net",
            "hard_stop":           True,
        }},
        {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
    ],
    "min_indicators_required": 2,
    "entry_indicators": [
        {"type": "rsi_overbought", "params": {"min_value": 54, "hard_stop": True}},
        # Price vs EMA: wide allowance for post-crash EMA elevation
        {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 5.0}},
        # Volume: soft, no hard_stop
        {"type": "volume_spike",   "params": {"min_ratio": 0.5, "max_ratio": 8.0}},
        {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":0.88,"hard_stop":True}},
    ],
    "min_entry_indicators_required": 3,
}

SWING_VARIANTS = {
    "p3_base" : _SWING_BASE,
   
    # Actual profile in use
    "p3_v4_ema50drop": {
        **_SWING_BASE,
        "take_profit_pct": 3.5,
        "stop_loss_pct": 2,
        "trailing_stop_pct": 1.3,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": False,
        "min_signal_confidence": 70.0,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6,     # 24h — captures full slow-grind pattern
                "oversold_threshold": 35,  # SUI 240m hit 32.9
                "current_min": 30,
                "min_jump": 2.5,           # SUI only had 3.1 max jump across 4h candles
                "require_sustained": False,
                "sustained_rise_mode": "net",  # net allows dip-then-higher (ETH pattern)
                "hard_stop": True,
            }},
            {"type": "price_extended_below_ema", "params": {
                "ema": 50, "min_gap_pct": -3.5, "max_gap_pct": -10.0,
            }},

            {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 60, "hard_stop": True}},
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,   # SOL fix: need to reach across 4h candle boundary
                "oversold_threshold":  45,
                "current_min":         33,
                "min_jump":            3.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "price_vs_ema", "params": {
                "ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 2.0,
            }},
            { "type": "adx_regime",
                "params": {
                    "min_adx": 0,
                    "max_adx": 30,    
                    "hard_stop":           True
                }},
        ],
        "min_entry_indicators_required": 3,
    },

    # ── Profile 1: EMA Cross RSI Pullback ──────────────────────────────────────
    # Ticks optimizer iter 3 champion: score=182.36, 23T, 65% WR, 3.29x PF, +18.4% (60d, 5 symbols)
    # Market: 4hr EMA cross bullish + RSI in bullish zone (52-63). Enter on 1hr pullback
    # where RSI dips to 28-50 (both ranges must agree). ADX 22-40 confirms entry momentum.
    # No ADX required in trend — RSI zone acts as the selectivity filter.
    "p3_v7_rsi_pullback": {
        **_SWING_BASE,
        "take_profit_pct": 3.0,
        "stop_loss_pct": 2.0,
        "trailing_stop_pct": 1.2,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 241,

        # 4hr: EMA bullish cross (hard) + RSI in bullish zone 52-63 (both ranges hard-stop)
        "trend_indicators": [
            {"type": "ema_cross",  "params": {"hard_stop": True}},
            {"type": "rsi_range",  "params": {"min": 48, "max": 63, "invert": True, "hard_stop": True}},
            {"type": "rsi_range",  "params": {"min": 52, "max": 65, "invert": True, "hard_stop": True}},
        ],
        "min_indicators_required": 3,

        # 1hr: ADX in momentum zone (22-40) + RSI pulled back to 28-50 (both ranges hard-stop)
        "entry_indicators": [
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 40}},
            {"type": "rsi_range",  "params": {"min": 30, "max": 52, "invert": True, "hard_stop": True}},
            {"type": "rsi_range",  "params": {"min": 28, "max": 50, "invert": True, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
    },

    # ── Profile 2: EMA Cross ADX + Volume Entry ────────────────────────────────
    # Ticks optimizer iter 3 champion: score=182.26, 20T, 65% WR, 3.79x PF, +16.0% (60d, 5 symbols)
    # Market: 4hr EMA cross bullish + ADX in strong-but-not-extreme trend (20-32) + RSI 48-65.
    # Enter on 1hr pullback with volume spike (crowd re-entry) + RSI 28-50 + BB/EMA confirmation.
    # Volume spike as hard-stop on entry differentiates this profile from p3_v7.
    "p3_v8_vol_pullback": {
        **_SWING_BASE,
        "take_profit_pct": 3.0,
        "stop_loss_pct": 2.0,
        "trailing_stop_pct": 1.2,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 241,

        # 4hr: EMA bullish cross (hard) + ADX trend strength 20-32 (hard) + RSI 48-65
        "trend_indicators": [
            {"type": "ema_cross",  "params": {"hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 20, "max_adx": 32, "hard_stop": True}},
            {"type": "rsi_range",  "params": {"min": 48, "max": 65, "invert": True}},
        ],
        "min_indicators_required": 3,

        # 1hr: volume spike 1.2-8x (crowd re-entry, hard) + RSI 28-50 + BB in lower half + price near EMA20
        # 3 of 4 must pass; volume_spike is the non-negotiable hard gate
        "entry_indicators": [
            {"type": "volume_spike",   "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
            {"type": "rsi_range",      "params": {"min": 28, "max": 50, "invert": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.5}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 2.0}},
        ],
        "min_entry_indicators_required": 3,
    },

}