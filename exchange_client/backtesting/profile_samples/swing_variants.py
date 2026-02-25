
# =============================================================================
# PROFILE3 VARIANTS  (based on "profile3" / swing_4h1h_simple)
# =============================================================================
#
# Profile3 uses 240m as HTF and 60m as entry TF. Both use rsi_reversal_momentum
# which looks for: was deeply oversold → jumped → now sustained rising.
#
# What the crash looked like on higher TFs:
#
# 240m (SOL):
#   Feb23 04:03 — RSI=25.7, EMA20 at 83.61 vs price 77.72 = 7.6% above
#   Feb23 08:03 — RSI=34.7  ← profile3 needs current_min=35, missed by 0.3!
#   Feb23 12:03 — RSI=37.8  ← this is the first passing candle (8hrs after bottom)
#   Vol: 4.5x at 04:03, 1.9x at 08:03 — profile3 needs 2x, only got it at the
#        crash candle. By the time RSI cleared 35 the vol had faded.
#
# 60m (entry):
#   After the crash, 60m RSI was 14-21 for 6 hours, then rose to 44 by 10:00
#   60m EMA20 was 4-6% above price throughout the whole 12-hour recovery.
#   ema_slope "not_falling" on 60m: this was STRONGLY FALLING the whole time.
#
# Key structural problems:
#   1. EMA slope check (0.05% min) at 240m blocks entry even when RSI confirms
#   2. The 60m ema_slope blocks entries throughout the bounce window
#   3. By the time RSI clears threshold, volume has dissipated
#   4. current_min=35 on 240m means you miss the first good candle (34.7)
#
# New variant approach: target the 60m timeframe more directly, use RSI-based
# trend reads rather than EMA slope, and consider 60m as both HTF and entry.
# =============================================================================

_SWING_BASE = {
    "strategy_type": "trend_following",
    "signal_timeframe": "60",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "take_profit_pct": 5.0,
    "stop_loss_pct": 4.0,
    "trailing_stop_pct": 3.5,
    "arm_trailing_stop_pct": 3.0,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 3600,
    "min_signal_confidence": 78.0,
    "min_volume_ratio": 1.3,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 72,
    "use_market_regime_filter": False,
}

