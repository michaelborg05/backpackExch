

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

# =============================================================================
# HISTORY / CULLED VARIANTS  (Jul 18 2026)
#
# Removed as clearly dead on the 30d tick window (all PF < 0.8x):
#   opt_v1_emacross_revmom, tf_iter3_exit_rsi68, tf_v1_revmom_exitA,
#   tf_iter4_exit_rsi67, tf_iter4_exit_rsi67_noregime  — the old 7-indicator
#     "sustained revmom" entry family. 0.29-0.36x PF, 7 trades each, 29% WR.
#   tf_v3_rsizone_adx22 (0.07x), tf_v3_rsizone_adx22_tp12 (0.67x)
#   tf_v4_tp9 (0.75x), tf_v4_zone3855_tp8 (0.57x)  — lever-isolation siblings,
#     both negative; the zone/TP levers no longer separate on this window.
#   tf_v4_zone3855_tp9_240 (0.28x) — 4h regime filter confirmed worse than 60m.
#   opt_v1_bkout_pctb_mom (0.96x) — dominated by bkout_steep_slope.
#
# Kept as controls: tf_v4_zone3855_tp9 + tf_v3_rsizone_17t (prod),
#   opt_v1_bkout_steep_slope + opt_v1_bkout_regime (only high-volume variants
#   that were not net-negative).
#
# -----------------------------------------------------------------------------
# V5 DIRECTION — derived from a per-indicator post-hoc sweep of the 30d results
# (112 unique trades across the 15 variants). Three gates carry essentially all
# of the separation; each is structural, not curve-fit to a date:
#
#   1. 60m RSI band 56-66.  htf_rsi 58-63 => 68% WR / +0.43% avg / +10.8% total.
#      htf_rsi 63-68 => -5.3% total; htf_rsi < 55 => -6.1% total. Entering an
#      already-overbought 60m trend is where the Jul 15-16 bleed came from.
#   2. 15m EMA20 > EMA50 (entry-TF alignment). Trades with 15m ema20 < ema50
#      were 35% WR / -5.5% total. The rsi_range family (v3/v4) has NO entry-TF
#      trend alignment check at all — every one of its trades in this window
#      fired with 15m ema20 < ema50, which is why it is starved AND negative.
#   3. 60m EMA20-50 separation < 1.5% (not already extended). hsep > 1.5%
#      => -4.3% total across 54 trades.
#
#   Combined on the raw trade population: 28T, 68% WR, +0.33% avg, 2.29x PF
#   (vs 112T, 51% WR, -0.00% avg, 0.99x PF unfiltered).
#
#   Volume finding (counter-intuitive, tested separately below): volume_ratio
#   0.5-0.8 => 74% WR; 1.1-1.5 => 29% WR. The `volume_spike min_ratio 1.5`
#   gate in the bkout family may be selecting the wrong entries entirely.
# =============================================================================

# Gate building blocks (60m = trend_indicators, 15m = entry_indicators)
_HTF_RSI_BAND = {"type": "rsi_range", "params": {"min": 56, "max": 66, "invert": True}}
_HTF_NOT_EXTENDED = {"type": "ema_gap", "params": {"mode": "max", "max_gap_pct": 1.5}}
_LTF_EMA_ALIGN = {"type": "ema_cross", "params": {}}

_EXIT_SET = [
    {"type": "rsi_overbought", "params": {"min_value": 68, "hard_stop": True}},
    {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": -0.02, "hard_stop": True}},
    {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 44, "use_momentum": False}},
]


def _bkout(**over):
    """opt_v1_bkout_steep_slope skeleton with overridable trend/entry lists."""
    cfg = {
        **_TF_BASE,
        "regime_timeframe": "60",
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
    }
    cfg.update(over)
    return cfg


def _zone(**over):
    """tf_v4_zone3855_tp9 skeleton (prod champion) with overrides."""
    cfg = {
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
        "exit_indicators": list(_EXIT_SET),
        "min_exit_indicators_required": 1,
        "min_position_age_for_trend_check": 15,
    }
    cfg.update(over)
    return cfg


