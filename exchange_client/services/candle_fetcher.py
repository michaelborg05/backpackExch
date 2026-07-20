"""Programmatic candle fetcher — replaces (eventually) the TradingView webhook feed.

Why this exists: TradingView alerts only produce data forward from the moment
the alert is created. That is the binding constraint on every backtest
conclusion in this project — new symbols cannot be tested for weeks, and the
usable window is stuck around 60 days, which gives 8-trade validation halves.
An exchange REST feed gives multi-year history on demand.

Design notes that matter:

  * ROW CONVENTION. TrendAnalysisLog stores the OHLC of the *previous* (last
    closed) candle alongside indicators computed through it. This fetcher
    matches that convention exactly, so shadow rows line up bar-for-bar with
    webhook rows.

  * GAP HANDLING IS NOT OPTIONAL. RSI and ADX are Wilder recursions; a missing
    candle poisons them for many bars afterwards. Observed p95 ADX error on
    gappy data was 1.4-3.5%, and ADX gates at 22/25/30 — enough to flip a gate.
    fetch_klines() verifies contiguity and reports gaps rather than silently
    computing on a broken series.

  * WARMUP. Indicators are computed over a longer window than is written, so
    the recursions have converged before the first persisted row. Never write
    rows from inside the warmup region.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from services import indicators as ind

log = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com"

TF_TO_BINANCE = {"1": "1m", "5": "5m", "15": "15m", "30": "30m",
                 "60": "1h", "240": "4h", "1D": "1d"}
TF_MINUTES = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60, "240": 240, "1D": 1440}

# Backpack trades USDC pairs; we source candles from Binance USDT pairs.
#
# USDT over USDC, measured Jul 2026:
#   * volume 2-21x higher (SOL 11x, BNB 13x, PAXG 18x, ZEC 21x). This is the
#     one that matters — volume_spike >= 1.5 is a hard gate, and a thin USDC
#     book produces a noisier, spikier volume_ratio.
#   * history is materially longer (BTC/ETH 2017-08 vs 2018-12, APT 2022-10 vs
#     2024-04, PAXG 2020-08 vs 2025-04).
#   * the USDT/USDC basis is a near-constant -0.057% with 0.015-0.03% stdev,
#     and every indicator here is scale-invariant or ratio-based (RSI, ADX,
#     BB %B, price-vs-EMA gap %), so a constant offset changes nothing.
#
# NOT ON BINANCE (verified against exchangeInfo, neither USDT nor USDC):
#   HYPE — a live traded symbol. Needs another source (Bybit/OKX/Gate list it)
#          or must stay on its current TradingView feed.
#   MON  — dropped from the expansion shortlist for the same reason.
# Unmapped symbols raise rather than silently resolving to nothing.
# Quote asset used on Binance. Set BINANCE_QUOTE=USDC to mirror a TradingView
# feed that is still on USDC pairs — during a parallel run the shadow feed must
# use the SAME quote as TV, otherwise the -0.057% USDT/USDC basis shows up as
# drift in Tools/compare_shadow.py and masks the differences you actually care
# about. Switch to USDT once TV is switched.
def get_quote() -> str:
    """Quote asset to fetch against.

    Resolution order: DB setting `candle_fetcher_quote` -> BINANCE_QUOTE env ->
    "USDT". The DB comes first so it can be changed without a redeploy; the env
    var remains as a bootstrap for contexts with no DB (CLI backfills, tests).

    During a parallel run this MUST match the quote the TradingView feed uses —
    the USDT/USDC basis is only -0.057% on price, but volume_ratio differs ~33%
    and flips the >=1.5 gate on ~13% of bars.
    """
    try:
        from cache.settings_cache import get_settings_cache
        cache = get_settings_cache()
        if cache is not None:
            v = cache.get("candle_fetcher_quote", default=None)
            if v and str(v).strip():
                return str(v).strip().upper()
    except Exception:  # noqa: BLE001 — never let config lookup break a fetch
        pass
    return os.getenv("BINANCE_QUOTE", "USDT").strip().upper()


# Base assets keyed by the internal Backpack symbol. The quote is appended at
# lookup time so the whole map follows get_quote().
SYMBOL_BASES: Dict[str, str] = {
    "BTC_USDC": "BTC",
    "ETH_USDC": "ETH",
    "SOL_USDC": "SOL",
    "XRP_USDC": "XRP",
    "BNB_USDC": "BNB",
    "ZEC_USDC": "ZEC",
    # expansion candidates (see Tools/check_market_depth.py)
    "SUI_USDC": "SUI",
    "DOGE_USDC": "DOGE",
    "JUP_USDC": "JUP",
    "APT_USDC": "APT",
    "SEI_USDC": "SEI",
    "PAXG_USDC": "PAXG",
}


def source_symbol_for(symbol: str) -> Optional[str]:
    """Internal symbol -> venue symbol, e.g. SOL_USDC -> SOLUSDT."""
    base = SYMBOL_BASES.get(symbol)
    return f"{base}{get_quote()}" if base else None


class _SymbolMap(dict):
    """Live view of SYMBOL_BASES resolved against the current quote.

    Behaves as a dict for membership tests and lookups, but re-resolves on each
    access so a settings change takes effect without a restart.
    """

    def __getitem__(self, key):
        v = source_symbol_for(key)
        if v is None:
            raise KeyError(key)
        return v

    def get(self, key, default=None):
        return source_symbol_for(key) or default

    def __contains__(self, key):
        return key in SYMBOL_BASES

    def __iter__(self):
        return iter(SYMBOL_BASES)

    def __len__(self):
        return len(SYMBOL_BASES)

    def keys(self):
        return SYMBOL_BASES.keys()

    def items(self):
        return ((k, source_symbol_for(k)) for k in SYMBOL_BASES)


SYMBOL_MAP: Dict[str, str] = _SymbolMap()

# Enough bars for the slowest recursion (ADX needs ~2x period, EMA50 needs 50,
# Wilder smoothing needs a few hundred to fully converge) plus margin.
WARMUP_BARS = 300


@dataclass
class Candle:
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class FetchReport:
    symbol: str
    timeframe: str
    requested: int = 0
    returned: int = 0          # rows computed for the window
    written: int = 0           # rows actually INSERTed (idempotent skips excluded)
    gaps: List[Tuple[datetime, datetime, int]] = field(default_factory=list)

    @property
    def contiguous(self) -> bool:
        return not self.gaps

    def describe(self) -> str:
        base = (f"{self.symbol}/{self.timeframe}: {self.returned} candles "
                f"({self.written} new)")
        if self.contiguous:
            return f"{base}, contiguous"
        missing = sum(n for _, _, n in self.gaps)
        return f"{base}, {len(self.gaps)} gap(s), {missing} bar(s) missing"


def _http_get(url: str, params: dict, retries: int = 4) -> list:
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": "candle-fetcher/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # noqa: BLE001 — transient network/rate-limit
            last = e
            sleep = 2 ** attempt
            log.warning("fetch failed (%s), retry %d/%d in %ds", e, attempt + 1, retries, sleep)
            time.sleep(sleep)
    raise RuntimeError(f"GET {full} failed after {retries} attempts: {last}")


def fetch_klines(symbol: str, timeframe: str, start: datetime, end: datetime,
                 source_symbol: Optional[str] = None) -> Tuple[List[Candle], FetchReport]:
    """Fetch contiguous klines for [start, end]. Reports gaps rather than hiding them."""
    interval = TF_TO_BINANCE.get(timeframe)
    if interval is None:
        raise ValueError(f"unsupported timeframe {timeframe!r}")
    src = source_symbol or SYMBOL_MAP.get(symbol)
    if not src:
        raise ValueError(f"no Binance symbol mapped for {symbol!r} — add it to SYMBOL_MAP")

    tf_min = TF_MINUTES[timeframe]
    candles: List[Candle] = []
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    while cursor < end_ms:
        batch = _http_get(f"{BINANCE_BASE}/api/v3/klines", {
            "symbol": src, "interval": interval,
            "startTime": cursor, "endTime": end_ms, "limit": 1000,
        })
        if not batch:
            break
        for k in batch:
            candles.append(Candle(
                open_time=datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
                open=float(k[1]), high=float(k[2]), low=float(k[3]),
                close=float(k[4]), volume=float(k[5]),
            ))
        nxt = batch[-1][0] + tf_min * 60 * 1000
        if nxt <= cursor:
            break
        cursor = nxt
        time.sleep(0.12)  # stay well inside Binance rate limits

    # Dedupe and order
    by_time = {c.open_time: c for c in candles}
    candles = [by_time[t] for t in sorted(by_time)]

    report = FetchReport(symbol=symbol, timeframe=timeframe,
                         requested=int((end - start).total_seconds() // 60 // tf_min),
                         returned=len(candles))
    step = timedelta(minutes=tf_min)
    for prev, cur in zip(candles, candles[1:]):
        delta = cur.open_time - prev.open_time
        if delta > step:
            missing = int(delta / step) - 1
            report.gaps.append((prev.open_time, cur.open_time, missing))
    return candles, report


def compute_rows(symbol: str, timeframe: str, candles: Sequence[Candle],
                 source: Optional[str] = None, source_symbol: Optional[str] = None,
                 warmup: int = WARMUP_BARS, is_backfill: bool = False) -> List[dict]:
    """Turn candles into TrendAnalysisLog-shaped rows.

    Row i carries the OHLC of candle i (the last CLOSED candle) and indicators
    computed through candle i — matching the webhook path's prev_candle
    convention. Rows inside the warmup region are dropped.
    """
    if len(candles) <= warmup + 5:
        return []

    times = [c.open_time for c in candles]
    o = [c.open for c in candles]
    h = [c.high for c in candles]
    lo = [c.low for c in candles]
    c_ = [c.close for c in candles]
    v = [c.volume for c in candles]

    ema20 = ind.ema(c_, 20)
    ema50 = ind.ema(c_, 50)
    rsi14 = ind.rsi(c_, 14)
    adx14 = ind.adx(h, lo, c_, 14)
    atrp = ind.atr_pct(h, lo, c_, 14)
    basis, upper, lower = ind.bollinger(c_, 20, 2.0)
    vwap = ind.vwap_session(times, h, lo, c_, v)
    vsma, vratio = ind.volume_metrics(v, 20)

    # Source carries the quote asset: a USDT-sourced bar and a USDC-sourced bar
    # for the same symbol/timeframe/timestamp are DIFFERENT observations and must
    # not collide on uq_trend_shadow_bar.
    source = source or f"binance:{get_quote()}"
    tf_min = TF_MINUTES[timeframe]

    # Drop the in-progress bar. Binance returns the current, unclosed candle as
    # the last element: its OHLC and volume are partial, which corrupts
    # volume_ratio (a hard gate) and every recursion seeded from it. Worse, the
    # idempotent insert means a partial bar written once is NEVER corrected when
    # the bar actually closes, so it must never be written in the first place.
    now_utc = datetime.now(timezone.utc)
    rows: List[dict] = []
    for i in range(warmup, len(candles)):
        bar_close = times[i] + timedelta(minutes=tf_min)
        if bar_close > now_utc:
            continue
        # Timestamp the row at the bar's CLOSE, which is when the webhook path
        # would have fired for that bar.
        rows.append({
            "symbol": symbol, "timeframe": timeframe,
            "timestamp": times[i] + timedelta(minutes=tf_min),
            "open": o[i], "high": h[i], "low": lo[i], "close": c_[i],
            "price": c_[i],
            "rsi": rsi14[i], "ema20": ema20[i], "ema50": ema50[i],
            "vwap": vwap[i],
            "bb_upper": upper[i], "bb_lower": lower[i], "bb_basis": basis[i],
            "volume": v[i], "volume_sma": vsma[i], "volume_ratio": vratio[i],
            "adx": adx14[i], "atr_pct": atrp[i],
            "source": source,
            "source_symbol": source_symbol or SYMBOL_MAP.get(symbol),
            "is_backfill": is_backfill,
        })
    return rows


def write_shadow_rows(db, rows: Sequence[dict]) -> int:
    """Upsert rows into trend_analysis_shadow. Idempotent on (sym, tf, ts, source)."""
    if not rows:
        return 0
    from sqlalchemy.dialects.postgresql import insert

    from db.models import TrendAnalysisShadow

    written = 0
    CHUNK = 500
    for i in range(0, len(rows), CHUNK):
        chunk = [r for r in rows[i:i + CHUNK] if r.get("rsi") is not None]
        if not chunk:
            continue
        stmt = insert(TrendAnalysisShadow).values(chunk)
        # DO UPDATE, not DO NOTHING. A bar can legitimately be re-fetched with
        # better data than the first write — most importantly if a partial
        # (in-progress) bar ever gets persisted, DO NOTHING would freeze it
        # permanently. With DO UPDATE, re-running a backfill over any window
        # repairs that window, so the table is self-healing.
        stmt = stmt.on_conflict_do_update(
            constraint="uq_trend_shadow_bar",
            set_={c: stmt.excluded[c] for c in (
                "open", "high", "low", "close", "price",
                "rsi", "ema20", "ema50", "vwap",
                "bb_upper", "bb_lower", "bb_basis",
                "volume", "volume_sma", "volume_ratio",
                "adx", "atr_pct", "source_symbol", "is_backfill",
            )},
        )
        res = db.execute(stmt.returning(TrendAnalysisShadow.id))
        written += len(res.fetchall())
    db.commit()
    return written


def fetch_and_store(db, symbol: str, timeframe: str, start: datetime, end: datetime,
                    source: Optional[str] = None, is_backfill: bool = False) -> FetchReport:
    """Fetch, compute and persist one symbol/timeframe. Returns the fetch report.

    `start` is extended backwards by the warmup so the first persisted row
    already has converged recursions.
    """
    tf_min = TF_MINUTES[timeframe]
    warm_start = start - timedelta(minutes=tf_min * WARMUP_BARS)
    candles, report = fetch_klines(symbol, timeframe, warm_start, end)
    if report.gaps:
        log.warning("GAPS — %s", report.describe())
    rows = compute_rows(symbol, timeframe, candles, source=source, is_backfill=is_backfill)
    rows = [r for r in rows if r["timestamp"] >= start]
    report.returned = len(rows)
    report.written = write_shadow_rows(db, rows)
    return report


# ===========================================================================
# 1-minute price path — intra-candle fill model
# ===========================================================================

def expand_bar_to_path(open_time: datetime, o: float, h: float, l: float, c: float
                       ) -> List[Tuple[float, float]]:
    """Expand one 1m OHLC bar into four (epoch_seconds, price) points.

    Order matters: it decides whether a stop or a target is deemed to hit first
    when a bar spans both. The standard conservative approximation walks toward
    the adverse extreme first:

        up bar   (close >= open):  O -> L -> H -> C
        down bar (close <  open):  O -> H -> L -> C

    For a long position that means the low is visited before the high inside an
    up bar, so a stop sitting between them triggers rather than the target. That
    is the pessimistic reading, which is the one worth having in a backtest.
    """
    base = open_time.timestamp()
    mid = (l, h) if c >= o else (h, l)
    return [(base, o), (base + 15, mid[0]), (base + 30, mid[1]), (base + 45, c)]


def fetch_and_store_paths(db, symbol: str, start: datetime, end: datetime,
                          source: Optional[str] = None) -> FetchReport:
    """Backfill 1m bars into price_path_shadow for [start, end]."""
    from sqlalchemy.dialects.postgresql import insert

    from db.models import PricePathShadow

    src = source or f"binance:{get_quote()}"
    candles, report = fetch_klines(symbol, "1", start, end)
    now_utc = datetime.now(timezone.utc)

    rows = [
        {"symbol": symbol, "timestamp": c.open_time, "open": c.open,
         "high": c.high, "low": c.low, "close": c.close, "source": src}
        for c in candles
        # never persist the in-progress bar (same hazard as compute_rows)
        if c.open_time + timedelta(minutes=1) <= now_utc
    ]
    report.returned = len(rows)

    written = 0
    CHUNK = 5000
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i + CHUNK]
        stmt = insert(PricePathShadow).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_price_path_bar",
            set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close")},
        )
        res = db.execute(stmt.returning(PricePathShadow.id))
        written += len(res.fetchall())
    db.commit()
    report.written = written
    return report
