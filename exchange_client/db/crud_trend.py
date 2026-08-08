# db/crud_trend.py
"""
CRUD operations for trend data.
Handles saving and loading trend data for cache warmup and analysis.
"""

from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from db.models import TrendAnalysisLog
from models.webhook import TrendData, PrevCandle, BollingerBands
from utils.logging import log_manager

logger = log_manager.get_logger("TrendCRUD")

# Rows per symbol/timeframe to replay on startup. Must cover the longest
# history any indicator reads, not just the longest EMA/RSI seed: TrendCache
# keeps 100 closed candles and distance_from_high reads up to lookback_bars of
# them. At the old value of 15 that gate had less history than its
# min(20, lookback_bars) threshold after every restart, and the indicator
# *passes* when short of history — so a hard-stop dip filter silently waved
# entries through for hours after each deploy (this app redeploys on every
# merge to main). 100 matches the cache cap, so a restart now starts primed.
WARMUP_ENTRIES = 100  # rows per symbol/timeframe to replay on startup


def get_trend_history(
    db: Session,
    symbol: str,
    timeframe: str,
    limit: int = WARMUP_ENTRIES,
) -> List[TrendAnalysisLog]:
    """
    Retrieve the last N trend_analysis_log rows for a symbol/timeframe,
    ordered oldest-first so the cache can replay them in sequence.
    """
    # Fetch newest-first with limit, then reverse for oldest-first replay
    rows = (
        db.query(TrendAnalysisLog)
        .filter(
            TrendAnalysisLog.symbol == symbol,
            TrendAnalysisLog.timeframe == timeframe,
        )
        .order_by(desc(TrendAnalysisLog.timestamp))
        .limit(limit)
        .all()
    )
    rows.reverse()
    return rows


def get_all_symbols_with_history(db: Session) -> List[Dict[str, str]]:
    """
    Return all distinct symbol/timeframe pairs present in trend_analysis_log.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    results = (
        db.query(TrendAnalysisLog.symbol, TrendAnalysisLog.timeframe)
        .filter(TrendAnalysisLog.timestamp >= cutoff)
        .distinct()
        .all()
    )
    return [{'symbol': symbol, 'timeframe': timeframe} for symbol, timeframe in results]


def load_trend_data_from_history(row: TrendAnalysisLog) -> TrendData:
    """
    Reconstruct a TrendData object from a TrendAnalysisLog row.
    """
    prev_candle = PrevCandle(
        prev_open=row.open,
        prev_high=row.high,
        prev_low=row.low,
        prev_close=row.close,
    )
    bb = BollingerBands(
        bb_upper=row.bb_upper,
        bb_lower=row.bb_lower,
        bb_basis=row.bb_basis,
    )
    return TrendData(
        symbol=row.symbol,
        timeframe=row.timeframe,
        price=float(row.price) if row.price is not None else float(row.close or 0),
        rsi=float(row.rsi) if row.rsi is not None else 50.0,
        ema20=float(row.ema20) if row.ema20 is not None else float(row.close or 0),
        ema50=float(row.ema50) if row.ema50 is not None else float(row.close or 0),
        vwap=float(row.vwap) if row.vwap is not None else float(row.close or 0),
        volume=float(row.volume) if row.volume is not None else None,
        volume_sma=float(row.volume_sma) if row.volume_sma is not None else None,
        volume_ratio=float(row.volume_ratio) if row.volume_ratio is not None else None,
        adx=float(row.adx) if row.adx is not None else None,
        timestamp=row.timestamp.timestamp() if row.timestamp else None,
        prev_candle=prev_candle,
        bb=bb,
        indicators_changed=True,
    )


def get_latest_trend_timestamp(db: Session, symbol: str, timeframe: str) -> Optional[datetime]:
    """Most recent bar timestamp already stored for a symbol/timeframe, or None."""
    return (
        db.query(func.max(TrendAnalysisLog.timestamp))
        .filter(
            TrendAnalysisLog.symbol == symbol,
            TrendAnalysisLog.timeframe == timeframe,
        )
        .scalar()
    )


def get_trend_rows_after(
    db: Session,
    symbol: str,
    timeframe: str,
    since: Optional[datetime],
    limit: int = 50,
) -> List[TrendAnalysisLog]:
    """Rows strictly newer than `since`, oldest-first — for replaying fresh bars
    into TrendCache after a candle fetcher cycle writes them.

    `since=None` (no prior cache state) falls back to the last WARMUP_ENTRIES
    rows, matching startup warmup behavior.
    """
    if since is None:
        return get_trend_history(db, symbol, timeframe, limit=WARMUP_ENTRIES)
    return (
        db.query(TrendAnalysisLog)
        .filter(
            TrendAnalysisLog.symbol == symbol,
            TrendAnalysisLog.timeframe == timeframe,
            TrendAnalysisLog.timestamp > since,
        )
        .order_by(TrendAnalysisLog.timestamp)
        .limit(limit)
        .all()
    )


def get_trend_history_stats(db: Session) -> Dict[str, Any]:
    """
    Return record counts per symbol/timeframe from trend_analysis_log.
    """
    total_records = db.query(TrendAnalysisLog).count()

    symbol_timeframe_counts = (
        db.query(
            TrendAnalysisLog.symbol,
            TrendAnalysisLog.timeframe,
            func.count(TrendAnalysisLog.id).label('count'),
        )
        .group_by(TrendAnalysisLog.symbol, TrendAnalysisLog.timeframe)
        .all()
    )

    return {
        'total_records': total_records,
        'symbol_timeframe_breakdown': [
            {'symbol': symbol, 'timeframe': timeframe, 'record_count': count}
            for symbol, timeframe, count in symbol_timeframe_counts
        ],
    }

def log_trend_for_analysis(db: Session, trend_data: TrendData, retention_hours: int = 72):
    """Saves a flat record for analysis and cleans up old data"""
    
    # Extract prev_candle and bb safe-guarding against missing data
    prev = getattr(trend_data, 'prev_candle', {})
    bb = getattr(trend_data, 'bb', {})

    new_log = TrendAnalysisLog(
        symbol=trend_data.symbol,
        timeframe=trend_data.timeframe,
        price=float(trend_data.price),
        open=getattr(prev, 'prev_open', None),
        high=getattr(prev, 'prev_high', None),
        low=getattr(prev, 'prev_low', None),
        close=getattr(prev, 'prev_close', None),
        rsi=float(trend_data.rsi),
        ema20=float(trend_data.ema20),
        ema50=float(trend_data.ema50),
        vwap=float(trend_data.vwap) if trend_data.vwap else None,
        bb_upper=getattr(bb,'bb_upper', None),
        bb_lower=getattr(bb,'bb_lower', None),
        bb_basis=getattr(bb,'bb_basis', None),
        volume=float(trend_data.volume) if trend_data.volume else None,
        volume_sma=float(trend_data.volume_sma) if trend_data.volume_sma else None,
        volume_ratio=float(trend_data.volume_ratio) if trend_data.volume_ratio else None,
        adx=float(trend_data.adx) if trend_data.adx else None,
        timestamp=datetime.fromtimestamp(trend_data.timestamp, tz=timezone.utc),
        source="webhook:tradingview",
    )
    
    db.add(new_log)
    
    db.commit()
    db.refresh(new_log)
