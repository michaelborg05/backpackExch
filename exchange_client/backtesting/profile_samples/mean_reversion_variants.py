# =============================================================================
# MEAN REVERSION VARIANTS  (based on 15m_MB_ATR profile)
# Fixes weakness: trade fired without true exhaustion (BB middle, low volume,
# EMA barely touched). RSI bounce was the only real signal.
# =============================================================================

_MEAN_REV_BASE = {
    "display_name": "mean_reversion_profile",
    "strategy_type": "mean_reversion",
    "signal_timeframe": "15",
    "entry_timeframe": "15",
    "take_profit_pct": 1,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 900,
    "min_signal_confidence": 75.0,
    "min_volume_ratio": 1.2,
    "use_trend_filter": False,
    "use_entry_filter": True,
    "max_position_hours": 4,
    "use_market_regime_filter": False,
    "entry_indicators": [
        {"type": "rsi_reversal_momentum",      "params": {"lookback_candles": 5, "oversold_threshold": 32, "current_min": 30, "min_jump": 4.0, "require_sustained": True, "sustained_rise_mode": "net","hard_stop": True}},
        {"type": "price_below_vwap",           "params": {"min_gap_pct": -0.5, "max_gap_pct": -6.0}},
        {"type": "volume_spike",               "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
        {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "pct_b","min_pct_b":0.01,"max_pct_b": 0.15}},
        {"type": "rsi_overbought",             "params": {"min_value": 44}},
    ],
    "min_entry_indicators_required": 4,
}

MEAN_REV_VARIANTS = {

    "mr_baseline": _MEAN_REV_BASE,

    # "mr_v1_spike_entry": {
    #     **_MEAN_REV_BASE,
    #     "take_profit_pct": 1,
    #     "stop_loss_pct": 0.7,   # wider SL — spike entries often have a retest
    #     "entry_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles": 4,
    #             "oversold_threshold": 32,  # needs to have been very oversold
    #             "current_min": 28,         # LOW bar — we enter early in the recovery
    #             "min_jump": 4.0,           # big single jump required (capitulation candle)
    #             "require_sustained": False, # NO sustained requirement — enter on the jump
    #             "hard_stop": True,
    #         }},
    #         {"type": "volume_spike", "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", 
    #                                                 "min_pct_b": 0.01,"max_pct_b": 0.15}},
    #         {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -6.0}},
    #         {"type": "rsi_overbought", "params": {"min_value": 48}},
    #         {"type": "reversal_candle", "params": {"pattern": "bull_close", 
    #                                                 "min_close_pct": 0.45,
    #                                                 "require_bull":True,
    #                                                 "max_drop_from_close_pct": 0.6}},
    #     ],
    #     "min_entry_indicators_required": 4,
    #     "min_signal_confidence": 66.0,
    # },
    "mr_v2_spike_entry_withTrend": {
        **_MEAN_REV_BASE,
        "use_trend_filter": True,
        "trend_indicators": [
            {"type": "price_extended_below_ema",   "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": -2.0}},
        ],
        "min_indicators_required": 1,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
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
            {"type": "reversal_candle", "params": {"pattern": "bull_close", 
                                                    "min_close_pct": 0.45,
                                                    "require_bull":True,
                                                    "max_drop_from_close_pct": 0.6}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 75.0,
    },

    "mr_v14_regime_gated": {
        **_MEAN_REV_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {
                "type": "price_extended_below_ema",
                "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": -2.0},
                "hard_stop": True,
            },
        ],
        "min_indicators_required": 1,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",    "params": {"lookback_candles": 6, "oversold_threshold": 38, "current_min": 35, "min_jump": 3.0, "require_sustained": True, "sustained_rise_mode": "net", "hard_stop": True}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -6.0}},
            {"type": "volume_spike",             "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.25}},
            {"type": "rsi_overbought",           "params": {"min_value": 48}},
            {"type": "reversal_candle",          "params": {"pattern": "bull_close", "min_body_pct": 0.45, "max_drop_from_close_pct": 0.5, "require_bull": True}},
            {"type": "price_below_vwap",         "params": {"min_gap_pct": -0.5, "max_gap_pct": -6.0}},
        ],
        "min_entry_indicators_required": 4,
    },

    # "mr_v11_waterfall": {
    #     **_MEAN_REV_BASE,
    #     "take_profit_pct": 0.8,   # tighter TP — waterfall recoveries are choppy
    #     "stop_loss_pct": 1,      # wider SL — these grind before recovering
    #     "trailing_stop_pct": 0.4,
    #     "arm_trailing_stop_pct": 0.4,
    #     "entry_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles": 8,     # look further back for the waterfall low
    #             "oversold_threshold": 30,
    #             "current_min": 30,         # just needs to be off the extreme low
    #             "min_jump": 3.0,
    #             "require_sustained": False,
    #             "sustained_rise_mode": "net",
    #             "hard_stop": True,
    #         }},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b",
    #                                                 "max_pct_b": 0.30}},
    #         {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
    #         {"type": "rsi_overbought", "params": {"min_value": 58}},
    #         # Vol check: don't require elevated current vol — the SMA got inflated
    #         # by crash candles. Just require it's not dead.
    #         {"type": "volume_spike", "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
    #     ],
    #     "min_entry_indicators_required": 4,
    #     "min_signal_confidence": 70.0,
    #     "min_volume_ratio": 0.7,
    # },

    "mr_v15_best_combined": {
        **_MEAN_REV_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_below_ema",
            "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": -2.0},
            "hard_stop": True},
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 0.8,    # v11's TP — actually fires at 26% rate
        "stop_loss_pct": 1.0,      # v11's SL
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "entry_indicators": [      # v11's looser RSI params
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 3.0,
                "require_sustained": False, "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.30}},
            {"type": "price_below_vwap",  "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "rsi_overbought",    "params": {"min_value": 48}},
            {"type": "volume_spike",      "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 70.0,
        "min_volume_ratio": 0.7,
    }   ,
 
    "mr_v15_best_combined-avoidmiddle": {
        **_MEAN_REV_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_below_ema",
            "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0},
            },
            {"type": "price_extended_below_ema",
            "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": -0.5},
            },
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 0.8,    # v11's TP — actually fires at 26% rate
        "stop_loss_pct": 1.0,      # v11's SL
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "entry_indicators": [      # v11's looser RSI params
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 3.0,
                "require_sustained": False, "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.30}},
            {"type": "price_below_vwap",  "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "rsi_overbought",    "params": {"min_value": 48}},
            {"type": "volume_spike",      "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 70.0,
        "min_volume_ratio": 0.7,
    } ,
    "mr_v15_best_combined-avoidmiddle_v2": {
        **_MEAN_REV_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_below_ema",
            "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.0},
            },
            {"type": "price_extended_below_ema",
            "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": -0.5},
            },
        ],
        "min_indicators_required": 1,
        "take_profit_pct": 1.0,    # v11's TP — actually fires at 26% rate
        "stop_loss_pct": 0.7,      # v11's SL
        "trailing_stop_pct": 0.5,
        "arm_trailing_stop_pct": 0.5,
        "entry_indicators": [      # v11's looser RSI params
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 8, "oversold_threshold": 30,
                "current_min": 30, "min_jump": 3.0,
                "require_sustained": False, "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.30}},
            {"type": "price_below_vwap",  "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "rsi_overbought",    "params": {"min_value": 48}},
            {"type": "volume_spike",      "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 70.0,
        "min_volume_ratio": 0.7,
    } ,
 
 
}