# =============================================================================
# DIP-BUY VARIANTS  (originating from Michael's manual SOL/ZEC/BTC/ETH trades —
# reviewed real fills, found a consistent discretionary pattern: buy a 4h RSI
# dip below EMA20/50 while the daily trend is still intact, sell once price
# reclaims EMA20 and RSI recovers. No fixed TP — exit is purely the "logical
# level" reclaim, matching how the real trades were actually managed.)
#
# The daily regime gate runs on real "1D" candles (fetched natively from
# Binance, see services/candle_fetcher.py TF_TO_BINANCE/TF_MINUTES — added to
# candle_fetcher_timeframes and backfilled 2026-07) via the existing
# price_vs_ema indicator — no custom resampling code. An earlier version of
# this gate derived a pseudo-daily bar from the 4h candle cache
# (higher_tf_trend, since removed): it worked, but needed 300 cached 4h bars
# per symbol which the live cache warmup (WARMUP_ENTRIES=15) can't provide,
# so the gate would silently no-op for ~47 days after every service restart —
# and this app auto-deploys on every merge to main. Real 1D data sidesteps
# that entirely: TrendCache.get(symbol, "1D") returns an already-mature,
# continuously-persisted EMA50 immediately, same as any other timeframe.
#
# distance_from_high (added alongside higher_tf_trend, still in use) stays on
# "240" (4h) — it deliberately wants intraday resolution for a 7-10 day
# window, not daily bars, so it's unaffected by the 1D change. It still needs
# more cached history (lookback_bars, up to 60) than WARMUP_ENTRIES=15
# provides, so it has a smaller residual restart gap (~4.5 days to rebuild
# organically) — not yet solved, much less severe than the daily gate's was.
#
# Backtested 2024-09-01 -> 2026-07-26, SOL/ZEC/BTC/ETH _USDC, entry_timeframe
# = "240" (4h), price_mode="close", no fees/slippage modeled. Per-variant PF
# numbers below are re-verified against real 1D data (2026-07-26) — and it's
# not just a wash vs. the old higher_tf_trend resample gate, it's meaningfully
# better across the board (e.g. dip_v1's BTC leg flips from a losing 0.77x to
# a solid 1.34x). The resample approximation was noisier than expected —
# _candle_history only appends on a "significant indicator change," so the
# bucketed daily bars had occasional missing candles feeding into the EMA.
# Real calendar-aligned, continuously-fetched daily data doesn't have that
# problem.
#
# Other findings (see conversation history for full detail):
#   - Ungated entry (no daily filter): PF 1.16x, 243 trades, +98.2% total.
#   - Daily-EMA50 gate roughly doubles avg PnL/trade and cuts trade count
#     ~40-50%, at the cost of skipping the worst SOL bear-market stretch
#     entirely (2025Q1/2026Q1) rather than trying to trade through it.
#   - distance_from_high needs a SHORT lookback (7-10 days) and a capped upper
#     bound (~20% max below high). The original 30-day/20% version looked
#     great in aggregate (PF 2.26x) but was a ZEC concentration artifact (69%
#     of trades, 83% of PnL from one symbol) — do not use that config.
#   - Combining both entry patterns (RSI/EMA dip OR distance-from-high dip,
#     via entry_indicator_groups, either group passing = entry) beats either
#     alone: best PF, best avg PnL, most total return, and profitable on
#     3 of 4 symbols individually. BTC is the one weak spot (PF ~0.8x) across
#     every variant that includes the RSI/EMA leg — worth persisted attention,
#     not yet solved.
#   - A stop-loss only helps the *ungated* entry (which catches real falling
#     knives); on the daily-gated entry a tight/medium stop (10-20%) cuts
#     genuine slow recoveries short and hurts PF. A wide 30% backstop costs
#     almost nothing (PF 1.39x -> 1.33x) and caps true tail risk — recommended
#     if going live with real capital, skippable for shadow/paper testing.
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

    # Exit is pure "logical level" reclaim, not a fixed %:
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
    "stop_loss_pct": 9999.0,     # effectively disabled — see *_sl30 variants for a real backstop
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

