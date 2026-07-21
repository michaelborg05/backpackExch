# Delta-Neutral Funding Harvest — Build Plan

*Drafted Jul 2026, after the trend + swing families were shown to be break-even
after fees over 2 years. This is a non-directional strategy: it does not predict
price. It collects the perpetual funding rate while holding an offsetting spot
position, so the net delta is ~0 and the P&L is the funding minus costs.*

## 1. The edge, honestly

Perpetual futures pay a **funding rate** periodically to keep the perp price
pegged to spot. When funding is **positive**, longs pay shorts. So:

```
LONG spot (Backpack)  +  SHORT perp (Bullet)   ->   collect funding, delta ~0
```

The position makes money from funding regardless of price direction. Spot gains
offset perp losses and vice-versa.

**This is an operations and risk-management game, not a signal game.** There is
no clever entry to discover — funding is a public number. The edge is captured
by *whoever manages the two legs and the risk well*, which rewards exactly what a
bot is good at: monitoring, fast rebalancing, unemotional unwinding.

### Economics you must respect

- **Cost to put the trade on and take it off ≈ 4 taker fills** (open spot, open
  perp, close spot, close perp). At ~0.13%/fill that is **~0.5% round-trip on the
  pair**, before basis slippage.
- **Funding at 10% APR ≈ 0.027%/day ≈ 0.0011%/hour.** To clear a 0.5% round-trip
  you must hold **~18 days** at 10% APR. At 30% APR, ~6 days.
- Therefore this is a **"enter only when funding is elevated and expected to
  persist, hold for days-to-weeks"** strategy. It is NOT high frequency. A
  handful of well-chosen positions a year beats churning.
- **Maker entries change this materially** — if both legs enter as maker (see
  `maker_execution_plan.md`), round-trip cost roughly halves and the hold time to
  break even halves with it. The two projects compound.

### The risks that actually kill this (rank order)

1. **Liquidation of the short perp leg on a price pump.** The two legs are on
   *different venues* — you cannot cross-margin. If price rips up, the Bullet
   perp short loses and can liquidate while the offsetting Backpack spot gain is
   stranded on Backpack. **Mitigation: low leverage (1x–2x max), and a margin
   monitor that tops up or de-risks the perp leg before liquidation.** This is
   the single most important piece of the whole build.
2. **Funding flips negative** — you start *paying*. Mitigation: monitor funding
   each interval; unwind (or flip) when the trailing funding turns unattractive
   net of the unwind cost.
3. **Basis risk.** Spot and perp prices diverge, especially on a smaller DEX.
   When you unwind, the basis may have moved against you. Mitigation: size for
   it, prefer liquid perps, track entry basis and exit when it is favourable.
4. **Legging risk.** You fill one leg and not the other → briefly directional.
   Mitigation: open the *less liquid* leg first (Bullet perp), confirm fill, then
   hedge on the more liquid leg (Backpack spot). Never leave a naked leg across a
   loop iteration.
5. **Venue / counterparty risk.** Funds sit on two venues (one CEX, one DEX).
   Size so a single-venue failure is survivable.

**If any of points 1–3 cannot be monitored reliably, do not run this live.** A
delta-neutral book that stops being monitored is a directional book with
leverage.

## 2. How it fits the current architecture

The plumbing is more ready than expected:

- `api_builders/factory.py::get_adapter(profile)` already returns a
  `BackpackAdapter` (spot) or `BulletAdapter` (perp) per profile.
- `BulletAdapter.get_funding_rate()` is **already implemented**
  (`api_builders/adapters/bullet.py:528`), and `utils/endpoints.py` has a
  `funding_rate` endpoint.
- Bullet `order_buy`/`order_sell` already support `reduce_only`, leverage, and
  on-chain TP/SL.
- Profiles already carry `market_type` (SPOT/PERP), `leverage_multiplier`, and
  link to an `ExchangeAccount` (which carries `exchange_type`).
- `risk_group` already links profiles that must share limits.

### Two profiles or one controller?

You intuited "a new strategy type + two linked profiles (spot & perp)." That is
half right. The recommendation:

**A new `strategy_type = "delta_neutral_funding"` owned by a SINGLE controller
profile that manages BOTH legs — not two independent profiles.**

Why not two independent profiles:
- The existing profile/signal machinery assumes each profile has its own entry
  signal, TP, SL, and trailing logic. A delta-neutral leg has *none of those* —
  it opens because funding is attractive and closes because funding is not, and
  the two legs must open/close **atomically and stay balanced**.
- Two independent profiles would each run their own exit logic and could unwind
  one leg without the other → instant naked directional exposure. That is the
  exact failure mode to avoid.

So: one controller profile, holding a reference to both accounts and both
symbols. Concretely, extend the profile with:

