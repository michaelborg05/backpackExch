
# =============================================================================
# RANGE TRADING VARIANTS  (based on 15m_MB profile)
# Fixes weakness: HTF trend gate was too permissive, vwap check was skippable
# =============================================================================

# Baseline — your current live config (reproduced for comparison)
_RANGE_BASE = {
    "display_name": "range_trading",
    "strategy_type": "range_trading",
    "signal_timeframe": "15",
    "trend_timeframe": "60",
    "entry_timeframe": "15",
    "take_profit_pct": 0.6,
    "stop_loss_pct": 0.6,
    "trailing_stop_pct": 0.3,
    "arm_trailing_stop_pct": 0.25,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 600,
    "min_signal_confidence": 65.0,
    "min_volume_ratio": 0.8,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 4,
    "use_market_regime_filter": False,
    # Trend filter (60m)
    "trend_indicators": [
        {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
        {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False,}},
        {"type": "rsi_overbought",  "params": {"min_value": 60, "hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
    ],
    "min_indicators_required": 4,
    # Entry filter (15m)
    "entry_indicators": [
        {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False, "hard_stop": True,}},
        {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
        {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.05, "max_pct_b": 0.45, "hard_stop": True}},
        {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False,"max_drop_from_close_pct": 0.5}},
        {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55,"max_drop_from_close_pct": 0.5}},
        {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.2,"max_drop_from_close_pct": 0.5}},
    ],
    "min_entry_indicators_required": 4,
}

