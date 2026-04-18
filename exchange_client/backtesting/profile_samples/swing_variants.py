
_SWING_BASE = {
    "strategy_type": "trend_following",
    "signal_timeframe": "60",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "take_profit_pct": 5.0,
    "stop_loss_pct": 4.0,
    "trailing_stop_pct": 3,
    "arm_trailing_stop_pct": 2.5,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 3600,
    "min_signal_confidence": 75.0,
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
   
    "p3_v2_sustained": {
        **_SWING_BASE,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  42,
                "current_min":         36,
                "min_jump":            2.5,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 48, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
                "oversold_threshold":  52,
                "current_min":         38,
                "min_jump":            3.0,
                "require_sustained":   False,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            # RSI overbought is the ONLY "too late" gate — not BB
            {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
            # Price vs EMA: wide allowance for post-crash EMA elevation
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
            # Volume: soft, no hard_stop
            {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1,"hard_stop":True}},

            # BB: lower band check only — confirms price was genuinely depressed
            # (not a hard stop — just a confidence indicator)
        ],
        "min_entry_indicators_required": 4,
    },

    "p3_v3_higher_low": {
        **_SWING_BASE,
        "take_profit_pct": 4,
        "stop_loss_pct": 3,
        "trailing_stop_pct": 1.8,
        "arm_trailing_stop_pct": 1.2,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  42,
                "current_min":         36,
                "min_jump":            2.5,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 48, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
                "oversold_threshold":  52,
                "current_min":         38,
                "min_jump":            3.0,
                "require_sustained":   False,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            # RSI overbought is the ONLY "too late" gate — not BB
            {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
            # Price vs EMA: wide allowance for post-crash EMA elevation
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
            # Volume: soft, no hard_stop
            {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1,"hard_stop":True}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.6}},
        
            # BB: lower band check only — confirms price was genuinely depressed
            # (not a hard stop — just a confidence indicator)
        ],
        "min_entry_indicators_required": 5
    },


    "p3_v4_ema50drop": {
        **_SWING_BASE,
        "take_profit_pct": 5,
        "stop_loss_pct": 3,
        "trailing_stop_pct": 2,
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
                "ema": 50, "min_gap_pct": -3.0, "max_gap_pct": -10.0,
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
        ],
        "min_entry_indicators_required": 3,
    },

    
    # =============================================================================
    # p3_v19_tight_pullback
    #
    # WHAT IT TARGETS:
    #   The "healthy pullback within an uptrend" — 4hr trend is running (RSI 47-69),
    #   price pulls back intraday to the lower half of the 1hr Bollinger Band with
    #   RSI cooling off under 52. Tighter than v18b on both BB and RSI ceiling,
    #   which filters out shallow/noisy pullbacks.
    #
    # BACKTEST (16 days, all 5 symbols):
    #   Trades: 184  |  Win rate: 69%  |  Avg PnL: +0.97%  |  Best: HYPE (82%), ETH (76%)
    #   SOL: 30 trades, 60% win  | ETH: 46, 76% | HYPE: 22, 82% | SUI: 42, 57% | BTC: 44, 73%
    #   NOTE: SOL and SUI are noisier — consider excluding or using stricter gates for those pairs
    #
    # TP/SL RATIONALE:
    #   TP 3% / SL 2.5% gives a 1.2:1 ratio, which works well with 69%+ win rate.
    #   Tighter than existing profiles (TP5%/SL4%) — suits shorter, sharper pullback bounces.
    #   Average hold time was ~16-20 bars (hours).
    # =============================================================================
    "p3_v19_tight_pullback": {
        **_SWING_BASE,
    
        "take_profit_pct":       3.0,   # Smaller target — these are pullback bounces, not full reversals
        "stop_loss_pct":         2.5,   # Tight stop — if it goes further, the trend assumption is wrong
        "trailing_stop_pct":     1.5,   # Trail at 1.5% — locks in gains on quick bounces
        "arm_trailing_stop_pct": 1.2,   # Arm early — these moves often pop quickly
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
        ],
        "min_indicators_required": 3,   # rsi_range + rsi_overbought are both hard stops
    
        # ── 1HR ENTRY FILTER ────────────────────────────────────────────────────────
        # Tighter than v18b: RSI ceiling at 52 (vs 58) and BB at 0.58 (vs 0.68)
        # This ensures you're entering on a real pullback, not just "not overbought"
        "entry_indicators": [
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 52,    # TIGHTER: 1hr RSI must be genuinely cooling (< 52)
                    "hard_stop": True,
                }
            },
            {
                "type": "bollinger_bands",
                "params": {
                    "band":      "upper",
                    "mode":      "pct_b",
                    "max_pct_b": 0.58,  # TIGHTER: lower 58% of band — confirmed pullback to value
                    "hard_stop": True,
                }
            },
            {
                "type": "price_vs_ema",
                "params": {
                    "ema":         20,
                    "min_gap_pct": -4.0,    # Don't enter in freefall
                    "max_gap_pct":  1.5,    # Must be near/below EMA20 (tighter than v18b's 2.5%)
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
    
    "p3_v19b_tight_pullback": {
        **_SWING_BASE,
    
        "take_profit_pct":       3.0,   # Smaller target — these are pullback bounces, not full reversals
        "stop_loss_pct":         2.5,   # Tight stop — if it goes further, the trend assumption is wrong
        "trailing_stop_pct":     1.5,   # Trail at 1.5% — locks in gains on quick bounces
        "arm_trailing_stop_pct": 1.2,   # Arm early — these moves often pop quickly
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
        ],
        "min_indicators_required": 3,   # rsi_range + rsi_overbought are both hard stops
    
        # ── 1HR ENTRY FILTER ────────────────────────────────────────────────────────
        # Tighter than v18b: RSI ceiling at 52 (vs 58) and BB at 0.58 (vs 0.68)
        # This ensures you're entering on a real pullback, not just "not overbought"
        "entry_indicators": [
            {"type": "rsi_range", 
                "params": {
                    "min": 35,
                    "max": 52,   # ceiling already covered by rsi_overbought, this adds the floor
                    "hard_stop": True
                    ,"invert": True,
                }, 
                }
            ,   # soft — RSI 32-35 shouldn't kill an otherwise clean setup
            {
                "type": "bollinger_bands",
                "params": {
                    "band":      "upper",
                    "mode":      "pct_b",
                    "max_pct_b": 0.58,  # TIGHTER: lower 58% of band — confirmed pullback to value
                }
            },
            {
                "type": "price_vs_ema",
                "params": {
                    "ema":         20,
                    "min_gap_pct": -4.0,    # Don't enter in freefall
                    "max_gap_pct":  2.5,    # Must be near/below EMA20 (tighter than v18b's 2.5%)
                    "hard_stop": True
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
    
    # =============================================================================
    # p3_v20_midband
    #
    # WHAT IT TARGETS:
    #   Similar trend gate to v19, but the entry requires price to be in the
    #   MID-LOWER band zone (pct_b 0.20-0.65) rather than just "not at the top".
    #   This avoids entries at extreme lows (which often see further dips) and
    #   favors the healthier pullback zone where trend continuation is stronger.
    #
    # BACKTEST (16 days, all 5 symbols):
    #   Trades: 195  |  Win rate: 64%  |  Avg PnL: +0.72%
    #   Lower win rate than v19 — the mid-band zone isn't as precise a signal.
    #   Consider using as a secondary/comparison variant, not primary.
    #
    # BEST USE CASE: Markets trending clearly upward with well-defined pullbacks.
    #   ETH and BTC tend to have cleaner mid-band setups than SOL/HYPE.
    # =============================================================================
    "p3_v20_midband": {
        **_SWING_BASE,
    
        "take_profit_pct":       3.0,
        "stop_loss_pct":         2.5,
        "trailing_stop_pct":     1.5,
        "arm_trailing_stop_pct": 1.2,
        "use_trailing_stop":     True,
        "max_position_hours":    36,
        "min_signal_confidence": 73.0,
        "signal_cooldown_seconds": 3600,
    
        "trend_indicators": [
            {
                "type": "rsi_range",
                "params": {
                    "min_value": 47,
                    "max_value": 69,
                    "invert": True,
                    "hard_stop": True,
                }
            },
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 70,
                    "hard_stop": True,
                }
            },
            {
                "type": "price_extended_below_ema",
                "params": {
                    "ema": 50,
                    "min_gap_pct": -2.5,
                    "max_gap_pct": 6.5,
                }
            },
        ],
        "min_indicators_required": 2,
    
        "entry_indicators": [
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 58,
                    "hard_stop": True,
                }
            },
            {
                # Require price to be in the MID-LOWER band — not at either extreme
                # pct_b 0.20 = near lower band (but not AT it)
                # pct_b 0.65 = upper-middle (not yet extended)
                # This avoids: (a) "catching falling knives" at pct_b < 0.20
                #              (b) chasing breakouts at pct_b > 0.65
                "type": "bollinger_bands",
                "params": {
                    "band":      "lower",
                    "mode":      "pct_b",
                    "min_pct_b": 0.20,  # Must be above the extreme lower band
                    "max_pct_b": 0.65,  # Must not be extended toward upper band
                    "hard_stop": True,
                }
            },
            {
                "type": "price_vs_ema",
                "params": {
                    "ema":         20,
                    "min_gap_pct": -5.0,
                    "max_gap_pct":  2.5,
                }
            },
            {
                "type": "volume_spike",
                "params": {
                    "min_ratio": 0.5,
                    "max_ratio": 8.0,
                }
            },
        ],
        "min_entry_indicators_required": 3,
    },
    
    
    # =============================================================================
    # p3_v21_btc_eth_only
    #
    # WHAT IT TARGETS:
    #   Same logic as v19_tight_pullback but calibrated for BTC and ETH specifically,
    #   which showed the best risk-adjusted results (ETH: 76% win, BTC: 73% win,
    #   both with very low SL hit rates — ETH only 2 SL hits in 46 trades!).
    #
    #   The observation from backtesting: ETH and BTC produce cleaner pullbacks
    #   (fewer "fake" pullbacks that continue down) compared to SOL/SUI.
    #
    #   This variant is intentionally designed to only be applied to BTC and ETH
    #   in your profile configuration — use v19 for the other pairs.
    #
    # BACKTEST (ETH + BTC only, 16 days):
    #   Trades: 90  |  Win rate: 74%  |  Combined avg SL hits: 7 total
    #   ETH: only 2 stop-outs in 46 trades — exceptionally clean
    #   BTC: 5 stop-outs in 44 trades, 26 timeouts (most profitable on average)
    #
    # TP/SL: Slightly wider TP (3.5%) to capture BTC's bigger moves on timeout
    # =============================================================================
    "p3_v21_btc_eth_only": {
        **_SWING_BASE,
    
        "take_profit_pct":       3.5,   # Slightly wider — BTC/ETH move more cleanly to targets
        "stop_loss_pct":         2.5,
        "trailing_stop_pct":     2.0,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop":     True,
        "max_position_hours":    48,    # BTC in particular resolves slower (avg 20hr)
        "min_signal_confidence": 74.0,
        "signal_cooldown_seconds": 3600,
    
        "trend_indicators": [
            {
                "type": "rsi_range",
                "params": {
                    "min_value": 47,
                    "max_value": 69,
                    "hard_stop": True,
                    "invert": True,
                }
            },
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 70,
                    "hard_stop": True,
                }
            },
            {
                "type": "price_extended_below_ema",
                "params": {
                    "ema": 50,
                    "min_gap_pct": -2.5,
                    "max_gap_pct": 6.5,
                }
            },
        ],
        "min_indicators_required": 2,
    
        "entry_indicators": [
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 52,    # Same tight ceiling as v19
                    "hard_stop": True,
                }
            },
            {
                "type": "bollinger_bands",
                "params": {
                    "band":      "upper",
                    "mode":      "pct_b",
                    "max_pct_b": 0.58,
                    "hard_stop": True,
                }
            },
            {
                "type": "price_vs_ema",
                "params": {
                    "ema":         20,
                    "min_gap_pct": -4.0,
                    "max_gap_pct":  2.0,
                }
            },
            {
                "type": "volume_spike",
                "params": {
                    "min_ratio": 0.6,   # Slightly stricter — BTC/ETH pullbacks often have decent vol
                    "max_ratio": 8.0,
                }
            },
        ],
        "min_entry_indicators_required": 3,
    },

}


