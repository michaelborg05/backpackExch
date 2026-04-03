# =============================================================================
# PROFILE3 VARIANTS V3 — post-mortem on why V2 variants still missed
# =============================================================================
#
# EXACT FAILURE SEQUENCE FOR EACH SYMBOL (Feb 24 recovery):
#
# ─── SOL ────────────────────────────────────────────────────────────────────
# The 4h trend filter finally cleared ~20:03 Feb24 (RSI 29→39, jump 6.4).
# At that point the 60m entry filter ran. Problem: the 60m bounce was FAST.
# By the time the 4h confirmed, 60m had already ripped from RSI 33 → 54-59
# and price had pushed through the 60m BB upper band.
#
# Timeline of the missed window:
#   14:03  RSI=32.6  pct_b=0.23  vol=2.03  ← BEST ENTRY, 4h not confirmed yet
#   15:03  RSI=37.9  pct_b=0.36  vol=1.87
#   16:03  RSI=44.3  pct_b=0.53  vol=1.21
#   17:03  RSI=53.9  pct_b=0.86  vol=2.23  ← 4h trend first clears here
#   18:03  RSI=52.1  pct_b=0.82  ← still okay on BB
#   19:03  RSI=54.3  pct_b=0.90  ← near BB top
#   20:03  RSI=56.1  pct_b=0.94  ← near BB top
#   21:03  RSI=58.9  pct_b=1.02  ← ABOVE BB upper → hard stop blocked entry
#
# The 4h lookback_candles=5 only covers 20h. The SOL crash was at 02:03 Feb23
# (~39 hours before the 21:03 Feb24 eval). With lookback_candles=5 on 60m,
# the rsi_reversal_momentum on 60m only looks at the last 5 hours — it never
# sees the original oversold event. When increased to 10 candles it passes
# but by then pct_b > 1.0 → BB hard stop fires.
#
# Root problem: 60m BB upper hard stop (pct_b > 0.85) blocks entry throughout
# the later recovery. The good entry window (pct_b 0.2–0.5, RSI 32–44) was
# BEFORE the 4h trend filter confirmed. After 4h confirmed, price had already
# moved up through the band.
#
# ─── ETH ────────────────────────────────────────────────────────────────────
# ETH fired successfully. The 60m bounce was slower (more gradual) so the
# entry window lined up with the 4h confirmation. pct_b peaked at 0.84–0.90
# (under the 0.85 hard stop threshold) during the entry window.
#
# ─── HYPE ───────────────────────────────────────────────────────────────────
# 60m BB upper breached at 15:03 (pct_b=1.03) — within 1 candle of the 4h
# trend possibly clearing. Then briefly came back down (0.86 at 18:03) but
# RSI was already 52-53 (not oversold on lookback). Entry filter rsi_reversal
# never found an oversold candle in the recent 5-10 hour window.
#
# ─── SUI ────────────────────────────────────────────────────────────────────
# SUI actually had the cleanest recovery — RSI stayed in 40-50 range, pct_b
# 0.35–0.65 throughout. SUI's failure is upstream: the 4h trend filter.
# The 4h rsi_reversal hard stop was blocking because the jump criterion wasn't
# met (gradual recovery on 4h). SUI's 60m would have been fine if 4h passed.
#
# ═══════════════════════════════════════════════════════════════════════════
# CORE STRUCTURAL PROBLEM:
# The 4h trend filter and 60m entry filter are checking DIFFERENT time events.
# The 4h confirms recovery ~12-20 hours after the crash. By then, the 60m
# price action has already moved — sometimes far enough to trigger BB stops.
#
# Solutions:
#   A) Remove BB upper hard stop from entry — use it as soft filter only
#   B) Raise BB pct_b threshold (0.85 → 1.05 or remove entirely)
#   C) Use 60m RSI overbought check instead of BB to block "too late" entries
#   D) Decouple: run entry filter on 60m candle at 4h confirmation time, not
#      on current candle (not configurable via params, but we can approximate
#      by using 60m RSI thresholds that naturally exclude the overbought state)
#   E) Accept that some entries fire higher — widen entry RSI current_min and
#      use the rsi_overbought hard stop (e.g. min_value=58) as the only gate
# ═══════════════════════════════════════════════════════════════════════════

