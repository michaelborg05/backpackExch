
# =============================================================================
# TREND FOLLOWING VARIANTS  (based on "default" and "15m_no_trend" profiles)
# =============================================================================
#
# What the Feb22-24 data reveals about structural misses:
#
# WINDOW A — post-crash bounce, SOL Feb23 06:18-07:48 UTC (+1.2% in 90 min)
#   At 06:18: 15m RSI=42.9, EMA20 flat/just crossed, pct_b=0.91, VWAP=78.52
#   WHY DEFAULT MISSED:
#     - 60m RSI was 19.3 at 06:xx — trend filter rsi_range(min=30) BLOCKS it.
#       Even at 07:03 when 60m RSI recovered to 31.5, still barely clears 30.
#     - 60m EMA20 was 4.3% above price — ema_slope "not_falling" BLOCKS it.
#     - 15m RSI was 42.9 — entry rsi_threshold(min=52) BLOCKS it.
#   WHY 15m_NO_TREND MISSED:
#     - rsi_threshold(min=57) BLOCKS it even harder.
#     - price_vs_ema: price was -0.0% from EMA (fine) but rsi kills it first.
#
# WINDOW B — second day consolidation morning, Feb24 07:18-09:18 UTC
#   RSI15 reached 49-50, EMA20 converging, pct_b=0.62-0.76
#   WHY DEFAULT MISSED: 60m RSI was 28-35 throughout — trend filter blocks.
#   WHY 15m_NO_TREND MISSED: rsi_threshold(min=57) not reached.
#
# ROOT CAUSE: Both profiles require RSI>=52 (default) or >=57 (no_trend).
# In post-crash recovery these RSI levels weren't reached until the move
# was already 2-3% off the bottom — well past a good entry.
# The 60m EMA slope filter on "default" adds another layer of lag:
# 60m EMA20 didn't flatten until ~12 hours after the bottom.
#
# EMA lag observation (user's own note): EMA20/50 on 15m are fine for timing
# but the 60m EMA slope gate creates massive false-negatives in recoveries.
# The 60m RSI is a better "regime" indicator because it responds faster.
#
# Design goals for new variants:
#   1. Lower RSI entry threshold — catch earlier in recovery (risk: more noise)
#   2. Replace 60m EMA slope with 60m RSI range — faster, less lag
#   3. Add BB pct_b as the "is price moving up?" signal instead of EMA slope
#   4. Allow post-crash entries where EMA is still above price temporarily
#   5. "15m-only" variants that don't lean on HTF at all (like 15m_no_trend
#      but with different indicator combinations)
# =============================================================================

