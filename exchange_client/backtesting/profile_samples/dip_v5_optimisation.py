# =============================================================================
# dip_v5 OPTIMISATION GRID  (round 2, 2026-08-19)
#
# Round 1 (see dip_buy_variants.py) established dip_v5_prod as the family
# champion by a wide margin, on 2yr / 9 symbols / 1m-path tick fills:
#
#   dip_v5_prod   n=31  WR 93.6%  avg +2.56%  PF 10.25  tail 3.2%  worst -6.50%
#                 7/7 quarters positive, 4/4 symbols, top symbol 32.6% of PnL
#
# It also confirmed the live TSL retune (arm 3.5 / trail 0.6) beats the
# research 4.0/2.0 on identical entries, and that the prod ABOVE-daily-EMA50
# gate beats every inverse variant tested.
#
# THE REMAINING PROBLEM IS FREQUENCY, NOT QUALITY. 31 trades in 2 years across
# 9 symbols is ~15/yr, roughly 1.7 per symbol-year. Two consequences:
#   - n=31 does not support much confidence in PF 10.25. A handful of trades
#     going the other way would move it a lot.
#   - At that cadence the profile contributes very little to the book however
#     good each trade is.
#
# This grid holds the winning shape fixed and varies one thing at a time, so
# every result is attributable. Three axes:
#
#   A. TRAILING STOP (arm x trail). Prior finding from the v7 grid was "the ARM
#      is the lever, not the trail" — keep the arm wide so the trail only acts
#      after real profit. That was measured on the DEEP entry; this checks it
#      on the reversal entry, where round 1 already showed arm 3.5/trail 0.6
#      beating arm 4.0/trail 2.0 (which confounds both axes at once).
#
#   B. DAILY GATE WIDTH. The gate is a hard "price >= daily EMA50". Softening
#      it to -2%/-4% should admit more trades. Round 1 showed that going all
#      the way to "9.5% BELOW" is worse, and removing it entirely is much
#      worse (+0.79% vs +2.56%), but the region just below zero was never
#      tested — and that is where the extra trades would come from.
#
#   C. ENTRY STRICTNESS. rsi_reversal_momentum requires a >=6 point jump off a
#      <=35 trough with RSI now >=35. Relaxing the jump to 4, or the trough to
#      40, admits weaker reversals. The original grid search chose 35/6 on a
#      2024-09 -> 2026-07 window; this re-tests it against the current exit and
#      trail, which have both changed since.
#
# Everything else — symbols, exit, cooldown, timeouts — is identical to
# dip_v5_prod so the comparison is clean.
#
# Run:
#   DATABASE_URL=$DATABASE_URL_LOCAL python backtesting/run_profile_variants_backtest.py \
#       --set dip_v5_opt --days 0-730 --price-source ticks --price-mode close
#
# READ THE RESULTS AS A GRID, NOT A LEADERBOARD. With ~20 variants on n=30-150
# trades each, the top line is partly noise. A change is only believable if it
# moves in the same direction across neighbouring cells (e.g. arm 3.0 and 4.0
# both behaving consistently around 3.5) and keeps quarterly/symbol spread.
# =============================================================================

_V5_BASE = {
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

    "symbols": ["SOL_USDC", "ZEC_USDC", "BTC_USDC", "ETH_USDC"],
}

def _entry(oversold=35.0, jump=6.0, current_min=35.0):
    return [
        {"type": "rsi_reversal_momentum", "params": {
            "lookback_candles": 4, "oversold_threshold": oversold, "current_min": current_min,
            "min_jump": jump, "require_sustained": False, "sustained_rise_mode": "net",
            "hard_stop": True}},
        {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
    ]

def _gate(min_gap):
    return [{"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": min_gap, "hard_stop": True}}]

def _v(name, *, arm=3.5, trail=0.6, gap=0, oversold=35.0, jump=6.0):
    return {**_V5_BASE, "display_name": name,
            "arm_trailing_stop_pct": arm, "trailing_stop_pct": trail,
            "trend_indicators": _gate(gap),
            "entry_indicators": _entry(oversold, jump)}

