# =============================================================================
# 15m TREND (tf_v9) — applying the 2026-08-19 dip-family learnings
#
# Control is an exact replica of live 15m_tf_v9_atrcap070 (prod_profiles.py,
# exported 2026-08-18): 15m entry / 60m trend+exit, TP 3.0, SL 0.8,
# trail 0.25 armed at 0.35, 12h timeout, market-regime filter ON, 24/7.
#
# WHAT THE DIP WORK SAYS TO TRY HERE
#   1. THE ARM IS THE LEVER, NOT THE TRAIL. On the dip family, sweeping the
#      trailing arm produced a smooth curve with a clear optimum while trail
#      width was pure noise. tf_v9 ships arm 0.35 / trail 0.25 and the existing
#      trend_variants only ever tested arm 0.25/0.35/0.50 — three points, with
#      the shipped value in the middle and no reach above 0.5. If the same
#      shape holds, the optimum may be well outside that range.
#   2. ema_slope's lookback is newly configurable. tf_v9 uses ema_slope in BOTH
#      its trend set (60m) and entry set (15m), and until today every one of
#      those compared just two adjacent bars. On 15m that is an extremely noisy
#      read of "rising". Longer lookbacks are now expressible.
#   3. The regime filter is recorded as a measured NO-OP for tf_v9 (64k bars
#      vetoed, 1 trade changed). Worth confirming on this window, because if it
#      is inert it is a free simplification and one less thing to reason about.
#   4. BNB is recorded as the leg to drop. Prod still includes it.
#
# METHOD DISCIPLINE CARRIED OVER — every one of these killed a candidate today:
#   - Run on ALL NINE symbols. Four-symbol fits did not survive out of sample.
#   - Judge on per-trade / PF / tail, NOT total return: totals here are sums of
#     per-trade percentages and are capital-blind, so they are only comparable
#     between variants with similar trade counts.
#   - For any filter, check the expectancy of the trades it REMOVES against the
#     ones it keeps. "PF and worst-trade improved" is gameable by deleting the
#     single worst trade.
#   - PLATEAU TEST: a parameter result is only believable if neighbouring
#     settings agree. Two candidates today passed every summary check and then
#     flipped sign between adjacent cells.
# =============================================================================

_ALL9 = ["SOL_USDC","ZEC_USDC","BTC_USDC","ETH_USDC","BNB_USDC","XRP_USDC","DOGE_USDC","SEI_USDC","SUI_USDC"]
_EX_BNB = [s for s in _ALL9 if s != "BNB_USDC"]

_TF9_BASE = {
    "display_name": "t_base",
    "strategy_type": "trend_following",
    "market_type": "SPOT",
    "entry_timeframe": "15",
    "trend_timeframe": "60",
    "exit_timeframe": "60",
    "take_profit_pct": 3.0,
    "stop_loss_pct": 0.8,
    "trailing_stop_pct": 0.25,
    "arm_trailing_stop_pct": 0.35,
    "use_trailing_stop": True,
    "signal_cooldown_minutes": 15,
    "sl_cooldown_minutes": 130,
    "tp_cooldown_minutes": 70,
    "min_signal_confidence": 70.0,
    "min_volume_ratio": 1.0,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 12,
    "use_market_regime_filter": True,
    "regime_timeframe": "60",
    "max_open_positions_per_profile": 2,
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "trend",
    "min_position_age_for_trend_check": 60,
    "trading_hours": [],
    "symbols": _ALL9,
}

def _trend_inds(slope_lb=1):
    return [
        {"type": "ema_cross", "params": {}},
        {"type": "adx_regime", "params": {"min_adx": 30, "max_adx": 65, "hard_stop": True}},
        {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.025,
                                         "lookback_bars": slope_lb, "hard_stop": True}},
        {"type": "ema_gap", "params": {"max_gap_pct": 1.5, "mode": "max", "hard_stop": True}},
        {"type": "rsi_range", "params": {"min": 54, "max": 68, "invert": True, "hard_stop": True}},
    ]