# =============================================================================
# V5 ITERATION 1 RESULT (30d tick, 7 symbols) — see _bk5() sweep below
#
#   tf_v5_bk_all          23T  70% WR  +0.18% avg  +4.24%  1.88x PF
#   tf_v5_bk_all_tp16sl9  23T  70% WR  +0.19% avg  +4.46%  2.03x PF
#   tf_v5_bk_all_lowvol   14T  71% WR  +0.23% avg  +3.17%  2.14x PF
#   ---- baselines ----
#   opt_v1_bkout_steep_slope 50T 50% WR +0.03% avg 1.06x PF
#   tf_v4_zone3855_tp9 (PROD)  4T 50% WR +0.05% avg 1.13x PF
#   tf_v3_rsizone_17t  (PROD)  6T 50% WR -0.23% avg 0.43x PF
#
# Conclusions:
#   - The three gates work as predicted: 50T/1.06x -> 23T/1.88x on the same base.
#     Lever isolation says the stack is what matters, not any single gate
#     (htfrsi alone 1.07x, gap alone 1.02x, ltfema alone 1.17x).
#   - volume_spike is NOT binding once the gates are applied (novol is trade-for-
#     trade identical to bk_all). The LOW-volume cap (0.45-1.15x) does add
#     quality but halves the sample — kept in the iter-2 sweep, not assumed.
#   - The rsi_range / "zone" family is FINISHED. Loosening it (ADX 18, wider
#     zone, unsustained revmom) made it worse (0.65-0.76x), and adding the gates
#     zeroes it out entirely — its entries are structurally the ones the gates
#     reject (15m ema20 < ema50). Both current prod profiles are in this family.
# =============================================================================


