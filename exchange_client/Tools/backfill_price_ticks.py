#!/usr/bin/env python3
"""
backfill_price_ticks.py
-----------------------
Backfills the `webhook_price_ticks` table with historical 1-minute close prices.

Pulls from Binance public klines API (no auth required) for deep history, then
optionally tops up with Backpack's own klines for the most recent period.

Symbol mapping:  SOL_USDC → SOLUSDT  (underscore → empty, USDC → USDT)

Usage
-----
    # Dry run — shows what would be inserted without writing
    python backfill_price_ticks.py --dry-run

    # Backfill last 30 days for all configured symbols
    python backfill_price_ticks.py --days 30

    # Backfill last 90 days for one symbol only
    python backfill_price_ticks.py --days 90 --symbol SOL_USDC

    # Backfill from a specific UTC date
    python backfill_price_ticks.py --from 2025-01-01

    # Use Backpack klines instead of Binance (shorter history, exact prices)
    python backfill_price_ticks.py --days 7 --source backpack

Notes
-----
- Binance returns up to 1000 candles per request; the script paginates automatically.
- Already-existing (symbol, timestamp) rows are skipped — safe to re-run.
- Binance rate limit is 1200 req/min; the script stays well under with a small sleep.
- HYPE_USDC and ZEC_USDC may not be listed on Binance — the script will warn and
  fall back to Backpack klines for those symbols automatically.
"""

import argparse
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import httpx as requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYMBOLS = [
    "SOL_USDC",
    "BTC_USDC",
    "HYPE_USDC",
    "BNB_USDC",
    "ETH_USDC",
    "XRP_USDC",
    "ZEC_USDC",
]

BINANCE_BASE = "https://api.binance.com"
BACKPACK_BASE = "https://api.backpack.exchange"

BINANCE_INTERVAL  = "1m"
BACKPACK_INTERVAL = "1m"
CANDLES_PER_PAGE  = 1000   # Binance max per request
SLEEP_BETWEEN_PAGES = 0.2  # seconds — keeps well under rate limit


def _bp_to_binance(symbol: str) -> str:
    """SOL_USDC → SOLUSDT"""
    return symbol.replace("_USDC", "USDT").replace("_", "")


# ---------------------------------------------------------------------------
# Binance helpers
# ---------------------------------------------------------------------------

