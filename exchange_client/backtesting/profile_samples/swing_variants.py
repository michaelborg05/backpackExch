
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
    "min_volume_ratio": 1.0,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 72,
    "use_market_regime_filter": False,
    # Trend invalidation enabled — the optimizer ran with this as the engine default (True).
    # These configs were tuned WITH exit logic active, so disabling it degrades performance.
    "use_trend_invalidation_exit": True,
}

SWING_VARIANTS = {

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

    # ── Previous profiles (kept for reference) ─────────────────────────────────

    # "p3_v5_ema50drop": candle-mode optimised (91% WR was candle artefact — ticks shows ~50%). Retired.
    # "p3_v6_bullish_pullback": candle-mode optimised (ema_slope + rsi_range + adx). Retired.

    # "p3_base": {
    #     **_SWING_BASE,
    #     "take_profit_pct": 3,
    #     "stop_loss_pct": 2,
    #     "trailing_stop_pct": 1,
    #     "arm_trailing_stop_pct": 1.0,
    #     "use_trailing_stop": True,
    #     "trend_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    6,
    #             "oversold_threshold":  36,
    #             "current_min":         34,
    #             "min_jump":            2.5,
    #             "require_sustained":   True,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         {"type": "rsi_overbought", "params": {"min_value": 54, "hard_stop": True}},
    #         {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 5.0}},
    #         {"type": "volume_spike",   "params": {"min_ratio": 0.5, "max_ratio": 8.0}},
    #         {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b","max_pct_b":0.88,"hard_stop":True}},
    #     ],
    #     "min_entry_indicators_required": 3,
    # },

    # "p3_v4_ema50drop": {
    #     **_SWING_BASE,
    #     "take_profit_pct": 3.5,
    #     "stop_loss_pct": 2,
    #     "trailing_stop_pct": 1.3,
    #     "arm_trailing_stop_pct": 1.5,
    #     "use_trailing_stop": False,
    #     "min_signal_confidence": 70.0,
    #     "trend_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles": 6, "oversold_threshold": 35, "current_min": 30,
    #             "min_jump": 2.5, "require_sustained": False, "sustained_rise_mode": "net", "hard_stop": True,
    #         }},
    #         {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -3.5, "max_gap_pct": -10.0}},
    #         {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 3,
    #     "entry_indicators": [
    #         {"type": "rsi_overbought", "params": {"min_value": 60, "hard_stop": True}},
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles": 5, "oversold_threshold": 45, "current_min": 33,
    #             "min_jump": 3.0, "require_sustained": True, "sustained_rise_mode": "net", "hard_stop": True,
    #         }},
    #         {"type": "price_vs_ema", "params": {"ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 2.0}},
    #         {"type": "adx_regime",   "params": {"min_adx": 0, "max_adx": 30, "hard_stop": True}},
    #     ],
    #     "min_entry_indicators_required": 3,
    # },
}