DIP_V5_OPT_VARIANTS = {

    # ── control: the live profile, unchanged ────────────────────────────────
    "o_base_prod": _v("o_base_prod"),

    # ── A. trailing stop: arm sweep at the prod trail (0.6) ─────────────────
    "o_arm2.5_tr0.6": _v("o_arm2.5_tr0.6", arm=2.5),
    "o_arm3.0_tr0.6": _v("o_arm3.0_tr0.6", arm=3.0),
    "o_arm4.0_tr0.6": _v("o_arm4.0_tr0.6", arm=4.0),
    "o_arm5.0_tr0.6": _v("o_arm5.0_tr0.6", arm=5.0),

    # ── A. trailing stop: trail sweep at the prod arm (3.5) ─────────────────
    "o_arm3.5_tr1.0": _v("o_arm3.5_tr1.0", trail=1.0),
    "o_arm3.5_tr1.5": _v("o_arm3.5_tr1.5", trail=1.5),
    "o_arm3.5_tr2.5": _v("o_arm3.5_tr2.5", trail=2.5),

    # ── A. corner check: wide arm + wide trail, and tight arm + tight trail.
    #    If "the arm is the lever" holds, arm5/tr2.5 should still be decent and
    #    arm2.5/tr0.6 should be the weak one.
    "o_arm5.0_tr2.5": _v("o_arm5.0_tr2.5", arm=5.0, trail=2.5),

    # ── B. daily gate width — the frequency lever most likely to work ───────
    "o_gate-2": _v("o_gate-2", gap=-2.0),
    "o_gate-4": _v("o_gate-4", gap=-4.0),
    "o_gate-7": _v("o_gate-7", gap=-7.0),

    # ── C. entry strictness ────────────────────────────────────────────────
    "o_jump4":            _v("o_jump4", jump=4.0),
    "o_jump8":            _v("o_jump8", jump=8.0),
    "o_oversold40":       _v("o_oversold40", oversold=40.0),
    "o_oversold30":       _v("o_oversold30", oversold=30.0),

    # ── combined frequency plays: the two most promising looseners together.
    #    Included so the interaction is visible; if either alone helps but the
    #    pair does not, that is the signal to keep them separate.
    "o_gate-4_jump4":     _v("o_gate-4_jump4", gap=-4.0, jump=4.0),
    "o_gate-4_oversold40":_v("o_gate-4_oversold40", gap=-4.0, oversold=40.0),
    "o_gate-2_oversold40":_v("o_gate-2_oversold40", gap=-2.0, oversold=40.0),
}


# =============================================================================
# ROUND 2 RESULTS (2yr, 9 symbols, tick fills) + ROUND 3 GRID
# -----------------------------------------------------------------------------
# A. TRAILING STOP — the ARM is the only thing that matters, and MORE IS BETTER
#    right up to the widest tested. Trail width is noise.
#
#      arm sweep (trail 0.6, gate 0)   n    WR     avg      PF     H1 avg  H2 avg
#        arm 2.5                      32  93.8%  +1.83%   7.83     ..      ..
#        arm 3.0                      31  93.5%  +2.14%   8.75     ..      ..
#        arm 3.5 (PROD)               31  93.5%  +2.56%  10.25    +2.96   +2.07
#        arm 4.0                      31  93.5%  +2.81%  11.16    +3.20   +2.34
#        arm 5.0                      31  93.5%  +2.96%  11.69    +3.32   +2.53
#      MONOTONE IN BOTH HALVES INDEPENDENTLY — not a single-regime artifact.
#
#      trail sweep (arm 3.5, gate 0): 0.6 -> +2.56%, 1.0 -> +2.46%,
#        1.5 -> +2.36%, 2.5 -> +2.55%. Flat. Trail width does not matter here.
#
#    Note all five arm cells have IDENTICAL entries (n=31, WR 93.5%, worst
#    -6.50%) — the arm only changes how much of each winner is kept. With just
#    2 losers in the sample, "delay the stop" always looks good, so the open
#    question is where it turns over. That is what round 3 tests.
#
# B. DAILY GATE — softening into the region just below zero is the frequency
#    answer, at almost no cost in quality:
#
#      gate (arm 3.5/0.6)      n    WR     avg    total     PF   tail   qtrs+
#        >= EMA50 (PROD)      31  93.5%  +2.56%   +79.2%  10.25   3.2%   7/7
#        >= -2%               48  87.5%  +2.25%  +108.2%  10.07   2.1%   8/8
#        >= -4%               60  86.7%  +2.12%  +127.3%   7.84   3.3%   8/9
#        >= -7%               78  76.9%  +1.16%   +90.5%   2.16   7.7%   7/9
#
#      -2% is a strict improvement in risk terms: 55% more trades, PF unchanged,
#      LOWER tail, 8/8 quarters, same 4/4 symbols, same concentration. -4%
#      nearly doubles trade count for the best total return. Quality falls off a
#      cliff between -4 and -7, so round 3 fills in -3/-5/-6. Both are positive
#      in both halves. Per-symbol the extra trades are spread, not dumped into
#      one name (BTC n14->23->27, ZEC n7->11->13, ETH n6->9->10, SOL n4->5->10).
#
# C. ENTRY STRICTNESS — the existing settings are already optimal. REJECTED:
#      jump 4  : n=44 avg +2.05% PF 5.53 — more trades, materially worse quality
#      jump 8  : n=18 avg +2.31% PF 7.39 — and UNSTABLE (H1 +3.10%, H2 +0.72%)
#      oversold 40: n=60 avg +1.13% PF 2.01, worst -26.98% — much worse tail
#      oversold 30: n=11 — too rare to trust despite 100% WR
#    Combining looseners is worse than either alone (gate-4 + jump4 = PF 3.15
#    vs gate-4 alone 7.84). Loosen the GATE only; leave the entry alone.
# =============================================================================