def _entry_inds(slope_lb=1):
    return [
        {"type": "rsi_threshold", "params": {"period": 14, "min_value": 55, "use_momentum": True,
                                             "early_threshold": 50, "hard_stop": True}},
        {"type": "rsi_momentum", "params": {"min_momentum": 1, "max_momentum": 8, "lookback_candles": 1}},
        {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 0.03,
                                         "lookback_bars": slope_lb, "hard_stop": True}},
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 72, "max_value": 100, "hard_stop": True}},
        {"type": "volume_spike", "params": {"min_ratio": 1.5, "max_ratio": 10, "hard_stop": True}},
        {"type": "price_vs_ema", "params": {"ema": 20, "min_gap_pct": -0.3, "max_gap_pct": 1.5}},
        {"type": "price_vs_vwap", "params": {}},
        {"type": "ema_cross", "params": {"use_slope": False, "min_slope_pct": 0.01, "hard_stop": True}},
        {"type": "atr_regime", "params": {"max_pct": 0.7, "period": 14, "hard_stop": True}},
    ]

def _v(name, *, arm=0.35, trail=0.25, tslope=1, eslope=1, regime=True, symbols=None, sl=0.8, tp=3.0):
    return {**_TF9_BASE, "display_name": name,
            "arm_trailing_stop_pct": arm, "trailing_stop_pct": trail,
            "take_profit_pct": tp, "stop_loss_pct": sl,
            "use_market_regime_filter": regime,
            "symbols": symbols or _ALL9,
            "trend_indicators": _trend_inds(tslope), "min_indicators_required": 5,
            "entry_indicators": _entry_inds(eslope), "min_entry_indicators_required": 7}

TF15_VARIANTS = {
    # ---- control: exact live config -----------------------------------------
    "t_base": _v("t_base"),

    # ---- 1. ARM SWEEP (trail fixed at the live 0.25) ------------------------
    "t_arm0.25": _v("t_arm0.25", arm=0.25),
    "t_arm0.45": _v("t_arm0.45", arm=0.45),
    "t_arm0.60": _v("t_arm0.60", arm=0.60),
    "t_arm0.80": _v("t_arm0.80", arm=0.80),
    "t_arm1.20": _v("t_arm1.20", arm=1.20),

    # ---- 1b. TRAIL SWEEP (arm fixed at the live 0.35) -----------------------
    "t_trail0.15": _v("t_trail0.15", trail=0.15),
    "t_trail0.40": _v("t_trail0.40", trail=0.40),
    "t_trail0.60": _v("t_trail0.60", trail=0.60),

    # ---- 2. ema_slope lookback (the new capability) -------------------------
    "t_tslope2":  _v("t_tslope2",  tslope=2),
    "t_tslope4":  _v("t_tslope4",  tslope=4),
    "t_eslope2":  _v("t_eslope2",  eslope=2),
    "t_eslope4":  _v("t_eslope4",  eslope=4),
    "t_bothslope2": _v("t_bothslope2", tslope=2, eslope=2),

    # ---- 3. is the regime filter really inert? ------------------------------
    "t_noregime": _v("t_noregime", regime=False),

    # ---- 4. symbol roster ---------------------------------------------------
    "t_exBNB": _v("t_exBNB", symbols=_EX_BNB),
}


