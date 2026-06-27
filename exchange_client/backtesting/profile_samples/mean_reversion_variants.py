# =============================================================================
# MEAN REVERSION VARIANTS  (based on 15m_MB_ATR profile)
# Fixes weakness: trade fired without true exhaustion (BB middle, low volume,
# EMA barely touched). RSI bounce was the only real signal.
# =============================================================================

_MEAN_REV_BASE = {
    "display_name": "mean_reversion_profile",
    "strategy_type": "mean_reversion",
    "entry_timeframe": "15",
    "take_profit_pct": 1,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 20,
    "max_cluster_entries": 2,
    "min_signal_confidence": 66.0,
    "min_volume_ratio": 1.2,
    "use_trend_filter": True,
    "trend_timeframe": "60",
    "entry_timeframe": "15",
    "use_entry_filter": True,
    "max_position_hours": 6,
    "use_market_regime_filter": False,
    "use_trend_invalidation_exit":      True,
    "trend_invalidation_indicators":    "entry",  # default: 4hr trend indicators
    "min_position_age_for_trend_check": 50,        # minutes; 0 = check immediately

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
        {"type": "price_extended_below_ema",   "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
        {"type": "price_extended_below_ema",   "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": -0.5}},
    ],
    "min_indicators_required": 1,
    "entry_indicators": [
        {"type": "rsi_reversal_momentum",      "params": {"lookback_candles": 8, "oversold_threshold": 30, "current_min": 30, "min_jump": 3.0, "require_sustained": False, "sustained_rise_mode": "net","hard_stop": True}},
        {"type": "price_below_vwap",           "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
        {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "pct_b","max_pct_b": 0.3}},
        {"type": "rsi_overbought",             "params": {"min_value": 40}},
    ],
    "min_entry_indicators_required": 4,
}