SWING_VARIANTS = {

    # -------------------------------------------------------------------------
    # BASELINE — faithful reproduction of the live profile3
    # -------------------------------------------------------------------------
    "p3_baseline": {
        **_SWING_BASE,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 5, "oversold_threshold": 30, "current_min": 35,
                "min_jump": 5.0, "require_sustained": True, "hard_stop": True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            {"type": "volume_spike",   "params": {"min_ratio": 2.0, "max_ratio": 10.0}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.05}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 5, "oversold_threshold": 35, "current_min": 40,
                "min_jump": 3.0, "require_sustained": True, "hard_stop": True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 60, "hard_stop": True}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -2.0, "max_gap_pct": 5.0}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.02}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.2, "max_ratio": 5.0}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V1: Drop the 240m EMA slope entirely — it's the biggest source of lag
    # At 240m scale, EMA20 can be 7-8% above price for 24+ hours after a crash.
    # The EMA slope will be "falling" throughout the recovery, blocking all
    # entries. The RSI reversal momentum check is the real signal here.
    # Replace EMA slope with a BB pct_b check to still gate out overbought 240m.
    # -------------------------------------------------------------------------
    "p3_v1_no_ema_slope_240m": {
        **_SWING_BASE,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 5, "oversold_threshold": 30, "current_min": 35,
                "min_jump": 5.0, "require_sustained": True, "hard_stop": True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            {"type": "volume_spike",   "params": {"min_ratio": 2.0, "max_ratio": 10.0}},
            # Replace EMA slope with BB upper gate — price must not be extended above band
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 5, "oversold_threshold": 35, "current_min": 40,
                "min_jump": 3.0, "require_sustained": True, "hard_stop": True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 60, "hard_stop": True}},
            # Price vs EMA: widen the gap allowance — post crash EMA is elevated
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -6.0, "max_gap_pct": 6.0}},
            # Drop 60m EMA slope too — for same reason
            {"type": "volume_spike",   "params": {"min_ratio": 1.2, "max_ratio": 5.0}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
    },

    # -------------------------------------------------------------------------
    # V2: Lower current_min from 35 to 32 on 240m trend filter
    # In the Feb23 crash: 240m RSI at 08:03 was 34.7 — missed the 35 threshold
    # by 0.3 points! This is the most targeted fix for that specific miss.
    # Also lower the volume threshold slightly — by 08:03 vol was back to 1.9x.
    # -------------------------------------------------------------------------
    "p3_v2_lower_current_min_240m": {
        **_SWING_BASE,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  30,
                "current_min":         32,   # lowered from 35 → 32
                "min_jump":            5.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.5, "max_ratio": 10.0}},  # lowered from 2.0
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.05}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  35,
                "current_min":         38,   # also relaxed slightly
                "min_jump":            3.0,
                "require_sustained":   True,
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 60, "hard_stop": True}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -2.0, "max_gap_pct": 5.0}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.02}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 5.0}},  # relaxed
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V3: 60m-as-HTF — use 60m as both the trend check and entry TF.
    # Profile3 was designed for "240m decides, 60m enters". This variant tests
    # whether using 60m as the HTF gets you in faster without sacrificing too
    # much quality. 60m RSI clears 35 much faster after a crash than 240m does.
    # Tighter TP/SL than p3 baseline since 60m swings are smaller.
    # -------------------------------------------------------------------------
    "p3_v3_60m_as_htf": {
        **_SWING_BASE,
        "trend_timeframe": "60",   # promote 60m to HTF role
        "take_profit_pct": 2.5,    # narrower — 60m swings not 240m
        "stop_loss_pct":   2.0,
        "trailing_stop_pct":      1.8,
        "arm_trailing_stop_pct":  1.5,
        "max_position_hours":     36,
        "min_signal_confidence":  74.0,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 5, "oversold_threshold": 30, "current_min": 35,
                "min_jump": 4.0, "require_sustained": True, "hard_stop": True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.5, "max_ratio": 10.0}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    4,
                "oversold_threshold":  33,
                "current_min":         38,
                "min_jump":            3.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -4.0, "max_gap_pct": 5.0}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 5.0}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
    },

    # -------------------------------------------------------------------------
    # V4: No EMA slope on 60m entry filter either + net sustained mode
    # Combines V1 (no 240m EMA slope) with dropping the 60m EMA slope and
    # using "net" sustained mode for rsi_reversal_momentum on both levels.
    # The "net" mode allows dip-then-higher-high RSI patterns which are very
    # common during the grinding recovery after a panic.
    # -------------------------------------------------------------------------
    "p3_v4_no_ema_slopes_net_mode": {
        **_SWING_BASE,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  30,
                "current_min":         34,
                "min_jump":            5.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.8, "max_ratio": 10.0}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  33,
                "current_min":         38,
                "min_jump":            3.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought",  "params": {"min_value": 60, "hard_stop": True}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 5.0}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 5.0}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
    },

    # -------------------------------------------------------------------------
    # V5: Strict / high-conviction version — for normal (non-crash) markets
    # Tighten all thresholds so it only fires on very clean setups.
    # Higher jump requirement, higher vol requirement, tighter RSI bands.
    # This will likely fire rarely but when it does it should be high quality.
    # -------------------------------------------------------------------------
    "p3_v5_strict_high_conviction": {
        **_SWING_BASE,
        "min_signal_confidence": 82.0,
        "min_volume_ratio": 2.0,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6, "oversold_threshold": 28, "current_min": 38,
                "min_jump": 7.0, "require_sustained": True, "hard_stop": True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
            {"type": "volume_spike",   "params": {"min_ratio": 2.5, "max_ratio": 10.0}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.05}},
        ],
        "min_indicators_required": 4,  # all 4 required
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 5, "oversold_threshold": 38, "current_min": 43,
                "min_jump": 4.0, "require_sustained": True, "hard_stop": True,
            }},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -2.0, "max_gap_pct": 4.0}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.02}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.5, "max_ratio": 5.0}},
        ],
        "min_entry_indicators_required": 5,
    },
}
