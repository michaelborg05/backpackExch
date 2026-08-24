# =============================================================================
# 4h-TREND / 1h-ENTRY DISCOVERY — Phase C (2026-08-19)
#
# These came out of a systematic, EXIT-FREE entry search rather than by hand.
# Method, because it is the point:
#
#   PHASE A  Built a labelled matrix ONCE — every 1h bar for 9 symbols over 2yr
#            (163,764 rows), with 45 features (1h + 4h + 1D context + a BTC
#            reference) and FORWARD labels no exit rule touches: MFE, MAE and
#            close-to-close return at 12/24/48h. Null is clean: P(up) 49.0%,
#            MFE/|MAE| = 1.00.
#            Screened 990 feature/threshold filters, keeping only those positive
#            in BOTH halves and across >=7/9 symbols -> 146 survivors.
#
#   PHASE A.2 Re-screened on RETURN / ATR-AT-ENTRY. A high-volatility filter
#            mechanically produces bigger absolute forward returns; that is
#            scale, not edge. Normalising removed the illusion and reordered
#            the table -> 90 risk-adjusted survivors.
#
#   PHASE B  Greedy forward selection from four seeds, one rule per feature,
#            constraints re-checked at every step.
#
#   PHASE B.2 EPISODE WEIGHTING — the step that mattered. Consecutive signal
#            bars in one symbol are one opportunity, not many. Collapsing them
#            (>24h gap starts a new episode) and bootstrapping at episode level:
#
#     combo                       bars  EPISODES  ep.mean  ep.pos%  p(<=0)
#     VOL  capitulation            657      115    +2.028     89%    0.000
#     DIP  deep 2d dip             787       46    +1.873     80%    0.000
#     MOM  h4 RSI + flat daily     664       39    +1.015     67%    0.013
#     MOM2 6-rule momentum        1060      120    -0.081     47%    0.646  <-- NOISE
#
#     MOM2 looked like the best find of the search at bar level (+1.265 radj,
#     stable across halves at +1.251/+1.304, 6 conditions all pulling the same
#     way). At episode level it is NEGATIVE. Its bar-level score came from a
#     few long episodes contributing hundreds of correlated rows each. Any
#     screen counting bars instead of episodes will keep making this mistake.
#
# THE HONEST HEADLINE: the momentum/trend side did not survive. MOM2 is noise
# and MOM fires only 2.1x per symbol-year on 39 episodes. What survives at
# 4h/1h is AGAIN mean reversion — buying capitulation. That is the third
# independent time this project has reached that conclusion.
#
# GEOMETRY, sized from the measured MAE rather than guessed. 1h median ATR is
# 1.05%; these signals fire when 1h ATR >= 2.56%, and their mean MAE over 24h
# is -8.0% (VOL) / -4.6% (DIP). So a conventional stop would sit inside normal
# adverse excursion and be hit roughly half the time. These therefore run the
# dip family's shape — no hard stop, a wide trailing stop, and a logical exit —
# with the arm set near 1.8x the ATR that gates entry (~4.6%), matching the
# ratio that works live on 4h (arm 3.5% / ATR 2.2% = 1.58x) versus the ratio
# that fails on 15m (0.35% / 0.49% = 0.71x).
#
# EXPECT THESE TO LOSE MOST OF THEIR SCREEN NUMBERS. Two exit-free screens
# already failed to transfer to portfolio results today. The screen ranks
# candidates; only the backtest below decides. Judge on per-trade / PF / tail,
# check what any filter REMOVES, and plateau-test any parameter that looks good.
# =============================================================================

_ALL9 = ["SOL_USDC","ZEC_USDC","BTC_USDC","ETH_USDC","BNB_USDC","XRP_USDC","DOGE_USDC","SEI_USDC","SUI_USDC"]

_BASE = {
    "strategy_type": "mean_reversion",
    "market_type": "SPOT",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "exit_timeframe": "60",
    "use_trend_filter": True,
    "use_entry_filter": True,
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_position_age_for_trend_check": 0,
    # logical exit: hold while RSI<55 OR still under EMA20; leave when both flip
    "exit_indicators": [
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
        {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
    ],
    "min_exit_indicators_required": 1,
    "use_trailing_stop": True,
    "arm_trailing_stop_pct": 4.5,      # ~1.8x the 2.56% ATR that gates entry
    "trailing_stop_pct": 1.5,
    "take_profit_pct": 99.0,
    "stop_loss_pct": 99.0,             # no hard stop — MAE is -8%, a stop would sit inside it
    "max_position_hours": 168,         # 7d; the labels were measured over 24-48h
    "min_signal_confidence": 0.0,
    "min_volume_ratio": 0.0,
    "signal_cooldown_minutes": 360,
    "symbols": _ALL9,
}

# permissive 4h trend gate — the search found NO 4h trend condition worth
# gating on, so this only excludes outright collapse
_LOOSE_4H = [{"type": "price_extended_below_ema",
              "params": {"ema": 50, "min_gap_pct": 40.0, "max_gap_pct": -45.0, "hard_stop": True}}]
_PROD_LIKE_4H = [{"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": 0, "hard_stop": True}}]

