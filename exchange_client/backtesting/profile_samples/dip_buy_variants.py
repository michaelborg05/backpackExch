# =============================================================================
# DIP-BUY VARIANTS  (1d/4h dip-buy family, originating from Michael's manual
# SOL/ZEC/BTC/ETH trades: buy a 4h dip below EMA20 while the daily trend gate
# allows it, sell once price reclaims EMA20 and RSI recovers, with a trailing
# stop running alongside.)
#
# PRUNED 2026-08-19. This file previously held 12 variants covering the whole
# exploration history (dip_v1-v9 plus TSL sweeps). Everything without a
# surviving 2yr tick-validated result was removed to keep the runnable set
# focused; the removed configs and why they lost are recorded at the bottom
# under "REMOVED VARIANTS" so the negative results are not lost.
#
# The file now contains three groups:
#   1. PROD MIRRORS      — exact replicas of the two live profiles
#   2. VALIDATED REFS    — the tick-validated champions, kept as the yardstick
#   3. DAILY-GATE SWEEP  — new 2026-08-19, the point of this round
#
# ---------------------------------------------------------------------------
# WHY THE DAILY-GATE SWEEP EXISTS  (the HYPOTHESIS — see RESULT below, which
# contradicts it. Kept because the reasoning is sound and the failure mode is
# the lesson.)
# ---------------------------------------------------------------------------
# Every profile in this family gates on `price_vs_ema {ema:50, min_gap_pct:0}`
# against real 1D candles — "only buy the dip while price is still ABOVE its
# daily EMA50". A bar-outcome screen over 3,400 qualifying dip bars (2yr, 7
# symbols, outcome = trail 3.5/0.6 with a 30d cap, 1m path fills) suggested
# that gate is pointed the wrong way:
#
#   filter on the qualifying bar             n     mean   median   WR    <-5%
#   (no daily gate at all)                3400   -0.58%  +3.12%   78%   17.2%
#   PROD: price ABOVE daily EMA50          738   -0.25%  +3.13%   80%   14.8%
#   INVERSE: price >=9.5% BELOW D-EMA50   1020   +0.61%  +3.17%   85%   13.8%
#   (BTC >=3.78% below ITS daily EMA50)   1021   +1.44%  +3.16%   87%   10.9%
#
# The prod gate beat no gate and cut the tail, but the inverse looked like it
# captured about four times as much improvement. Note the distribution shape:
# the MEDIAN qualifying bar is fine (+3.12%); a 17% catastrophic tail is what
# drags the mean negative, so every gate here is really a tail filter.
#
# The screen also appeared to replicate, from the opposite direction, a result
# this project already had and discarded: a BTC cross-gate requiring BTC
# STRENGTH was tested and rejected because "dropped alt trades were BETTER than
# kept — alt dips during BTC weakness bounce harder". The BTC leg needs a
# cross-symbol indicator that does not exist yet, so it is NOT in this file;
# only the per-symbol daily-EMA50 leg was testable, and the sweep below tests
# it at both a 5% and a 9.5% threshold.
#
# Run:
#   DATABASE_URL=$DATABASE_URL_LOCAL python backtesting/run_profile_variants_backtest.py \
#       --set dip_buy --days 0-730 --price-source ticks --price-mode close
#
# ---------------------------------------------------------------------------
# RESULT OF THE SWEEP (2yr, 9 symbols, tick fills, 2026-08-19)
# ---------------------------------------------------------------------------
# THE SCREEN DID NOT TRANSFER. The prod ABOVE-EMA50 gate WINS in all three
# entry families. Paired A/B, only the gate differs:
#
#   v5 prod entry (TSL 3.5/0.6)     n    WR    avgPnL     PF   tail   worst  qtrs+
#     PROD gate (above D-EMA50)     31  93.6%   +2.56%  10.25   3.2%  -6.50%   7/7
#     no gate                      151  75.5%   +0.79%   1.55  11.3% -19.14%   5/9
#     >=5% below D-EMA50            94  68.1%   +0.15%   1.08  13.8% -19.14%   5/9
#     >=9.5% below D-EMA50          71  77.5%   +1.26%   2.07   9.9% -19.14%   7/8
#
#   v7 prod entry (3d deep)         n    WR    avgPnL     PF   tail   worst  qtrs+
#     PROD gate                     58  84.5%   +1.49%   2.00   8.6% -23.67%   5/8
#     no gate                      142  79.6%   +1.20%   1.76  10.6% -23.67%   5/8
#     >=5% below                    95  75.8%   +0.94%   1.58  11.6% -20.49%   5/8
#     >=9.5% below                  83  80.7%   +1.43%   2.04   9.6% -20.49%   6/8
#
#   v8 min12 entry (TSL 4/2): PROD +1.39% / PF 1.82 > below9 +0.94% / 1.51
#                             > no gate +0.81% / 1.42
#
# WHY THE BAR SCREEN MISLED: it scored every qualifying bar independently on ONE
# entry rule (price near the 7-day low + 4h RSI<=47 + below 4h EMA20) which
# fires ~246x/symbol-year. These profiles fire 2-8x/symbol-year on completely
# different triggers, with position and cooldown constraints the screen had no
# model of. A bar-outcome screen is a hypothesis generator, NOT a substitute
# for the portfolio run — treat any future screen result the same way.
#
# The inverse gate is not worthless: on the v7 deep entry, >=9.5% below scores
# about the same per trade (+1.43% vs +1.49%) on 43% MORE trades (83 vs 58) for
# a higher total (+119% vs +87%) and one more positive quarter. But it
# concentrates badly (top symbol 82% of PnL vs 50%, 3/4 symbols positive vs
# 4/4), so it is a worse risk shape, not a better profile.
#
# SECOND RESULT — MICHAEL'S TSL RETUNE IS CONFIRMED. dip_v5_prod (3.5/0.6)
# beats dip_v5_rsi_reversal_trail (4.0/2.0) on the same entries: +2.56% vs
# +2.36% per trade, PF 10.25 vs 4.57, tail 3.2% vs 6.3%, worst -6.50% vs
# -12.56%, 7/7 quarters vs 6/7. The live change was a real improvement, and
# it earlier looked risky by analogy to dip_v6's failed 1% trail — that
# analogy was wrong, as the arm width (3.5) is what makes it safe.
#
# CAVEAT: dip_v5_prod is only 31 trades over 2 years across 9 symbols (~15/yr).
# The quality is excellent but the frequency is very low, and n=31 limits how
# much confidence the PF 10.25 deserves. Raising frequency without losing the
# edge is the open question — see profile_samples/dip_v5_optimisation.py.
# =============================================================================

