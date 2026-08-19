# =============================================================================
# MANUAL-MIMIC DIP VARIANTS
# (reverse-engineered from Michael's discretionary buys in Backpack subaccount 1,
#  fills exported 2026-08-18, decision times taken from order-placement
#  timestamps rather than fill timestamps)
#
# SAMPLE: 14 distinct buy decisions with a known entry (2026-04-02 -> 2026-08-14)
# across SOL/ETH/BTC/ZEC, resolved into 21 FIFO round trips:
#   n=21  WR 85.7%  avgPnL +2.45%  $-weighted +2.34%  PF 7.0  median hold 4.2d
#   per symbol: SOL +3.11% (n=14), ZEC +3.27% (n=3), BTC +0.47% (n=1),
#               ETH -0.82% (n=3, one -5.23% 65-day bag)
# Sells before 2026-04-01 had no recorded buy and are excluded, as instructed.
#
# ---------------------------------------------------------------------------
# THE HEADLINE FINDING
# ---------------------------------------------------------------------------
# NEITHER live dip profile would have fired on a SINGLE one of the 14 buys.
# Measured gate-by-gate against the real entries:
#
#   gate (as configured in prod)                passes   avgPnL of the trades it
#                                               /14      would have let through
#   price > daily EMA50   (both profiles)         3      +1.57%   (WR 67%)
#     ...trades it BLOCKED                       11      +2.52%   (WR 91%)
#   distance_from_high <= -12%  (v7)              1      +0.47%
#     ...trades it BLOCKED                       13      +2.46%
#   rsi_reversal_momentum jump>=6 (v5)            0      —
#   FULL prod v7 (all gates)                      0      —
#   FULL prod v5 (all gates)                      0      —
#
# So the live profiles are not a stricter version of the manual strategy —
# they are a different strategy that happens to share the word "dip".
#
# ---------------------------------------------------------------------------
# WHAT THE MANUAL ENTRIES ACTUALLY LOOK LIKE  (quantiles over the 14 buys)
# ---------------------------------------------------------------------------
#                                   min     25%     50%     75%     max
#   4h RSI                        17.5    34.6    39.3    41.8    46.9
#   1h RSI                        27.2    31.5    39.3    47.7    53.9
#   price vs 4h EMA20 (%)         -7.6    -4.8    -2.6    -1.5    +0.6
#   price vs DAILY EMA50 (%)     -14.7   -11.2    -4.0    -2.2    +1.7
#   % below 7d high (4h bars)    -15.9   -13.5    -7.2    -6.2    -3.1
#   % ABOVE 7d low   (4h bars)    -4.7    +0.3    +0.9    +2.1    +5.8   <====
#
# The last row is the whole strategy and it is the one thing the existing
# indicator set could not express. Michael buys within ~1-2% of the 7-day LOW.
# distance_from_high cannot say this: a shallow 5% drift off the high and a
# full flush into the low both satisfy it equally. Hence the new
# `distance_from_low` indicator (cache/trend_cache.py + backtest_engine.py),
# which is the backbone of every variant below.
#
# Secondary, weaker regularities:
#   - 4h RSI was BELOW 47 at all 14 entries, but only 3 were below 35. The
#     "RSI < 35" premise behind the live v5 profile is simply not what he does.
#   - He buys while 4h RSI is still FALLING (in 9 of 14, the current 4h RSI IS
#     the 4-bar minimum). The confirmation, when there is one, comes from the
#     1h: median 1h RSI is +5.9 points off its 6-bar low. That is a much
#     gentler turn than v5's "4h RSI jumped >=6 off a <=35 trough", which
#     scored 0/14.
#   - Price below the 4h EMA20 in 13 of 14 (median -2.6%).
#   - Always in a real pullback: >=3.1% below the 7-day high in all 14.
#   - No volume condition (median volume_ratio 1.26, range 0.70-2.15).
#   - Bottom-picking accuracy: entries sit a median 3.1% above the lowest low
#     of the surrounding +/-3 days; median MAE after entry is only -3.0%.
#
# EXITS (16 sell decisions) are almost exactly the family's existing "logical
# level" exit, just a touch later: 4h RSI median 61 (family exit uses 55, prod
# v7 uses 59), price median +1.9% ABOVE the 4h EMA20, and price back to within
# 0.8% of the 3-day high. `_MANUAL_EXIT` below uses 60.
#
# ---------------------------------------------------------------------------
# RULE RECALL AGAINST THE 14 REAL BUYS (what these variants are tuned to)
# ---------------------------------------------------------------------------
#   near 7d low <=2%, 4h RSI<=47, below 4h EMA20                    10/14
#     + also >=3% below the 7d high                                 10/14
#     + require 1h RSI turn >= 3 points                              7/14
#     + prod's daily-EMA50 gate                                      1/14   <—
#   near 7d low <=4% (wider), rest the same                         13/14
#
# The one persistent miss is ZEC 2026-08-14 (+3.46%), bought 5.8% above the
# 7-day low and marginally ABOVE the 4h EMA20 — a momentum-ish entry that does
# not belong to this pattern.
#
# ---------------------------------------------------------------------------
# WHAT STILL NEEDS BACKTESTING (do not treat any of this as validated)
# ---------------------------------------------------------------------------
# Everything below is a HYPOTHESIS FIT TO 14 TRADES over a 4.5-month window
# that was broadly kind to dip buyers. The sample cannot distinguish skill
# from regime. Specifically unresolved:
#   1. Dropping the daily-EMA50 gate is what the manual record argues for, but
#      that gate exists because it "skips the worst SOL bear stretch entirely"
#      (2025Q1/2026Q1, see dip_buy_variants.py). The manual sample contains no
#      bear quarter at all. mdip_v3_daily_gate is the control that settles it.
#   2. Buying into a still-falling 4h RSI is exactly what the v5 reversal
#      filter was built to stop, after a review showed the naive version buying
#      the first dip while price fell for days. mdip_v2_1h_confirm is the
#      control for that.
#   3. n=1 for BTC, n=3 for ETH/ZEC. Per-symbol conclusions are not available.
#   4. The manual trades were ~100% maker fills at 0bps. These profiles must
#      clear the 8.76bps taker break-even (see memory: execution_economics)
#      or be run maker-first.
#
# Run with:
#   python backtesting/run_profile_variants_backtest.py --set manual_dip \
#          --days 0-730 --price-source ticks --price-mode close
#
# PREREQUISITE: the daily-gated variant (mdip_v3) needs 1D candles, and the
# local DB only holds 1D from 2026-04-20. Backfill first:
#   python Tools/run_candle_fetcher.py backfill --timeframes 1D --days 760
# =============================================================================

