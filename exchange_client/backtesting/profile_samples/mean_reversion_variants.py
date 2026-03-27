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
    "take_profit_pct": 0.8,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 900,
    "min_signal_confidence": 75.0,
    "min_volume_ratio": 1.2,
    "use_trend_filter": False,
    "use_entry_filter": True,
    "max_position_hours": 0.75,
    "use_market_regime_filter": False,
    "entry_indicators": [
        {"type": "rsi_reversal_momentum",      "params": {"lookback_candles": 4, "oversold_threshold": 33, "current_min": 28, "min_jump": 4.0, "require_sustained": False, "sustained_rise_mode": "net","hard_stop": True}},
        {"type": "price_extended_below_ema",   "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
        {"type": "volume_spike",               "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
        {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "pct_b","max_pct_b": 0.25}},
        {"type": "rsi_overbought",             "params": {"min_value": 48}},
        {"type": "reversal_candle",            "params": {"pattern": "bull_close", "min_body_pct": 0.45,"max_drop_from_close_pct": 0.5,"require_bull": False}},
        {"type": "price_below_vwap",           "params": {"min_gap_pct": -0.5, "max_gap_pct": -6.0}},
    ],
    "min_entry_indicators_required": 4,
}

MEAN_REV_VARIANTS_OLD = {

    # -------------------------------------------------------------------------
    # BASELINE — current live config
    # -------------------------------------------------------------------------
    "mr_baseline": _MEAN_REV_BASE,

    # -------------------------------------------------------------------------
    # V1: Make BB lower breach a hard_stop
    # Rationale: SUI pct_b=0.41 — the BB lower breach FAILED but the trade
    # still fired because only 4/7 were needed. If price isn't near the lower
    # BB, it's not a mean reversion setup — it's just a mid-band dip.
    # -------------------------------------------------------------------------
    "mr_v1__higherrsi": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",      "params": {"lookback_candles": 6, "oversold_threshold": 38, "current_min": 35, "min_jump": 4.0, "require_sustained": True, "hard_stop": True}},
            {"type": "price_extended_below_ema",   "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
            {"type": "volume_spike",               "params": {"min_ratio": 1.1, "max_ratio": 5.0}},
            {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "breach","lookback_candles": 6}},
            {"type": "rsi_overbought",             "params": {"min_value": 65}},
            {"type": "reversal_candle",            "params": {"pattern": "hammer", "min_body_pct": 0.08,"max_drop_from_close_pct": 0.5}},
            {"type": "price_below_vwap",           "params": {"min_gap_pct": -0.5, "max_gap_pct": -8.0}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V2: Switch from BB breach to pct_b mode — more nuanced than binary breach
    # Rationale: pct_b < 0.15 means price in bottom 15% of band — more
    # reliable than a binary "touched or not" breach check.
    # -------------------------------------------------------------------------
    "mr_smller_jump": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",      "params": {"lookback_candles": 6, "oversold_threshold": 38, "current_min": 35, "min_jump": 3.0, "require_sustained": True, "hard_stop": True}},
            {"type": "price_extended_below_ema",   "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
            {"type": "volume_spike",               "params": {"min_ratio": 1.1, "max_ratio": 5.0}},
            {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "breach","lookback_candles": 6}},
            {"type": "rsi_overbought",             "params": {"min_value": 65}},
            {"type": "reversal_candle",            "params": {"pattern": "hammer", "min_body_pct": 0.08,"max_drop_from_close_pct": 0.5}},
            {"type": "price_below_vwap",           "params": {"min_gap_pct": -0.5, "max_gap_pct": -8.0}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V3: Demand real capitulation volume — raise volume minimum
    # Rationale: SUI volume was only 1.2x at entry. Real capitulation/exhaustion
    # moves have 2-3x+ volume. This is the most important filter for
    # mean reversion — we want to buy the SPIKE, not the quiet drift.
    # -------------------------------------------------------------------------
    "mr_v3_high_volume": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",    "params": {"lookback_candles": 3, "oversold_threshold": 32, "current_min": 38, "min_jump": 3.0, "require_sustained": True, "hard_stop": True}},
            {"type": "price_below_vwap",         "params": {"min_gap_pct": -0.7, "max_gap_pct": -8.0}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
            {"type": "volume_spike",             "params": {"min_ratio": 2.0, "max_ratio": 8.0}},  # raised 1.1→2.0
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "breach"}},
            {"type": "rsi_overbought",           "params": {"min_value": 65}},
            {"type": "reversal_candle",          "params": {"pattern": "hammer", "min_body_pct": 0.08}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 2.0,  # also tighten the global volume gate
    },

    # -------------------------------------------------------------------------
    # V4: Deeper oversold requirement — raise the bar for RSI
    # Rationale: The lookback threshold of 32 was passed by SUI at 29.9, but
    # the setup wasn't deep enough (only happened once, barely). Stricter
    # oversold_threshold + deeper current_min avoids borderline setups.
    # -------------------------------------------------------------------------
    "mr_v4_deeper_oversold": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",    "params": {"lookback_candles": 4, "oversold_threshold": 28, "current_min": 40, "min_jump": 5.0, "require_sustained": True, "hard_stop": True}},  # stricter
            {"type": "price_below_vwap",         "params": {"min_gap_pct": -0.7, "max_gap_pct": -8.0}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -1.0, "max_gap_pct": -10.0}},  # need more extension
            {"type": "volume_spike",             "params": {"min_ratio": 1.1, "max_ratio": 5.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "breach"}},
            {"type": "rsi_overbought",           "params": {"min_value": 65}},
            {"type": "reversal_candle",          "params": {"pattern": "hammer", "min_body_pct": 0.08}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V5: Replace price_extended_below_ema with pct_b lower check
    # Rationale: Fixed % below EMA is fragile across different volatility
    # regimes. BB pct_b <0.20 is a volatility-normalised way to say
    # "price is meaningfully stretched below its recent range." 
    # -------------------------------------------------------------------------
    "mr_v5_bb_extension": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",    "params": {"lookback_candles": 3, "oversold_threshold": 32, "current_min": 38, "min_jump": 3.0, "require_sustained": True, "hard_stop": True}},
            {"type": "price_below_vwap",         "params": {"min_gap_pct": -0.7, "max_gap_pct": -8.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20, "hard_stop": True}},  # replaces price_extended_below_ema
            {"type": "volume_spike",             "params": {"min_ratio": 1.1, "max_ratio": 5.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "breach"}},
            {"type": "rsi_overbought",           "params": {"min_value": 65}},
            {"type": "reversal_candle",          "params": {"pattern": "hammer", "min_body_pct": 0.08}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V6: Add 60m trend context — confirm HTF is also oversold (not just falling)
    # Rationale: SUI on the 60m had RSI=29.9 at 15:00 — it was deeply oversold
    # on the HTF too but still kept falling. We flip this: use the 60m to
    # CONFIRM that the HTF RSI is already turning (not still falling).
    # -------------------------------------------------------------------------
    "mr_v6_htf_rsi_confirmation": {
        **_MEAN_REV_BASE,
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            # 60m RSI must be below 45 (confirms oversold context on HTF)
            # but NOT still in free-fall (momentum turning up or flat)
            {"type": "rsi_oversold",  "params": {"max_value": 45, "require_rising": False}},
            # 60m RSI must have bounced off extreme (same reversal logic as entry)
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 3,
                "oversold_threshold": 35,
                "current_min": 30,
                "min_jump": 3.0,
                "require_sustained": False,
                "jump_required": False,   # just needs to have been oversold
                "hard_stop": True,
            }},
        ],
        "min_indicators_required": 1,  # just need the HTF to be in oversold territory
    },

    # -------------------------------------------------------------------------
    # V7: All corrections combined (strictest — likely fewer but better trades)
    # -------------------------------------------------------------------------
    "mr_v7_strict": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",    "params": {"lookback_candles": 4, "oversold_threshold": 28, "current_min": 40, "min_jump": 5.0, "require_sustained": True, "hard_stop": True}},
            {"type": "price_below_vwap",         "params": {"min_gap_pct": -0.7, "max_gap_pct": -8.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.15, "hard_stop": True}},
            {"type": "volume_spike",             "params": {"min_ratio": 2.0, "max_ratio": 8.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "breach"}},
            {"type": "rsi_overbought",           "params": {"min_value": 65}},
            {"type": "reversal_candle",          "params": {"pattern": "hammer", "min_body_pct": 0.08}},
        ],
        "min_entry_indicators_required": 5,  # raised from 4 to 5
        "min_signal_confidence": 78.0,
        "min_volume_ratio": 2.0,
    },

    # -------------------------------------------------------------------------
    # V8: Loose — lower bar to understand trade frequency vs quality tradeoff
    # -------------------------------------------------------------------------
    "mr_v8_loose": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",    "params": {"lookback_candles": 3, "oversold_threshold": 38, "current_min": 35, "min_jump": 2.0, "require_sustained": False, "hard_stop": True}},
            {"type": "price_below_vwap",         "params": {"min_gap_pct": -0.3, "max_gap_pct": -10.0}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.3, "max_gap_pct": -10.0}},
            {"type": "volume_spike",             "params": {"min_ratio": 0.8, "max_ratio": 6.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35}},
            {"type": "rsi_overbought",           "params": {"min_value": 65}},
            {"type": "reversal_candle",          "params": {"pattern": "hammer", "min_body_pct": 0.05}},
        ],
        "min_entry_indicators_required": 3,
        "min_signal_confidence": 68.0,
        "min_volume_ratio": 0.8,
    },
        #Modified by Michael
        #New profile. Same as standard but using sustained mode net and lookback of 5
        "mr_v9_rsi_reversal": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",      "params": {"lookback_candles": 5, "oversold_threshold": 32, "current_min": 25, "min_jump": 6.0, "require_sustained": True, "hard_stop": True, "sustained_rise_mode":"net"}},
            {"type": "price_below_vwap",           "params": {"min_gap_pct": -0.7, "max_gap_pct": -8.0}},
            {"type": "price_extended_below_ema",   "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
            {"type": "volume_spike",               "params": {"min_ratio": 1.1, "max_ratio": 5.0}},
            {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "breach"}},
            {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.45}},
            {"type": "rsi_overbought",             "params": {"min_value": 65}},
            {"type": "reversal_candle",            "params": {"pattern": "hammer", "min_body_pct": 0.08}},
        ],
        "min_entry_indicators_required": 4,

    },

}


