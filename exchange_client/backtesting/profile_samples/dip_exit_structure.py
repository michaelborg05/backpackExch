"""
backtesting/profile_samples/dip_exit_structure.py
==================================================
ROUND 1 (2026-09-28) — IS THE LOGICAL EXIT, NOT THE TRAIL, WHAT CAPS THE DIP
PROFILES' WINNERS?

Motivation (2026-09-26 replay of all 18 live dip trades, entries held fixed,
1m paths, prod reproduced to the basis point at +2.36%/trade):

    live (arm 3.5, trail 0.6/1.0)                          +2.36%/trade
    flat trail 2.0 / 3.0                                   +2.65 / +2.65
    ratchet wide-first (3->0.8) / tight-first (1->3)        +2.66 / +2.65   <- SHAPE IS NOISE
    +1% profit floor on the logical exit                   +3.14
    25% runner tranche @ 8% trail, exempt from the exit    +4.56
    NO logical exit at all, trail 3.0                      +7.44

Widening the trail just hands the trade to the logical exit instead (trail
exits 11->6, logical 7->12). 7 of the 18 live exits were TREND_INVALIDATION and
four of those fired at -1.88% to +1.99% immediately before the market ran +14%
to +44%. That replay is 18 trades in a 10-week uptrend, so it proves nothing on
its own — this file is the 2yr / all-symbol test.

WHAT TREND_INVALIDATION ACTUALLY IS, decoded and verified against the live exit
bars: min_exit_indicators_required=1 over `rsi_overbought(min_value=59)` — which
is an RSI **CAP**, bullish when RSI <= 59 — and `price_extended_below_ema(20,
-0.001..-99)` — bullish only when price is BELOW the ema20. Invalidation fires
when NEITHER holds, i.e.

    RSI(4h) > 59  AND  close >= EMA20(4h)        (v5 uses 55)

a "the bounce is complete" rule. In an uptrend the EMA20 reclaim is the START of
the move, and the rule has no P&L floor, so it liquidates underwater positions
at the worst possible moment.

THE TRAP IN THE REPLAY NUMBER, recorded before the run so the result cannot be
rationalised afterwards: `nolog_tr3`'s 100% win rate and +0.61% worst trade are
ARITHMETIC, not evidence. With stop_loss_pct=99 there is no hard stop, so once
the logical exit is gone the only exits are the trail — which cannot fire below
roughly arm - trail = +0.5% — and the 720h stale exit. The entire loss
distribution therefore lives in trades that NEVER REACH THE 3.5% ARM, and the
10-week bull sample contained exactly zero of those (7 of 18 were still under
+3% MFE when prod exited them; the rally rescued every one).

    => THE DECISIVE METRIC HERE IS THE stale_position EXIT BUCKET: how many,
       and at what P&L. If removing the logical exit merely converts
       trend_invalidation exits into deeper stale_position exits, it is not an
       improvement, it is deferred loss recognition.

PER ROUND 4 OF dip_v5_optimisation.py: run on the FULL symbol roster, never a
4-symbol subset. Temporal robustness is not cross-sectional robustness.

NOTE ON TAKE PROFIT (Michael's addition): a TP is not a free cap. prod's
`_check_stale_position` measures staleness as progress TOWARD TP
(`progress_pct = profit_pct / take_profit_pct * 100`, exit only if <= 50%), and
the engine mirrors it exactly. So at the live TP of 99 the 720h cap is
effectively unconditional, while at TP 15 it only applies to trades under
+7.5%. Adding a TP therefore changes the time exit as well as adding a ceiling
— the tp15/tp20 cells move two levers at once, which is why the
`live_tp15` cells are here to isolate the ceiling on its own.
"""

# =============================================================================
# Shared skeleton — the LIVE dip configuration, minus the symbol pin.
# Matches trading_profiles/indicators for profile7 (v5) and profile10 (v7) as
# read from the prod branch on 2026-09-26. Deliberately UNPINNED on symbols so
# a run cannot silently collapse onto a 4-symbol in-sample subset.
# =============================================================================
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
    "min_exit_indicators_required": 1,

    "use_trailing_stop": True,
    "arm_trailing_stop_pct": 3.5,
    "take_profit_pct": 99.0,
    "stop_loss_pct": 99.0,
    "max_position_hours": 720,

    "min_signal_confidence": 0.0,
    "min_volume_ratio": 0.0,
    "signal_cooldown_minutes": 1300,
}