_DIP_BUY_BASE = {
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

    # Exit is a pure "logical level" reclaim, not a fixed %:
    #   stay in the trade while RSI<55 OR price<EMA20 (i.e. exit only once
    #   BOTH have flipped — RSI>=55 AND price has reclaimed EMA20).
    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_position_age_for_trend_check": 0,
    "exit_indicators": [
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
        {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
    ],
    "min_exit_indicators_required": 1,

    "use_trailing_stop": False,
    "take_profit_pct": 9999.0,   # effectively disabled — exit is via trend invalidation above
    "stop_loss_pct": 9999.0,     # hard SLs poison this family, see REMOVED VARIANTS
    "max_position_hours": 720,   # 30d safety timeout backstop

    "min_signal_confidence": 0.0,   # this family doesn't use the confidence-score gate
    "min_volume_ratio": 0.0,        # or the volume-ratio gate — pure indicator logic only

    "signal_cooldown_minutes": 1,
    # No max_open_positions_per_profile cap: within a single symbol's replay,
    # only one position can ever be open anyway (sequential in time), so this
    # key would only do something when run through a harness that pools it
    # ACROSS symbols (e.g. run_profile_variants_backtest.py's shared
    # ProfileOpenPositionCap) — which is not how this family was validated.
    # Do not set this to a small number here; it silently strangles 3 of 4
    # symbols rather than limiting per-symbol pyramiding.

    "symbols": ["SOL_USDC", "ZEC_USDC", "BTC_USDC", "ETH_USDC"],
}

# ── Daily trend gates ────────────────────────────────────────────────────────
# The live gate: price at or above its daily EMA50.
_GATE_PROD = [
    {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": 0, "hard_stop": True}},
]
# Inverse gates. price_extended_below_ema reads (max_gap_pct <= gap <= min_gap_pct),
# so min_gap_pct is the SHALLOW bound and max_gap_pct the DEEP one — i.e. this
# says "between N% and 40% BELOW the daily EMA50". The 40% floor keeps true
# collapses out rather than being an opinion about trend.
_GATE_BELOW5 = [
    {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -5.0, "max_gap_pct": -40.0, "hard_stop": True}},
]
_GATE_BELOW9 = [
    {"type": "price_extended_below_ema", "params": {"ema": 50, "min_gap_pct": -9.5, "max_gap_pct": -40.0, "hard_stop": True}},
]

# ── Entry patterns ───────────────────────────────────────────────────────────
# Requires RSI to have actually touched an oversold zone in the last 4 bars
# AND jumped back up >=6 points AND currently be >=35 — not just "RSI<40 right
# now". Found via a 2024-09 -> 2026-07 grid search after a manual review showed
# the plain rsi_oversold entry buying the FIRST dip signal while price kept
# falling for days.
_RSI_REVERSAL_ENTRY = [
    {"type": "rsi_reversal_momentum", "params": {
        "lookback_candles": 4, "oversold_threshold": 35, "current_min": 35,
        "min_jump": 6.0, "require_sustained": False, "sustained_rise_mode": "net",
        "hard_stop": True,
    }},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
]

# Deep-dip: price 12-30% below the rolling high. lookback 18 bars = 3 days,
# 42 bars = 7 days.
def _deep_entry(lookback_bars, min_pct_below=12.0):
    return [
        {"type": "distance_from_high", "params": {"lookback_bars": lookback_bars, "min_pct_below": min_pct_below, "max_pct_below": 30.0, "hard_stop": True}},
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
    ]

# prod raised the exit RSI leg from the family default 55 -> 59
_EXIT_59 = [
    {"type": "rsi_overbought", "params": {"side": "long", "min_value": 59, "max_value": 30, "lookback_candles": None}},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
]


DIP_BUY_VARIANTS = {

    # =========================================================================
    # 1. PROD MIRRORS — exact replicas of the two live profiles
    #    (prod_profiles.py, exported 2026-08-18). These are the baseline every
    #    gate experiment below is measured against. Both run TSL arm 3.5 /
    #    trail 0.6, which was retuned live from the research 4.0/2.0.
    # =========================================================================

    # = live "4hr_dip_v5_rsi_reversal_trail"
    "dip_v5_prod": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v5_prod",
        "trend_indicators": _GATE_PROD,
        "entry_indicators": _RSI_REVERSAL_ENTRY,
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 3.5,
        "trailing_stop_pct": 0.6,
        "take_profit_pct": 99.0,
        "stop_loss_pct": 99.0,
        "signal_cooldown_minutes": 1300,
    },

    # = live "4hr_dip_v7_deep_dip_satellite" (3-day lookback, exit RSI 59)
    "dip_v7_prod": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v7_prod",
        "trend_indicators": _GATE_PROD,
        "entry_indicators": _deep_entry(18),
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 3.5,
        "trailing_stop_pct": 0.6,
        "take_profit_pct": 99.0,
        "stop_loss_pct": 99.0,
        "signal_cooldown_minutes": 1300,
        "exit_indicators": _EXIT_59,
        "min_exit_indicators_required": 1,
    },

    # =========================================================================
    # 2. VALIDATED REFERENCES — kept because each has a real 2yr tick result.
    # =========================================================================

    # TICK-VALIDATED (2026-07-27), 7 symbols ex BNB/DOGE: candle n=54 avg +3.16%
    # PF 20.2x -> path1m n=55 avg +2.34% PF 6.51x, worst -12.56%, 6/6 quarters
    # positive — the only variant in the family with that consistency. The
    # research trail (4.0/2.0) rather than prod's 3.5/0.6; this pair is the
    # cleanest read on what the retune actually bought.
    "dip_v5_rsi_reversal_trail": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v5_rsi_reversal_trail",
        "trend_indicators": _GATE_PROD,
        "entry_indicators": _RSI_REVERSAL_ENTRY,
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 4.0,
        "trailing_stop_pct": 2.0,
    },

    # 7-day deep-dip baseline. 2yr tick: n=195, avg +1.45%, +283.7%, PF 2.16x —
    # the most fill-robust variant in the family. Kept as the lookback control
    # against the 3-day versions.
    "dip_v7_deep_dip_satellite": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v7_deep_dip_satellite",
        "trend_indicators": _GATE_PROD,
        "entry_indicators": _deep_entry(42),
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 4.0,
        "trailing_stop_pct": 2.0,
    },

    # 2yr tick sweep, 8 ex-BNB symbols: 178T, WR 83%, avg 1.83%, +325% total,
    # PF 2.53x, 8/8 symbols positive — best total return of the sweep.
    "dip_v8_3d_deep_dip_min12": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v8_3d_deep_dip_min12",
        "trend_indicators": _GATE_PROD,
        "entry_indicators": _deep_entry(18, 12.0),
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 4.0,
        "trailing_stop_pct": 2.0,
    },

    # Same sweep: 99T, WR 89%, avg 2.26%, +223%, PF 3.31x, 8/8 symbols — best
    # PF and best diversification of the sweep.
    "dip_v8_3d_deep_dip_min15": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v8_3d_deep_dip_min15",
        "trend_indicators": _GATE_PROD,
        "entry_indicators": _deep_entry(18, 15.0),
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 4.0,
        "trailing_stop_pct": 2.0,
    },

    # =========================================================================
    # 3. DAILY-GATE SWEEP (new 2026-08-19) — same entries and exits as the
    #    profile each one shadows, ONLY the daily trend gate changes. Any
    #    difference in the results is therefore attributable to the gate.
    #    Each prod profile gets: no gate / >=5% below D-EMA50 / >=9.5% below.
    # =========================================================================

    "dip_v5_prod_nogate": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v5_prod_nogate",
        "use_trend_filter": False,
        "trend_indicators": [],
        "min_indicators_required": 0,
        "entry_indicators": _RSI_REVERSAL_ENTRY,
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True, "arm_trailing_stop_pct": 3.5, "trailing_stop_pct": 0.6,
        "take_profit_pct": 99.0, "stop_loss_pct": 99.0, "signal_cooldown_minutes": 1300,
    },
    "dip_v5_prod_below5": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v5_prod_below5",
        "trend_indicators": _GATE_BELOW5,
        "entry_indicators": _RSI_REVERSAL_ENTRY,
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True, "arm_trailing_stop_pct": 3.5, "trailing_stop_pct": 0.6,
        "take_profit_pct": 99.0, "stop_loss_pct": 99.0, "signal_cooldown_minutes": 1300,
    },
    "dip_v5_prod_below9": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v5_prod_below9",
        "trend_indicators": _GATE_BELOW9,
        "entry_indicators": _RSI_REVERSAL_ENTRY,
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True, "arm_trailing_stop_pct": 3.5, "trailing_stop_pct": 0.6,
        "take_profit_pct": 99.0, "stop_loss_pct": 99.0, "signal_cooldown_minutes": 1300,
    },

    "dip_v7_prod_nogate": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v7_prod_nogate",
        "use_trend_filter": False,
        "trend_indicators": [],
        "min_indicators_required": 0,
        "entry_indicators": _deep_entry(18),
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True, "arm_trailing_stop_pct": 3.5, "trailing_stop_pct": 0.6,
        "take_profit_pct": 99.0, "stop_loss_pct": 99.0, "signal_cooldown_minutes": 1300,
        "exit_indicators": _EXIT_59, "min_exit_indicators_required": 1,
    },
    "dip_v7_prod_below5": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v7_prod_below5",
        "trend_indicators": _GATE_BELOW5,
        "entry_indicators": _deep_entry(18),
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True, "arm_trailing_stop_pct": 3.5, "trailing_stop_pct": 0.6,
        "take_profit_pct": 99.0, "stop_loss_pct": 99.0, "signal_cooldown_minutes": 1300,
        "exit_indicators": _EXIT_59, "min_exit_indicators_required": 1,
    },
    "dip_v7_prod_below9": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v7_prod_below9",
        "trend_indicators": _GATE_BELOW9,
        "entry_indicators": _deep_entry(18),
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True, "arm_trailing_stop_pct": 3.5, "trailing_stop_pct": 0.6,
        "take_profit_pct": 99.0, "stop_loss_pct": 99.0, "signal_cooldown_minutes": 1300,
        "exit_indicators": _EXIT_59, "min_exit_indicators_required": 1,
    },

    # The best-scoring validated entry (dip_v8 min12) also gets the sweep, so
    # the gate result is not read off the prod TSL alone.
    "dip_v8_min12_nogate": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v8_min12_nogate",
        "use_trend_filter": False,
        "trend_indicators": [],
        "min_indicators_required": 0,
        "entry_indicators": _deep_entry(18, 12.0),
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True, "arm_trailing_stop_pct": 4.0, "trailing_stop_pct": 2.0,
    },
    "dip_v8_min12_below9": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v8_min12_below9",
        "trend_indicators": _GATE_BELOW9,
        "entry_indicators": _deep_entry(18, 12.0),
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True, "arm_trailing_stop_pct": 4.0, "trailing_stop_pct": 2.0,
    },
}