_ATR_HIGH  = {"type": "atr_regime", "params": {"min_pct": 2.56, "max_pct": None, "period": 14, "hard_stop": True}}
_DFH_20    = {"type": "distance_from_high", "params": {"lookback_bars": 168, "min_pct_below": 20.7, "max_pct_below": 60.0, "hard_stop": True}}
_BELOW_VWAP= {"type": "price_below_vwap", "params": {"min_gap_pct": -2.365, "max_gap_pct": -30.0, "hard_stop": True}}
_EMA50_FALL= {"type": "ema_slope", "params": {"ema": 50, "direction": "falling", "min_slope_pct": 0.563,
                                              "lookback_bars": 3, "hard_stop": True}}
_DFH_2D    = {"type": "distance_from_high", "params": {"lookback_bars": 48, "min_pct_below": 11.55, "max_pct_below": 60.0, "hard_stop": True}}
_ATR_4H    = {"type": "atr_regime", "params": {"min_pct": 5.08, "max_pct": None, "period": 14, "hard_stop": True}}

def _v(name, entry, trend=None, **kw):
    return {**_BASE, "display_name": name,
            "trend_indicators": trend if trend is not None else _LOOSE_4H,
            "min_indicators_required": 1,
            "entry_indicators": entry, "min_entry_indicators_required": len(entry), **kw}

H1_DISCOVERY_VARIANTS = {
    # ---- the episode-level winner, and ablations of each leg ---------------
    "n_vol_full":   _v("n_vol_full",   [_ATR_HIGH, _DFH_20, _BELOW_VWAP, _EMA50_FALL]),
    "n_vol_noVwap": _v("n_vol_noVwap", [_ATR_HIGH, _DFH_20, _EMA50_FALL]),
    "n_vol_noSlope":_v("n_vol_noSlope",[_ATR_HIGH, _DFH_20, _BELOW_VWAP]),
    "n_vol_noAtr":  _v("n_vol_noAtr",  [_DFH_20, _BELOW_VWAP, _EMA50_FALL]),
    "n_vol_dfhOnly":_v("n_vol_dfhOnly",[_ATR_HIGH, _DFH_20]),

    # ---- second-ranked family ---------------------------------------------
    "n_dip_full":   _v("n_dip_full",   [_DFH_2D, _ATR_4H]),

    # ---- does the prod-style daily/4h trend gate help or hurt here? --------
    "n_vol_prodgate": _v("n_vol_prodgate", [_ATR_HIGH, _DFH_20, _BELOW_VWAP, _EMA50_FALL], trend=_PROD_LIKE_4H),

    # ---- geometry plateau test on the winner (arm, at fixed trail) ---------
    "n_vol_arm3.0": _v("n_vol_arm3.0", [_ATR_HIGH,_DFH_20,_BELOW_VWAP,_EMA50_FALL], arm_trailing_stop_pct=3.0),
    "n_vol_arm6.0": _v("n_vol_arm6.0", [_ATR_HIGH,_DFH_20,_BELOW_VWAP,_EMA50_FALL], arm_trailing_stop_pct=6.0),
    "n_vol_arm8.0": _v("n_vol_arm8.0", [_ATR_HIGH,_DFH_20,_BELOW_VWAP,_EMA50_FALL], arm_trailing_stop_pct=8.0),
    "n_vol_trail0.8": _v("n_vol_trail0.8", [_ATR_HIGH,_DFH_20,_BELOW_VWAP,_EMA50_FALL], trailing_stop_pct=0.8),
    "n_vol_trail2.5": _v("n_vol_trail2.5", [_ATR_HIGH,_DFH_20,_BELOW_VWAP,_EMA50_FALL], trailing_stop_pct=2.5),
    "n_vol_notrail":  _v("n_vol_notrail",  [_ATR_HIGH,_DFH_20,_BELOW_VWAP,_EMA50_FALL], use_trailing_stop=False),

    # ---- the momentum side, kept so its failure is on the record ----------
    "n_mom":  _v("n_mom", [
        {"type": "rsi_threshold", "params": {"period": 14, "min_value": 70, "hard_stop": True}},
        {"type": "ema_slope", "params": {"ema": 20, "direction": "rising", "min_slope_pct": 1.2,
                                         "lookback_bars": 3, "hard_stop": True}},
    ]),
}


