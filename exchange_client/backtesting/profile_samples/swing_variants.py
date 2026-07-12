_SWING_BASE = {
    "strategy_type": "trend_following",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "take_profit_pct": 3,
    "stop_loss_pct": 2,
    "trailing_stop_pct": 1,
    "arm_trailing_stop_pct": 1.0,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 241,
    "max_open_positions_per_profile": 2,
    "min_signal_confidence": 74.0,
    "min_volume_ratio": 1.0,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "stop_loss_slippage_pct": 0.05,
    "max_position_hours": 72,
    "use_market_regime_filter": False,
    # Trend invalidation exit — mirrors production position_manager behaviour.
    # mode "trend": re-check 4hr trend indicators (catches big structural reversals).
    # mode "entry": re-check 1hr entry conditions (faster but noisier).
    # mode "exit":  use dedicated exit_indicators (most targeted).
    "use_trend_invalidation_exit":      True,
    "trend_invalidation_indicators":    "exit",  # default: 4hr trend indicators
    "min_position_age_for_trend_check": 241,        # minutes; 0 = check immediately
    # Exit indicators: "has the trade broken down?" rather than "can I enter?"
    # These are used when trend_invalidation_indicators="exit".
    "exit_indicators": [
        # RSI drops back below 48 → 1hr momentum is gone
        {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 45, "use_momentum": False, "hard_stop": True}},
        # Price closes below 1hr EMA20 → short-term structure broken
        {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -100.0, "max_gap_pct": 0.0, "hard_stop": True}},
        # BB %B drops below 0.35 → price retreating to lower half of bands
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.35, "hard_stop": True}},
    ],
    "min_exit_indicators_required": 2,
    "exit_timeframe": "60",
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
        {"type": "rsi_reversal_momentum", "params": {
            "lookback_candles":    6,
            "oversold_threshold":  36,
            "current_min":         34,
            "min_jump":            2.5,
            "require_sustained":   True,
            "sustained_rise_mode": "net",
            "hard_stop":           True,
        }},
        {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
    ],
    "min_indicators_required": 2,
    "entry_indicators": [
        {"type": "rsi_overbought", "params": {"min_value": 54, "hard_stop": True}},
        # Price vs EMA: wide allowance for post-crash EMA elevation
        {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 5.0}},
        # Volume: soft, no hard_stop
        {"type": "volume_spike",   "params": {"min_ratio": 0.5, "max_ratio": 8.0}},
        {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":0.88,"hard_stop":True}},
    ],
    "min_entry_indicators_required": 3,
}

