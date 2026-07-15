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

    # =========================================================================
    # NEW ITERATIONS — SHALLOW DIPS & SUSTAINED RECOVERIES  (no volume gates)
    # Prod v7/v8 both target capitulation: deep oversold (RSI<35-38) + sharp
    # jump. These variants deliberately go the other way — mild pullbacks and/or
    # gradual multi-candle recoveries — using only RSI, EMA direction, and RSI
    # reversal lookback. NO volume_spike indicators; min_volume_ratio kept low so
    # confidence never depends on volume (which is noisy across weekends/off-hours).
    #
    # Design note: trend_indicators double as the exit (trend_invalidation="trend").
    #   - price_extended_below_ema gate  => exits when price reverts toward EMA
    #                                        (small, bounded target — suits shallow dips)
    #   - rsi_oversold + require_rising   => exits when 60m RSI climbs out of oversold
    #                                        (lets price run past EMA — suits sustained legs)
    # =========================================================================

    # ------------------------------------------------------------------ SHALLOW
    # ── v9: shallow displacement + gradual (net) RSI recovery ───────────────
    # Trend (60m): price only 0.4–1.8% below EMA50 (mild pullback, not a crash)
    #   + RSI mildly oversold (<46) and just starting to turn (min_momentum 0.15).
    # Entry (15m): RSI came from ~38 and rose in a *sustained* net way (min_jump
    #   only 2.5 but require_sustained w/ net mode = multi-candle grind, not a spike),
    #   EMA20 no longer falling, price in lower BB half. Ceiling raised to 55 since
    #   a shallow dip won't depress 15m RSI as far. Tight TP/SL matches small target.
    "mr_opt_v9_shallow_disp_gradual": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       0.8,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.4,
        "arm_trailing_stop_pct": 0.5,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 15,
        "trend_indicators": [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -0.4, "max_gap_pct": -1.8}},
            {"type": "rsi_oversold", "params": {"max_value": 46, "require_rising": True, "min_momentum": 0.15}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 10, "oversold_threshold": 38, "current_min": 36,
                "min_jump": 2.5, "require_sustained": True, "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.0}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.5}},
            {"type": "rsi_overbought",  "params": {"min_value": 55, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 0.5,
    },

    # ── v10: mild pullback, NO displacement gate — pure RSI + EMA + lookback ──
    # No price_extended gate at all: catches shallow pullbacks that never stretch
    # far from EMA50. Trend (60m): RSI<48 & turning + EMA50 not collapsing.
    # Entry (15m): RSI only dipped to ~42 (shallow) then ground higher (net, small
    # jump), EMA20 not falling. rsi_overbought ceiling uses lookback_candles=6 to
    # also reject entries where 15m RSI peaked >60 recently (already-run bounce).
    "mr_opt_v10_mild_pullback_lookback": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       0.7,
        "stop_loss_pct":         0.5,
        "trailing_stop_pct":     0.35,
        "arm_trailing_stop_pct": 0.4,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 15,
        "trend_indicators": [
            {"type": "rsi_oversold", "params": {"max_value": 48, "require_rising": True, "min_momentum": 0.15}},
            {"type": "ema_slope",    "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.02}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 12, "oversold_threshold": 42, "current_min": 40,
                "min_jump": 2.0, "require_sustained": True, "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.0}},
            {"type": "rsi_overbought",  "params": {"min_value": 60, "lookback_candles": 6, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.6}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 0.5,
    },

    # ── v11: shallow displacement + ADX regime + rising EMA20 ────────────────
    # Adds ADX (15-55) as a *non-volume* quality filter (blocks dead chop and
    # extreme trends). Requires EMA20 actively rising (not just flat) so we only
    # buy shallow dips where the short-term turn is already confirmed.
    "mr_opt_v11_shallow_adx_gradual": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.0,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.4,
        "arm_trailing_stop_pct": 0.6,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 15,
        "trend_indicators": [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -0.5, "max_gap_pct": -2.2}},
            {"type": "rsi_oversold", "params": {"max_value": 44, "require_rising": True, "min_momentum": 0.2}},
            {"type": "adx_regime",   "params": {"min_adx": 15, "max_adx": 55}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 10, "oversold_threshold": 37, "current_min": 35,
                "min_jump": 2.5, "require_sustained": True, "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01}},
            {"type": "rsi_overbought",  "params": {"min_value": 54, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.5}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 0.5,
    },

    # --------------------------------------------------------------- SUSTAINED
    # ── v12: moderate dip, RSI-gated exit lets the recovery RUN ─────────────
    # Uses an rsi_oversold trend gate (not price_extended), so the position is
    # only invalidated once 60m RSI climbs out of oversold — price is free to run
    # well past EMA50 during a sustained leg. Wider TP (1.4%) + higher trailing arm
    # to bank a longer move. Entry demands a *sustained* net rise (small jump), so
    # sudden one-candle V-bounces are filtered out.
    "mr_opt_v12_sustained_net_recovery": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.4,
        "stop_loss_pct":         0.8,
        "trailing_stop_pct":     0.6,
        "arm_trailing_stop_pct": 0.9,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 30,
        "trend_indicators": [
            {"type": "rsi_oversold", "params": {"max_value": 42, "require_rising": True, "min_momentum": 0.25}},
            {"type": "adx_regime",   "params": {"min_adx": 16, "max_adx": 55}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 12, "oversold_threshold": 35, "current_min": 34,
                "min_jump": 2.5, "require_sustained": True, "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.0}},
            {"type": "rsi_overbought",  "params": {"min_value": 52, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.45}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 0.5,
    },

    # ── v13: EMA-direction led + controlled RSI momentum (gradual, not sudden) ─
    # Leads with EMA20 actually rising (hard) and a *bounded* RSI momentum
    # (0.25–2.0): the upper bound explicitly rejects sudden RSI surges, so we only
    # take steady, sustained recoveries. rsi_reversal (non-hard) just confirms the
    # move came out of a dip. Exit via rsi_oversold gate = room for the leg to run.
    "mr_opt_v13_ema20_turn_momentum": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.2,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.8,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 30,
        "trend_indicators": [
            {"type": "rsi_oversold", "params": {"max_value": 45, "require_rising": True, "min_momentum": 0.2}},
            {"type": "ema_slope",    "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.02}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.25, "max_momentum": 2.0, "lookback_candles": 2, "hard_stop": True}},
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 12, "oversold_threshold": 40, "current_min": 38,
                "min_jump": 2.0, "require_sustained": True, "sustained_rise_mode": "net",
            }},
            {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "min_volume_ratio": 0.5,
    },

    # ── v14: explicit "no V-spike" — sustained rise with momentum upper bound ─
    # Shallow-to-moderate dip (0.6–2.8% below EMA50). Combines require_sustained
    # (net) with an rsi_momentum cap (<=1.8 over 3 candles): a sharp capitulation
    # bounce blows past that ceiling and is rejected, leaving only the gradual
    # grind-higher recoveries prod v7/v8 don't take.
    "mr_opt_v14_gradual_no_spike": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.0,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.6,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 20,
        "trend_indicators": [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -0.6, "max_gap_pct": -2.8}},
            {"type": "rsi_oversold", "params": {"max_value": 44, "require_rising": True, "min_momentum": 0.2}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 12, "oversold_threshold": 38, "current_min": 36,
                "min_jump": 2.0, "require_sustained": True, "sustained_rise_mode": "net",
                "hard_stop": True,
            }},
            {"type": "rsi_momentum",   "params": {"min_momentum": 0.2, "max_momentum": 1.8, "lookback_candles": 3, "hard_stop": True}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "not_falling", "min_slope_pct": 0.0}},
            {"type": "rsi_overbought", "params": {"min_value": 55, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
        "min_volume_ratio": 0.5,
    },

    # =========================================================================
    # ITERATION 2 — built on the v13 winner (EMA20-rising + bounded momentum).
    # 50d finding: the "EMA20 actively rising (hard) + rsi_momentum capped" combo
    # took ZERO stop losses (v13: 75% WR, 20.9x PF) — it only enters once the
    # turn is real. Downside was frequency (4 trades). These loosen thresholds /
    # widen targets to raise trade count while keeping that no-knife-catch quality.
    # The momentum UPPER bound is the "no sudden recovery" lever (blocks V-spikes).
    # =========================================================================

    # ── v15: v13 loosened for frequency ─────────────────────────────────────
    "mr_opt_v15_ema_turn_loosened": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.2,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.8,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 20,
        "trend_indicators": [
            {"type": "rsi_oversold", "params": {"max_value": 47, "require_rising": True, "min_momentum": 0.15}},
            {"type": "ema_slope",    "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.02}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.2, "max_momentum": 2.5, "lookback_candles": 2, "hard_stop": True}},
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 12, "oversold_threshold": 42, "current_min": 38,
                "min_jump": 1.5, "require_sustained": True, "sustained_rise_mode": "net",
            }},
            {"type": "rsi_overbought", "params": {"min_value": 58, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "min_volume_ratio": 0.5,
    },

    # ── v16: v13 recipe + wider TP to let sustained legs run further ─────────
    "mr_opt_v16_ema_turn_wide_tp": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.8,
        "stop_loss_pct":         0.8,
        "trailing_stop_pct":     0.7,
        "arm_trailing_stop_pct": 1.2,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 30,
        "trend_indicators": [
            {"type": "rsi_oversold", "params": {"max_value": 45, "require_rising": True, "min_momentum": 0.2}},
            {"type": "adx_regime",   "params": {"min_adx": 16, "max_adx": 55}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.25, "max_momentum": 2.2, "lookback_candles": 2, "hard_stop": True}},
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 12, "oversold_threshold": 40, "current_min": 38,
                "min_jump": 2.0, "require_sustained": True, "sustained_rise_mode": "net",
            }},
            {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "min_volume_ratio": 0.5,
    },

    # ── v17: the SHALLOW-DIP idea redone WITH the rising-EMA20 gate ──────────
    # v9/v11 failed (stopped out on knives) precisely because they lacked the
    # hard rising-EMA20 confirmation. Same shallow displacement here, but entry
    # is blocked until EMA20 is actually turning up + momentum is positive-but-
    # controlled. Tight TP/SL for the small reversion target.
    "mr_opt_v17_shallow_ema_confirmed": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       0.9,
        "stop_loss_pct":         0.6,
        "trailing_stop_pct":     0.4,
        "arm_trailing_stop_pct": 0.5,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 15,
        "trend_indicators": [
            {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -0.5, "max_gap_pct": -2.2}},
            {"type": "rsi_oversold", "params": {"max_value": 46, "require_rising": True, "min_momentum": 0.15}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.2, "max_momentum": 2.2, "lookback_candles": 2, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 55, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.5}},
        ],
        "min_entry_indicators_required": 3,
        "min_volume_ratio": 0.5,
    },

    # ── v18: pure momentum/EMA quality (no reversal, no BB) — cleanest v13 ───
    # 3 hard gates only: EMA20 rising, RSI rising over 3 candles (sustained) but
    # capped (no spike), and an RSI ceiling. Closest to v13's zero-SL profile.
    "mr_opt_v18_momentum_only_quality": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.3,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.8,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 25,
        "trend_indicators": [
            {"type": "rsi_oversold", "params": {"max_value": 46, "require_rising": True, "min_momentum": 0.2}},
            {"type": "ema_slope",    "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.02}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.3, "max_momentum": 2.0, "lookback_candles": 3, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "min_volume_ratio": 0.5,
    },

    # =========================================================================
    # ITERATION 3 — frequency sweep on the v18 winner, isolating ONE lever:
    # the 60m EMA50 slope tolerance. v18's ema50 "not_falling @0.02" is the main
    # quality gate but also the main frequency limiter (only ~5 setups/50d). These
    # relax ONLY that slope tolerance (and the oversold ceiling) — entry gates are
    # kept identical to v18 — to map the quality/frequency trade-off cleanly.
    #
    # RESULT (50d): the gate is a CLIFF, not a slope. Relaxing 0.02 -> 0.06 blew
    # trades 5 -> 53 and crashed WR 80% -> 34% (v19: 0.60x PF). 0.12 -> 83 trades,
    # 36% WR (v20: 0.68x). CONCLUSION: keep ema50 not_falling @0.02 tight. The
    # high-quality sustained-recovery edge is inherently rare (~1/wk / 6 symbols);
    # forcing frequency turns it into knife-catching. v13 + v18 are the keepers.
    # v19/v20 below are DEPRECATED — retained only as the evidence for this.
    # =========================================================================

    # ── v19: v18 with a small EMA50 downslope allowance (-0.06%) ─────────────
    "mr_opt_v19_v18_ema50_soft": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.3,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.8,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 25,
        "trend_indicators": [
            {"type": "rsi_oversold", "params": {"max_value": 48, "require_rising": True, "min_momentum": 0.2}},
            {"type": "ema_slope",    "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.06}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.3, "max_momentum": 2.0, "lookback_candles": 3, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "min_volume_ratio": 0.5,
    },

    # ── v20: v18 with a larger EMA50 downslope allowance (-0.12%) ────────────
    "mr_opt_v20_v18_ema50_softer": {
        **_MEAN_REV_BASE,
        "take_profit_pct":       1.3,
        "stop_loss_pct":         0.7,
        "trailing_stop_pct":     0.5,
        "arm_trailing_stop_pct": 0.8,
        "use_trailing_stop":     True,
        "use_trend_filter":      True,
        "trend_timeframe":       "60",
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 25,
        "trend_indicators": [
            {"type": "rsi_oversold", "params": {"max_value": 48, "require_rising": True, "min_momentum": 0.2}},
            {"type": "ema_slope",    "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.12}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope",     "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.015, "hard_stop": True}},
            {"type": "rsi_momentum",  "params": {"min_momentum": 0.3, "max_momentum": 2.0, "lookback_candles": 3, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        "min_volume_ratio": 0.5,
    },

}
