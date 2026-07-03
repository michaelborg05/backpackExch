# =============================================================================
# TREND-FOLLOWING SHORT VARIANTS
# Mirror of trend_variants.py — ride confirmed downtrends instead of fading them.
#
# Purpose: complement mrs_v13 (mean-reversion short). The MR profile fades
# overbought exhaustion and sits idle during sustained sell-offs. These profiles
# do the opposite: they require a confirmed 60m downtrend and short the pullbacks.
#
# Structure (mirror of the long trend-follower):
#   - 60m trend gate: confirmed downtrend (falling EMAs, ADX cap)
#   - 15m entry: pullback toward EMA20 that rolls over (RSI mid-band)
#
# =============================================================================
# CURATED VARIANT SET — RATIONALE FOR CULLED PROFILES
# =============================================================================
# Removed after multi-round backtesting:
#   - v1_curated_symbols : engine never applied per-variant symbol filter;
#                          produced identical trades to base.
#   - v3_breakdown_momentum : -0.16% avg on clean 42d data, 50% WR.
#                             Shorting fresh lows underperformed fading rallies.
#   - v4_hardgate_strict : -0.03% avg on clean data. Over-selectivity hurt.
#   - v9_calm_market_tight : htf_adx<=22 was a crash-week artefact (n=4 OOS).
#   - v10_calm_market_wide_tp : actively losing (n=5, 20% WR, -0.29% avg).
#                               The single clearest overfit in the set.
#   - v12_validated_combined : produced identical trades to v11. Redundant.
#   - v13_high_rsi_short : 71% WR finding evaporated on clean data (52% WR).
#                          Single-window pattern, not a real signal.
#   - v14_robust_baseline : identical to v11. Kept v11 as the canonical name.
#
# RETAINED:
#   - base, v2, v5, v6, v7, v8 : exploratory variants spanning the design space
#   - v11 : regime-robust workhorse (htf_adx<=25 + pct_b>=0.35 + late trail)
#   - v15, v16, v17 : low-volume rally finding — the strongest validated signal
# =============================================================================

_TF_SHORT_BASE = {
    "display_name": "trend_following_short_profile",
    "strategy_type": "short_trend_following",
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
    "max_position_hours": 6,
    "use_market_regime_filter": True,

    # 60m DOWNTREND GATE
    # NOTE: deliberately NO adx_regime hard gate at base level — 60m ADX < 22
    # for most pairs even mid-crash, so a strict gate filters out valid entries.
    "trend_indicators": [
        {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.02, "hard_stop": True}},
        {"type": "ema_slope", "params": {"ema": 50, "direction": "falling", "min_slope_pct": 0.0}},
        {"type": "adx_regime", "params": {"min_adx": 15, "max_adx": 60}},
    ],
    "min_indicators_required": 2,

    # 15m PULLBACK-AND-ROLLOVER ENTRY
    # price rallies back near/above the falling 15m EMA20, RSI in mid-band
    # (38-58, NOT yet oversold), then rolls over.
    "entry_indicators": [
        # falling 15m EMA20 — local momentum down
        {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.0, "max_slope_pct": 0.30, "hard_stop": True}},
        # RSI mid-band: above 38 (not crashed — MR territory) AND below 58 (not in a real bounce)
        {"type": "rsi_range", "params": {"min": 38, "max": 58, "invert": True, "hard_stop": True}},
        # price pulled back toward EMA20 (the short-side "rip to ema") — fade the bounce
        {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 0.8}},
        # price below VWAP confirms intraday sellers in control
        {"type": "price_above_vwap", "params": {"min_gap_pct": -8.0, "max_gap_pct": 0.5}},
        # bear close: sellers won the candle into the close
        {"type": "reversal_candle", "params": {"pattern": "bear_close", "max_close_pct": 0.45, "max_rise_from_close_pct": 0.6}},
        # upper BB ceiling — block shorts initiated at the very bottom of the band
        {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.10, "max_pct_b": 0.75}},
    ],
    "min_entry_indicators_required": 4,
}

