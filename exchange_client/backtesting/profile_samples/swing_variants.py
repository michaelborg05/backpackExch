
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

    # -------------------------------------------------------------------------
    # V13: RAISED BB THRESHOLD + EXTENDED LOOKBACK
    #
    # Rather than removing BB entirely, raise the pct_b hard stop from 0.85
    # to 1.10 — price must actually be 10% above the BB upper to be blocked.
    # In a post-crash recovery this is the real "extended" zone. At pct_b 0.85–
    # 1.05 the price is just catching up to the mean, not truly overbought.
    #
    # Also: extend 60m rsi_reversal lookback to 15 candles (15 hours) to
    # reliably find the original crash event from across the 4h candle.
    # -------------------------------------------------------------------------
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

    "p3_v18_momentum_continuation": {
        **_SWING_BASE,
 
        # ── TP/SL ──────────────────────────────────────────────────────────────
        # Targeting larger trend legs (5-9%) not oversold bounces (3-5%)
        "take_profit_pct":       6.0,   # BTC ran +5.8%, SOL +8.6% on the Apr 7 move
        "stop_loss_pct":         3.5,   # wider than the oversold profiles — trends can
                                        # retrace 2-3% before continuing
        "trailing_stop_pct":     2.5,   # lock in gains once running
        "arm_trailing_stop_pct": 2.0,   # arm after 2% — protect the initial leg
        "use_trailing_stop":     True,
        "max_position_hours":    48,    # trend legs resolve in 1-2 days
        "min_signal_confidence": 75.0,
 
        # ── 4HR TREND FILTER ───────────────────────────────────────────────────
        # Goal: confirm a trend IS running on the 4hr, RSI in healthy mid-range
        # NOT waiting for oversold — just confirming the trend exists
        "trend_indicators": [
            # ADX: the trend must have direction and momentum
            # ADX > 22 on 4hr = real trend, not range noise
            # Note: adx_trend is a simple threshold check; if your codebase
            # doesn't have this indicator type yet, use price_extended_below_ema
            # as a proxy (price within band = not in a ranging flat)
            {
                "type": "adx_trend",
                "params": {
                    "min_adx": 20,          # trend must be established
                    "max_adx": 60,          # don't enter blow-off moves
                    "hard_stop": True,
                }
            },
            # RSI: mid-range bullish momentum, not at extremes
            # We want RSI > 48 (trend has lifted off) but < 70 (not overbought)
            {
                "type": "rsi_range",
                "params": {
                    "min_value": 48,        # 4hr RSI must be in bullish territory
                    "max_value": 69,        # but not at extreme overbought
                    "hard_stop": True,
                }
            },
            # Price vs EMA50: not overextended above the trend anchor
            {
                "type": "price_extended_below_ema",  # reused indicator, but checking ABOVE
                "params": {
                    "ema": 50,
                    "min_gap_pct": -2.0,    # allow slight dip below EMA50 (false breaks)
                    "max_gap_pct": 6.0,     # block if too far extended (chasing)
                    # Note: if your implementation only blocks below, use max_gap_pct
                    # as a confidence penalty rather than hard_stop
                },
                "hard_stop": False,         # soft — confidence penalty only
            },
        ],
        "min_indicators_required": 2,   # ADX + RSI_range are the two hard gates
 
        # ── 1HR ENTRY FILTER ───────────────────────────────────────────────────
        # Goal: catch the intraday pullback within the 4hr uptrend
        # The 4hr says "trend exists", the 1hr says "price has pulled back to entry"
        "entry_indicators": [
            # RSI overbought gate — don't enter 1hr spike
            # This is a HARD STOP: if 1hr RSI > 60, we're chasing, not entering
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 60,        # 1hr RSI must be below 60
                    "hard_stop": True,
                }
            },
            # BB position: price should be back toward middle/lower of 1hr band
            # pct_b < 0.72 means price has pulled back — not at the upper band
            {
                "type": "bollinger_bands",
                "params": {
                    "band":       "upper",
                    "mode":       "pct_b",
                    "max_pct_b":  0.72,     # upper 28% of band = too extended
                    "hard_stop":  True,
                }
            },
            # Price vs 1hr EMA20: near or slightly below — the pullback anchor
            {
                "type": "price_vs_ema",
                "params": {
                    "ema":         20,
                    "min_gap_pct": -5.0,    # allow down to -5% below EMA20 (intraday dip)
                    "max_gap_pct":  2.0,    # don't enter too far above EMA20
                }
            },
            # RSI floor on 1hr: must not be in freefall (RSI < 30 = something wrong)
            # This is intentionally LOW — we want the pullback, just not a crash
            {
                "type": "rsi_overbought",   # reuse as a floor by inverting logic
                # OR implement as rsi_range check: 30 < RSI < 60
                # If your codebase has rsi_range as an entry indicator:
                "params": {
                    "min_value": 35,        # RSI floor — not in freefall
                    "hard_stop": False,     # soft penalty only at the low end
                }
            },
            # Volume: moderate — trend continuation candles have decent vol
            {
                "type": "volume_spike",
                "params": {
                    "min_ratio": 0.6,       # very soft lower bound — pullbacks have lower vol
                    "max_ratio": 8.0,
                }
            },
        ],
        "min_entry_indicators_required": 3,  # need RSI gate + BB + at least one other
    },
 
 
