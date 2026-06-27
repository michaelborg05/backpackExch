# db/crud_retention.py
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta, timezone
from typing import Dict


def delete_old_transaction_data(db: Session, cutoff: datetime) -> Dict[str, int]:
    """
    Delete orders, positions, trades, and ai_signal_log older than cutoff.
    Deletion order respects FK constraints:
      orders → positions, trades
      positions → trades, ai_signal_log
    """
    # 1. Orders reference positions and trades — delete first
    orders_deleted = db.execute(
        text("DELETE FROM orders WHERE created_at < :cutoff"),
        {"cutoff": cutoff}
    ).rowcount

    # 2. Positions reference trades and ai_signal_log — delete next
    positions_deleted = db.execute(
        text("DELETE FROM positions WHERE created_at < :cutoff"),
        {"cutoff": cutoff}
    ).rowcount

    # 3. Trades are now unreferenced for the old date range
    trades_deleted = db.execute(
        text("DELETE FROM trades WHERE created_at < :cutoff"),
        {"cutoff": cutoff}
    ).rowcount

    # 4. Null out ai_log_id on any newer positions still referencing old ai_signal_log rows
    db.execute(
        text("""
            UPDATE positions
            SET ai_log_id = NULL
            WHERE ai_log_id IN (
                SELECT id FROM ai_signal_log WHERE timestamp < :cutoff
            )
        """),
        {"cutoff": cutoff}
    )

    # 5. ai_signal_log is now safe to clean up
    ai_deleted = db.execute(
        text("DELETE FROM ai_signal_log WHERE timestamp < :cutoff"),
        {"cutoff": cutoff}
    ).rowcount

    db.commit()
    return {
        "orders": orders_deleted,
        "positions": positions_deleted,
        "trades": trades_deleted,
        "ai_signal_log": ai_deleted,
    }


def delete_old_trend_analysis(db: Session, cutoff: datetime) -> int:
    count = db.execute(
        text("DELETE FROM trend_analysis_log WHERE created_at < :cutoff"),
        {"cutoff": cutoff}
    ).rowcount
    db.commit()
    return count


def delete_old_webhook_price_ticks(db: Session, cutoff: datetime) -> int:
    count = db.execute(
        text("DELETE FROM webhook_price_ticks WHERE timestamp < :cutoff"),
        {"cutoff": cutoff}
    ).rowcount
    db.commit()
    return count


def delete_old_circuit_breaker_events(db: Session, cutoff: datetime) -> int:
    count = db.execute(
        text("DELETE FROM circuit_breaker_events WHERE triggered_at < :cutoff"),
        {"cutoff": cutoff}
    ).rowcount
    db.commit()
    return count


def delete_old_config_audit_log(db: Session, cutoff: datetime) -> int:
    count = db.execute(
        text("DELETE FROM config_audit_log WHERE changed_at < :cutoff"),
        {"cutoff": cutoff}
    ).rowcount
    db.commit()
    return count


def delete_old_daily_balance_snapshots(db: Session, cutoff: datetime) -> int:
    count = db.execute(
        text("DELETE FROM daily_balance_snapshots WHERE snapshot_date < :cutoff"),
        {"cutoff": cutoff}
    ).rowcount
    db.commit()
    return count


def run_all_retention(
    db: Session,
    retention_trans_history_days: int,
    retention_trenddata_history_days: int,
    retention_audit_history_days: int,
) -> Dict[str, int]:
    """Run all retention policies and return row counts deleted per table."""
    now = datetime.now(timezone.utc)

    transaction_cutoff = now - timedelta(days=retention_trans_history_days)
    trend_cutoff = now - timedelta(days=retention_trenddata_history_days)
    audit_cutoff = now - timedelta(days=retention_audit_history_days)

    results: Dict[str, int] = {}

    tx = delete_old_transaction_data(db, transaction_cutoff)
    results.update(tx)

    results["trend_analysis_log"] = delete_old_trend_analysis(db, trend_cutoff)
    results["webhook_price_ticks"] = delete_old_webhook_price_ticks(db, trend_cutoff)
    results["circuit_breaker_events"] = delete_old_circuit_breaker_events(db, audit_cutoff)
    results["config_audit_log"] = delete_old_config_audit_log(db, audit_cutoff)
    results["daily_balance_snapshots"] = delete_old_daily_balance_snapshots(db, audit_cutoff)

    return results
