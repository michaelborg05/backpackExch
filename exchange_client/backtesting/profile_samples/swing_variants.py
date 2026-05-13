
_SWING_BASE = {
    "strategy_type": "trend_following",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "take_profit_pct": 3,
    "stop_loss_pct": 2,
    "trailing_stop_pct": 1.2,
    "arm_trailing_stop_pct": 1.2,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 120,
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
    "p3_v19_tight_pullback-groups": {
        **_SWING_BASE,

        "take_profit_pct":       1.5,   # Smaller target — these are pullback bounces, not full reversals
        "stop_loss_pct":         1,   # Tight stop — if it goes further, the trend assumption is wrong
        "trailing_stop_pct":     0.7,   # Trail at 1.5% — locks in gains on quick bounces
        "arm_trailing_stop_pct": 0.7,   # Arm early — these moves often pop quickly
        "use_trailing_stop":     True,
        "max_position_hours":    36,    # Tighter time limit — pullback bounces should resolve in 36hr
        "min_signal_confidence": 73.0,
        "signal_cooldown_minutes": 60,

        # ── 4HR TREND FILTER ───────────────────────────────────────────────────────
        # Confirms the 4hr trend is in the bullish momentum zone (47-69 RSI)
        # and price hasn't extended too far above EMA50 (not chasing)
        #
        # extension_check group (OR, hard_stop=True):
        #   Block ONLY if BOTH RSI > 60 AND EMA50 gap > 3% at the same time.
        #   Either condition alone is not reliable enough to hard-block.
        #   Previously rsi_range was a standalone hard stop (RSI > 60 = block always),
        #   which caused too many false negatives on valid entries.
        "trend_indicators": [
            {
                # Group member: extension_check (OR)
                # Passes when 4hr RSI is in [47, 60] — i.e. not extended
                "type": "rsi_range",
                "indicator_group": "extension_check",
                "params": {
                    "min": 47,
                    "max": 55,
                    "invert": True,
                }
            },
            {
                # Group member: extension_check (OR)
                # Passes when price is within -2.5% to +3% of EMA50
                "type": "price_vs_ema",
                "indicator_group": "extension_check",
                "params": {
                    "ema": 50,
                    "min_gap_pct": -2.5,
                    "max_gap_pct": 1.5,
                }
            },
            {
                # Ungrouped hard stop — absolute block if RSI ≥ 70 (extreme overbought)
                "type": "rsi_range",
                "params": {
                    "min": 40,
                    "max": 65,
                    "invert": True,
                    "hard_stop": True,
                }
            },
            {
                # Ungrouped soft — ADX regime confirmation
                "type": "adx_regime",
                "params": {
                    "min_adx": 10,
                    "max_adx": 27,
                }
            },
        ],
        # 3 logical units: extension_check group + rsi_overbought (ungrouped) + adx_regime (ungrouped)
        "min_indicators_required": 3,

        # Group config: OR logic means group passes if EITHER rsi_range OR price_vs_ema passes.
        # hard_stop=True means if BOTH fail (both extended simultaneously), block immediately.
        "trend_indicator_groups": {
            "extension_check": {"require_all": False, "hard_stop": True},
        },
    
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

    "p3_v20_tight_pullback": {
        **_SWING_BASE,
    
        "take_profit_pct":       1.5,   # Smaller target — these are pullback bounces, not full reversals
        "stop_loss_pct":         1,   # Tight stop — if it goes further, the trend assumption is wrong
        "trailing_stop_pct":     0.7,   # Trail at 1.5% — locks in gains on quick bounces
        "arm_trailing_stop_pct": 0.7,   # Arm early — these moves often pop quickly
        "use_trailing_stop":     True,
        "max_position_hours":    36,    # Tighter time limit — pullback bounces should resolve in 36hr
        "min_signal_confidence": 73.0,
        "signal_cooldown_minutes": 60,
    
        # ── 4HR TREND FILTER ───────────────────────────────────────────────────────
        # Confirms the 4hr trend is in the bullish momentum zone (47-69 RSI)
        # and price hasn't extended too far above EMA50 (not chasing)
        "trend_indicators": [
            {
                "type": "rsi_range",
                "params": {
                    "min": 47,    # 4hr RSI must be in bullish zone — not oversold, not peaked
                    "max": 60,    # block overbought trends (blow-off risk)
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
    "p3_v21_tight_pullback-groups2": {
        **_SWING_BASE,

        "take_profit_pct":       1.5,   # Smaller target — these are pullback bounces, not full reversals
        "stop_loss_pct":         1,   # Tight stop — if it goes further, the trend assumption is wrong
        "trailing_stop_pct":     0.7,   # Trail at 1.5% — locks in gains on quick bounces
        "arm_trailing_stop_pct": 0.7,   # Arm early — these moves often pop quickly
        "use_trailing_stop":     True,
        "max_position_hours":    36,    # Tighter time limit — pullback bounces should resolve in 36hr
        "min_signal_confidence": 73.0,
        "signal_cooldown_minutes": 60,

        # ── 4HR TREND FILTER ───────────────────────────────────────────────────────
        # Confirms the 4hr trend is in the bullish momentum zone (47-69 RSI)
        # and price hasn't extended too far above EMA50 (not chasing)
        #
        # extension_check group (OR, hard_stop=True):
        #   Block ONLY if BOTH RSI > 60 AND EMA50 gap > 3% at the same time.
        #   Either condition alone is not reliable enough to hard-block.
        #   Previously rsi_range was a standalone hard stop (RSI > 60 = block always),
        #   which caused too many false negatives on valid entries.
        "trend_indicators": [
            {
                # Group member: extension_check (OR)
                # Passes when 4hr RSI is in [47, 60] — i.e. not extended
                "type": "rsi_range",
                "indicator_group": "extension_check",
                "params": {
                    "min": 47,
                    "max": 55,
                    "invert": True,
                }
            },
            {
                # Group member: extension_check (OR)
                # Passes when price is within -2.5% to +3% of EMA50
                "type": "price_vs_ema",
                "indicator_group": "extension_check",
                "params": {
                    "ema": 50,
                    "min_gap_pct": -2.5,
                    "max_gap_pct": 1,
                }
            },
            {
                # Ungrouped hard stop — absolute block if RSI ≥ 70 (extreme overbought)
                "type": "rsi_range",
                "params": {
                    "min": 40,
                    "max": 65,
                    "invert": True,
                    "hard_stop": True,
                }
            },
            {
                # Ungrouped soft — ADX regime confirmation
                "type": "adx_regime",
                "params": {
                    "min_adx": 14,
                    "max_adx": 27,
                }
            },
        ],
        # 3 logical units: extension_check group + rsi_overbought (ungrouped) + adx_regime (ungrouped)
        "min_indicators_required": 3,

        # Group config: OR logic means group passes if EITHER rsi_range OR price_vs_ema passes.
        # hard_stop=True means if BOTH fail (both extended simultaneously), block immediately.
        "trend_indicator_groups": {
            "extension_check": {"require_all": False, "hard_stop": True},
        },
    
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


