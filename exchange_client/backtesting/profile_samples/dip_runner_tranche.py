"""
backtesting/profile_samples/dip_runner_tranche.py
==================================================
ROUND 1 (2026-09-28) — DOES A RUNNER TRANCHE CAPTURE THE TAIL WITHOUT BUYING
THE TAIL RISK?

Background. dip_exit_structure.py refuted the obvious fix (remove the logical
exit, widen the trail): over 2yr/23 symbols it defers and DEEPENS losses —
v7's 49 worst trades go from -13.4%, where the trend-invalidation exit cut
them, to -27.3% running into the 720h cap, netting -396. Widening or
ratcheting the trail on its own is worth ~24bps and the ratchet SHAPE is
noise. A take profit at 15/20% is a literal no-op on the live config.

But the same run showed exactly where the risk lives, and it is not where a
runner operates:

    v7_live exit buckets        n     avg      worst
      trailing_stop           450   +3.55     +2.42
      trend_invalidation      115   -7.46    -41.62
      stale_position            4  -36.77    -58.41

    49 of those 115 trend_invalidation trades NEVER ARMED, even over 720h.

A runner tranche is only reachable THROUGH a trailing exit. It therefore
cannot touch the never-armed population at all — structurally, not
statistically. Its downside is bounded: the runner stops at
hw * (1 - runner_trail), and hw >= entry * (1 + arm), so at arm 3.5 / runner
trail 12 the worst a runner can do is about -8.8% on a trade that had already
banked its main tranche at roughly +3%.

THE HYPOTHESIS, and the honest caveat. In the 18-trade replay the runner only
paid when it was EXEMPT from the logical exit (+4.56%/trade vs +2.36% live;
with the exit still applied to the runner it was +2.48%, i.e. nothing). So
this is the same KIND of change that failed in dip_exit_structure.py — the
claim is that bounding it to `runner_fraction` of an already-winning trade is
what makes it survive. The `_ti` cells below keep the logical exit on the
runner, so how much of any gain comes from the exemption is visible rather
than assumed.

PRIOR EXPECTATION, recorded before the run: the exempt cells will beat the
control on avg%/trade and the gain will be concentrated in 2024Q4 / 2026Q3 —
the two strong quarters. The test is whether the LOSING quarters (2025Q4,
2026Q1, 2026Q2 for v7) get worse, and whether the worst trade and the <-10%
tail move at all. If the tail is unchanged and the bad quarters are flat, the
structural argument held. If the bad quarters degrade, the bound was not the
protection it looks like.

Split is 60/40 — close 60% of the position at the normal trailing exit, leave
40% running (Michael, 2026-09-28). A 25% cell is kept as a reference point so
the sensitivity to the fraction is visible.

READ THE RESULTS THE WAY ROUND 4 OF dip_v5_optimisation.py TAUGHT: per-symbol
and per-quarter, on the full roster, never a subset.
"""

from backtesting.profile_samples.dip_exit_structure import _FAMILY, _v

# =============================================================================
# Runner cells. Everything not named here is the LIVE config: logical exit ON,
# live trail (0.6 v5 / 1.0 v7), arm 3.5, TP/SL 99, 720h cap.
# =============================================================================


def _r(name, family, *, frac=0.40, runner_trail=8.0, exempt=True):
    v = _v(name, family)
    v.update({
        "runner_fraction":                  frac,
        "runner_trailing_stop_pct":         runner_trail,
        "runner_exempt_trend_invalidation": exempt,
    })
    return v


DIP_RUNNER_VARIANTS = {}
for _f in ("v5", "v7"):
    DIP_RUNNER_VARIANTS.update({
        # ── control: live, runner disabled. MUST reproduce x_{f}_live exactly;
        #    if it does not, the runner code changed the no-runner path. ──────
        f"r_{_f}_live":            _v(f"r_{_f}_live", _f),

        # ── the 60/40 split, sweeping how much room the runner gets ─────────
        f"r_{_f}_run40_tr6":       _r(f"r_{_f}_run40_tr6",  _f, runner_trail=6.0),
        f"r_{_f}_run40_tr8":       _r(f"r_{_f}_run40_tr8",  _f, runner_trail=8.0),
        f"r_{_f}_run40_tr12":      _r(f"r_{_f}_run40_tr12", _f, runner_trail=12.0),

        # ── the same runner, but still subject to the logical exit. Isolates
        #    how much of the gain is the exemption rather than the wider trail
        #    — the replay said "all of it", which needs confirming at 2yr. ───
        f"r_{_f}_run40_tr8_ti":    _r(f"r_{_f}_run40_tr8_ti", _f, runner_trail=8.0, exempt=False),

        # ── fraction sensitivity reference point ────────────────────────────
        f"r_{_f}_run25_tr8":       _r(f"r_{_f}_run25_tr8", _f, frac=0.25, runner_trail=8.0),
    })