# --- v5: the RSI-reversal entry (live profile7), trail 0.6, exit RSI 55 -------
_V5_ENTRY = [
    {"type": "rsi_reversal_momentum", "params": {
        "lookback_candles": 4, "oversold_threshold": 35.0, "current_min": 35.0,
        "min_jump": 6.0, "require_sustained": False, "sustained_rise_mode": "net",
        "hard_stop": True}},
    {"type": "price_extended_below_ema", "params": {
        "ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
]
_V5_EXIT = [
    {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
]

# --- v7: the deep distance_from_high entry (live profile10), trail 1.0, RSI 59 -
_V7_ENTRY = [
    {"type": "distance_from_high", "params": {
        "lookback_bars": 18, "min_pct_below": 12.0, "max_pct_below": 30.0, "hard_stop": True}},
    {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
]
_V7_EXIT = [
    {"type": "rsi_overbought", "params": {"side": "long", "min_value": 59, "max_value": 30, "lookback_candles": None}},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
]

_FAMILY = {
    # label: (entry, exit, live_trail_pct, min_position_age_for_trend_check)
    "v5": (_V5_ENTRY, _V5_EXIT, 0.6, 0),
    "v7": (_V7_ENTRY, _V7_EXIT, 1.0, 30),
}


def _v(name, family, *, trail=None, tp=99.0, use_ti=True):
    entry, exit_inds, live_trail, min_age = _FAMILY[family]
    return {
        **_BASE,
        "display_name": name,
        "entry_indicators": entry,
        "exit_indicators": exit_inds,
        "min_position_age_for_trend_check": min_age,
        "trailing_stop_pct": live_trail if trail is None else trail,
        "take_profit_pct": tp,
        "use_trend_invalidation_exit": use_ti,
    }


DIP_EXIT_VARIANTS = {}
for _f in ("v5", "v7"):
    DIP_EXIT_VARIANTS.update({
        # ── control: the live profile, unchanged ────────────────────────────
        f"x_{_f}_live":            _v(f"x_{_f}_live", _f),

        # ── A. drop the logical exit, sweep the trail that replaces it ──────
        #    This is the whole question. The trail becomes the ONLY exit
        #    besides the 720h stale cap, so watch the stale bucket.
        f"x_{_f}_nolog_tr2":       _v(f"x_{_f}_nolog_tr2", _f, trail=2.0, use_ti=False),
        f"x_{_f}_nolog_tr3":       _v(f"x_{_f}_nolog_tr3", _f, trail=3.0, use_ti=False),

        # ── B. + a take-profit ceiling so a big move is banked rather than
        #    given back through the trail (Michael's addition). NOTE these move
        #    two levers: see the TP caveat in the module docstring.
        f"x_{_f}_nolog_tr3_tp15":  _v(f"x_{_f}_nolog_tr3_tp15", _f, trail=3.0, tp=15.0, use_ti=False),
        f"x_{_f}_nolog_tr3_tp20":  _v(f"x_{_f}_nolog_tr3_tp20", _f, trail=3.0, tp=20.0, use_ti=False),

        # ── C. the TP ceiling ALONE, logical exit and trail left live, so the
        #    ceiling's contribution can be separated from dropping the exit ──
        f"x_{_f}_live_tp15":       _v(f"x_{_f}_live_tp15", _f, tp=15.0),
        f"x_{_f}_live_tp20":       _v(f"x_{_f}_live_tp20", _f, tp=20.0),
    })


# =============================================================================
# ROUND 1 RESULT (2026-09-28) — REFUTED. THE LIVE CONFIG WINS ON BOTH ENTRIES.
# 2yr, 23 symbols, tick fills, net of the measured 0.05% VIP5 round trip.
# -----------------------------------------------------------------------------
#   variant              n   win%  net_avg   net_tot    PF    worst  tail  qtr+  sym+  hrs
#   x_v5_live          157   79%   +1.61    +253.3   2.95  -18.43  1.9%  7/8  18/22   58
#   x_v5_nolog_tr3     148   90%   +2.15    +318.6   2.46  -38.84  5.4%  6/8  17/22  165
#   x_v5_nolog_tr2     148   90%   +1.90    +281.6   2.29  -38.84  5.4%  6/8  18/22  156
#   x_v7_live          569   82%   +1.04    +594.2   1.58  -58.41  7.4%  7/9  16/23   77
#   x_v7_nolog_tr3     542   90%   +0.32    +174.5   1.12  -63.63  8.9%  5/9  15/23  128
#   x_v7_nolog_tr2     544   90%   +0.33    +178.9   1.12  -63.63  8.8%  5/9  16/23  124
#
# THE 90% WIN RATE IS MANUFACTURED, exactly as predicted above. With SL=99 the
# trail cannot fire below arm-trail — the observed minimum win is +0.35% on both
# families. Wins are a property of the exit structure; the losses migrate into
# the 720h stale bucket. Pairing every trade on (symbol, entry_time), which is
# exact because entries are identical across these variants:
#
#   v7_live -> v7_nolog_tr3              n    ctrl      test     delta
#     trailing_stop -> trailing_stop   431   +3.57     +3.39     -78.0
#     trend_invalidation -> trail       57   -2.85     +3.48    +361.0
#     trend_invalidation -> stale       49  -13.43    -27.28    -678.8   <- the killer
#                                                      NET     -395.8
#
#   v5_live -> v5_nolog_tr3              n    ctrl      test     delta
#     trailing_stop -> trailing_stop    94   +3.59     +4.11     +49.1
#     trend_invalidation -> trail       38   -0.43     +3.90    +164.6
#     trend_invalidation -> stale       16   -4.87    -13.50    -138.0
#                                                      NET      +75.6
#
# => DROPPING THE LOGICAL EXIT DOES NOT REMOVE LOSSES, IT DEFERS AND DEEPENS
#    THEM. The TI exit was already cutting v7's 49 worst trades at -13.4%;
#    without it they run to -27.3% before the 720h cap catches them. v5 nets
#    +75.6 over two years and pays for it with the worst case doubling
#    (-18.43 -> -38.84) and the tail tripling (1.9% -> 5.4%).
#
# THE 18-TRADE REPLAY THAT MOTIVATED THIS FILE WAS SAMPLED FROM THE SINGLE MOST
# FAVOURABLE QUARTER IN TWO YEARS. Per-quarter net:
#   variant          2024Q4 2025Q1 2025Q2 2025Q3 2025Q4 2026Q1 2026Q2 2026Q3
#   x_v5_live         +86.9  +35.4  +49.1  +18.0   -2.5   +9.7   +2.2  +54.5
#   x_v5_nolog_tr3   +157.9  +38.1  +18.7   +9.7  -18.9  +15.9  -38.4 +135.5
#   x_v7_live        +356.4  +84.4  +53.5 +144.1  -67.2  -88.8   +1.8 +103.9
#   x_v7_nolog_tr3   +276.4  +28.5  -19.2  +63.9  -92.0 -135.0  -93.6 +142.9
# 2026Q3 is the replay window and the one quarter where nolog is clearly better.
# 2026Q1/Q2 are far worse. Round 4 of dip_v5_optimisation.py, again.
#
# TAKE PROFIT (15% / 20%) — REFUTED, AND A NO-OP ON THE LIVE CONFIG.
#   x_v5_live / _tp15 / _tp20 are BIT-IDENTICAL (n=157, +1.61, PF 2.95) at both
#   120d and 2yr: the logical exit or the trail always fires first, so a 15-20%
#   ceiling is never reached. On v7_live it is marginally negative (+1.04 ->
#   +1.01/+1.02), and on every nolog base it is negative (v5 +2.15 -> +2.11,
#   v7 +0.32 -> +0.25). A TP only ever caps a winner here; it protects nothing.
#
# WHAT SURVIVES — THE RUNNER TRANCHE, AND THIS RUN STRENGTHENS ITS CASE.
# All the damage sits in trades that NEVER ARM: 49 of v7's 106 TI exits never
# reached +3.5% even over 720h. A runner only comes into existence AFTER a
# trailing exit has fired, so it cannot touch that population at all, and its
# downside is bounded at ~runner_fraction x (hw*0.92 vs hw*0.97) on trades that
# were already winners. The bucket it would operate on is large and healthy:
# 431 trades at +3.57% (v7) and 94 at +3.59% (v5).
#   Caveat carried forward: in the 18-trade replay the runner only paid when it
#   was EXEMPT from the logical exit (+4.56 vs +2.36; with the exit still active
#   it was +2.48, i.e. nothing). So it is the same kind of change that failed
#   here, bounded to a fraction of already-winning trades. Test it as such.
#
# NOTHING IN THIS FILE SHOULD BE DEPLOYED.
# =============================================================================