# Exit is the family's "logical level" reclaim, tuned to the observed sell
# behaviour: hold while 4h RSI < 60 OR price is still below the 4h EMA20; exit
# once BOTH have flipped. (Family default is 55, prod v7 uses 59, the manual
# sells median 61.)
_MANUAL_EXIT = [
    {"type": "rsi_overbought", "params": {"side": "long", "min_value": 60}},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
]

_MANUAL_BASE = {
    "strategy_type": "mean_reversion",
    "market_type": "SPOT",
    "entry_timeframe": "240",
    "exit_timeframe": "240",
    # NOTE: trend_timeframe is still declared because the engine reads it, but
    # every variant except mdip_v3_daily_gate runs a permissive trend gate —
    # deliberately, see the headline finding above.
    "trend_timeframe": "1D",

    "use_trend_filter": True,
    "use_entry_filter": True,

    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_position_age_for_trend_check": 0,
    "exit_indicators": _MANUAL_EXIT,
    "min_exit_indicators_required": 1,

    # Manual trades used no fixed TP/SL — every exit was discretionary. The
    # trailing stop is the one piece of risk control the discretionary record
    # does NOT justify on its own; it is inherited from dip_v5/v7 where it was
    # measured to help. 4.0/2.0 is used (the tick-validated width), NOT prod's
    # 3.5/0.6 — a 0.6% trail is in the same class as dip_v6's 1.0%, which
    # failed tick validation.
    "use_trailing_stop": True,
    "arm_trailing_stop_pct": 4.0,
    "trailing_stop_pct": 2.0,
    "take_profit_pct": 9999.0,
    "stop_loss_pct": 9999.0,
    "max_position_hours": 720,       # 30d timeout; longest real hold was 65d (the ETH bag)

    "min_signal_confidence": 0.0,
    "min_volume_ratio": 0.0,         # no volume condition in the manual record
    "signal_cooldown_minutes": 1300, # matches prod's ~1 trade/day/symbol ceiling

    "symbols": ["SOL_USDC", "ZEC_USDC", "BTC_USDC", "ETH_USDC"],
}

