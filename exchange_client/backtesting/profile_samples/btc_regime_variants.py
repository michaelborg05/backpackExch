# =============================================================================
# BTC-REGIME GATE — Phase 2 validation (2026-08-19)
#
# THE CLAIM UNDER TEST. A bar-outcome screen over 3,400 qualifying dip bars
# (2yr, 7 symbols, outcome = trail 3.5/0.6 with a 30d cap, 1m path fills) found
# that requiring BTC to sit at least 3.78% BELOW its own daily EMA50 moved the
# mean from -0.58% to +1.44%/trade and cut the <-5% tail from 17.2% to 10.9%.
# 7/8 quarters positive, 6/7 symbols, 15 distinct episodes of which 11 positive
# with the largest only 15% of the sample, episode-level bootstrap p=0.041.
#
# It also independently replicates, from the opposite direction, an existing
# project finding: a BTC cross-gate requiring BTC STRENGTH was tested earlier
# and rejected because "dropped alt trades were BETTER than kept — alt dips
# during BTC weakness bounce harder".
#
# WHY THIS IS EXPECTED TO FAIL. The per-symbol analogue of exactly this idea
# (price below its OWN daily EMA50) scored +0.61% at bar level and then LOST at
# strategy level in all three entry families — the live above-EMA50 gate beat
# every inverse variant. Bar screens score every qualifying bar independently,
# with no position limits, no cooldowns and no fees; these profiles fire 2-8x
# per symbol-year with all of those active. Treat a good result here with
# suspicion and a bad one as conclusive.
#
# PRE-REGISTERED PASS BAR (fixed before the run so it cannot be moved after):
#   1. Must beat the live config on PROFIT FACTOR *and* WORST TRADE. Total
#      return alone does not count — every loosening tried this session bought
#      total return with tail risk, and that trade is already known to be bad.
#   2. Must hold in BOTH time-halves.
#   3. Must hold across the SYMBOL cross-section (>= as many positive symbols).
#   Anything less and the gate is rejected. Rule 3 exists because a champion
#   that passed 1 and 2 (arm 7) still died on held-out symbols.
#
# Nine symbols, always — the four-symbol fits in this project do not survive.
#
# Run:
#   DATABASE_URL=$DATABASE_URL_LOCAL python backtesting/run_profile_variants_backtest.py \
#       --set btc_regime --days 0-730 --price-source ticks --price-mode close
# =============================================================================

_ALL9 = ["SOL_USDC","ZEC_USDC","BTC_USDC","ETH_USDC","BNB_USDC","XRP_USDC","DOGE_USDC","SEI_USDC","SUI_USDC"]