# =============================================================================
# ROUND 1b — distance_from_high / distance_from_low on a TREND profile.
#
# Both indicators were built for the dip family, where they mean "price has
# fallen far enough". On a trend follower the interesting question is the
# MIRROR IMAGE, and it is genuinely two-sided:
#
#   CONTINUATION reading — only buy while price is still pressed against the
#     recent high (distance_from_high with a SMALL max_pct_below). Trend
#     followers are supposed to buy strength, and tf_v9 currently has no
#     indicator that says "we are near the highs" — ema_gap and price_vs_ema
#     both measure distance from a moving average, which is a different thing.
#
#   PULLBACK reading — only buy after price has backed off the high by a
#     little (a band like 1.5-4% below). tf_v9's entry set already leans this
#     way via price_vs_ema (-0.3% to +1.5% of EMA20), so this tests whether an
#     explicit price-structure version beats the EMA-relative one.
#
#   OFF-THE-LOW reading — distance_from_low with a MINIMUM distance, i.e.
#     "price has already travelled up from the recent low", which filters out
#     entries that are really just bounces inside a base.
#
# Note distance_from_low's max_pct_above is not nullable, so an open-ended
# "at least N% above the low" is written as max_pct_above 999.
#
# Lookbacks on 15m: 24 bars = 6h, 48 = 12h, 96 = 24h. Both engines cap
# _candle_history at 100 bars, so lookback_bars must stay <= 100.
#
# Each is added as a hard_stop AND min_entry_indicators_required goes 7 -> 8,
# which per the project's own note makes it a pure veto rather than shifting
# the scoring threshold.
#
# BEWARE THE ASYMMETRIC FAILURE MODES: distance_from_high fails OPEN on short
# history (it silently passes), distance_from_low fails CLOSED. With
# WARMUP_BARS priming the cache in backtests this should not bite, but it is
# the difference between "gate inactive" and "no trades" if it ever does.
# =============================================================================

def _dfh(lb, minb, maxb):
    return {"type": "distance_from_high", "params": {"lookback_bars": lb,
            "min_pct_below": minb, "max_pct_below": maxb, "hard_stop": True}}
def _dfl(lb, mina, maxa=999.0):
    return {"type": "distance_from_low", "params": {"lookback_bars": lb,
            "min_pct_above": mina, "max_pct_above": maxa, "hard_stop": True}}

def _v_extra(name, extra, **kw):
    v = _v(name, **kw)
    v["entry_indicators"] = v["entry_indicators"] + [extra]
    v["min_entry_indicators_required"] = 8      # was 7 -> pure veto
    return v

TF15_VARIANTS.update({
    # --- CONTINUATION: near the recent high (plateau built in over the band) --
    "t_nearhigh_1_24h":  _v_extra("t_nearhigh_1_24h",  _dfh(96, 0.0, 1.0)),
    "t_nearhigh_2_24h":  _v_extra("t_nearhigh_2_24h",  _dfh(96, 0.0, 2.0)),
    "t_nearhigh_4_24h":  _v_extra("t_nearhigh_4_24h",  _dfh(96, 0.0, 4.0)),
    "t_nearhigh_2_6h":   _v_extra("t_nearhigh_2_6h",   _dfh(24, 0.0, 2.0)),
    "t_nearhigh_2_12h":  _v_extra("t_nearhigh_2_12h",  _dfh(48, 0.0, 2.0)),

    # --- PULLBACK: backed off the high by a band ------------------------------
    "t_pullback_1_4_24h": _v_extra("t_pullback_1_4_24h", _dfh(96, 1.0, 4.0)),
    "t_pullback_2_6_24h": _v_extra("t_pullback_2_6_24h", _dfh(96, 2.0, 6.0)),

    # --- OFF-THE-LOW: already travelled up from the base ----------------------
    "t_offlow_2_24h":  _v_extra("t_offlow_2_24h",  _dfl(96, 2.0)),
    "t_offlow_4_24h":  _v_extra("t_offlow_4_24h",  _dfl(96, 4.0)),
    "t_offlow_6_24h":  _v_extra("t_offlow_6_24h",  _dfl(96, 6.0)),
    "t_offlow_2_6h":   _v_extra("t_offlow_2_6h",   _dfl(24, 2.0)),

    # --- the two best-motivated ideas combined --------------------------------
    "t_nearhigh2_offlow2": {**_v_extra("t_nearhigh2_offlow2", _dfh(96, 0.0, 2.0)),
                            "min_entry_indicators_required": 9},
})
TF15_VARIANTS["t_nearhigh2_offlow2"]["entry_indicators"] = (
    _entry_inds(1) + [_dfh(96, 0.0, 2.0), _dfl(96, 2.0)])