MEAN_REV_VARIANTS = {

    # -------------------------------------------------------------------------
    # V10: SPIKE-ONLY — only enters on the immediate candle after the capitulation
    # spike. Requires the vol spike AND RSI jump to happen in the same 1-2 candle
    # window. Very selective — will fire on SOL 13:32, ETH 07:46, SUI 07:46.
    # 
    # Key insight: the best entries in this data were RSI 22-30 + vol 2x+ candles
    # that then had a NEXT candle RSI jump of 6+. Don't wait for "sustained" —
    # that confirmation always fires too late.
    # -------------------------------------------------------------------------
    "mr_baseline": _MEAN_REV_BASE,

    "mr_v10_spike_entry": {
        **_MEAN_REV_BASE,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 1,   # wider SL — spike entries often have a retest
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
                                                    "max_pct_b": 0.25}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -6.0}},
            {"type": "rsi_overbought", "params": {"min_value": 48}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", 
                                                    "min_close_pct": 0.45,
                                                    "max_drop_from_close_pct": 0.6}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 75.0,
    },

    # -------------------------------------------------------------------------
    # V11: WATERFALL RECOVERY — for the HYPE/SUI pattern where RSI grinds for
    # hours. No require_sustained, lower current_min, ignores BB breach (bands
    # are blown out during waterfalls), uses pct_b instead.
    #
    # Fires when: RSI was <30 in lookback AND has now bounced to 32+ AND vol
    # was elevated at some point (lookback vol check via lower ratio).
    # -------------------------------------------------------------------------
    "mr_v11_waterfall": {
        **_MEAN_REV_BASE,
        "take_profit_pct": 0.8,   # tighter TP — waterfall recoveries are choppy
        "stop_loss_pct": 1,      # wider SL — these grind before recovering
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 8,     # look further back for the waterfall low
                "oversold_threshold": 30,
                "current_min": 30,         # just needs to be off the extreme low
                "min_jump": 4.0,
                "require_sustained": False,
                "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b",
                                                    "max_pct_b": 0.30}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "rsi_overbought", "params": {"min_value": 58}},
            # Vol check: don't require elevated current vol — the SMA got inflated
            # by crash candles. Just require it's not dead.
            {"type": "volume_spike", "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 70.0,
        "min_volume_ratio": 0.7,
    },

    #changed to lower RSI settings
    # -------------------------------------------------------------------------
    "mr_v12_waterfalladjusted": {
        **_MEAN_REV_BASE,
        "take_profit_pct": 0.8,   # tighter TP — waterfall recoveries are choppy
        "stop_loss_pct": 1,      # wider SL — these grind before recovering
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 8,     # look further back for the waterfall low
                "oversold_threshold": 30,
                "current_min": 30,         # just needs to be off the extreme low
                "min_jump": 3.0,
                "require_sustained": False,
                "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b",
                                                    "max_pct_b": 0.30}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "rsi_overbought", "params": {"min_value": 42, "hard_stop": True,}},
            # Vol check: don't require elevated current vol — the SMA got inflated
            # by crash candles. Just require it's not dead.
            {"type": "volume_spike", "params": {"min_ratio": 0.7, "max_ratio": 8.0}},
        ],
    },

    # -------------------------------------------------------------------------
    # V13: DIAGNOSTIC — minimal gates, high trade count to understand what's
    # actually blocking entries. Check which indicator is failing most often.
    # Not for live use — just for understanding the data.
    # -------------------------------------------------------------------------
    "mr_v13_min5": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",      "params": {"lookback_candles": 4, "oversold_threshold": 32, "current_min": 28, "min_jump": 4.0, "require_sustained": False, "sustained_rise_mode": "net","hard_stop": True}},
            {"type": "price_extended_below_ema",   "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
            {"type": "volume_spike",               "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
            {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "pct_b","max_pct_b": 0.25}},
            {"type": "rsi_overbought",             "params": {"min_value": 48}},
            {"type": "reversal_candle",            "params": {"pattern": "bull_close", "min_body_pct": 0.45,"max_drop_from_close_pct": 0.5,"require_bull": False}},
            {"type": "price_below_vwap",           "params": {"min_gap_pct": -0.5, "max_gap_pct": -6.0}},
        ],
        "min_entry_indicators_required": 5,
    },
    "mr_v13_lowerRSIs": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",      "params": {"lookback_candles": 4, "oversold_threshold": 30, "current_min": 30, "min_jump": 2.5, "require_sustained": False, "sustained_rise_mode": "net","hard_stop": True}},
            {"type": "price_extended_below_ema",   "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
            {"type": "volume_spike",               "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
            {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "pct_b","max_pct_b": 0.25}},
            {"type": "rsi_overbought",             "params": {"min_value": 48}},
            {"type": "reversal_candle",            "params": {"pattern": "bull_close", "min_body_pct": 0.45,"max_drop_from_close_pct": 0.5,"require_bull": False}},
            {"type": "price_below_vwap",           "params": {"min_gap_pct": -0.5, "max_gap_pct": -6.0}},
        ],
        "min_entry_indicators_required": 4,
    },
}