# =============================================================================
# REMOVED VARIANTS (pruned 2026-08-19) — kept here so the negative results
# survive the deletion. All numbers are the 2yr figures recorded before removal.
#
#   dip_v1_rsi_ema          PF 1.57x, 118T — plain "RSI<40 & below EMA20".
#                           Superseded by v5's reversal filter after review
#                           showed it buying the FIRST dip while price kept
#                           falling for days. SOL slightly negative.
#   dip_v2_dist_high_7d     PF 1.37x, 156T — shallow 5-20% distance-from-high.
#                           Superseded by the deep (12-30%) band; depth is the
#                           dominant lever, min6 loses money at every lookback.
#   dip_v3_combined         PF 1.51x, 174T — v1 OR v2 via indicator groups.
#   dip_v3_combined_sl30    PF 1.32x, 174T — v3 plus a 30% catastrophic stop.
#                           Both dropped with their parents. The SL result is
#                           the useful part: hard stops POISON this family
#                           (a 12% stop scored PF 0.68 on a later replay of
#                           Michael's own entries) because they convert slow
#                           genuine recoveries into realised losses.
#   dip_v4_rsi_reversal     PF 4.88x, 30T — v5 without the trailing stop.
#                           Strictly dominated by v5 on every axis measured.
#   dip_v6_dist_high_trail  FAILS TICK VALIDATION. Candle +242%/PF 1.52x
#                           collapses to +110.6%/PF 1.22x under path1m fills
#                           and the 60d window flips negative. The shallow
#                           entry plus a tight 1% trail is a candle-mode
#                           artifact. Do not resurrect without a rebuilt exit.
#   dip_v7_..._satelliteTSL   arm 3.0 / trail 0.6  } superseded by the prod
#   dip_v7_..._satelliteTSL2  arm 2.0 / trail 0.6  } mirrors at arm 3.5. The
#                           finding they produced is worth keeping: THE ARM IS
#                           THE LEVER, NOT THE TRAIL. Keep the arm wide (3-4%)
#                           so the trail only acts after real profit; TSL2's
#                           weakness was arm=2, not trail=0.6.
#   dip_v9_majors           PF 3.34x, 42T on ETH/SOL/BNB only. A different
#                           symbol universe (BTC excluded — no edge there in
#                           any config), so it is not comparable in a shared
#                           run. Re-add if the majors thread is picked back up.
# =============================================================================
