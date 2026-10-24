"""
backtesting/profile_samples/dip_ti_conditional.py
=================================================
ROUND 1 (2026-10-23) — SHOULD THE LOGICAL EXIT DEPEND ON THE POSITION'S STATE?

The logical exit (TREND_INVALIDATION) fires when RSI(4h) > 59 AND close >=
EMA20(4h) — min_exit_indicators_required=1 over two HOLD conditions, so both
must fail. Michael's concern: after a long time underwater the rule fires
early in a recovery that keeps going.

Forward-return study of the 161 live-config TI exits (2yr, 23 syms; price
measured from the exit bar, 4h closes):

    v7 by exit P&L    n   fwd7d  fwd14d  back to entry <=14d
      < -10%         36   -2.84  -13.39     9%   <- exit is right, keeps falling
      -10..-5        19   +1.04   +4.76    63%
      -5..-2         24   +3.84   +7.92    83%   <- sold just before recovery
      -2..0          18   +4.63   +1.18   100%   <-
      > 0            18   -1.36   -7.76   100%
    v7 by hold time: 7-14d / >14d held get a +3..+4.5% 1-3d bounce after the
    exit that is GONE by 14d (-3.1 / -4.8). Long holds are not the problem;
    SHALLOW LOSERS are. v5 has the same shape on fewer trades.

So two hypotheses, both opt-in engine params (inert when None):
  A. ti_hold_pnl_range=(-X, 0): ignore the exit while the loss is shallower
     than X. If it deepens past -X the next exit signal still fires, so loss
     control is kept — unlike the refuted "only exit in profit".
  B. ti_late_after_hours / ti_late_exit_indicators: Michael's time-based idea.
     After N hours, raise the RSI cap 59 -> 65/70 to ride the 1-3d bounce.

Judge on TOTALS and n (a longer hold blocks re-entries), per quarter and per
symbol, and strip end_of_window.
"""

from backtesting.profile_samples.dip_entry_review import _v, _EXIT_59


def _exit_cap(cap):
    return [dict(i, params=dict(i["params"], min_value=cap)) if i["type"] == "rsi_overbought" else i
            for i in _EXIT_59]


DIP_TI_VARIANTS = {}
for _f in ("v5", "v7"):
    DIP_TI_VARIANTS[f"t_{_f}_live"] = _v(f"t_{_f}_live", _f)
    for _x in (2, 3, 5):
        DIP_TI_VARIANTS[f"t_{_f}_hold{_x}"] = {**_v(f"t_{_f}_hold{_x}", _f), "ti_hold_pnl_range": (-_x, 0)}
    for _h in (72, 168):
        for _cap in (65, 70):
            _n = f"t_{_f}_late{_h}h_rsi{_cap}"
            DIP_TI_VARIANTS[_n] = {**_v(_n, _f), "ti_late_after_hours": _h,
                                   "ti_late_exit_indicators": _exit_cap(_cap)}

# ── ROUND 2: round 1's hold ends the moment P&L crosses 0, where RSI is still
#    >59, so it mostly swaps a small loss for a breakeven exit. Extend the upper
#    edge to +1 and to the 3.5% trail arm so a recovering trade can arm. ─────
DIP_TI_R2_VARIANTS = {}
for _f in ("v5", "v7"):
    DIP_TI_R2_VARIANTS[f"t2_{_f}_live"] = _v(f"t2_{_f}_live", _f)
    for _x in (2, 3, 5):
        for _hi in (1.0, 3.5):
            _n = f"t2_{_f}_hold{_x}_to{str(_hi).replace('.', '')}"
            DIP_TI_R2_VARIANTS[_n] = {**_v(_n, _f), "ti_hold_pnl_range": (-_x, _hi)}


