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
    "max_open_positions_per_profile": 2,
    "min_signal_confidence": 66.0,
    "min_volume_ratio": 1.2,
    "use_trend_filter": True,
    "trend_timeframe": "60",
    "entry_timeframe": "15",
    "use_entry_filter": True,
    "max_position_hours": 6,
    "use_market_regime_filter": False,
    "use_trend_invalidation_exit":      True,
    "trend_invalidation_indicators":    "entry",  # default: 4hr trend indicators
    "min_position_age_for_trend_check": 50,        # minutes; 0 = check immediately

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

    # =========================================================================
    # TICK-MODE OPTIMIZER RESULTS  (3-iteration search, 60d, 6 symbols, tick SL/TP)
    # These are validated at tick-level. Key discoveries: SL must be 0.9-1.0% to
    # survive intracandle wicks; ADX filter (18-65) is essential to block choppy
    # and extreme-trending market conditions.
    # =========================================================================

    # ── opt_v4: deep displacement + hard RSI bounce — ALL-TIME BEST ──────────
    # Trend (60m): price must be 2–5% below EMA50 (deep crash only) AND RSI < 38
    # (hard gate — blocks knife-catching in gradual declines that stay below 38).
    # Entry (15m): RSI must have jumped 5+ points from below 28 in 6 candles
    # (sharp bounce from genuine panic) + VWAP below (hard) + BB lower zone + volume.
    # Backtest (60d, 4 symbols): 11 trades, WR=73%, PF=2.47x, avg_pnl=+0.28%
    # The 2% depth floor is the key change vs v3 — kills all "shallow" knife catches.
    "mr_opt_v4_deep_disp_rsi_bounce": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.0,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.5,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        # Optimizer used default mode ("trend") not "entry" — strict entry indicators
        # (RSI<42 hard, VWAP hard, volume hard) must NOT be used as exit triggers
        # or they'll cut trades the moment the mean reversion bounce starts.
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,
        "trend_indicators": [
            # Deep crash gate: price must be 2–5% below EMA50 (not just touching)
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -2.0, "max_gap_pct": -5.0}},
            # Hard RSI cap: blocks entries when 60m RSI >= 38 (gradual downtrend filter)
            {"type": "rsi_overbought", "params": {"min_value": 38, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            # Strict bounce: RSI jumped 5+ points from below 28 → confirms panic exhaustion
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6, "oversold_threshold": 28, "current_min": 32,
                "min_jump": 5.0, "require_sustained": False, "hard_stop": True,
            }},
            # Hard VWAP gate: price must be below VWAP (not just soft signal)
            {"type": "price_below_vwap",  "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0, "hard_stop": True}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.25}},
            # Hard RSI ceiling: don't enter if 15m RSI already climbed above 42
            {"type": "rsi_overbought",    "params": {"min_value": 42, "hard_stop": True}},
            {"type": "volume_spike",      "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 1.0,
    },

    # ── opt_v5: tight SL variant — highest total PnL in 60d window ──────────
    # Same deep-displacement signal as v4 but SL cut to 0.6% and TSL tightened
    # to 0.4%. Losers get cut faster, which pushed total PnL to +3.29% over 60d
    # (highest of any config). Trade-off: tighter SL may stop out more in chop.
    # Backtest (60d, 4 symbols): 12 trades, WR=67%, PF=2.49x, avg_pnl=+0.27%
    "mr_opt_v5_deep_disp_tight_sl": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.0,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.4,
        "arm_trailing_stop_pct": 0.5,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,
        "trend_indicators": [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -2.0, "max_gap_pct": -5.0}},
            {"type": "rsi_overbought", "params": {"min_value": 38, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6, "oversold_threshold": 28, "current_min": 32,
                "min_jump": 5.0, "require_sustained": False, "hard_stop": True,
            }},
            {"type": "price_below_vwap",  "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.25}},
            {"type": "rsi_overbought",    "params": {"min_value": 42, "hard_stop": True}},
            {"type": "volume_spike",      "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 1.0,
    },

    # ── opt_v6: moderate displacement + RSI actively turning — high win rate ──
    # Different trigger family vs v4/v5: shallower displacement (1.5–3.5% below EMA50)
    # but adds an active RSI momentum requirement at the trend level — 60m RSI must
    # be below 38 AND actively rising (min_momentum=0.3), catching the exact turn.
    # Entry uses rsi_range cap (max 45) to avoid entering after the bounce happened.
    # Quick exit (TP=0.7%, SL=0.5%) preserves the high WR by not holding through noise.
    # Backtest (60d, 4 symbols): 10 trades, WR=80%, PF=3.79x, avg_pnl=+0.20%
    "mr_opt_v6_mod_disp_oversold_turn": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       0.7,
        "stop_loss_pct":         0.5,
        "trailing_stop_pct":     0.3,
        "arm_trailing_stop_pct": 0.35,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,
        "trend_indicators": [
            # Moderate displacement: 1.5–3.5% below EMA50 (broader than v4, but RSI turn required)
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -1.5, "max_gap_pct": -3.5}},
            # Key differentiator: 60m RSI must be oversold AND actively rising (not just below threshold)
            {"type": "rsi_oversold", "params": {"max_value": 38, "require_rising": True, "min_momentum": 0.3}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            # Range cap: prevents entry if 15m RSI already above 45 (bounce already priced in)
            {"type": "rsi_range",            "params": {"min": 20, "max": 45, "invert": True}},
            # Bounce confirmation: RSI jumped 3+ points from below 30 in 8 candles
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 8, "oversold_threshold": 30, "current_min": 28,
                "min_jump": 3.0, "hard_stop": True,
            }},
            {"type": "bollinger_bands",  "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35}},
            {"type": "price_below_vwap", "params": {"min_gap_pct": -0.3, "max_gap_pct": -10.0}},
            {"type": "volume_spike",     "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 3,
        "min_volume_ratio": 1.0,
    },

    # ── opt_v7: ADX-gated RSI turn — HIGHEST QUALITY, SELECTIVE ─────────────
    # Trend (60m): RSI must be oversold (<38) AND actively rising (min_momentum=0.3),
    # catching the exact turn out of oversold. ADX gate (18-65) blocks choppy markets
    # (ADX<18 = no directional bias = mean reversion setup unreliable) and extreme
    # trending markets where mean reversion fails (ADX>65).
    # Entry (15m): standard v3 RSI bounce from below 30 + VWAP + BB lower + volume.
    # Wide TP (2.0%) targets the full mean-reversion leg; 1.0% SL gives room for wicks.
    # Backtest (60d, 6 symbols, tick-mode): 11 trades, WR=55%, PF=2.56x, avg_pnl=+0.38%
    # Updated TP/SL after improvement experiments: TP=2.5%/SL=0.8% (same 8 trades, PF 3.34→4.75x)
    "mr_opt_v7_adx_rsi_turn_wide": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       2.5,
        "stop_loss_pct":         0.8,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 1.2,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,
        "trend_indicators": [
            # RSI oversold AND actively turning up — catches the exact reversal, not just the bottom
            {"type": "rsi_oversold",  "params": {"max_value": 38, "require_rising": True, "min_momentum": 0.3}},
            # ADX filter: some directional movement (>18) but not extreme trend (>65)
            {"type": "adx_regime",    "params": {"min_adx": 18, "max_adx": 65}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 8, "oversold_threshold": 30, "current_min": 30,
                "min_jump": 3.0, "require_sustained": False, "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "price_below_vwap",  "params": {"min_gap_pct": -0.5, "max_gap_pct": -10.0}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.3}},
            {"type": "rsi_overbought",    "params": {"min_value": 40}},
            {"type": "volume_spike",      "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 1.0,
    },
    "mr_opt_v8_deep_cap_bounceAI": {
        "symbols": ['BNB_USDC', 'BTC_USDC', 'ETH_USDC', 'SOL_USDC', 'XRP_USDC', 'ZEC_USDC'],
        "trading_type": "rules_live",
        "strategy_type": "mean_reversion",
        "market_type": "SPOT",
        "entry_timeframe": "15",
        "trend_timeframe": "60",
        "exit_timeframe": "60",
        "take_profit_pct": 1.0,
        "stop_loss_pct": 0.9,
        "trailing_stop_pct": 0.5,
        "arm_trailing_stop_pct": 0.6,
        "use_trailing_stop": True,
        "enable_signal_generation": True,
        "signal_cooldown_minutes": 20,
        "sl_cooldown_minutes": 20,
        "tp_cooldown_minutes": 20,
        "min_signal_confidence": 66.0,
        "min_volume_ratio": 1.0,
        "use_trend_filter": True,
        "use_entry_filter": True,
        "use_atr_filter": False,
        "max_position_hours": 6,
        "use_market_regime_filter": False,  # sweep 49d: regime filter hurts MR longs (-5.8% @4h) — keep off
        "default_order_size_usdc": 100.0,
        "max_position_size_pct": 30.0,
        "max_open_positions": 1,
        "max_open_positions_per_profile": 2,
        "max_portfolio_exposure_pct": 100.0,
        "leverage_multiplier": 1.0,
        "use_trend_invalidation_exit": True,
        "trend_invalidation_indicators": "trend",
        "min_position_age_for_trend_check": 30,
        "trading_hours": [],
        "trend_indicators": [
            {"type": "rsi_oversold", "params": {"max_value": 35, "require_rising": False, "min_momentum": 0.3}},
            {"type": "adx_regime", "params": {"min_adx": 18, "max_adx": 65}},
        ],
        "min_indicators_required": 2,
        "entry_indicator_groups": {'reversal_confirm': {'hard_stop': True, 'require_all': False}},
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 12, "oversold_threshold": 25, "current_min": 28, "min_jump": 4, "require_sustained": False, "hard_stop": True}},
            {"type": "volume_spike", "params": {"min_ratio": 1.5, "max_ratio": 8, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.4}},
            {"type": "rsi_overbought", "params": {"min_value": 45, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

}
