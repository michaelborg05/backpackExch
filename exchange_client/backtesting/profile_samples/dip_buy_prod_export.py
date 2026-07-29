# =============================================================================
# PROD EXPORT — dip_v5_rsi_reversal_trail and dip_v7_deep_dip_satellite
# =============================================================================
# Fully flattened, standalone dicts (no inheritance from _DIP_BUY_BASE / entry
# constants) for direct copy into your profile-creation flow — matching the
# same "paste the exported dict" format as prod_profiles.py.
#
# Differences from the backtest config (backtesting/profile_samples/
# dip_buy_variants.py) — everything else is identical:
#   - take_profit_pct / stop_loss_pct: backtest used 9999.0 as a sentinel for
#     "disabled" because BacktestEngine.run() does float(profile.tp/sl_pct)
#     unconditionally. The live schema (models/trading_profile.py) natively
#     supports None for both — that's the correct value here, not 9999.
#   - Added fields that don't exist on BacktestProfile at all: account_id,
#     trading_type, entry_order_mode, default_order_size_usdc,
#     max_position_size_pct, max_open_positions, risk_group, is_active.
#     Every value below marked "<<< FILL IN >>>" is a real decision only you
#     can make (which exchange account, how much capital, your risk cap) —
#     don't deploy with placeholder numbers.
#
# risk_group: both profiles share "dip_buy_family" so a RiskGroup row with
# max_positions_per_symbol=1 dedupes overlapping same-symbol holds (measured
# 22% of v7 trades / 69% of v5 trades overlap on the same symbol — see the
# comment on dip_v7_deep_dip_satellite in dip_buy_variants.py for the full
# analysis). Create that RiskGroup once via the RiskGroup API/model before
# activating either profile, or drop the risk_group key to let them run
# fully independent (will double up on the same coin sometimes).
# =============================================================================

