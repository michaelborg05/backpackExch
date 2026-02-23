"""
backtesting/profile_variants.py
=================================
Curated indicator configuration variants for backtesting.

Each variant set is grounded in what ACTUALLY went wrong in the two
losing trades (2026-02-23):

  TRADE 1 — range_trading (15m_MB): SOL $82.77 — stopped out 20min later
    Root cause: SOL was in a downtrend (60m RSI=33.2, EMA20 1.4% above price).
    The range_trading profile fired because the 15m bounced off the BB lower
    while price happened to be above VWAP — the HTF trend gate was too weak.

  TRADE 2 — mean_reversion (15m_MB_ATR): SUI 0.9249 — stopped out 5hrs later
    Root cause: Not a real oversold setup. BB pct_b=0.41 (middle of band),
    volume only 1.2x, EMA20 distance only -0.11%. The RSI bounce looked good
    but no other indicator confirmed true exhaustion/capitulation.

Variants are organised by profile and strategy type. Use with BacktestEngine:

    from backtesting.profile_variants import RANGE_VARIANTS, MEAN_REV_VARIANTS
    from backtesting.backtest_engine import BacktestProfile, BacktestEngine

    for name, config in RANGE_VARIANTS.items():
        profile = BacktestProfile.from_dict(name, config)
        result  = BacktestEngine(db, profile).run("SOL_USDC", start, end)
        print(f"{name}: {result.win_rate:.0%} win | {result.total_pnl_pct:+.1f}% PnL")
"""

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
    "take_profit_pct": 0.5,
    "stop_loss_pct": 0.45,
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
        {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 40, "use_momentum": False}},
        {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
    ],
    "min_indicators_required": 3,
    # Entry filter (15m)
    "entry_indicators": [
        {"type": "rsi_oversold",    "params": {"max_value": 48, "require_rising": True, "min_momentum": 1, "hard_stop": True}},
        {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.30}},
        {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 4.0}},
        {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
        {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
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
    "range_v1_htf_rsi_hardstop": {
        **_RANGE_BASE,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 45, "use_momentum": False, "hard_stop": True}},  # raised+hardstop
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
    },

    # -------------------------------------------------------------------------
    # V2: Add 60m BB position gate — block when 60m is already near lower band
    # Rationale: SOL 60m pct_b=0.12 — price was near the LOWER band of the HTF.
    # That means the HTF is in a downswing. For range trading you want to see
    # HTF in the MID band (0.25–0.75), not hugging the lower band.
    # -------------------------------------------------------------------------
    "range_v2_htf_bb_midrange": {
        **_RANGE_BASE,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 40, "use_momentum": False}},
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
            # NEW: block if HTF is near its own lower band (downtrend on HTF)
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20, "hard_stop": True}},
        ],
        "min_indicators_required": 3,  # still 3/5, but the new BB lower hard_stop blocks downtrends
    },

    # -------------------------------------------------------------------------
    # V3: Make vwap a hard_stop — SOL was actually ABOVE vwap when it fired
    # Rationale: price_below_vwap was one of the indicators that FAILED, but
    # since only 4/6 were needed, the trade still fired. Making it a hard_stop
    # means range entries MUST be below vwap (which is the whole point of a
    # range dip buy).
    # -------------------------------------------------------------------------
    "range_v3_vwap_hardstop": {
        **_RANGE_BASE,
        "entry_indicators": [
            {"type": "rsi_oversold",    "params": {"max_value": 48, "require_rising": True, "min_momentum": 1, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},  # NOW HARD STOP
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.30}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 4.0}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V4: Tighter BB lower requirement — only trade at TRUE range lows
    # Rationale: SOL pct_b was 0.13 — just inside the 0.30 threshold.
    # Tightening to 0.20 means we only enter when price is in the bottom 20%
    # of the band — a more convincing range-low signal.
    # -------------------------------------------------------------------------
    "range_v4_tighter_bb": {
        **_RANGE_BASE,
        "entry_indicators": [
            {"type": "rsi_oversold",    "params": {"max_value": 48, "require_rising": True, "min_momentum": 1, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20}},  # tightened 0.30→0.20
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 4.0}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V5: Add EMA proximity gate — block if EMA20 is too far above price
    # Rationale: SOL EMA20 was 83.15 vs price 82.77 = 0.46% above. That's
    # fine for range. But the 60m EMA20 was 83.93 — 1.4% above. We check
    # on 15m: if the fast EMA is significantly above price, we're in a
    # downmove not a range.
    # "max_gap_pct: 1.0" means block if price is >1% below EMA20 (falling knife)
    # -------------------------------------------------------------------------
    "range_v5_ema_proximity": {
        **_RANGE_BASE,
        "entry_indicators": [
            {"type": "rsi_oversold",    "params": {"max_value": 48, "require_rising": True, "min_momentum": 1, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.30}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 4.0}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
            # NEW: price must not be more than 1% below EMA20 (blocks falling knife entries)
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.0, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V6: Kitchen sink — all of V1+V3+V4 combined (strictest)
    # Use to find the upper bound of precision (may have very few signals)
    # -------------------------------------------------------------------------
    "range_v6_strict": {
        **_RANGE_BASE,
        "trend_indicators": [
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.01}},
            {"type": "rsi_threshold",   "params": {"period": 14, "min_value": 45, "use_momentum": False, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_oversold",    "params": {"max_value": 48, "require_rising": True, "min_momentum": 1, "hard_stop": True}},
            {"type": "price_below_vwap","params": {"min_gap_pct": -0.15, "max_gap_pct": -2.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.20}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.2, "max_ratio": 4.0}},  # slightly higher volume threshold
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.25}},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -1.0, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 68.0,
    },

    # -------------------------------------------------------------------------
    # V7: Relax entry — lower bar to catch more dips (opposite direction test)
    # Lower pct_b threshold and RSI threshold to see if we get MORE trades
    # (with likely lower win rate — useful to understand the trade-off curve)
    # -------------------------------------------------------------------------
    "range_v7_loose": {
        **_RANGE_BASE,
        "entry_indicators": [
            {"type": "rsi_oversold",    "params": {"max_value": 52, "require_rising": True, "min_momentum": 0.5, "hard_stop": True}},  # looser RSI
            {"type": "price_below_vwap","params": {"min_gap_pct": 0.0, "max_gap_pct": -3.0}},   # allows at/near vwap
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.45}},  # wider
            {"type": "volume_spike",    "params": {"min_ratio": 0.8, "max_ratio": 5.0}},
            {"type": "reversal_candle", "params": {"pattern": "doji", "max_body_pct": 0.35}},
            {"type": "rsi_overbought",  "params": {"min_value": 60, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,  # only need 3/6
        "min_signal_confidence": 60.0,
    },
}


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
    "take_profit_pct": 1.0,
    "stop_loss_pct": 1.0,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 900,
    "min_signal_confidence": 75.0,
    "min_volume_ratio": 1.2,
    "use_trend_filter": False,
    "use_entry_filter": True,
    "max_position_hours": 8,
    "use_market_regime_filter": False,
    "entry_indicators": [
        {"type": "rsi_reversal_momentum",      "params": {"lookback_candles": 3, "oversold_threshold": 32, "current_min": 38, "min_jump": 3.0, "require_sustained": True, "hard_stop": True}},
        {"type": "price_below_vwap",           "params": {"min_gap_pct": -0.7, "max_gap_pct": -8.0}},
        {"type": "price_extended_below_ema",   "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
        {"type": "volume_spike",               "params": {"min_ratio": 1.1, "max_ratio": 5.0}},
        {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "breach"}},
        {"type": "rsi_overbought",             "params": {"min_value": 65}},
        {"type": "reversal_candle",            "params": {"pattern": "hammer", "min_body_pct": 0.08}},
    ],
    "min_entry_indicators_required": 4,
}

MEAN_REV_VARIANTS = {

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
    "mr_v1_bb_breach_hardstop": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",    "params": {"lookback_candles": 3, "oversold_threshold": 32, "current_min": 38, "min_jump": 3.0, "require_sustained": True, "hard_stop": True}},
            {"type": "price_below_vwap",         "params": {"min_gap_pct": -0.7, "max_gap_pct": -8.0}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
            {"type": "volume_spike",             "params": {"min_ratio": 1.1, "max_ratio": 5.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "breach", "hard_stop": True}},  # NOW HARD STOP
            {"type": "rsi_overbought",           "params": {"min_value": 65}},
            {"type": "reversal_candle",          "params": {"pattern": "hammer", "min_body_pct": 0.08}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V2: Switch from BB breach to pct_b mode — more nuanced than binary breach
    # Rationale: pct_b < 0.15 means price in bottom 15% of band — more
    # reliable than a binary "touched or not" breach check.
    # -------------------------------------------------------------------------
    "mr_v2_bb_pct_b": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",    "params": {"lookback_candles": 3, "oversold_threshold": 32, "current_min": 38, "min_jump": 3.0, "require_sustained": True, "hard_stop": True}},
            {"type": "price_below_vwap",         "params": {"min_gap_pct": -0.7, "max_gap_pct": -8.0}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
            {"type": "volume_spike",             "params": {"min_ratio": 1.1, "max_ratio": 5.0}},
            {"type": "bollinger_bands",          "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.15, "hard_stop": True}},  # pct_b instead of breach
            {"type": "rsi_overbought",           "params": {"min_value": 65}},
            {"type": "reversal_candle",          "params": {"pattern": "hammer", "min_body_pct": 0.08}},
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

        "mr_v9_lookback_sustained": {
        **_MEAN_REV_BASE,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum",      "params": {"lookback_candles": 5, "oversold_threshold": 32, "current_min": 38, "min_jump": 3.0, "require_sustained": True, "hard_stop": True}},
            {"type": "price_below_vwap",           "params": {"min_gap_pct": -0.7, "max_gap_pct": -8.0}},
            {"type": "price_extended_below_ema",   "params": {"ema": 20, "min_gap_pct": -0.7, "max_gap_pct": -10.0}},
            {"type": "volume_spike",               "params": {"min_ratio": 1.1, "max_ratio": 5.0}},
            {"type": "bollinger_bands",            "params": {"band": "lower", "mode": "breach"}},
            {"type": "rsi_overbought",             "params": {"min_value": 65}},
            {"type": "reversal_candle",            "params": {"pattern": "hammer", "min_body_pct": 0.08}},
        ],
        "min_entry_indicators_required": 4,

    },

}


# =============================================================================
# Convenience: all variants in one dict
# =============================================================================
ALL_VARIANTS = {**RANGE_VARIANTS, **MEAN_REV_VARIANTS}


# =============================================================================
# Quick sweep runner — use this to run all variants in one go
# =============================================================================
def run_all_variants(
    db_session,
    symbol: str,
    start,
    end,
    variant_set: dict = None,
    verbose: bool = False,
    show_trades: bool = False,
    export_csv: str = None,
) -> list:
    """
    Run all variants and return sorted results.

    Args:
        show_trades: print per-trade breakdown table under each variant
        export_csv:  filepath to write all trades across all variants as CSV

    Example:
        results = run_all_variants(db, "SOL_USDC", start, end, RANGE_VARIANTS,
                                   show_trades=True, export_csv="trades.csv")
    """
    from backtesting.backtest_engine import BacktestEngine, BacktestProfile

    if variant_set is None:
        variant_set = ALL_VARIANTS

    results = []
    for name, config in variant_set.items():
        profile = BacktestProfile.from_dict(name, config)
        engine  = BacktestEngine(db_session, profile, verbose=verbose)
        result  = engine.run(symbol=symbol, start=start, end=end)
        results.append(result)

    results.sort(key=lambda r: (r.profit_factor, r.total_pnl_pct), reverse=True)

    # ---- Summary table ----
    print(f"\n{'Variant':<35} {'Trades':>7} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>10} {'ProfFact':>9}")
    print("-" * 80)
    for r in results:
        print(
            f"{r.profile_name:<35} {r.total_trades:>7} {r.win_rate:>6.0%} "
            f"{r.avg_pnl_pct:>7.2f}% {r.total_pnl_pct:>9.2f}% {r.profit_factor:>9.2f}x"
        )

    # ---- Per-trade breakdown ----
    if show_trades:
        print("\n" + "=" * 80)
        print("TRADE-BY-TRADE BREAKDOWN")
        print("=" * 80)
        for r in results:
            if r.total_trades == 0:
                print(f"\n{r.profile_name}: (no trades)")
                continue
            print(f"\n-- {r.profile_name} --")
            print(r.trade_log())

    # ---- CSV export ----
    if export_csv:
        import csv
        fields = [
            "variant", "symbol", "trade_num", "outcome",
            "entry_time", "exit_time", "hold_minutes",
            "entry_price", "exit_price", "pnl_pct",
            "exit_reason", "confidence", "volume_ratio", "rsi_at_entry",
        ]
        with open(export_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in results:
                for i, t in enumerate(r.trades, 1):
                    writer.writerow({
                        "variant":      r.profile_name,
                        "symbol":       r.symbol,
                        "trade_num":    i,
                        "outcome":      "WIN" if t.won else ("OPEN" if t.exit_price is None else "LOSS"),
                        "entry_time":   t.entry_time.isoformat() if t.entry_time else "",
                        "exit_time":    t.exit_time.isoformat()  if t.exit_time  else "",
                        "hold_minutes": round(t.hold_minutes, 1) if t.hold_minutes else "",
                        "entry_price":  t.entry_price,
                        "exit_price":   t.exit_price or "",
                        "pnl_pct":      round(t.pnl_pct, 4),
                        "exit_reason":  t.exit_reason,
                        "confidence":   t.entry_details.get("confidence", ""),
                        "volume_ratio": t.entry_details.get("volume_ratio", ""),
                        "rsi_at_entry": t.entry_details.get("rsi", ""),
                    })
        print(f"\n[CSV] Trade log exported -> {export_csv}")

    return results