# db/crud_monitored_symbols.py
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import delete
from db.models import MonitoredSymbol, SymbolConfig, TrendAnalysisLog
from utils.logging import log_manager

logger = log_manager.get_logger("MonitoredSymbols")


def get_all_monitored_symbols(db: Session) -> List[MonitoredSymbol]:
    return db.query(MonitoredSymbol).order_by(MonitoredSymbol.symbol).all()


def get_monitored_symbol(db: Session, symbol: str) -> Optional[MonitoredSymbol]:
    return db.query(MonitoredSymbol).filter(MonitoredSymbol.symbol == symbol).first()


def get_enabled_symbols_set(db: Session) -> set:
    """Return a set of enabled symbol strings — used for fast webhook gating."""
    rows = db.query(MonitoredSymbol.symbol).filter(MonitoredSymbol.enabled == True).all()
    return {r.symbol for r in rows}


def add_monitored_symbol(db: Session, symbol: str, enabled: bool = True) -> MonitoredSymbol:
    existing = get_monitored_symbol(db, symbol)
    if existing:
        return existing
    row = MonitoredSymbol(symbol=symbol, enabled=enabled)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def set_monitored_symbol_enabled(db: Session, symbol: str, enabled: bool) -> Optional[MonitoredSymbol]:
    row = get_monitored_symbol(db, symbol)
    if not row:
        return None
    row.enabled = enabled
    db.commit()
    db.refresh(row)
    return row


def delete_monitored_symbol(db: Session, symbol: str) -> dict:
    """
    Cascade delete a monitored symbol:
      1. Remove from symbol_configs (all profiles)
      2. Delete all trend_analysis_log rows for this symbol
      3. Evict from TrendCache
      4. Delete the monitored_symbols row

    Returns a summary of what was removed.
    """
    row = get_monitored_symbol(db, symbol)
    if not row:
        return {"deleted": False, "reason": "not_found"}

    # 1. Remove from all profile symbol_configs
    sc_result = db.execute(
        delete(SymbolConfig).where(SymbolConfig.symbol == symbol)
    )
    symbol_configs_removed = sc_result.rowcount

    # 2. Delete trend history
    tl_result = db.execute(
        delete(TrendAnalysisLog).where(TrendAnalysisLog.symbol == symbol)
    )
    trend_rows_removed = tl_result.rowcount

    # 3. Remove from monitored_symbols
    db.delete(row)
    db.commit()

    # 4. Evict from TrendCache and PriceCache
    try:
        from cache.trend_cache import get_trend_cache
        get_trend_cache().evict_symbol(symbol)
    except Exception as e:
        logger.warning(f"Could not evict {symbol} from TrendCache: {e}")

    try:
        from cache.price_cache import get_price_cache
        get_price_cache().remove_ticker(symbol)
    except Exception as e:
        logger.warning(f"Could not remove {symbol} from PriceCache: {e}")

    logger.info(
        f"Deleted monitored symbol {symbol}: "
        f"{symbol_configs_removed} symbol_config row(s), "
        f"{trend_rows_removed} trend log row(s) removed"
    )

    return {
        "deleted": True,
        "symbol": symbol,
        "symbol_configs_removed": symbol_configs_removed,
        "trend_rows_removed": trend_rows_removed,
    }
