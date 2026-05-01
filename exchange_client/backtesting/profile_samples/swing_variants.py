
_SWING_BASE = {
    "strategy_type": "trend_following",
    "signal_timeframe": "60",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "take_profit_pct": 3,
    "stop_loss_pct": 2,
    "trailing_stop_pct": 1.2,
    "arm_trailing_stop_pct": 1.2,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 7500,
    "min_signal_confidence": 74.0,
    "min_volume_ratio": 1.3,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 72,
    "use_market_regime_filter": False,
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
   
    "p3_v3_ranging4hr": {
        **_SWING_BASE,
        "take_profit_pct": 1.5,
        "stop_loss_pct": 1,
        "trailing_stop_pct": 1,
        "arm_trailing_stop_pct": 0.6,
        "trend_indicators": [
            {
                # Price within reasonable distance of EMA50 — not over-extended
                "type": "adx_regime",
                "params": {
                    "min_adx": 10,
                    "max_adx": 22,    
                }
            },
            {
                "type": "rsi_range",
                "params": {
                    "min_value": 40,    # 4hr RSI must be in bullish zone — not oversold, not peaked
                    "max_value": 58,    # block overbought trends (blow-off risk)
                    "invert": True,
                    "hard_stop": True,
                }
            },
            {
                # Price within reasonable distance of EMA50 — not over-extended
                "type": "price_vs_ema",
                "params": {
                    "ema": 50,
                    "min_gap_pct": -2,    # Allow slight dips (false breaks)
                    "max_gap_pct": 2,     # Block if price has run >6.5% above EMA50
                }
            },

        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":0.35,"hard_stop":True}},
            {
                "type": "rsi_range",
                "params": {
                    "min_value": 35,    # 4hr RSI must be in bullish zone — not oversold, not peaked
                    "max_value": 48,    # block overbought trends (blow-off risk)
                    "invert": True,
                    "hard_stop": True,
                }
            },
        ],
        "min_entry_indicators_required": 2
    },

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
                }},
        ],
        "min_entry_indicators_required": 3,
    },

    #23rd April - This is the new v19 in use
    "p3_v19_tight_pullback": {
        **_SWING_BASE,
    
        "take_profit_pct":       1.5,   # Smaller target — these are pullback bounces, not full reversals
        "stop_loss_pct":         1,   # Tight stop — if it goes further, the trend assumption is wrong
        "trailing_stop_pct":     0.7,   # Trail at 1.5% — locks in gains on quick bounces
        "arm_trailing_stop_pct": 0.7,   # Arm early — these moves often pop quickly
        "use_trailing_stop":     True,
        "max_position_hours":    36,    # Tighter time limit — pullback bounces should resolve in 36hr
        "min_signal_confidence": 73.0,
        "signal_cooldown_seconds": 3600,
    
        # ── 4HR TREND FILTER ───────────────────────────────────────────────────────
        # Confirms the 4hr trend is in the bullish momentum zone (47-69 RSI)
        # and price hasn't extended too far above EMA50 (not chasing)
        "trend_indicators": [
            {
                "type": "rsi_range",
                "params": {
                    "min_value": 47,    # 4hr RSI must be in bullish zone — not oversold, not peaked
                    "max_value": 60,    # block overbought trends (blow-off risk)
                    "invert": True,
                    "hard_stop": True,
                }
            },
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 70,    # Belt-and-suspenders: block RSI ≥ 70 explicitly
                    "lookback_candles": 8,
                    "hard_stop": True,
                }
            },
            {
                # Price within reasonable distance of EMA50 — not over-extended
                "type": "price_vs_ema",
                "params": {
                    "ema": 50,
                    "min_gap_pct": -2.5,    # Allow slight dips (false breaks)
                    "max_gap_pct": 3,     # Block if price has run >6.5% above EMA50
                }
            },
            {
                # Price within reasonable distance of EMA50 — not over-extended
                "type": "adx_regime",
                "params": {
                    "min_adx": 10,
                    "max_adx": 27,    
                }
            },
        ],
        "min_indicators_required": 4,   # rsi_range + rsi_overbought are both hard stops
    
        # ── 1HR ENTRY FILTER ────────────────────────────────────────────────────────
        # Tighter than v18b: RSI ceiling at 52 (vs 58) and BB at 0.58 (vs 0.68)
        # This ensures you're entering on a real pullback, not just "not overbought"
        "entry_indicators": [
            {
                "type": "rsi_range",
                "params": {
                    "min": 35,    # TIGHTER: 1hr RSI must be genuinely cooling (< 52)
                    "max": 52,    # TIGHTER: 1hr RSI must be genuinely cooling (< 52)
                    "invert": True,
                    "hard_stop": True,
                }
            },
            {
                "type": "bollinger_bands",
                "params": {
                    "band":      "upper",
                    "mode":      "pct_b",
                    "min_pct_b": 0.1,  # TIGHTER: lower 58% of band — confirmed pullback to value
                    "max_pct_b": 0.58,  # TIGHTER: lower 58% of band — confirmed pullback to value
                }
            },
            {
                "type": "price_vs_ema",
                "params": {
                    "ema":         20,
                    "min_gap_pct": -4.0,    # Don't enter in freefall
                    "max_gap_pct":  2.5,    # Must be near/below EMA20 (tighter than v18b's 2.5%)
                }
            },
            {
                "type": "volume_spike",
                "params": {
                    "min_ratio": 0.5,   # Soft lower bound — pullbacks can have quiet volume
                    "max_ratio": 8.0,
                }
            },
        ],
        "min_entry_indicators_required": 3,
    },

    "p3_v20_tight_pullback-mod": {
        **_SWING_BASE,
    
        "take_profit_pct":       1.5,   # Smaller target — these are pullback bounces, not full reversals
        "stop_loss_pct":         1,   # Tight stop — if it goes further, the trend assumption is wrong
        "trailing_stop_pct":     0.7,   # Trail at 1.5% — locks in gains on quick bounces
        "arm_trailing_stop_pct": 0.7,   # Arm early — these moves often pop quickly
        "use_trailing_stop":     True,
        "max_position_hours":    36,    # Tighter time limit — pullback bounces should resolve in 36hr
        "min_signal_confidence": 73.0,
        "signal_cooldown_seconds": 3600,
    
        # ── 4HR TREND FILTER ───────────────────────────────────────────────────────
        # Confirms the 4hr trend is in the bullish momentum zone (47-69 RSI)
        # and price hasn't extended too far above EMA50 (not chasing)
        "trend_indicators": [
            {
                "type": "rsi_range",
                "params": {
                    "min_value": 47,    # 4hr RSI must be in bullish zone — not oversold, not peaked
                    "max_value": 55,    # block overbought trends (blow-off risk)
                    "invert": True,
                    "hard_stop": True,
                }
            },
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 70,    # Belt-and-suspenders: block RSI ≥ 70 explicitly
                    "lookback_candles": 8,
                    "hard_stop": True,
                }
            },
            {
                # Price within reasonable distance of EMA50 — not over-extended
                "type": "price_vs_ema",
                "params": {
                    "ema": 50,
                    "min_gap_pct": -2.5,    # Allow slight dips (false breaks)
                    "max_gap_pct": 1,     # Block if price has run >6.5% above EMA50
                }
            },
            {
                # Price within reasonable distance of EMA50 — not over-extended
                "type": "adx_regime",
                "params": {
                    "min_adx": 10,
                    "max_adx": 27,    
                }
            },
        ],
        "min_indicators_required": 4,   # rsi_range + rsi_overbought are both hard stops
    
        # ── 1HR ENTRY FILTER ────────────────────────────────────────────────────────
        # Tighter than v18b: RSI ceiling at 52 (vs 58) and BB at 0.58 (vs 0.68)
        # This ensures you're entering on a real pullback, not just "not overbought"
        "entry_indicators": [
            {
                "type": "rsi_range",
                "params": {
                    "min": 35,    # TIGHTER: 1hr RSI must be genuinely cooling (< 52)
                    "max": 52,    # TIGHTER: 1hr RSI must be genuinely cooling (< 52)
                    "invert": True,
                    "hard_stop": True,
                }
            },
            {
                "type": "bollinger_bands",
                "params": {
                    "band":      "upper",
                    "mode":      "pct_b",
                    "min_pct_b": 0.1,  # TIGHTER: lower 58% of band — confirmed pullback to value
                    "max_pct_b": 0.58,  # TIGHTER: lower 58% of band — confirmed pullback to value
                }
            },
            {
                "type": "price_vs_ema",
                "params": {
                    "ema":         20,
                    "min_gap_pct": -4.0,    # Don't enter in freefall
                    "max_gap_pct":  2.5,    # Must be near/below EMA20 (tighter than v18b's 2.5%)
                }
            },
            {
                "type": "volume_spike",
                "params": {
                    "min_ratio": 0.5,   # Soft lower bound — pullbacks can have quiet volume
                    "max_ratio": 8.0,
                }
            },
        ],
        "min_entry_indicators_required": 3,
    },
    "p3_v21_tight_pullback-mod": {
        **_SWING_BASE,
    
        "take_profit_pct":       1.5,   # Smaller target — these are pullback bounces, not full reversals
        "stop_loss_pct":         1,   # Tight stop — if it goes further, the trend assumption is wrong
        "trailing_stop_pct":     0.7,   # Trail at 1.5% — locks in gains on quick bounces
        "arm_trailing_stop_pct": 0.7,   # Arm early — these moves often pop quickly
        "use_trailing_stop":     True,
        "max_position_hours":    36,    # Tighter time limit — pullback bounces should resolve in 36hr
        "min_signal_confidence": 73.0,
        "signal_cooldown_seconds": 3600,
    
        # ── 4HR TREND FILTER ───────────────────────────────────────────────────────
        # Confirms the 4hr trend is in the bullish momentum zone (47-69 RSI)
        # and price hasn't extended too far above EMA50 (not chasing)
        "trend_indicators": [
            {
                "type": "rsi_range",
                "params": {
                    "min_value": 47,    # 4hr RSI must be in bullish zone — not oversold, not peaked
                    "max_value": 55,    # block overbought trends (blow-off risk)
                    "invert": True,
                    "hard_stop": True,
                }
            },
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 70,    # Belt-and-suspenders: block RSI ≥ 70 explicitly
                    "lookback_candles": 8,
                    "hard_stop": True,
                }
            },
            {
                # Price within reasonable distance of EMA50 — not over-extended
                "type": "price_vs_ema",
                "params": {
                    "ema": 50,
                    "min_gap_pct": -2.5,    # Allow slight dips (false breaks)
                    "max_gap_pct": 1.5,     # Block if price has run >6.5% above EMA50
                }
            },
            {
                # Price within reasonable distance of EMA50 — not over-extended
                "type": "adx_regime",
                "params": {
                    "min_adx": 10,
                    "max_adx": 27,    
                }
            },
        ],
        "min_indicators_required": 4,   # rsi_range + rsi_overbought are both hard stops
    
        # ── 1HR ENTRY FILTER ────────────────────────────────────────────────────────
        # Tighter than v18b: RSI ceiling at 52 (vs 58) and BB at 0.58 (vs 0.68)
        # This ensures you're entering on a real pullback, not just "not overbought"
        "entry_indicators": [
            {
                "type": "rsi_range",
                "params": {
                    "min": 35,    # TIGHTER: 1hr RSI must be genuinely cooling (< 52)
                    "max": 52,    # TIGHTER: 1hr RSI must be genuinely cooling (< 52)
                    "invert": True,
                    "hard_stop": True,
                }
            },
            {
                "type": "bollinger_bands",
                "params": {
                    "band":      "upper",
                    "mode":      "pct_b",
                    "min_pct_b": 0.1,  # TIGHTER: lower 58% of band — confirmed pullback to value
                    "max_pct_b": 0.58,  # TIGHTER: lower 58% of band — confirmed pullback to value
                }
            },
            {
                "type": "price_vs_ema",
                "params": {
                    "ema":         20,
                    "min_gap_pct": -4.0,    # Don't enter in freefall
                    "max_gap_pct":  2.5,    # Must be near/below EMA20 (tighter than v18b's 2.5%)
                }
            },
            {
                "type": "volume_spike",
                "params": {
                    "min_ratio": 0.5,   # Soft lower bound — pullbacks can have quiet volume
                    "max_ratio": 8.0,
                }
            },
        ],
        "min_entry_indicators_required": 3,
    },


}


