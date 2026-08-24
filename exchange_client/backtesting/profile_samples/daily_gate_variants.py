# =============================================================================
# DAILY-GATE REFORMULATION — is there a LIGHTER gate than "price >= daily
# EMA50" that removes the bad trades and keeps the good ones? (2026-08-19)
#
# METHOD. Take the UNGATED v7 profile's 352 real portfolio trades (not
# independently scored bars — these are actual trades with position and
# cooldown logic applied) and ask which daily-timeframe features separate the
# 40 disasters (< -5%) from the rest. Every feature is weak on its own — the
# best AUC is 0.596, where 0.5 is nothing — and the top six all say the same
# thing: the disasters happen when the daily trend is already rolling over
# (EMA20 under EMA50, both slopes negative, 14-day return negative).
#
# Applying each as a filter to that trade set:
#
#   gate                              n   (%)   WR     avg     PF   tail  syms
#     no gate                       352 (100%) 80.1% +1.19%  1.73  11.4%  9/9
#     price > daily EMA50 (LIVE)    127 ( 36%) 86.6% +2.01%  2.88   7.9%  8/9
#     daily EMA20 slope(5d) > 0     175 ( 50%) 86.3% +2.06%  3.11   6.3%  9/9  <--
#     daily RSI > 50                168 ( 48%) 85.1% +1.87%  2.66   7.1%  9/9
#     daily EMA20 > EMA50           181 ( 51%) 84.5% +1.65%  2.26   7.7%  9/9
#     daily 14d return > 0          180 ( 51%) 83.3% +1.66%  2.31   8.9%  9/9
#     daily EMA50 slope(5d) > 0     182 ( 52%) 84.1% +1.58%  2.21   7.7%  9/9
#     daily RSI > 45                229 ( 65%) 80.8% +1.30%  1.85  10.5%  9/9
#
# The daily EMA20 5-day slope beats the live level gate on average PnL, profit
# factor, tail rate and symbol spread WHILE KEEPING 38% MORE TRADES. That is
# the first thing all session to look like a genuine improvement rather than a
# frequency-for-quality trade.
#
# THE LOOKBACK IS THE WHOLE EFFECT, and it degrades monotonically:
#     5d: avg +2.06%  PF 3.11  tail 6.3%
#     3d: avg +1.81%  PF 2.61  tail 8.7%
#     2d: avg +1.69%  PF 2.39  tail 8.6%
#     1d: avg +1.45%  PF 2.00  tail 9.7%   <- all the engine supported until now
# A clean monotone relationship is a good sign it is real smoothing rather than
# noise, but it meant the promising version was not testable: ema_slope only
# ever compared adjacent bars. `lookback_bars` has now been added to
# _get_ema_slope in BOTH engines (default 1, so nothing existing changes) and
# the _ema_history retention raised 3 -> 12 (prod) and 5 -> 12 (replay).
#
# THREE REASONS TO DISTRUST THE TABLE ABOVE, which is why these variants exist:
#   1. It is POST-HOC FILTERING of one profile's trade list, not a backtest.
#      Gating changes which trades occur at all (position occupancy, cooldowns),
#      so the real run will not reproduce these numbers. Note the live gate
#      shows n=127 here vs n=155 in its own backtest — same gate, different
#      trades — which is exactly the size of the discrepancy to expect.
#   2. NONE of the lighter gates removes the -37.68% worst trade that the live
#      gate removes. Every one of them keeps it. That is the same single-trade
#      pattern that made arm 4.0 look safe and the BTC-strength gate look good.
#   3. ~25 gate/threshold combinations have now been screened against this one
#      dataset. Something had to look good.
#
# PASS BAR (as corrected through the session): beat the live gate on PF AND
# tail, hold in both halves, hold across symbols, AND the removed trades must
# have meaningfully worse expectancy than the kept ones.
# =============================================================================

_ALL9 = ["SOL_USDC","ZEC_USDC","BTC_USDC","ETH_USDC","BNB_USDC","XRP_USDC","DOGE_USDC","SEI_USDC","SUI_USDC"]