# Permissive trend gate: price within 25% below the daily EMA50. This is NOT
# the prod gate — it only excludes true collapse (the deepest manual entry was
# 14.7% below daily EMA50), while keeping the engine's trend-filter plumbing
# populated so `use_trend_filter` stays True.
_LOOSE_DAILY = [
    {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": -25, "hard_stop": True}},
]
# The prod gate, for the A/B control.
_PROD_DAILY = [
    {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": 0, "hard_stop": True}},
]

# The core pattern: at the bottom of a real pullback, RSI soft-oversold, under
# the 4h EMA20. max_pct_above 2.0 = "within 2% of the 7-day low"; min_pct_above
# -1.5 stops it catching an unlimited new low (pct_above goes negative there).
_NEAR_LOW_ENTRY = [
    {"type": "distance_from_low",  "params": {"lookback_bars": 42, "max_pct_above": 2.0, "min_pct_above": -1.5, "hard_stop": True}},
    {"type": "distance_from_high", "params": {"lookback_bars": 42, "min_pct_below": 3.0, "max_pct_below": 30.0, "hard_stop": True}},
    {"type": "rsi_overbought",     "params": {"side": "long", "min_value": 47, "hard_stop": True}},
    {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
]

MANUAL_DIP_VARIANTS = {

    # BASELINE — the pattern as measured, no daily-trend opinion.
    # Recall 10/14 on the real buys (avgPnL of the captured subset +2.23%).
    "mdip_v1_near_low": {
        **_MANUAL_BASE,
        "display_name": "mdip_v1_near_low",
        "trend_indicators": _LOOSE_DAILY,
        "min_indicators_required": 1,
        "entry_indicators": _NEAR_LOW_ENTRY,
        "min_entry_indicators_required": 4,
    },

    # Same entry plus a 1h RSI turn — the "selling has exhausted" confirmation
    # Michael appears to use in about half the trades. This is the honest
    # middle ground between "buy the falling knife" (v1) and prod v5's 4h
    # reversal filter, which caught 0/14.
    # Recall 7/14. Costs the four biggest SOL winners — which is exactly the
    # trade-off the backtest needs to price.
    "mdip_v2_1h_confirm": {
        **_MANUAL_BASE,
        "display_name": "mdip_v2_1h_confirm",
        "trend_indicators": _LOOSE_DAILY,
        "min_indicators_required": 1,
        "entry_timeframe": "60",     # the confirmation lives on the 1h
        "entry_indicators": [
            {"type": "distance_from_low",  "params": {"lookback_bars": 42, "max_pct_above": 2.0, "min_pct_above": -1.5, "hard_stop": True}},
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6, "oversold_threshold": 45, "current_min": 30,
                "min_jump": 3.0, "require_sustained": False, "sustained_rise_mode": "net",
                "hard_stop": True}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,
        # The 42-bar low window is ~1.75 days on the 1h, not 7 — deliberate:
        # this variant is meant to be a faster, more reactive read.
        #
        # exit_timeframe MUST follow the entry down to 60. Left at the base's
        # 240 it produced 57 trades with 60-minute holds on a 120d SOL run:
        # a 1h dip inside a 4h uptrend satisfied the 1h entry while the 4h
        # exit condition (RSI>60 AND price back over EMA20) was ALREADY true,
        # so every position was closed on the very next bar.
        "exit_timeframe": "60",
    },

    # A/B CONTROL — v1 entry, prod's "price > daily EMA50" gate bolted back on.
    # This is the single most important run in the set. It scored 1/14 against
    # the manual record; if it nonetheless wins over 2 years, the gate is
    # earning its keep in the bear quarters the manual sample never saw, and
    # the discretionary evidence is a regime artifact.
    "mdip_v3_daily_gate": {
        **_MANUAL_BASE,
        "display_name": "mdip_v3_daily_gate",
        "trend_indicators": _PROD_DAILY,
        "min_indicators_required": 1,
        "entry_indicators": _NEAR_LOW_ENTRY,
        "min_entry_indicators_required": 4,
    },

    # WIDER LOW BAND — within 4% of the 7-day low instead of 2%.
    # Recall 13/14 (the loosest rule that still captures nearly everything).
    # Expect meaningfully more trades and lower per-trade quality; the point of
    # the run is to find where the frequency/quality curve turns over.
    "mdip_v4_wide_low": {
        **_MANUAL_BASE,
        "display_name": "mdip_v4_wide_low",
        "trend_indicators": _LOOSE_DAILY,
        "min_indicators_required": 1,
        "entry_indicators": [
            {"type": "distance_from_low",  "params": {"lookback_bars": 42, "max_pct_above": 4.0, "min_pct_above": -1.5, "hard_stop": True}},
            {"type": "distance_from_high", "params": {"lookback_bars": 42, "min_pct_below": 3.0, "max_pct_below": 30.0, "hard_stop": True}},
            {"type": "rsi_overbought",     "params": {"side": "long", "min_value": 47, "hard_stop": True}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # STRICT BOTTOM — within 1% of the 7-day low and the low must have HELD
    # (min_pct_above 0 = no new lows). Lowest frequency, highest conviction;
    # tests whether the edge is in the precision of the bottom call or just in
    # "buy weakness". Blocks the 3 real entries that printed a new low —
    # including SOL 2026-06-02, the single best trade in the sample (+7.16%).
    "mdip_v5_strict_bottom": {
        **_MANUAL_BASE,
        "display_name": "mdip_v5_strict_bottom",
        "trend_indicators": _LOOSE_DAILY,
        "min_indicators_required": 1,
        "entry_indicators": [
            {"type": "distance_from_low",  "params": {"lookback_bars": 42, "max_pct_above": 1.0, "min_pct_above": 0.0, "hard_stop": True}},
            {"type": "distance_from_high", "params": {"lookback_bars": 42, "min_pct_below": 3.0, "max_pct_below": 30.0, "hard_stop": True}},
            {"type": "rsi_overbought",     "params": {"side": "long", "min_value": 47, "hard_stop": True}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # LONGER MEMORY — 10-day (60-bar) low window instead of 7-day. Michael's
    # entries score nearly identically on both windows (the 7d and 10d columns
    # differ for only one of the 14), so this is close to free; it should mostly
    # reduce trade count by rejecting bounces off a low that is only recent.
    "mdip_v6_10d_low": {
        **_MANUAL_BASE,
        "display_name": "mdip_v6_10d_low",
        "trend_indicators": _LOOSE_DAILY,
        "min_indicators_required": 1,
        "entry_indicators": [
            {"type": "distance_from_low",  "params": {"lookback_bars": 60, "max_pct_above": 2.0, "min_pct_above": -1.5, "hard_stop": True}},
            {"type": "distance_from_high", "params": {"lookback_bars": 60, "min_pct_below": 3.0, "max_pct_below": 30.0, "hard_stop": True}},
            {"type": "rsi_overbought",     "params": {"side": "long", "min_value": 47, "hard_stop": True}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 4,
    },

    # NO TRAILING STOP — pure logical-level exit, which is what the manual
    # trades actually did (median hold 4.2d, and several winners ran well past
    # a 2% giveback). Isolates how much of any result comes from the inherited
    # TSL rather than from the entry.
    "mdip_v7_no_trail": {
        **_MANUAL_BASE,
        "display_name": "mdip_v7_no_trail",
        "trend_indicators": _LOOSE_DAILY,
        "min_indicators_required": 1,
        "entry_indicators": _NEAR_LOW_ENTRY,
        "min_entry_indicators_required": 4,
        "use_trailing_stop": False,
    },

    # CATASTROPHIC BACKSTOP — v1 plus a wide 12% stop.
    # Motivated by the first smoke run: on SOL alone over 120 days, mdip_v1
    # took a single -18.9% trade (entered 2026-05-22 at 84.55 "near the 7-day
    # low", then the 7-day low kept falling for three weeks to 68.60) that
    # accounted for the entire -9.6% result across 8 trades. Without the daily
    # trend gate, "near the recent low" has no defence against a sustained
    # downtrend — the low simply keeps moving.
    # 12% (not dip_v3's 30%) because this family enters much closer to the
    # bottom, so a genuine setup should not be 12% underwater. Michael's real
    # entries had a median MAE of only -3.0%; the two that went past -12% were
    # his worst (ETH 2026-05-22, -27% MAE) and his best (SOL 2026-06-02, -20%
    # MAE then +7.16%) — so this stop is NOT free, and the run has to price it.
    "mdip_v8_sl12": {
        **_MANUAL_BASE,
        "display_name": "mdip_v8_sl12",
        "trend_indicators": _LOOSE_DAILY,
        "min_indicators_required": 1,
        "entry_indicators": _NEAR_LOW_ENTRY,
        "min_entry_indicators_required": 4,
        "stop_loss_pct": 12.0,
    },
}


# =============================================================================
# EXIT SWEEP (added after the first 2yr/9-symbol tick run, 2026-08-18)
#
# That run killed all eight entry variants above: every one negative over
# 2 years BEFORE fees, best PF 1.00 (mdip_v4_wide_low). Crucially the
# daily-EMA50 control did NOT rescue it — mdip_v3_daily_gate came in WORSE
# (PF 0.89, 4/9 quarters) than the ungated baseline, so the manual record's
# argument against that gate stands; the gate just wasn't the problem.
#
# The problem is the EXIT, and the split is stark. Across mdip_v1's 195 trades:
#
#   exit reason           n    WR     avgPnL   totalPnL    PF
#   trailing_stop        79   100%    +3.71%    +293.2%    inf
#   trend_invalidation  113    50%    -2.23%    -251.7%   0.38
#   stale_position        2     0%   -25.16%     -50.3%   0.00
#
# Every trade that exits on the trailing stop wins. The logical-level exit
# (RSI>=60 AND price reclaimed EMA20) gives back everything the trail earns,
# and the 30-day timeout realises two -25% bags. Win/loss asymmetry overall:
# 70% WR but +3.27% avg win vs -7.86% avg loss.
#
# This also explains the gap to the discretionary record. In Michael's OWN
# window (entries 2026-04-01 -> 2026-08-18) the mechanical v1 rule went
# -18.0%, PF 0.79, avg loss -10.53% — while he made +2.45%/trade on 14 buys
# with a median MAE of only -3.0% and a worst REALISED loss of -5.23%. Same
# entries, opposite result: his edge is in how he manages and exits, not in
# what he buys.
#
# These variants isolate that. All share mdip_v1's entry.
# =============================================================================

_MX_BASE = {
    **_MANUAL_BASE,
    "trend_indicators": _LOOSE_DAILY,
    "min_indicators_required": 1,
    "entry_indicators": _NEAR_LOW_ENTRY,
    "min_entry_indicators_required": 4,
}

MANUAL_DIP_VARIANTS.update({

    # Trailing stop ONLY — logical-level exit removed entirely. Directly tests
    # whether the trend_invalidation leg is pure cost.
    "mx_v1_trail_only": {
        **_MX_BASE,
        "display_name": "mx_v1_trail_only",
        "use_trend_invalidation_exit": False,
    },

    # Trail only, armed much earlier (+1.5%) and tighter (1.0%). Converts more
    # of the 113 invalidation exits into trail exits. CAUTION: a 1.0% trail is
    # the width that failed tick validation on dip_v6 — this is run in tick
    # mode precisely so that shows up.
    "mx_v2_trail_early": {
        **_MX_BASE,
        "display_name": "mx_v2_trail_early",
        "use_trend_invalidation_exit": False,
        "arm_trailing_stop_pct": 1.5,
        "trailing_stop_pct": 1.0,
    },

    # Trail only, armed at +2.5% / trail 1.5% — the middle setting.
    "mx_v3_trail_mid": {
        **_MX_BASE,
        "display_name": "mx_v3_trail_mid",
        "use_trend_invalidation_exit": False,
        "arm_trailing_stop_pct": 2.5,
        "trailing_stop_pct": 1.5,
    },

    # Trail only + a 90-day timeout instead of 30. Michael sat in a 65-day ETH
    # bag and got out at -5.23%; the 30d timeout force-closed two positions at
    # -25% avg. Tests whether patience with underwater positions is part of
    # the edge or just survivorship in a 14-trade sample.
    "mx_v4_trail_patient": {
        **_MX_BASE,
        "display_name": "mx_v4_trail_patient",
        "use_trend_invalidation_exit": False,
        "max_position_hours": 2160,
    },

    # Keep the logical exit but make it fire EARLIER (RSI 50, not 60), so
    # bounces are banked before they round-trip. The opposite hypothesis to
    # mx_v1: that the invalidation exit is not worthless, just too late.
    "mx_v5_early_logical": {
        **_MX_BASE,
        "display_name": "mx_v5_early_logical",
        "exit_indicators": [
            {"type": "rsi_overbought", "params": {"side": "long", "min_value": 50}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
        ],
    },

    # Trail only, on the wider entry band (mdip_v4's within-4%-of-low), which
    # was the best of the eight entry variants.
    "mx_v6_wide_trail_only": {
        **_MX_BASE,
        "display_name": "mx_v6_wide_trail_only",
        "entry_indicators": [
            {"type": "distance_from_low",  "params": {"lookback_bars": 42, "max_pct_above": 4.0, "min_pct_above": -1.5, "hard_stop": True}},
            {"type": "distance_from_high", "params": {"lookback_bars": 42, "min_pct_below": 3.0, "max_pct_below": 30.0, "hard_stop": True}},
            {"type": "rsi_overbought",     "params": {"side": "long", "min_value": 47, "hard_stop": True}},
            {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
        ],
        "use_trend_invalidation_exit": False,
    },
})


# =============================================================================
# RESULTS — 2yr / 9-symbol tick-mode runs, 2026-08-18. READ BEFORE REUSING ANY
# OF THE ABOVE. Full 14-variant table (--days 0-730 --price-source ticks):
#
#   variant                  T    WR    avgPnL   totPnL     PF
#   mx_v6_wide_trail_only  167   83%   +0.21%   +35.4%    1.07   <- only positive
#   mdip_v4_wide_low       244   70%   -0.01%    -1.5%    1.00
#   mdip_v7_no_trail       169   62%   -0.04%    -6.3%    0.99
#   mdip_v1_near_low       195   70%   -0.04%    -7.3%    0.98
#   mdip_v5_strict_bottom  141   71%   -0.12%   -16.5%    0.95
#   mx_v1_trail_only       142   82%   -0.32%   -45.7%    0.91
#   mdip_v3_daily_gate      89   64%   -0.29%   -25.7%    0.89
#   mdip_v2_1h_confirm     682   64%   -0.16%  -106.0%    0.89
#   mdip_v6_10d_low        146   68%   -0.36%   -52.4%    0.86
#   mx_v4_trail_patient     88   83%   -0.70%   -61.5%    0.84
#   mx_v5_early_logical    275   66%   -0.35%   -95.2%    0.81
#   mdip_v8_sl12           247   69%   -0.64%  -157.0%    0.78
#   mx_v3_trail_mid        182   87%   -0.58%  -106.5%    0.78
#   mx_v2_trail_early      235   90%   -0.61%  -144.3%    0.69
#
# VERDICT: the near-low entry has NO mechanical edge. 13 of 14 negative BEFORE
# fees, and the one positive is not real (below). Do not deploy any of these.
#
# Three specific things this run settled:
#
# 1. THE DAILY-EMA50 GATE IS NOT THE DIFFERENTIATOR. mdip_v3_daily_gate came
#    in WORSE than the ungated baseline (0.89 vs 0.98, 5/9 quarters). The
#    manual record's argument against that gate survives; it just wasn't what
#    was wrong. Point 1 of "WHAT STILL NEEDS BACKTESTING" above is resolved.
#
# 2. "EVERY TRAILING-STOP EXIT WINS" IS A SELECTION EFFECT, NOT A LEVER.
#    The trail arms at +4% and trails 2%, so a trail exit is >= +1.9% BY
#    CONSTRUCTION — of course they are all winners. The exit sweep was built
#    on the inference that routing more trades to the trail would therefore
#    help. It does the opposite: every trail-only variant lost, and the two
#    that armed the trail earliest were the WORST in the entire set
#    (mx_v2 0.69, mx_v3 0.78) despite 87-90% win rates. Tightening the trail
#    buys many small wins and pays for them with rare huge losses.
#
# 3. mx_v6's +35% IS A TIMEOUT ARTIFACT, NOT AN EDGE. Its exits split into
#    133 trail exits (100% WR, +555%) against 30 stale_position timeouts
#    (10% WR, -17.2% avg, -516%). The whole result is 133 capped winners
#    versus 30 bags that the 30-day clock happened to close before they got
#    worse. Supporting evidence that it is noise: 5/9 quarters positive,
#    2026Q1 alone -93%, worst trade -58%, ETH carries 75% of total PnL, SOL is
#    negative, and ex-best-symbol the 2-year total is +8.9%. At +21bps/trade
#    gross it nets ~+12bps after the 8.76bps taker break-even — a rounding
#    error on a return stream that is short a deep out-of-the-money put.
#
# WHAT THIS MEANS FOR THE MANUAL TRADES. Run mdip_v1 over Michael's OWN window
# (entries 2026-04-01 -> 2026-08-18) and it makes -18.0%, PF 0.79, avg loss
# -10.53%. Over those same months on those same symbols he made +2.45%/trade
# with median MAE -3.0% and a worst REALISED loss of -5.23%. Same entries,
# opposite result. The discretionary edge is in trade management — sizing into
# weakness, waiting out drawdowns that a 30-day clock force-closes, and never
# realising a -10% loss — none of which any profile in this file expresses.
# Chasing it with more entry-filter permutations is not the next move.
# =============================================================================


# =============================================================================
# POST-MORTEM (2026-08-18, after the exit sweep) — WHY THIS FAMILY FAILED, AND
# WHY THE "10/14 RECALL" EVIDENCE ABOVE WAS WORTHLESS. Read this before
# building another mimic profile from a discretionary trade log.
#
# 1. THE RULE IS SATISFIED 10.9% OF THE TIME. Scanning all 18,060 4h bars over
#    2 years on SOL/ETH/BTC/ZEC:
#
#      rule                                          bars   % bars  fires/yr/sym  recall
#      mdip_v1 near-low<=2% +RSI<=47 +<EMA20 +3%off   1971    10.9%       246     10/14
#      mdip_v4 same, near-low<=4%                     4096    22.7%       512     13/14
#      mdip_v5 near-low<=1%, low held                  743     4.1%        93     ~6/14
#      PROD v7 >=12% below 3d high + RSI<45           1092     6.0%       136      1/14
#      PROD v5 4h RSI reversal + <EMA20                688     3.8%        86      0/14
#
#    Michael made 14 buys in 4.5 months on these 4 symbols — about 9 per
#    symbol-year. The rule describes a STATE that is true a quarter of the
#    time, not an EVENT. Recall of 10/14 is what you get for free from a
#    condition that loose; it was never evidence. Precision is ~0.7%.
#    MEASURE FIRING FREQUENCY ALONGSIDE RECALL. A rule reverse-engineered from
#    N trades must be checked against how often it fires on the other N*100.
#
# 2. THE ENGINE WAS ALREADY IN A POSITION AT 14 OF HIS 14 BUYS. Because the
#    rolling low moves DOWN with price, "within 2% of the 7-day low" stays true
#    all the way through a decline. The engine takes the first qualifying bar
#    and is then locked in for days, so it systematically entered a median 6.0%
#    HIGHER than he did, and those trades averaged -6.04% against his +2.32%:
#
#      his 2026-06-02 SOL buy @75.11 (+7.16%) — engine in since 05-22 @84.40 (-18.72%)
#      his 2026-06-04 BTC buy @64127 (+0.47%) — engine in since 05-12 @80835 (-22.37%)
#      his 2026-05-22 ETH buy @2071 (-5.23%)  — engine in since 05-12 @2295  (-27.94%)
#
#    This is the SAME failure the plain rsi_oversold entry had (see
#    _RSI_REVERSAL_ENTRY in dip_buy_variants.py: "buying the FIRST dip signal
#    while price kept falling for days"). distance_from_low reproduced it with
#    a new indicator. A "wait for the low to hold" filter does not fix it
#    either — 6 of his 14 entries were at a low that was 0-1 bars old.
#
# 3. HIS EXITS ARE NOT THE EDGE EITHER. Holding his 14 real entries fixed and
#    swapping in each mechanical exit (1m path replay):
#
#      exit rule                          WR    avgPnL   totPnL     PF    worst
#      HIS ACTUAL EXITS                 85.7%   +2.32%  +32.47%   7.06   -5.23%
#      trail 3.5/0.6  (PROD)            92.9%   +2.83%  +39.62%  20.67   -2.01%  <- beats him
#      trail 4.0/2.0  (research)        85.7%   +2.10%  +29.39%   3.89   -8.17%
#      trail 2.0/1.0  (tight)          100.0%   +1.69%  +23.60%    inf   +1.11%
#      logical RSI>=55 + EMA20 reclaim  78.6%   +1.64%  +23.02%   2.95  -10.89%
#      logical RSI>=60 + EMA20 reclaim  78.6%   +0.42%   +5.83%   1.22  -16.71%
#      hard SL 12%                      64.3%   -1.16%  -16.22%   0.68  -12.00%
#
#    PROD's 3.5/0.6 trailing stop OUTPERFORMS his own discretionary exits on
#    his own entries. So the earlier "his edge is trade management" reading was
#    wrong — the edge is in WHICH of the ~1971 qualifying bars he chose, and
#    that is not recoverable from the indicator data.
#
#    Two corrections this table forces on the config above:
#      - `_MANUAL_EXIT` uses RSI 60 because his sells MEDIANED 61. That was a
#        mistake: 60 is far worse than the family's default 55 (PF 1.22 vs
#        2.95). Matching the median of the observed distribution is not the
#        same as finding the threshold that performs.
#      - The warning on `dip_v5_prod`/`dip_v7_prod` that a 0.6% trail is
#        "in the same width class as dip_v6's failed 1.0%" does not hold on
#        these entries — 3.5/0.6 was the single best exit tested, on 1m paths.
#        Width alone does not determine whether a trail whipsaws; where it arms
#        relative to the entry's typical bounce does.
#
# 4. TIMEOUTS WERE A RED HERRING. On his entries the logical exit resolves
#    identically at no-clock / 30d / 90d (all +5.83%) — every trade closed
#    within 23 days. The 30-day timeout only mattered for the mechanical
#    family's much worse entries.
#
# BOTTOM LINE: 14 trades over one favourable regime cannot identify a rule.
# The extracted features are necessary but roughly 27x too permissive, and the
# discriminating information is not in the candle data. Do not deploy anything
# in this file. Its value is the negative results and the method note in (1).
# =============================================================================


# =============================================================================
# EPISODE-LEVEL FEATURE HUNT (2026-08-19) — closes the manual-mimic thread and
# turns up one unrelated lead.
#
# Setup: every 4h bar over 2yr on the 7 path-covered symbols that satisfied the
# mdip_v1 entry rule = 3,400 bars, each labelled with its outcome under the best
# exit found (trail 3.5/0.6, 30d cap, 1m paths). Baseline: mean -0.58%, median
# +3.12%, WR 78%, share below -5% = 17.2%, P5 -21.1%. Note the shape — the
# MEDIAN bar is fine (+3.12%); a 17% catastrophic tail is what makes the mean
# negative. Screened ~360 feature/threshold combinations, requiring a positive
# mean in BOTH halves of the window.
#
# RESULT 1 — THE MIMIC THREAD IS CLOSED. Only 5 of 360 candidates survived, and
# the best of them keeps just 4 of Michael's 14 buys (held-out check). No
# episode-level feature in the daily/4h data reproduces his selection. Combined
# with the earlier finding that his within-episode timing is at the 44th
# percentile, the conclusion is that his edge is real (p=0.016 block bootstrap)
# but NOT expressible in this feature set. Stop here; do not add more variants.
#
# RESULT 2 — THE PROD DAILY-EMA50 GATE POINTS THE WRONG WAY, and the fix is to
# invert a gate this project already tested and discarded:
#
#   filter                              n     mean    median   WR    <-5%      P5
#   (none)                           3400   -0.58%   +3.12%   78%   17.2%  -21.1%
#   BTC <= -3.78% vs its daily EMA50 1021   +1.44%   +3.16%   87%   10.9%  -12.3%
#   symbol <= -9.49% vs daily EMA50  1020   +0.61%   +3.17%   85%   13.8%  -19.2%
#   PROD GATE: symbol ABOVE D-EMA50   738   -0.25%   +3.13%   80%   14.8%  -19.9%
#
#   CORRECTION (this line previously said the live gate is "worse than no
#   filter" — that misread the table). The prod gate at -0.25% is marginally
#   BETTER than no filter at all (-0.58%), and it does cut the tail (14.8% vs
#   17.2%). It is not harmful; it is just pointed the wrong way and leaves most
#   of the available edge on the table — the INVERSE gate more than doubles the
#   improvement (symbol below D-EMA50: +0.61%; BTC below its D-EMA50: +1.44%).
#   Dip entries do better when the market is already well below its daily
#   EMA50 than when it is above it.
#
#   Robustness of the BTC filter: 7/8 quarters positive (vs 5/9 unfiltered),
#   6/7 symbols positive, top symbol only 26% of PnL, and the 1,021 bars come
#   from 15 distinct episodes of which 11 are positive with the largest only
#   15% of the sample. Episode-level bootstrap of the +1.44% mean: 5-95pct
#   +0.10..+2.58, p(<=0) = 0.041. Borderline but real.
#
#   This REPLICATES an existing project finding from the opposite direction.
#   The dip family previously tested a BTC cross-gate requiring BTC STRENGTH,
#   rejected it because "dropped alt trades were BETTER than kept — alt dips
#   during BTC weakness bounce harder", and concluded "per-symbol daily gate
#   suffices". The screen says the stronger move is to INVERT that gate and
#   keep it, not to drop it.
#
#   NOT YET VALIDATED AS A STRATEGY. This is a bar-outcome screen: every
#   qualifying bar scored independently, no position/cooldown/exposure limits,
#   no fees. A real portfolio backtest will produce far fewer trades and could
#   easily wash the effect out. The engine also has no cross-symbol BTC-regime
#   indicator today, so this needs one built before it can be tested properly.
# =============================================================================


# =============================================================================
# ROUND 2 (2026-08-19) — TESTING "DON'T BUY THE FIRST CANDLE AT THE LEVEL"
#
# The post-mortem above diagnosed the family's failure precisely: a rolling-low
# reference stays satisfied ALL THE WAY DOWN a decline, so the engine took the
# first qualifying bar and was locked in a position at 14 of Michael's 14 buys,
# having entered a median 6.0% higher (those trades averaged -6.04% vs his
# +2.32%). That diagnosis was never actually TESTED — it was checked
# descriptively (6 of his 14 entries were at a low only 0-1 bars old) and set
# aside. This round tests it properly.
#
# New indicator param: distance_from_low.min_low_age_bars — require the window
# low to have been printed at least N bars ago, i.e. NO NEW LOW in the last N
# bars. That is a different rule from mdip_v5_strict_bottom's "price must be
# above the window low" (which was tested and failed at PF 0.95): a low can be
# 0 bars old with price still fractionally above it. On ties the MOST RECENT
# occurrence counts, so a re-touched low reads as young.
#
# On the 4h entry timeframe: 3 bars = 12h, 6 = 1 day, 12 = 2 days, 18 = 3 days.
#
# Run on ALL NINE SYMBOLS — the round-1 mdip family was fitted on four
# (SOL/ZEC/BTC/ETH), and the dip_v5 optimisation showed that a four-symbol fit
# does not survive out of sample. Do not repeat that mistake here.
#
# PRIOR EXPECTATION, recorded before the run so it cannot be rationalised
# afterwards: this probably does NOT rescue the family. Michael himself bought
# at a 0-1 bar old low in 6 of 14 cases, so the filter would have blocked
# nearly half his trades — it is not a faithful description of what he does.
# The reason to run it anyway is that it targets the exact mechanism that
# produced the -6.04% average, and the alternative is leaving a diagnosis
# untested.
# =============================================================================

_ALL9_MD = ["SOL_USDC","ZEC_USDC","BTC_USDC","ETH_USDC","BNB_USDC","XRP_USDC","DOGE_USDC","SEI_USDC","SUI_USDC"]

def _near_low_entry(age=0, max_above=2.0, min_above=-1.5):
    return [
        {"type": "distance_from_low",  "params": {"lookback_bars": 42, "max_pct_above": max_above,
                                                  "min_pct_above": min_above, "min_low_age_bars": age,
                                                  "hard_stop": True}},
        {"type": "distance_from_high", "params": {"lookback_bars": 42, "min_pct_below": 3.0, "max_pct_below": 30.0, "hard_stop": True}},
        {"type": "rsi_overbought",     "params": {"side": "long", "min_value": 47, "hard_stop": True}},
        {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
    ]

def _w(name, *, age=0, max_above=2.0, min_above=-1.5, gate="loose"):
    return {**_MANUAL_BASE, "display_name": name, "symbols": _ALL9_MD,
            "trend_indicators": _LOOSE_DAILY if gate == "loose" else _PROD_DAILY,
            "min_indicators_required": 1,
            "entry_indicators": _near_low_entry(age, max_above, min_above),
            "min_entry_indicators_required": 4}

MANUAL_DIP_VARIANTS.update({
    # the age sweep, everything else identical
    "w_age0":  _w("w_age0"),            # control = mdip_v1 on 9 symbols
    "w_age3":  _w("w_age3",  age=3),    # 12h without a new low
    "w_age6":  _w("w_age6",  age=6),    # 1 day
    "w_age12": _w("w_age12", age=12),   # 2 days
    "w_age18": _w("w_age18", age=18),   # 3 days

    # requiring age means price has had time to lift off the low, so pair the
    # stronger age filters with a wider "how far above the low" band too
    "w_age6_wide":  _w("w_age6_wide",  age=6,  max_above=4.0),
    "w_age12_wide": _w("w_age12_wide", age=12, max_above=4.0),

    # and with the PROD daily gate, which beat every alternative in the
    # dip_v5 work — the mdip family only ever ran the loose gate
    "w_age6_prodgate":  _w("w_age6_prodgate",  age=6,  gate="prod"),
    "w_age12_prodgate": _w("w_age12_prodgate", age=12, gate="prod"),
    "w_age0_prodgate":  _w("w_age0_prodgate",  gate="prod"),
})


# =============================================================================
# ROUND 2 RESULT — "DON'T BUY THE FIRST CANDLE" IS REFUTED, AND SO IS THE
# DIAGNOSIS BEHIND IT. (2yr, 9 symbols, tick fills)
#
#   age filter (bars w/o a new low)   n    WR     avg     net     PF   tail   worst
#     0  = control                  445  69.9%  -0.18%  -0.27%  0.93  15.1% -45.30%
#     3  (12h)                      427  69.6%  -0.19%  -0.28%  0.92  15.0% -45.30%
#     6  (1 day)                    416  70.4%  -0.11%  -0.20%  0.95  14.7% -45.30%
#    12  (2 days)                   375  69.1%  -0.34%  -0.42%  0.87  15.2% -45.30%
#    18  (3 days)                   337  68.8%  -0.50%  -0.59%  0.82  16.3% -45.30%
#   + wider band above the low: no better (PF 0.93-0.95)
#   + the PROD daily gate:      WORSE (PF 0.70-0.76, and only 1-2/9 symbols
#                               positive) — the gate that wins on the v5
#                               reversal entry actively hurts this one.
#
# Every setting negative, non-monotonic, no threshold helps. H1 positive and
# H2 negative throughout, so the family also degrades badly in the recent year.
#
# THE DECISIVE DETAIL — THE WORST TRADE IS IDENTICAL AT EVERY AGE SETTING:
#   SUI_USDC, entry 2026-01-15 20:00 @ 1.7809 -> -45.30%, in ALL of age 0, 6,
#   12 and 18. Trades worse than -20%: 15 at age 0, and still 12 at age 18 —
#   the filter removes 24% of trades and only 20% of the disasters.
#
# So the catastrophic losses are NOT first-candle entries. They are entries at
# lows that had ALREADY HELD FOR DAYS and then broke. That refutes the
# mechanism in the post-mortem above: the engine did not underperform Michael
# because it bought the first bar at the level. In a sustained decline EVERY
# bar looks like a held low right up until it is not, so "wait for the low to
# hold" carries no information about whether it will keep holding. There is no
# version of this filter that separates the two cases, because on the data
# available they are not distinguishable at the time of entry.
#
# This closes the manual-mimic thread on evidence rather than on judgement.
# The `distance_from_low` indicator and its `min_low_age_bars` parameter remain
# in both engines — they are correct and cheap, and may be useful elsewhere —
# but nothing in this file should be deployed.
# =============================================================================