def _v3(name, *, arm=3.5, trail=0.6, gap=0, exit_rsi=55, trailing=True):
    v = _v(name, arm=arm, trail=trail, gap=gap)
    if not trailing:
        v = {**v, "use_trailing_stop": False}
    if exit_rsi != 55:
        v = {**v, "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": exit_rsi}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
        ]}
    return v

DIP_V5_OPT_VARIANTS.update({
    # --- where does the arm turn over? (gate 0, trail 0.6) -------------------
    "p_arm6":      _v3("p_arm6", arm=6.0),
    "p_arm7":      _v3("p_arm7", arm=7.0),
    "p_arm9":      _v3("p_arm9", arm=9.0),
    # the arm -> infinity limit: no trailing stop at all, pure logical exit
    "p_notrail":   _v3("p_notrail", trailing=False),

    # --- fill in the gate cliff between -4 and -7 ---------------------------
    "p_gate-3":    _v3("p_gate-3", gap=-3.0),
    "p_gate-5":    _v3("p_gate-5", gap=-5.0),
    "p_gate-6":    _v3("p_gate-6", gap=-6.0),

    # --- the actual candidates: best gate x best arm ------------------------
    "p_gate-2_arm5":  _v3("p_gate-2_arm5", gap=-2.0, arm=5.0),
    "p_gate-4_arm5":  _v3("p_gate-4_arm5", gap=-4.0, arm=5.0),
    "p_gate-2_arm4":  _v3("p_gate-2_arm4", gap=-2.0, arm=4.0),
    "p_gate-4_arm4":  _v3("p_gate-4_arm4", gap=-4.0, arm=4.0),
    "p_gate-2_arm7":  _v3("p_gate-2_arm7", gap=-2.0, arm=7.0),
    "p_gate-4_arm7":  _v3("p_gate-4_arm7", gap=-4.0, arm=7.0),
    "p_gate-4_notrail": _v3("p_gate-4_notrail", gap=-4.0, trailing=False),

    # --- if "let winners run" is the theme, is the RSI-55 exit also early? ---
    "p_exit59":       _v3("p_exit59", exit_rsi=59),
    "p_exit65":       _v3("p_exit65", exit_rsi=65),
    "p_gate-4_exit59_arm5": _v3("p_gate-4_exit59_arm5", gap=-4.0, exit_rsi=59, arm=5.0),
})