# =============================================================================
# SIMPLER ALTERNATIVE: p3_v18b_momentum_simple
# =============================================================================
# If adx_trend isn't an available indicator type in your backtest engine,
# use this version which approximates with indicators you already have.
#
# Uses price_extended_below_ema as the "not overextended" check, and
# rsi_overbought (inverted) as the momentum floor. More compatible with
# existing indicator types.
# =============================================================================
 
    "p3_v18b_momentum_simple": {
        **_SWING_BASE,
 
        "take_profit_pct":       5.5,
        "stop_loss_pct":         3.5,
        "trailing_stop_pct":     2.5,
        "arm_trailing_stop_pct": 2.0,
        "use_trailing_stop":     True,
        "max_position_hours":    48,
        "min_signal_confidence": 74.0,
 
        # ── 4HR TREND FILTER ───────────────────────────────────────────────────
        "trend_indicators": [
            # RSI range check: 4hr RSI must be in the 47-69 momentum zone
            # This IS your rsi_range indicator (you have it on some profiles)
            {
                "type": "rsi_range",
                "params": {
                    "min_value": 47,
                    "max_value": 69,
                    "hard_stop": True,
                }
            },
            # Overbought gate: belt-and-suspenders on the top end
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 70,        # block RSI 70+ on 4hr (blow-off)
                    "hard_stop": True,
                }
            },
            # Price not too far above EMA50 (not chasing an extended move)
            {
                "type": "price_extended_below_ema",
                "params": {
                    "ema": 50,
                    "min_gap_pct": -2.5,    # allow brief dips below
                    "max_gap_pct": 6.5,     # cap at 6.5% extension
                }
            },
        ],
        "min_indicators_required": 2,   # RSI range + overbought gate are both hard stops
 
        # ── 1HR ENTRY FILTER ───────────────────────────────────────────────────
        "entry_indicators": [
            # Primary gate: 1hr RSI must be cooling (< 58)
            {
                "type": "rsi_overbought",
                "params": {
                    "min_value": 58,        # 1hr RSI ceiling for entry
                    "hard_stop": True,
                }
            },
            # BB: intraday pullback confirmed — price in lower 65% of band
            {
                "type": "bollinger_bands",
                "params": {
                    "band":      "upper",
                    "mode":      "pct_b",
                    "max_pct_b": 0.68,
                    "hard_stop": True,
                }
            },
            # Price near 1hr EMA20
            {
                "type": "price_vs_ema",
                "params": {
                    "ema":         20,
                    "min_gap_pct": -5.0,
                    "max_gap_pct":  2.5,
                }
            },
            # Volume: soft gate
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
    # -------------------------------------------------------------------------
    # V14: RSI-ONLY ENTRY GATE — the simplest possible version
    #
    # "p3_v3_bb_rsilower": {
    #     **_SWING_BASE,
    #     "trend_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    8,
    #             "oversold_threshold":  45,
    #             "current_min":         36,
    #             "min_jump":            3.0,
    #             "require_sustained":   True,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
    #             "oversold_threshold":  45,
    #             "current_min":         38,
    #             "min_jump":            3.0,
    #             "require_sustained":   True,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         # RSI overbought is the ONLY "too late" gate — not BB
    #         {"type": "rsi_overbought", "params": {"min_value": 45, "hard_stop": True}},
    #         # Price vs EMA: wide allowance for post-crash EMA elevation
    #         {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
    #         # Volume: soft, no hard_stop
    #         {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
    #         {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1}},

    #        # BB: lower band check only — confirms price was genuinely depressed
    #         # (not a hard stop — just a confidence indicator)
    #     ],
    #     "min_entry_indicators_required": 4,
    # },

    # -------------------------------------------------------------------------
    # V15: STAGGERED ENTRY WINDOW — two-phase design
    #
    # Phase 1 (early entry): fires quickly after 4h trend confirms. Looser
    # BB gate (1.05), lower current_min (38), only 2/4 needed.
    # Phase 2 (late entry): already covered by the cooldown — the cooldown
    # means it only fires once per hour anyway.
    #
    # Key insight for SOL: the entry window is 15:03–20:03. We want to enter
    # at 15:03–17:03 when pct_b is 0.36–0.86 (before it breaks the band).
    # The 4h trend confirms at ~16:00–17:00. So we need the entry to fire
    # in the first 1–2 candles after 4h confirmation, before price pushes higher.
    #
    # This variant specifically targets that: requires the 60m rsi_reversal to
    # have a low current_min (confirms recent oversold on 60m) plus a BB that
    # is not yet extended (pct_b < 1.0 allows some band-walking).
    # -------------------------------------------------------------------------
    # "p3_v4_higherrsilevels": {
    #     **_SWING_BASE,
    #     "trend_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    8,
    #             "oversold_threshold":  48,
    #             "current_min":         36,
    #             "min_jump":            3.0,
    #             "require_sustained":   False,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         {"type": "rsi_overbought", "params": {"min_value": 55, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
    #             "oversold_threshold":  52,
    #             "current_min":         38,
    #             "min_jump":            3.0,
    #             "require_sustained":   False,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         # RSI overbought is the ONLY "too late" gate — not BB
    #         {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
    #         # Price vs EMA: wide allowance for post-crash EMA elevation
    #         {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
    #         # Volume: soft, no hard_stop
    #         {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
    #         {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1,"hard_stop":True}},

    #        # BB: lower band check only — confirms price was genuinely depressed
    #         # (not a hard stop — just a confidence indicator)
    #     ],
    #     "min_entry_indicators_required": 4,
    # },

    # -------------------------------------------------------------------------
    # V16: SUI-SPECIFIC — fix the 4h trend gate for gradual recoveries
    #
    # SUI's problem is purely upstream — the 4h RSI reversal never passed
    # because RSI recovered too gradually (no single big jump, slow grind).
    # SUI's 60m entry would have been clean (pct_b 0.35–0.65, RSI 40–50).
    #
    # Fix: lower min_jump to 3.0 on trend filter AND use a 2-candle check
    # (min net rise across lookback rather than requiring a single-candle jump).
    # Also: accept oversold_threshold=33 to match SUI's bounce from RSI 26→35.
    #
    # Entry: SUI doesn't have the BB problem so keep a normal BB gate.
    # -------------------------------------------------------------------------
    # "p3_v5_sustained_strict": {
    #     **_SWING_BASE,
    #     "trend_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    8,
    #             "oversold_threshold":  45,
    #             "current_min":         36,
    #             "min_jump":            3.0,
    #             "require_sustained":   False,
    #             "sustained_rise_mode": "strict",
    #             "hard_stop":           True,
    #         }},
    #         {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
    #             "oversold_threshold":  45,
    #             "current_min":         38,
    #             "min_jump":            3.0,
    #             "require_sustained":   False,
    #             "sustained_rise_mode": "strict",
    #             "hard_stop":           True,
    #         }},
    #         # RSI overbought is the ONLY "too late" gate — not BB
    #         {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
    #         # Price vs EMA: wide allowance for post-crash EMA elevation
    #         {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
    #         # Volume: soft, no hard_stop
    #         {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
    #         {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1,"hard_stop":True}},

    #        # BB: lower band check only — confirms price was genuinely depressed
    #         # (not a hard stop — just a confidence indicator)
    #     ],
    #     "min_entry_indicators_required": 4,
    # },


    # -------------------------------------------------------------------------
    # V17: COMBINED — targets all four symbols simultaneously
    #
    # Synthesizes fixes for each failure mode into one variant:
    #   SOL: lookback_candles=20 on entry, BB upper at 1.0 (not 0.85)
    #   HYPE: same BB fix, RSI OB at 62 is the real gate
    #   ETH: oversold_threshold=32 on trend (ETH hit 30.9 not <30)
    #   SUI: min_jump=3.0 + net mode on trend filter
    #
    # This is the "production candidate" variant that should be backtested
    # across the full dataset. It's slightly more permissive than baseline
    # but uses RSI structure as the quality gate rather than price indicators.
    # -------------------------------------------------------------------------
    # "p3_v17_unified_fix": {
    #     **_SWING_BASE,
    #     "min_signal_confidence": 76.0,
    #     "trend_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    8,
    #             "oversold_threshold":  35,   # ETH fix: was 30, ETH hit 30.9
    #             "current_min":         40,
    #             "min_jump":            3.5,  # SUI fix: was 5.0, now accepts gradual recovery
    #             "require_sustained":   True,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
    #         # No EMA slope. No vol spike. Both are post-crash lagging failures.
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    20,   # SOL fix: need to reach across 4h candle boundary
    #             "oversold_threshold":  30,
    #             "current_min":         38,
    #             "min_jump":            3.0,
    #             "require_sustained":   True,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         # RSI OB is the primary "too late" gate — replaces BB for that purpose
    #         {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
    #         # BB upper: raised to 1.0 — only block if price is ABOVE the band (SOL/HYPE fix)
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 1.0, "hard_stop": True}},
    #         # Volume: soft only
    #         {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
    #     ],
    #     "min_entry_indicators_required": 3,
    # },

}