_BASE = {
    "strategy_type": "mean_reversion", "market_type": "SPOT",
    "trend_timeframe": "1D", "entry_timeframe": "240", "exit_timeframe": "240",
    "use_trend_filter": True, "use_entry_filter": True,
    "use_trend_invalidation_exit": True, "trend_invalidation_indicators": "exit",
    "min_position_age_for_trend_check": 0,
    "exit_indicators": [
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
        {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
    ],
    "min_exit_indicators_required": 1,
    "use_trailing_stop": True, "arm_trailing_stop_pct": 3.5, "trailing_stop_pct": 0.6,
    "take_profit_pct": 99.0, "stop_loss_pct": 99.0, "max_position_hours": 720,
    "min_signal_confidence": 0.0, "min_volume_ratio": 0.0, "signal_cooldown_minutes": 1300,
    "symbols": _ALL9,
}
_V5_ENTRY = [
    {"type": "rsi_reversal_momentum", "params": {
        "lookback_candles": 4, "oversold_threshold": 35, "current_min": 35,
        "min_jump": 6.0, "require_sustained": False, "sustained_rise_mode": "net", "hard_stop": True}},
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

_LEVEL = {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": 0, "hard_stop": True}}
def _slope(ema=20, lb=5, direction="rising", hard=True):
    return {"type": "ema_slope", "params": {"ema": ema, "direction": direction,
            "min_slope_pct": 0.0, "lookback_bars": lb, "hard_stop": hard}}
def _rsi(minv=50):
    return {"type": "rsi_threshold", "params": {"period": 14, "min_value": minv, "hard_stop": True}}

def _v(name, entry, trend, exit_inds=None, groups=None):
    v = {**_BASE, "display_name": name, "entry_indicators": entry,
         "min_entry_indicators_required": len(entry),
         "trend_indicators": trend,
         "min_indicators_required": 1 if groups else len(trend)}
    if groups: v["trend_indicator_groups"] = groups
    if exit_inds: v["exit_indicators"] = exit_inds
    return v

DAILY_GATE_VARIANTS = {}
for _fam, _entry, _exit in (("v5", _V5_ENTRY, None), ("v7", _V7_ENTRY, _V7_EXIT)):
    DAILY_GATE_VARIANTS.update({
        f"s_{_fam}_level":        _v(f"s_{_fam}_level", _entry, [_LEVEL], _exit),                  # LIVE control
        f"s_{_fam}_slope20_5":    _v(f"s_{_fam}_slope20_5", _entry, [_slope(20,5)], _exit),        # the candidate
        f"s_{_fam}_slope20_3":    _v(f"s_{_fam}_slope20_3", _entry, [_slope(20,3)], _exit),
        f"s_{_fam}_slope20_1":    _v(f"s_{_fam}_slope20_1", _entry, [_slope(20,1)], _exit),        # old engine behaviour
        f"s_{_fam}_slope50_5":    _v(f"s_{_fam}_slope50_5", _entry, [_slope(50,5)], _exit),
        f"s_{_fam}_level_and_slope20_5": _v(f"s_{_fam}_level_and_slope20_5", _entry, [_LEVEL, _slope(20,5)], _exit),
        f"s_{_fam}_drsi50":       _v(f"s_{_fam}_drsi50", _entry, [_rsi(50)], _exit),
        f"s_{_fam}_slope20_5_drsi50": _v(f"s_{_fam}_slope20_5_drsi50", _entry, [_slope(20,5), _rsi(50)], _exit),
    })


# =============================================================================
# RESULT — the post-hoc screen did NOT transfer (as flagged), but LEVEL *AND*
# SLOPE did. (2yr / 9 symbols / tick fills)
#
# Slope INSTEAD of level fails, confirming reason #1 above:
#   v5: level n=70 +2.13% PF 5.63   ->  slope20_5 n=104 +1.56% PF 3.45
#   v7: level n=155 +1.65% PF 2.27  ->  slope20_5 n=172 +1.44% PF 2.01
#   (the screen had predicted +2.06%/PF 3.11 for the slope gate — the real
#    number is +1.56%. Post-hoc filtering of a trade list is not a backtest.)
#
# Slope as an ADDITIONAL requirement on top of the level gate is different:
#
#   v7   gate                        n     avg     total     PF   tail  worst  qtrs syms
#     level (LIVE)                 155  +1.65%  +255.9%   2.27  9.0%  -24.73  7/8  8/9
#     level AND EMA20 slope5 > 0   143  +1.82%  +259.9%   2.57  8.4%  -24.73  6/8  9/9
#   Better average, better PF, lower tail, all 9 symbols positive, higher total
#   return on TWELVE FEWER TRADES, and better in both halves (H1 1.60 vs 1.55,
#   H2 2.05 vs 1.77). Worse on one axis only: 6/8 quarters vs 7/8.
#
#   Critically it PASSES the removed-vs-kept test that killed every previous
#   candidate: the 12 trades it removes average -0.33%, against +1.82% for the
#   ones it keeps. It is selecting, not just thinning.
#
# The v5 version does NOT pass that test and should not be adopted:
#     v5 level AND slope: n=60 +2.17% PF 6.45 — looks good on the summary, but
#     the 10 trades it removes average +1.85% (9 of them winners). Same trap as
#     the BTC-strength gate: better headline numbers bought by deleting
#     profitable trades that happened to include the one -8.24% loser.
#
# HOW MUCH TO BELIEVE THE v7 RESULT: the entire improvement comes from removing
# 12 trades out of 155. That is a thin base — the same fragility that made arm
# 4.0 look safe on one trade, just less extreme. The lookback plateau test
# below is the discriminator: if the effect is real it should vary smoothly
# around lookback 5 rather than appearing only at that one value.
#
# Also rejected outright: daily RSI as a gate (rsi_threshold min 50) — v7
# n=33 avg -0.78% PF 0.76; it removes 133 trades averaging +2.19%. It is not a
# trend gate at all on this timeframe.
# =============================================================================

def _lvl_slope(fam, entry, exit_inds, lb):
    return _v(f"p_{fam}_lvl_slope{lb}", entry, [_LEVEL, _slope(20, lb)], exit_inds)

for _fam, _entry, _exit in (("v7", _V7_ENTRY, _V7_EXIT), ("v5", _V5_ENTRY, None)):
    for _lb in (2, 3, 4, 5, 7, 10):
        DAILY_GATE_VARIANTS[f"p_{_fam}_lvl_slope{_lb}"] = _lvl_slope(_fam, _entry, _exit, _lb)
    # slope direction variants at the winning lookback
    DAILY_GATE_VARIANTS[f"p_{_fam}_lvl_notfall5"] = _v(
        f"p_{_fam}_lvl_notfall5", _entry, [_LEVEL, _slope(20, 5, "not_falling")], _exit)


# =============================================================================
# PLATEAU TEST RESULT — THE CANDIDATE IS NOISE. REJECTED. (2yr / 9 syms / tick)
#
# v7, level AND daily-EMA20-slope > 0, sweeping the slope lookback. The column
# that matters is the expectancy of the trades the gate REMOVES: if the gate
# genuinely selects, that number should be negative across a RANGE of
# lookbacks, not at one value.
#
#   lookback   n    avg     PF    tail  qtrs  |  REMOVES   at
#     (none)  155  +1.65%  2.27   9.0%   7/8  |     —       —
#       2     128  +1.88%  2.60   8.6%   6/8  |    27    +0.58%
#       3     138  +1.85%  2.55   8.7%   6/8  |    19    +0.47%
#       4     139  +1.98%  2.95   7.9%   7/8  |    16    -1.17%
#       5     143  +1.82%  2.57   8.4%   6/8  |    12    -0.33%
#       7     143  +1.64%  2.24   9.1%   6/8  |    12    +1.82%
#      10     147  +1.68%  2.31   8.8%   7/8  |     8    +1.08%
#
# The removed-trade expectancy swings from +1.82% to -1.17% between ADJACENT
# lookbacks, and avg/PF bounce with no structure (2.60, 2.55, 2.95, 2.57, 2.24,
# 2.31). That is not a plateau — it is a filter removing a near-random 8-27
# trades out of 155, and two of the six cells happened to catch a negative
# subset. Compare the trailing-stop arm sweep from the dip_v5 work, which rose
# 1.83 -> 2.14 -> 2.56 -> 2.81 -> 2.96 -> 3.31 -> 3.55 and then fell: THAT is
# what a real effect looks like across a parameter.
#
# The v5 side is a cleaner rejection still — the removed trades are PROFITABLE
# at every single lookback (+2.16, +1.98, +2.05, +1.85, +2.11, +1.67). It
# consistently deletes winners. Its better-looking tail (1.7% vs 2.9%) and
# symbol spread (9/9 vs 8/9) are bought by trading less, and total return falls
# from +148.8% to +117-139%.
#
# not_falling at lookback 5 is byte-identical to rising at lookback 5 on both
# entries — over 5 daily bars the EMA20 is essentially never exactly flat, so
# the two directions collapse to the same filter.
#
# VERDICT: no lighter or additional daily gate found. The live level gate at 0
# stands. That is now five independent attacks on it (invert, soften, replace
# with a market-wide reference, reformulate as direction/convergence, and add a
# slope requirement) and it has survived all five.
#
# WHAT THE SCREEN WAS ACTUALLY SEEING: the daily features DO separate winners
# from disasters (EMA20 under EMA50, negative slopes, negative 14d return —
# best AUC 0.596). But every one of those is a restatement of "the daily trend
# is down", which the level gate already captures. There was no independent
# information in them, only a noisier proxy for the same thing.
#
# KEPT REGARDLESS: `lookback_bars` on ema_slope (both engines, default 1 so
# nothing changes) and the _ema_history retention bump. The 1-bar slope was
# genuinely too noisy to be useful on daily bars, and now longer lookbacks are
# at least expressible for future work.
# =============================================================================
