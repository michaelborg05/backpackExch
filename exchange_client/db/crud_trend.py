# db/crud_trend_history.py
"""
CRUD operations for TrendHistory table.
Handles saving and loading trend data for cache warmup.
"""

from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from db.models import TrendHistory, TrendAnalysisLog
from models.webhook import TrendData
from utils.logging import log_manager

logger = log_manager.get_logger("TrendHistoryCRUD")


def save_trend_snapshot(
    db: Session,
    trend_data: TrendData,
    max_entries_per_symbol: int = 5
) -> TrendHistory:
    """
    Save a trend snapshot to the database.
    Automatically manages retention - keeps only last N entries per symbol/timeframe.
    
    Args:
        db: Database session
        trend_data: TrendData object from webhook
        max_entries_per_symbol: Maximum snapshots to keep per symbol/timeframe (default 5)
        
    Returns:
        Created TrendHistory record
    """
    # Convert TrendData to JSON-serializable dict
    trend_dict = trend_data.model_dump()
    
    # Create record
    history_entry = TrendHistory(
        symbol=trend_data.symbol,
        timeframe=trend_data.timeframe,
        trend_data=trend_dict,
        price=float(trend_data.price),
        rsi=float(trend_data.rsi),
        ema20=float(trend_data.ema20),
        ema50=float(trend_data.ema50),
        vwap=float(trend_data.vwap) if trend_data.vwap else None,
        volume_ratio=float(trend_data.volume_ratio) if trend_data.volume_ratio else None,
        indicators_changed=getattr(trend_data, 'indicators_changed', True),
        data_timestamp=datetime.fromtimestamp(
            getattr(trend_data, 'timestamp', datetime.now(timezone.utc).timestamp()),
            tz=timezone.utc
        )
    )
    
    db.add(history_entry)
    db.commit()
    db.refresh(history_entry)
    
    # Clean up old entries (keep only last N)
    _cleanup_old_entries(
        db,
        symbol=trend_data.symbol,
        timeframe=trend_data.timeframe,
        max_entries=max_entries_per_symbol
    )
    
    logger.debug(
        f"Saved trend snapshot: {trend_data.symbol} ({trend_data.timeframe}) - "
        f"RSI: {trend_data.rsi:.1f}, Price: ${trend_data.price:.2f}"
    )
    
    return history_entry


def _cleanup_old_entries(
    db: Session,
    symbol: str,
    timeframe: str,
    max_entries: int
):
    """
    Remove old entries, keeping only the most recent N for this symbol/timeframe.
    
    Args:
        db: Database session
        symbol: Trading symbol
        timeframe: Timeframe (e.g., '1h', '4h')
        max_entries: Number of entries to keep
    """
    # Get all entries for this symbol/timeframe, ordered by newest first
    all_entries = (
        db.query(TrendHistory)
        .filter(
            TrendHistory.symbol == symbol,
            TrendHistory.timeframe == timeframe
        )
        .order_by(desc(TrendHistory.data_timestamp))
        .all()
    )
    
    # If we have more than max_entries, delete the oldest ones
    if len(all_entries) > max_entries:
        entries_to_delete = all_entries[max_entries:]
        for entry in entries_to_delete:
            db.delete(entry)
        
        db.commit()
        logger.debug(
            f"Cleaned up {len(entries_to_delete)} old entries for "
            f"{symbol} ({timeframe}), kept {max_entries} most recent"
        )


def get_trend_history(
    db: Session,
    symbol: str,
    timeframe: str,
    limit: Optional[int] = None
) -> List[TrendHistory]:
    """
    Retrieve trend history for a symbol/timeframe, ordered by timestamp (oldest first).
    
    Args:
        db: Database session
        symbol: Trading symbol
        timeframe: Timeframe (e.g., '1h', '4h')
        limit: Optional limit on number of records to return
        
    Returns:
        List of TrendHistory records, ordered oldest to newest
    """
    query = (
        db.query(TrendHistory)
        .filter(
            TrendHistory.symbol == symbol,
            TrendHistory.timeframe == timeframe
        )
        .order_by(TrendHistory.data_timestamp)  # Oldest first for replay
    )
    
    if limit:
        query = query.limit(limit)
    
    return query.all()


def get_all_symbols_with_history(db: Session) -> List[Dict[str, str]]:
    """
    Get all unique symbol/timeframe combinations that have saved history.
    
    Returns:
        List of dicts with 'symbol' and 'timeframe' keys
    """
    results = (
        db.query(TrendHistory.symbol, TrendHistory.timeframe)
        .distinct()
        .all()
    )
    
    return [{'symbol': symbol, 'timeframe': timeframe} for symbol, timeframe in results]


def load_trend_data_from_history(history_entry: TrendHistory) -> TrendData:
    """
    Convert a TrendHistory database record back into a TrendData object.
    """
    # Use the unpacking operator (**) to feed the dict directly into the model
    return TrendData(**history_entry.trend_data)

def get_latest_trend_snapshot(
    db: Session,
    symbol: str,
    timeframe: str
) -> Optional[TrendHistory]:
    """
    Get the most recent trend snapshot for a symbol/timeframe.
    
    Args:
        db: Database session
        symbol: Trading symbol
        timeframe: Timeframe
        
    Returns:
        Latest TrendHistory record or None if not found
    """
    return (
        db.query(TrendHistory)
        .filter(
            TrendHistory.symbol == symbol,
            TrendHistory.timeframe == timeframe
        )
        .order_by(desc(TrendHistory.data_timestamp))
        .first()
    )


def delete_trend_history(
    db: Session,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None
) -> int:
    """
    Delete trend history. Can delete all, or filter by symbol/timeframe.
    
    Args:
        db: Database session
        symbol: Optional symbol filter
        timeframe: Optional timeframe filter
        
    Returns:
        Number of records deleted
    """
    query = db.query(TrendHistory)
    
    if symbol:
        query = query.filter(TrendHistory.symbol == symbol)
    if timeframe:
        query = query.filter(TrendHistory.timeframe == timeframe)
    
    count = query.count()
    query.delete()
    db.commit()
    
    logger.info(f"Deleted {count} trend history records")
    return count


def get_trend_history_stats(db: Session) -> Dict[str, Any]:
    """
    Get statistics about stored trend history.
    
    Returns:
        Dict with stats about the trend history table
    """
    total_records = db.query(TrendHistory).count()
    
    symbol_timeframe_counts = (
        db.query(
            TrendHistory.symbol,
            TrendHistory.timeframe,
            func.count(TrendHistory.id).label('count')
        )
        .group_by(TrendHistory.symbol, TrendHistory.timeframe)
        .all()
    )
    
    return {
        'total_records': total_records,
        'symbol_timeframe_breakdown': [
            {
                'symbol': symbol,
                'timeframe': timeframe,
                'record_count': count
            }
            for symbol, timeframe, count in symbol_timeframe_counts
        ]
    }

def log_trend_for_analysis(db: Session, trend_data: TrendData, retention_hours: int = 72):
    """Saves a flat record for analysis and cleans up old data"""
    
    # Extract prev_candle and bb safe-guarding against missing data
    prev = getattr(trend_data, 'prev_candle', {})
    bb = getattr(trend_data, 'bb', {})

    new_log = TrendAnalysisLog(
        symbol=trend_data.symbol,
        timeframe=trend_data.timeframe,
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
        timestamp=datetime.fromtimestamp(trend_data.timestamp, tz=timezone.utc)
    )
    
    db.add(new_log)
    
    db.commit()
    db.refresh(new_log)