_SWING_BASE = {
    "strategy_type": "trend_following",
    "signal_timeframe": "60",
    "entry_timeframe": "60",
    "trend_timeframe": "240",
    "take_profit_pct": 5.0,
    "stop_loss_pct": 4.0,
    "trailing_stop_pct": 3,
    "arm_trailing_stop_pct": 2.5,
    "use_trailing_stop": True,
    "signal_cooldown_seconds": 3600,
    "min_signal_confidence": 75.0,
    "min_volume_ratio": 1.3,
    "use_trend_filter": True,
    "use_entry_filter": True,
    "max_position_hours": 72,
    "use_market_regime_filter": False,
    "trend_indicators": [
        {"type": "rsi_reversal_momentum", "params": {
            "lookback_candles":    4,
            "oversold_threshold":  42,
            "current_min":         36,
            "min_jump":            2.5,
            "require_sustained":   False,
            "sustained_rise_mode": "net",
            "hard_stop":           True,
        }},
        {"type": "rsi_overbought", "params": {"min_value": 55, "hard_stop": True}},
    ],
    "min_indicators_required": 2,
    "entry_indicators": [
        {"type": "rsi_reversal_momentum", "params": {
            "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
            "oversold_threshold":  52,
            "current_min":         38,
            "min_jump":            3.0,
            "require_sustained":   False,
            "sustained_rise_mode": "net",
            "hard_stop":           True,
        }},
        # RSI overbought is the ONLY "too late" gate — not BB
        {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
        # Price vs EMA: wide allowance for post-crash EMA elevation
        {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
        # Volume: soft, no hard_stop
        {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1,"hard_stop":True}},

        # BB: lower band check only — confirms price was genuinely depressed
        # (not a hard stop — just a confidence indicator)
    ],
    "min_entry_indicators_required": 4,
}

SWING_VARIANTS = {
    "p3_base" : _SWING_BASE,

    # -------------------------------------------------------------------------
    # V15: RECALIBRATED — fires earlier on 240m, tighter TP/SL for grinding recovery
    #
    # Key changes from existing variants:
    # - lookback=4 on 240m (16h window) catches the dip faster than lookback=8
    # - current_min=34 (not 36) — recovery starts at 38-40 on 240m, need room
    # - require_sustained=False on 240m — 4h candles don't need consecutive rises
    # - TP 2.5% / SL 2.5% — this market moved <1% per candle; 4% TP is unrealistic
    # - 60m entry: simple RSI+pct_b gates, no rsi_reversal hard stop
    #   (the 60m already showing RSI 39-45 when 240m fires — reversal is confirmed)
    # -------------------------------------------------------------------------
    # "p3_v15_recal_tight_tp": {
    #     **_SWING_BASE,
    #     "take_profit_pct": 2.5,        # reduced from 4.0 — matches actual volatility
    #     "stop_loss_pct": 2.5,
    #     "trailing_stop_pct": 1.8,
    #     "arm_trailing_stop_pct": 1.2,  # arm early — the grind is slow
    #     "use_trailing_stop": True,
    #     "min_signal_confidence": 72.0, # slightly relaxed
    #     "trend_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles": 4,     # 16h window — catches current dip
    #             "oversold_threshold": 38,  # 240m RSI hit 36.5 (SOL), 35.0 (ETH)
    #             "current_min": 34,         # needs to be off extreme but not recovered
    #             "min_jump": 4.0,           # solid jump required on 4h candle
    #             "require_sustained": False, # 4h bars — one big candle is enough
    #             "hard_stop": True,
    #         }},
    #         {"type": "rsi_overbought", "params": {
    #             "min_value": 58,           # was 50 — RSI 50 is mid-recovery, not late
    #             "hard_stop": True,
    #         }},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         # 60m RSI: below 55 means still in recovery zone, not extended
    #         {"type": "rsi_overbought", "params": {"min_value": 55, "hard_stop": True}},
    #         # 60m BB: price in lower 70% of band — not chasing
    #         {"type": "bollinger_bands", "params": {
    #             "band": "upper", "mode": "pct_b",
    #             "max_pct_b": 0.70, "hard_stop": True,
    #         }},
    #         # Volume: soft — recovery candles have subdued volume
    #         {"type": "volume_spike", "params": {"min_ratio": 0.6, "max_ratio": 8.0}},
    #         # Price vs EMA: wide allowance — EMA lags in a crash recovery
    #         {"type": "price_vs_ema", "params": {
    #             "ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 5.0,
    #         }},
    #     ],
    #     "min_entry_indicators_required": 3,
    # },

    # -------------------------------------------------------------------------
    # V16: TRAILING STOP FOCUS — no fixed TP, let trailing stop manage the exit
    #
    # For grinding recoveries, a fixed TP often misses the eventual breakout.
    # BTC recovered from 30k to 38k in Feb — that's 26%. Even 5–8% would be
    # captured with a good trailing stop. Don't cap the upside with a fixed TP.
    #
    # Set TP very wide (8%) so it almost never hits, rely on trailing stop.
    # Arm trail early at 1.5% to lock in the small initial gains.
    # -------------------------------------------------------------------------
    # "p3_v16_trail_only": {
    #     **_SWING_BASE,
    #     "take_profit_pct": 8.0,        # effectively disabled — trailing stop does the work
    #     "stop_loss_pct": 3.0,          # initial hard SL
    #     "trailing_stop_pct": 2.0,
    #     "arm_trailing_stop_pct": 1.5,  # arm after 1.5% — protect any early gain
    #     "use_trailing_stop": True,
    #     "max_position_hours": 96,      # allow up to 4 days on the trade
    #     "min_signal_confidence": 72.0,
    #     "trend_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles": 4,
    #             "oversold_threshold": 38,
    #             "current_min": 34,
    #             "min_jump": 4.0,
    #             "require_sustained": False,
    #             "hard_stop": True,
    #         }},
    #         {"type": "rsi_overbought", "params": {"min_value": 58, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         {"type": "rsi_overbought", "params": {"min_value": 55, "hard_stop": True}},
    #         {"type": "bollinger_bands", "params": {
    #             "band": "upper", "mode": "pct_b",
    #             "max_pct_b": 0.75, "hard_stop": True,
    #         }},
    #         {"type": "volume_spike", "params": {"min_ratio": 0.6, "max_ratio": 8.0}},
    #         {"type": "price_vs_ema", "params": {
    #             "ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 5.0,
    #         }},
    #     ],
    #     "min_entry_indicators_required": 3,
    # },

    # -------------------------------------------------------------------------
    # V17: GRADUAL RECOVERY (SUI/ETH style) — for when 240m RSI grinds slowly
    # without a single large jump. Min_jump=2.5 catches the step-up pattern.
    # Uses lookback=6 to see the full 24h dip-and-recover arc.
    # -------------------------------------------------------------------------
    "p3_v1_gradual": {
        **_SWING_BASE,
        "take_profit_pct": 4,
        "stop_loss_pct": 3,
        "trailing_stop_pct": 1.8,
        "arm_trailing_stop_pct": 1.2,
        "use_trailing_stop": True,
        "min_signal_confidence": 70.0,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6,     # 24h — captures full slow-grind pattern
                "oversold_threshold": 36,  # SUI 240m hit 32.9
                "current_min": 34,
                "min_jump": 2.5,           # SUI only had 3.1 max jump across 4h candles
                "require_sustained": True,
                "sustained_rise_mode": "net",  # net allows dip-then-higher (ETH pattern)
                "hard_stop": True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 54, "hard_stop": True}},
            {"type": "bollinger_bands", "params": {
                "band": "upper", "mode": "pct_b",
                "max_pct_b": 0.88, "hard_stop": True,  # SUI was at 0.84 when base fired
            }},
            {"type": "volume_spike", "params": {"min_ratio": 0.5, "max_ratio": 8.0}},
            {"type": "price_vs_ema", "params": {
                "ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 5.0,
            }},
        ],
        "min_entry_indicators_required": 3,
    },
   
    "p3_v2_sustained": {
        **_SWING_BASE,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  42,
                "current_min":         36,
                "min_jump":            2.5,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 48, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
                "oversold_threshold":  52,
                "current_min":         38,
                "min_jump":            3.0,
                "require_sustained":   False,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            # RSI overbought is the ONLY "too late" gate — not BB
            {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
            # Price vs EMA: wide allowance for post-crash EMA elevation
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
            # Volume: soft, no hard_stop
            {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1,"hard_stop":True}},

            # BB: lower band check only — confirms price was genuinely depressed
            # (not a hard stop — just a confidence indicator)
        ],
        "min_entry_indicators_required": 4,
    },

    # -------------------------------------------------------------------------
    # V13: RAISED BB THRESHOLD + EXTENDED LOOKBACK
    #
    # Rather than removing BB entirely, raise the pct_b hard stop from 0.85
    # to 1.10 — price must actually be 10% above the BB upper to be blocked.
    # In a post-crash recovery this is the real "extended" zone. At pct_b 0.85–
    # 1.05 the price is just catching up to the mean, not truly overbought.
    #
    # Also: extend 60m rsi_reversal lookback to 15 candles (15 hours) to
    # reliably find the original crash event from across the 4h candle.
    # -------------------------------------------------------------------------
    "p3_v3_higher_low": {
        **_SWING_BASE,
        "take_profit_pct": 4,
        "stop_loss_pct": 3,
        "trailing_stop_pct": 1.8,
        "arm_trailing_stop_pct": 1.2,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  42,
                "current_min":         36,
                "min_jump":            2.5,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 48, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
                "oversold_threshold":  52,
                "current_min":         38,
                "min_jump":            3.0,
                "require_sustained":   False,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            # RSI overbought is the ONLY "too late" gate — not BB
            {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
            # Price vs EMA: wide allowance for post-crash EMA elevation
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
            # Volume: soft, no hard_stop
            {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1,"hard_stop":True}},
            {"type": "reversal_candle", "params": {"pattern": "higher_low", "require_bull": False, "max_drop_from_close_pct": 0.6}},
        
            # BB: lower band check only — confirms price was genuinely depressed
            # (not a hard stop — just a confidence indicator)
        ],
        "min_entry_indicators_required": 5
    },


    "p3_v4_ema50drop": {
        **_SWING_BASE,
        "take_profit_pct": 5,
        "stop_loss_pct": 3,
        "trailing_stop_pct": 2,
        "arm_trailing_stop_pct": 1.5,
        "use_trailing_stop": False,
        "min_signal_confidence": 70.0,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles": 6,     # 24h — captures full slow-grind pattern
                "oversold_threshold": 33,  # SUI 240m hit 32.9
                "current_min": 30,
                "min_jump": 2.5,           # SUI only had 3.1 max jump across 4h candles
                "require_sustained": False,
                "sustained_rise_mode": "net",  # net allows dip-then-higher (ETH pattern)
                "hard_stop": True,
            }},
            {"type": "price_extended_below_ema", "params": {
                "ema": 50, "min_gap_pct": -3.0, "max_gap_pct": -10.0,
            }},

            {"type": "rsi_overbought", "params": {"min_value": 56, "hard_stop": True}},
        ],
        "min_indicators_required": 3,
        "entry_indicators": [
            {"type": "rsi_overbought", "params": {"min_value": 60, "hard_stop": True}},
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,   # SOL fix: need to reach across 4h candle boundary
                "oversold_threshold":  45,
                "current_min":         33,
                "min_jump":            3.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "price_vs_ema", "params": {
                "ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 2.0,
            }},
        ],
        "min_entry_indicators_required": 3,
    },

    # -------------------------------------------------------------------------
    # V14: RSI-ONLY ENTRY GATE — the simplest possible version
    #
    # "p3_v3_bb_rsilower": {
    #     **_SWING_BASE,
    #     "trend_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    8,
    #             "oversold_threshold":  45,
    #             "current_min":         36,
    #             "min_jump":            3.0,
    #             "require_sustained":   True,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
    #             "oversold_threshold":  45,
    #             "current_min":         38,
    #             "min_jump":            3.0,
    #             "require_sustained":   True,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         # RSI overbought is the ONLY "too late" gate — not BB
    #         {"type": "rsi_overbought", "params": {"min_value": 45, "hard_stop": True}},
    #         # Price vs EMA: wide allowance for post-crash EMA elevation
    #         {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
    #         # Volume: soft, no hard_stop
    #         {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
    #         {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1}},

    #        # BB: lower band check only — confirms price was genuinely depressed
    #         # (not a hard stop — just a confidence indicator)
    #     ],
    #     "min_entry_indicators_required": 4,
    # },

    # -------------------------------------------------------------------------
    # V15: STAGGERED ENTRY WINDOW — two-phase design
    #
    # Phase 1 (early entry): fires quickly after 4h trend confirms. Looser
    # BB gate (1.05), lower current_min (38), only 2/4 needed.
    # Phase 2 (late entry): already covered by the cooldown — the cooldown
    # means it only fires once per hour anyway.
    #
    # Key insight for SOL: the entry window is 15:03–20:03. We want to enter
    # at 15:03–17:03 when pct_b is 0.36–0.86 (before it breaks the band).
    # The 4h trend confirms at ~16:00–17:00. So we need the entry to fire
    # in the first 1–2 candles after 4h confirmation, before price pushes higher.
    #
    # This variant specifically targets that: requires the 60m rsi_reversal to
    # have a low current_min (confirms recent oversold on 60m) plus a BB that
    # is not yet extended (pct_b < 1.0 allows some band-walking).
    # -------------------------------------------------------------------------
    # "p3_v4_higherrsilevels": {
    #     **_SWING_BASE,
    #     "trend_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    8,
    #             "oversold_threshold":  48,
    #             "current_min":         36,
    #             "min_jump":            3.0,
    #             "require_sustained":   False,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         {"type": "rsi_overbought", "params": {"min_value": 55, "hard_stop": True}},
    #     ],
    #     "min_indicators_required": 2,
    #     "entry_indicators": [
    #         {"type": "rsi_reversal_momentum", "params": {
    #             "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
    #             "oversold_threshold":  52,
    #             "current_min":         38,
    #             "min_jump":            3.0,
    #             "require_sustained":   False,
    #             "sustained_rise_mode": "net",
    #             "hard_stop":           True,
    #         }},
    #         # RSI overbought is the ONLY "too late" gate — not BB
    #         {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
    #         # Price vs EMA: wide allowance for post-crash EMA elevation
    #         {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
    #         # Volume: soft, no hard_stop
    #         {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
    #         {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1,"hard_stop":True}},

    #        # BB: lower band check only — confirms price was genuinely depressed
    #         # (not a hard stop — just a confidence indicator)
    #     ],
    #     "min_entry_indicators_required": 4,
    # },

    # -------------------------------------------------------------------------
    # V16: SUI-SPECIFIC — fix the 4h trend gate for gradual recoveries
    #
    # SUI's problem is purely upstream — the 4h RSI reversal never passed
    # because RSI recovered too gradually (no single big jump, slow grind).
    # SUI's 60m entry would have been clean (pct_b 0.35–0.65, RSI 40–50).
    #
    # Fix: lower min_jump to 3.0 on trend filter AND use a 2-candle check
    # (min net rise across lookback rather than requiring a single-candle jump).
    # Also: accept oversold_threshold=33 to match SUI's bounce from RSI 26→35.
    #
    # Entry: SUI doesn't have the BB problem so keep a normal BB gate.
    # -------------------------------------------------------------------------
    "p3_v5_sustained_strict": {
        **_SWING_BASE,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    8,
                "oversold_threshold":  45,
                "current_min":         36,
                "min_jump":            3.0,
                "require_sustained":   False,
                "sustained_rise_mode": "strict",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    15,   # ~15 hours back — crosses the 4h candle boundary
                "oversold_threshold":  45,
                "current_min":         38,
                "min_jump":            3.0,
                "require_sustained":   False,
                "sustained_rise_mode": "strict",
                "hard_stop":           True,
            }},
            # RSI overbought is the ONLY "too late" gate — not BB
            {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
            # Price vs EMA: wide allowance for post-crash EMA elevation
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
            # Volume: soft, no hard_stop
            {"type": "volume_spike",   "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
            {"type": "bollinger_bands",   "params": {"band": "lower", "mode": "pct_b","max_pct_b":1.1,"hard_stop":True}},

           # BB: lower band check only — confirms price was genuinely depressed
            # (not a hard stop — just a confidence indicator)
        ],
        "min_entry_indicators_required": 4,
    },


    # -------------------------------------------------------------------------
    # V17: COMBINED — targets all four symbols simultaneously
    #
    # Synthesizes fixes for each failure mode into one variant:
    #   SOL: lookback_candles=20 on entry, BB upper at 1.0 (not 0.85)
    #   HYPE: same BB fix, RSI OB at 62 is the real gate
    #   ETH: oversold_threshold=32 on trend (ETH hit 30.9 not <30)
    #   SUI: min_jump=3.0 + net mode on trend filter
    #
    # This is the "production candidate" variant that should be backtested
    # across the full dataset. It's slightly more permissive than baseline
    # but uses RSI structure as the quality gate rather than price indicators.
    # -------------------------------------------------------------------------
    "p3_v17_unified_fix": {
        **_SWING_BASE,
        "min_signal_confidence": 76.0,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    8,
                "oversold_threshold":  35,   # ETH fix: was 30, ETH hit 30.9
                "current_min":         40,
                "min_jump":            3.5,  # SUI fix: was 5.0, now accepts gradual recovery
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            # No EMA slope. No vol spike. Both are post-crash lagging failures.
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    20,   # SOL fix: need to reach across 4h candle boundary
                "oversold_threshold":  30,
                "current_min":         38,
                "min_jump":            3.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            # RSI OB is the primary "too late" gate — replaces BB for that purpose
            {"type": "rsi_overbought",  "params": {"min_value": 62, "hard_stop": True}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 6.0}},
            # BB upper: raised to 1.0 — only block if price is ABOVE the band (SOL/HYPE fix)
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 1.0, "hard_stop": True}},
            # Volume: soft only
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 3,
    },

}