SWING_VARIANTS = {
    "p3_base" : _SWING_BASE,
   
    # ── Profile 9: Refined RSI Pullback ───────────────────────────────────────
    # Derived from p3_v7_rsi_pullback with three fixes:
    #   1. Collapsed two overlapping trend RSI ranges (48-63 ∩ 52-65) into one rsi_range(52-63)
    #   2. Collapsed two overlapping entry RSI ranges (30-52 ∩ 28-50) into one rsi_range(30-50)
    #   3. Added ema_slope to trend layer — filters stale EMA crosses (no slope requirement in v7
    #      means a cross from weeks ago still passes even as price drifts lower)
    #   4. Replaced redundant second RSI in entry with volume_spike — structural confirmation
    #      that buyers are actually returning into the pullback, not just RSI drifting down
    "p3_v9_refined_pullback": {
        **_SWING_BASE,
        "take_profit_pct": 3.0,
        "stop_loss_pct": 2.0,
        "trailing_stop_pct": 1.2,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 241,
        "min_volume_ratio": 1.0,
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,

        # 4hr: EMA cross bullish (hard) + EMA20 slope actively rising ≥0.05%/candle (hard)
        # + RSI in bullish zone 52-63 (hard). ema_slope is the key addition over v7.
        "trend_indicators": [
            {"type": "ema_cross", "params": {"hard_stop": True}},
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.05, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 52, "max": 63, "invert": True, "hard_stop": True}},
        ],
        "min_indicators_required": 3,

        # 1hr: ADX in momentum zone (22-40) + RSI pulled back to 30-50 (hard)
        # + volume spike (1.2x+) confirms buyers re-entering, not just passive RSI drift.
        "entry_indicators": [
            {"type": "adx_regime",   "params": {"min_adx": 22, "max_adx": 40}},
            {"type": "rsi_range",    "params": {"min": 30, "max": 50, "invert": True, "hard_stop": True}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 3,
    },

    # ── Profile 1: EMA Cross RSI Pullback ──────────────────────────────────────
    # Ticks optimizer iter 3 champion: score=182.36, 23T, 65% WR, 3.29x PF, +18.4% (60d, 5 symbols)
    # Market: 4hr EMA cross bullish + RSI in bullish zone (52-63). Enter on 1hr pullback
    # where RSI dips to 30-50. ADX 22-40 confirms entry momentum.
    # No ADX required in trend — RSI zone acts as the selectivity filter.
    "p3_v7_rsi_pullback": {
        **_SWING_BASE,
        "take_profit_pct": 3.0,
        "stop_loss_pct": 2.0,
        "trailing_stop_pct": 1.2,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 241,
        "min_volume_ratio": 1.0,
        # "trend" mode re-checks 4hr trend indicators (EMA cross + RSI zone) on open positions.
        # Do NOT use "entry" mode here — 1hr RSI climbing above 50 as the trade wins would
        # incorrectly trigger an exit since the entry RSI range (28-50) would then "fail".
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,

        # 4hr: EMA bullish cross (hard) + RSI in bullish zone 52-63 (hard)
        # (collapsed from two overlapping ranges 48-63 ∧ 52-65 — behaviour identical)
        "trend_indicators": [
            {"type": "ema_cross",  "params": {"hard_stop": True}},
            {"type": "rsi_range",  "params": {"min": 52, "max": 63, "invert": True, "hard_stop": True}},
        ],
        "min_indicators_required": 2,

        # 1hr: ADX in momentum zone (22-40) + RSI pulled back to 30-50 (hard)
        # (collapsed from two overlapping ranges 30-52 ∧ 28-50 — behaviour identical)
        "entry_indicators": [
            {"type": "adx_regime", "params": {"min_adx": 22, "max_adx": 40}},
            {"type": "rsi_range",  "params": {"min": 30, "max": 50, "invert": True, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 2,
    },

    # ── Profile 2: EMA Cross ADX + Volume Entry ────────────────────────────────
    # Ticks optimizer iter 3 champion: score=182.26, 20T, 65% WR, 3.79x PF, +16.0% (60d, 5 symbols)
    # Market: 4hr EMA cross bullish + ADX in strong-but-not-extreme trend (20-32) + RSI 48-65.
    # Enter on 1hr pullback with volume spike (crowd re-entry) + RSI 28-50 + BB/EMA confirmation.
    # Volume spike as hard-stop on entry differentiates this profile from p3_v7.
    "p3_v8_vol_pullback": {
        **_SWING_BASE,
        "symbols": ['SOL_USDC', 'BTC_USDC', 'ETH_USDC','XRP_USDC'],
        "take_profit_pct": 3.0,
        "stop_loss_pct": 2.0,
        "trailing_stop_pct": 1.2,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 241,
        "min_volume_ratio": 1.0,
        # "trend" mode: same reasoning as p3_v7 — volume_spike in entry indicators won't
        # persist after entry candle, so "entry" mode would exit the position almost immediately.
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,

        # 4hr: EMA bullish cross (hard) + ADX trend strength 20-32 (hard) + RSI 48-65
        "trend_indicators": [
            {"type": "ema_cross",  "params": {"hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 20, "max_adx": 32, "hard_stop": True}},
            {"type": "rsi_range",  "params": {"min": 48, "max": 65, "invert": True}},
        ],
        "min_indicators_required": 3,

        # 1hr: volume spike 1.2-8x (crowd re-entry, hard) + RSI 28-50 + BB in lower half + price near EMA20
        # 3 of 4 must pass; volume_spike is the non-negotiable hard gate
        "entry_indicators": [
            {"type": "volume_spike",   "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
            {"type": "rsi_range",      "params": {"min": 28, "max": 50, "invert": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.5}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 2.0}},
        ],
        "min_entry_indicators_required": 3,
    },

    "p3_v6_vol_pullback_adx": {
        **_SWING_BASE,
        "symbols": ['SOL_USDC', 'BTC_USDC', 'ETH_USDC','XRP_USDC','ZEC_USDC'],
        "take_profit_pct": 3.0,
        "stop_loss_pct": 2.0,
        "trailing_stop_pct": 1.2,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 241,
        "min_volume_ratio": 1.0,
        # "trend" mode: same reasoning as p3_v7 — volume_spike in entry indicators won't
        # persist after entry candle, so "entry" mode would exit the position almost immediately.
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,

        # 4hr: EMA bullish cross (hard) + ADX trend strength 20-32 (hard) + RSI 48-65
        "trend_indicators": [
            {"type": "ema_cross",  "params": {"hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 20, "max_adx": 40, "hard_stop": True}},
            {"type": "rsi_range",  "params": {"min": 48, "max": 65, "invert": True}},
        ],
        "min_indicators_required": 3,

        # 1hr: volume spike 1.2-8x (crowd re-entry, hard) + RSI 28-50 + BB in lower half + price near EMA20
        # 3 of 4 must pass; volume_spike is the non-negotiable hard gate
        "entry_indicators": [
            {"type": "volume_spike",   "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
            {"type": "rsi_range",      "params": {"min": 28, "max": 50, "invert": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.5}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 2.0}},
        ],
        "min_entry_indicators_required": 3,
    },

    # ── v6b: fast dip-buyer for perps (bullet) — 60m trend / 15m entry ────────
    # 3-round optimization champion (Jul 8 2026, data Apr 29 → Jul 8, ticks mode,
    # 0.05% SL slippage, fees excluded):
    #   30d: 106T 51% WR +11.8% PF 1.34 | 60d: 142T 53% +20.2% PF 1.46 | full: 164T 53% +22.0% PF 1.42
    #   Overlap with backpack set (v7+v11+v15): 5% — structurally different TF.
    #   Avg hold 3.1h (funding-friendly). Per-symbol: all positive except XRP (-0.7%, n=15).
    # FEE SENSITIVITY (avg trade is thin ~0.13%): at 0.02%/side taker → 60d +14.3% PF 1.30;
    # at 0.05%/side → 60d +5.6% PF 1.11 (marginal — do not run at high taker fees).
    # Rejected in optimization: breakout entries (PF 0.78), ema_gap trend gate (0.79),
    # 2x-vol bursts (0.56), TP>=1.8 geometry (fee headroom did NOT improve), all-4 entry.
    # For prod: enable consecutive-SL breaker in circuit_breaker_config (suggest k=3 / 12h
    # for this TF) and calibrate stop_loss_slippage_pct from bullet percent_missed data.
    "p3_v6b_fast_dip_regime": {
        **_SWING_BASE,
        "symbols": ['SOL_USDC', 'BTC_USDC', 'ETH_USDC', 'XRP_USDC', 'ZEC_USDC'],
        "trend_timeframe": "60",
        "entry_timeframe": "15",
        "use_market_regime_filter": True,
        "take_profit_pct": 1.5,
        "stop_loss_pct": 1.0,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 0.8,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 61,
        "max_position_hours": 24,
        "min_volume_ratio": 1.0,
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,

        # 60m trend: EMA cross (hard) + ADX 20-45 (hard) + RSI 50-68
        "trend_indicators": [
            {"type": "ema_cross",  "params": {"hard_stop": True}},
            {"type": "adx_regime", "params": {"min_adx": 20, "max_adx": 45, "hard_stop": True}},
            {"type": "rsi_range",  "params": {"min": 50, "max": 68, "invert": True}},
        ],
        "min_indicators_required": 3,

        # 15m entry: volume spike (hard) + deep RSI dip 25-45 + BB lower half + price near EMA20
        "entry_indicators": [
            {"type": "volume_spike",    "params": {"min_ratio": 1.2, "max_ratio": 8.0, "hard_stop": True}},
            {"type": "rsi_range",       "params": {"min": 25, "max": 45, "invert": True}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.5}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -3.0, "max_gap_pct": 1.0}},
        ],
        "min_entry_indicators_required": 3,
    },

    # ── Profile 11: v9 with relaxed ema_slope (0.02%) ─────────────────────────
    # v9 at 0.05% slope was too restrictive — 10 trades total, 0 fires on SOL/XRP/ZEC.
    # Dropping to 0.02% should recover trade count while still filtering stale EMA crosses
    # (a 0.02% per-candle slope on 4hr is still a genuinely rising EMA, just less steep).
    # If WR/PF stay near v9 but trades recover toward v7 levels, this is the keeper.
    "p3_v11_slope_relaxed": {
        **_SWING_BASE,
        "symbols": ['SOL_USDC', 'BTC_USDC', 'ETH_USDC','XRP_USDC','ZEC_USDC','BNB_USDC'],
        "take_profit_pct": 3.5,
        "stop_loss_pct": 2.0,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 241,
        "min_volume_ratio": 1.0,
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,

        # 4hr: same as v9 but slope threshold halved — 0.02% filters flat/stale crosses
        # without blocking gently-rising trends that v9 was missing (SOL, XRP, ZEC)
        "trend_indicators": [
            {"type": "ema_cross", "params": {"hard_stop": True}},
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 52, "max": 63, "invert": True, "hard_stop": True}},
        ],
        "min_indicators_required": 3,

        # 1hr: identical to v9
        "entry_indicators": [
            {"type": "adx_regime",   "params": {"min_adx": 22, "max_adx": 40}},
            {"type": "rsi_range",    "params": {"min": 30, "max": 50, "invert": True, "hard_stop": True}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 3,
    },


    # ── Profile 12: v7 trend + v8 rich entry (hybrid) ─────────────────────────
    # Combines the best structural element of each champion:
    #   Trend: v7's permissive trend layer (ema_cross + single RSI zone 52-63, no ADX gate)
    #          — keeps BNB/ZEC accessible where v8's ADX 20-32 fails
    #   Entry: v8's multi-indicator entry structure (4 indicators, 3-of-4 must pass)
    #          — BB + price_vs_ema + RSI + soft volume for richer pullback confirmation
    # Goal: v7's trade frequency with v8's entry quality. Volume remains soft (non-blocking).
    "p3_v12_hybrid": {
        **_SWING_BASE,
        "take_profit_pct": 3.0,
        "stop_loss_pct": 2.0,
        "trailing_stop_pct": 1.2,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 241,
        "min_volume_ratio": 1.0,
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,

        # 4hr: v7 trend structure — no ADX required, just EMA cross + RSI zone
        # Single collapsed RSI range (was two overlapping in v7)
        "trend_indicators": [
            {"type": "ema_cross", "params": {"hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 52, "max": 63, "invert": True, "hard_stop": True}},
        ],
        "min_indicators_required": 2,

        # 1hr: v8-style rich entry — RSI pullback + BB position + price near EMA + soft volume
        # 3 of 4 must pass; no hard_stop on any so signal confidence can arbitrate
        "entry_indicators": [
            {"type": "rsi_range",      "params": {"min": 28, "max": 50, "invert": True, "hard_stop": True}},
            {"type": "bollinger_bands","params": {"band": "upper", "mode": "pct_b", "min_pct_b": 0.0, "max_pct_b": 0.5}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -5.0, "max_gap_pct": 2.0}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 3,
    },

    # ── Profile 13: Wide trend RSI + clean entry (no ADX in trend) ────────────
    # SOL diagnosis: v7 misses SOL because RSI zone 52-63 is too tight (SOL sits 48-52
    # when pullback conditions align). Widening to 48-65 (same as v8) should recapture SOL
    # while skipping the ADX-in-trend gate that kills BNB in v8.
    # Entry stays clean (v9 style): ADX + collapsed RSI + volume.

    "p3_v13_wide_rsi_trend": {
        **_SWING_BASE,
        "symbols": ['BNB_USDC', 'BTC_USDC', 'ETH_USDC'],
        "take_profit_pct": 3.0,
        "stop_loss_pct": 2.0,
        "trailing_stop_pct": 0.6,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 241,
        "min_volume_ratio": 1.0,
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,

        # 4hr: ema_cross + wider RSI 48-65 (no ADX gate, keeping BNB accessible)
        "trend_indicators": [
            {"type": "ema_cross", "params": {"hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 48, "max": 65, "invert": True, "hard_stop": True}},
        ],
        "min_indicators_required": 2,

        # 1hr: v9-style clean entry — ADX momentum + RSI pullback + volume confirmation
        "entry_indicators": [
            {"type": "adx_regime",   "params": {"min_adx": 22, "max_adx": 40}},
            {"type": "rsi_range",    "params": {"min": 30, "max": 50, "invert": True, "hard_stop": True}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 3,
    },

    # ── Profile 15: v13 + ema_slope (premium quality filter) ──────────────────
    # Tests if v11's slope gate + v13's wider RSI zone = better than either alone.
    # v11 (narrow RSI 52-63 + slope) = 91% WR but only fires on ETH/BTC/BNB.
    # v13 (wide RSI 48-65, no slope) = 71% WR, fires on SOL too.
    # v15 combines both: wide RSI keeps SOL/XRP accessible, slope filters stale crosses.
    # If trade count stays near v13 (21T) but WR lifts toward v11 (91%), this is the keeper.
    "p3_v15_wide_rsi_slope": {
        **_SWING_BASE,
        "take_profit_pct": 3.0,
        "stop_loss_pct": 2.0,
        "trailing_stop_pct": 1.2,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": True,
        "min_signal_confidence": 74.0,
        "signal_cooldown_minutes": 241,
        "min_volume_ratio": 1.0,
        "trend_invalidation_indicators":    "trend",
        "min_position_age_for_trend_check": 0,

        # 4hr: ema_cross + ema_slope (filters stale crosses) + wider RSI 48-65
        "trend_indicators": [
            {"type": "ema_cross", "params": {"hard_stop": True}},
            {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 48, "max": 65, "invert": True, "hard_stop": True}},
        ],
        "min_indicators_required": 3,

        # 1hr: identical to v13
        "entry_indicators": [
            {"type": "adx_regime",   "params": {"min_adx": 22, "max_adx": 40}},
            {"type": "rsi_range",    "params": {"min": 30, "max": 50, "invert": True, "hard_stop": True}},
            {"type": "volume_spike", "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 3,
    },

}