# =============================================================================
# ROUND 3 RESULTS + ROUND 4 (out-of-sample validation)
# -----------------------------------------------------------------------------
# THE ARM HAS A GENUINE INTERIOR OPTIMUM AT ~7% (gate 0, trail 0.6):
#     arm  2.5   3.0   3.5*  4.0   5.0   6.0   7.0    9.0   none
#     avg +1.83 +2.14 +2.56 +2.81 +2.96 +3.31 +3.55  +3.20 +3.05
#     PF   7.83  8.75 10.25 11.16 11.69 12.97 13.83   6.76  6.48
#   (* = current prod). Rises to 7 then falls — and the RANKING HOLDS IN BOTH
#   HALVES INDEPENDENTLY (H1 arm7 +3.87% vs arm3.5 +2.87%; H2 +3.20% vs +2.22%).
#   Beyond ~9 the trail rarely arms at all and the profile degenerates toward
#   the no-trail case (WR drops 93.5% -> 90.3%, worst -6.50% -> -8.64%). An
#   interior peak with consistent halves is much stronger evidence than the
#   monotone edge round 2 saw.
#
# THE GATE CLIFF IS BETWEEN -4 AND -5 (arm 3.5):
#     gate    0     -2     -3     -4     -5     -6     -7
#     avg  +2.56  +2.25  +2.16  +2.12  +1.44  +1.29  +1.16
#     PF   10.25  10.07  10.34   7.84   2.67   2.33   2.16
#     n       31     48     53     60     67     73     78
#   -2 and -3 hold PF at ~10 with 55-70% more trades and the LOWEST tails of
#   the whole grid (2.1% / 1.9% vs 3.2% at gate 0), 8/8 quarters positive.
#
# BEST COMBINED (2yr, 4 symbols, tick fills):
#     p_gate-2_arm7   n=48  WR 87.5%  avg +3.01%  total +144.6%  PF 13.12
#                     tail 2.1%  worst -6.50%  8/8 quarters  4/4 symbols
#     p_gate-4_arm7   n=60  WR 85.0%  avg +2.65%  total +158.8%  PF  8.27
#                     tail 3.3%  worst -6.50%  8/9 quarters  4/4 symbols
#     o_base_prod     n=31  WR 93.5%  avg +2.56%  total  +79.2%  PF 10.25
#   gate-2_arm7 is +55% trades and +83% total return over prod at a HIGHER PF
#   and a LOWER tail. Half-split: H1 +3.45%, H2 +2.64%.
#
# EXIT RSI — REJECTED, and this one is important because it cuts against the
# "let winners run" theme that the arm result establishes:
#     exit 55 (base) +2.56%  PF 10.25
#     exit 59        +1.32%  PF  1.82  worst -26.10%  (H1 +3.17%, H2 -0.96%)
#     exit 65        +1.24%  PF  1.70  worst -26.10%
#   Widening the trailing-stop arm lets winners run; widening the LOGICAL exit
#   just holds losers longer. Leave the exit at 55. (Note prod's v7 profile
#   uses 59 — worth revisiting there separately.)
#
# -----------------------------------------------------------------------------
# ROUND 4 — THE VALIDATION THAT MATTERS
# -----------------------------------------------------------------------------
# Everything above was fitted on FOUR symbols (SOL/ZEC/BTC/ETH — the _V5_BASE
# symbol list, which the runner uses to filter). BNB/XRP/DOGE/SEI/SUI were
# never involved in any of the 36 variants. Running the champion and the prod
# baseline on those five is therefore a genuine out-of-sample test, not another
# in-sample cell. If arm 7 + gate -2 does not beat prod there, it is a fit.
#
# Also here: a finer arm sweep to confirm the peak sits at 7 rather than being
# a single lucky cell, a trail check at the new arm, and a transfer test of
# arm 7 onto the v7 DEEP entry (a different entry population — if the arm
# finding is about this strategy's bounce shape it should transfer).
#
# NOTE ON MULTIPLE COMPARISONS: this is now ~50 variants deep on n=31-90 each.
# The defence is not the p-value, it is that both sweeps are SMOOTH with
# interior optima and consistent across independent halves, plus the OOS test
# below. Treat a champion that fails OOS as refuted regardless of its in-sample
# numbers.
# =============================================================================

_OOS_SYMS = ["BNB_USDC", "XRP_USDC", "DOGE_USDC", "SEI_USDC", "SUI_USDC"]

def _v4(name, *, arm=3.5, trail=0.6, gap=0, symbols=None):
    v = _v(name, arm=arm, trail=trail, gap=gap)
    if symbols:
        v = {**v, "symbols": symbols}
    return v

DIP_V5_OPT_VARIANTS.update({
    # --- confirm the peak is a plateau around 7, not one lucky cell ---------
    "q_g2_arm6.5": _v4("q_g2_arm6.5", gap=-2.0, arm=6.5),
    "q_g2_arm7.5": _v4("q_g2_arm7.5", gap=-2.0, arm=7.5),
    "q_g2_arm8":   _v4("q_g2_arm8",   gap=-2.0, arm=8.0),
    "q_g3_arm7":   _v4("q_g3_arm7",   gap=-3.0, arm=7.0),
    # trail should still be irrelevant at the wider arm
    "q_g2_arm7_tr1.5": _v4("q_g2_arm7_tr1.5", gap=-2.0, arm=7.0, trail=1.5),
    "q_g2_arm7_tr2.5": _v4("q_g2_arm7_tr2.5", gap=-2.0, arm=7.0, trail=2.5),

    # --- OUT-OF-SAMPLE: 5 symbols never used in the optimisation ------------
    "z_OOS_base_prod":   _v4("z_OOS_base_prod",   symbols=_OOS_SYMS),
    "z_OOS_gate-2_arm7": _v4("z_OOS_gate-2_arm7", gap=-2.0, arm=7.0, symbols=_OOS_SYMS),
    "z_OOS_gate-4_arm7": _v4("z_OOS_gate-4_arm7", gap=-4.0, arm=7.0, symbols=_OOS_SYMS),
    "z_OOS_arm7":        _v4("z_OOS_arm7",        arm=7.0, symbols=_OOS_SYMS),
    "z_OOS_gate-2":      _v4("z_OOS_gate-2",      gap=-2.0, symbols=_OOS_SYMS),
})

