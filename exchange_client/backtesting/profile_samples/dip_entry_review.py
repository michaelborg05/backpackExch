"""
backtesting/profile_samples/dip_entry_review.py
===============================================
ROUND 1 (2026-10-19) — ARE THE LIVE DIP ENTRIES LEAVING A SEPARABLE LOSER
POPULATION ON THE TABLE?

Motivation: the Oct 2026 live losers — ZEC v7 (1385, Oct 1) and v5 (1390,
Oct 2) both fell -19.5% and exited -5.1/-5.5% on the logical exit; RAY v7
(2.22, Oct 12) and v5 (1.92, Oct 16) closed -19.8/-7.4% (the second through the
phantom wide-book price bug, fixed in #41). Both ZEC entries bought a 4h EMA20
that had been falling ~0.5%/bar for days.

Method: the live controls below export every 2yr trade; entry-time features
are attached offline and each candidate gate is judged by the REMOVED-vs-KEPT
expectancy of the trades it would veto (see btc_regime_variants.py: "PF and
worst must improve" is gameable). Only a gate that survives that screen, per
symbol and per quarter, gets a variant here.

Controls match prod as of 2026-10-19: v5's exit RSI cap moved 55 -> 59 on
2026-10-06 (config_audit_log), so v5 is run at 59, unlike dip_exit_structure.
"""

from backtesting.profile_samples.dip_exit_structure import _BASE, _V5_ENTRY, _V7_ENTRY

_EXIT_59 = [
    {"type": "rsi_overbought", "params": {"side": "long", "min_value": 59}},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
]

_FAMILY = {
    # label: (entry, live_trail_pct, min_position_age_for_trend_check)
    "v5": (_V5_ENTRY, 0.6, 0),
    "v7": (_V7_ENTRY, 1.0, 30),
}


def _v(name, family, *, extra_entry=None, extra_required=0):
    entry, trail, min_age = _FAMILY[family]
    return {
        **_BASE,
        "display_name": name,
        "entry_indicators": entry + (extra_entry or []),
        "min_entry_indicators_required": _BASE["min_entry_indicators_required"] + extra_required,
        "exit_indicators": _EXIT_59,
        "min_position_age_for_trend_check": min_age,
        "trailing_stop_pct": trail,
    }


def _slope_cap(max_slope):
    # Veto the entry unless EMA20(4h) fell by more than |max_slope|% over 5 bars.
    # hard_stop pass still counts +1, hence extra_required=1 (a pure veto).
    return [{"type": "ema_slope", "params": {
        "ema": 20, "direction": "not_rising", "max_slope_pct": max_slope,
        "lookback_bars": 5, "hard_stop": True}}]


DIP_ENTRY_VARIANTS = {
    "e_v5_live": _v("e_v5_live", "v5"),
    "e_v7_live": _v("e_v7_live", "v7"),

    # ── the only screen candidate with a plateau: v7, skip flat-EMA20 dips ──
    **{f"e_v7_slope{abs(s):.2f}".replace(".", ""): _v(f"e_v7_slope{abs(s):.2f}".replace(".", ""), "v7",
                                                        extra_entry=_slope_cap(s), extra_required=1)
       for s in (-0.25, -0.55, -0.75, -1.0)},
}

# ── ROUND 2: v7's entry RSI cap (live 45) was never swept. Lower = wait for a
#    deeper RSI before buying the same dip. v5's equivalent (oversold 30) was
#    tested in dip_v5_optimisation round 2: n=11, too rare. ───────────────────
for _cap in (35, 38, 40, 42):
    _entry = [dict(i, params=dict(i["params"], min_value=_cap)) if i["type"] == "rsi_overbought" else i
              for i in _V7_ENTRY]
    DIP_ENTRY_VARIANTS[f"e_v7_rsi{_cap}"] = {**_v(f"e_v7_rsi{_cap}", "v7"), "entry_indicators": _entry}