# =============================================================================
# RESULTS (2026-10-23) — 2yr (23-753d), 23 syms, tick fills, net 0.05% RT.
# -----------------------------------------------------------------------------
# B. TIME-BASED RSI CAP (Michael's idea) — REJECTED. v7 late168h_rsi65 +47.6
#    but 8 TI exits (-22.0) become stale_position (-33.2) = -89.2: the same
#    defer-and-deepen failure as dip_exit_structure. Negative in 4/9 quarters.
#    rsi70 cells lose outright (late72h_rsi70 -167, worst -58 -> -64). Every v5
#    late cell is <= live except late72h_rsi70 (+15, but worst -26 -> -39).
#
# A. SHALLOW-LOSS HOLD — the only survivor, v7 only, and MARGINAL:
#   variant            n   avg    net_tot    H1      H2     PF   tail  qtr+
#   t_v7_live        569  1.04    +594.2  +644.5  -50.3  1.58  7.4%  7/9
#   t_v7_hold2  (-2,0)568 1.09    +619.3  +660.6  -41.4  1.60  7.4%  7/9
#   t_v7_hold3  (-3,0)566 1.11    +628.3  +669.6  -41.4  1.61  7.6%  7/9
#   t2_v7_hold3_to10  566 1.12    +634.8  +690.7  -56.0  1.61  7.8%  7/9
#   t2_v7_hold3_to35  564 1.15    +650.9  +702.0  -51.2  1.62  8.0%  7/9
#   t2_v7_hold5_to35  561 1.16    +651.1  +685.1  -34.0  1.61  8.4%  7/9
# All 9 hold cells beat live (+22..+57) — a genuine plateau. Mechanism (paired,
# hold3_to35): 34 TI exits at +0.02 become trails at +3.23 (+108.9); the cost is
# the 78 that still fail, exiting 0.74 deeper (-57.3). No new stale exits,
# worst trade unchanged. BUT: the gain is first-year only (H2 flat at -51 vs
# -50 for hold3_to35), every cell loses 11-12.5 in 2026Q1, the <-10% tail
# rises 7.4 -> 8.0-8.4%. ~+0.1%/trade. Worth a forward test at most.
# v5: no plateau (hold5_to35 +30.6 alone; hold3_to35 -1.4; rest negative).
#
# Answer to "does a long-underwater exit sell the recovery?": NO. Deep / long
# holds keep falling after the exit (v7 <-10% exits: -13.4% at 14d, 9% ever
# regain entry). The exit's real cost is on SHALLOW losers, and even there the
# fix is worth ~10% of v7's total. Not deployed; prod has no equivalent field.
# =============================================================================


# ── ROUND 3 (2026-10-24): Michael's EMA20 gate. The exit's hold condition
#    price_extended_below_ema(20) reads max_gap <= gap <= min_gap, so raising
#    min_gap_pct from -0.001 to +X holds until the close is X% ABOVE EMA20
#    (RSI > 59 still required too). Pure DB config in prod — trend_cache uses
#    the same comparison. Never swept before. ──────────────────────────────
def _exit_gap(x):
    return [dict(i, params=dict(i["params"], min_gap_pct=x)) if i["type"] == "price_extended_below_ema" else i
            for i in _EXIT_59]


DIP_TI_R3_VARIANTS = {}
for _f in ("v5", "v7"):
    DIP_TI_R3_VARIANTS[f"t3_{_f}_live"] = _v(f"t3_{_f}_live", _f)
    for _x in (1, 2, 3, 5, 8):
        _n = f"t3_{_f}_ema20gap{_x}"
        DIP_TI_R3_VARIANTS[_n] = {**_v(_n, _f), "exit_indicators": _exit_gap(float(_x))}

# ROUND 3 RESULT (2026-10-24) — EMA20 GATE: REJECTED. (Window 23-753d run 5 days
# later than rounds 1-2, so v7 n=567 not 569; controls are same-run.)
#   v7 total: live/gap1/gap2 +594.4 (BIT-IDENTICAL), gap3 +581.3, gap5 +510.6, gap8 +443.7
#   v5 total: live +224.0, gap1 +225.4, gap2 +231.4, gap3 +234.2, gap5 +209.6,
#             gap8 +237.1 (worst -26 -> -39) — noise, mixed quarters, no plateau.
# The EMA half of the exit is NOT BINDING below ~+2%: when 4h RSI first crosses
# 59, price is nearly always already >2% above EMA20. The RSI half sets the exit.
# Above +3% it only defers losers: v7 gap5 moves 12 TI exits (-17.6) into stale
# (-32.5) = -179.3. Fourth instance of defer-and-deepen. Keep min_gap_pct -0.001.