DIP_V5_PROD = {
    "name": "dip_v5_rsi_reversal_trail",          # unique internal key
    "display_name": "Dip Buy — RSI Reversal + Trail",

    "account_id": None,        # <<< FILL IN >>> ExchangeAccount.id to trade under
    "trading_type": "shadow",  # <<< start here — flip to "rules_live" once you've watched it >>>
    "strategy_type": "mean_reversion",
    "market_type": "SPOT",

    "entry_order_mode": "maker_then_taker",
    "maker_timeout_sec": None,   # None = system default (45s)

    "take_profit_pct": None,     # no fixed target — exit is the logical reclaim / trailing stop
    "stop_loss_pct": None,       # no hard stop — MAE routinely -5..-10% before the bounce (measured)
    "use_trailing_stop": True,
    "arm_trailing_stop_pct": 4.0,
    "trailing_stop_pct": 2.0,

    "trend_timeframe": "1D",
    "entry_timeframe": "240",
    "exit_timeframe": "240",

    "use_trend_filter": True,
    "trend_indicators": [
        {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": 0, "hard_stop": True}},
    ],
    "min_indicators_required": 1,

    "use_entry_filter": True,
    "entry_indicators": [
        {"type": "rsi_reversal_momentum", "params": {
            "lookback_candles": 4, "oversold_threshold": 35, "current_min": 35,
            "min_jump": 6.0, "require_sustained": False, "sustained_rise_mode": "net",
            "hard_stop": True,
        }},
        {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -50, "hard_stop": True}},
    ],
    "min_entry_indicators_required": 2,

    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_position_age_for_trend_check": 0,
    "exit_indicators": [
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
        {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
    ],
    "min_exit_indicators_required": 1,

    "max_position_hours": 720,   # 30d safety timeout backstop
    "min_signal_confidence": 0.0,
    "min_volume_ratio": 0.0,
    "signal_cooldown_minutes": 1,

    "default_order_size_usdc": None,   # <<< FILL IN >>> per-trade size
    "max_position_size_pct": None,     # <<< FILL IN >>> cap as % of portfolio
    "max_open_positions": 1,           # per-symbol cap — MUST be 1: every backtested number
                                        # (PF, win rate, all quarterly figures) assumed exactly
                                        # one open position per symbol. >1 allows the entry to
                                        # re-fire on a symbol you're already in (pyramiding) —
                                        # untested here, don't enable without backtesting it first.
    "max_open_positions_per_profile": None,  # cross-symbol total — leave unset/high, do NOT set
                                              # to a small number: it pools across ALL symbols, not
                                              # per-symbol (this bug starved 3 of 4 coins earlier —
                                              # see dip_buy_variants.py's comment on _DIP_BUY_BASE)
    "risk_group": "dip_buy_family",
    "max_portfolio_exposure_pct": None,  # <<< FILL IN >>>

    "symbols": ["BTC_USDC", "ETH_USDC", "SOL_USDC", "XRP_USDC", "SUI_USDC", "SEI_USDC", "ZEC_USDC"],
    # BNB and DOGE excluded — measured PF 0.49x on BNB (2yr), DOGE too few
    # signals to judge (n=2). See "Deep Dive" section 1 for the per-symbol table.

    "is_active": True,
}

DIP_V7_PROD = {
    "name": "dip_v7_deep_dip_satellite",
    "display_name": "Dip Buy — Deep Dip Satellite",

    "account_id": None,        # <<< FILL IN >>>
    "trading_type": "shadow",  # <<< start here >>>
    "strategy_type": "mean_reversion",
    "market_type": "SPOT",

    "entry_order_mode": "maker_then_taker",
    "maker_timeout_sec": None,

    "take_profit_pct": None,
    "stop_loss_pct": None,     # worst measured trade -26% on real tick fills — SMALLER size than v5, not a tighter stop
    "use_trailing_stop": True,
    "arm_trailing_stop_pct": 4.0,
    "trailing_stop_pct": 2.0,

    "trend_timeframe": "1D",
    "entry_timeframe": "240",
    "exit_timeframe": "240",

    "use_trend_filter": True,
    "trend_indicators": [
        {"type": "price_vs_ema", "params": {"ema": 50, "min_gap_pct": 0, "hard_stop": True}},
    ],
    "min_indicators_required": 1,

    "use_entry_filter": True,
    "entry_indicators": [
        {"type": "distance_from_high", "params": {"lookback_bars": 42, "min_pct_below": 12.0, "max_pct_below": 30.0, "hard_stop": True}},
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 45, "hard_stop": True}},
    ],
    "min_entry_indicators_required": 2,

    "use_trend_invalidation_exit": True,
    "trend_invalidation_indicators": "exit",
    "min_position_age_for_trend_check": 0,
    "exit_indicators": [
        {"type": "rsi_overbought", "params": {"side": "long", "min_value": 55}},
        {"type": "price_extended_below_ema", "params": {"ema": 20, "min_gap_pct": -0.001, "max_gap_pct": -99}},
    ],
    "min_exit_indicators_required": 1,

    "max_position_hours": 720,
    "min_signal_confidence": 0.0,
    "min_volume_ratio": 0.0,
    "signal_cooldown_minutes": 1,

    "default_order_size_usdc": None,   # <<< FILL IN >>> — recommend smaller than v5's size
    "max_position_size_pct": None,     # <<< FILL IN >>>
    "max_open_positions": 1,           # per-symbol cap — MUST be 1, see dip_v5's comment above;
                                        # applies here too, v7 was validated single-position too
    "max_open_positions_per_profile": None,  # cross-symbol total — leave unset/high
    "risk_group": "dip_buy_family",
    "max_portfolio_exposure_pct": None,  # <<< FILL IN >>>

    "symbols": ["BTC_USDC", "ETH_USDC", "SOL_USDC", "XRP_USDC", "SUI_USDC", "SEI_USDC", "ZEC_USDC"],

    "is_active": True,
}
