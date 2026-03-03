#!/usr/bin/env python3
"""
backfill_adx.py
---------------
Backfills the `adx` column in the `trend_analysis_log` table by recalculating
ADX from the existing high / low / close candle data.

Matches TradingView's ta.dmi(14, 14) output exactly — uses Wilder smoothing
(RMA) with a simple-average seed, which is what Pine Script does internally.

Usage
-----
    # Dry run — shows what would be updated without writing anything
    python backfill_adx.py --dry-run

    # Live run — writes ADX values to the database
    python backfill_adx.py

    # Overwrite ALL rows, even ones that already have an ADX value
    python backfill_adx.py --overwrite

    # Only process specific symbol/timeframe combinations
    python backfill_adx.py --symbol ETH_USDC --timeframe 60
    python backfill_adx.py --symbol ETH_USDC  # all timeframes for ETH
    python backfill_adx.py --timeframe 60      # all symbols on 60m

    # Adjust ADX period (default 14, matches Pine script default)
    python backfill_adx.py --period 14

Notes
-----
- Rows in the warmup window (first 2*period-1 rows per symbol/timeframe group)
  will be left as NULL — there is not enough prior data to compute a valid ADX.
- The script is idempotent by default: rows that already have a non-NULL adx
  value are skipped unless --overwrite is passed.
- Rows with NULL high, low, or close are skipped and logged as warnings.
- Progress is printed per symbol/timeframe group so you can monitor large runs.
"""

import argparse
import sys
from typing import Optional
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Inline ADX calculation — no external TA library dependency
# Matches TradingView ta.dmi(period, period) / Pine's ta.rma() smoothing
# ---------------------------------------------------------------------------

def _calculate_adx_series(
    highs:  list[float],
    lows:   list[float],
    closes: list[float],
    period: int = 14,
) -> list[Optional[float]]:
    """
    Calculate ADX for a full price series using Wilder smoothing.

    Parameters
    ----------
    highs, lows, closes : lists of float, same length, ordered oldest → newest
    period              : ADX/DI lookback period (default 14)

    Returns
    -------
    List of floats (same length as inputs).
    Index 0 .. (2*period - 2) will be None (warmup).
    Index (2*period - 1) onward will be float ADX values.
    """
    n = len(highs)
    adx_start = 2 * period - 1  # first index that can have a valid ADX value

    if n < adx_start + 1:
        return [None] * n

    # ── Step 1: raw TR, +DM, -DM ────────────────────────────────────────────
    tr_raw  = [None]
    pdm_raw = [None]
    ndm_raw = [None]

    for i in range(1, n):
        h, l, c         = highs[i],   lows[i],   closes[i]
        ph, pl, pc      = highs[i-1], lows[i-1], closes[i-1]

        tr  = max(h - l, abs(h - pc), abs(l - pc))
        up   = h - ph
        down = pl - l

        pdm_raw.append(up   if (up   > down and up   > 0) else 0.0)
        ndm_raw.append(down if (down > up   and down > 0) else 0.0)
        tr_raw.append(tr)

    # ── Step 2: Wilder smoothing of TR, +DM, -DM ────────────────────────────
    # Seed = simple average of first `period` values (indices 1 .. period)
    k = 1.0 / period  # Wilder factor = 1/period

    atr_s = [None] * (period + 1)
    pdm_s = [None] * (period + 1)
    ndm_s = [None] * (period + 1)

    atr_s[period] = sum(tr_raw[1 : period + 1])
    pdm_s[period] = sum(pdm_raw[1 : period + 1])
    ndm_s[period] = sum(ndm_raw[1 : period + 1])

    for i in range(period + 1, n):
        atr_s.append(atr_s[-1] * (1 - k) + tr_raw[i]  * k)
        pdm_s.append(pdm_s[-1] * (1 - k) + pdm_raw[i] * k)
        ndm_s.append(ndm_s[-1] * (1 - k) + ndm_raw[i] * k)

    # ── Step 3: +DI, -DI, DX ────────────────────────────────────────────────
    dx = [None] * n

    for i in range(period, n):
        atr = atr_s[i]
        if not atr or atr == 0:
            continue
        pdi = 100.0 * pdm_s[i] / atr
        ndi = 100.0 * ndm_s[i] / atr
        di_sum = pdi + ndi
        dx[i]  = 100.0 * abs(pdi - ndi) / di_sum if di_sum > 0 else 0.0

    # ── Step 4: Wilder smooth DX → ADX ──────────────────────────────────────
    # Seed = simple average of DX values from index `period` .. `adx_start`
    dx_seed_slice = [dx[i] for i in range(period, adx_start + 1) if dx[i] is not None]

    if len(dx_seed_slice) < period:
        return [None] * n  # shouldn't happen given the length check above

    adx_values          = [None] * n
    adx_values[adx_start] = sum(dx_seed_slice) / period

    for i in range(adx_start + 1, n):
        if dx[i] is not None and adx_values[i - 1] is not None:
            adx_values[i] = adx_values[i - 1] * (1 - k) + dx[i] * k

    return adx_values


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _fetch_groups(session, symbol_filter, timeframe_filter):
    """Return distinct (symbol, timeframe) pairs to process."""
    from db.models import TrendAnalysisLog
    from sqlalchemy import distinct
    try:
        query = session.query(
            TrendAnalysisLog.symbol,
            TrendAnalysisLog.timeframe,
        ).distinct()

        if symbol_filter:
            query = query.filter(TrendAnalysisLog.symbol == symbol_filter)
        if timeframe_filter:
            query = query.filter(TrendAnalysisLog.timeframe == timeframe_filter)

        return query.all()
    except Exception as e:
        print (f"Error {e}")