RANGE_VARIANTS = {

    # -------------------------------------------------------------------------
    # BASELINE — current live config (use for comparison)
    # -------------------------------------------------------------------------
    "range_baseline": _RANGE_BASE,

    # -------------------------------------------------------------------------
    # V1: Stronger HTF gate — fix the SOL downtrend problem
    # Change: 60m RSI minimum raised from 40→45, AND make it a hard_stop.
    # Rationale: SOL 60m RSI was 33.2 when trade fired. A hard_stop at 45
    # would have killed this trade outright. Slightly stricter but ranges
    # only form in neutral-to-mild trending markets.
    # -------------------------------------------------------------------------
    # "range_v1_rsi_momentum": {
    #     **_RANGE_BASE,
    #     "trend_indicators": [
    #         {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": True}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
    #     ],
    # },

    # -------------------------------------------------------------------------
    # V2: Add 60m BB position gate — block when 60m is already near lower band
    # Rationale: SOL 60m pct_b=0.12 — price was near the LOWER band of the HTF.
    # That means the HTF is in a downswing. For range trading you want to see
    # HTF in the MID band (0.25–0.75), not hugging the lower band.
    # -------------------------------------------------------------------------
    # "range_v2_htf_price_vs_emadip": {
    #     **_RANGE_BASE,
    #     "trend_indicators": [
    #         {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 2.5}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 4,
    # },
    # -------------------------------------------------------------------------
    # V3: Make vwap a hard_stop — SOL was actually ABOVE vwap when it fired
    # Rationale: price_below_vwap was one of the indicators that FAILED, but
    # since only 4/6 were needed, the trade still fired. Making it a hard_stop
    # means range entries MUST be below vwap (which is the whole point of a
    # range dip buy).
    # -------------------------------------------------------------------------
    # "range_v3_htf_bb_tighter": {
    #     **_RANGE_BASE,
    #     "trend_indicators": [
    #         {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.55, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 3,
    # },

    # -------------------------------------------------------------------------
    # V4: Tighter BB lower requirement — only trade at TRUE range lows
    # Rationale: SOL pct_b was 0.13 — just inside the 0.30 threshold.
    # Tightening to 0.20 means we only enter when price is in the bottom 20%
    # of the band — a more convincing range-low signal.
    # -------------------------------------------------------------------------
    "range_v4_claude_trendchange": {
        **_RANGE_BASE,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 4, "oversold_threshold": 48, "min_jump": 2,"current_min":35, "sustained_rise": False}},
            {"type": "rsi_overbought",  "params": {"min_value": 60, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
    },

    # -------------------------------------------------------------------------
    # V5: Add EMA proximity gate — block if EMA20 is too far above price
    # Rationale: SOL EMA20 was 83.15 vs price 82.77 = 0.46% above. That's
    # fine for range. But the 60m EMA20 was 83.93 — 1.4% above. We check
    # on 15m: if the fast EMA is significantly above price, we're in a
    # downmove not a range.
    # "max_gap_pct: 1.0" means block if price is >1% below EMA20 (falling knife)
    # -------------------------------------------------------------------------
    "range_v4_reversal_candles_largerSL": {
        **_RANGE_BASE,
        "take_profit_pct": 0.85,
        "stop_loss_pct": 0.65,
        "trailing_stop_pct": 0.3,
        "arm_trailing_stop_pct": 0.35,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01,"hard_stop": True}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False}},
            {"type": "rsi_overbought",  "params": {"min_value": 60, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
        ],
        "min_indicators_required": 4,
        "entry_indicators": [
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.05, "max_pct_b": 0.45, "hard_stop": True}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "min_close_pct": 0.2}},
        ],
        "min_entry_indicators_required": 5,        
    },


    "range_v11_reversal_candles_bbshorter": {
        **_RANGE_BASE,
        "take_profit_pct": 0.85,
        "stop_loss_pct": 0.65,
        "trailing_stop_pct": 0.3,
        "arm_trailing_stop_pct": 0.35,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01,"hard_stop": True}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False}},
            {"type": "rsi_overbought",  "params": {"min_value": 60, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.70, "hard_stop": True}},
        ],
        "min_indicators_required": 4,
        "entry_indicators": [
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.05, "max_pct_b": 0.35, "hard_stop": True}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "min_close_pct": 0.2}},
        ],
        "min_entry_indicators_required": 5,        
    },

    "range_v12_reversal_candles_RSIShorter": {
        **_RANGE_BASE,
        "take_profit_pct": 0.85,
        "stop_loss_pct": 0.65,
        "trailing_stop_pct": 0.3,
        "arm_trailing_stop_pct": 0.35,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01,"hard_stop": True}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False}},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
        ],
        "min_indicators_required": 4,
        "entry_indicators": [
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 35, "use_momentum": False, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 55, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.05, "max_pct_b": 0.45, "hard_stop": True}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "min_close_pct": 0.2}},
        ],
        "min_entry_indicators_required": 5,        
    },


    # -------------------------------------------------------------------------
    # V6: Kitchen sink — all of V1+V3+V4 combined (strictest)
    # Use to find the upper bound of precision (may have very few signals)
    # -------------------------------------------------------------------------
    # "range_v6_rsithreshold_HTF": {
    #     **_RANGE_BASE,
    #     "trend_indicators": [
    #         {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 40, "use_momentum": True, "early_threshold": 32}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 65, "hard_stop": True}},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 3,
    # },

    # -------------------------------------------------------------------------
    # V7: Relax entry — lower bar to catch more dips (opposite direction test)
    # Lower pct_b threshold and RSI threshold to see if we get MORE trades
    # (with likely lower win rate — useful to understand the trade-off curve)
    # -------------------------------------------------------------------------
    # "range_v7_adx": {
    #     **_RANGE_BASE,
    #     "trend_indicators": [
    #         {"type": "rsi_range",       "params": {"min": 38, "max": 62, "invert": True}},
    #         {"type": "adx_regime",       "params": {"max_adx": 30}},
    #         {"type": "bb_width_regime",  "params": {"required_direction": "not_expanding", "lookback": 3, "expand_threshold_pct": 0.1 }},
    #     ],
    #     "min_indicators_required": 3,
    #     "entry_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 3, "oversold_threshold": 48, "min_jump": 4,"current_min":40, "sustained_rise": True, "hard_stop": True}},
    #         {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0}},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.05, "max_pct_b": 0.35}},
    #         {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 4.0}},
    #         {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
    #     ],
    #     "min_entry_indicators_required": 4,
    # },

    # "range_v8_simpleRsi": {
    #     **_RANGE_BASE,
    #     "trend_indicators": [
    #         {"type": "rsi_range",       "params": {"min": 38, "max": 65, "invert": True, "hard_stop": True}},
    #         {"type": "adx_regime",       "params": {"max_adx": 35}},
    #         {"type": "bb_width_regime",  "params": {"required_direction": "not_expanding", "lookback": 3, "expand_threshold_pct": 0.1 }},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         {"type": "rsi_range",       "params": {"min": 38, "max": 62, "invert": True}},
    #         {"type": "rsi_reversal_momentum",   "params": {"lookback_candles": 2, "oversold_threshold": 50, "current_min": 40, "min_jump": 2, "require_sustained": False, "hard_stop": True}},
    #         {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0}},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b","min_pct_b": 0.05, "max_pct_b": 0.40 , "hard_stop": True}},
    #         {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 4.0}},
    #     ],
    #     "min_entry_indicators_required": 3,
    # },

}

# RANGE_VARIANTS = {
#     "range_v2_htf_bb_midrange": {
#         **_RANGE_BASE,
#         "take_profit_pct": 0.5,
#         "stop_loss_pct": 0.45,
#         "trailing_stop_pct": 0.3,
#         "arm_trailing_stop_pct": 0.25,
#         "use_trailing_stop": True,
#         "signal_cooldown_seconds": 600,
#         "min_signal_confidence": 65.0,
#         "min_volume_ratio": 0.8,
#         "use_trend_filter": False,
#         "trend_indicators": [
#             {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
#             {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 40, "use_momentum": False}},
#             {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
#             {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
#             # NEW: block if HTF is near its own lower band (downtrend on HTF)
#             {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20, "hard_stop": True}},
#         ],
#         "min_indicators_required": 3,  # still 3/5, but the new BB lower hard_stop blocks downtrends
#     }
# }