# =============================================================================
# ROUND 1 RESULT (2026-10-19) — REFUTED. NO ROBUST ENTRY VETO; LIVE WINS.
# 2yr (23-753d, ends 2026-09-26), 23 symbols, tick fills, net of 0.05% RT.
# -----------------------------------------------------------------------------
# Offline removed-vs-kept screen of 23 entry features (4h EMA20 slope/gap, RSI,
# dist from 18-bar high / 7d low, momentum, daily EMA50 gap/slope, ATR, BTC):
# the losers are SHALLOW, SLOW dips (price just under a flat EMA20); steeply
# falling EMA20 entries are the BEST quintile — the opposite of the ZEC
# intuition. gap20 cuts were single-threshold spikes (overfit); only v7
# e20_slope5 showed a plateau (+60..+112 at cuts -0.75..0), and even that was
# second-year only (H1 removed avg ~0, H2 ~-2) and negative in 4/8 quarters.
#
# In the ENGINE it loses at every cut:
#   variant          n    avg   net_tot     H1      H2    PF   worst  qtr+  sym+
#   e_v7_live      569  +1.04   +594.2   +644.5  -50.3  1.58  -58.41  7/9  16/23
#   e_v7_slope025  538  +1.04   +561.9   +615.8  -54.0  1.58  -58.41  6/9  17/23
#   e_v7_slope055  509  +1.05   +535.9   +554.2  -18.3  1.59  -58.41  6/9  17/23
#   e_v7_slope075  490  +1.04   +510.3   +522.9  -12.7  1.58  -58.41  7/9  16/23
#   e_v7_slope100  471  +1.09   +511.3   +575.4  -64.1  1.60  -58.41  6/9  17/23
#
# WHY THE SCREEN LIED: it removed 171 trades at slope055, the engine only 60.
# A vetoed dip is not skipped, it RE-ENTERS a few bars later once the EMA20 has
# fallen far enough — same episode, worse timing. An entry veto on a feature
# that evolves within the episode DEFERS the trade; offline removed-vs-kept
# cannot see that. Always confirm a screen in the engine and compare n.
# Costs concentrate in bull quarters (2024Q4 -65..-83). Worst trade untouched.
#
# Side finding: e_v7_live is NET NEGATIVE in its second year (H2 -50.3) while
# v5 stays positive (+16.0) — v7's edge is front-loaded, as in the 14-symbol
# OOS test. NOTHING IN THIS FILE SHOULD BE DEPLOYED.
# =============================================================================


# =============================================================================
# ROUND 2 RESULT (2026-10-21) — v7 ENTRY RSI CAP: REJECTED, LIVE 45 STAYS.
#   variant      n    avg   net_tot    H1      H2     PF   worst  tail  qtr+  sym+
#   e_v7_live  569  +1.04   +594.2  +644.5   -50.3  1.58  -58.41  7.4%  7/9  16/23
#   e_v7_rsi42 465  +0.90   +418.9  +526.1  -107.2  1.47  -38.67  7.7%  6/9  16/23
#   e_v7_rsi40 393  +1.10   +433.3  +521.2   -87.9  1.63  -34.91  6.6%  6/9  15/23
#   e_v7_rsi38 323  +1.01   +327.2  +409.0   -81.8  1.56  -33.54  7.4%  5/8  14/23
#   e_v7_rsi35 223  +1.52   +338.2  +329.4    +8.9  2.08  -29.13  5.4%  6/8  20/23
# Every lower cap costs 160-270 of total, mostly in bull quarters (2024Q4
# -80..-221) where the deep-RSI entry never comes; it helps in 2025Q4/2026Q1
# (+11..+74) and halves the worst trade. A risk dial, not an edge. rsi35's
# positive H2 is not trustworthy: rsi38 beside it is H2 -82, 14/23 syms — no
# plateau. At 35, v7 becomes a lower-frequency copy of v5. Same conclusion as
# dip_v5_optimisation rounds 2-7: frequency and edge are one dial.
# =============================================================================
