# services/cache_warmup.py
"""
Cache warmup service that loads trend history from database on startup.
Replays historical trend data to rebuild RSI and EMA history in cache.
"""

from typing import List, Dict
from sqlalchemy.orm import Session
from cache.trend_cache import TrendCache, get_trend_cache
from db.crud_trend import (
    get_all_symbols_with_history,
    get_trend_history,
    load_trend_data_from_history
)
from utils.logging import log_manager

logger = log_manager.get_logger("CacheWarmup")


def warmup_trend_cache(db: Session, trend_cache: TrendCache = None) -> Dict[str, int]:
    """
    Warm up the trend cache by replaying stored trend history from database.
    This rebuilds the RSI and EMA history needed for slope calculations.
    
    Args:
        db: Database session
        trend_cache: Optional TrendCache instance (uses global if not provided)
        
    Returns:
        Dict with warmup statistics:
        {
            'symbols_loaded': int,
            'total_snapshots_replayed': int,
            'symbols': [{'symbol': str, 'timeframe': str, 'snapshots': int}]
        }
    """
    if trend_cache is None:
        trend_cache = get_trend_cache()
    
    logger.info("🔥 Starting trend cache warmup from database...")
    
    # Get all symbol/timeframe combinations that have history
    symbol_timeframes = get_all_symbols_with_history(db)
    
    if not symbol_timeframes:
        logger.info("ℹ️  No trend history found in database - cache will build organically")
        return {
            'symbols_loaded': 0,
            'total_snapshots_replayed': 0,
            'symbols': []
        }
    
    total_snapshots = 0
    warmup_stats = []
    
    # Process each symbol/timeframe
    for item in symbol_timeframes:
        symbol = item['symbol']
        timeframe = item['timeframe']
        
        # Get historical snapshots (oldest first for proper replay)
        history = get_trend_history(db, symbol, timeframe)
        
        if not history:
            continue
        
        # Replay each snapshot into the cache
        snapshot_count = 0
        for history_entry in history:
            # Convert database record back to TrendData
            trend_data = load_trend_data_from_history(history_entry)
            
            # Update cache (this rebuilds RSI/EMA history)
            trend_cache.update(trend_data, persist_to_db=False)
            snapshot_count += 1
        
        total_snapshots += snapshot_count
        warmup_stats.append({
            'symbol': symbol,
            'timeframe': timeframe,
            'snapshots': snapshot_count
        })
        
        logger.info(
            f"✅ Warmed up {symbol} ({timeframe}): "
            f"replayed {snapshot_count} snapshots"
        )
    
    logger.info(
        f"🔥 Cache warmup complete! "
        f"Loaded {len(symbol_timeframes)} symbol/timeframe combinations, "
        f"replayed {total_snapshots} total snapshots"
    )
    
    return {
        'symbols_loaded': len(symbol_timeframes),
        'total_snapshots_replayed': total_snapshots,
        'symbols': warmup_stats
    }


def warmup_specific_symbol(
    db: Session,
    symbol: str,
    timeframe: str,
    trend_cache: TrendCache = None
) -> int:
    """
    Warm up cache for a specific symbol/timeframe combination.
    Useful for targeted cache loading or testing.
    
    Args:
        db: Database session
        symbol: Trading symbol
        timeframe: Timeframe (e.g., '1h', '4h')
        trend_cache: Optional TrendCache instance
        
    Returns:
        Number of snapshots replayed
    """
    if trend_cache is None:
        trend_cache = get_trend_cache()
    
    logger.info(f"🔥 Warming up cache for {symbol} ({timeframe})...")
    
    # Get historical snapshots
    history = get_trend_history(db, symbol, timeframe)
    
    if not history:
        logger.warning(f"⚠️  No history found for {symbol} ({timeframe})")
        return 0
    
    # Replay snapshots
    for history_entry in history:
        trend_data = load_trend_data_from_history(history_entry)
        trend_cache.update(trend_data,persist_to_db=False)
    
    logger.info(
        f"✅ Warmed up {symbol} ({timeframe}): "
        f"replayed {len(history)} snapshots"
    )
    
    return len(history)


def get_warmup_summary(db: Session) -> Dict:
    """
    Get a summary of what data is available for cache warmup.
    Useful for debugging or monitoring.
    
    Args:
        db: Database session
        
    Returns:
        Dict with summary information
    """
    from db.crud_trend import get_trend_history_stats
    
    stats = get_trend_history_stats(db)
    
    summary = {
        'total_snapshots_available': stats['total_records'],
        'symbol_timeframes_count': len(stats['symbol_timeframe_breakdown']),
        'breakdown': stats['symbol_timeframe_breakdown']
    }
    
    return summary