# =============================================================================
# RESULT — STOP. THE tf_v9 15m FAMILY FAILS TICK VALIDATION. (2026-08-19)
#
# Every one of the 28 variants came back negative, INCLUDING the control, which
# contradicted the recorded "+9-11bps net, one deployable directional edge".
# Chasing that contradiction is the actual finding of this round.
#
# Step 1 — is the replica wrong? Ran the validated trend_variants variant
# tf_v9_atrcap070 over the identical window/roster/fill model:
#     tf_v9_atrcap070, 2yr, 9 syms, TICK:  n=263  WR 67.7%  avg -0.021%  PF 0.93
# So no: the validated variant is negative too. The replica is fine (t_base
# -0.04% vs the variant -0.02%; the small gap is prod's stricter entry
# threshold of 7-of-9 vs the variant's 6, min_volume_ratio 1.0 vs 0.0, and the
# trend-invalidation exit that prod has and the variant does not).
#
# Step 2 — same config, ONLY the fill model changed:
#     CANDLE fills: n=241 WR 69.7% avg +0.079% total +19.0% PF 1.28
#     TICK   fills: n=263 WR 67.7% avg -0.021% total  -5.5% PF 0.93
# On the 229 trades present in both runs the mean difference is -0.080pp per
# trade. The candle-mode +8bps is in line with the numbers this family was
# originally signed off on; under intra-candle fills the edge is gone.
#
# Step 3 — the mechanism, which is what makes it believable:
#     avgWin   +0.520% (candle) -> +0.420% (tick)     <- winners are CLIPPED
#     avgLoss  -0.937% (candle) -> -0.943% (tick)     <- losses barely move
#     exit reason changes on 26% of shared trades, dominated by
#     trailing_stop <-> stop_loss flips (28 and 22).
# The 0.25% trailing stop is narrower than ordinary intra-bar noise on 15m, so
# the candle model — which only ever sees the close — lets winners run that the
# real path would have stopped out. This is EXACTLY the dip_v6 failure
# ("tight 1% trail is a candle-mode artifact, do-not-deploy"), one timeframe
# down and on the family that is currently live.
#
# CORROBORATION FROM REALITY: the project's own measured live figure is
# -0.1623%/trade before fees (see memory: execution_economics). That is
# consistent with the tick result (-0.02%) and flatly inconsistent with the
# candle result (+0.08%) — prod is in fact worse than tick-mode predicts, which
# is the expected direction given real slippage on top.
#
# Ex-BNB does not rescue it: n=215 avg +0.029% GROSS, i.e. 2.9bps against an
# 8.76bps taker break-even — still net negative. Per symbol only SEI (+0.356%),
# SOL (+0.172%), DOGE (+0.129%), SUI (+0.061%) and XRP (+0.028%) are positive;
# BNB (-0.243%), ETH (-0.141%), ZEC (-0.103%) and BTC (-0.034%) are not.
# 5/9 quarters positive, and the three worst are 2025Q1/Q3/Q4.
#
# WHAT NOT TO CONCLUDE: this does not say the 28 variants were fairly tested.
# They were all measured against a baseline with no edge, so "nothing beat the
# control" is uninformative here. The one result that stands on its own is the
# ARM SWEEP, because it is smooth and monotone rather than a comparison to a
# broken baseline:
#     arm  0.25   0.35*  0.45   0.60   0.80   1.20
#     avg -0.01% -0.04% -0.07% -0.09% -0.09% -0.15%
#     WR   74.5%  66.3%  59.9%  53.0%  48.2%  37.0%
# Widening the arm is unambiguously wrong for a fast trend profile — the
# opposite of the dip family, where wider was better. Tighter is better here,
# and 0.25 (the tightest tested) is the best cell, which points at the same
# conclusion from the other end: this profile lives or dies on how much of a
# small move it can bank before noise takes it back.
#
# NEXT STEP IS NOT MORE BACKTESTING. Prod has been running these profiles
# live — compare realised prod fills against both models before touching
# anything. If prod matches tick, the family needs rebuilding around a wider
# stop/trail (which the arm sweep says will cost win rate) or retiring.
# =============================================================================