def _fetch_binance_page(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    """
    Fetch up to CANDLES_PER_PAGE 1m klines from Binance.
    Returns list of dicts with keys: timestamp (datetime), price (Decimal).
    """
    binance_symbol = _bp_to_binance(symbol)
    url = (
        f"{BINANCE_BASE}/api/v3/klines"
        f"?symbol={binance_symbol}"
        f"&interval={BINANCE_INTERVAL}"
        f"&startTime={start_ms}"
        f"&endTime={end_ms}"
        f"&limit={CANDLES_PER_PAGE}"
    )
    resp = requests.get(url, timeout=15)

    if resp.status_code == 400:
        data = resp.json()
        # Symbol not found on Binance
        if data.get("code") == -1121:
            raise ValueError(f"Symbol {binance_symbol} not found on Binance")
        resp.raise_for_status()

    resp.raise_for_status()
    raw = resp.json()

    # Binance kline format: [open_time, open, high, low, close, volume, ...]
    ticks = []
    for candle in raw:
        open_time_ms = candle[0]
        close_price  = candle[4]
        ts = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
        ticks.append({"timestamp": ts, "price": Decimal(close_price)})

    return ticks


def fetch_binance(symbol: str, start: datetime, end: datetime) -> list[dict]:
    """Paginate through Binance klines for the full requested window."""
    all_ticks = []
    cursor_ms  = int(start.timestamp() * 1000)
    end_ms     = int(end.timestamp() * 1000)

    while cursor_ms < end_ms:
        page = _fetch_binance_page(symbol, cursor_ms, end_ms)
        if not page:
            break

        all_ticks.extend(page)
        # Advance cursor past the last candle we got
        last_ts_ms = int(page[-1]["timestamp"].timestamp() * 1000)
        cursor_ms  = last_ts_ms + 60_000  # +1 minute

        if len(page) < CANDLES_PER_PAGE:
            break  # we've reached the end

        time.sleep(SLEEP_BETWEEN_PAGES)

    return all_ticks


# ---------------------------------------------------------------------------
# Backpack helpers
# ---------------------------------------------------------------------------

def fetch_backpack(symbol: str, start: datetime, end: datetime) -> list[dict]:
    """Paginate through Backpack klines for the requested window."""
    all_ticks = []
    cursor_s   = int(start.timestamp())
    end_s      = int(end.timestamp())

    while cursor_s < end_s:
        url = (
            f"{BACKPACK_BASE}/api/v1/klines"
            f"?symbol={symbol}"
            f"&interval={BACKPACK_INTERVAL}"
            f"&startTime={cursor_s}"
            f"&limit=500"
        )
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        raw = resp.json()

        if not raw:
            break

        for candle in raw:
            start_val = candle.get("start") or candle[0]
            close     = candle.get("close") or candle[4]
            # Backpack returns datetime strings ("2026-06-17 11:34:00"), not epoch
            if isinstance(start_val, str) and not start_val.isdigit():
                ts = datetime.strptime(start_val, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            else:
                ts = datetime.fromtimestamp(int(start_val), tz=timezone.utc)
            if ts.timestamp() > end_s:
                break
            all_ticks.append({"timestamp": ts, "price": Decimal(str(close))})

        last_ts_s = int(all_ticks[-1]["timestamp"].timestamp()) if all_ticks else cursor_s
        cursor_s  = last_ts_s + 60

        if len(raw) < 500:
            break

        time.sleep(SLEEP_BETWEEN_PAGES)

    return all_ticks


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _existing_timestamps(db, symbol: str, start: datetime, end: datetime) -> set:
    from db.models import WebhookPriceTick
    rows = (
        db.query(WebhookPriceTick.timestamp)
        .filter(
            WebhookPriceTick.symbol    == symbol,
            WebhookPriceTick.timestamp >= start,
            WebhookPriceTick.timestamp <= end,
        )
        .all()
    )
    return {r.timestamp.replace(tzinfo=timezone.utc) if r.timestamp.tzinfo is None else r.timestamp for r in rows}


def _insert_batch(db, symbol: str, ticks: list[dict], existing: set, dry_run: bool) -> int:
    from db.models import WebhookPriceTick

    new_rows = []
    for tick in ticks:
        if tick["timestamp"] in existing:
            continue
        new_rows.append(WebhookPriceTick(
            symbol    = symbol,
            timestamp = tick["timestamp"],
            price     = tick["price"],
        ))

    if not dry_run and new_rows:
        db.bulk_save_objects(new_rows)
        db.commit()

    return len(new_rows)


# ---------------------------------------------------------------------------
# Main backfill
# ---------------------------------------------------------------------------

def backfill(
    days:          Optional[int]      = 30,
    from_date:     Optional[datetime] = None,
    symbol_filter: Optional[str]      = None,
    source:        str                = "binance",
    dry_run:       bool               = False,
):
    end   = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)
    start = from_date if from_date else (end - timedelta(days=days))

    symbols = [symbol_filter] if symbol_filter else SYMBOLS

    log.info(f"Range  : {start.isoformat()} → {end.isoformat()}")
    log.info(f"Symbols: {', '.join(symbols)}")
    log.info(f"Source : {source}")
    log.info(f"Mode   : {'DRY RUN' if dry_run else 'LIVE'}")
    log.info("")

    from db.utils import get_db_session

    total_inserted = 0

    with get_db_session() as db:
        for symbol in symbols:
            log.info(f"── {symbol} ──")

            ticks = []
            used_source = source

            if source == "binance":
                try:
                    ticks = fetch_binance(symbol, start, end)
                except ValueError as e:
                    log.warning(f"  Binance: {e} — falling back to Backpack")
                    used_source = "backpack"
                except Exception as e:
                    log.error(f"  Binance fetch failed: {e} — falling back to Backpack")
                    used_source = "backpack"

            if used_source == "backpack":
                try:
                    ticks = fetch_backpack(symbol, start, end)
                except Exception as e:
                    log.error(f"  Backpack fetch also failed: {e} — skipping {symbol}")
                    continue

            if not ticks:
                log.warning(f"  No candles returned — skipping")
                continue

            log.info(f"  Fetched {len(ticks):,} candles from {used_source}")

            existing = _existing_timestamps(db, symbol, start, end)
            log.info(f"  Already in DB: {len(existing):,} rows")

            inserted = _insert_batch(db, symbol, ticks, existing, dry_run)
            log.info(f"  {'Would insert' if dry_run else 'Inserted'}: {inserted:,} rows")

            total_inserted += inserted

    log.info("")
    log.info("─" * 50)
    log.info(f"Total {'would insert' if dry_run else 'inserted'}: {total_inserted:,} rows")
    if dry_run:
        log.info("DRY RUN — no changes written. Re-run without --dry-run to apply.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill webhook_price_ticks from Binance (or Backpack) 1m klines."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days back to fetch (default: 30). Ignored if --from is set.",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        type=str,
        default=None,
        help="Start date in UTC, e.g. 2025-01-01. Overrides --days.",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Only backfill this symbol (e.g. SOL_USDC). Omit for all.",
    )
    parser.add_argument(
        "--source",
        choices=["binance", "backpack"],
        default="binance",
        help="Price source (default: binance). Binance has deeper history.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be inserted without writing to the database.",
    )

    args = parser.parse_args()

    from_date = None
    if args.from_date:
        from_date = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    backfill(
        days          = args.days,
        from_date     = from_date,
        symbol_filter = args.symbol,
        source        = args.source,
        dry_run       = args.dry_run,
    )