# =============================================================================
# ROUND 1 RESULT (2026-09-28) — THE STRUCTURAL ARGUMENT HELD; THE EDGE DID NOT.
# REFUTED. 2yr, 23 symbols, tick fills, net of the 0.05% VIP5 round trip.
# -----------------------------------------------------------------------------
# FIRST, THE ARTIFACT THAT MAKES THE RAW TABLE LIE. A runner still open when the
# backtest window ends is marked to market at the final price, and the window
# ends in 2026Q3 — mid-rally. Those `end_of_window` rows are unrealised:
#
#   variant             n   eow_n  eow_avg  eow_total   total_all  total_REALISED
#   r_v5_live         157      0    +0.00       +0.0      +253.3         +253.3
#   r_v5_run40_tr8    157      2   +19.01      +38.0      +293.1         +255.1
#   r_v7_run40_tr8    532      6   +14.41      +86.5      +525.5         +439.0
#
# v5_run40_tr8's apparent +39.8 gain over live is +38.0 of unrealised open
# position. This is the SAME artifact that inflated the 18-trade replay which
# started this whole thread. Always strip end_of_window from both sides.
#
# REALISED-ONLY TOTALS, per quarter:
#   variant           24Q4   25Q1   25Q2   25Q3   25Q4   26Q1   26Q2   26Q3   TOTAL    n
#   r_v5_live        +86.9  +35.4  +49.1  +18.0   -2.5   +9.7   +2.2  +41.1  +239.9  153
#   r_v5_run40_tr6   +97.2  +34.2  +50.7  +22.0   -7.0   +8.5  +14.8  +46.8  +267.2  153
#   r_v5_run40_tr8   +80.1  +28.9  +39.0  +17.6   -1.2   +5.9  +38.6  +37.9  +246.9  153
#   r_v5_run25_tr8   +82.6  +31.3  +42.8  +17.7   -1.7   +7.3  +24.9  +39.1  +244.2  153
#   r_v5_run40_tr12  +63.1  +23.4  +57.2  +11.8   +3.5   +0.6  +31.7  +22.6  +213.9  146
#   r_v5_run40_tr8_ti+86.3  +34.6  +39.8   +9.7   -0.9   +9.7   +6.6  +39.1  +225.1  153
#
#   r_v7_live         (…)                                             +576.9  563
#   r_v7_run40_tr6                                                    +533.8  547
#   r_v7_run25_tr8                                                    +465.4  526
#   r_v7_run40_tr8                                                    +439.0  526
#
# WHAT HELD — and it is worth keeping, because the reasoning was right:
#   The worst trade and the <-10% tail are UNCHANGED at every setting on both
#   families (v5 -18.43 / 1.9%, v7 -58.41 / ~7.6%, identical to their controls).
#   A runner really cannot reach the never-armed population. The bound works.
#
# WHAT DID NOT — the upside it was supposed to buy is not there:
#   v5_run40_tr6 (the ONLY positive cell): 96 of 157 trades change, 38 improve
#   (+123.8) and 58 worsen (-89.8) for a net +27 over two years — +0.18%/trade,
#   on 13/22 symbols. It pays ~2.3% on most winners to occasionally collect
#   +8-10%, and that is close to a coin flip.
#   v5_run40_tr8 / run25_tr8: net +7.0 / +4.3, and ZEC alone is +19.1 / +11.9 —
#   ex-ZEC both are NEGATIVE. Single-symbol artifacts, same shape as the
#   tightzone/SOL result in swing_2yr_analysis.
#   v7: negative at every setting. It fires 3.6x more often than v5 (563 vs 153
#   realised trades), so a runner holding the position slot BLOCKS NEW ENTRIES —
#   35-87 lost entries depending on the runner trail. avg%/trade flatters this
#   badly (run40_tr6 reads +1.05 vs live +1.04) while the TOTAL is -43.
#
# THE EXEMPTION IS LOAD-BEARING AND THAT IS THE PROBLEM. r_v5_run40_tr8_ti,
# which keeps the logical exit on the runner, is +225.1 vs live +239.9 — WORSE
# than having no runner at all. So every version of this that helps at all
# depends on exempting the runner from the logical exit, which is the same
# mechanism dip_exit_structure.py refuted. Bounding it to 40% of an
# already-winning trade removed the tail risk but removed the payoff with it.
#
# NOTHING HERE SHOULD BE DEPLOYED. The `runner_*` engine fields stay — they are
# correct, inert at runner_fraction=0 (controls reproduce the dip_exit baselines
# exactly), and cheap to keep for a future strategy where the exit distribution
# is genuinely bimodal.
# =============================================================================