def _fetch_rows(session, symbol, timeframe, overwrite):
    """
    Fetch rows for one symbol/timeframe, ordered oldest → newest.

    If overwrite=False, we still fetch ALL rows so the ADX series has
    the full history for Wilder smoothing — we just won't write back rows
    that already have a value.
    """
    from db.models import TrendAnalysisLog

    return (
        session.query(TrendAnalysisLog)
        .filter(
            TrendAnalysisLog.symbol    == symbol,
            TrendAnalysisLog.timeframe == timeframe,
        )
        .order_by(TrendAnalysisLog.timestamp.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# Main backfill logic
# ---------------------------------------------------------------------------

def backfill(
    dry_run:          bool = False,
    overwrite:        bool = False,
    period:           int  = 14,
    symbol_filter:    Optional[str] = None,
    timeframe_filter: Optional[str] = None,
):
    from sqlalchemy.orm import Session
    from db.utils import get_db_session          # adjust import path if needed

    with get_db_session() as db:
        try:
            groups = _fetch_groups(db, symbol_filter, timeframe_filter)

            if not groups:
                print("No symbol/timeframe combinations found — check your filters.")
                return

            print(f"Found {len(groups)} symbol/timeframe group(s) to process.")
            print(f"ADX period : {period}  |  Warmup rows needed : {2 * period - 1}")
            print(f"Mode       : {'DRY RUN (no writes)' if dry_run else 'LIVE'}")
            print(f"Overwrite  : {overwrite}")
            print()

            total_updated  = 0
            total_skipped  = 0
            total_null_row = 0

            for symbol, timeframe in groups:
                rows = _fetch_rows(db, symbol, timeframe, overwrite)

                if not rows:
                    print(f"  {symbol} ({timeframe}): no rows — skipping")
                    continue

                # ── Validate OHLC completeness ───────────────────────────────────
                valid_rows   = []
                invalid_rows = []
                for row in rows:
                    if row.high is None or row.low is None or row.close is None:
                        invalid_rows.append(row.id)
                    else:
                        valid_rows.append(row)

                if invalid_rows:
                    print(
                        f"  {symbol} ({timeframe}): WARNING — {len(invalid_rows)} row(s) "
                        f"with NULL high/low/close (IDs: {invalid_rows[:5]}"
                        f"{'...' if len(invalid_rows) > 5 else ''})"
                        f" — these will be skipped in the series."
                    )
                    total_null_row += len(invalid_rows)

                if len(valid_rows) < 2 * period - 1:
                    print(
                        f"  {symbol} ({timeframe}): only {len(valid_rows)} valid rows, "
                        f"need {2 * period - 1} for warmup — skipping entirely"
                    )
                    continue

                # ── Build price series from valid rows only ──────────────────────
                highs  = [float(r.high)  for r in valid_rows]
                lows   = [float(r.low)   for r in valid_rows]
                closes = [float(r.close) for r in valid_rows]

                adx_series = _calculate_adx_series(highs, lows, closes, period)

                # ── Write back ───────────────────────────────────────────────────
                group_updated = 0
                group_skipped = 0

                for i, row in enumerate(valid_rows):
                    adx_val = adx_series[i]

                    if adx_val is None:
                        # Still in warmup window — leave NULL
                        group_skipped += 1
                        continue

                    if row.adx is not None and not overwrite:
                        # Already has a value and we're not overwriting
                        group_skipped += 1
                        continue

                    if not dry_run:
                        row.adx = round(adx_val, 4)

                    group_updated += 1

                if not dry_run and group_updated > 0:
                    db.commit()

                total_updated  += group_updated
                total_skipped  += group_skipped

                warmup_count = sum(1 for v in adx_series if v is None)
                print(
                    f"  {symbol} ({timeframe}): "
                    f"{len(valid_rows)} valid rows | "
                    f"{warmup_count} warmup (NULL) | "
                    f"{group_updated} {'would update' if dry_run else 'updated'} | "
                    f"{group_skipped} skipped"
                )

            print()
            print("─" * 60)
            print(f"Total rows {'that would be' if dry_run else ''} updated : {total_updated}")
            print(f"Total rows skipped                  : {total_skipped}")
            print(f"Total rows with NULL OHLC           : {total_null_row}")

            if dry_run:
                print()
                print("DRY RUN — no changes written. Re-run without --dry-run to apply.")

        except Exception as e:
            print(f"\nERROR: {e}")
            raise



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill ADX values in trend_analysis_log from existing OHLC data."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be updated without writing to the database.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Recalculate and overwrite rows that already have an ADX value.",
    )
    parser.add_argument(
        "--period",
        type=int,
        default=14,
        help="ADX period (default: 14, matches TradingView default).",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Only process this symbol (e.g. ETH_USDC). Omit for all symbols.",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default=None,
        help="Only process this timeframe (e.g. 60). Omit for all timeframes.",
    )

    args = parser.parse_args()

    backfill(
        dry_run          = args.dry_run,
        overwrite        = args.overwrite,
        period           = args.period,
        symbol_filter    = args.symbol,
        timeframe_filter = args.timeframe,
    )