_BASE = {
    "strategy_type": "mean_reversion",
    "market_type": "SPOT",
    "trend_timeframe": "1D",
    "entry_timeframe": "240",
    "exit_timeframe": "240",
    "use_trend_filter": True,
    "trend_indicators": [
        {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": 0, "hard_stop": True}},
    ],
    "min_indicators_required": 1,
    "use_entry_filter": True,
    "min_entry_indicators_required": 2,
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_position_age_for_trend_check": 0,
    "exit_indicators": [
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
        {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
    ],
    "min_exit_indicators_required": 1,
    "use_trailing_stop": True,
    "arm_trailing_stop_pct": 3.5,
    "trailing_stop_pct": 0.6,
    "take_profit_pct": 99.0,
    "stop_loss_pct": 99.0,
    "max_position_hours": 720,
    "min_signal_confidence": 0.0,
    "min_volume_ratio": 0.0,
    "signal_cooldown_minutes": 1300,
    "symbols": _ALL9,
}

_V5_ENTRY = [
    {"type": "rsi_reversal_momentum", "params": {
        "lookback_candles": 4, "oversold_threshold": 35, "current_min": 35,
        "min_jump": 6.0, "require_sustained": False, "sustained_rise_mode": "net",
        "hard_stop": True}},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
]
_V7_ENTRY = [
    {"type": "distance_from_high", "params": {"lookback_bars": 18, "min_pct_below": 12.0, "max_pct_below": 30.0, "hard_stop": True}},
    {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
]
_V7_EXIT = [
    {"type": "rsi_overbought", "params": {"side": "long", "min_value": 59, "max_value": 30, "lookback_candles": None}},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
]

def _btc(max_gap, min_gap=-25.0):
    """BTC must sit between min_gap and max_gap % of its own daily EMA50.
    Both negative = 'BTC is this far BELOW its EMA50'."""
    return {"type": "reference_symbol_vs_ema", "params": {
        "reference_symbol": "BTC_USDC", "timeframe": "1D", "ema": 50,
        "min_gap_pct": min_gap, "max_gap_pct": max_gap, "hard_stop": True}}

def _v(name, entry, exit_inds=None, btc=None):
    v = {**_BASE, "display_name": name,
         "entry_indicators": entry + ([btc] if btc else []),
         "min_entry_indicators_required": len(entry) + (1 if btc else 0)}
    if exit_inds:
        v["exit_indicators"] = exit_inds
    return v

BTC_REGIME_VARIANTS = {
    # ── v5 reversal entry ────────────────────────────────────────────────────
    "b_v5_live":        _v("b_v5_live",        _V5_ENTRY),                        # control
    "b_v5_btc3.78":     _v("b_v5_btc3.78",     _V5_ENTRY, btc=_btc(-3.78)),       # the screen's threshold
    "b_v5_btc2":        _v("b_v5_btc2",        _V5_ENTRY, btc=_btc(-2.0)),        # looser
    "b_v5_btc6":        _v("b_v5_btc6",        _V5_ENTRY, btc=_btc(-6.0)),        # stricter
    # inverse of the inverse — require BTC STRENGTH. The earlier project test
    # rejected this; included so both directions are measured in one run.
    "b_v5_btcSTRONG":   _v("b_v5_btcSTRONG",   _V5_ENTRY, btc=_btc(None, 0.0)),

    # ── v7 deep-dip entry ────────────────────────────────────────────────────
    "b_v7_live":        _v("b_v7_live",        _V7_ENTRY, _V7_EXIT),              # control
    "b_v7_btc3.78":     _v("b_v7_btc3.78",     _V7_ENTRY, _V7_EXIT, btc=_btc(-3.78)),
    "b_v7_btc2":        _v("b_v7_btc2",        _V7_ENTRY, _V7_EXIT, btc=_btc(-2.0)),
    "b_v7_btc6":        _v("b_v7_btc6",        _V7_ENTRY, _V7_EXIT, btc=_btc(-6.0)),
    "b_v7_btcSTRONG":   _v("b_v7_btcSTRONG",   _V7_ENTRY, _V7_EXIT, btc=_btc(None, 0.0)),
}


# =============================================================================
# PHASE 2 RESULT (2026-08-19, 2yr / 9 symbols / 1m-path tick fills)
# VERDICT: REJECTED IN BOTH DIRECTIONS. Do not deploy.
#
# The screen's hypothesis (require BTC WEAKNESS) does not survive contact with
# a portfolio backtest at all:
#
#   v5 entry            n     WR     avg     total     PF    worst
#     live (control)   70  87.1%  +2.13%  +148.8%   5.63   -8.24%
#     BTC <= -2%        6  83.3%  +0.81%    +4.9%   1.59   -8.24%
#     BTC <= -3.78%     3  66.7%  -0.75%    -2.3%   0.73   -8.24%
#     BTC <= -6%        1     —       —        —       —        —
#
#   v7 entry            n     WR     avg     total     PF    worst
#     live (control)  155  83.9%  +1.65%  +255.9%   2.27  -24.73%
#     BTC <= -2%       22  81.8%  +0.37%    +8.2%   1.14  -23.67%
#     BTC <= -3.78%    18  83.3%  +0.88%   +15.9%   1.38  -23.67%
#     BTC <= -6%       11  81.8%  -0.48%    -5.3%   0.86  -23.67%
#
# The +1.44%/trade the bar screen promised is nowhere. Requiring BTC weakness
# strangles the profiles (70 -> 3-6 trades, 155 -> 11-22) and quality collapses
# with it. This is the SECOND time a bar-outcome screen from that dataset has
# failed to transfer — the per-symbol version failed the same way. The screen
# is not a weak predictor of strategy-level performance; it is not a predictor.
#
# ---------------------------------------------------------------------------
# THE OPPOSITE DIRECTION "PASSED" THE PRE-REGISTERED BAR AND IS STILL WRONG —
# WHICH MEANS THE BAR WAS FLAWED.
#
#   b_v5_btcSTRONG (BTC ABOVE its daily EMA50): n=60 avg +2.17% PF 6.46
#     tail 1.67% worst -6.50%, both halves positive, 8/9 symbols.
#     vs control:      n=70 avg +2.13% PF 5.63 tail 2.86% worst -8.24%.
#   By the stated criteria (PF up, worst up, both halves, symbols held) that is
#   a PASS. It is not. Look at WHICH TRADES IT REMOVES:
#
#     10 removed, of which NINE ARE WINNERS. Removed set averages +1.83%
#     (+18.3pp of return given up). The single loser removed is the -8.24% BNB
#     trade — and that one trade is the entire source of BOTH the PF gain and
#     the worst-trade gain. Ex that trade the removed set averages +2.95%.
#
#   Same story on v7, larger: 39 removed, 33 winners, removed set averages
#   +1.47%, giving up 57.2pp of return, and the worst trade does not improve
#   at all (-24.73% either way).
#
# So the gate does not identify bad trades. It removes a broadly profitable
# slice that happens to contain one big loser.
#
# THE METHOD LESSON: "PF and worst-trade must both improve" is satisfiable by
# ANY filter that deletes the single worst trade, no matter how much good it
# deletes alongside. That criterion is gameable and should not be used alone.
# The test that actually discriminates is:
#     DO THE REMOVED TRADES HAVE WORSE EXPECTANCY THAN THE KEPT ONES?
#   v5: removed +1.83% vs kept +2.17%.   v7: removed +1.47% vs kept +1.71%.
# Neither is a meaningful separation — both subsets are strongly profitable.
# Add this comparison to the pass bar for every future filter.
#
# WHAT SURVIVES: the `reference_symbol_vs_ema` indicator itself is built,
# unit-tested (6 cases incl. fail-open) and live in both engines, along with
# the three symbol guards in the replay loop that cross-symbol data requires.
# That infrastructure is correct and reusable. The BTC gate built on it is not
# worth deploying in either direction.
# =============================================================================


# =============================================================================
# ROUND 2 — REPLACEMENT, not overlay. (2026-08-19)
#
# Phase 2 only ever tested the BTC gate BOLTED ON TOP of the per-symbol daily
# EMA50 gate. The untested design is REPLACEMENT: drop the symbol's own gate
# and use BTC's instead. That is a real question, not a re-run, because the two
# gates agree only 76.4% of the time (Jaccard 0.46-0.63 per symbol; ZEC as low
# as 62.3%) — roughly a quarter of days disagree, so they are substantially
# different filters.
#
# The question it answers: does the daily gate earn its keep because "THIS
# SYMBOL's trend is up", or because "THE MARKET is up"? Round 1 proved the gate
# is worth having (prod gate beat no-gate decisively); nothing has established
# WHICH of those two things is doing the work.
#
# Also included: a faster BTC read (4h instead of 1D) and a shorter EMA (20),
# since if any market-wide signal exists it may need to be more responsive than
# a daily EMA50 that flips only ~53% of days.
#
# CORRECTED PASS BAR — the Phase 2 bar was gameable. "PF and worst-trade both
# improve" is satisfied by ANY filter that deletes the single worst trade, no
# matter how much good it deletes with it (b_v5_btcSTRONG removed 9 winners per
# loser and still "passed"). The added, decisive test is:
#     THE REMOVED TRADES MUST HAVE MEANINGFULLY WORSE EXPECTANCY THAN THE KEPT
#     ONES. If removed-avg is close to kept-avg, the filter is not selecting.
# =============================================================================

def _btc_gate(tf="1D", ema=50, min_gap=0.0, max_gap=None):
    return [{"type": "reference_symbol_vs_ema", "params": {
        "reference_symbol": "BTC_USDC", "timeframe": tf, "ema": ema,
        "min_gap_pct": min_gap, "max_gap_pct": max_gap, "hard_stop": True}}]

def _r(name, entry, exit_inds=None, trend=None, use_trend=True):
    v = {**_BASE, "display_name": name,
         "entry_indicators": entry,
         "min_entry_indicators_required": len(entry),
         "use_trend_filter": use_trend,
         "trend_indicators": trend if trend is not None else [],
         "min_indicators_required": len(trend) if trend else 0}
    if exit_inds:
        v["exit_indicators"] = exit_inds
    return v

_SYMBOL_GATE = [{"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": 0, "hard_stop": True}}]

BTC_REGIME_VARIANTS.update({
    # ---- v5 entry -----------------------------------------------------------
    "r_v5_symgate":     _r("r_v5_symgate",   _V5_ENTRY, trend=_SYMBOL_GATE),          # = LIVE control
    "r_v5_nogate":      _r("r_v5_nogate",    _V5_ENTRY, trend=None, use_trend=False), # floor
    "r_v5_btconly_1D":  _r("r_v5_btconly_1D", _V5_ENTRY, trend=_btc_gate()),          # BTC replaces symbol
    "r_v5_btconly_4h":  _r("r_v5_btconly_4h", _V5_ENTRY, trend=_btc_gate(tf="240")),
    "r_v5_btconly_ema20": _r("r_v5_btconly_ema20", _V5_ENTRY, trend=_btc_gate(ema=20)),
    "r_v5_both":        _r("r_v5_both",      _V5_ENTRY, trend=_SYMBOL_GATE + _btc_gate()),  # AND

    # ---- v7 entry -----------------------------------------------------------
    "r_v7_symgate":     _r("r_v7_symgate",   _V7_ENTRY, _V7_EXIT, trend=_SYMBOL_GATE),
    "r_v7_nogate":      _r("r_v7_nogate",    _V7_ENTRY, _V7_EXIT, trend=None, use_trend=False),
    "r_v7_btconly_1D":  _r("r_v7_btconly_1D", _V7_ENTRY, _V7_EXIT, trend=_btc_gate()),
    "r_v7_btconly_4h":  _r("r_v7_btconly_4h", _V7_ENTRY, _V7_EXIT, trend=_btc_gate(tf="240")),
    "r_v7_btconly_ema20": _r("r_v7_btconly_ema20", _V7_ENTRY, _V7_EXIT, trend=_btc_gate(ema=20)),
    "r_v7_both":        _r("r_v7_both",      _V7_ENTRY, _V7_EXIT, trend=_SYMBOL_GATE + _btc_gate()),
})


# =============================================================================
# ROUND 3 — IS THE DAILY GATE ASKING THE RIGHT QUESTION? (2026-08-19)
#
# Every dip profile gates on a LEVEL: "price >= daily EMA50". That is a single
# static test, and it throws away two things that are arguably more informative:
#
#   (a) DIRECTION. A daily EMA50 that is RISING while price sits just under it
#       is a different market from one that is falling with price just over it.
#       The level test cannot tell them apart, and it prefers the second.
#   (b) CONVERGENCE. Price 6% below a daily EMA50 and closing fast is the
#       classic recovery setup; price 6% below and still falling is a knife.
#       The level test treats both as identical and blocks both.
#
# No new indicator is needed for any of this. ema_slope already exists in both
# engines (1-bar lookback on the given timeframe), and trend_indicator_groups
# already supports OR-composition. "Below EMA50 but recovering" is expressible
# exactly as: price < daily EMA50 AND price > daily EMA20 — the short average
# has been reclaimed, the long one has not. That is the shape of a gap closing
# from below, without needing a gap-velocity indicator.
#
# The variant that matters most is g_*_recovering_only: it takes ONLY the bars
# the live gate rejects, so it answers the question directly — is everything
# below the daily EMA50 genuinely untradeable, or is the profitable subset
# there just unreachable with a level test?
#
# Pass bar as corrected in round 2, including the removed-vs-kept expectancy
# test. For the OR variants the relevant comparison is the MARGINAL trades
# (those the live gate would not have taken) standing on their own — a
# superset that merely inherits the control's trades proves nothing.
# =============================================================================

_D_EMA50_LEVEL   = {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": 0, "hard_stop": True}}
_D_EMA50_RISING  = {"type": "ema_slope", "params": {"ema": 50, "direction": "rising", "min_slope_pct": 0.01, "hard_stop": True}}
_D_EMA50_NOTFALL = {"type": "ema_slope", "params": {"ema": 50, "direction": "not_falling", "min_slope_pct": 0.01, "hard_stop": True}}
# "below the 50 but above the 20" = gap closing from underneath
_D_BELOW50 = {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -0.001, "max_gap_pct": -40.0, "hard_stop": True}}
_D_ABOVE20 = {"type": "price_vs_ema", "params": {"ema": 20, "min_gap_pct": 0, "hard_stop": True}}

def _g(name, entry, exit_inds=None, trend=None, groups=None):
    v = {**_BASE, "display_name": name,
         "entry_indicators": entry,
         "min_entry_indicators_required": len(entry),
         "use_trend_filter": True,
         "trend_indicators": trend,
         "min_indicators_required": 1 if groups else len(trend)}
    if groups:
        v["trend_indicator_groups"] = groups
    if exit_inds:
        v["exit_indicators"] = exit_inds
    return v

def _level_or_recovering():
    """group A: price >= daily EMA50.  group B: below the 50 but above the 20.
    Either group passing lets the trade through."""
    return ([{**_D_EMA50_LEVEL, "indicator_group": "above50", "params": {**_D_EMA50_LEVEL["params"], "hard_stop": False}},
             {**_D_BELOW50,     "indicator_group": "recovering", "params": {**_D_BELOW50["params"], "hard_stop": False}},
             {**_D_ABOVE20,     "indicator_group": "recovering", "params": {**_D_ABOVE20["params"], "hard_stop": False}}],
            {"above50":    {"require_all": True, "hard_stop": False},
             "recovering": {"require_all": True, "hard_stop": False}})

_or_inds, _or_groups = _level_or_recovering()

for _fam, _entry, _exit in (("v5", _V5_ENTRY, None), ("v7", _V7_ENTRY, _V7_EXIT)):
    BTC_REGIME_VARIANTS.update({
        f"g_{_fam}_level":            _g(f"g_{_fam}_level",  _entry, _exit, trend=[_D_EMA50_LEVEL]),
        f"g_{_fam}_slope_rising":     _g(f"g_{_fam}_slope_rising",  _entry, _exit, trend=[_D_EMA50_RISING]),
        f"g_{_fam}_slope_notfalling": _g(f"g_{_fam}_slope_notfalling", _entry, _exit, trend=[_D_EMA50_NOTFALL]),
        f"g_{_fam}_level_and_slope":  _g(f"g_{_fam}_level_and_slope", _entry, _exit, trend=[_D_EMA50_LEVEL, _D_EMA50_NOTFALL]),
        f"g_{_fam}_recovering_only":  _g(f"g_{_fam}_recovering_only", _entry, _exit, trend=[_D_BELOW50, _D_ABOVE20]),
        f"g_{_fam}_level_or_recov":   _g(f"g_{_fam}_level_or_recov",  _entry, _exit, trend=_or_inds, groups=_or_groups),
    })


# =============================================================================
# ROUND 2 RESULT — THE GATE'S VALUE IS SYMBOL-SPECIFIC, NOT MARKET-WIDE.
# (2yr / 9 symbols / tick fills)
#
#   v5 entry, only the trend gate differs      n     avg      total     PF    worst
#     symbol >= its own daily EMA50 (LIVE)    70   +2.13%  +148.8%   5.63   -8.24%
#     BTC    >= its own daily EMA50          124   +1.66%  +205.8%   3.13  -15.48%
#     BTC 4h >= its own EMA50                 40   -0.31%   -12.4%   0.86  -15.48%
#     BTC    >= its own daily EMA20           88   +1.26%  +111.2%   2.14  -15.48%
#     no gate at all                         359   +0.51%  +184.8%   1.32  -38.17%
#
#   v7 entry                                   n     avg      total     PF    worst
#     symbol gate (LIVE)                     155   +1.65%  +255.9%   2.27  -24.73%
#     BTC daily                              160   +1.30%  +208.1%   1.85  -37.68%
#     BTC 4h                                  97   +0.87%   +84.3%   1.47  -24.73%
#     BTC daily EMA20                        134   +0.57%   +75.9%   1.27  -37.68%
#     no gate                                358   +1.06%  +381.2%   1.62  -37.68%
#
# Round 1 established the daily gate is worth having but could not say WHY,
# because "this symbol's trend is up" and "the market is up" were perfectly
# confounded. Swapping in BTC's own EMA50 separates them, and the answer is
# unambiguous: the symbol's own trend is doing the work. BTC's regime is a
# strictly worse proxy at every timeframe and EMA length tested, and it is
# NOT merely redundant — the two gates agree only 76.4% of the time, so BTC
# genuinely carries different information, it is just worse information.
#
# Nuance worth keeping: the bars BTC lets through that the symbol gate blocks
# are not junk (+1.18%/trade on v5, 64 of them). They are simply worse than the
# bars the symbol gate selects (+2.13%). So this is a ranking result, not a
# "BTC regime is meaningless" result.
#
# Also note r_v7_nogate: +381% total return, the highest of anything tested,
# on 358 trades at +1.06% with PF 1.62 and a -37.68% worst trade. The same
# frequency-for-quality trade every loosening in this project makes. If raw
# deployed return were the objective rather than risk-adjusted return, the
# ungated v7 would be the pick — worth knowing that is the shape of the choice.
#
# THE BTC-REFERENCE AVENUE IS NOW CLOSED in all three forms tested: as an
# overlay requiring weakness (collapses), as an overlay requiring strength
# (removes 9 winners per loser), and as a replacement (strictly worse).
# =============================================================================


# =============================================================================
# ROUND 3 RESULT — LEVEL vs SLOPE vs "RECOVERING FROM BELOW"
# (2yr / 9 symbols / tick fills)
#
# (a) SLOPE ADDS NOTHING OVER LEVEL — they are near-interchangeable.
#
#   v5 entry                  n     avg      PF   syms      v7 entry     n     avg      PF
#     level (LIVE)           70  +2.13%   5.63    8/9        level     155  +1.65%   2.27
#     level AND not_falling  70  +2.13%   5.63    8/9        AND       155  +1.65%   2.27
#     slope rising only      69  +2.09%   5.48    8/9        rising    153  +1.63%   2.24
#     slope not_falling only 74  +2.10%   5.83    9/9        notfall   157  +1.57%   2.17
#
#   "level AND slope" is BYTE-IDENTICAL to level alone on both entries (same n,
#   same avg, same PF, same worst). That is the finding: when price is above
#   its daily EMA50, that EMA50 is essentially never falling, so the direction
#   test is already implied by the level test and contributes zero information.
#   Using slope INSTEAD of level lands within noise of it either way.
#
#   The only cell that improved anything: v5 slope not_falling gives 9/9
#   symbols positive vs 8/9 and PF 5.83 vs 5.63, on 4 extra trades averaging
#   +1.62%. That is well inside noise at n=74 vs 70 — not worth acting on.
#
# (b) "BELOW THE EMA50 BUT RECOVERING" IS NEGATIVE — the interesting one.
#   Operationalised as: price < daily EMA50 AND price > daily EMA20 (the short
#   average reclaimed, the long one not) — i.e. the gap closing from beneath.
#
#     g_v7_recovering_only   n=20  WR 55.0%  avg -1.21%  PF 0.64  tail 30.0%
#                            2/6 quarters, H1 -0.31%, H2 -3.32%
#     g_v5_recovering_only   n= 2  — far too rare on the reversal entry to judge
#
#   And the OR-composition confirms it from the other side: g_v7_level_or_recov
#   ADDS 16 trades over the live gate at -1.14% average. The bars the recovery
#   condition admits are exactly the ones that lose.
#
#   So the answer to "if it is below the EMA50 but closing fast, is that not
#   also a signal?" is NO on this evidence. Win rate collapses from 84% to 55%
#   and the catastrophic-tail rate triples from 9% to 30%. Reclaiming the daily
#   EMA20 while still under the EMA50 is not a recovery signal for this
#   strategy — it is the middle of a downtrend, which is the same conclusion
#   the min_low_age_bars work reached from a different direction (a low that
#   has held for days is not evidence it will keep holding).
#
#   CAVEAT: n=20, and "above the daily EMA20" is one specific proxy for
#   "closing fast". A true gap-VELOCITY measure (gap narrowing by X% over N
#   bars) might separate differently and is not tested. But the direction is
#   consistent with every other loosening tried in this project.
#
# NET: the level gate at 0 is the right formulation. Direction adds nothing
# because it is already implied; convergence-from-below is actively harmful.
# =============================================================================
