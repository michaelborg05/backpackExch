

_TF_BASE = {
    "strategy_type": "trend_following",
    "entry_timeframe": "15",
    "take_profit_pct": 0.8,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 15,
    "max_open_positions_per_profile": 2,
    "min_signal_confidence": 70.0,
    "min_volume_ratio": 1.1,
    "use_trend_filter": True,
    "trend_timeframe": "60",
    "use_entry_filter": True,
    "max_position_hours": 12,
    "use_market_regime_filter": True,
    "trading_hours": [
        {"day_of_week": 0, "start_time": "05:00", "end_time": "12:00", "enabled": True},
        {"day_of_week": 0, "start_time": "15:00", "end_time": "21:00", "enabled": True},
        {"day_of_week": 1, "start_time": "02:00", "end_time": "23:00", "enabled": True},
        {"day_of_week": 2, "start_time": "01:00", "end_time": "12:00", "enabled": True},
        {"day_of_week": 2, "start_time": "14:00", "end_time": "23:00", "enabled": True},
        {"day_of_week": 3, "start_time": "03:00", "end_time": "12:00", "enabled": True},
        {"day_of_week": 3, "start_time": "14:00", "end_time": "21:00", "enabled": True},
        {"day_of_week": 4, "start_time": "03:00", "end_time": "12:00", "enabled": True},
        {"day_of_week": 4, "start_time": "14:00", "end_time": "21:00", "enabled": True},
    ],
    "trend_indicators": [
        {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015,"hard_stop": True}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95}},
        {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
        {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
    ],
    "min_indicators_required": 3,
    "entry_indicators": [
        {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
        {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.65}},
        {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 57,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
        {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
        {"type": "price_vs_vwap",   "params": {}},
        {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02,"max_slope_pct":0.25,"hard_stop": True}},
    ],
    "min_entry_indicators_required": 6,

}

TREND_VARIANTS = {

    # -------------------------------------------------------------------------
    # OPTIMIZER-DISCOVERED VARIANTS  (5-iteration indicator search, Jun 2026)
    # Tested across SOL/ETH/BTC/HYPE/BNB/XRP on 14-day window
    # -------------------------------------------------------------------------

    # Strategy A — "EMA cross + RSI reversal momentum"
    # Precision filter: only enters after RSI bounces from oversold in a strong
    # trending market (ADX ≥ 28). Very selective (~10 trades / 14d / 6 symbols)
    # but highly accurate: 80% WR, 3.04x profit factor.
    "opt_v1_emacross_revmom": {
        **_TF_BASE,
        "take_profit_pct":       0.8,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.4,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",     "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 4,
        "entry_indicators": [
            {"type": "price_vs_ema",           "params": {"ema": 20, "min_gap_pct": 0.0, "max_gap_pct": 2.5}},
            {"type": "rsi_reversal_momentum",  "params": {"lookback_candles": 6, "oversold_threshold": 38, "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "bollinger_bands",        "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.6}},
            {"type": "rsi_threshold",          "params": {"period": 14, "min_value": 52, "use_momentum": False, "early_threshold": 37, "hard_stop": True}},
            {"type": "rsi_overbought",         "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",          "params": {}},
            {"type": "ema_slope",              "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
    },

    # -------------------------------------------------------------------------
    # BREAKOUT CONTINUATION VARIANTS  (trend continuation, not reversal)
    # Trend filter: ema_cross + ADX >= 28 (same as opt_v1)
    # Entry change: RSI momentum shift above 50 + volume spike, NOT oversold bounce
    # -------------------------------------------------------------------------

    # Breakout v1: RSI>55 momentum + BB pct_b rising + volume spike
    "opt_v1_bkout_pctb_mom": {
        **_TF_BASE,
        "take_profit_pct":       1.2,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.8,
        "trend_indicators": [
            {"type": "ema_cross",  "params": {}},
            {"type": "adx_regime", "params": {"min_adx": 30, "max_adx": 65, "hard_stop": True}},
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_threshold",     "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 50, "hard_stop": True}},
            {"type": "rsi_momentum",      "params": {"min_momentum": 1.5, "max_momentum": 8.0}},
            {"type": "rsi_overbought",    "params": {"min_value": 72, "hard_stop": True}},
            {"type": "bb_pct_b_momentum", "params": {"required_direction": "rising", "lookback": 3}},
            {"type": "volume_spike",      "params": {"min_ratio": 1.5}},
            {"type": "ema_slope",         "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "price_vs_vwap",     "params": {}},
        ],
        "min_entry_indicators_required": 5,
    },

    # Breakout v2: Steep EMA slope (strong trend velocity) + high volume + RSI>55
    "opt_v1_bkout_steep_slope": {
        **_TF_BASE,
        "take_profit_pct":       1.2,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.8,
        "trend_indicators": [
            {"type": "ema_cross",  "params": {}},
            {"type": "adx_regime", "params": {"min_adx": 30, "max_adx": 65, "hard_stop": True}},
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.025, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 50, "hard_stop": True}},
            {"type": "rsi_momentum",   "params": {"min_momentum": 1.0, "max_momentum": 8.0}},
            {"type": "rsi_overbought", "params": {"min_value": 72, "hard_stop": True}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.5}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.03, "hard_stop": True}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -0.3, "max_gap_pct": 1.5}},
            {"type": "price_vs_vwap",  "params": {}},
        ],
        "min_entry_indicators_required": 5,
    },

    # Breakout + regime filter: 60m BB not expanding
    "opt_v1_bkout_regime": {
        **_TF_BASE,
        "take_profit_pct":       1.2,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.8,
        "trend_indicators": [
            {"type": "ema_cross",       "params": {}},
            {"type": "adx_regime",      "params": {"min_adx": 30, "max_adx": 65, "hard_stop": True}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "bb_width_regime", "params": {"required_direction": "not_expanding", "lookback": 4}},
        ],
        "min_indicators_required": 4,
        "entry_indicators": [
            {"type": "rsi_threshold",     "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 50, "hard_stop": True}},
            {"type": "rsi_momentum",      "params": {"min_momentum": 1.5, "max_momentum": 8.0}},
            {"type": "rsi_overbought",    "params": {"min_value": 72, "hard_stop": True}},
            {"type": "bb_pct_b_momentum", "params": {"required_direction": "rising", "lookback": 3}},
            {"type": "volume_spike",      "params": {"min_ratio": 1.5}},
            {"type": "ema_slope",         "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "price_vs_vwap",     "params": {}},
        ],
        "min_entry_indicators_required": 5,
    },

    # ==========================================================================
    # V2 OPTIMISER VARIANTS — Jun 2026 (40-day window, per-minute price ticks)
    # 4 iterations across 7 symbols (SOL/ETH/BTC/HYPE/BNB/XRP/ZEC).
    # Goal: ≥0.15% avg PnL, ≥60% win rate on 60m-trend / 15m-entry profiles.
    #
    # Exit indicator semantics (is_bullish check per 15m candle close):
    #   hard_stop=True → exit immediately when that condition fails
    #   soft indicators → stay in while ≥ min_exit_indicators_required pass
    #
    # Results: 1=CHAMPION (29T, 59% WR, 0.19% avg, 1.82x PF)
    # ==========================================================================

    # ── 1. CHAMPION — revmom entry + exit RSI overbought at 68 ─────────────────
    # RSI68 exit cuts BNB losses early (RSI briefly spikes to 68 before SL),
    # saving ~0.24% per losing BNB trade vs the default 60m trend-check exit.
    "tf_iter3_exit_rsi68": {
        **_TF_BASE,
        "regime_timeframe": "240",  # sweep 49d: 4h best for this profile (aligned with prod)
        "take_profit_pct":       0.8,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.4,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",     "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 4,
        "entry_indicators": [
            {"type": "price_vs_ema",          "params": {"ema": 20, "min_gap_pct": 0.0, "max_gap_pct": 2.5}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38, "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.6}},
            {"type": "rsi_threshold",         "params": {"period": 14, "min_value": 52, "use_momentum": False, "early_threshold": 37, "hard_stop": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",         "params": {}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
        "trend_invalidation_indicators": "exit",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 68, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
        ],
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    },

    # ── 2. RUNNER-UP — same entry + exit overbought at 72 ──────────────────────
    "tf_v1_revmom_exitA": {
        **_TF_BASE,
        "take_profit_pct":       0.8,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.4,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",     "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 4,
        "entry_indicators": [
            {"type": "price_vs_ema",          "params": {"ema": 20, "min_gap_pct": 0.0, "max_gap_pct": 2.5}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38, "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.6}},
            {"type": "rsi_threshold",         "params": {"period": 14, "min_value": 52, "use_momentum": False, "early_threshold": 37, "hard_stop": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",         "params": {}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
        "trend_invalidation_indicators": "exit",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 72, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
        ],
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    },

    # ── 3. THIRD — same as champion but exit overbought at 67 ──────────────────
    "tf_iter4_exit_rsi67": {
        **_TF_BASE,
        "take_profit_pct":       0.8,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.4,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",     "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 4,
        "entry_indicators": [
            {"type": "price_vs_ema",          "params": {"ema": 20, "min_gap_pct": 0.0, "max_gap_pct": 2.5}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38, "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.6}},
            {"type": "rsi_threshold",         "params": {"period": 14, "min_value": 52, "use_momentum": False, "early_threshold": 37, "hard_stop": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",         "params": {}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
        "trend_invalidation_indicators": "exit",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 67, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
        ],
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    },

    # ==========================================================================
    # V3 INDICATOR SEARCH — Jun 2026 (40-day, 3-iteration trend+entry search)
    # 791 variants tested across 7 symbols. New direction: ADX 22 + RSI zone
    # entry dramatically outperforms the sustained revmom entry from prior runs.
    #
    # Core discovery: simpler 3-indicator entry (RSI 40-58 zone + looser revmom
    # + EMA slope) beats the 7-indicator champion entry at 89% WR vs 59%.
    # ADX 22 (vs prior 28) catches more valid trend setups without degrading quality.
    #
    # Exit: unchanged — champion RSI68 exit set.
    #
    # Rank 1 all-time: 9T, 89% WR, 0.48% avg, 8.25x PF (or 0.56% avg with TP=1.2)
    # Rank 23:        17T, 82% WR, 0.43% avg, 5.02x PF (sustained revmom variant)
    # ==========================================================================

    # ── V3 CHAMPION — ADX22 + RSI zone entry (base TP/SL) ─────────────────────
    # Trend: EMA cross + ADX22 hard-stop + RSI<60 ceiling.
    # Entry: RSI must be IN the 40-58 zone (pullback zone within uptrend) +
    #        looser revmom (no sustained requirement) + EMA slope rising.
    # ADX 22 vs prior 28: earlier trend detection, same quality.
    # require_sustained=False: allows entries on the first candle of RSI recovery.
    "tf_v3_rsizone_adx22": {
        **_TF_BASE,
        "take_profit_pct":       0.8,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.4,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "adx_regime",     "params": {"min_adx": 22, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_range",             "params": {"min": 40, "max": 58, "invert": True}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 4, "oversold_threshold": 40, "current_min": 43, "min_jump": 3.0, "require_sustained": False}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "trend_invalidation_indicators": "exit",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 68, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
        ],
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    },

    # ── V3 CHAMPION — wide TP/SL variant (highest scoring configuration) ───────
    # Identical indicators to tf_v3_rsizone_adx22 but TP=1.2, SL=0.7.
    # Higher TP captures larger moves; slightly wider SL gives trades room.
    # Score=142.06, 9T, 89% WR, 0.56% avg, 8.25x PF.
    "tf_v3_rsizone_adx22_tp12": {
        **_TF_BASE,
        "take_profit_pct":       1.2,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.6,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "adx_regime",     "params": {"min_adx": 22, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_range",             "params": {"min": 40, "max": 58, "invert": True}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 4, "oversold_threshold": 40, "current_min": 43, "min_jump": 3.0, "require_sustained": False}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "trend_invalidation_indicators": "exit",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 68, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
        ],
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    },

    # ── V3 HIGH-VOLUME — sustained revmom + RSI zone (17T, 82% WR, 0.43% avg) ─
    # Same ADX22 trend as champion but entry uses sustained revmom (require_sustained=True)
    # with harder oversold threshold (45 vs 40). RSI zone 40-58 still gates entry zone.
    # Produces ~2x more trades than the loose revmom variant with only modest quality drop.
    # 17T, 82% WR, 0.43% avg, 5.02x PF. Score=112.
    "tf_v3_rsizone_17t": {
        **_TF_BASE,
        "regime_timeframe": "60",   # sweep 49d: 1h best; 4h hurt this profile (aligned with prod)
        "take_profit_pct":       0.8,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.4,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "adx_regime",     "params": {"min_adx": 22, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_range",             "params": {"min": 40, "max": 58, "invert": True}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 45, "current_min": 44, "min_jump": 5.0, "require_sustained": True, "hard_stop": True}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "trend_invalidation_indicators": "exit",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 68, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
        ],
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    },

    # ==========================================================================
    # V4 ITERATION — Jul 15 2026. Focused sweep on the two prod long profiles
    # (tf_v3_rsizone_17t strong / tf_iter3_exit_rsi68 weak) over 3 tick windows
    # (early-indep 27d, 30d, 57d — tick data only reaches 2026-05-19).
    #
    # Winner tf_v4_zone3855_tp9: two changes to tf_v3_rsizone_17t only —
    #   RSI entry zone 40-58 -> 38-55 (deeper pullback), TP 0.8 -> 0.9.
    #   PF 4.02x / 6.70x / 5.60x across the 3 windows (baseline 1.67/2.15/1.86),
    #   avg PnL ~0.5% (baseline ~0.18%), WR 80-89%. ~half the trades, ~3x quality.
    #
    # Confirmed NEGATIVES this run (see memory tf_zone3855_tp9_champion):
    #   - widening trading_hours = overfit (great 30d, collapses 57d) — keep curated
    #   - pure momentum entries (rsi_momentum / bb_pct_b rising) fail
    #   - regime filter ON @ 60m beats off and 240m
    #   - dropping ZEC not needed once zone 38-55 is used
    #
    # tf_v4_tp9 and tf_v4_zone3855_tp8 are the lever-isolation siblings kept so
    # the wider-window (candle-mode 90d) test brackets the winner rather than
    # confirming one config in isolation (14T over 57d is a low sample).
    # ==========================================================================

    # ── V4 WINNER — deeper RSI zone (38-55) + TP 0.9 ──────────────────────────
    "tf_v4_zone3855_tp9": {
        **_TF_BASE,
        "regime_timeframe": "60",
        "take_profit_pct":       0.9,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.35,
        "arm_trailing_stop_pct": 0.45,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "adx_regime",     "params": {"min_adx": 22, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_range",             "params": {"min": 38, "max": 55, "invert": True}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 45, "current_min": 44, "min_jump": 5.0, "require_sustained": True, "hard_stop": True}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "trend_invalidation_indicators": "exit",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 68, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
        ],
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    },

    # ── V4 sibling — TP 0.9 only (zone unchanged 40-58); more trades, robust 2nd
    # Isolates the TP lever. 57d: 18T, 72% WR, 0.31% avg, 2.42x PF.
    "tf_v4_tp9": {
        **_TF_BASE,
        "regime_timeframe": "60",
        "take_profit_pct":       0.9,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.35,
        "arm_trailing_stop_pct": 0.45,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "adx_regime",     "params": {"min_adx": 22, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_range",             "params": {"min": 40, "max": 58, "invert": True}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 45, "current_min": 44, "min_jump": 5.0, "require_sustained": True, "hard_stop": True}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "trend_invalidation_indicators": "exit",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 68, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
        ],
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    },

    # ── V4 sibling — deeper zone (38-55) at base TP 0.8; isolates the zone lever
    "tf_v4_zone3855_tp8": {
        **_TF_BASE,
        "regime_timeframe": "60",
        "take_profit_pct":       0.8,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.4,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "adx_regime",     "params": {"min_adx": 22, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_range",             "params": {"min": 38, "max": 55, "invert": True}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 45, "current_min": 44, "min_jump": 5.0, "require_sustained": True, "hard_stop": True}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "trend_invalidation_indicators": "exit",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 68, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
        ],
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    },

    # ── noregime test variants (kept for reference) ─────────────────────────────
    "tf_iter4_exit_rsi67_noregime": {
        **_TF_BASE,
        "use_market_regime_filter": False,
        "take_profit_pct":       0.8,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.4,
        "trend_indicators": [
            {"type": "ema_cross",      "params": {}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime",     "params": {"min_adx": 28, "max_adx": 65, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 60, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 4,
        "entry_indicators": [
            {"type": "price_vs_ema",          "params": {"ema": 20, "min_gap_pct": 0.0, "max_gap_pct": 2.5}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 38, "current_min": 45, "min_jump": 5.0, "require_sustained": True}},
            {"type": "bollinger_bands",       "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.05, "max_pct_b": 0.6}},
            {"type": "rsi_threshold",         "params": {"period": 14, "min_value": 52, "use_momentum": False, "early_threshold": 37, "hard_stop": True}},
            {"type": "rsi_overbought",        "params": {"min_value": 65, "hard_stop": True}},
            {"type": "price_vs_vwap",         "params": {}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "max_slope_pct": 0.25, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
        "trend_invalidation_indicators": "exit",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 67, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
        ],
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    },

}