# --- transfer test: does the arm finding hold on the v7 DEEP entry? ---------
_DEEP_ENTRY = [
    {"type": "distance_from_high", "params": {"lookback_bars": 18, "min_pct_below": 12.0, "max_pct_below": 30.0, "hard_stop": True}},
    {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
]
def _deep(name, *, arm, trail=0.6, gap=0):
    return {**_V5_BASE, "display_name": name,
            "arm_trailing_stop_pct": arm, "trailing_stop_pct": trail,
            "trend_indicators": _gate(gap), "entry_indicators": _DEEP_ENTRY,
            "exit_indicators": [
                {"type": "rsi_overbought", "params": {"side": "long", "min_value": 59, "max_value": 30, "lookback_candles": None}},
                {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
            ]}
DIP_V5_OPT_VARIANTS.update({
    "t_deep_arm3.5": _deep("t_deep_arm3.5", arm=3.5),
    "t_deep_arm5":   _deep("t_deep_arm5",   arm=5.0),
    "t_deep_arm7":   _deep("t_deep_arm7",   arm=7.0),
    "t_deep_g2_arm7":_deep("t_deep_g2_arm7",arm=7.0, gap=-2.0),
})


# =============================================================================
# ROUND 4 RESULT — THE CHAMPION IS REFUTED. PROD WINS. + ROUND 5
# -----------------------------------------------------------------------------
# Out-of-sample, on the five symbols that were never part of any optimisation
# variant (BNB/XRP/DOGE/SEI/SUI):
#
#   variant              n     WR      avg      total     PF   worst
#   base_prod (LIVE)    39  82.1%   +1.78%   +69.6%    3.95   -8.24%   <- BEST
#   arm7                38  71.1%   +1.15%   +43.8%    1.74  -27.08%
#   gate-2              47  76.6%   +1.01%   +47.6%    1.88  -15.66%
#   gate-2_arm7         46  67.4%   +0.54%   +24.7%    1.28  -27.08%
#   gate-4_arm7         66  69.7%   -0.04%    -2.4%    0.98  -27.08%
#
# Every single "improvement" degrades the live config out of sample, and the
# combined champion is 3.3x worse. Pooled across all nine symbols:
#
#   base_prod    n=70  WR 87.1%  avg +2.13%  tot +148.8%  PF 5.63  worst  -8.24%
#   arm7         n=69  WR 81.2%  avg +2.23%  tot +153.7%  PF 3.27  worst -27.08%
#   gate-2       n=95  WR 82.1%  avg +1.64%  tot +155.8%  PF 3.37  worst -15.66%
#   gate-2_arm7  n=94  WR 77.7%  avg +1.80%  tot +169.3%  PF 2.67  worst -27.08%
#
# The alternatives buy a little more total return with roughly half the profit
# factor and a worst trade three times deeper. On risk-adjusted terms the
# LIVE CONFIG IS THE BEST OF EVERYTHING TESTED. No change is recommended.
#
# WHY THE IN-SAMPLE EVIDENCE WAS SO CONVINCING AND STILL WRONG — worth
# remembering, because it passed every guard used:
#   - the arm sweep was smooth and monotone,
#   - it had a clean INTERIOR optimum at 7 (not an edge),
#   - and the ranking held in both time-halves INDEPENDENTLY.
# All three, and it still failed on new symbols. TEMPORAL ROBUSTNESS IS NOT
# CROSS-SECTIONAL ROBUSTNESS. The mechanism is visible in the numbers: the four
# in-sample symbols produced only TWO losing trades in 31. The arm parameter
# controls how long winners are held, so on a near-loserless sample "wider is
# better" is nearly tautological. The held-out symbols had real losers, and
# there the wider arm turned an -8.24% worst case into -27.08%.
#   => Any parameter sweep on a >90% win-rate sample must be validated on a
#      DIFFERENT CROSS-SECTION, not just a different time period.
#
# TRANSFER TEST (arm sweep on the v7 DEEP entry, in-sample symbols) — also no:
#   arm 3.5 (prod): avg +1.49%  PF 2.00  tail  8.6%
#   arm 5.0       : avg +1.83%  PF 1.93  tail 12.7%
#   arm 7.0       : avg +2.33%  PF 1.98  tail 16.0%
#   Higher average, flat PF, and the tail doubles. The wider arm is not adding
#   edge anywhere — it is just taking more risk and being paid fairly for it.
#
# ROUND 5 runs the decision-relevant comparison directly on ALL NINE symbols
# (rather than pooling two runs post hoc), including the modest arm widenings
# that were never tested out of sample, in case a small step survives where
# arm 7 did not.
# =============================================================================

_ALL9 = ["SOL_USDC","ZEC_USDC","BTC_USDC","ETH_USDC","BNB_USDC","XRP_USDC","DOGE_USDC","SEI_USDC","SUI_USDC"]

def _v5f(name, *, arm=3.5, trail=0.6, gap=0):
    return {**_v(name, arm=arm, trail=trail, gap=gap), "symbols": _ALL9}

DIP_V5_OPT_VARIANTS.update({
    "f9_base_prod":   _v5f("f9_base_prod"),
    "f9_arm4":        _v5f("f9_arm4",  arm=4.0),
    "f9_arm4.5":      _v5f("f9_arm4.5",arm=4.5),
    "f9_arm5":        _v5f("f9_arm5",  arm=5.0),
    "f9_arm7":        _v5f("f9_arm7",  arm=7.0),
    "f9_arm3":        _v5f("f9_arm3",  arm=3.0),
    "f9_gate-1":      _v5f("f9_gate-1", gap=-1.0),
    "f9_gate-2":      _v5f("f9_gate-2", gap=-2.0),
    "f9_gate-2_arm4": _v5f("f9_gate-2_arm4", gap=-2.0, arm=4.0),
    "f9_trail1.5":    _v5f("f9_trail1.5", trail=1.5),
})


# =============================================================================
# ROUND 5 — FINAL. ALL NINE SYMBOLS. RECOMMENDATION: CHANGE NOTHING.
# -----------------------------------------------------------------------------
#   variant           n     WR     avg     total     PF   tail   worst  qtrs syms  top
#   f9_base_prod(LIVE)70  87.1%  +2.13%  +148.8%   5.63  2.9%  -8.24%   7/9  8/9  20%
#   f9_arm4           70  85.7%  +2.32%  +162.3%   5.59  2.9%  -8.24%   8/9  9/9  21%
#   f9_trail1.5       70  87.1%  +1.92%  +134.4%   5.18  2.9%  -8.24%   7/9  8/9  20%
#   f9_arm3           70  88.6%  +1.86%  +130.3%   5.07  2.9%  -8.24%   7/9  8/9  22%
#   f9_gate-1         81  85.2%  +1.85%  +150.2%   3.97  3.7% -16.00%   8/9  8/9  22%
#   f9_gate-2_arm4    95  81.1%  +1.80%  +171.1%   3.48  4.2% -15.66%   8/9  8/9  23%
#   f9_gate-2         95  82.1%  +1.64%  +155.8%   3.37  4.2% -15.66%   7/9  8/9  23%
#   f9_arm5           70  84.3%  +2.06%  +144.2%   3.31  4.3% -27.08%   8/9  9/9  21%
#   f9_arm7           69  81.2%  +2.23%  +153.7%   3.27  4.4% -27.08%   8/9  8/9  26%
#   f9_arm4.5         70  84.3%  +1.96%  +137.3%   3.20  4.3% -27.08%   7/9  9/9  20%
#
# arm 4.0 looks like a marginal win over the live 3.5: +0.19%/trade, +13pp
# total, 9/9 symbols instead of 8/9, 8/9 quarters instead of 7/9, better in
# BOTH halves, identical tail and worst case, PF unchanged (5.59 vs 5.63).
# IT IS STILL THE WRONG CHOICE, and the reason is the mechanism, not the stats.
#
# WHY: the entire difference between arm 4.0 (worst -8.24%) and arm 4.5 (worst
# -27.08%) is ONE TRADE — SUI 2026-05-23, which peaked somewhere between +4.0%
# and +4.5%. At arm 4.0 the trail armed and banked +3.76%; at arm 4.5 it never
# armed, the position fell through to the unstopped logical exit, and it closed
# at -27.08%. That single trade is -30.84pp of the -24.94pp total difference —
# the other 16 diverging trades net +5.9pp IN FAVOUR of the wider arm.
#
# So the arm's real job is: catch trades that peak modestly and then reverse.
# Every widening abandons another slice of the peak distribution to an exit
# that has no stop behind it. Each step is a bet that no trade peaks in the
# newly-abandoned band and then collapses. Over 2 years there was exactly one
# such trade and it happened to sit at 4.0-4.5%. Had it peaked at 4.6%, arm 4.0
# would have inherited the -27% too and would look identical to arm 4.5.
#
# arm 4.0's clean worst case is therefore a coin flip on one trade's peak, not
# a property of the setting. Moving 3.5 -> 4.0 buys 19bps/trade in exchange for
# standing next to a discontinuity whose position is unknowable in advance.
# Not worth it. STAY AT 3.5.
#
# Same verdict on the gate: -1% and -2% add trades but drop PF from 5.63 to
# 3.97/3.37 and push the worst case from -8.24% to -16%. The extra frequency is
# bought with tail risk, consistently.
#
# ---------------------------------------------------------------------------
# NET RESULT OF FIVE ROUNDS / ~60 VARIANTS: the live configuration
# (gate: price >= daily EMA50, arm 3.5, trail 0.6, exit RSI 55) is the best
# risk-adjusted setting of everything tested, on the full nine-symbol universe.
# Nothing here should be deployed. Three things were learned:
#   1. Michael's live TSL retune (3.5/0.6 from 4.0/2.0) was a real improvement.
#   2. The daily-EMA50 gate is correctly signed and correctly placed at 0.
#   3. Temporal robustness is not cross-sectional robustness — see round 4.
# =============================================================================


# =============================================================================
# ROUND 6 — the one live setting still unanswered: v7's EXIT RSI.
#
# The live 4hr_dip_v7_deep_dip_satellite uses exit RSI 59; the v5 family uses
# 55. Round 3 showed 59 and 65 are much worse than 55 ON THE V5 REVERSAL ENTRY
# (+1.32% / +1.24% vs +2.56%, and 59 was unstable across halves). That does not
# transfer automatically — the deep entry entered 12-30% below the 3-day high,
# a much more stretched position, so it may genuinely need a higher RSI to call
# the bounce done.
#
# Run on ALL NINE SYMBOLS directly (round 4's lesson), at the live arm/trail.
# Given round 4, treat any winner here with suspicion until it holds per-symbol
# and across both halves.
# =============================================================================

def _deep9(name, *, exit_rsi, arm=3.5, trail=0.6, gap=0, lookback=18):
    return {**_V5_BASE, "display_name": name, "symbols": _ALL9,
            "arm_trailing_stop_pct": arm, "trailing_stop_pct": trail,
            "trend_indicators": _gate(gap),
            "entry_indicators": [
                {"type": "distance_from_high", "params": {"lookback_bars": lookback, "min_pct_below": 12.0, "max_pct_below": 30.0, "hard_stop": True}},
                {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
            ],
            "exit_indicators": [
                {"type": "rsi_overbought", "params": {"side": "long", "min_value": exit_rsi}},
                {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
            ],
            "min_exit_indicators_required": 1}

DIP_V5_OPT_VARIANTS.update({
    "x_deep9_exit50": _deep9("x_deep9_exit50", exit_rsi=50),
    "x_deep9_exit55": _deep9("x_deep9_exit55", exit_rsi=55),
    "x_deep9_exit59": _deep9("x_deep9_exit59", exit_rsi=59),   # = LIVE
    "x_deep9_exit63": _deep9("x_deep9_exit63", exit_rsi=63),
    # and the 7d lookback at the live exit, for the lookback question on 9 syms
    "x_deep9_lb42_exit59": _deep9("x_deep9_lb42_exit59", exit_rsi=59, lookback=42),
})


# =============================================================================
# ROUND 6 RESULT — v7's live exit RSI 59 is FINE. No change.
#   deep entry, all 9 symbols, arm 3.5/0.6:
#     exit 50: n=158 avg +1.44% PF 2.21  q5/8
#     exit 55: n=156 avg +1.70% PF 2.43  q6/8   H1+1.67 H2+1.73
#     exit 59: n=155 avg +1.65% PF 2.27  q7/8   H1+1.45 H2+1.92   <- LIVE
#     exit 63: n=154 avg +1.86% PF 2.57  q7/8   H1+1.60 H2+2.20
#   Spread is ~20bps across a 13-point RSI range, non-monotonic, and 59 has the
#   best quarterly consistency. The v5-entry finding (55 >> 59) does NOT
#   transfer — on the deep entry the exit RSI barely matters, because the
#   trailing stop is doing the work. Leave it at 59.
#   Also confirmed: 3d lookback beats 7d on 9 symbols (avg +1.65% / PF 2.27 vs
#   +1.07% / PF 1.62), i.e. the live lookback choice is right.
#
# ROUND 7 — the user's actual question: is there a HIGHER-FREQUENCY satellite?
# The deep entry's depth threshold is the only untested frequency lever left.
# A prior 2yr sweep found min6 loses at every lookback and min15 is the
# highest-quality band, but min 8-10 with the CURRENT exit/trail on all NINE
# symbols was never run. Shallower = more trades, smaller average — exactly the
# shape asked for — so the question is where it stops clearing costs.
# =============================================================================

DIP_V5_OPT_VARIANTS.update({
    "y_deep9_min8":  _deep9("y_deep9_min8",  exit_rsi=59),
    "y_deep9_min9":  _deep9("y_deep9_min9",  exit_rsi=59),
    "y_deep9_min10": _deep9("y_deep9_min10", exit_rsi=59),
    "y_deep9_min15": _deep9("y_deep9_min15", exit_rsi=59),
})
for _n, _m in (("y_deep9_min8",8.0),("y_deep9_min9",9.0),("y_deep9_min10",10.0),("y_deep9_min15",15.0)):
    DIP_V5_OPT_VARIANTS[_n]["entry_indicators"] = [
        {"type": "distance_from_high", "params": {"lookback_bars": 18, "min_pct_below": _m, "max_pct_below": 30.0, "hard_stop": True}},
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
    ]


# =============================================================================
# ROUND 7 RESULT — NO VIABLE HIGHER-FREQUENCY SATELLITE. The depth ladder,
# 9 symbols, live exit 59 / arm 3.5 / trail 0.6:
#
#   min% below high    n    WR     avg    net    total    PF   tail   worst   qtrs
#     8              270  77.0%  +0.43% +0.34% +115.6%  1.20  13.3% -46.36%  4/9
#     9              239  80.8%  +0.57% +0.48% +135.8%  1.26  13.8% -44.83%  4/9
#    10              200  81.0%  +0.72% +0.63% +143.5%  1.35  14.0% -44.83%  5/9
#    12  = LIVE v7   155  83.9%  +1.65% +1.56% +255.9%  2.27   9.0% -24.73%  7/8
#    15               83  89.2%  +2.12% +2.03% +176.1%  2.97   7.2% -22.68%  7/8
#
# Going shallower than 12 collapses the edge: PF 2.27 -> 1.20-1.35, the tail
# jumps from 9% to 13-14%, the worst trade doubles to -46%, and quarterly
# consistency falls from 7/8 to 4/9. As a SATELLITE (marginal trades only,
# excluding those the live v7 already takes) it is worse still:
#     min8  marginal: n=206 avg +0.22% net +0.13% PF 1.10  H1 +0.83 H2 -0.38
#     min9  marginal: n=171 avg +0.22% net +0.13% PF 1.09  H1 +0.63 H2 -0.20
#     min10 marginal: n=116 avg +0.17% net +0.09% PF 1.07  H1 +0.78 H2 -0.45
# All three are ~breakeven after fees and NEGATIVE in the recent half, while
# carrying a -45% tail. Do not deploy.
#
# min 15 is the opposite trade-off — better quality (PF 2.97, 8/8 symbols) at
# half the frequency and a lower total return than min 12. The live min 12 sits
# at the total-return optimum, which is the right choice for the satellite role
# v7 already plays.
#
# ---------------------------------------------------------------------------
# THE GENERAL CONCLUSION FROM ROUNDS 2-7: IN THIS FAMILY, FREQUENCY AND EDGE
# ARE THE SAME DIAL. Three independent axes were pushed for more trades —
# the daily gate (0 -> -1/-2/-4/-7), the entry reversal strictness (jump 6 -> 4,
# oversold 35 -> 40), and the dip depth (12 -> 10/9/8) — and every one of them
# converted per-trade edge into trade count at close to a 1:1 rate, arriving at
# roughly PF 1.0-1.4 and a negative recent half. That is not a coincidence of
# one parameter; it is the shape of the strategy. The dip family's edge is
# INTRINSICALLY LOW-FREQUENCY.
#
# => Additional trade frequency has to come from a DIFFERENT strategy family,
#    not from loosening this one. The existing prod book already does this:
#    15m_tf_v9_atrcap070 / 15m_tf_v90_atrcap070_seidoge occupy the
#    high-frequency slot, 4hr_dip_v7 the middle, 4hr_dip_v5 the low-frequency
#    high-quality slot. There is no fourth rung to add inside the dip family.
# =============================================================================