_TF_BASE = {
    "strategy_type": "trend_following",
    "signal_timeframe": "15",
    "entry_timeframe": "15",
    "take_profit_pct": 0.75,
    "stop_loss_pct": 0.6,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 900,
    "min_signal_confidence": 70.0,
    "min_volume_ratio": 1.1,
    "use_trend_filter": True,
    "trend_timeframe": "60",
    "use_entry_filter": True,
    "max_position_hours": 12,
    "use_market_regime_filter": True,
    "trend_indicators": [
        {"type": "ema_slope", "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01,"hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95,"hard_stop": True}},
        {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
        {"type": "rsi_overbought",  "params": {"min_value": 68, "hard_stop": True}},
    ],
    "min_indicators_required": 3,
    "entry_indicators": [
        {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
        {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.65}},
        {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 57,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
#        {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising",      "min_slope_pct": 0.02}},
#        {"type": "ema_slope",       "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.01}},
#        {"type": "rsi_reversal_momentum",   "params": {"lookback_candles": 3, "oversold_threshold": 42, "current_min": 45, "min_jump": 3, "require_sustained": False, "hard_stop": True}},
        {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
        {"type": "price_vs_vwap",   "params": {}},
    ],
    "min_entry_indicators_required": 5,

}

TREND_VARIANTS = {

    # -------------------------------------------------------------------------
    # BASELINES — faithful reproductions of live profiles for comparison
    # -------------------------------------------------------------------------
    "tf_baseline_default": {
        **_TF_BASE,
    },

    # -------------------------------------------------------------------------
    # V1: Lower RSI entry — drop from 52 to 44 to catch earlier in recovery
    # In Window A, RSI hit 42.9 at the best entry candle (06:18).
    # The baseline required 52 — meaning it would have missed by 9 points.
    # Dropping to 44 (early_threshold 40) would have caught the 06:33 candle
    # (RSI=44.5) with pct_b=0.99 and price just above EMA.
    # Trade-off: fires in mediocre 40-50 RSI chop too. Backtest required.
    # -------------------------------------------------------------------------
    "tf_v1_ai_profile": {
        **_TF_BASE,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01,"hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.95,"hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 2, "hard_stop": True}},
            {"type": "ema_gap",         "params": {"min_gap_pct": 0.15, "mode": "min", "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.9, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 68,"lookback_candles":6, "hard_stop": True}},
            
            {"type": "rsi_reversal_momentum",   "params": {"lookback_candles": 10, "oversold_threshold": 48, "current_min": 36, "min_jump": 3, "require_sustained": False,}},
            {"type": "rsi_range", "params": {"min": 50, "max": 67, "invert": True}},
            {"type": "reversal_candle", "params": {"pattern": "engulfing", "max_drop_from_close_pct": 0.6}},
            {"type": "reversal_candle", "params": {"pattern": "bull_close", "min_close_pct": 0.55, "max_drop_from_close_pct": 0.6}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.6}},
        ],
        "min_entry_indicators_required": 6,
    },

    "tf_v2_ema_slope_rising": {
        **_TF_BASE,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01,"hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.95,"hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
    },

    "tf_v3_changed_entries": {
        **_TF_BASE,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01,"hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95,"hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.65}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 54,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising",      "min_slope_pct": 0.02}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.6}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
        ],
        "min_entry_indicators_required": 5,
    },

    "tf_v3_changed_entriesWith6Min": {
        **_TF_BASE,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01,"hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95,"hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.65}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 54,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising",      "min_slope_pct": 0.02}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.6}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
        ],
        "min_entry_indicators_required": 6,
    },

    # -------------------------------------------------------------------------
    # V3: BB momentum instead of EMA slope — faster signal, less lag
    # The EMA slope needs multiple candles of sustained price movement to flip.
    # BB pct_b reacts to price immediately. Using pct_b RISING as the momentum
    # check means we catch the move at start of the BB expansion rather than
    # after the EMA has already confirmed it.
    # Entry: pct_b must be in 0.35-0.80 (moving up through the band, not at
    # extremes). This avoids both "just oversold" (pct_b<0.25) and "already
    # extended" (pct_b>0.80) entries.
    # -------------------------------------------------------------------------
    # "tf_v3_bb_momentum_no_ema_slope": {
    #     **_TF_BASE,
    #     "trend_indicators": [
    #         {"type": "rsi_range", "params": {"min": 28, "max": 65}},
    #         {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         # Price in mid-band and moving up (the rising part of the recovery)
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.80}},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35, "hard_stop": True}},  # must be above 35% of band
    #         {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.25, "hard_stop": True}},
    #         # RSI showing momentum but lower bar than baseline
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 45, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
    #         {"type": "price_vs_vwap",   "params": {}},
    #         # EMA: allow price slightly below EMA (post-crash) but not far
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.0, "max_gap_pct": 2.0}},
    #     ],
    #     "min_entry_indicators_required": 5,
    #     "min_volume_ratio": 0.9,  # slightly relaxed — slow recoveries have low vol
    # },

    # -------------------------------------------------------------------------
    # V4: "No trend filter, BB + RSI momentum only" — equivalent to the
    # 15m_no_trend profile but replacing the hammer candle and high RSI
    # requirement with BB pct_b range + lower RSI threshold.
    # This specifically targets the Window A / B pattern where RSI was 42-50
    # and BB was in the middle-upper range (not near extremes).
    # Lean: slightly more aggressive, good for testing "what if we just didn't
    # require 57 RSI and a hammer candle" from 15m_no_trend.
    # -------------------------------------------------------------------------
    # "tf_v4_no_trend_bb_rsi": {
    #     **_TF_BASE,
    #     "entry_indicators": [
    #         # BB must be in the mid-rising range
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.75}},
    #         {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.30, "hard_stop": True}},
    #         # RSI showing actual momentum up
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 45, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
    #         # Price vs VWAP and EMA — looser gap than baseline
    #         {"type": "price_vs_vwap",   "params": {}},
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.8, "max_gap_pct": 1.5}},
    #     ],
    #     "min_entry_indicators_required": 4,
    #     "min_signal_confidence": 68.0,
    #     "min_volume_ratio": 0.9,
    # },

    # -------------------------------------------------------------------------
    # V5: "No trend filter, RSI reversal + BB" — specifically designed for
    # the post-crash bounces in this dataset. The 15m RSI went from 12 → 42
    # over ~5 hours. The reversal momentum indicator looks back 4-5 candles
    # to confirm the bounce has started.
    # Key difference from MR variants: this is trend_following not MR, so it
    # doesn't require the full capitulation setup (BB breach, extreme vwap gap).
    # It just needs to see RSI recovering from an oversold read.
    # -------------------------------------------------------------------------
    # "tf_v5_no_trend_rsi_reversal": {
    #     **_TF_BASE,
    #     "entry_indicators": [
    #         # RSI was recently oversold and is rising sustainably
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    5,
    #             "oversold_threshold":  35,   # was below 35 in last 5 candles
    #             "current_min":         40,   # currently above 40
    #             "min_jump":            4.0,  # jumped 4+ in one candle (the bounce candle)
    #             "require_sustained":   True,
    #             "sustained_rise_mode": "net",  # allow dip-then-recovery shape
    #             "hard_stop":           True,
    #         }},
    #         {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
    #         # BB: not at the top yet (catching the move, not chasing)
    #         {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
    #         # VWAP: must be near or above (bounce has legs)
    #         {"type": "price_vs_vwap",   "params": {}},
    #         # EMA: allow meaningful gap below (post-crash EMA still elevated)
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -2.5, "max_gap_pct": 2.0}},
    #     ],
    #     "min_entry_indicators_required": 4,
    #     "min_volume_ratio": 0.8,
    #     "min_signal_confidence": 65.0,
    # },

    # -------------------------------------------------------------------------
    # V6: Strict trend confirm, lower RSI — keep the HTF discipline but relax
    # the entry RSI to 46. The 60m RSI gate does most of the heavy lifting;
    # in normal (non-crash) markets it keeps RSI>30 anyway, so this variant
    # is really about whether a lower entry RSI helps on normal bounces.
    # -------------------------------------------------------------------------
    # "tf_v6_strict_htf_lower_entry_rsi": {
    #     **_TF_BASE,
    #     "trend_indicators": [
    #         {"type": "rsi_range",  "params": {"min": 32, "max": 62, "invert": True}},
    #         {"type": "ema_slope",  "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
    #         {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising",      "min_slope_pct": 0.02}},
    #         {"type": "ema_slope",       "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.01}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 46, "use_momentum": True, "early_threshold": 42, "hard_stop": True}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 65, "hard_stop": True}},
    #         {"type": "price_vs_vwap",   "params": {}},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.70, "hard_stop": True}},
    #         {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.30, "hard_stop": True}},
    #     ],
    #     "min_entry_indicators_required": 6,
    # },

    # # -------------------------------------------------------------------------
    # # V7: 15m-only, volume + RSI + hammer — reproduce 15m_no_trend but
    # # drop the RSI threshold from 57 to 47 and add BB pct_b in place of it.
    # # The hammer candle check stays because it adds good timing precision
    # # (confirms the reversal candle, not just any RSI bounce).
    # # -------------------------------------------------------------------------
    # "tf_v7_no_trend_lower_rsi_keep_hammer": {
    #     **_TF_BASE,
    #     "entry_indicators": [
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
    #         {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08}},
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.65}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 47, "use_momentum": True, "early_threshold": 42, "hard_stop": True}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
    #         {"type": "price_vs_vwap",   "params": {}},
    #     ],
    #     "min_entry_indicators_required": 5,
    #     "min_signal_confidence": 68.0,
    # },

    # # -------------------------------------------------------------------------
    # # V8: Volume spike as primary gating signal
    # # Observation: the big bounces in this dataset all had a vol spike candle
    # # (the 10x candle at crash, then smaller spikes at turns). Rather than
    # # relying on EMA slope for direction, use volume to confirm "something is
    # # happening" and RSI to confirm it's a recovery not a continuation.
    # # Note min_volume_ratio raised — vol is the main edge here.
    # # -------------------------------------------------------------------------
    # "tf_v8_volume_primary": {
    #     **_TF_BASE,
    #     "entry_indicators": [
    #         # Must have real volume — not just background noise
    #         {"type": "volume_spike",    "params": {"min_ratio": 1.5, "max_ratio": 6.0}},
    #         # RSI: moderate — showing it's a recovery not just random noise
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 45, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 65, "hard_stop": True}},
    #         # BB in mid range — not at extremes
    #         {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.70, "hard_stop": True}},
    #         {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.25, "hard_stop": True}},
    #         {"type": "price_vs_vwap",   "params": {}},
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 2.0}},
    #     ],
    #     "min_entry_indicators_required": 5,
    #     "min_signal_confidence": 68.0,
    #     "min_volume_ratio": 1.5,
    # },
    # "tf_v9_feb18defaultprofile": {
    #     **_TF_BASE,
    #     "trend_indicators": [
    #         {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 52, "use_momentum": True, "early_threshold": 40}},
    #         {"type": "rsi_overbought",   "params": {"min_value": 70, "hard_stop": True}},
    #         {"type": "price_vs_vwap",  "params": {}},
    #     ],
    #     "min_indicators_required": 3,
    #     "entry_indicators": [
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
    #         {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02}},
    #         {"type": "ema_slope",  "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.01}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 58, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 70, "hard_stop": True}},
    #         {"type": "price_vs_vwap",   "params": {}},
    #     ],
    #     "min_entry_indicators_required": 5,
    #     "min_signal_confidence": 68.0,
    #     "min_volume_ratio": 1.5,
    # },

    # "tf_v9_feb18_15m_profile": {
    #     **_TF_BASE,
    #     "use_trend_filter": False,
    #     "use_entry_filter": True,
    #     "entry_indicators": [
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
    #         {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02}},
    #         {"type": "ema_slope",  "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.01}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 53, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
    #         {"type": "rsi_overbought",  "params": {"min_value": 70, "hard_stop": True}},
    #         {"type": "price_vs_vwap",   "params": {}},
    #     ],
    #     "min_entry_indicators_required": 5,
    #     "min_signal_confidence": 68.0,
    #     "min_volume_ratio": 1.5,
    # },
    
    # "tf_v9_feb14defaultprofile": {
    #     **_TF_BASE,
    #     "trend_indicators": [
    #         {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02}},
    #         {"type": "ema_slope",  "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.01}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 52, "use_momentum": True, "early_threshold": 40}},
    #         {"type": "price_vs_vwap",  "params": {}},
    #     ],
    #     "min_indicators_required": 3,
    #     "entry_indicators": [
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": 0, "max_gap_pct": 1.5}},
    #         {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02}},
    #         {"type": "ema_slope",  "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.01}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 53, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
    #         {"type": "price_vs_vwap",   "params": {}},
    #     ],
    #     "min_entry_indicators_required": 4,
    #     "min_signal_confidence": 68.0,
    #     "min_volume_ratio": 1.5,
    # },

    # "tf_v9_feb14_15m_profile": {
    #     **_TF_BASE,
    #     "use_trend_filter": False,
    #     "use_entry_filter": True,
    #     "entry_indicators": [
    #         {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": 0, "max_gap_pct": 1.5}},
    #         {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02}},
    #         {"type": "ema_slope",  "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.01}},
    #         {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 53, "use_momentum": True, "early_threshold": 40, "hard_stop": True}},
    #         {"type": "price_vs_vwap",   "params": {}},
    #     ],
    #     "min_entry_indicators_required": 4,
    #     "min_signal_confidence": 70.0,
    #     "min_volume_ratio": 1.5,
    # },
}




