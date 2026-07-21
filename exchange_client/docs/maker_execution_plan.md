# Maker Execution — Build Plan

*Drafted Jul 2026. Across the 15m-trend and 4hr-swing families, the best
configs over 2 years land at roughly break-even AFTER fees. Break-even is
~0.0876%/trade gross; the best variants sit right on it. Switching entries from
taker to maker recovers ~0.03–0.07%/trade — enough to move the best profiles
from marginal-loss to marginal-profit. This is the single highest-value change
available and it does not require finding a better signal.*

## 1. Why this is worth doing before more signal work

- Backtests are GROSS (`taker_fee_pct` defaults to 0). At a ~0.13% taker
  round-trip, every trend variant is net-negative; the best swing profile
  (`p3_v11`, +0.051%/trade) is net-negative too.
- **Maker fees are lower (often a rebate).** Capturing the spread instead of
  paying it is worth roughly the entire remaining edge.
- The adverse-selection risk was **measured** (`Tools/measure_limit_fills.py`,
  435 entries): a limit resting **at the signal price** filled ~100% within
  15–30 min with **~0 adverse selection**. Crucially, **do not price-improve** —
  resting even 5bps below cost more in missed winners (+0.67% avg) than the fee
  saved. So the correct design is narrow and specific: post AT the signal price,
  short timeout, fall back to taker.

## 2. What already exists

The scaffolding is partly built — this is an extension, not a green field:

- `models/trade.py` and `models/webhook.py` already carry a `postOnly` field.
- `utils/constants.py` has `POST_ONLY_MODE` / `POST_ONLY_TAKER`; `utils/auth.py`
  documents the Backpack `OrderType` enum (`Limit`, `PostOnly`, …).
- `api_builders/adapters/base.py` defines `process_limit_order(order, position_id)`
  and both Backpack and Bullet adapters implement limit/IOC order paths.
- Entry currently goes through `MonitoringService._execute_signal()` ->
  `adapter.order_buy(...)`, which today places an aggressive (taker) order.

## 3. The design (deliberately narrow)

Add a **maker-first entry with taker fallback**, controlled per profile:

```
entry_order_mode   = "taker" | "maker_then_taker"   [NEW profile field, default taker]
maker_timeout_sec  = 90       (how long to rest before falling back)
maker_offset_bps   = 0        (MUST default 0 — resting at signal price; do NOT
                               expose price-improvement as a tunable without the
                               adverse-selection caveat front and centre)
```

Flow in `_execute_signal()` when `entry_order_mode == "maker_then_taker"`:

1. Compute the limit price = signal price (offset 0). Place a **PostOnly** limit
   via `adapter.process_limit_order(...)`.
2. Poll the order (reuse `_monitor_orders`) until filled or `maker_timeout_sec`.
3. **Filled** → record the position exactly as today, but tag the fill as maker
   (for fee attribution). Done.
4. **Not filled at timeout** → cancel, then place the existing market/taker order
   as fallback. Tag as taker.
5. **Partial fill** → decide policy up front: either top up the remainder as
   taker, or keep only the maker-filled size. Recommend: complete remainder as
   taker so position size matches intent.

Exits stay taker for now — stops must not miss. (A later phase can make TP a
maker order since it is not time-critical, but do not block the first ship on
it.)

## 4. Measurement — prove it, do not assume it

The whole point is fee capture, so instrument it:

- Add `fill_type` ("maker" | "taker" | "mixed") to the `trades`/`positions`
  record.
- Add a small report: maker fill rate, avg time-to-fill, and realised
  fee/trade, compared against the taker baseline. This directly confirms the
  ~0.03–0.07%/trade saving that makes the strategy families viable.
- Cross-check the live maker fill rate against the backtest assumption. The
  offline test used "price traded to the level" as the fill condition, which is
  an *upper bound* — real maker fill rate will be somewhat lower. If it is much
  lower than ~90%, revisit the timeout and the taker-fallback rate (too many
  fallbacks erodes the saving).

## 5. Build order

1. **Schema + config**: add `entry_order_mode`, `maker_timeout_sec`,
   `fill_type`. Default everything to current behaviour (taker) so deploying
   changes nothing until a profile opts in.
2. **Maker-first path in `_execute_signal`** behind the flag, using the existing
   `process_limit_order` + order polling. Taker fallback on timeout.
3. **Fee attribution + report** (section 4).
4. **Enable on ONE profile** (e.g. the best swing config) at small size; compare
   realised fee/trade and fill rate against the backtest.
5. **Roll out** to other profiles only after the live maker fill rate confirms
   the saving.

## 6. Risks / gotchas

- **Missed entries.** A maker order that never fills means a skipped trade. The
  adverse-selection test says the missed ones skew toward *winners*, so the
  taker fallback matters — do not run maker-only. Measure the fallback rate.
- **Do not expose price-improvement casually.** `maker_offset_bps > 0` looked
  attractive in one cut of the data and destroys the edge; keep the default 0
  and document why.
- **Exit safety unchanged.** Keep stops as taker. Never let maker logic touch the
  stop path.
- **Backpack PostOnly semantics.** Confirm a PostOnly that would cross the book
  is rejected (not silently converted to taker) — otherwise fee attribution
  lies. Verify against the live venue before trusting the report.

## 7. Relationship to the delta-neutral plan

These compound. If the delta-neutral funding harvest is built
(`delta_neutral_funding_plan.md`), maker entries on *both* legs roughly halve its
~0.5% round-trip cost and halve the hold time to break even. Build maker
execution first — it is lower-risk, self-contained, immediately useful to the
existing profiles, and a prerequisite for the funding harvest being attractive.
