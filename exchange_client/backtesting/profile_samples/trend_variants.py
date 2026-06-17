

_TF_BASE = {
    "strategy_type": "trend_following",
    "entry_timeframe": "15",
    "take_profit_pct": 0.8,
    "stop_loss_pct": 0.7,
    "trailing_stop_pct": 0.5,
    "arm_trailing_stop_pct": 0.5,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 15,
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
    # BASELINES — faithful reproductions of live profiles for comparison
    # -------------------------------------------------------------------------
    "tf_base_15m_trend": {
        **_TF_BASE,
    },

    "tf_v1_TSL": {
        **_TF_BASE,
        "trailing_stop_pct": 0.2,
        "arm_trailing_stop_pct": 0.45,
    },

    "tf_v2_RSIMomentum": {
        **_TF_BASE,
        "trend_indicators": [
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
    },

    "tf_v3_BBchange": {
        **_TF_BASE,
        "entry_indicators": [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.55,"hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 57,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02,"max_slope_pct":0.25,"hard_stop": True}},
            {"type": "rsi_momentum", "params": {"min_momentum": 0.5, "max_momentum": 3.0}},
        ],
        "min_entry_indicators_required": 7,

    },

    "tf_v3_BB_rsi": {
        **_TF_BASE,
        "entry_indicators": [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.55,"hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 57,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "rsi_momentum", "params": {"min_momentum": 0.5, "max_momentum": 3.0}},
        ],
        "min_entry_indicators_required": 6,

    },


    "tf_v4_TSL_mom_bb": {
        **_TF_BASE,
        "trailing_stop_pct": 0.2,
        "arm_trailing_stop_pct": 0.45,
        "trend_indicators": [
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.0, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
        "entry_indicators": [
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "reversal_candle", "params": {"pattern": "hammer", "min_body_pct": 0.08, "max_drop_from_close_pct": 0.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":0.05, "max_pct_b": 0.55,"hard_stop": True}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 57,"use_momentum": True, "early_threshold":45, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 63, "hard_stop": True}},
            {"type": "price_vs_vwap",   "params": {}},
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02,"max_slope_pct":0.25,"hard_stop": True}},
            {"type": "rsi_momentum", "params": {"min_momentum": 0.5, "max_momentum": 3.0}},
        ],
        "min_entry_indicators_required": 7,

    },

    "tf_v5_15m_trend_adxhard": {
        **_TF_BASE,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015,"hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b":-0.05, "max_pct_b": 0.95}},
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 60, "hard_stop": True}},
            {"type": "rsi_overbought",  "params": {"min_value": 68, "lookback_candles":5, "hard_stop": True}},
        ],
    },

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

    # Strategy B — "EMA slope + BB hard stop trend + RSI momentum entry"
    # More frequent than A (~42 trades / 14d / 6 symbols), still 71% WR.
    # Key insight: BB pct_b 0.0–0.55 as a HARD STOP on 60m trend filter forces
    # entries only when HTF price is in the lower half of the band (pullback confirmed).
    # rsi_momentum(0.5–4.0) on entry ensures RSI is actively accelerating upward.
    "opt_v2_ema_bbhard_rsimom": {
        **_TF_BASE,
        "take_profit_pct":       1.2,
        "stop_loss_pct":         0.8,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.6,
        "trend_indicators": [
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.55, "hard_stop": True}},
            {"type": "adx_regime",     "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought", "params": {"min_value": 68, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.6}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 43, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            {"type": "rsi_momentum",   "params": {"min_momentum": 0.5, "max_momentum": 4.0}},
            {"type": "price_vs_vwap",  "params": {}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
    },

    # -------------------------------------------------------------------------
    # BREAKOUT CONTINUATION VARIANTS  (trend continuation, not reversal)
    # Trend filter: ema_cross + ADX >= 28 (same as opt_v1)
    # Entry change: RSI momentum shift above 50 + volume spike, NOT oversold bounce
    # Rationale: rsi_reversal_momentum identifies 0.4–0.8% moves → can't cover fees.
    #            Breakout signals identify 1.0–1.5%+ moves where TP=1.2% is reachable.
    # -------------------------------------------------------------------------

    # Breakout v1: RSI>55 momentum + BB pct_b rising + volume spike
    # bb_pct_b_momentum rising = price is actively moving toward upper band (genuine breakout direction).
    # Avoids false breakouts where price briefly spikes then reverses.
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
    # Steeper EMA slope (0.03%+) means the trend is accelerating, not just established.
    # These are the highest-velocity trend moments where continuation is most likely.
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

    # Breakout v3: Strict — all three breakout signals must fire + trailing arm high
    # If the breakout has: pct_b momentum + steep slope + high volume, let it run to 1.5%.
    "opt_v1_bkout_strict": {
        **_TF_BASE,
        "take_profit_pct":       1.5,
        "stop_loss_pct":         0.8,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 1.0,
        "trend_indicators": [
            {"type": "ema_cross",  "params": {}},
            {"type": "adx_regime", "params": {"min_adx": 32, "max_adx": 65, "hard_stop": True}},
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.025, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_threshold",     "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 50, "hard_stop": True}},
            {"type": "rsi_momentum",      "params": {"min_momentum": 2.0, "max_momentum": 8.0}},
            {"type": "rsi_overbought",    "params": {"min_value": 72, "hard_stop": True}},
            {"type": "bb_pct_b_momentum", "params": {"required_direction": "rising", "lookback": 3}},
            {"type": "volume_spike",      "params": {"min_ratio": 2.0}},
            {"type": "ema_slope",         "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.025, "hard_stop": True}},
            {"type": "price_vs_vwap",     "params": {}},
        ],
        "min_entry_indicators_required": 6,
    },

    # Breakout + regime filter: 60m BB not expanding (not already in extended move on HTF)
    # bb_width_regime "not_expanding" on 60m = bands are stable or contracting.
    # Blocks entries when the HTF is already in a volatile surge — avoids chasing.
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

    # Strategy C — "EMA slope + BB hard stop trend + RSI momentum entry (tighter TP:SL)"
    # Same indicator logic as B, tighter TP/SL ratio (1.0:0.6 = 1.67:1).
    # 72% WR, 2.33x profit factor, 25 trades / 14d / 6 symbols.
    "opt_v3_ema_bbhard_rsimom_tight": {
        **_TF_BASE,
        "take_profit_pct":       1.0,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.4,
        "arm_trailing_stop_pct": 0.5,
        "trend_indicators": [
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.55, "hard_stop": True}},
            {"type": "adx_regime",     "params": {"min_adx": 22, "max_adx": 60}},
            {"type": "rsi_overbought", "params": {"min_value": 68, "lookback_candles": 5, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -0.5, "max_gap_pct": 1.5}},
            {"type": "bollinger_bands","params": {"band": "lower", "mode": "pct_b", "min_pct_b": -0.05, "max_pct_b": 0.6}},
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 43, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            {"type": "rsi_momentum",   "params": {"min_momentum": 0.5, "max_momentum": 4.0}},
            {"type": "price_vs_vwap",  "params": {}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
    },

}