_RSI_EMA_ENTRY = [
    {"type": "rsi_oversold", "params": {"max_value": 40, "require_rising": False, "hard_stop": True}},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
]

_DIST_HIGH_ENTRY = [
    {"type": "distance_from_high", "params": {"lookback_bars": 42, "min_pct_below": 5.0, "max_pct_below": 20.0, "hard_stop": True}},
    {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
]

# Requires RSI to have actually touched an oversold zone in the last 4 bars
# AND jumped back up >=6 points AND currently be >=35 — not just "RSI<40 right
# now". Found via a 2024-09 -> 2026-07 grid search after a manual review of
# 30 recent days showed the plain rsi_oversold entry buying the FIRST dip
# signal while price kept falling for days afterward (e.g. ZEC bought at
# 531.86/514.22 on the way down to its actual 478 low, which is where Michael's
# real trade bought and won). oversold_threshold=35 was deliberately chosen
# over deeper values (25/30): those score even better per-trade but only
# produce 5-19 trades over 2yr (too rare to trust); 35 gives 30-48 trades at
# comparable-or-better quality.
_RSI_REVERSAL_ENTRY = [
    {"type": "rsi_reversal_momentum", "params": {
        "lookback_candles": 4, "oversold_threshold": 35, "current_min": 35,
        "min_jump": 6.0, "require_sustained": False, "sustained_rise_mode": "net",
        "hard_stop": True,
    }},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
]

DIP_BUY_VARIANTS = {

    # PF=1.57x | 118T | WR=62% | AvgPnL=+1.15% | TotalPnL=+135.5%
    # RSI(4h)<40 & price<EMA20(4h), daily-EMA50 gated (real 1D data).
    # SOL slightly negative (0.97x); BTC/ZEC/ETH all solidly positive.
    "dip_v1_rsi_ema": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v1_rsi_ema",
        "entry_indicators": _RSI_EMA_ENTRY,
        "min_entry_indicators_required": 2,
    },

    # PF=1.37x | 156T | WR=71% | AvgPnL=+0.66% | TotalPnL=+103.2%
    # Price 5-20% below the 7-day high, RSI<45, daily-EMA50 gated (real 1D
    # data). Positive on all 4 symbols individually (1.27x-1.69x) — broader
    # than v1.
    "dip_v2_dist_high_7d": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v2_dist_high_7d",
        "entry_indicators": _DIST_HIGH_ENTRY,
        "min_entry_indicators_required": 2,
    },

    # PF=1.51x | 174T | WR=70% | AvgPnL=+0.95% | TotalPnL=+166.0% (real 1D data)
    # RECOMMENDED — either entry pattern fires (OR across groups, AND within
    # each). Best risk-adjusted return of the family, all 4 symbols positive
    # individually. BTC is still the relative laggard (1.20x vs 1.34-1.68x for
    # the others) but no longer negative like it was under the resample gate.
    "dip_v3_combined": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v3_combined",
        "entry_indicators": [
            {**_RSI_EMA_ENTRY[0], "indicator_group": "rsi_ema"},
            {**_RSI_EMA_ENTRY[1], "indicator_group": "rsi_ema"},
            {**_DIST_HIGH_ENTRY[0], "indicator_group": "dist_high"},
            {**_DIST_HIGH_ENTRY[1], "indicator_group": "dist_high"},
        ],
        "entry_indicator_groups": {
            "rsi_ema":   {"require_all": True, "hard_stop": False},
            "dist_high": {"require_all": True, "hard_stop": False},
        },
        "min_entry_indicators_required": 1,   # at least one of the two groups
    },

    # PF=1.32x | 174T | WR=69% | AvgPnL=+0.68% | TotalPnL=+117.9% (real 1D data)
    # Same as dip_v3_combined plus a 30% catastrophic-only stop. Costs a real
    # chunk of ZEC's upside (its avg PnL roughly halves) but caps tail risk —
    # use this one over v3 if trading real capital; v3 is fine for
    # shadow/paper testing.
    "dip_v3_combined_sl30": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v3_combined_sl30",
        "entry_indicators": [
            {**_RSI_EMA_ENTRY[0], "indicator_group": "rsi_ema"},
            {**_RSI_EMA_ENTRY[1], "indicator_group": "rsi_ema"},
            {**_DIST_HIGH_ENTRY[0], "indicator_group": "dist_high"},
            {**_DIST_HIGH_ENTRY[1], "indicator_group": "dist_high"},
        ],
        "entry_indicator_groups": {
            "rsi_ema":   {"require_all": True, "hard_stop": False},
            "dist_high": {"require_all": True, "hard_stop": False},
        },
        "min_entry_indicators_required": 1,
        "stop_loss_pct": 30.0,
    },

    # PF=4.88x | 30T | WR=90% | AvgPnL=+2.58% | TotalPnL=+77.3% (real 1D data)
    # Swaps the rsi_oversold leg for rsi_reversal_momentum (see comment above
    # _RSI_REVERSAL_ENTRY). Same daily-EMA50 gate and logical exit as v1.
    # Massive PF jump over v1's 1.57x on a smaller, higher-conviction trade
    # count — but see dip_v5 below, which is a strict improvement on this.
    "dip_v4_rsi_reversal": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v4_rsi_reversal",
        "entry_indicators": _RSI_REVERSAL_ENTRY,
        "min_entry_indicators_required": 2,
    },

    # PF=10.88x | 30T | WR=93% | AvgPnL=+2.79% | TotalPnL=+83.8% (real 1D data)
    # RECOMMENDED — dip_v4 plus a trailing stop (arm at +4%, trail 2% below
    # peak) running ALONGSIDE the logical exit (whichever fires first). Added
    # after reviewing real charts showed some bounces reverse into losses
    # before ever satisfying the logical exit's RSI>=55 + EMA20-reclaim
    # condition simultaneously — e.g. a SOL trade that peaked +4.72% then fell
    # to -11.43%, an ETH trade that peaked +1.67% then fell to -6.91%, neither
    # protected because the bounce never got the exit legs to trigger at once.
    # This is a strict improvement over dip_v4 on every axis measured: same
    # trade count, higher avg/total PnL, ~2.2x better PF, worst trade capped
    # at -6.91% instead of -11.43%. Also the only variant in this whole family
    # with 6/6 positive quarters. BTC is the single biggest per-symbol
    # contributor here (14 of 30 trades, +23.7%) — a first for this family,
    # every prior variant either excluded BTC or had it as the weak spot.
    #
    # TICK-VALIDATED (2026-07-27): full-2yr replay on the backfilled 1m price
    # paths (--tick-source path1m), 7-symbol universe ex BNB/DOGE:
    # candle n=54 avg +3.16% PF 20.2x  ->  path1m n=55 avg +2.34% PF 6.51x,
    # worst -6.91% -> -12.56%, still 6/6 quarters positive. The edge is real
    # under realistic intra-candle fills; the candle numbers just flatter it.
    # Budget expectations off the tick numbers, not the candle ones.
    "dip_v5_rsi_reversal_trail": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v5_rsi_reversal_trail",
        "entry_indicators": _RSI_REVERSAL_ENTRY,
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 4.0,
        "trailing_stop_pct": 2.0,
    },

    # PF=1.71x | 215T | WR=82% | AvgPnL=+0.79% | TotalPnL=+169.5% (real 1D data)
    # dip_v2's distance-from-high entry plus a TIGHT trailing stop (arm +2%,
    # trail 1% — half the width of v5's, because v2's higher-frequency shallower
    # entries produce smaller bounces worth banking early). Highest total
    # return in the family and positive across 90/180/365d windows where the
    # un-trailed v2 was negative. CAVEATS vs v5: only 5/8 quarters positive
    # (2025Q1 -22.3%, 2026Q1 -15.0% drawdown quarters) and ZEC carries ~56% of
    # total PnL — a lumpier, more concentrated return stream than v5's 6/6
    # quarters. Different risk shape, not a strict upgrade: v5 = low frequency
    # + smooth; v6 = high frequency + bigger total + rougher ride.
    # (Same trail on dip_v1 was tested and NOT added: it helps v1's bad
    # near-term windows but clips its 365d winners — no config was cleanly
    # better, because v1's problem is entries that never go into profit at all.)
    #
    # WARNING — FAILS TICK VALIDATION (2026-07-27): on the backfilled 1m price
    # paths the tight 1% trail gets whipsawed by intra-candle noise the candle
    # model never sees. Full-2yr 7-symbol run: candle +242%/PF 1.52x collapses
    # to +110.6%/PF 1.22x (avg +0.64% -> +0.27%/trade) under path1m fills, and
    # the 60d webhook-tick window outright flips negative. DO NOT DEPLOY as-is
    # — kept for reference; would need a rebuilt exit (wider trail, or a
    # bar-close-evaluated trail) to be live-viable.
    "dip_v6_dist_high_trail": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v6_dist_high_trail",
        "entry_indicators": _DIST_HIGH_ENTRY,
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 2.0,
        "trailing_stop_pct": 1.0,
    },

    # PF=2.17x | 181T | WR=77% | AvgPnL=+1.86% | TotalPnL=+336.7% (candle, 2yr, 7 syms)
    # TICK-VALIDATED: path1m fills barely move it — n=195, avg +1.45%, +283.7%,
    # PF 2.16x. The most fill-robust variant in the family (wide entries + wide
    # trail don't care about intra-candle noise).
    #
    # The "deep dip" satellite: price 12-30% below the 7-day high (vs v2/v6's
    # 5-20%) + RSI<45, same daily-EMA50 gate, logical exit + TSL 4/2 (v5's wide
    # trail, NOT v6's tight one). Higher frequency than v5 (~90/yr vs ~27/yr
    # across 7 symbols), lower per-trade quality, much deeper worst case
    # (-32.3% candle / -26.1% tick) — run SMALLER size than v5, never larger:
    # 2x-sizing this was explicitly tested and rejected (same return as 1x,
    # double the drawdown).
    #
    # Overlap with v5 (measured, 2yr/7syms): entries NEVER share a bar (deep
    # enters early on price depth, v5 enters later on RSI-reversal
    # confirmation), but 22% of deep holds have a concurrent same-symbol v5
    # hold (69% of v5 trades sit inside a deep hold). Running both in parallel
    # therefore doubles same-symbol exposure ~20 times/yr unless the profiles
    # share a risk_group with max_positions_per_symbol=1. Note the overlapping
    # subset is deep's BEST cohort (PF 3.35x vs 1.99x ex-overlap) — allowing
    # the double-up is a defensible aggressive setting, deduping is the
    # conservative default. Portfolio sim (v5 + deep@1x, K=3 slots): +155%/2yr,
    # realized maxDD -18% vs v5-alone +72%/-2.2%.
    "dip_v7_deep_dip_satellite": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v7_deep_dip_satellite",
        "entry_indicators": [
            {"type": "distance_from_high", "params": {"lookback_bars": 42, "min_pct_below": 12.0, "max_pct_below": 30.0, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 4.0,
        "trailing_stop_pct": 2.0,
    },
    "dip_v7_deep_dip_satelliteTSL": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v7_deep_dip_satelliteTSL",
        "entry_indicators": [
            {"type": "distance_from_high", "params": {"lookback_bars": 42, "min_pct_below": 12.0, "max_pct_below": 30.0, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 3.0,
        "trailing_stop_pct": 0.6,
    },
    "dip_v7_deep_dip_satelliteTSL2": {
        **_DIP_BUY_BASE,
        "display_name": "dip_v7_deep_dip_satelliteTSL2",
        "entry_indicators": [
            {"type": "distance_from_high", "params": {"lookback_bars": 42, "min_pct_below": 12.0, "max_pct_below": 30.0, "hard_stop": True}},
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 2,
        "use_trailing_stop": True,
        "arm_trailing_stop_pct": 2.0,
        "trailing_stop_pct": 0.6,
    },
}
