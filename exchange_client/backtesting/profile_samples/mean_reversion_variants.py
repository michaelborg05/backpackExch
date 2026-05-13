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
    "min_signal_confidence": 66.0,
    "min_volume_ratio": 1.2,
    "use_trend_filter": True,
    "trend_timeframe": "60",
    "entry_timeframe": "15",
    "use_entry_filter": True,
    "max_position_hours": 6,
    "use_market_regime_filter": False,
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
}