```
market_type            = "DELTA_NEUTRAL"          # or keep SPOT + a role flag
account_id             -> Backpack spot account    (the long leg)
hedge_account_id       -> Bullet perp account       (the short leg)   [NEW column]
hedge_symbol           -> e.g. SOL_USDC_PERP        [NEW, optional; default map]
target_leverage        = 1.0 - 2.0                  (reuse leverage_multiplier)
funding_entry_apr      = e.g. 12.0   (enter when trailing funding APR >= this)
funding_exit_apr       = e.g. 4.0    (unwind when it falls below this)
max_basis_pct          = e.g. 0.5    (skip/again exit if basis too wide)
margin_floor_pct       = e.g. 40     (top-up/de-risk perp margin above this)
```

`hedge_account_id` + `hedge_symbol` are the only new schema fields; everything
else reuses existing columns.

## 3. New components to build

### 3.1 `FundingCache` (cache/funding_cache.py)
Mirror the existing cache singletons. Polls `adapter.get_funding_rate()` per
tracked perp on an interval, stores current rate + a trailing average (e.g. 3-day
funding APR) + next funding time. This is the signal input.

### 3.2 `DeltaNeutralController` (services/delta_neutral_service.py)
A new service thread started from `main.py`, same pattern as
`CandleFetcherService`. Its loop, per delta-neutral profile:

1. **Read state**: does an open pair exist for this profile? (both legs, from
   `positions` filtered by profile + a `leg` tag).
2. **If flat and funding APR >= `funding_entry_apr` and basis <= `max_basis_pct`
   and no risk flags** → OPEN:
   - Open the perp SHORT on Bullet first (less liquid leg), at `target_leverage`.
   - Confirm fill. Then open the spot LONG on Backpack for the matched notional.
   - Record both legs with a shared `pair_id` so they are always closed together.
3. **If a pair is open** → MANAGE each loop:
   - Recompute net delta; rebalance if it drifts beyond a band (price moves
     change the perp's notional vs the spot).
   - Check perp margin ratio vs `margin_floor_pct`; top up collateral or reduce
     both legs if approaching liquidation.
   - Accrue/collect funding (Bullet pays into the perp account automatically;
     just track it).
4. **If open and funding APR < `funding_exit_apr` OR basis adverse OR risk flag**
   → UNWIND both legs atomically (close perp reduce_only, sell spot), record P&L
   = funding collected + basis move − fees.

Keep every leg mutation **idempotent and crash-safe**: on restart, reconcile
actual venue positions against the `positions` table before acting. A controller
that double-opens after a restart is a real money bug.

### 3.3 Persistence
Reuse `positions` with two additions: `pair_id` (links the two legs) and `leg`
("spot_long" | "perp_short"). A small `funding_ledger` table (pair_id, timestamp,
funding_collected) makes P&L attribution honest.

### 3.4 Monitoring / safety
- Extend `HealthAlertingService` with a delta-neutral check: alert if net delta
  exceeds a band, if perp margin ratio is low, or if a leg is naked.
- A hard **kill-switch**: if only one leg is open for more than N seconds, either
  complete the hedge or flatten the open leg. Never sit naked.

## 4. Suggested build order (each independently testable)

1. **`FundingCache` + a read-only report** — poll funding on the perps you can
   trade, print trailing APR and current basis. **Ship nothing live.** Just watch
   for 2–4 weeks and confirm the funding is actually harvestable after modelled
   costs. This is the go/no-go gate; do it before building anything else.
2. **Backtest / paper the economics** — using historical funding (Bullet or a
   proxy like Binance funding) + spot/perp basis, simulate "enter at APR≥X, hold,
   exit at APR<Y" over 1–2 years. Confirm net-of-cost positive. This answers "is
   the edge real for the venues I use" before a line of execution code.
3. **Schema + controller skeleton** (no live orders) — reconcile state, compute
   signals, log intended actions. Run alongside prod in dry-run.
4. **Single-leg execution behind a flag** on tiny size — open+close one perp,
   one spot, confirm fills, fees, and the `positions`/ledger records.
5. **Full pair lifecycle on minimum size** — open both, hold, rebalance, unwind.
   Watch the margin monitor do its job through a real price move.
6. **Size up gradually**, only after the margin monitor and kill-switch have been
   exercised by real volatility.

## 5. Honest go / no-go

Build step 1 and 2 first and **stop there if the numbers do not clear costs on
the specific venues you use.** Bullet is a DEX; its funding, depth, and basis
behaviour must be measured, not assumed. If step-2 backtest is not clearly
positive net of a realistic 4-fill round trip, this is not worth the operational
risk of running two leveraged venues against each other.

The prize if it does clear: a positive-expectancy, non-directional return stream
uncorrelated to everything else you run — which is the thing the directional
work could never produce.