TREND_SHORT_VARIANTS = {

    # -------------------------------------------------------------------------
    # BASELINE — faithful mirror of the long trend-follower
    # Kept as the comparison anchor.
    # -------------------------------------------------------------------------
    "tfs_base_15m_short": {
        **_TF_SHORT_BASE,
    },

    # -------------------------------------------------------------------------
    # V2: TIGHT TP — high-frequency comparison
    # TP0.8/SL0.7 with tighter trailing and shorter max age. Highest trade
    # count of any variant; useful as a frequency benchmark.
    # Clean OOS: 63.4% WR / +0.044% avg (n=194).
    # -------------------------------------------------------------------------
    "tfs_v2_tight_tp": {
        **_TF_SHORT_BASE,
        "take_profit_pct": 0.8,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.4,
        "arm_trailing_stop_pct": 0.4,
        "max_position_hours": 4,
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V5: PCT_B FILTERED — the first validated refinement
    # Adds bb_pct_b >= 0.35 to base. Clean OOS: 59.7% WR / +0.025% avg (n=144).
    # Modest but real — the pct_b filter is one of the validated signals.
    # -------------------------------------------------------------------------
    "tfs_v5_pctb_filter": {
        **_TF_SHORT_BASE,
        "entry_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.0, "max_slope_pct": 0.30, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 38, "max": 58, "invert": True, "hard_stop": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 0.8}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": -8.0, "max_gap_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bear_close", "max_close_pct": 0.45, "max_rise_from_close_pct": 0.6}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.35, "max_pct_b": 0.85, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V6: HIGH SELECTIVITY — pct_b >= 0.50, ADX gate <=30, armed-late trail
    # Tighter than v5/v11. Clean OOS: 62.5% WR / +0.069% avg (n=48).
    # Demonstrated the armed-late trail fix works (trail exits avg +0.48%).
    # -------------------------------------------------------------------------
    "tfs_v6_high_selectivity": {
        **_TF_SHORT_BASE,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.25,
        "arm_trailing_stop_pct": 0.6,
        "max_position_hours": 6,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "ema_slope", "params": {"ema": 50, "direction": "falling", "min_slope_pct": 0.0}},
            {"type": "adx_regime", "params": {"min_adx": 15, "max_adx": 30, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.0, "max_slope_pct": 0.30, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 40, "max": 56, "invert": True, "hard_stop": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": -1.0, "max_gap_pct": 0.8}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": -6.0, "max_gap_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bear_close", "max_close_pct": 0.40, "max_rise_from_close_pct": 0.5}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.50, "max_pct_b": 0.90, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
    },

    # -------------------------------------------------------------------------
    # V7: ARMED-LATE TRAIL — v5 entries with the trail behavior fix
    # Trail armed at +0.6% gain, tight 0.2% trail. Demonstrates that the trail
    # fix improves PnL: trail exits avg +0.48% (vs +0.11% with the old trail).
    # Clean OOS: 52.3% WR / +0.036% avg (n=132).
    # -------------------------------------------------------------------------
    "tfs_v7_armed_late_trail": {
        **_TF_SHORT_BASE,
        "take_profit_pct": 0.8,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.2,
        "arm_trailing_stop_pct": 0.6,
        "entry_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.0, "max_slope_pct": 0.30, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 38, "max": 58, "invert": True, "hard_stop": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 0.8}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": -8.0, "max_gap_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bear_close", "max_close_pct": 0.45, "max_rise_from_close_pct": 0.6}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.35, "max_pct_b": 0.85, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V8: WIDER TP + FILTERED — TP 1.2 comparison
    # TP1.2 with pct_b filter. Clean OOS: 47.8% WR / +0.068% avg (n=115).
    # Lower WR but slightly better avg than v5 — the wider TP catches bigger
    # moves. Useful comparison for TP sizing.
    # -------------------------------------------------------------------------
    "tfs_v8_wide_tp_filtered": {
        **_TF_SHORT_BASE,
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.3,
        "arm_trailing_stop_pct": 0.8,
        "max_position_hours": 8,
        "entry_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.0, "max_slope_pct": 0.30, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 38, "max": 58, "invert": True, "hard_stop": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 0.8}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": -8.0, "max_gap_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bear_close", "max_close_pct": 0.45, "max_rise_from_close_pct": 0.6}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.35, "max_pct_b": 0.85, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V11: REGIME-ROBUST WORKHORSE
    # The OOS-validated combination: htf_adx<=25 (NOT 22) + pct_b>=0.35 +
    # armed-late trail. Most consistent variant across regimes — positive in
    # 4 of 5 weekly windows including the non-crash periods.
    # Clean OOS: 64.5% WR / +0.145% avg (n=31).
    # -------------------------------------------------------------------------
    "tfs_v11_calm_relaxed": {
        **_TF_SHORT_BASE,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.25,
        "arm_trailing_stop_pct": 0.6,
        "max_position_hours": 6,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "ema_slope", "params": {"ema": 50, "direction": "falling", "min_slope_pct": 0.0}},
            {"type": "adx_regime", "params": {"min_adx": 12, "max_adx": 25, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.0, "max_slope_pct": 0.30, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 38, "max": 58, "invert": True, "hard_stop": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 0.8}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": -8.0, "max_gap_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bear_close", "max_close_pct": 0.45, "max_rise_from_close_pct": 0.6}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.35, "max_pct_b": 0.85, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # =========================================================================
    # LOW-VOLUME RALLY VARIANTS — the strongest validated signal in the data
    # =========================================================================
    # WIN median vol_ratio: 0.61. LOSS median: 0.71. Low-volume rallies have
    # no real buying pressure — shorts work. High-volume rallies are real
    # demand and they squeeze shorts.
    #
    # Stacked filter (no BTC + htf_adx<=25 + pct_b>=0.35 + vol_ratio<=0.6):
    #   89.5% WR / +0.479% avg / +9.09% total (n=19)
    # Per-symbol balanced: ETH 91% WR, BNB 87.5% WR.
    # Tightened to vol<=0.5: 94.1% WR / +0.505% avg (n=17)
    # =========================================================================

    # -------------------------------------------------------------------------
    # V15: LOW-VOL RALLY SHORT — the validated multi-filter stack
    # v11's logic + vol_ratio <= 0.6 hard gate. Single biggest validated lift
    # on clean data. Trade frequency low — only fires on weak rallies.
    # -------------------------------------------------------------------------
    "tfs_v15_lowvol_rally_short": {
        **_TF_SHORT_BASE,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.25,
        "arm_trailing_stop_pct": 0.6,
        "max_position_hours": 6,
        # Cap the global volume gate — base profile had min_volume_ratio 1.1
        # which would FORCE high-volume entries. We want the opposite.
        "min_volume_ratio": 0.0,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "ema_slope", "params": {"ema": 50, "direction": "falling", "min_slope_pct": 0.0}},
            {"type": "adx_regime", "params": {"min_adx": 12, "max_adx": 25, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.0, "max_slope_pct": 0.30, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 38, "max": 58, "invert": True, "hard_stop": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 0.8}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": -8.0, "max_gap_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bear_close", "max_close_pct": 0.45, "max_rise_from_close_pct": 0.6}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.35, "max_pct_b": 0.85, "hard_stop": True}},
            # KEY: low-volume rally — fade weak bounces, not strong demand
            {"type": "volume_spike", "params": {"min_ratio": 0.0, "max_ratio": 0.6, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
    },

    # -------------------------------------------------------------------------
    # V16: STAR LOW-VOL — vol<=0.5, tightest version
    # The cleanest config in the data: 94% WR / +0.50% avg (n=17, no BTC).
    # Very selective — expect 1-2 trades/week. High-confidence sleeve, not a
    # primary income strategy. Symbol exclusion handled at assignment layer
    # (caveat: confirm your engine actually honours per-variant symbol filters
    # before relying on this — earlier v1_curated tests suggest it doesn't).
    # -------------------------------------------------------------------------
    "tfs_v16_star_lowvol": {
        **_TF_SHORT_BASE,
        # symbols handled at assignment layer: ETH_USDC, BNB_USDC (NOT BTC_USDC)
        "take_profit_pct": 1.2,
        "stop_loss_pct": 0.8,
        "trailing_stop_pct": 0.5,
        "arm_trailing_stop_pct": 0.6,
        "max_position_hours": 6,
        "min_volume_ratio": 0.0,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "ema_slope", "params": {"ema": 50, "direction": "falling", "min_slope_pct": 0.0}},
            {"type": "adx_regime", "params": {"min_adx": 12, "max_adx": 25, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.0, "max_slope_pct": 0.30, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 38, "max": 58, "invert": True, "hard_stop": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 0.8}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": -8.0, "max_gap_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bear_close", "max_close_pct": 0.45, "max_rise_from_close_pct": 0.6}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.35, "max_pct_b": 0.85, "hard_stop": True}},
            # Tighter vol cap than v15 — only the weakest rallies
            {"type": "volume_spike", "params": {"min_ratio": 0.0, "max_ratio": 0.5, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
    },

    # -------------------------------------------------------------------------
    # V17: V11 STRUCTURE WITH VOL ADD-ON — middle ground
    # v11 + vol_ratio <= 0.8. Less aggressive filtering than v15 — keeps more
    # trades. Projection ~75% WR / +0.27% avg (no BTC). Recommended as the
    # primary live candidate: balance between frequency and edge.
    # -------------------------------------------------------------------------
    "tfs_v17_v11_with_vol": {
        **_TF_SHORT_BASE,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.25,
        "arm_trailing_stop_pct": 0.6,
        "max_position_hours": 6,
        "min_volume_ratio": 0.0,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "ema_slope", "params": {"ema": 50, "direction": "falling", "min_slope_pct": 0.0}},
            {"type": "adx_regime", "params": {"min_adx": 12, "max_adx": 25, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.0, "max_slope_pct": 0.30, "hard_stop": True}},
            {"type": "rsi_range", "params": {"min": 38, "max": 58, "invert": True, "hard_stop": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 0.8}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": -8.0, "max_gap_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bear_close", "max_close_pct": 0.45, "max_rise_from_close_pct": 0.6}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.35, "max_pct_b": 0.85, "hard_stop": True}},
            # Looser vol cap — keeps more trades than v15/v16
            {"type": "volume_spike", "params": {"min_ratio": 0.0, "max_ratio": 0.8, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
    },

    # =========================================================================
    # TIGHTER ENTRY FILTERS — clean 42d data showed two clean improvements
    # =========================================================================
    # Round-6 findings on the v11/v15/v16/v17 set:
    #   - RSI floor at 43 (not 38): WR 65.7% -> 71.7%, avg +0.14% -> +0.23%
    #     ALL 3 v16 SLs had RSI < 40.5 at entry. RSI 38-42 is too soft.
    #   - bb_pct_b floor at 0.40 (not 0.35): WR -> 78.3%, avg -> +0.45%
    #     v17 base 0.094% avg lifts to 0.486% with pct_b>=0.40 alone.
    #   - Combined RSI>=43 + pct_b>=0.40: consistent +0.42-0.50% avg across
    #     every variant tested. n drops ~75% so trade frequency is the cost.
    #   - Trail exits avg +0.50% (working as designed); max_age exits avg ~0%
    #     are the remaining drag — 6-hour holds that resolve at break-even.
    # =========================================================================

    # -------------------------------------------------------------------------
    # V18: V17 + TIGHTER RSI/PCT_B — the "make v17 sharper" variant
    # v17's structure (vol<=0.8) with RSI floor 43 and pct_b floor 0.40.
    # Backtest projection on combined data: 71% WR / +0.43% avg.
    # Recommended primary candidate — keeps v17's relative trade frequency
    # while applying the validated entry-quality filters.
    # -------------------------------------------------------------------------
    "tfs_v18_v17_tight_entry": {
        **_TF_SHORT_BASE,
        "take_profit_pct": 1.0,
        "stop_loss_pct": 0.7,
        "trailing_stop_pct": 0.25,
        "arm_trailing_stop_pct": 0.6,
        "max_position_hours": 6,
        "min_volume_ratio": 0.0,
        "trend_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.02, "hard_stop": True}},
            {"type": "ema_slope", "params": {"ema": 50, "direction": "falling", "min_slope_pct": 0.0}},
            {"type": "adx_regime", "params": {"min_adx": 12, "max_adx": 25, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "ema_slope", "params": {"ema": 20, "direction": "falling", "min_slope_pct": 0.0, "max_slope_pct": 0.30, "hard_stop": True}},
            # KEY CHANGE: RSI floor raised from 38 to 43
            {"type": "rsi_range", "params": {"min": 43, "max": 58, "invert": True, "hard_stop": True}},
            {"type": "price_extended_above_ema", "params": {"ema": 20, "min_gap_pct": -1.5, "max_gap_pct": 0.8}},
            {"type": "price_above_vwap", "params": {"min_gap_pct": -8.0, "max_gap_pct": 0.5}},
            {"type": "reversal_candle", "params": {"pattern": "bear_close", "max_close_pct": 0.45, "max_rise_from_close_pct": 0.6}},
            # KEY CHANGE: pct_b floor raised from 0.35 to 0.40
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "min_pct_b": 0.40, "max_pct_b": 0.85, "hard_stop": True}},
            {"type": "volume_spike", "params": {"min_ratio": 0.0, "max_ratio": 0.8, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 5,
    },
}