# =============================================================================
# PHASE C RESULT + PHASE D WALK-FORWARD — DO NOT DEPLOY. (2026-08-19)
#
# PHASE C looked excellent. 2yr / 9 symbols / tick fills:
#
#   variant           n    WR     avg     total    PF   tail   worst  qtrs syms
#   n_vol_notrail   103  85.4%  +4.07%  +419.0%  6.29   3.9%  -17.62  7/8  9/9
#   n_vol_arm8.0    106  87.7%  +3.77%  +399.2%  6.13   3.8%  -17.62  7/8  9/9
#   n_dip_full       64  85.9%  +3.06%  +196.1%  7.91   3.1%  -12.98  5/6  8/8
#   n_vol_full      113  88.5%  +2.80%  +315.9%  5.15   3.5%  -17.62  7/8  9/9
#   n_vol_noVwap    155  87.7%  +2.79%  +432.4%  5.29   4.5%  -17.62  8/8  9/9
#   (live dip_v5 for scale: n=70 +2.13% PF 5.63; live dip_v7: n=155 +1.65% PF 2.27)
#
#   Leg ablations behaved sensibly — the ATR and distance-from-high legs are
#   load-bearing (dropping ATR takes PF 5.15 -> 2.71 and symbols 9/9 -> 7/9),
#   while the VWAP leg is nearly free to drop (+2.79% on 37% MORE trades, 8/8
#   quarters). Trail width was flat (0.8/1.5/2.5 -> +2.87/+2.80/+2.72) and the
#   arm was monotone to the boundary (3.0 -> 8.0 -> no-trail: +1.91 -> +3.77 ->
#   +4.07). That monotone-to-the-edge shape is the same one that failed
#   out-of-sample in the dip_v5 work, and it was the first warning sign.
#
# PHASE D killed it. All nine symbols were used in the screen, so no held-out
# cross-section remained — the only honest test left was to re-run the ENTIRE
# discovery (screen + greedy combine) on one half and evaluate its pick on the
# other. Both directions:
#
#   H1 -> H2   rule found: btc_d_vs50<=-8.83 AND adx<=21.71 AND
#                          h4_ema20_slope3>=-0.428 AND h4_ema20_vs_50<=-3.702
#              TRAIN n=372 ep=22 radj +4.890 P(up) 83.1%
#              TEST  n=801 ep=45 radj -0.187 P(up) 40.6%   <-- FAILS
#
#   H2 -> H1   rule found: btc_d_vs50<=-15.83 AND h4_ema20_slope3<=-1.165
#              TRAIN n=788 ep=37 radj +1.234 P(up) 71.6%
#              TEST  NO SIGNALS AT ALL — the rule does not generalise enough
#                    to fire once in the other half
#
# So the SEARCH PROCEDURE ITSELF does not generalise at this sample size. Given
# different data it picks entirely different rules, and those rules are
# worthless (or inert) out of sample. That is a property of the method, not of
# one unlucky candidate — which means the Phase C numbers cannot be trusted
# either, however good they look. n_vol_full was selected using both halves, so
# its healthy second-half performance is exactly what it was selected for.
#
# Telling detail: BOTH halves' searches latched onto btc_d_vs50 (BTC below its
# own daily EMA50) as the first or strongest rule. That is the same feature
# whose dedicated strategy-level test earlier today rejected it in every form —
# overlay both directions, and as a replacement gate. The screen keeps finding
# it attractive and it keeps failing. Consistent, and a useful calibration on
# how much bar-level attractiveness is worth.
#
# WHAT IS AND IS NOT ESTABLISHED
#   NOT established: that n_vol_full has an edge. Do not deploy it.
#   IS established: (a) the Phase A/B machinery is correct and reusable, and
#   the matrix build is the expensive part (done once, screening is seconds);
#   (b) episode weighting and walk-forward both catch things that half-splits,
#   symbol-splits and plateau tests do not — MOM2 passed both halves and 7/9
#   symbols and was still noise;
#   (c) at 1h/4h the surviving signal shape is AGAIN deep-dip mean reversion,
#   the third independent time this project has landed there, and the momentum
#   side produced nothing.
#
# IF THIS IS PICKED BACK UP: n_vol_full is a 1h-entry cousin of the live 4h dip
# profiles, so its plausibility comes from that family's independent
# tick-validated support, NOT from this search. The only way to establish it is
# forward/shadow trading on unseen data. Check its overlap with dip_v7 first —
# if they take the same trades it adds nothing but correlated exposure.
#
# n_mom is BROKEN, not a result: 752 trades, 96% exiting at exactly 0.00% via
# trend_invalidation on the entry bar. The rsi_threshold trend gate and the
# exit set contradict each other so positions close instantly. Fix or delete
# before reading anything into the momentum side from it.
# =============================================================================