MEAN_REV_VARIANTS = {

    "mr_baseline": _MEAN_REV_BASE,

    "mr_v2_spike_entry_withTrend": {
        **_MEAN_REV_BASE,
        "arm_trailing_stop_pct": 0.4,
        "use_trend_filter": True,
        "trend_indicators": [
            {"type": "price_extended_below_ema",   "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -4.0}},
            {"type": "price_extended_below_ema",   "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": -0.5}},
        ],
        "min_indicators_required": 1,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", 
                "indicator_group": "grp_1",
                "params": {
                    "lookback_candles": 4,
                    "oversold_threshold": 32,  # needs to have been very oversold
                    "current_min": 28,         # LOW bar — we enter early in the recovery
                    "min_jump": 4.0,           # big single jump required (capitulation candle)
                    "require_sustained": False, # NO sustained requirement — enter on the jump
                    "hard_stop": True,
            }},
            {"type": "volume_spike", "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", 
                                                    "min_pct_b": 0.01,"max_pct_b": 0.2}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -6.0}},
            {"type": "rsi_overbought", "params": {"min_value": 48}},
            {"type": "reversal_candle", 
                "indicator_group": "grp_1",
                 "params": {"pattern": "bull_close", 
                                                    "min_close_pct": 0.45,
                                                    "require_bull":True,
                                                    "max_drop_from_close_pct": 0.6}},
        ],
        "entry_indicator_groups": {
            "grp_1": {"require_all": False, "hard_stop": True},
        },
        "min_entry_indicators_required": 3,
    },
    
     "mr_v3_htf_gated": {
        **_MEAN_REV_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
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
        "min_volume_ratio": 1.0,  # raise from 0.7 to skip dead zone
    },

    "mr_v7_htf_gated_with_reversal": {
        **_MEAN_REV_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": 0.5,  "max_gap_pct": -0.5}},
            # THE key gate — 18% WR when htf_rsi >= 38
            {"type": "rsi_overbought", "params": {"min_value": 38, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            # OR group: RSI momentum OR bull candle — either confirms reversal
            {
                "type": "rsi_reversal_momentum",
                "indicator_group": "reversal_confirm",
                "params": {
                    "lookback_candles": 8, "oversold_threshold": 30, "current_min": 30,
                    "min_jump": 3.0, "require_sustained": False,
                    "sustained_rise_mode": "net", "hard_stop": False,
                },
            },
            {
                "type": "reversal_candle",
                "indicator_group": "reversal_confirm",
                "params": {"pattern": "bull_close", "min_close_pct": 0.45,
                        "require_bull": True, "max_drop_from_close_pct": 0.6},
            },
            # Ungrouped gates
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",   "params": {"min_value": 40}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ],
        "entry_indicator_groups": {
            "reversal_confirm": {"require_all": False, "hard_stop": True},
        },
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 1.0,
    },
    # "mr_v8_htf_bb_reversal": {
    #     **_MEAN_REV_BASE,
    #     "use_trend_filter": True,
    #     "trend_timeframe": "60",
    #     "trend_indicators": [
    #         {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
    #         {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": 0.5,  "max_gap_pct": -0.5}},
    #         {"type": "rsi_overbought", "params": {"min_value": 38, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         # Same reversal_confirm group as v7
    #         {
    #             "type": "rsi_reversal_momentum",
    #             "indicator_group": "reversal_confirm",
    #             "params": {"lookback_candles": 8, "oversold_threshold": 30, "current_min": 30,
    #                     "min_jump": 3.0, "require_sustained": False, "sustained_rise_mode": "net", "hard_stop": False},
    #         },
    #         {
    #             "type": "reversal_candle",
    #             "indicator_group": "reversal_confirm",
    #             "params": {"pattern": "bull_close", "min_close_pct": 0.45,
    #                     "require_bull": True, "max_drop_from_close_pct": 0.6},
    #         },
    #         # NEW vs v7: BB split into two zones, avoiding the 0.10-0.20 no-man's-land
    #         {
    #             "type": "bollinger_bands",
    #             "indicator_group": "bb_location",
    #             "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.10},
    #         },
    #         {
    #             "type": "bollinger_bands",
    #             "indicator_group": "bb_location",
    #             "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.20, "max_pct_b": 0.35},
    #         },
    #         # Unchanged from v7
    #         {"type": "rsi_overbought",   "params": {"min_value": 40}},
    #         {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
    #         {"type": "volume_spike",     "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
    #     ],
    #     "entry_indicator_groups": {
    #         "reversal_confirm": {"require_all": False, "hard_stop": True},
    #         # NEW vs v7
    #         "bb_location":      {"require_all": False, "hard_stop": True},
    #     },
    #     "min_entry_indicators_required": 5,  # up from 4 in v7 — bb_location now counts as a unit
    #     "min_volume_ratio": 1.0,
    # },
    "mr_v8_htf_gated_with_reversal_TSL": {
        **_MEAN_REV_BASE,
        "use_trend_filter": True,
        "trailing_stop_pct": 0.45,
        "arm_trailing_stop_pct": 0.7,
        "use_trailing_stop": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": 0.5,  "max_gap_pct": -0.5}},
            # THE key gate — 18% WR when htf_rsi >= 38
            {"type": "rsi_overbought", "params": {"min_value": 38, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            # OR group: RSI momentum OR bull candle — either confirms reversal
            {
                "type": "rsi_reversal_momentum",
                "indicator_group": "reversal_confirm",
                "params": {
                    "lookback_candles": 8, "oversold_threshold": 30, "current_min": 30,
                    "min_jump": 3.0, "require_sustained": False,
                    "sustained_rise_mode": "net", "hard_stop": False,
                },
            },
            {
                "type": "reversal_candle",
                "indicator_group": "reversal_confirm",
                "params": {"pattern": "bull_close", "min_close_pct": 0.45,
                        "require_bull": True, "max_drop_from_close_pct": 0.6},
            },
            # Ungrouped gates
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",   "params": {"min_value": 40}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ],
        "entry_indicator_groups": {
            "reversal_confirm": {"require_all": False, "hard_stop": True},
        },
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 1.0,
    },

    "mr_v9_v7tightened": {
        **_MEAN_REV_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": 0.5,  "max_gap_pct": -0.5}},
            # THE key gate — 18% WR when htf_rsi >= 38
            {"type": "rsi_overbought", "params": {"min_value": 38, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            # OR group: RSI momentum OR bull candle — either confirms reversal
            {
                "type": "rsi_reversal_momentum",
                "indicator_group": "reversal_confirm",
                "params": {
                    "lookback_candles": 8, "oversold_threshold": 30, "current_min": 30,
                    "min_jump": 3.0, "require_sustained": False,
                    "sustained_rise_mode": "net", "hard_stop": False,
                },
            },
            {
                "type": "reversal_candle",
                "indicator_group": "reversal_confirm",
                "params": {"pattern": "bull_close", "min_close_pct": 0.45,
                        "require_bull": True, "max_drop_from_close_pct": 0.6},
            },
            # Ungrouped gates
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",   "params": {"min_value": 42, "hard_stop": True}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.1, "max_ratio": 8.0, "hard_stop": True}},
        ],
        "entry_indicator_groups": {
            "reversal_confirm": {"require_all": False, "hard_stop": True},
        },
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 1.1,
    },

    # =========================================================================
    # OPTIMIZER-DISCOVERED VARIANTS  (60-day window, 4-iteration search)
    # =========================================================================

    # ── opt_v1: HTF rsi_oversold turning — ultra-selective, high conviction ──
    # Novel finding: putting rsi_oversold(require_rising=True) on the 60m trend
    # filter catches the EXACT turn from oversold, not just the oversold zone.
    # Very selective (~1-2 trades/month/symbol) but excellent quality when it fires.
    # Backtest (60d, 6 symbols): 7 trades, WR=71%, PF=2.41x, avg_pnl=+0.28%
    # Best exit found: TP=1.5%, SL=0.8%, no trailing (avg_pnl +0.53%)
    "mr_opt_v1_rsioversold_turn": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.5,
        "stop_loss_pct":         0.8,
        "trailing_stop_pct":     0.0,
        "arm_trailing_stop_pct": 0.0,
        "use_trailing_stop":     False,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_indicators": [
            # Price 1.5–3.5% below EMA50 (displacement confirmed)
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.5}},
            # 60m RSI was below 38 AND is now rising (catches the exact turn, not just the bottom)
            {"type": "rsi_oversold", "params": {"max_value": 38, "require_rising": True, "min_momentum": 0.3}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 8, "oversold_threshold": 30, "current_min": 30,
                "min_jump": 3.0, "require_sustained": False, "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "price_below_vwap",  "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",    "params": {"min_value": 40}},
            {"type": "volume_spike",      "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 1.0,
    },

    # ── opt_v2: dual RSI confirmation — best balance of volume and quality ────
    # Entry requires BOTH rsi_oversold(turning up) AND rsi_reversal_momentum.
    # Two independent RSI reversal signals must agree = much higher conviction.
    # Simpler trend filter than v3 (just displacement + RSI ceiling) but stronger entry.
    # Backtest (60d, 6 symbols): 38 trades, WR=55%, PF=1.85x, avg_pnl=+0.22%
    "mr_opt_v2_dual_rsi_confirm": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.5,
        "stop_loss_pct":         0.8,
        "trailing_stop_pct":     0.0,
        "arm_trailing_stop_pct": 0.0,
        "use_trailing_stop":     False,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_indicators": [
            # Shallower displacement window vs v3: catches more setup conditions
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.0, "max_gap_pct": -2.5}},
            # Simple RSI ceiling: blocks entries if 60m RSI >= 42 (not yet recovering)
            {"type": "rsi_overbought", "params": {"min_value": 42, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            # Gate 1: 15m RSI currently below 38 AND turning up (direct oversold confirmation)
            {"type": "rsi_oversold", "params": {
                "max_value": 38, "require_rising": True, "min_momentum": 0.5,
            }},
            # Gate 2: RSI bounced from deep oversold (complementary — oversold_threshold=25 is looser)
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 10, "oversold_threshold": 25, "current_min": 32,
                "min_jump": 3.0, "require_sustained": False, "hard_stop": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35}},
            # Hard ceiling: don't enter if 15m RSI already above 45 (bounce already happened)
            {"type": "rsi_overbought",   "params": {"min_value": 45, "hard_stop": True}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.3, "max_gap_pct": -10.0}},
        ],
        "min_entry_indicators_required": 3,
        "min_volume_ratio": 1.0,
    },

    # ── opt_v3: HTF BB lower band + engulfing candle — highest win rate ───────
    # Novel trend filter: requires price near/below lower BB on 60m (pct_b -0.1 to 0.2)
    # in addition to EMA50 displacement. Double-filters for genuine oversold on HTF.
    # Entry uses engulfing candle as reversal signal instead of pure RSI momentum.
    # Backtest (60d, 4 symbols): 35 trades, WR=66%, PF=1.42x, avg_pnl=+0.09%
    "mr_opt_v3_bb_engulf": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       0.8,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.4,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_indicators": [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0}},
            # 60m price in the lower BB zone (pct_b -0.1 to 0.2): confirms HTF genuinely oversold
            {"type": "bollinger_bands", "params": {
                "band": "lower", "mode": "pct_b", "min_pct_b": -0.1, "max_pct_b": 0.2,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 38, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            # Engulfing candle: previous candle was bearish, current bullish engulfs it
            {"type": "reversal_candle",       "params": {"pattern": "engulfing"}},
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 8, "oversold_threshold": 30, "current_min": 28,
                "min_jump": 2.5, "hard_stop": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35}},
            {"type": "rsi_overbought",   "params": {"min_value": 40, "hard_stop": True}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 1.0,
    },

    # =========================================================================
    # ITERATION-3 OPTIMIZER RESULTS  (3-iteration search, 60d, 4 symbols)
    # All three profiles target the same root fix: block knife-catching in
    # sustained downtrends. The old prod profile (mr_v3_htf_gated) fired when
    # 60m RSI < 38, but RSI stays below 38 for weeks in strong downtrends.
    # These profiles add displacement depth or active RSI reversal confirmation
    # at the trend level so we only enter genuine mean-reversion setups.
    # =========================================================================

    # ── opt_v4: deep displacement + hard RSI bounce — ALL-TIME BEST ──────────
    # Trend (60m): price must be 2–5% below EMA50 (deep crash only) AND RSI < 38
    # (hard gate — blocks knife-catching in gradual declines that stay below 38).
    # Entry (15m): RSI must have jumped 5+ points from below 28 in 6 candles
    # (sharp bounce from genuine panic) + VWAP below (hard) + BB lower zone + volume.
    # Backtest (60d, 4 symbols): 11 trades, WR=73%, PF=2.47x, avg_pnl=+0.28%
    # The 2% depth floor is the key change vs v3 — kills all "shallow" knife catches.
    "mr_opt_v4_deep_disp_rsi_bounce": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.0,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.5,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        # Optimizer used default mode ("trend") not "entry" — strict entry indicators
        # (RSI<42 hard, VWAP hard, volume hard) must NOT be used as exit triggers
        # or they'll cut trades the moment the mean reversion bounce starts.
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,
        "trend_indicators": [
            # Deep crash gate: price must be 2–5% below EMA50 (not just touching)
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -2.0, "max_gap_pct": -5.0}},
            # Hard RSI cap: blocks entries when 60m RSI >= 38 (gradual downtrend filter)
            {"type": "rsi_overbought", "params": {"min_value": 38, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            # Strict bounce: RSI jumped 5+ points from below 28 → confirms panic exhaustion
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6, "oversold_threshold": 28, "current_min": 32,
                "min_jump": 5.0, "require_sustained": False, "hard_stop": True,
            }},
            # Hard VWAP gate: price must be below VWAP (not just soft signal)
            {"type": "price_below_vwap",  "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0, "hard_stop": True}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.25}},
            # Hard RSI ceiling: don't enter if 15m RSI already climbed above 42
            {"type": "rsi_overbought",    "params": {"min_value": 42, "hard_stop": True}},
            {"type": "volume_spike",      "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 1.0,
    },

    # ── opt_v5: tight SL variant — highest total PnL in 60d window ──────────
    # Same deep-displacement signal as v4 but SL cut to 0.6% and TSL tightened
    # to 0.4%. Losers get cut faster, which pushed total PnL to +3.29% over 60d
    # (highest of any config). Trade-off: tighter SL may stop out more in chop.
    # Backtest (60d, 4 symbols): 12 trades, WR=67%, PF=2.49x, avg_pnl=+0.27%
    "mr_opt_v5_deep_disp_tight_sl": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.0,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.4,
        "arm_trailing_stop_pct": 0.5,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,
        "trend_indicators": [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -2.0, "max_gap_pct": -5.0}},
            {"type": "rsi_overbought", "params": {"min_value": 38, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6, "oversold_threshold": 28, "current_min": 32,
                "min_jump": 5.0, "require_sustained": False, "hard_stop": True,
            }},
            {"type": "price_below_vwap",  "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.25}},
            {"type": "rsi_overbought",    "params": {"min_value": 42, "hard_stop": True}},
            {"type": "volume_spike",      "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 1.0,
    },

    # ── opt_v6: moderate displacement + RSI actively turning — 80% win rate ──
    # Different trigger family vs v4/v5: shallower displacement (1.5–3.5% below EMA50)
    # but adds an active RSI momentum requirement at the trend level — 60m RSI must
    # be below 38 AND actively rising (min_momentum=0.3), catching the exact turn.
    # Entry uses rsi_range cap (max 45) to avoid entering after the bounce happened.
    # Quick exit (TP=0.7%, SL=0.5%) preserves the high WR by not holding through noise.
    # Backtest (60d, 4 symbols): 10 trades, WR=80%, PF=3.79x, avg_pnl=+0.20%
    "mr_opt_v6_mod_disp_oversold_turn": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       0.7,
        "stop_loss_pct":         0.5,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.35,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,
        "trend_indicators": [
            # Moderate displacement: 1.5–3.5% below EMA50 (broader than v4, but RSI turn required)
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.5}},
            # Key differentiator: 60m RSI must be oversold AND actively rising (not just below threshold)
            {"type": "rsi_oversold", "params": {"max_value": 38, "require_rising": True, "min_momentum": 0.3}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            # Range cap: prevents entry if 15m RSI already above 45 (bounce already priced in)
            {"type": "rsi_range",            "params": {"min": 20, "max": 45, "invert": True}},
            # Bounce confirmation: RSI jumped 3+ points from below 30 in 8 candles
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 8, "oversold_threshold": 30, "current_min": 28,
                "min_jump": 3.0, "hard_stop": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.3, "max_gap_pct": -10.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 3,
        "min_volume_ratio": 1.0,
    },
}