def _bk5(htf_band=(56, 66), gap_max=1.5, adx_min=30, tp=1.2, sl=0.7,
         trail=0.5, arm=0.8, vol=(1.5, 10.0), vol_hard=True):
    """bkout base + the three V5 gates, with every swept lever exposed.

    vol_hard=False reproduces the iter-1 form where volume_spike was a soft
    (scored) indicator rather than a hard gate — a much bigger lever than it
    looks: hard-gating it took the same base from 23T/70% WR to 12T/92% WR.
    """
    return _bkout(
        take_profit_pct=tp, stop_loss_pct=sl,
        trailing_stop_pct=trail, arm_trailing_stop_pct=arm,
        min_volume_ratio=0.0,
        trend_indicators=[
            {"type": "ema_cross",  "params": {}},
            {"type": "adx_regime", "params": {"min_adx": adx_min, "max_adx": 65, "hard_stop": True}},
            {"type": "ema_slope",  "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.025, "hard_stop": True}},
            {"type": "rsi_range",  "params": {"min": htf_band[0], "max": htf_band[1], "invert": True, "hard_stop": True}},
            {"type": "ema_gap",    "params": {"mode": "max", "max_gap_pct": gap_max, "hard_stop": True}},
        ],
        min_indicators_required=5,
        entry_indicators=[
            {"type": "rsi_threshold",  "params": {"period": 14, "min_value": 55, 
                                                  "use_momentum": True, "early_threshold": 50, "hard_stop": True}},
            {"type": "rsi_momentum",   "params": {"min_momentum": 1.0, "max_momentum": 8.0}},
            {"type": "ema_slope",      "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.03, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"min_value": 72, "hard_stop": True}},
            {"type": "volume_spike",   "params": {"min_ratio": vol[0], "max_ratio": vol[1], 
                                                  **({"hard_stop": True} if vol_hard else {})}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -0.3, "max_gap_pct": 1.5}},
            {"type": "price_vs_vwap",  "params": {}},
            {"type": "ema_cross",      "params": {"hard_stop": True}},
        ],
        min_entry_indicators_required=6,
    )


TREND_VARIANTS = {

    # ======================= CONTROLS (prod + best legacy) ====================

    # PROD — V4 winner: deeper RSI zone (38-55) + TP 0.9. 30d: 4T, 1.13x PF.
    "tf_v4_zone3855_tp9": _zone(),

    # PROD — V3 high-volume sustained revmom, zone 40-58. 30d: 6T, 0.43x PF.
    "tf_v3_rsizone_17t": _zone(
        take_profit_pct=0.8, stop_loss_pct=0.6,
        trailing_stop_pct=0.3, arm_trailing_stop_pct=0.4,
        entry_indicators=[
            {"type": "rsi_range",             "params": {"min": 40, "max": 58, "invert": True}},
            {"type": "rsi_reversal_momentum", "params": {"lookback_candles": 6, "oversold_threshold": 45, "current_min": 44, "min_jump": 5.0, "require_sustained": True, "hard_stop": True}},
            {"type": "ema_slope",             "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}},
        ],
    ),

    # LEGACY control — highest trade count, 30d: 50T, 50% WR, 1.06x PF.
    "opt_v1_bkout_steep_slope": _bkout(),

    # LEGACY control — steep_slope + BB-width regime gate. 30d: 43T, 1.08x PF.
    "opt_v1_bkout_regime": _bkout(
        trend_indicators=[
            {"type": "ema_cross",       "params": {}},
            {"type": "adx_regime",      "params": {"min_adx": 30, "max_adx": 65, "hard_stop": True}},
            {"type": "ema_slope",       "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "bb_width_regime", "params": {"required_direction": "not_expanding", "lookback": 4}},
        ],
        min_indicators_required=4,
        entry_indicators=[
            {"type": "rsi_threshold",     "params": {"period": 14, "min_value": 55, "use_momentum": True, "early_threshold": 50, "hard_stop": True}},
            {"type": "rsi_momentum",      "params": {"min_momentum": 1.5, "max_momentum": 8.0}},
            {"type": "rsi_overbought",    "params": {"min_value": 72, "hard_stop": True}},
            {"type": "bb_pct_b_momentum", "params": {"required_direction": "rising", "lookback": 3}},
            {"type": "volume_spike",      "params": {"min_ratio": 1.5}},
            {"type": "ema_slope",         "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "price_vs_vwap",     "params": {}},
        ],
    ),

    # ================= V5 FINAL SET — validated Jul 18 2026 ==================
    # Method: 3 iterations on 30d tick data, then re-run over 60d and split into
    # two INDEPENDENT 30d halves (the 60d window contains the 30d one, so the
    # raw 60d totals overstate everything).
    #
    #   variant                 EARLY May19-Jun18      LATE Jun18-Jul18   both+
    #   tf_v5_tp14sl8            8T 38%  +1.03% 1.4x   12T 92%  +6.36%    YES
    #   tf_v5_base_volhard       8T 38%  +0.65% 1.2x   12T 92%  +6.04%    YES
    #   tf_v4_zone3855_tp9(PROD)12T 83%  +5.55% 4.5x    4T 50%  +0.20%    YES
    #   tf_v5_band5468           9T 44%  -0.16% 1.0x   14T 93%  +7.80%    no
    #   tf_v5_adx25             15T 40%  -0.46% 0.9x   17T 82%  +8.50%    no
    #   tf_v5_gap25             11T 36%  -0.81% 0.8x   17T 88%  +6.70%    no
    #   tf_v5_loose2_adxgap     19T 37%  -2.82% 0.7x   25T 80% +11.50%    no
    #   tf_v3_rsizone_17t(PROD) 15T 73%  +3.21% 2.0x    6T 50%  -1.37%    no
    #   opt_v1_bkout_steep      63T 40%  -9.22% 0.7x   50T 50%  +1.33%    no
    #
    # WHAT HELD UP:
    #   - The three V5 gates are real: they turn the ungated bkout base from
    #     -9.22% (early) / +1.33% (late) into positive on both halves. Every
    #     gated variant beats its ungated parent in both windows.
    #   - volume_spike >= 1.5 must be a HARD gate. Soft-scoring it (volsoft)
    #     roughly doubles trade count and destroys the edge (0.9x/1.9x vs
    #     1.2x/96.7x). This CONTRADICTS the post-hoc "low volume wins" read from
    #     the iter-0 CSV — that finding did not survive being tested forward.
    #
    # WHAT DID NOT:
    #   - Loosening the gates (loose2/loose3, adx25, gap25, band5468) produces
    #     the biggest headline totals but is entirely a LATE-window artefact —
    #     all of them are negative in the early half. Do not deploy these.
    #   - The +6-11% "late window" numbers at 80-93% WR are one favourable
    #     month, not an edge estimate. 8-12 trades per half is below what this
    #     process can distinguish from noise.
    #
    # REGIME SPLIT (the most useful finding): the two families are complementary.
    #   The zone/dip-buy family (prod) wins the early chop and dies in the late
    #   trend; the gated breakout family does the reverse. Neither is a
    #   standalone all-weather 60m/15m profile on this evidence.
    # =========================================================================

    # ---- survivors: positive in BOTH independent halves ----
    "tf_v5_tp14sl8":         _bk5(tp=1.4, sl=0.8, trail=0.55, arm=0.9),
    "tf_v5_base_volhard":    _bk5(),

    # ---- kept for the next window's re-test (late-window-only so far) ----
    "tf_v5_band5468":        _bk5(htf_band=(54, 68)),
    "tf_v5_adx25":           _bk5(adx_min=25),

    # ---- the volume-hard-gate control; do not delete, it anchors the finding --
    "tf_v5_base_volsoft":    _bk5(vol_hard=False),

    # ============ V6 — ATR-SCALED EXITS: TESTED AND REJECTED =================
    # Jul 19 2026. Engine gained real ATR-sized exits (`atr_stop_mult` /
    # `atr_tp_mult` in BacktestProfile, rolling ATR14 on the entry TF). The
    # hypothesis did NOT survive being manipulated rather than observed.
    #
    # THE DIAGNOSTIC (386 pooled trades) looked compelling:
    #   stop distance in ATR units, pooled:   0.6-0.9 ATR -> 0.59x PF / 65% SL
    #                                         1.6-2.2 ATR -> 2.11x PF / 24% SL
    #                                         2.2+   ATR -> 3.69x PF / 10% SL
    #   within-symbol control (each symbol split at its own median, so this is
    #   not symbol selection): tight half 205T 47% WR 0.87x vs wide half 181T
    #   62% WR 1.80x, with 6 of 7 symbols individually agreeing.
    #   And it looked causal rather than regime: in the top ATR bucket the
    #   non-stopped trades averaged +1.087% (best of any bucket) with 82% of
    #   winners TP-capped, i.e. "direction is right, geometry is wrong".
    #
    # THE ACTUAL TEST, on the ungated base where the 55%-SL population lives:
    #   opt_v1_bkout_steep_slope (fixed 0.7%)  113T  44% WR   -7.89%  0.86x
    #   tf_v6_raw_atr_sl18                      97T  52% WR  -10.08%  0.83x
    #   tf_v6_raw_atr_sl22                      93T  54% WR   -8.82%  0.85x
    #   tf_v6_raw_atr_sl18_tp32                 94T  45% WR  -16.40%  0.75x
    #   tf_v6_raw_atr_sl22_tp40                 80T  46% WR   -3.17%  0.95x
    #
    # Win rate moved EXACTLY as predicted (44% -> 52-54%) and expectancy still
    # got worse: fewer, bigger losses instead of more, smaller ones. Widening
    # the stop bought back the noise-stopouts and paid full price for them.
    # The ATR relationship was a proxy for "this strategy has edge in calm
    # conditions", not a causal statement about stop placement.
    #
    # On the V5-gated variants ATR sizing is a no-op-to-slightly-negative
    # (3.67x -> 3.11x best case, identical trade counts) because those gates
    # already select calm setups — their stops sit at 1.8+ ATR before any change.
    #
    # SECOND TIME a post-hoc bucket finding inverted under forward test in this
    # profile family (the first was "low volume ratio wins"). Bucket stats on a
    # pooled trade population are hypotheses, not findings.
    #
    # Kept: the two least-bad ATR variants, as anchors so this is not re-run.
    "tf_v6_raw_atr_sl22_tp40": _bkout() | {"atr_stop_mult": 2.2, "atr_tp_mult": 4.0},
    "tf_v6_atr_sl22":          _bk5(tp=1.4, sl=0.8, trail=0.55, arm=0.9) | {"atr_stop_mult": 2.2},

    # ========== V7a — PURE TRAILING EXIT: CONFIRMED, BEST RESULT =============
    # Jul 19 2026. The one ATR-diagnostic finding that never got invalidated:
    # 82% of winners in volatile conditions and 42% in calm were TP-capped —
    # exiting at the ceiling, not because the move ended. Sweeping the TP level
    # (0.8-2.0, best 1.4) only relocates the ceiling. These remove it: TP parked
    # at 50% so it can never bind; the trailing stop is the only profit exit.
    #
    # This is the most trustworthy result in the whole V5-V7 sequence because
    # the ENTRIES ARE IDENTICAL (20T, and 8T/12T in each half) — only the exit
    # rule changes, so no selection effect is possible. Both halves improve:
    #
    #   variant                     EARLY          LATE        60d total   PF
    #   tf_v5_tp14sl8 (fixed 1.4)  8T +1.03%   12T +6.36%      +7.39%    3.67x
    #   tf_v7_trail_a35_t25        8T +3.24%   12T +7.03%     +10.27%    4.99x
    #   tf_v7_trail_a80_t50        8T +1.64%   12T +7.34%      +8.98%    4.25x
    #   tf_v7_trail_a35_t35        8T +2.01%   12T +6.54%      +8.55%    4.09x
    #   tf_v7_hybrid_tp25          8T +2.07%   12T +6.20%      +8.26%    3.99x
    #
    # +39% total PnL for the winner, and the gain is largest in the EARLY half
    # where the fixed-TP parent was weakest (+1.03% -> +3.24%). Win rate also
    # rose 70% -> 75%, which is not what you would expect if this were just
    # trading TP hits for smaller trailing exits.
    "tf_v7_trail_a35_t25":  _bk5(tp=50.0, sl=0.8, trail=0.25, arm=0.35),
    "tf_v7_trail_a80_t50":  _bk5(tp=50.0, sl=0.8, trail=0.50, arm=0.80),
    "tf_v7_hybrid_tp25":    _bk5(tp=2.5, sl=0.8, trail=0.40, arm=0.45),

    # ======= V7b — VOLATILITY CEILING (entry filter): CONFIRMED on raw =======
    # Distinct from the REJECTED ATR *stop* test (V6): this SKIPS high-vol
    # entries rather than trying to survive them with a wider stop. Removing bad
    # trades and surviving them are different interventions — and the results
    # differ accordingly.
    #
    #   opt_v1_bkout_steep_slope (no cap) 108T 45% WR  -5.50%  0.89x  [E -6.83 / L +1.33]
    #   tf_v7_raw_atrcap045                43T 65% WR +11.83%  2.01x  [E +6.10 / L +5.73]
    #   tf_v7_raw_atrcap070                64T 52% WR  +1.02%  1.04x  [E -0.30 / L +1.33]
    #
    # Positive in BOTH halves, and at 43 trades it has the best sample-to-quality
    # tradeoff of anything found — roughly 2x the trade count of the V5-gated
    # survivors at a comparable PF.
    #
    # VERIFIED NOT A DISGUISED SYMBOL FILTER (0.45% sits below HYPE/ZEC median
    # ATR, so this needed checking): dropping HYPE+ZEC outright gives only
    # 49T/1.13x, versus 43T/2.01x for the cap. The cap also removes SOL's and
    # ETH's volatile PERIODS (SOL 16T/-2.69% -> 11T/+1.77%) and keeps HYPE's two
    # calm-condition winners. It is a time-varying filter, not symbol selection.
    #
    # CAVEAT: parameter-sensitive. 0.45 works, 0.70 does not (early half -0.30%).
    # Re-check the threshold on the next independent window before trusting it.
    #
    # On the V5-GATED base the cap is redundant — those gates already select calm
    # setups, so it only shrinks the sample (3-4 trades in the early half) for no
    # PnL gain (+7.05% vs +7.39%). Not kept.
    "tf_v7_raw_atrcap045":  _bkout() | {"max_entry_atr_pct": 0.45},
    "tf_v7_raw_atrcap070":  _bkout() | {"max_entry_atr_pct": 0.70},
    # the natural combination — trailing exit + vol ceiling on the raw base
    "tf_v7_raw_cap045_trail": _bkout() | {
        "max_entry_atr_pct": 0.45,
        "take_profit_pct": 50.0, "trailing_stop_pct": 0.25, "arm_trailing_stop_pct": 0.35,
    },

    # ================= V9 — 2-YEAR ITERATION (Jul 20 2026) ===================
    # First iteration with enough data to select on QUARTERLY CONSISTENCY rather
    # than total PnL. 9 quarters, 2024-Q3..2026-Q3, spanning 2 UP, 2 CHOP and 4
    # DOWN quarters. Baseline to beat:
    #
    #   tf_v8_band5468_trail   231T  7/9 quarters +  +16.3%  1.28x   ++-+-++++
    #   tf_v8_trail_tp30       193T  6/9           +13.7%  1.31x   ++---++++
    #   tf_v4_zone3855_tp9     244T  3/9            -5.8%  0.92x   ------+++  (prod)
    #   tf_v3_rsizone_17t      303T  3/9            -3.9%  0.96x   --+---++-  (prod)
    #
    # Selection rule for this round: a change must hold or improve the 7/9
    # quarterly hit rate. Total PnL and PF are tiebreakers only — every previous
    # round of this project was led astray by optimising them directly.
    "tf_v9_base":        _bk5(htf_band=(54, 68), tp=3.0, sl=0.8, trail=0.25, arm=0.35),

    # ---- band width around the 54-68 winner ----
    "tf_v9_band5270":    _bk5(htf_band=(52, 70), tp=3.0, sl=0.8, trail=0.25, arm=0.35),
    "tf_v9_band5666":    _bk5(htf_band=(56, 66), tp=3.0, sl=0.8, trail=0.25, arm=0.35),
    "tf_v9_band5072":    _bk5(htf_band=(50, 72), tp=3.0, sl=0.8, trail=0.25, arm=0.35),

    # ---- trailing geometry: how much giveback, and how early it arms ----
    "tf_v9_trail20":     _bk5(htf_band=(54, 68), tp=3.0, sl=0.8, trail=0.20, arm=0.35),
    "tf_v9_trail35":     _bk5(htf_band=(54, 68), tp=3.0, sl=0.8, trail=0.35, arm=0.35),
    "tf_v9_arm25":       _bk5(htf_band=(54, 68), tp=3.0, sl=0.8, trail=0.25, arm=0.25),
    "tf_v9_arm50":       _bk5(htf_band=(54, 68), tp=3.0, sl=0.8, trail=0.25, arm=0.50),

    # ---- stop width ----
    "tf_v9_sl06":        _bk5(htf_band=(54, 68), tp=3.0, sl=0.6, trail=0.25, arm=0.35),
    "tf_v9_sl10":        _bk5(htf_band=(54, 68), tp=3.0, sl=1.0, trail=0.25, arm=0.35),

    # ---- the two gates that define the family ----
    "tf_v9_adx25":       _bk5(htf_band=(54, 68), adx_min=25, tp=3.0, sl=0.8, trail=0.25, arm=0.35),
    "tf_v9_gap25":       _bk5(htf_band=(54, 68), gap_max=2.5, tp=3.0, sl=0.8, trail=0.25, arm=0.35),
    "tf_v9_gap10":       _bk5(htf_band=(54, 68), gap_max=1.0, tp=3.0, sl=0.8, trail=0.25, arm=0.35),

    # ---- intraday vol ceiling, which held up on the 60d window ----
    "tf_v9_atrcap":      _bk5(htf_band=(54, 68), tp=3.0, sl=0.8, trail=0.25, arm=0.35) | {"max_entry_atr_pct": 0.45},
    "tf_v9_atrcap070":   _bk5(htf_band=(54, 68), tp=3.0, sl=0.8, trail=0.25, arm=0.35) | {"max_entry_atr_pct": 0.70},

}
