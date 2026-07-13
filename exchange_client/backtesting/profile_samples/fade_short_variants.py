"""
backtesting/profile_samples/fade_short_variants.py
===================================================
Pruned variant book after the HYPE-free 60-day run (2026-05-03 -> 2026-07-02).

Latest 60-day results (HYPE removed, net of 0.08% round-trip fees):
  mrs_v15_optimised         145 tr  +0.223/tr  +32.33 net  73.8% WR  PF 2.34  maxDD 5.2%
  short_fade_v2c_bbwidthAI  243 tr  +0.118/tr  +28.79 net  65.4% WR  PF 1.75  maxDD 9.9%
  short_fade_v3b_exitpinAI  288 tr  +0.097/tr  +27.99 net  55.6% WR  PF 1.86  maxDD 8.2%

DECISIONS FROM THIS RUN:
  - PRUNED (persistent laggards / rejected mechanisms): v1, v1b_adx18,
    v2b_deep, v2_adxcap, v1_exitpin, v3_exitand, v3c_arm50, mrs_v16b_exit15.
    * arm 0.5: more trailing exits (84 v 68) at lower avg (+0.31 v +0.37) — wash.
    * mrs 15m band exit: -4.28 over 12 fires while SL count stayed at 36; it
      also cost the 60m EMA50-reversion exit (+5.87 over 17 fires). v15's
      exit design wins; multi-TF exit support deprioritised.
  - mrs_v16a had a SCORING-DILUTION BUG: adding the rsi>=55 gate as an 8th
    indicator with min still 4 made 4-of-8 EASIER than 4-of-7 — 104 of its
    167 trades were new entries v15 never took (+0.052/tr, 61% WR drag).
    Fixed here as mrs_v16a2 with min_entry_indicators_required = 5.
  - v3b exit block: converts stop-outs 67 -> 40 into invalidation exits
    averaging -0.22 (median -0.21). Fee-neutral on EV (+27.99 v +28.79) but
    materially better tail: maxDD 8.2% v 9.9%, worst-24h -3.9% v -5.8%.
    Its remaining leak: 36 re-entries within 90 min of an invalidation exit
    on the same symbol net only +0.014/tr at 44% WR (vs +0.109 elsewhere).
    -> v3d below is the same profile with a post-invalidation cooldown,
    PENDING the engine change described in its comment block.

ENGINE SEMANTICS (verified in backtest_engine.py):
  - exit_indicators are HOLD conditions on exit_timeframe; the position
    exits via trend_invalidation when passing count < min_exit_indicators_required
    (checked after min_position_age_for_trend_check).
  - hard_stop must live INSIDE params (engine ~line 391); top-level is a no-op.
  - Every passing indicator counts toward min_entry_indicators_required —
    a "gate" indicator therefore also adds a scoring point. When adding a
    hard gate, bump the min by 1 to keep selectivity constant.

HYPE_USDC removed at master-list level (May HYPE: 82 tr, -10.74 net, 40.2% WR
was mrs_v15's entire prior underperformance).
"""
_MEAN_REV_SHORT_BASE = {
    "display_name": "mean_reversion_short_profile",
    "strategy_type": "mean_reversion_short",
    "entry_timeframe": "15",
    "take_profit_pct": 1.2,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 15,
    "sl_cooldown_minutes": 90,
    "tp_cooldown_minutes": 35,
    "max_open_positions_per_profile": 2,
    "min_signal_confidence": 75.0,
    "min_volume_ratio": 1.2,
    "use_trend_filter": False,
    "use_entry_filter": True,
    "max_position_hours": 4,
    "use_market_regime_filter": False,
    # Fill realism + safeguard defaults for this book
    "stop_loss_slippage_pct": 0.1,
    "max_consecutive_stop_losses": 2,
    "consecutive_sl_lock_hours": 24,
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
    "entry_indicators": [
        # Core short momentum gate: RSI peaked OB then dropped sharply and is falling
        {"type": "rsi_overbought_momentum",  "params": {"lookback_candles": 5, "overbought_threshold": 68, "current_max": 65, "min_drop": 4.0, "require_sustained": True, "sustained_fall_mode": "net", "drop_required": True}},
        # Price stretched above VWAP
        {"type": "price_above_vwap",         "params": {"min_gap_pct": 0.5, "max_gap_pct": 8.0}},
        # Volume spike confirms distribution / buying climax
        {"type": "volume_spike",             "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
        # Price in upper portion of BB — near the upper band
        {"type": "bollinger_bands",          "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.80, "max_pct_b": 1.10}},
        # Not deeply oversold — blocks shorts in a genuine downtrend that's already extended
        {"type": "rsi_overbought",           "params": {"max_value": 35,"side": "short"}},
    ],
    "min_entry_indicators_required": 4,
    "exit_indicators": [
        # Exit short when price reverts within 0.5% of EMA50 on 60m (mean reversion complete)
        {"type": "price_extended_above_ema",
        "params": {"ema": 50, "min_gap_pct": 0.5, "max_gap_pct": 10.0}},
        # Also exit if RSI drops below 35 (already oversold — short has run its course)
        {"type": "rsi_overbought",
        "params": {"side": "short", "max_value": 35}},
    ],
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_exit_indicators_required": 1,
    "min_position_age_for_trend_check": 30,  # don't check first 30 mins
    "exit_timeframe": "60",
}



# ---------------------------------------------------------------------------
# Base for the v3 exit/geometry variants. Mirrors short_fade_v2c_bbwidthAI
# (best fade over 60 days). If v2c's entry logic changes, change it here too.
# ---------------------------------------------------------------------------
_FADE_V2C_BASE = {
    "symbols": [ 'BTC_USDC', 'ETH_USDC', 'SOL_USDC', 'XRP_USDC', 'ZEC_USDC'],
    "strategy_type": "short_trend_following",
    "entry_timeframe": "15",
    "trend_timeframe": "60",
    "sl_cooldown_minutes": 90,
    "tp_cooldown_minutes": 35,
    "take_profit_pct": 1.2,
    "stop_loss_pct": 0.9,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.6,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 20,
    "min_signal_confidence": 70.0,
    "min_volume_ratio": 0,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 5,
    "use_market_regime_filter": False,
    # Fill realism + safeguard defaults for this book
    "stop_loss_slippage_pct": 0.1,
    "max_consecutive_stop_losses": 2,
    "consecutive_sl_lock_hours": 24,
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "trend",
    "min_position_age_for_trend_check": 45,
    "trading_hours": [],
    "trend_indicators": [
        {"type": "ema_cross", "params": {"direction": "down", "hard_stop": True}},
        {"type": "adx_regime", "params": {"min_adx": 0, "max_adx": 32, "hard_stop": True}},
    ],
    "min_indicators_required": 2,
    "entry_indicators": [
        {"type": "volume_spike", "params": {"min_ratio": 0, "max_ratio": 0.6, "hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.6, "max_pct_b": 1.2, "hard_stop": True}},
        {"type": "rsi_range", "params": {"min": 45, "max": 65, "invert": True, "hard_stop": True}},
        {"type": "bb_width_regime", "params": {"required_direction": "not_expanding", "lookback": 4}},
    ],
    "min_entry_indicators_required": 4,
}

FADE_SHORT_VARIANTS = {


 
# ---------------------------------------------------------------------------
# 3. EXPLORATORY — v2 + bb_width_regime "not_expanding" on the entry TF.
#    Untested hypothesis (band-width data isn't in the trade CSV so it can't
#    be validated by replay): expanding bands during the rally = breakout in
#    progress, contracting/stable = drift rally, which is what the fade
#    wants. If this doesn't beat v2 head-to-head, drop it — one extra
#    condition is only worth carrying if it pays.
    "short_fade_v2c_bbwidthAI":{
        "display_name": "short_fade_v2c_bbwidthAI",
        "symbols": [ 'BTC_USDC', 'ETH_USDC', 'SOL_USDC', 'XRP_USDC', 'ZEC_USDC'],
        "strategy_type": "short_trend_following",
        "entry_timeframe": "15",
        "trend_timeframe": "60",
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.5,
        "arm_trailing_stop_pct": 0.6,
        "use_trailing_stop": True,
        "signal_cooldown_minutes": 20,
        "min_signal_confidence": 70.0,
        "min_volume_ratio": 0,
        "use_trend_filter": True,
        "use_entry_filter": True,
        "max_position_hours": 5,
        "use_market_regime_filter": True,
        "regime_timeframe": "240",  # 4h sustained-rally guard (aligned with prod, sweep 49d)
        # Fill realism + safeguard defaults for this book
        "stop_loss_slippage_pct": 0.1,
        "max_consecutive_stop_losses": 2,
        "consecutive_sl_lock_hours": 24,
        "use_trend_invalidation_exit": True,
        "trend_invalidation_indicators": "trend",
        "min_position_age_for_trend_check": 45,
        "trading_hours": [],
        "trend_indicators": [
            {"type": "ema_cross", "params": {"direction": "down", "hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 0, "max_adx": 32, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "volume_spike", "params": {"min_ratio": 0, "max_ratio": 0.6, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.6, "max_pct_b": 1.2, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 45, "max": 65, "invert": True, "hard_stop": True}},
            {"type": "bb_width_regime", "params": {"required_direction": "not_expanding", "lookback": 4}},
        ],
        "min_entry_indicators_required": 4,
    },    

    "mrs_v15_optimised": {
        **_MEAN_REV_SHORT_BASE,
        "use_market_regime_filter": True,
        "regime_timeframe": "240",  # 4h sustained-rally guard (aligned with prod bullet_shorts_v15AI)
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            # Gate 1: price must be extended ≥ 2% above 60m EMA50
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0},
             "hard_stop": True},
            # Gate 2: caps entries when 60m RSI is already elevated (≥70 = trending too hard)
            {"type": "rsi_range",
             "params": {"min": 70, "max": 100},
             "hard_stop": True},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 68,
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True}},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought",   "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            # OB zone (70-100): passes when RSI < 70 — price peaked OB, now just off the top
            {"type": "rsi_range",        "params": {"min": 70, "max": 100}},
            # Fallen zone (45-60): passes when RSI < 45 or > 60 — RSI has deeply reverted
            # These two zones are INDEPENDENT quality signals, not alternatives — both can fire
            # at RSI 60-69, contributing 2 separate points (best entry zone). Do NOT group them.
            {"type": "rsi_range",        "params": {"min": 45, "max": 60}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
        ],
        "min_entry_indicators_required": 4,
        "min_signal_confidence": 72.0,
        "min_volume_ratio": 1.0,
        # Exit: leave when price reverts to within 2% of EMA50 (lock in gain early)
        "exit_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0}},
        ],
        "use_trend_invalidation_exit": True,
        "trend_invalidation_indicators": "exit",
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 0,
        "exit_timeframe": "60",
    },

# ---------------------------------------------------------------------------
# v3.2 — v2c + band-riding exit, pct_b-only (aggressive).
#    Exit when pct_b alone is still > 0.9 after 45 min. Strongest single
#    separator in the data: 89% of stop-outs end pinned >= 0.9 vs 3% of
#    wins. Expect a large share of -0.9 stop-outs converted into smaller
#    invalidation losses; risk is clipping slow winners that entered above
#    0.9 (see header). Run head-to-head with v3.1.
    "short_fade_v3b_exitpinAI": {
        **_FADE_V2C_BASE,
        "display_name": "short_fade_v3b_exitpinAI",
        "trend_invalidation_indicators": "exit",
        "sl_cooldown_minutes": 15,
        "tp_cooldown_minutes": 15,
        "exit_timeframe": "15",
        "min_position_age_for_trend_check": 45,
        "exit_indicators": [
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": -2.0, "max_pct_b": 0.9}},
        ],
        "min_exit_indicators_required": 1,
    },

# ---------------------------------------------------------------------------
# mrs_v16a2 — RSI >= 55 hard floor, scoring-dilution FIXED (min 4 -> 5).
#    The floor now behaves as a true gate: 4 of the original 7 signals plus
#    the mandatory 8th. Replay basis (v15 trades with rsi>=55): +0.263/tr,
#    75.9% WR. The buggy min-4 version took 104 unlocked off-thesis trades.
    "mrs_v16a2_rsi55AI": {
        **_MEAN_REV_SHORT_BASE,
        "display_name": "mrs_v16a2_rsi55AI",
        "use_trend_filter": True,
        "trend_timeframe": "60",
        "trend_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0, "hard_stop": True}},
            {"type": "rsi_range",
             "params": {"min": 70, "max": 100, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "rsi_overbought_momentum", "params": {
                "lookback_candles": 5, "overbought_threshold": 68,
                "current_max": 70, "min_drop": 5.0,
                "require_sustained": True, "sustained_fall_mode": "net",
                "drop_required": True}},
            {"type": "bollinger_bands",  "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.85}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": 2.0, "max_gap_pct": 15.0}},
            {"type": "rsi_overbought",   "params": {"side": "short", "max_value": 35, "hard_stop": True}},
            {"type": "rsi_range",        "params": {"min": 70, "max": 100}},
            {"type": "rsi_range",        "params": {"min": 45, "max": 60}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.2, "max_ratio": 2.4}},
            # Hard floor — only fade strength (RSI >= 55), never weakness
            {"type": "rsi_range",        "params": {"min": 55, "max": 100, "invert": True, "hard_stop": True}},
        ],
        # FIXED: 5, not 4 — the 8th indicator's pass-point must not dilute
        # the original 4-of-7 selectivity (engine counts every pass).
        "min_entry_indicators_required": 5,
        "min_signal_confidence": 78.0,
        "min_volume_ratio": 1.2,
        "exit_indicators": [
            {"type": "price_extended_above_ema",
             "params": {"ema": 50, "min_gap_pct": 2.0, "max_gap_pct": 10.0}},
        ],
        "use_trend_invalidation_exit": True,
        "trend_invalidation_indicators": "exit",
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 0,
        "exit_timeframe": "60",
    },

}