SWING_VARIANTS_OLD = {

    # -------------------------------------------------------------------------
    # V6: RSI-ONLY TREND GATE — remove both EMA slope AND volume from hard gates
    #
    # Core insight: after a crash, RSI reversal + "not overbought" IS the signal.
    # EMA slope and volume are both lagging/crash-candle indicators that are
    # structurally guaranteed to fail during the recovery window.
    #
    # This variant uses only 2 trend indicators (RSI reversal + RSI not OB) and
    # requires both (2/2). No EMA slope. No volume hard gate.
    # Volume is moved to a soft check on the entry side only.
    #
    # Addresses: ETH (never <30), HYPE (RSI 34.9, vol low), SOL/SUI (vol faded)
    # Risk: may fire in slow bleeds that look like RSI recovery but aren't.
    # Mitigation: require_sustained=True + net mode to filter choppy RSI patterns.
    # -------------------------------------------------------------------------
    "p3_v6_rsi_only_trend": {
        **_SWING_BASE,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    6,
                "oversold_threshold":  35,    # lowered: ETH hit 30.9, not <30
                "current_min":         36,    # reasonable recovery threshold
                "min_jump":            4.0,   # slightly lower than 5.0
                "require_sustained":   True,
                "sustained_rise_mode": "net", # allow dip-then-higher pattern
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            # No EMA slope. No volume spike. Both are hard-blocked in recovery.
        ],
        "min_indicators_required": 2,  # both must pass
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    10,
                "oversold_threshold":  35,
                "current_min":         40,
                "min_jump":            3.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 60, "hard_stop": True}},
            # Price vs EMA: wide gap allowed since EMA is elevated post-crash
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 3.0}},
            # Volume: soft gate, no hard_stop — acts as a confidence scorer
            {"type": "volume_spike",    "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.85, "hard_stop": True}},
        ],
        "min_entry_indicators_required": 3,  # need 3/5 (RSI + OB + at least one of price/vol/bb)
    },

    # -------------------------------------------------------------------------
    # V7: LOWER OVERSOLD + LOW VOLUME TOLERANT
    #
    # Specifically targets ETH-style crashes where RSI dips to 30–31 but NOT
    # below 30. The oversold_threshold is lowered to 32 and current_min is
    # widened. Volume spike min_ratio dropped to 1.3 with NO hard stop — it
    # contributes to confidence scoring but doesn't block.
    #
    # Key deltas from baseline:
    #   - oversold_threshold: 30 → 32  (catches ETH at 30.9)
    #   - volume hard stop: removed from trend filter
    #   - EMA slope: removed from trend filter
    #   - min_indicators_required: 2/3 (RSI reversal + RSI OB + vol as bonus)
    # -------------------------------------------------------------------------
    "p3_v7_low_oversold_no_vol_gate": {
        **_SWING_BASE,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    6,
                "oversold_threshold":  32,
                "current_min":         37,
                "min_jump":            4.5,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            # Volume kept but NOT a hard stop — soft signal contribution only
            {"type": "volume_spike",   "params": {"min_ratio": 1.3, "max_ratio": 10.0}},
        ],
        "min_indicators_required": 2,  # need RSI reversal + OB; vol is a bonus
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  33,
                "current_min":         40,
                "min_jump":            3.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 60, "hard_stop": True}},
            {"type": "price_vs_ema",   "params": {"ema": 20, "min_gap_pct": -8.0, "max_gap_pct": 4.0}},
            {"type": "volume_spike",   "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 3,
    },

    # -------------------------------------------------------------------------
    # V8: SPLIT TREND + ENTRY TIMEFRAMES — 240m trend is RSI-only, 60m entry
    #     uses a more complete filter including BB pct_b and price_vs_ema.
    #
    # Logic: the 240m trend filter's job is just to confirm "was this a real
    # dip and is it recovering?" — RSI alone handles that. The 60m entry filter
    # then does the heavy lifting to time the actual entry.
    #
    # This gives you a cleaner separation of concerns:
    #   240m: "Was there a real oversold event and is RSI recovering?" (2 checks)
    #   60m:  "Is this a good entry right now?" (4 checks, need 3)
    #
    # Lower confidence threshold since the trend check is lighter.
    # -------------------------------------------------------------------------
    "p3_v8_split_rsi_trend_full_entry": {
        **_SWING_BASE,
        "min_signal_confidence": 75.0,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    7,       # look back further for the dip
                "oversold_threshold":  32,
                "current_min":         36,
                "min_jump":            4.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            # 60m RSI must also confirm recovery
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  30,
                "current_min":         38,
                "min_jump":            3.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
            # Price must not be too far above or below EMA20 on 60m
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -7.0, "max_gap_pct": 3.0}},
            # BB: not extended to upside
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.85, "hard_stop": True}},
            # Volume on 60m — softer threshold since 60m vol normalized faster
            {"type": "volume_spike",    "params": {"min_ratio": 1.1, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,  # need 4/5 (RSI reversal + OB + 2 others)
    },

    # -------------------------------------------------------------------------
    # V9: GRADUAL RECOVERY MODE — for when the dip was moderate (RSI 30–35)
    #     and the recovery is slow/grinding (small vol, gradual RSI rise)
    #
    # ETH is the model here: RSI 30.9 at bottom, no single big jump, grinding
    # up from 30 to 38 over 12+ hours, vol 1.2–1.8x throughout.
    #
    # Key changes:
    #   - No require_sustained on trend (or use "net" with a lower min_jump)
    #   - min_jump reduced to 3.5 on 240m (was 5.0)
    #   - current_min: 34 (catches the grinding recovery from 30–34 range)
    #   - No EMA slope, no vol hard gate
    #   - TP/SL tighter (slower recovery = smaller move)
    # -------------------------------------------------------------------------
    "p3_v9_gradual_recovery": {
        **_SWING_BASE,
        "take_profit_pct": 3.5,      # more conservative — slow grinds have smaller TP
        "stop_loss_pct":   3.0,
        "trailing_stop_pct":     2.5,
        "arm_trailing_stop_pct": 2.0,
        "max_position_hours": 48,
        "min_signal_confidence": 74.0,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    8,       # look back 32h for the dip event
                "oversold_threshold":  33,      # catches ETH-style ~31 bottoms
                "current_min":         36,      # recovered to 36+ from sub-33
                "min_jump":            3.5,     # smaller jump ok for slow recoveries
                "require_sustained":   True,
                "sustained_rise_mode": "net",   # allow dip-then-higher pattern
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 62, "hard_stop": True}},
        ],
        "min_indicators_required": 2,
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    6,
                "oversold_threshold":  33,
                "current_min":         38,
                "min_jump":            2.5,     # very small jump OK — catching grinds
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought",  "params": {"min_value": 58, "hard_stop": True}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -10.0, "max_gap_pct": 2.0}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 6.0}},
        ],
        "min_entry_indicators_required": 3,
    },

    # -------------------------------------------------------------------------
    # V10: CRASH + VOL MEMORY — uses lookback to find the historical vol spike
    #      even if current vol has normalized.
    #
    # The crash vol spike (4–10x) happens at candle 0. By candle 2–3 of the
    # recovery, vol is back to 1.2–1.8x. This variant relaxes current vol
    # but adds a check that the LOOKBACK window contained a vol spike (i.e.,
    # the volume spike requirement is time-shifted to the lookback, not current).
    #
    # Implemented by: keeping volume_spike but not hard_stop + lower ratio,
    # combined with a deeper RSI lookback to capture the original spike event.
    # Also adds a bb pct_b lower band check — price should be near or below
    # the lower BB (classic oversold setup).
    # -------------------------------------------------------------------------
    "p3_v10_crash_memory": {
        **_SWING_BASE,
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    8,       # 32h lookback — finds the crash
                "oversold_threshold":  30,
                "current_min":         35,
                "min_jump":            5.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
            # Lower BB: price should be below or near BB lower band — confirms oversold
            {"type": "bollinger_bands", "params": {"band": "lower", "mode": "pct_b", "max_pct_b": 0.4, "hard_stop": False}},
            # Volume: soft, no hard stop — the spike happened earlier in the lookback
            {"type": "volume_spike",   "params": {"min_ratio": 1.2, "max_ratio": 10.0}},
        ],
        "min_indicators_required": 2,  # RSI reversal + OB are the two hard gates
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    6,
                "oversold_threshold":  32,
                "current_min":         38,
                "min_jump":            3.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought",  "params": {"min_value": 60, "hard_stop": True}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -9.0, "max_gap_pct": 3.0}},
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "max_pct_b": 0.85, "hard_stop": True}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.0, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 3,
    },

    # -------------------------------------------------------------------------
    # V11: ASYMMETRIC GATE — different rules for trend vs entry
    #
    # Trend (240m): VERY permissive — only needs RSI reversal to confirm dip
    #               happened and recovery started. Just 1 hard gate.
    # Entry (60m):  STRICT — must pass 4/5 checks to ensure good timing.
    #               This is where quality control happens, not at trend level.
    #
    # Rationale: the 240m trend filter is a blunt instrument that was blocking
    # too early. Move the sophistication to the entry filter which runs on
    # every bar anyway. The trend filter just asks "is a recovery underway?"
    # -------------------------------------------------------------------------
    "p3_v11_permissive_trend_strict_entry": {
        **_SWING_BASE,
        "min_signal_confidence": 80.0,  # raise confidence requirement to compensate
        "trend_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    8,
                "oversold_threshold":  32,
                "current_min":         35,
                "min_jump":            4.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought", "params": {"min_value": 65, "hard_stop": True}},
        ],
        "min_indicators_required": 2,   # both must pass, that's the only gate
        "entry_indicators": [
            {"type": "rsi_reversal_momentum", "params": {
                "lookback_candles":    5,
                "oversold_threshold":  33,
                "current_min":         42,  # stricter on 60m — must be further recovered
                "min_jump":            4.0,
                "require_sustained":   True,
                "sustained_rise_mode": "net",
                "hard_stop":           True,
            }},
            {"type": "rsi_overbought",  "params": {"min_value": 60, "hard_stop": True}},
            {"type": "price_vs_ema",    "params": {"ema": 20, "min_gap_pct": -7.0, "max_gap_pct": 3.0}},
            # Both BB checks — upper gate and confirmation price was near lower band
            {"type": "bollinger_bands", "params": {"band": "upper", "mode": "pct_b", "max_pct_b": 0.85, "hard_stop": True}},
            {"type": "volume_spike",    "params": {"min_ratio": 1.2, "max_ratio": 8.0}},
        ],
        "min_entry_indicators_required": 4,  # strict: 4/5
    },
}